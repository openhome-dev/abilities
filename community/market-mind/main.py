import os
import re
import json
from typing import Dict, List, Optional, Tuple

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

try:
    from num2words import num2words as _n2w
    _HAS_NUM2WORDS = True
except ImportError:
    _HAS_NUM2WORDS = False

# ---------------------------------------------------------------------------
# TradingView Scanner endpoints (public, no API key required)
# ---------------------------------------------------------------------------
TV_SCAN_URLS = {
    "crypto": "https://scanner.tradingview.com/crypto/scan",
    "america": "https://scanner.tradingview.com/america/scan",
    "forex": "https://scanner.tradingview.com/forex/scan",
}

TV_COLUMNS_FULL = [
    "close", "change", "change|60", "change|240",
    "volume", "Value.Traded",
    "RSI", "RSI|60", "RSI|240",
    "MACD.macd", "MACD.signal",
    "EMA20", "EMA50", "EMA200",
    "SMA20", "SMA50", "SMA200",
    "Recommend.All", "Recommend.All|60", "Recommend.All|240",
    "ADX", "ATR",
    "BB.upper", "BB.lower",
    "Perf.W", "Perf.1M",
    "high", "low",
]

TV_COLUMNS_SCAN = [
    "name", "description", "close", "change", "volume",
    "RSI", "Recommend.All",
]

# ---------------------------------------------------------------------------
# Deterministic asset alias map  ->  (EXCHANGE:TICKER, scanner_key)
# ---------------------------------------------------------------------------
ASSET_MAP = {
    "bitcoin": ("BINANCE:BTCUSDT", "crypto"),
    "btc": ("BINANCE:BTCUSDT", "crypto"),
    "ethereum": ("BINANCE:ETHUSDT", "crypto"),
    "eth": ("BINANCE:ETHUSDT", "crypto"),
    "solana": ("BINANCE:SOLUSDT", "crypto"),
    "sol": ("BINANCE:SOLUSDT", "crypto"),
    "xrp": ("BINANCE:XRPUSDT", "crypto"),
    "ripple": ("BINANCE:XRPUSDT", "crypto"),
    "dogecoin": ("BINANCE:DOGEUSDT", "crypto"),
    "doge": ("BINANCE:DOGEUSDT", "crypto"),
    "cardano": ("BINANCE:ADAUSDT", "crypto"),
    "ada": ("BINANCE:ADAUSDT", "crypto"),
    "avalanche": ("BINANCE:AVAXUSDT", "crypto"),
    "avax": ("BINANCE:AVAXUSDT", "crypto"),
    "polygon": ("BINANCE:MATICUSDT", "crypto"),
    "matic": ("BINANCE:MATICUSDT", "crypto"),
    "chainlink": ("BINANCE:LINKUSDT", "crypto"),
    "link": ("BINANCE:LINKUSDT", "crypto"),
    "polkadot": ("BINANCE:DOTUSDT", "crypto"),
    "dot": ("BINANCE:DOTUSDT", "crypto"),
    "litecoin": ("BINANCE:LTCUSDT", "crypto"),
    "ltc": ("BINANCE:LTCUSDT", "crypto"),
    "apple": ("NASDAQ:AAPL", "america"),
    "aapl": ("NASDAQ:AAPL", "america"),
    "tesla": ("NASDAQ:TSLA", "america"),
    "tsla": ("NASDAQ:TSLA", "america"),
    "nvidia": ("NASDAQ:NVDA", "america"),
    "nvda": ("NASDAQ:NVDA", "america"),
    "microsoft": ("NASDAQ:MSFT", "america"),
    "msft": ("NASDAQ:MSFT", "america"),
    "amazon": ("NASDAQ:AMZN", "america"),
    "amzn": ("NASDAQ:AMZN", "america"),
    "google": ("NASDAQ:GOOGL", "america"),
    "googl": ("NASDAQ:GOOGL", "america"),
    "meta": ("NASDAQ:META", "america"),
    "amd": ("NASDAQ:AMD", "america"),
    "spy": ("AMEX:SPY", "america"),
    "spx": ("SP:SPX", "america"),
    "qqq": ("NASDAQ:QQQ", "america"),
    "gold": ("TVC:GOLD", "forex"),
    "xauusd": ("TVC:GOLD", "forex"),
    "xau": ("TVC:GOLD", "forex"),
    "silver": ("TVC:SILVER", "forex"),
    "xagusd": ("TVC:SILVER", "forex"),
    "eurusd": ("FX:EURUSD", "forex"),
    "gbpusd": ("FX:GBPUSD", "forex"),
    "usdjpy": ("FX:USDJPY", "forex"),
    "dxy": ("TVC:DXY", "forex"),
    "dollar": ("TVC:DXY", "forex"),
    "us10y": ("TVC:US10Y", "forex"),
}

WATCHLIST_FILE = "watchlist.json"
SNAPSHOT_FILE = "market_mind_snapshots.json"

# ---------------------------------------------------------------------------
# TTS Speech Normalization
# ---------------------------------------------------------------------------
_DIGIT_WORDS = {
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
    '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
}

_ONES = [
    '', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
    'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
    'sixteen', 'seventeen', 'eighteen', 'nineteen',
]
_TENS = [
    '', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy',
    'eighty', 'ninety',
]


def _int_to_words(n: int) -> str:
    """Convert an integer to English words."""
    if _HAS_NUM2WORDS:
        try:
            return _n2w(n)
        except Exception:
            pass
    if n < 0:
        return 'minus ' + _int_to_words(-n)
    if n == 0:
        return 'zero'
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + ('-' + _ONES[o] if o else '')
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES[h] + ' hundred' + (' ' + _int_to_words(r) if r else '')
    if n < 1_000_000:
        th, r = divmod(n, 1000)
        return _int_to_words(th) + ' thousand' + (' ' + _int_to_words(r) if r else '')
    if n < 1_000_000_000:
        m, r = divmod(n, 1_000_000)
        return _int_to_words(m) + ' million' + (' ' + _int_to_words(r) if r else '')
    if n < 1_000_000_000_000:
        b, r = divmod(n, 1_000_000_000)
        return _int_to_words(b) + ' billion' + (' ' + _int_to_words(r) if r else '')
    return str(n)


def _decimal_to_spoken(digits: str) -> str:
    """Convert decimal digits to individual spoken words: '034' -> 'zero three four'."""
    stripped = digits.rstrip('0') or '0'
    return ' '.join(_DIGIT_WORDS.get(d, d) for d in stripped)


def _number_to_spoken(num_str: str) -> str:
    """Convert a number string like '1234.56' to spoken form."""
    num_str = num_str.replace(',', '')
    if '.' in num_str:
        int_part, dec_part = num_str.split('.', 1)
        int_val = int(int_part) if int_part else 0
        dec_stripped = dec_part.rstrip('0')
        if not dec_stripped:
            return _int_to_words(int_val)
        return _int_to_words(int_val) + ' point ' + _decimal_to_spoken(dec_stripped)
    return _int_to_words(int(num_str))


def normalize_for_speech(text: str) -> str:
    """Convert numbers, currencies, percentages to spoken words for TTS."""

    # 1) Dollar amounts: $1,234.56  $85432  $0.0034
    def _dollar_repl(m):
        raw = m.group(1).replace(',', '')
        try:
            if '.' in raw:
                int_part, dec_part = raw.split('.', 1)
                int_val = int(int_part or '0')
                if len(dec_part) == 2:
                    cents = int(dec_part)
                    result = _int_to_words(int_val) + ' dollars'
                    if cents > 0:
                        result += ' and ' + _int_to_words(cents) + ' cents'
                    return result
                else:
                    return _number_to_spoken(raw) + ' dollars'
            else:
                return _int_to_words(int(raw)) + ' dollars'
        except Exception:
            return m.group(0)

    text = re.sub(r'\$(\d[\d,]*(?:\.\d+)?)', _dollar_repl, text)

    # 2) Signed percentages: +2.5%  -0.5%
    def _signed_pct_repl(m):
        sign = 'up ' if m.group(1) == '+' else 'down '
        return sign + _number_to_spoken(m.group(2)) + ' percent'

    text = re.sub(r'([+-])(\d[\d,]*(?:\.\d+)?)%', _signed_pct_repl, text)

    # 3) Unsigned percentages: 2.5%
    text = re.sub(
        r'(\d[\d,]*(?:\.\d+)?)%',
        lambda m: _number_to_spoken(m.group(1)) + ' percent',
        text,
    )

    # 4) R-multiples: 1R  2R  3R
    text = re.sub(
        r'\b(\d+)R\b',
        lambda m: _int_to_words(int(m.group(1))) + ' R',
        text,
    )

    # 5) Remaining standalone numbers: 65  1,234  10.50
    text = re.sub(
        r'\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\b',
        lambda m: _number_to_spoken(m.group(1)),
        text,
    )

    return text


# ---------------------------------------------------------------------------
# Intent routing — LLM-first, no rigid keyword gates
# ---------------------------------------------------------------------------
FALLBACK_EXIT_WORDS = {"stop", "exit", "quit", "bye", "goodbye"}

ROUTER_SYSTEM_PROMPT = (
    "You classify trading/finance voice commands. Return ONLY valid JSON.\n"
    "Keys: {\"intent\": \"ANALYZE|SCAN|BRIEF|WATCHLIST|RISK|EXIT\", "
    "\"asset\": \"<lowercase asset or empty>\", "
    "\"action\": \"add|remove|show|<empty>\"}\n"
    "Rules:\n"
    "- ANALYZE = user wants info, data, price, technicals, or any detail "
    "about a specific asset. This covers ANY phrasing: 'show me', 'tell me "
    "about', 'how is', 'pull up', 'give me', 'what about', 'look at', "
    "'run down on', 'status of', 'update on', etc.\n"
    "- SCAN = user wants to see market movers, top gainers/losers, "
    "what's hot, screener, or a broad market scan.\n"
    "- BRIEF = user wants a morning brief, daily summary, market overview, "
    "portfolio check, or recap.\n"
    "- WATCHLIST = user wants to add/remove/show items on their watchlist.\n"
    "- RISK = user wants position sizing, risk calculation, stop loss math, "
    "lot size, or risk-reward.\n"
    "- EXIT = user wants to stop, leave, end, quit, say goodbye, or is done "
    "with the conversation. Words like stop, exit, quit, done, bye, cancel, "
    "nothing, no thanks, that's all, I'm good, nevermind.\n"
    "- For WATCHLIST, set action to add/remove/show.\n"
    "- Map common names: btc=bitcoin, eth=ethereum, xau/xauusd=gold, "
    "doge=dogecoin, sol=solana. Keep asset lowercase.\n"
    "- When in doubt and the user mentions ANY asset name, default to ANALYZE.\n"
    "- Only use EXIT when the user clearly wants to end the conversation, "
    "not when they say 'no' as part of a longer sentence like "
    "'no check bitcoin instead'."
)

ANALYSIS_SYSTEM_PROMPT = (
    "You are a concise voice-first market analyst. "
    "Given raw indicator data, synthesize a 2-3 sentence spoken summary. "
    "State: current price and direction, momentum regime "
    "(overbought/oversold/neutral), trend vs key moving averages, "
    "and the TradingView recommendation. "
    "Use uncertainty language (likely, appears, suggests). "
    "Never give buy/sell signals. Keep it under 40 words. "
    "IMPORTANT: Write all numbers, prices, and percentages as spoken words. "
    "For example say 'eighty five thousand dollars' not '$85,000', "
    "and 'two point five percent' not '2.5%'."
)

BRIEF_SYSTEM_PROMPT = (
    "You are a market briefing anchor. Given data for multiple assets, "
    "deliver a concise spoken morning brief in 3-5 sentences. "
    "Highlight biggest movers, overall regime, and anything unusual. "
    "If snapshot deltas are provided, mention key changes. "
    "Keep it under 80 words. Use natural spoken phrasing. "
    "IMPORTANT: Write all numbers, prices, and percentages as spoken words. "
    "For example say 'eighty five thousand dollars' not '$85,000', "
    "and 'two point five percent' not '2.5%'."
)

ASSET_RESOLVER_PROMPT = (
    "The user mentioned an asset in a voice command. "
    "Return ONLY the lowercase common name or ticker symbol. "
    "Examples: 'how is bitcoin doing' -> bitcoin, "
    "'check nvda' -> nvda, 'gold price' -> gold, "
    "'what about the S and P' -> spy. "
    "Return one word only."
)


class MarketMindCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

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
        self._initial_input = None
        try:
            self._initial_input = worker.transcription
        except Exception:
            pass
        if not self._initial_input:
            try:
                self._initial_input = worker.last_transcription
            except Exception:
                pass
        self.worker.session_tasks.create(self.run())

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------
    def _log(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(f"[MarketMind] {msg}")

    def _log_err(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(f"[MarketMind] {msg}")

    # ------------------------------------------------------------------
    # TTS-safe speak wrapper
    # ------------------------------------------------------------------
    async def _speak(self, text: str):
        """Normalize numbers/symbols for TTS, then speak."""
        normalized = normalize_for_speech(text)
        self._log(f"Speaking (normalized): {normalized[:100]}...")
        await self.capability_worker.speak(normalized)

    # ------------------------------------------------------------------
    # JSON / LLM helpers
    # ------------------------------------------------------------------
    def _clean_json(self, raw: str) -> str:
        cleaned = (raw or "").replace("```json", "").replace("```", "").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start:end + 1]
        return cleaned

    def _llm(self, prompt: str, system: str = "", history: list = None) -> str:
        return self.capability_worker.text_to_text_response(
            prompt,
            history=history or [],
            system_prompt=system,
        )

    # ------------------------------------------------------------------
    # TradingView Scanner API
    # ------------------------------------------------------------------
    def _tv_fetch(self, ticker: str, scanner: str) -> Optional[Dict]:
        url = TV_SCAN_URLS.get(scanner)
        if not url:
            return None
        payload = {
            "symbols": {"tickers": [ticker]},
            "columns": TV_COLUMNS_FULL,
        }
        try:
            self._log(f"Fetching {ticker} from {scanner} scanner")
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                self._log_err(f"TV scanner returned {resp.status_code}")
                return None
            body = resp.json()
            rows = body.get("data", [])
            if not rows:
                return None
            values = rows[0].get("d", [])
            if len(values) != len(TV_COLUMNS_FULL):
                self._log_err(
                    f"Column mismatch: expected {len(TV_COLUMNS_FULL)}, "
                    f"got {len(values)}"
                )
                return None
            result = {}
            for i, col in enumerate(TV_COLUMNS_FULL):
                result[col] = values[i]
            result["_ticker"] = ticker
            result["_scanner"] = scanner
            self._log(f"Got data for {ticker}: price={result.get('close')}")
            return result
        except requests.exceptions.Timeout:
            self._log_err(f"Timeout fetching {ticker}")
            return None
        except Exception as e:
            self._log_err(f"TV fetch error: {e}")
            return None

    def _tv_scan_movers(
        self, scanner: str, limit: int = 5, order: str = "desc"
    ) -> List[Dict]:
        url = TV_SCAN_URLS.get(scanner)
        if not url:
            return []
        payload = {
            "columns": TV_COLUMNS_SCAN,
            "sort": {"sortBy": "change", "sortOrder": order},
            "range": [0, limit],
        }
        try:
            self._log(f"Scanning top movers on {scanner}")
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                self._log_err(f"TV scan returned {resp.status_code}")
                return []
            rows = resp.json().get("data", [])
            results = []
            for row in rows:
                vals = row.get("d", [])
                if len(vals) == len(TV_COLUMNS_SCAN):
                    entry = {}
                    for i, col in enumerate(TV_COLUMNS_SCAN):
                        entry[col] = vals[i]
                    entry["_ticker"] = row.get("s", "")
                    results.append(entry)
            return results
        except Exception as e:
            self._log_err(f"TV scan error: {e}")
            return []

    # ------------------------------------------------------------------
    # Asset resolution
    # ------------------------------------------------------------------
    def _resolve_asset(self, text: str) -> Optional[Tuple[str, str, str]]:
        """Returns (ticker, scanner, display_name) or None."""
        cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        for alias in sorted(ASSET_MAP.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", cleaned):
                ticker, scanner = ASSET_MAP[alias]
                display = alias.upper() if len(alias) <= 5 else alias.title()
                return (ticker, scanner, display)
        try:
            raw = self._llm(
                f"User said: {text}", system=ASSET_RESOLVER_PROMPT
            )
            word = raw.strip().lower().split()[0].strip(".,;:'\"")
            if word in ASSET_MAP:
                ticker, scanner = ASSET_MAP[word]
                display = word.upper() if len(word) <= 5 else word.title()
                return (ticker, scanner, display)
        except Exception as e:
            self._log_err(f"Asset resolver LLM error: {e}")
        return None

    # ------------------------------------------------------------------
    # Intent routing — LLM decides everything
    # ------------------------------------------------------------------
    def _route_intent(self, text: str) -> Dict:
        try:
            raw = self._llm(f"User said: {text}", system=ROUTER_SYSTEM_PROMPT)
            parsed = json.loads(self._clean_json(raw))
            intent = str(parsed.get("intent", "ANALYZE")).upper()
            asset = str(parsed.get("asset", "") or "").lower().strip()
            action = str(parsed.get("action", "") or "").lower().strip()
            valid_intents = {
                "ANALYZE", "SCAN", "BRIEF", "WATCHLIST", "RISK", "EXIT"
            }
            if intent not in valid_intents:
                if self._resolve_asset(text):
                    intent = "ANALYZE"
                else:
                    intent = "ANALYZE"
            self._log(
                f"Route: intent={intent} asset={asset} action={action}"
            )
            return {"intent": intent, "asset": asset, "action": action}
        except Exception as e:
            self._log_err(f"Router LLM error: {e}")
        lowered = (text or "").lower().strip()
        if lowered in FALLBACK_EXIT_WORDS:
            return {"intent": "EXIT", "asset": "", "action": ""}
        if self._resolve_asset(text):
            return {"intent": "ANALYZE", "asset": "", "action": ""}
        return {"intent": "ANALYZE", "asset": "", "action": ""}

    # ------------------------------------------------------------------
    # Feature: Analyze Asset
    # ------------------------------------------------------------------
    async def _analyze_asset(self, text: str, route_asset: str = ""):
        query = route_asset if route_asset else text
        resolved = self._resolve_asset(query)
        if not resolved and route_asset != text:
            resolved = self._resolve_asset(text)
        if not resolved:
            await self._speak(
                "I couldn't figure out which asset you mean. "
                "Try saying something like bitcoin, Tesla, or gold."
            )
            return

        ticker, scanner, display = resolved
        await self._speak(
            f"Pulling up {display} for you."
        )

        data = self._tv_fetch(ticker, scanner)
        if not data:
            await self._speak(
                f"Sorry, I couldn't get data for {display} right now. "
                "Try again in a moment."
            )
            return

        summary = self._build_analysis_text(data, display)
        spoken = self._llm(
            f"User asked about {display}. Raw data:\n{summary}",
            system=ANALYSIS_SYSTEM_PROMPT,
        )
        if spoken and spoken.strip():
            await self._speak(spoken.strip())
        else:
            await self._speak(summary)

    def _build_analysis_text(self, data: Dict, name: str) -> str:
        price = data.get("close")
        change = data.get("change")
        rsi_d = data.get("RSI")
        rsi_1h = data.get("RSI|60")
        rsi_4h = data.get("RSI|240")
        macd = data.get("MACD.macd")
        macd_sig = data.get("MACD.signal")
        ema20 = data.get("EMA20")
        data.get("EMA50")
        ema200 = data.get("EMA200")
        rec_d = data.get("Recommend.All")
        rec_1h = data.get("Recommend.All|60")
        adx = data.get("ADX")
        perf_w = data.get("Perf.W")
        perf_m = data.get("Perf.1M")

        parts = [f"{name}: price {self._fmt_price(price)}"]

        if change is not None:
            direction = "up" if change > 0 else "down"
            parts.append(f"{direction} {abs(change):.2f}% today")

        if rsi_d is not None:
            parts.append(f"Daily RSI {rsi_d:.0f}")
        if rsi_1h is not None:
            parts.append(f"1h RSI {rsi_1h:.0f}")
        if rsi_4h is not None:
            parts.append(f"4h RSI {rsi_4h:.0f}")

        if macd is not None and macd_sig is not None:
            cross = "bullish" if macd > macd_sig else "bearish"
            parts.append(f"MACD {cross}")

        if price is not None and ema20 is not None:
            rel = "above" if price > ema20 else "below"
            parts.append(f"Price {rel} EMA20")
        if price is not None and ema200 is not None:
            rel = "above" if price > ema200 else "below"
            parts.append(f"Price {rel} EMA200")

        if rec_d is not None:
            parts.append(f"TV daily rec {self._fmt_rec(rec_d)}")
        if rec_1h is not None:
            parts.append(f"TV 1h rec {self._fmt_rec(rec_1h)}")

        if adx is not None:
            strength = "strong" if adx > 25 else "weak"
            parts.append(f"ADX {adx:.0f} ({strength} trend)")

        if perf_w is not None:
            parts.append(f"Week {perf_w:+.2f}%")
        if perf_m is not None:
            parts.append(f"Month {perf_m:+.2f}%")

        return ". ".join(parts) + "."

    def _fmt_price(self, price) -> str:
        if price is None:
            return "N/A"
        price = float(price)
        if price >= 1000:
            return f"${price:,.0f}"
        if price >= 1:
            return f"${price:.2f}"
        if price >= 0.01:
            return f"${price:.4f}"
        return f"${price:.6f}"

    def _fmt_rec(self, val) -> str:
        if val is None:
            return "neutral"
        val = float(val)
        if val >= 0.5:
            return "strong buy"
        if val >= 0.1:
            return "buy"
        if val <= -0.5:
            return "strong sell"
        if val <= -0.1:
            return "sell"
        return "neutral"

    # ------------------------------------------------------------------
    # Feature: Market Scanner
    # ------------------------------------------------------------------
    async def _market_scanner(self):
        await self._speak(
            "Scanning the markets for top movers."
        )

        crypto_movers = self._tv_scan_movers("crypto", limit=5)
        stock_movers = self._tv_scan_movers("america", limit=5)

        if not crypto_movers and not stock_movers:
            await self._speak(
                "I couldn't reach the market scanner right now. "
                "Try again shortly."
            )
            return

        lines = []
        if crypto_movers:
            lines.append("Top crypto movers:")
            for m in crypto_movers:
                name = m.get("description") or m.get("name") or m.get(
                    "_ticker", ""
                )
                chg = m.get("change")
                if chg is not None:
                    direction = "up" if chg > 0 else "down"
                    lines.append(
                        f"  {name} {direction} {abs(chg):.1f}%"
                    )

        if stock_movers:
            lines.append("Top stock movers:")
            for m in stock_movers:
                name = m.get("description") or m.get("name") or m.get(
                    "_ticker", ""
                )
                chg = m.get("change")
                if chg is not None:
                    direction = "up" if chg > 0 else "down"
                    lines.append(
                        f"  {name} {direction} {abs(chg):.1f}%"
                    )

        raw_text = "\n".join(lines)
        spoken = self._llm(
            f"Format this scanner output for voice in 3-4 short sentences. "
            f"Only mention the top 3 most notable:\n{raw_text}",
            system="You are a market scanner voice assistant. Be concise. "
                   "Write all numbers and percentages as spoken words.",
        )
        await self._speak(
            spoken.strip() if spoken else raw_text
        )

    # ------------------------------------------------------------------
    # Feature: Morning Brief
    # ------------------------------------------------------------------
    async def _morning_brief(self):
        watchlist = await self._load_watchlist()
        if not watchlist:
            await self._speak(
                "Your watchlist is empty. Say 'add Bitcoin' or 'add Solana' "
                "to add symbols, then ask for the morning brief again."
            )
            return

        await self._speak(
            "Pulling your morning brief. One moment."
        )

        previous_snap = await self._load_snapshots()
        current_snap = {}
        briefs = []

        for alias in watchlist:
            resolved = self._resolve_asset(alias)
            if not resolved:
                continue
            ticker, scanner, display = resolved
            data = self._tv_fetch(ticker, scanner)
            if not data:
                briefs.append(f"{display}: data unavailable")
                continue

            price = data.get("close")
            change = data.get("change")
            rsi = data.get("RSI")
            current_snap[alias] = {
                "price": price,
                "change": change,
                "rsi": rsi,
            }

            line = f"{display} at {self._fmt_price(price)}"
            if change is not None:
                direction = "up" if change > 0 else "down"
                line += f", {direction} {abs(change):.1f}%"

            prev = previous_snap.get(alias)
            if prev and prev.get("price") and price:
                old_p = float(prev["price"])
                new_p = float(price)
                if old_p > 0:
                    delta_pct = ((new_p - old_p) / old_p) * 100
                    if abs(delta_pct) > 0.1:
                        line += (
                            f" (moved {delta_pct:+.1f}% since last check)"
                        )

            if rsi is not None:
                if rsi > 70:
                    line += ", RSI overbought"
                elif rsi < 30:
                    line += ", RSI oversold"

            briefs.append(line)
            if self.worker:
                await self.worker.session_tasks.sleep(0.2)

        await self._save_snapshots(current_snap)

        if not briefs:
            await self._speak(
                "Couldn't get data for any of your watchlist symbols. "
                "Try again in a moment."
            )
            return

        brief_text = "\n".join(briefs)
        spoken = self._llm(
            f"Deliver this as a spoken morning market brief:\n{brief_text}",
            system=BRIEF_SYSTEM_PROMPT,
        )
        await self._speak(
            spoken.strip() if spoken else brief_text
        )

    # ------------------------------------------------------------------
    # Feature: Watchlist management
    # ------------------------------------------------------------------
    async def _manage_watchlist(self, text: str, action: str = ""):
        lowered = (text or "").lower()
        if not action:
            if "add" in lowered:
                action = "add"
            elif "remove" in lowered or "delete" in lowered:
                action = "remove"
            else:
                action = "show"

        watchlist = await self._load_watchlist()

        if action == "show":
            if not watchlist:
                await self._speak(
                    "Your watchlist is empty. "
                    "Say 'add bitcoin' to get started."
                )
            else:
                names = ", ".join(a.upper() for a in watchlist)
                await self._speak(
                    f"Your watchlist has: {names}."
                )
            return

        asset_text = re.sub(
            r"\b(add|remove|delete|to|from|my|watchlist|watch list)\b",
            "",
            lowered,
        ).strip()

        if not asset_text:
            asset_text = await self.capability_worker.run_io_loop(
                "Which asset do you want to "
                f"{'add to' if action == 'add' else 'remove from'} "
                "your watchlist?"
            )

        resolved = self._resolve_asset(asset_text)
        alias = asset_text.split()[0].lower() if asset_text else ""
        if resolved:
            _, _, display = resolved
            alias = asset_text.strip().lower().split()[0]
            for key in ASSET_MAP:
                if ASSET_MAP[key][0] == resolved[0]:
                    alias = key
                    break
        else:
            display = alias.upper()

        if action == "add":
            if alias and alias not in watchlist:
                watchlist.append(alias)
                await self._save_watchlist(watchlist)
                await self._speak(
                    f"Added {display} to your watchlist."
                )
            elif alias in watchlist:
                await self._speak(
                    f"{display} is already on your watchlist."
                )
            else:
                await self._speak(
                    "I couldn't figure out which asset to add."
                )
        elif action == "remove":
            if alias in watchlist:
                watchlist.remove(alias)
                await self._save_watchlist(watchlist)
                await self._speak(
                    f"Removed {display} from your watchlist."
                )
            else:
                await self._speak(
                    f"{display} isn't on your watchlist."
                )

    # ------------------------------------------------------------------
    # Feature: Risk Calculator
    # ------------------------------------------------------------------
    async def _risk_calculator(self):
        entry_str = await self.capability_worker.run_io_loop(
            "What's your entry price?"
        )
        entry = self._parse_number(entry_str)
        if entry is None:
            await self._speak(
                "I didn't catch a valid entry price. Let's try again later."
            )
            return

        stop_str = await self.capability_worker.run_io_loop(
            "What's your stop loss price?"
        )
        stop = self._parse_number(stop_str)
        if stop is None:
            await self._speak(
                "I didn't catch a valid stop price. Let's try again later."
            )
            return

        risk_str = await self.capability_worker.run_io_loop(
            "What percentage of your account are you risking? "
            "For example, say one percent."
        )
        risk_pct = self._parse_number(risk_str)
        if risk_pct is None or risk_pct <= 0:
            risk_pct = 1.0

        account_str = await self.capability_worker.run_io_loop(
            "What's your account size in dollars?"
        )
        account = self._parse_number(account_str)
        if account is None or account <= 0:
            await self._speak(
                "I need a valid account size. Let's try again later."
            )
            return

        risk_per_unit = abs(entry - stop)
        if risk_per_unit == 0:
            await self._speak(
                "Entry and stop are the same price. "
                "There's no risk to calculate."
            )
            return

        risk_amount = account * (risk_pct / 100.0)
        position_size = risk_amount / risk_per_unit
        max_loss = risk_amount
        direction = "long" if stop < entry else "short"
        target_1r = (
            entry + risk_per_unit if direction == "long"
            else entry - risk_per_unit
        )
        target_2r = (
            entry + (2 * risk_per_unit) if direction == "long"
            else entry - (2 * risk_per_unit)
        )
        target_3r = (
            entry + (3 * risk_per_unit) if direction == "long"
            else entry - (3 * risk_per_unit)
        )

        response = (
            f"For a {direction} at {self._fmt_price(entry)} "
            f"with stop at {self._fmt_price(stop)}, "
            f"risking {risk_pct:.1f}% of ${account:,.0f}: "
            f"Position size is {position_size:.2f} units. "
            f"Max loss is ${max_loss:,.0f}. "
            f"1R target at {self._fmt_price(target_1r)}, "
            f"2R at {self._fmt_price(target_2r)}, "
            f"3R at {self._fmt_price(target_3r)}."
        )
        await self._speak(response)

    def _parse_number(self, text: str) -> Optional[float]:
        if not text:
            return None
        cleaned = re.sub(r"[^\d.\-]", "", (text or "").replace(",", ""))
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # File storage helpers
    # ------------------------------------------------------------------
    def _parse_watchlist_raw(self, raw: str) -> Optional[List[str]]:
        """Parse watchlist JSON; tolerate append-corrupted content (take last array)."""
        if not raw or not raw.strip():
            return None
        raw = raw.strip()
        try:
            data = json.loads(raw)
            if isinstance(data, list) and all(
                isinstance(x, str) for x in data
            ):
                return data
        except json.JSONDecodeError:
            pass
        try:
            last_bracket = raw.rfind("]")
            if last_bracket != -1:
                start = raw.rfind("[", 0, last_bracket + 1)
                if start != -1:
                    segment = raw[start:last_bracket + 1]
                    data = json.loads(segment)
                    if isinstance(data, list) and all(
                        isinstance(x, str) for x in data
                    ):
                        self._log(
                            "Loaded watchlist from truncated/corrupted file"
                        )
                        return data
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    async def _load_watchlist(self) -> List[str]:
        try:
            exists = await self.capability_worker.check_if_file_exists(
                WATCHLIST_FILE, False
            )
            if exists:
                raw = await self.capability_worker.read_file(
                    WATCHLIST_FILE, False
                )
                parsed = self._parse_watchlist_raw(raw or "")
                if parsed is not None:
                    self._log(f"Loaded watchlist: {parsed}")
                    return parsed
                self._log_err("Watchlist file corrupted or empty, treating as empty")
            else:
                self._log("No watchlist file yet")
        except Exception as e:
            self._log_err(f"Load watchlist error: {e}")
        return []

    async def _save_watchlist(self, watchlist: List[str]):
        try:
            try:
                await self.capability_worker.delete_file(
                    WATCHLIST_FILE, False
                )
            except Exception:
                pass
            await self.capability_worker.write_file(
                WATCHLIST_FILE, json.dumps(watchlist), False
            )
            verify = await self._load_watchlist()
            if verify != watchlist:
                self._log_err(
                    f"Watchlist verify failed: saved {watchlist}, read {verify}"
                )
            else:
                self._log(f"Watchlist saved: {watchlist}")
        except Exception as e:
            self._log_err(f"Save watchlist error: {e}")

    async def _load_snapshots(self) -> Dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(
                SNAPSHOT_FILE, False
            )
            if exists:
                raw = await self.capability_worker.read_file(
                    SNAPSHOT_FILE, False
                )
                return json.loads(raw)
        except Exception as e:
            self._log_err(f"Load snapshots error: {e}")
        return {}

    async def _save_snapshots(self, snap: Dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(
                SNAPSHOT_FILE, False
            )
            if exists:
                await self.capability_worker.delete_file(
                    SNAPSHOT_FILE, False
                )
            await self.capability_worker.write_file(
                SNAPSHOT_FILE, json.dumps(snap), False
            )
        except Exception as e:
            self._log_err(f"Save snapshots error: {e}")

    # ------------------------------------------------------------------
    # Best initial input (from trigger transcription or history)
    # ------------------------------------------------------------------
    def _best_initial_input(self) -> str:
        if self._initial_input and self._initial_input.strip():
            return self._initial_input.strip()
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

    # ------------------------------------------------------------------
    # Main conversation loop
    # ------------------------------------------------------------------
    async def run(self):
        try:
            if self.worker:
                await self.worker.session_tasks.sleep(0.3)

            initial = self._best_initial_input()
            current_query = initial
            is_just_trigger = self._is_bare_trigger(current_query)

            if not current_query or is_just_trigger:
                current_query = await self.capability_worker.run_io_loop(
                    "Hey, Market Mind here. I can analyze any asset, "
                    "scan for movers, give you a morning brief, "
                    "manage your watchlist, or calculate position sizing. "
                    "What do you need?"
                )
            else:
                await self._speak(
                    "Market Mind on it."
                )

            max_turns = 5
            for turn in range(max_turns):
                if not current_query or not current_query.strip():
                    current_query = await self.capability_worker.run_io_loop(
                        "What would you like to know?"
                    )
                    if not current_query:
                        break

                route = self._route_intent(current_query)
                intent = route.get("intent", "ANALYZE")

                if intent == "EXIT":
                    await self._speak(
                        "Alright, signing off. Talk soon."
                    )
                    break
                elif intent == "SCAN":
                    await self._market_scanner()
                elif intent == "BRIEF":
                    await self._morning_brief()
                elif intent == "WATCHLIST":
                    await self._manage_watchlist(
                        current_query, route.get("action", "")
                    )
                elif intent == "RISK":
                    await self._risk_calculator()
                else:
                    await self._analyze_asset(
                        current_query, route.get("asset", "")
                    )

                if turn < max_turns - 1:
                    current_query = await self.capability_worker.run_io_loop(
                        "Anything else? Ask another question or say stop."
                    )
                else:
                    await self._speak(
                        "That's all the turns for now. "
                        "Trigger me again anytime."
                    )
        except Exception as e:
            self._log_err(f"Unexpected error: {e}")
            if self.capability_worker:
                await self._speak(
                    "Something went wrong on my end. "
                    "Try triggering Market Mind again."
                )
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()

    def _is_bare_trigger(self, text: str) -> bool:
        bare = {
            "market mind", "market update", "market", "trading",
            "check market", "market check",
        }
        lowered = (text or "").lower().strip()
        return lowered in bare
