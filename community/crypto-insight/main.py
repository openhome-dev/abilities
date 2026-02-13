import json
import os
from typing import Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

COINLORE_BASE = "https://api.coinlore.net"
COINLORE_TICKER_URL = f"{COINLORE_BASE}/api/ticker/"
COINLORE_MARKETS_URL = f"{COINLORE_BASE}/api/coin/markets/"
COINLORE_TICKERS_URL = f"{COINLORE_BASE}/api/tickers/"
COINLORE_SEARCH_PAGES = 50
COINLORE_PAGE_SIZE = 100

MATCHING_HOTWORDS = [
    "crypto insight",
    "crypto ai",
    "check crypto",
    "what's bitcoin doing",
    "crypto price",
    "check ethereum",
    "bitcoin price",
    "ethereum price",
    "what's the price on gold",
    "price of gold",
    "gold price",
    "just tell me the price",
    "tell me the price",
]


class CryptoAiCapability(MatchingCapability):
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
            matching_hotwords=data.get("matching_hotwords") or MATCHING_HOTWORDS,
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

    def _looks_like_trigger_echo(self, text: Optional[str]) -> bool:
        """If the first 'response' is the phrase that triggered the ability, ignore it."""
        if not text or not text.strip():
            return False
        lowered = text.lower().strip()
        if self.initial_request and lowered == self.initial_request.lower().strip():
            return True
        hotwords = self.matching_hotwords if self.matching_hotwords else []
        if hotwords and any(hw and hw.lower() in lowered for hw in hotwords):
            return True
        return False

    def _normalize_asset_with_llm(self, user_input: str) -> str:
        if not user_input or not user_input.strip():
            return "bitcoin"
        prompt = (
            "The user asked for a price or update on an asset. Reply with ONLY one word: the asset to search for. "
            "Examples: gold xauusd -> gold; xau usd -> gold; ethereum -> ethereum; dog coin -> dogecoin; "
            "btc -> bitcoin; sol -> solana; silver -> silver; tether gold -> gold. "
            "Output nothing else, just that one word in lowercase."
        )
        try:
            out = self.capability_worker.text_to_text_response(f"{prompt}\n\nUser said: {user_input.strip()}")
            if out and out.strip():
                term = out.strip().lower().split()[0].strip(".,;")
                if term:
                    self._log_info(f"[CryptoInsight] LLM normalized to: {term}")
                    return term
        except Exception as e:
            self._log_error(f"[CryptoInsight] LLM normalize error: {e}")
        words = [w.strip(".,;") for w in user_input.strip().lower().split() if len(w) > 1]
        return words[0] if words else "bitcoin"

    def _resolve_coinlore_id_dynamic(self, search_term: str) -> Optional[tuple]:
        if not search_term or not search_term.strip():
            return None
        q = search_term.lower().strip()
        try:
            for page in range(COINLORE_SEARCH_PAGES):
                start = page * COINLORE_PAGE_SIZE
                response = requests.get(
                    COINLORE_TICKERS_URL,
                    params={"start": start, "limit": COINLORE_PAGE_SIZE},
                    timeout=10
                )
                if response.status_code != 200:
                    continue
                data = response.json()
                items = data.get("data", [])
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

    def fetch_price_data(self, coinlore_id: str) -> Optional[Dict]:
        try:
            self._log_info(f"[CryptoInsight] Fetching price for CoinLore id: {coinlore_id}")
            response = requests.get(
                COINLORE_TICKER_URL,
                params={"id": coinlore_id},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    coin = data[0]
                    try:
                        price = float(coin.get("price_usd", 0))
                        change_str = coin.get("percent_change_24h") or "0"
                        change_24h = float(change_str)
                    except (TypeError, ValueError):
                        return None
                    return {"price": price, "change_24h": change_24h}
                return None
            elif response.status_code == 429:
                self._log_error("[CryptoInsight] CoinLore rate limited (429)")
                return {"price": None, "change_24h": None, "rate_limited": True}
            else:
                self._log_error(f"[CryptoInsight] CoinLore ticker returned {response.status_code}")
                return None
        except Exception as e:
            self._log_error(f"[CryptoInsight] Price fetch error: {e}")
            return None

    def fetch_ohlc_data(self, coinlore_id: str, days: int = 14) -> Optional[List[float]]:
        try:
            self._log_info(f"[CryptoInsight] Fetching chart data from CoinLore for id: {coinlore_id}")
            response = requests.get(
                COINLORE_MARKETS_URL,
                params={"id": coinlore_id},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if not isinstance(data, list) or len(data) == 0:
                    return None
                points = []
                for m in data:
                    try:
                        price = float(m.get("price_usd", 0))
                        ts = int(m.get("time", 0))
                        if price > 0 and ts > 0:
                            points.append((ts, price))
                    except (TypeError, ValueError):
                        continue
                points.sort(key=lambda x: x[0])
                closes = [p[1] for p in points]
                self._log_info(f"[CryptoInsight] Got {len(closes)} price points from CoinLore")
                return closes if len(closes) >= 7 else None
            elif response.status_code == 429:
                self._log_error("[CryptoInsight] CoinLore markets rate limited (429)")
                return None
            else:
                self._log_error(f"[CryptoInsight] CoinLore markets returned {response.status_code}")
                return None
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
        elif rsi > 70:
            return "overbought, suggesting a potential correction"
        else:
            return "neutral momentum"

    def interpret_trend(self, current_price: float, sma: float, period: int) -> str:
        if current_price > sma:
            pct_above = ((current_price - sma) / sma) * 100
            return f"above the {period}-day average by {pct_above:.1f}%, indicating bullish trend"
        else:
            pct_below = ((sma - current_price) / sma) * 100
            return f"below the {period}-day average by {pct_below:.1f}%, indicating bearish trend"

    def format_price(self, price: float) -> str:
        if price >= 1000:
            return f"${price:,.0f}"
        elif price >= 1:
            return f"${price:.2f}"
        elif price >= 0.01:
            return f"${price:.4f}"
        else:
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
            await self.worker.session_tasks.sleep(1.0)
        closes = self.fetch_ohlc_data(coinlore_id, days=14)

        price_str = self.format_price(current_price)
        change_str = self.format_change(change_24h)

        response_parts = [
            f"{display_name} is trading at {price_str}, {change_str} in 24 hours."
        ]

        if closes and len(closes) >= 15:
            rsi = self.calculate_rsi(closes, period=14)
            if rsi is not None:
                rsi_interpretation = self.interpret_rsi(rsi)
                response_parts.append(f"RSI is {rsi:.0f}, suggesting {rsi_interpretation}.")

        if closes and len(closes) >= 7:
            sma_7 = self.calculate_sma(closes, period=7)
            if sma_7 is not None:
                trend = self.interpret_trend(current_price, sma_7, period=7)
                response_parts.append(f"Price is {trend}.")

        return " ".join(response_parts)

    async def run(self):
        try:
            # Small delay so we don't consume the trigger phrase as the "asset" answer.
            if self.worker:
                await self.worker.session_tasks.sleep(0.2)
            prompt = "Which asset would you like to check? Say a cryptocurrency, gold, or symbol."
            user_input = await self.capability_worker.run_io_loop(prompt)
            if self._looks_like_trigger_echo(user_input):
                self._log_info("[CryptoInsight] Ignoring trigger-echo transcription")
                user_input = await self.capability_worker.run_io_loop(
                    "I didn't catch that. Say a cryptocurrency, gold, or symbol."
                )
            if not user_input or not user_input.strip():
                await self.capability_worker.speak("I didn't catch that. Defaulting to Bitcoin.")
                user_input = "bitcoin"
            search_term = self._normalize_asset_with_llm(user_input.strip())
            resolved = self._resolve_coinlore_id_dynamic(search_term)
            if not resolved:
                await self.capability_worker.speak(
                    f"I couldn't find '{search_term}' in the database. "
                    "Try Bitcoin, Ethereum, gold, or another cryptocurrency or gold-backed token."
                )
                return

            coinlore_id, display_name = resolved
            await self.capability_worker.speak(f"Let me check {display_name} for you.")
            analysis = await self.analyze_crypto(coinlore_id, display_name)
            if analysis:
                await self.capability_worker.speak(analysis)
            else:
                await self.capability_worker.speak(
                    f"Sorry, I couldn't get data for {display_name}. Try again in a moment."
                )

        except Exception as e:
            self._log_error(f"[CryptoInsight] Unexpected error: {e}")
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Sorry, something went wrong while checking crypto prices. Please try again."
                )
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()
