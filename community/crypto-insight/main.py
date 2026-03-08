import json
import os
import re
from typing import Dict, List, Optional, Tuple

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

COINLORE_BASE = "https://api.coinlore.net"
COINLORE_TICKER_URL = f"{COINLORE_BASE}/api/ticker/"
COINLORE_MARKETS_URL = f"{COINLORE_BASE}/api/coin/markets/"
COINLORE_TICKERS_URL = f"{COINLORE_BASE}/api/tickers/"
COINLORE_SEARCH_PAGES = 25
COINLORE_PAGE_SIZE = 100
COINLORE_SUGGESTION_PAGES = 8

MATCHING_HOTWORDS = [
    "crypto insight",
    "crypto ai",
    "check crypto",
    "crypto price",
    "market update",
    "bitcoin price",
    "ethereum price",
    "xrp price",
    "solana price",
    "dogecoin price",
    "gold price",
    "xauusd",
    "xau",
    "price of bitcoin",
    "price of ethereum",
    "price of gold",
    "what's the price",
    "what is the price",
    "how is bitcoin doing",
    "how is ethereum doing",
    "how is xrp doing",
    "how is gold doing",
    "rsi",
    "sma",
    "trend",
    "ticker",
    "quote",
]

DIRECT_WAKE_PHRASES = ("crypto insight", "crypto ai", "check crypto")

MARKET_HINT_WORDS = {
    "crypto", "cryptocurrency", "bitcoin", "btc", "ethereum", "eth", "xrp", "sol", "solana",
    "doge", "dogecoin", "gold", "xau", "xauusd", "price", "quote", "ticker", "market",
    "rsi", "sma", "trend", "trending", "overbought", "oversold",
}

ASSET_ALIASES = {
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "eth": "ethereum",
    "ripple": "xrp",
    "xrp": "xrp",
    "solana": "solana",
    "sol": "solana",
    "dogecoin": "dogecoin",
    "doge": "dogecoin",
    "gold": "gold",
    "xauusd": "gold",
    "xau usd": "gold",
    "xau": "gold",
}

ROUTER_PROMPT = (
    "Classify whether the user is asking about crypto or gold market data. "
    "Return ONLY valid JSON with exactly these keys: "
    '{"should_handle": true/false, "asset": "string", "intent": "price|analysis|unknown"}.\n'
    "Rules: should_handle=true only for crypto/gold price, quote, trend, rsi, sma, market update requests. "
    "If unclear asset, set asset=\"\". Use lowercase. Map xau/xauusd to gold."
)

NORMALIZER_PROMPT = (
    "Convert the user's market request into ONE lowercase asset word to search. "
    "Examples: btc->bitcoin, eth->ethereum, xauusd->gold, xau usd->gold, doge->dogecoin. "
    "Return only one word."
)

VOICE_FORMAT_PROMPT = (
    "Rewrite this market update for spoken voice output in 1 or 2 short sentences. "
    "Do not add facts. Do not change any numbers."
)

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave", "nothing"}
PREVIOUS_ASSET_WORDS = {"it", "that", "same", "same one", "that one", "this one"}
GENERIC_ASSET_WORDS = {"crypto", "coin", "coins", "market", "price", "token", "asset"}


class WewrwewCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    initial_request: Optional[str] = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.initial_request = None
        try:
            self.initial_request = worker.transcription
        except Exception:
            pass
        if not self.initial_request:
            try:
                self.initial_request = worker.last_transcription
            except Exception:
                pass
        if not self.initial_request:
            try:
                self.initial_request = worker.current_transcription
            except Exception:
                pass
        self.worker.session_tasks.create(self.run())

    def _log_info(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(msg)

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(msg)

    def _clean_json_object(self, raw: str) -> str:
        cleaned = (raw or "").strip().replace("```json", "").replace("```", "").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start:end + 1]
        return cleaned

    def _to_bool(self, value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return False

    def _best_initial_input(self) -> str:
        if self.initial_request and self.initial_request.strip():
            return self.initial_request.strip()
        try:
            history = self.worker.agent_memory.full_message_history or []
            for msg in reversed(history):
                role = str(msg.get("role", "")).lower()
                content = str(msg.get("content", "") or "").strip()
                if role == "user" and content:
                    return content
        except Exception:
            pass
        return ""

    def _looks_like_trigger_echo(self, text: Optional[str]) -> bool:
        if not text or not text.strip():
            return False
        lowered = text.lower().strip()
        initial = (self.initial_request or "").lower().strip()

        if initial and lowered == initial:
            if any(phrase in lowered for phrase in DIRECT_WAKE_PHRASES):
                return True
            if not self._looks_like_market_request(lowered):
                return True

        return False

    def _looks_like_market_request(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(word in lowered for word in MARKET_HINT_WORDS)

    def _is_exit(self, text: Optional[str]) -> bool:
        lowered = (text or "").lower().strip()
        if not lowered:
            return False
        return any(word in lowered for word in EXIT_WORDS)

    def _references_previous_asset(self, text: str) -> bool:
        lowered = (text or "").lower().strip()
        if not lowered:
            return False
        return any(f" {word} " in f" {lowered} " for word in PREVIOUS_ASSET_WORDS)

    def _extract_asset_alias(self, text: str) -> str:
        cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return ""
        for phrase in sorted(ASSET_ALIASES.keys(), key=len, reverse=True):
            pattern = rf"\b{re.escape(phrase)}\b"
            if re.search(pattern, cleaned):
                return ASSET_ALIASES[phrase]
        return ""

    def _route_request_with_llm(self, user_input: str) -> Dict[str, str]:
        route = {"should_handle": "false", "asset": "", "intent": "unknown"}
        if not user_input or not user_input.strip():
            return route
        try:
            raw = self.capability_worker.text_to_text_response(
                f"{ROUTER_PROMPT}\n\nUser said: {user_input.strip()}"
            )
            parsed = json.loads(self._clean_json_object(raw))
            should_handle = self._to_bool(parsed.get("should_handle", False))
            asset = str(parsed.get("asset", "") or "").strip().lower().split(" ")[0]
            if asset in GENERIC_ASSET_WORDS:
                asset = ""
            intent = str(parsed.get("intent", "unknown") or "unknown").strip().lower()
            if intent not in {"price", "analysis", "unknown"}:
                intent = "unknown"
            route = {
                "should_handle": "true" if should_handle else "false",
                "asset": asset,
                "intent": intent,
            }
            self._log_info(f"[CryptoInsight] LLM route: {route}")
        except Exception as e:
            self._log_error(f"[CryptoInsight] LLM route error: {e}")
        return route

    def _normalize_asset_with_llm(self, user_input: str) -> str:
        if not user_input or not user_input.strip():
            return ""
        try:
            raw = self.capability_worker.text_to_text_response(
                f"{NORMALIZER_PROMPT}\n\nUser said: {user_input.strip()}"
            )
            if raw and raw.strip():
                term = raw.strip().lower().split()[0].strip(".,;")
                if term:
                    self._log_info(f"[CryptoInsight] LLM normalized asset: {term}")
                    return term
        except Exception as e:
            self._log_error(f"[CryptoInsight] LLM normalize error: {e}")
        return ""

    def _resolve_coinlore_id_dynamic(self, search_term: str) -> Optional[Tuple[str, str]]:
        if not search_term or not search_term.strip():
            return None
        q = search_term.lower().strip()
        try:
            for page in range(COINLORE_SEARCH_PAGES):
                start = page * COINLORE_PAGE_SIZE
                response = requests.get(
                    COINLORE_TICKERS_URL,
                    params={"start": start, "limit": COINLORE_PAGE_SIZE},
                    timeout=10,
                )
                if response.status_code != 200:
                    continue
                items = response.json().get("data", [])
                if not items:
                    break
                for item in items:
                    nameid = (item.get("nameid") or "").lower()
                    name = (item.get("name") or "").lower()
                    symbol = (item.get("symbol") or "").lower()
                    if q in nameid or q in name or q == symbol or (len(q) > 1 and q in symbol):
                        cid = str(item.get("id", ""))
                        display = item.get("name") or item.get("symbol") or search_term
                        self._log_info(f"[CryptoInsight] Resolved '{search_term}' -> id={cid} name={display}")
                        return (cid, display)
            self._log_error(f"[CryptoInsight] No CoinLore match for: {search_term}")
            return None
        except Exception as e:
            self._log_error(f"[CryptoInsight] Dynamic resolve error: {e}")
            return None

    def _build_candidate_assets(self, text: str, preferred: str = "") -> List[str]:
        candidates: List[str] = []
        preferred_clean = (preferred or "").lower().strip()
        if preferred_clean and preferred_clean not in GENERIC_ASSET_WORDS:
            candidates.append(preferred_clean)
        alias = self._extract_asset_alias(text)
        if alias:
            candidates.append(alias)
        llm_asset = self._normalize_asset_with_llm(text)
        if llm_asset and llm_asset not in GENERIC_ASSET_WORDS:
            candidates.append(llm_asset)
        seen = set()
        unique: List[str] = []
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                unique.append(candidate)
        return unique

    def _resolve_from_text(self, text: str, preferred_asset: str = "") -> Tuple[Optional[Tuple[str, str]], str]:
        candidates = self._build_candidate_assets(text, preferred=preferred_asset)
        for candidate in candidates:
            resolved = self._resolve_coinlore_id_dynamic(candidate)
            if resolved:
                return resolved, candidate
        return None, (candidates[-1] if candidates else "")

    def _suggest_assets(self, search_term: str, limit: int = 3) -> List[str]:
        q = (search_term or "").lower().strip()
        if not q:
            return []
        suggestions: List[str] = []
        seen = set()
        try:
            for page in range(COINLORE_SUGGESTION_PAGES):
                response = requests.get(
                    COINLORE_TICKERS_URL,
                    params={"start": page * COINLORE_PAGE_SIZE, "limit": COINLORE_PAGE_SIZE},
                    timeout=10,
                )
                if response.status_code != 200:
                    continue
                items = response.json().get("data", [])
                if not items:
                    break
                for item in items:
                    name = str(item.get("name") or "")
                    symbol = str(item.get("symbol") or "")
                    hay = f"{name} {symbol} {item.get('nameid', '')}".lower()
                    if q in hay:
                        label = f"{name} ({symbol})" if name and symbol else (name or symbol)
                        if label and label not in seen:
                            seen.add(label)
                            suggestions.append(label)
                            if len(suggestions) >= limit:
                                return suggestions
            return suggestions
        except Exception as e:
            self._log_error(f"[CryptoInsight] Suggestion lookup error: {e}")
            return []

    def fetch_price_data(self, coinlore_id: str) -> Optional[Dict]:
        try:
            self._log_info(f"[CryptoInsight] Fetching price for CoinLore id: {coinlore_id}")
            response = requests.get(
                COINLORE_TICKER_URL,
                params={"id": coinlore_id},
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    coin = data[0]
                    try:
                        price = float(coin.get("price_usd", 0))
                        change_24h = float(coin.get("percent_change_24h") or "0")
                    except (TypeError, ValueError):
                        return None
                    return {"price": price, "change_24h": change_24h}
                return None
            if response.status_code == 429:
                self._log_error("[CryptoInsight] CoinLore ticker rate limited (429)")
                return {"price": None, "change_24h": None, "rate_limited": True}
            self._log_error(f"[CryptoInsight] CoinLore ticker returned {response.status_code}")
            return None
        except Exception as e:
            self._log_error(f"[CryptoInsight] Price fetch error: {e}")
            return None

    def fetch_ohlc_data(self, coinlore_id: str) -> Optional[List[float]]:
        try:
            self._log_info(f"[CryptoInsight] Fetching chart data from CoinLore for id: {coinlore_id}")
            response = requests.get(
                COINLORE_MARKETS_URL,
                params={"id": coinlore_id},
                timeout=10,
            )
            if response.status_code != 200:
                if response.status_code == 429:
                    self._log_error("[CryptoInsight] CoinLore markets rate limited (429)")
                else:
                    self._log_error(f"[CryptoInsight] CoinLore markets returned {response.status_code}")
                return None
            data = response.json()
            if not isinstance(data, list) or not data:
                return None
            points = []
            for market in data:
                try:
                    price = float(market.get("price_usd", 0))
                    ts = int(market.get("time", 0))
                    if price > 0 and ts > 0:
                        points.append((ts, price))
                except (TypeError, ValueError):
                    continue
            points.sort(key=lambda x: x[0])
            closes = [point[1] for point in points]
            self._log_info(f"[CryptoInsight] Got {len(closes)} price points from CoinLore")
            return closes if len(closes) >= 7 else None
        except Exception as e:
            self._log_error(f"[CryptoInsight] Chart data fetch error: {e}")
            return None

    def calculate_rsi(self, closes: List[float], period: int = 14) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        try:
            changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
            gains = [max(change, 0) for change in changes]
            losses = [max(-change, 0) for change in changes]
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            self._log_info(f"[CryptoInsight] RSI calculated: {rsi:.1f}")
            return rsi
        except Exception as e:
            self._log_error(f"[CryptoInsight] RSI calculation error: {e}")
            return None

    def calculate_sma(self, closes: List[float], period: int) -> Optional[float]:
        if len(closes) < period:
            return None
        try:
            sma = sum(closes[-period:]) / period
            self._log_info(f"[CryptoInsight] SMA-{period} calculated: {sma:.2f}")
            return sma
        except Exception as e:
            self._log_error(f"[CryptoInsight] SMA calculation error: {e}")
            return None

    def interpret_rsi(self, rsi: float) -> str:
        if rsi < 30:
            return "oversold, possibly indicating a buying opportunity"
        if rsi > 70:
            return "overbought, suggesting a potential correction"
        return "neutral momentum"

    def interpret_trend(self, current_price: float, sma: float, period: int) -> str:
        if current_price > sma:
            pct_above = ((current_price - sma) / sma) * 100
            return f"above the {period}-day average by {pct_above:.1f}%, indicating bullish trend"
        pct_below = ((sma - current_price) / sma) * 100
        return f"below the {period}-day average by {pct_below:.1f}%, indicating bearish trend"

    def format_price(self, price: float) -> str:
        if price >= 1000:
            return f"${price:,.0f}"
        if price >= 1:
            return f"${price:.2f}"
        if price >= 0.01:
            return f"${price:.4f}"
        return f"${price:.6f}"

    def format_change(self, change: float) -> str:
        direction = "up" if change > 0 else "down"
        return f"{direction} {abs(change):.1f}%"

    async def analyze_crypto(self, coinlore_id: str, display_name: str) -> Optional[str]:
        price_data = self.fetch_price_data(coinlore_id)
        if not price_data:
            return None
        if price_data.get("rate_limited"):
            return "CoinLore is rate limiting requests. Please try again in a minute."
        if price_data["price"] is None:
            return None

        current_price = price_data["price"]
        change_24h = price_data.get("change_24h") or 0

        if self.worker:
            await self.worker.session_tasks.sleep(0.4)

        closes = self.fetch_ohlc_data(coinlore_id)
        parts = [f"{display_name} is trading at {self.format_price(current_price)}, {self.format_change(change_24h)} in 24 hours."]

        if closes and len(closes) >= 15:
            rsi = self.calculate_rsi(closes, period=14)
            if rsi is not None:
                parts.append(f"RSI is {rsi:.0f}, suggesting {self.interpret_rsi(rsi)}.")

        if closes and len(closes) >= 7:
            sma_7 = self.calculate_sma(closes, period=7)
            if sma_7 is not None:
                parts.append(f"Price is {self.interpret_trend(current_price, sma_7, period=7)}.")

        return " ".join(parts)

    def _format_for_voice(self, user_input: str, analysis: str) -> str:
        if not analysis or not analysis.strip():
            return analysis
        try:
            raw = self.capability_worker.text_to_text_response(
                f"{VOICE_FORMAT_PROMPT}\n\nUser asked: {user_input}\nRaw analysis: {analysis}"
            )
            if raw and raw.strip():
                return raw.strip()
        except Exception as e:
            self._log_error(f"[CryptoInsight] Voice format error: {e}")
        return analysis

    async def _ask_for_asset(self, initial_input: str) -> str:
        if self.worker:
            await self.worker.session_tasks.sleep(0.2)

        if initial_input and any(phrase in initial_input.lower() for phrase in DIRECT_WAKE_PHRASES):
            prompt = "Sure. Which asset should I check?"
        elif initial_input and not self._looks_like_market_request(initial_input):
            prompt = "I handle live crypto and gold prices. Which asset do you want?"
        else:
            prompt = "Which asset would you like to check? Say a cryptocurrency, gold, or symbol."

        user_input = await self.capability_worker.run_io_loop(prompt)
        if self._looks_like_trigger_echo(user_input):
            self._log_info("[CryptoInsight] Ignoring trigger-echo transcription")
            user_input = await self.capability_worker.run_io_loop(
                "I didn't catch that. Tell me the asset, like bitcoin, ethereum, or gold."
            )

        if user_input and user_input.strip():
            return user_input.strip()
        return ""

    async def _ask_follow_up(self) -> str:
        follow_up = await self.capability_worker.run_io_loop(
            "Want another market update? You can ask another asset, or say stop."
        )
        return (follow_up or "").strip()

    async def _resolve_with_followup(self, failed_term: str) -> Optional[Tuple[str, str]]:
        suggestions = self._suggest_assets(failed_term, limit=3)
        if suggestions:
            await self.capability_worker.speak(
                f"I couldn't find '{failed_term}'. Try one of these: {', '.join(suggestions)}."
            )
        else:
            await self.capability_worker.speak(
                f"I couldn't find '{failed_term}'. Try Bitcoin, Ethereum, XRP, Solana, or gold."
            )

        retry_input = await self.capability_worker.run_io_loop(
            "Say another asset or symbol and I'll check it now."
        )
        if not retry_input or not retry_input.strip():
            return None

        resolved, _ = self._resolve_from_text(retry_input.strip())
        return resolved

    async def _resolve_query_turn(
        self,
        query_text: str,
        previous_resolved: Optional[Tuple[str, str]] = None,
    ) -> Tuple[Optional[Tuple[str, str]], str]:
        query = (query_text or "").strip()
        if not query:
            return None, ""

        route = self._route_request_with_llm(query)
        preferred_asset = route.get("asset", "")
        resolved, search_term = self._resolve_from_text(query, preferred_asset=preferred_asset)
        if resolved:
            return resolved, search_term

        if previous_resolved and self._references_previous_asset(query):
            return previous_resolved, previous_resolved[1]

        if not resolved and (route.get("should_handle") == "true" or self._looks_like_market_request(query)):
            resolved, search_term = self._resolve_from_text(query, preferred_asset=preferred_asset)
            if resolved:
                return resolved, search_term

        return None, search_term

    async def run(self):
        try:
            if self.worker:
                await self.worker.session_tasks.sleep(0.2)
            initial_input = self._best_initial_input()
            current_query = initial_input
            if not current_query:
                current_query = await self._ask_for_asset("")

            previous_resolved: Optional[Tuple[str, str]] = None
            turns_left = 3

            while turns_left > 0:
                turns_left -= 1
                if not current_query:
                    current_query = await self._ask_for_asset("")
                    if not current_query:
                        await self.capability_worker.speak("I didn't catch that. Try again when you're ready.")
                        break

                if self._is_exit(current_query):
                    await self.capability_worker.speak("Okay, signing off. Bye!")
                    break

                resolved, search_term = await self._resolve_query_turn(
                    current_query,
                    previous_resolved=previous_resolved,
                )

                if not resolved:
                    resolved = await self._resolve_with_followup(search_term or current_query or "that asset")
                    if not resolved:
                        await self.capability_worker.speak(
                            "I still couldn't resolve that symbol. Try a common one like bitcoin, ethereum, xrp, solana, or gold."
                        )
                        break

                coinlore_id, display_name = resolved
                previous_resolved = resolved
                await self.capability_worker.speak(f"Let me check {display_name} for you.")
                analysis = await self.analyze_crypto(coinlore_id, display_name)
                if not analysis:
                    await self.capability_worker.speak(
                        f"Sorry, I couldn't get data for {display_name}. Try again in a moment."
                    )
                else:
                    spoken = self._format_for_voice(current_query or display_name, analysis)
                    await self.capability_worker.speak(spoken)

                follow_up = await self._ask_follow_up()
                if not follow_up or self._is_exit(follow_up):
                    await self.capability_worker.speak("Okay, signing off. Bye!")
                    break
                current_query = follow_up
        except Exception as e:
            self._log_error(f"[CryptoInsight] Unexpected error: {e}")
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Sorry, something went wrong while checking crypto prices. Please try again."
                )
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()
