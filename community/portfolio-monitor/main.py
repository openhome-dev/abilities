import re
import requests
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

FINNHUB_BASE = "https://finnhub.io/api/v1"
AV_BASE = "https://www.alphavantage.co/query"
STORAGE_KEY = "portfolio_data"
CACHE_TTL_SECONDS = 180

HOTWORDS = {
    "portfolio monitor", "my portfolio", "check my stocks", "stock update",
    "portfolio update", "my stocks", "stock alert", "stock check",
    "add to portfolio", "add a stock", "log a stock", "track a stock",
    "remove from portfolio", "remove a stock",
    "set stock alert", "set a stock alert", "stock price alert",
    "what's moving", "biggest movers", "gainers today", "losers today",
    "clear my portfolio", "wipe my portfolio",
    "compare my stocks", "compare my portfolio", "day over day",
    "how did my stocks do", "stock comparison", "versus yesterday",
    "update my position", "bought more", "i sold", "add more shares",
    "change my position", "update my stock", "sold some",
    "how are the markets", "market update", "market pulse",
    "what's the market doing", "market today", "market check",
    "check apple", "check tesla", "check nvidia", "check amazon",
    "check microsoft", "check google", "check meta", "check netflix",
    "how's apple", "how's tesla", "how's nvidia", "how's amazon",
    "how's microsoft", "how's google", "how's meta", "how's netflix",
}

_MARKET_INDICES = [
    ("SPY", "S&P 500"),
    ("QQQ", "Nasdaq"),
    ("DIA", "Dow Jones"),
]

TICKER_MAP = {
    "apple": "AAPL",
    "tesla": "TSLA",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "nvidia": "NVDA",
    "meta": "META",
    "facebook": "META",
    "netflix": "NFLX",
    "disney": "DIS",
    "salesforce": "CRM",
    "visa": "V",
    "mastercard": "MA",
    "jpmorgan": "JPM",
    "jp morgan": "JPM",
    "johnson": "JNJ",
    "walmart": "WMT",
    "exxon": "XOM",
    "chevron": "CVX",
    "unitedhealth": "UNH",
    "home depot": "HD",
    "adobe": "ADBE",
    "paypal": "PYPL",
    "intel": "INTC",
    "amd": "AMD",
    "qualcomm": "QCOM",
    "broadcom": "AVGO",
    "uber": "UBER",
    "lyft": "LYFT",
    "airbnb": "ABNB",
    "spotify": "SPOT",
    "shopify": "SHOP",
    "palantir": "PLTR",
    "coinbase": "COIN",
    "robinhood": "HOOD",
    "snapchat": "SNAP",
    "snap": "SNAP",
    "twitter": "X",
    "berkshire": "BRK.B",
    "boeing": "BA",
    "ford": "F",
    "general motors": "GM",
    "gm": "GM",
    "bank of america": "BAC",
    "wells fargo": "WFC",
    "citigroup": "C",
    "goldman sachs": "GS",
    "morgan stanley": "MS",
}

COMMON_WORDS = {
    "A", "I", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN",
    "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US",
    "WE", "ADD", "AND", "ARE", "BUT", "CAN", "FOR", "GET", "GOT", "HAD",
    "HAS", "HIM", "HIS", "HOW", "LET", "NOT", "NOW", "OFF", "OUT", "OWN",
    "PUT", "SAY", "SEE", "SET", "THE", "TOO", "TWO", "USE", "WAS", "WHO",
    "WHY", "YES", "YET", "YOU", "ALL", "NEW", "OLD", "OUR", "TOP",
}

_EXIT_PATTERN = re.compile(
    r'\b(stop|exit|quit|done|cancel|bye|goodbye|never\s*mind|no\s*thanks|'
    r"that'?s\s*all|nothing|nah|skip)\b",
    re.IGNORECASE,
)

_ADD_COMMAND_PHRASES = {
    "add a stock", "add to portfolio", "log a stock", "track a stock",
    "add stock", "new stock", "add another", "add another stock",
}

_AFFIRMATIVE_PATTERN = re.compile(
    r'\b(yes|yeah|sure|yep|absolutely|ok|okay|go ahead)\b',
    re.IGNORECASE,
)

_VALID_INTENTS = frozenset({
    "PORTFOLIO", "CHECK", "COMPARE", "MOVERS", "ADD", "UPDATE",
    "SET_ALERT", "REMOVE", "CLEAR", "MARKET"
})

_HUB_ACTIONS = frozenset({"BREAKDOWN", "COMPARE", "MOVERS", "MARKET", "CHECK", "UNKNOWN"})


def _empty_data() -> dict:
    return {
        "holdings": [],
        "alert_thresholds": {},
        "price_cache": {},
        "alerted_today": [],
        "meta": {
            "api_calls_today": 0,
            "api_calls_date": "",
            "last_eod_summary": "",
        },
    }


class PortfolioMonitorCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    finnhub_key: str = ""
    av_key: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Hotword matching
    # ------------------------------------------------------------------

    def does_match(self, text: str) -> bool:
        t = text.lower().strip()
        if any(hw in t for hw in HOTWORDS):
            return True
        # "check [company/ticker]" or "how's [company/ticker] doing"
        if re.search(r'\b(check|how.?s|how is)\b', t) and "portfolio" not in t:
            return bool(self._resolve_ticker_cheap(text))
        # "add Apple" / "add NVDA" — static map + ticker pattern, no LLM
        if re.search(r'\badd\b', t) and "portfolio" not in t:
            for company in TICKER_MAP:
                if company in t:
                    return True
            for match in re.finditer(r'\b([A-Z]{2,5})\b', text.upper()):
                if match.group(1) not in COMMON_WORDS:
                    return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        if not text or not text.strip():
            return True
        stripped = text.strip().rstrip(".,!?").strip().lower()
        if stripped in ("no", "skip"):
            return True
        return bool(_EXIT_PATTERN.search(text))

    def _classify_intent(self, text: str) -> str:
        t = text.lower()

        # Cheap pre-filter for unambiguous destructive actions only
        if any(kw in t for kw in ("clear", "wipe", "reset")) and any(
            kw in t for kw in ("portfolio", "stocks", "holdings", "all")
        ):
            return "CLEAR"
        if re.search(r'\b(remove|delete)\b', t) or (
            re.search(r'\bdrop\b', t) and any(
                kw in t for kw in ("portfolio", "holding", "position", "from my", "from the")
            )
        ):
            return "REMOVE"

        try:
            raw = self.capability_worker.text_to_text_response(
                "Route this request for a stock portfolio voice assistant.\n"
                "Pick exactly one intent:\n"
                "PORTFOLIO — view overall portfolio value and P&L\n"
                "CHECK — price or status of a specific stock\n"
                "COMPARE — day-over-day: how each stock moved vs yesterday's close\n"
                "MOVERS — biggest gainer and loser in the portfolio today\n"
                "ADD — add a new stock to the portfolio\n"
                "UPDATE — modify an existing position: bought more shares, sold some, or correct avg cost\n"
                "SET_ALERT — set a price drop or rise alert for a stock\n"
                "REMOVE — remove a stock from the portfolio\n"
                "CLEAR — wipe the entire portfolio\n"
                "MARKET — broad market overview: S&P 500, Nasdaq, Dow Jones\n\n"
                "Reply with ONLY the intent label.\n"
                f"User input: {text.strip() or '(portfolio update)'}"
            )
            intent = raw.strip().upper().split()[0].strip(".,")
            return intent if intent in _VALID_INTENTS else "PORTFOLIO"
        except Exception:
            return "PORTFOLIO"

    def _classify_hub_action(self, text: str) -> str:
        try:
            raw = self.capability_worker.text_to_text_response(
                "The user is inside a portfolio dashboard. Route their request:\n"
                "BREAKDOWN — full per-stock detail list\n"
                "COMPARE — day-over-day comparison vs yesterday's close\n"
                "MOVERS — biggest gainer and loser today\n"
                "MARKET — broad market indices (S&P 500, Nasdaq, Dow)\n"
                "CHECK — specific stock price or status\n"
                "UNKNOWN — none of the above\n\n"
                "Reply with ONLY the label.\n"
                f"User input: {text}"
            )
            result = raw.strip().upper().split()[0].strip(".,")
            return result if result in _HUB_ACTIONS else "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    def _resolve_ticker_cheap(self, text: str) -> str | None:
        """Static-only ticker resolution — safe to call from does_match (no LLM)."""
        if not text:
            return None
        lower = text.lower()
        for company, ticker in sorted(TICKER_MAP.items(), key=lambda x: -len(x[0])):
            if company in lower:
                return ticker
        for match in re.finditer(r'\b([A-Z]{2,5})\b', text.upper()):
            candidate = match.group(1)
            if candidate not in COMMON_WORDS:
                return candidate
        return None

    def _resolve_ticker(self, text: str) -> str | None:
        result = self._resolve_ticker_cheap(text)
        if result:
            return result
        return self._resolve_ticker_llm(text)

    def _resolve_ticker_llm(self, text: str) -> str | None:
        try:
            raw = self.capability_worker.text_to_text_response(
                "Extract the US stock ticker symbol from this text. "
                "Return ONLY the ticker (e.g. AAPL, TSLA) or 'NONE' if not found.\n"
                f"Text: {text}"
            )
            result = raw.strip().upper().split()[0].strip(".,") if raw.strip() else "NONE"
            return None if result == "NONE" else result
        except Exception:
            return None

    def _resolve_company_name(self, ticker: str) -> str:
        for company, t in TICKER_MAP.items():
            if t == ticker:
                return company.title()
        try:
            raw = self.capability_worker.text_to_text_response(
                f"What company does the US stock ticker {ticker} represent? "
                "Reply with ONLY the company name, nothing else."
            )
            return raw.strip() or ticker
        except Exception:
            return ticker

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def _fetch_quote_finnhub(self, ticker: str) -> dict | None:
        try:
            resp = requests.get(
                f"{FINNHUB_BASE}/quote",
                params={"symbol": ticker, "token": self.finnhub_key},
                timeout=10,
            )
            if resp.status_code == 200:
                d = resp.json()
                price = d.get("c", 0)
                if price:
                    return {
                        "price": float(price),
                        "change_pct": float(d.get("dp", 0)),
                        "prev_close": float(d.get("pc", 0)),
                        "high": float(d.get("h", 0)),
                        "low": float(d.get("l", 0)),
                    }
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PortfolioMonitor] Finnhub error for {ticker}: {e}"
            )
            return None

    def _fetch_quote_av(self, ticker: str) -> dict | None:
        if not self.av_key:
            return None
        try:
            resp = requests.get(
                AV_BASE,
                params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": self.av_key},
                timeout=10,
            )
            if resp.status_code == 200:
                gq = resp.json().get("Global Quote", {})
                price = float(gq.get("05. price", 0))
                if price:
                    raw_pct = gq.get("10. change percent", "0%").replace("%", "")
                    return {
                        "price": price,
                        "change_pct": float(raw_pct),
                        "prev_close": float(gq.get("08. previous close", 0)),
                        "high": float(gq.get("03. high", 0)),
                        "low": float(gq.get("04. low", 0)),
                    }
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PortfolioMonitor] AV error for {ticker}: {e}"
            )
            return None

    def _fetch_quote(self, ticker: str) -> dict | None:
        quote = self._fetch_quote_finnhub(ticker)
        if quote:
            return quote
        return self._fetch_quote_av(ticker)

    # ------------------------------------------------------------------
    # Context Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
            return _empty_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PortfolioMonitor] Load error: {e}")
            return _empty_data()

    def _save_data(self, data: dict):
        try:
            self.capability_worker.update_key(STORAGE_KEY, data)
        except Exception:
            try:
                self.capability_worker.create_key(STORAGE_KEY, data)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[PortfolioMonitor] Save error: {e}")

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_portfolio(self):
        data = self._load_data()
        holdings = data.get("holdings", [])
        if not holdings:
            await self.capability_worker.speak(
                "No stocks in your portfolio yet. Say 'add a stock' to start tracking."
            )
            return

        cache = data.get("price_cache", {})
        changed = False

        # Pre-scan for stale tickers; announce once if multiple need fetching
        stale_tickers = []
        for h in holdings:
            ticker = h["ticker"]
            q = cache.get(ticker)
            is_stale = True
            if q:
                try:
                    cached_at = datetime.strptime(q["cached_at"], "%Y-%m-%dT%H:%M:%S")
                    is_stale = (datetime.utcnow() - cached_at).total_seconds() > CACHE_TTL_SECONDS
                except Exception:
                    pass
            if is_stale:
                stale_tickers.append(h["ticker"])

        if len(stale_tickers) > 1:
            await self.capability_worker.speak("Fetching latest prices...")
        elif len(stale_tickers) == 1:
            solo = next(h for h in holdings if h["ticker"] == stale_tickers[0])
            await self.capability_worker.speak(f"Fetching {solo.get('name', stale_tickers[0])}...")

        for ticker in stale_tickers:
            quote = self._fetch_quote(ticker)
            if quote:
                cache[ticker] = {
                    **quote,
                    "cached_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                }
                changed = True

        if changed:
            data["price_cache"] = cache
            self._save_data(data)

        # Compute totals for snapshot
        total_value = 0.0
        total_cost = 0.0
        day_pnl = 0.0
        for h in holdings:
            q = cache.get(h["ticker"])
            if not q:
                continue
            price = q["price"]
            prev_close = q.get("prev_close", price)
            shares = h.get("shares", 0)
            avg_cost = h.get("avg_cost", 0)
            total_value += price * shares
            total_cost += avg_cost * shares
            day_pnl += (price - prev_close) * shares

        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
        day_dir = "up" if day_pnl >= 0 else "down"
        overall_dir = "up" if total_pnl >= 0 else "down"

        # Snapshot — tight two lines, then navigation prompt
        await self.capability_worker.speak(
            f"Portfolio at ${total_value:,.0f} — {day_dir} ${abs(day_pnl):,.0f} today, "
            f"{overall_dir} ${abs(total_pnl):,.0f} ({abs(total_pnl_pct):.0f}%) overall."
        )
        await self.capability_worker.speak(
            "Say 'breakdown' for full detail, 'compare' for day-over-day, "
            "'movers' for biggest movers, 'market' for market indices, or a stock name."
        )

        while True:
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                break
            action = self._classify_hub_action(reply)
            if action == "BREAKDOWN":
                await self._speak_portfolio_breakdown(data)
            elif action == "COMPARE":
                await self._handle_compare(data)
            elif action == "MOVERS":
                await self._handle_movers(data)
            elif action == "MARKET":
                await self._handle_market()
            elif action == "CHECK":
                ticker = self._resolve_ticker(reply)
                if ticker:
                    await self._speak_single_stock(ticker, data)
                else:
                    await self.capability_worker.speak(
                        "Which stock? Say a company name or ticker symbol."
                    )
            else:
                ticker = self._resolve_ticker(reply)
                if ticker:
                    await self._speak_single_stock(ticker, data)
                else:
                    await self.capability_worker.speak(
                        "Say 'breakdown', 'compare', 'movers', 'market', a stock name, or stop."
                    )

    async def _speak_portfolio_breakdown(self, data: dict):
        holdings = data.get("holdings", [])
        cache = data.get("price_cache", {})
        stock_lines = []

        for h in holdings:
            ticker = h["ticker"]
            name = h.get("name", ticker)
            shares = h.get("shares", 0)
            avg_cost = h.get("avg_cost", 0)
            q = cache.get(ticker)

            if not q:
                stock_lines.append(f"{name}: no data available")
                continue

            price = q["price"]
            change_pct = q.get("change_pct", 0)
            position_value = price * shares
            position_cost = avg_cost * shares
            position_pnl = position_value - position_cost
            position_pnl_pct = (position_pnl / position_cost * 100) if position_cost else 0

            day_dir = "up" if change_pct >= 0 else "down"
            pos_dir = "up" if position_pnl >= 0 else "down"
            stock_lines.append(
                f"{name}: ${price:,.0f}, {day_dir} {abs(change_pct):.0f}% today, "
                f"{pos_dir} ${abs(position_pnl):,.0f} ({abs(position_pnl_pct):.0f}%) overall"
            )

        if not stock_lines:
            return
        chunk_size = 4
        for i in range(0, len(stock_lines), chunk_size):
            chunk = stock_lines[i:i + chunk_size]
            await self.capability_worker.speak(". ".join(chunk) + ".")
            if i + chunk_size < len(stock_lines):
                await self.capability_worker.speak("Want to hear the rest?")
                reply = await self.capability_worker.user_response()
                if self._is_exit(reply) or not _AFFIRMATIVE_PATTERN.search(reply or ""):
                    break

    async def _handle_compare(self, data: dict | None = None):
        if data is None:
            data = self._load_data()
        holdings = data.get("holdings", [])
        if not holdings:
            await self.capability_worker.speak("No stocks in your portfolio yet.")
            return

        cache = data.get("price_cache", {})
        lines = []
        no_data = []

        for h in holdings:
            ticker = h["ticker"]
            name = h.get("name", ticker)
            q = cache.get(ticker)
            if not q or not q.get("prev_close"):
                no_data.append(name)
                continue

            price = q["price"]
            prev_close = q["prev_close"]
            change_pct = q.get("change_pct", 0)
            day_dollar = abs(price - prev_close)
            direction = "up" if change_pct >= 0 else "down"
            pct_str = f"{abs(change_pct):.0f}" if abs(change_pct) >= 1 else "less than 1"
            lines.append(f"{name} {direction} {pct_str}% (${day_dollar:,.0f})")

        if not lines:
            await self.capability_worker.speak(
                "No comparison data yet — say 'my portfolio' first to fetch current prices."
            )
            return

        chunk_size = 4
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i + chunk_size]
            prefix = "Today versus yesterday: " if i == 0 else "Continuing: "
            await self.capability_worker.speak(prefix + ", ".join(chunk) + ".")
            if i + chunk_size < len(lines):
                await self.capability_worker.speak("Want to hear the rest?")
                reply = await self.capability_worker.user_response()
                if self._is_exit(reply) or not _AFFIRMATIVE_PATTERN.search(reply or ""):
                    break
        if no_data:
            await self.capability_worker.speak(f"No data for: {', '.join(no_data)}.")

    async def _speak_single_stock(self, ticker: str, data: dict):
        cache = data.get("price_cache", {})
        q = cache.get(ticker)
        if not q:
            await self.capability_worker.speak(f"Fetching {ticker}...")
            q = self._fetch_quote(ticker)
            if q:
                data.setdefault("price_cache", {})[ticker] = {
                    **q,
                    "cached_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                }
                self._save_data(data)

        if not q:
            await self.capability_worker.speak(
                f"Couldn't get data for {ticker} right now. Try again in a moment."
            )
            return

        price = q["price"]
        change_pct = q.get("change_pct", 0)
        day_dir = "up" if change_pct >= 0 else "down"
        pct_str = f"{abs(change_pct):.0f}" if abs(change_pct) >= 1 else "less than 1"

        holding = next(
            (h for h in data.get("holdings", []) if h["ticker"] == ticker), None
        )
        name = holding.get("name", ticker) if holding else (
            next((c.title() for c, t in TICKER_MAP.items() if t == ticker), ticker)
        )

        msg = f"{name} is at ${price:,.0f}, {day_dir} {pct_str} percent today."

        if holding:
            shares = holding["shares"]
            avg_cost = holding["avg_cost"]
            pos_value = price * shares
            pos_cost = avg_cost * shares
            pos_pnl = pos_value - pos_cost
            pos_pnl_pct = (pos_pnl / pos_cost * 100) if pos_cost else 0
            pos_dir = "up" if pos_pnl >= 0 else "down"
            msg += (
                f" Your {shares:g} shares are worth ${pos_value:,.0f} — "
                f"{pos_dir} ${abs(pos_pnl):,.0f} ({abs(pos_pnl_pct):.0f}%) on your position."
            )
        else:
            msg += " Not in your portfolio — say 'add a stock' to track it."

        await self.capability_worker.speak(msg)

    async def _handle_check(self, trigger_text: str):
        ticker = self._resolve_ticker(trigger_text)

        if not ticker:
            await self.capability_worker.speak(
                "Which stock should I check? Say the company name or ticker symbol."
            )
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            ticker = self._resolve_ticker(reply)

        if not ticker:
            await self.capability_worker.speak(
                "I couldn't identify that stock. Try using the ticker symbol like AAPL or TSLA."
            )
            return

        while ticker:
            data = self._load_data()

            cached = data.get("price_cache", {}).get(ticker)
            is_fresh = False
            if cached:
                try:
                    cached_at = datetime.strptime(cached["cached_at"], "%Y-%m-%dT%H:%M:%S")
                    is_fresh = (datetime.utcnow() - cached_at).total_seconds() < CACHE_TTL_SECONDS
                except Exception:
                    pass

            if not is_fresh:
                await self.capability_worker.speak(f"Checking {ticker}...")
                quote = self._fetch_quote(ticker)
                if not quote:
                    await self.capability_worker.speak(
                        f"Couldn't get data for {ticker} right now. Try again in a moment."
                    )
                    return
                data.setdefault("price_cache", {})[ticker] = {
                    **quote,
                    "cached_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                }
                self._save_data(data)

            await self._speak_single_stock(ticker, data)

            await self.capability_worker.speak(
                "Want to check another stock? Say a name or stop."
            )
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                break
            ticker = self._resolve_ticker(reply)
            if not ticker:
                await self.capability_worker.speak(
                    "I couldn't identify that stock. Try using the ticker symbol like AAPL or TSLA."
                )
                break

    async def _handle_movers(self, data: dict | None = None):
        if data is None:
            data = self._load_data()
        holdings = data.get("holdings", [])
        if not holdings:
            await self.capability_worker.speak("No stocks in your portfolio yet.")
            return

        cache = data.get("price_cache", {})
        movers = []
        for h in holdings:
            ticker = h["ticker"]
            q = cache.get(ticker)
            if q:
                movers.append((h.get("name", ticker), q.get("change_pct", 0)))

        if not movers:
            await self.capability_worker.speak(
                "No price data cached yet — say 'my portfolio' to fetch current prices."
            )
            return

        movers.sort(key=lambda x: x[1])
        worst = movers[0]
        best = movers[-1]

        parts = []
        if best[1] > 0:
            parts.append(f"Biggest gainer: {best[0]}, up {best[1]:.0f} percent.")
        if worst[1] < 0:
            parts.append(f"Biggest loser: {worst[0]}, down {abs(worst[1]):.0f} percent.")

        if not parts:
            await self.capability_worker.speak(
                "Everything's flat today — no significant movers in your portfolio."
            )
            return

        await self.capability_worker.speak(" ".join(parts))

    async def _handle_market(self):
        await self.capability_worker.speak("Checking market indices...")
        parts = []
        for ticker, label in _MARKET_INDICES:
            quote = self._fetch_quote(ticker)
            if quote:
                change_pct = quote.get("change_pct", 0)
                direction = "up" if change_pct >= 0 else "down"
                pct_str = f"{abs(change_pct):.1f}" if abs(change_pct) >= 0.1 else "flat"
                parts.append(f"{label} {direction} {pct_str}%")
        if not parts:
            await self.capability_worker.speak(
                "Couldn't fetch market data right now. Try again in a moment."
            )
            return
        await self.capability_worker.speak("Markets today: " + ", ".join(parts) + ".")

    async def _handle_update(self, trigger_text: str, ticker: str | None = None):
        if ticker is None:
            ticker = self._resolve_ticker(trigger_text)
        if not ticker:
            await self.capability_worker.speak("Which stock do you want to update?")
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            ticker = self._resolve_ticker(reply)
        if not ticker:
            await self.capability_worker.speak(
                "I couldn't identify that stock. Try using the ticker symbol."
            )
            return

        data = self._load_data()
        holding = next((h for h in data.get("holdings", []) if h["ticker"] == ticker), None)
        if not holding:
            name = self._resolve_company_name(ticker)
            await self.capability_worker.speak(
                f"{name} isn't in your portfolio. Say 'add a stock' to add it."
            )
            return

        name = holding.get("name", ticker)
        shares = holding["shares"]
        avg_cost = holding["avg_cost"]
        await self.capability_worker.speak(
            f"{name}: {shares:g} shares at ${avg_cost:,.0f} average, "
            f"total cost ${shares * avg_cost:,.0f}. "
            "Say 'bought more', 'sold some', or 'correct' to overwrite."
        )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return
        r = reply.lower()

        if any(kw in r for kw in ("bought", "more", "buy", "added", "purchase")):
            await self.capability_worker.speak(
                "How many shares did you buy, and at what price? Say both — like '5 at 210'."
            )
            details = await self.capability_worker.user_response()
            if self._is_exit(details):
                return
            nums = [float(n.replace(",", "")) for n in re.findall(r'[\d,]+\.?\d*', details) if n]
            if len(nums) < 2 or nums[0] <= 0 or nums[1] <= 0:
                await self.capability_worker.speak(
                    "I need both the number of shares and the price."
                )
                return
            new_shares, new_price = nums[0], nums[1]
            total_shares = shares + new_shares
            new_avg = (shares * avg_cost + new_shares * new_price) / total_shares
            holding["shares"] = total_shares
            holding["avg_cost"] = round(new_avg, 2)
            self._save_data(data)
            await self.capability_worker.speak(
                f"Updated — {name} now {total_shares:g} shares at ${new_avg:,.0f} average."
            )

        elif any(kw in r for kw in ("sold", "sell", "sale", "reduced")):
            await self.capability_worker.speak("How many shares did you sell?")
            details = await self.capability_worker.user_response()
            if self._is_exit(details):
                return
            nums = [float(n.replace(",", "")) for n in re.findall(r'[\d,]+\.?\d*', details) if n]
            if not nums or nums[0] <= 0:
                await self.capability_worker.speak("I need to know how many shares you sold.")
                return
            sold = nums[0]
            remaining = shares - sold
            if remaining <= 0:
                confirmed = await self.capability_worker.run_confirmation_loop(
                    f"That would leave zero shares. Remove {name} from your portfolio?"
                )
                if confirmed:
                    data["holdings"] = [h for h in data["holdings"] if h["ticker"] != ticker]
                    data.get("alert_thresholds", {}).pop(ticker, None)
                    data.get("price_cache", {}).pop(ticker, None)
                    self._save_data(data)
                    await self.capability_worker.speak(f"Removed {name} from your portfolio.")
            else:
                holding["shares"] = remaining
                self._save_data(data)
                await self.capability_worker.speak(
                    f"Updated — {name} now {remaining:g} shares remaining."
                )

        elif any(kw in r for kw in ("correct", "overwrite", "set", "change", "update")):
            await self.capability_worker.speak(
                "What's the correct number of shares and average cost? "
                "Say both — like '10 at 175'."
            )
            details = await self.capability_worker.user_response()
            if self._is_exit(details):
                return
            nums = [float(n.replace(",", "")) for n in re.findall(r'[\d,]+\.?\d*', details) if n]
            if len(nums) < 2 or nums[0] <= 0 or nums[1] <= 0:
                await self.capability_worker.speak(
                    "I need both the number of shares and the price."
                )
                return
            holding["shares"] = nums[0]
            holding["avg_cost"] = nums[1]
            self._save_data(data)
            await self.capability_worker.speak(
                f"Updated — {name} corrected to {nums[0]:g} shares at ${nums[1]:,.0f} average."
            )

        else:
            await self.capability_worker.speak(
                "Say 'bought more', 'sold some', or 'correct' to update the position."
            )

    async def _handle_add(self, trigger_text: str):
        while True:
            trigger_clean = trigger_text.lower().strip()
            generic_trigger = not trigger_clean or trigger_clean in _ADD_COMMAND_PHRASES

            name = None  # resolved early in non-generic branch; reused at save time

            if generic_trigger:
                await self.capability_worker.speak(
                    "Which stock, how many shares, and at what price? "
                    "Say it all — like 'Apple 10 shares at 180'."
                )
                reply = await self.capability_worker.user_response()
                if self._is_exit(reply):
                    return

                ticker = self._resolve_ticker(reply)
                if not ticker:
                    await self.capability_worker.speak(
                        "I didn't catch the stock. Say 'add a stock' to try again."
                    )
                    return

                nums = re.findall(r'[\d,]+\.?\d*', reply)
                nums_clean = []
                for n in nums:
                    try:
                        nums_clean.append(float(n.replace(",", "")))
                    except ValueError:
                        pass

                if len(nums_clean) < 2:
                    await self.capability_worker.speak(
                        "I need both the number of shares and the price. "
                        "Say 'add a stock' and include all three — like 'Apple 10 shares at 180'."
                    )
                    return

                shares = nums_clean[0]
                avg_cost = nums_clean[1]

            else:
                ticker = self._resolve_ticker(trigger_text)
                if not ticker:
                    await self.capability_worker.speak(
                        "Say 'add a stock' to add to your portfolio."
                    )
                    return

                nums = re.findall(r'[\d,]+\.?\d*', trigger_text)
                nums_clean = []
                for n in nums:
                    try:
                        nums_clean.append(float(n.replace(",", "")))
                    except ValueError:
                        pass

                if len(nums_clean) >= 2:
                    shares = nums_clean[0]
                    avg_cost = nums_clean[1]
                else:
                    name = self._resolve_company_name(ticker)
                    await self.capability_worker.speak(
                        f"Adding {name}. How many shares and at what price? "
                        "Say both — like '10 shares at 180'."
                    )
                    reply = await self.capability_worker.user_response()
                    if self._is_exit(reply):
                        return

                    more_nums = re.findall(r'[\d,]+\.?\d*', reply)
                    more_clean = []
                    for n in more_nums:
                        try:
                            more_clean.append(float(n.replace(",", "")))
                        except ValueError:
                            pass

                    if len(more_clean) < 2:
                        await self.capability_worker.speak(
                            "Say both the number of shares and the price — like '10 at 180'."
                        )
                        return

                    shares = more_clean[0]
                    avg_cost = more_clean[1]

            if shares <= 0 or avg_cost <= 0:
                await self.capability_worker.speak(
                    "Shares and price must be greater than zero. Say 'add a stock' to try again."
                )
                return

            data = self._load_data()
            existing = next(
                (h for h in data.get("holdings", []) if h["ticker"] == ticker), None
            )
            if existing:
                ex_name = existing.get("name", ticker)
                await self.capability_worker.speak(
                    f"{ex_name} is already in your portfolio — "
                    f"{existing['shares']:g} shares at ${existing['avg_cost']:,.0f} average. "
                    "Want to update this position?"
                )
                confirm = await self.capability_worker.user_response()
                if _AFFIRMATIVE_PATTERN.search(confirm or ""):
                    await self._handle_update("", ticker=ticker)
                    return
            else:
                if name is None:
                    name = self._resolve_company_name(ticker)
                holding = {
                    "id": str(int(datetime.now().timestamp() * 1000)),
                    "ticker": ticker,
                    "name": name,
                    "shares": shares,
                    "avg_cost": avg_cost,
                    "added_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                }
                data["holdings"].append(holding)
                self._save_data(data)
                await self.capability_worker.speak(
                    f"Added {shares:g} shares of {name} at ${avg_cost:,.0f} average. "
                    f"Total position: ${shares * avg_cost:,.0f}."
                )

            await self.capability_worker.speak(
                "Want to add another stock? Say a stock name or stop."
            )
            next_reply = await self.capability_worker.user_response()
            if self._is_exit(next_reply):
                return
            trigger_text = "" if _AFFIRMATIVE_PATTERN.search(next_reply) else next_reply

    async def _handle_set_alert(self, trigger_text: str):
        ticker = self._resolve_ticker(trigger_text)

        if not ticker:
            await self.capability_worker.speak(
                "Which stock do you want to set an alert for?"
            )
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            ticker = self._resolve_ticker(reply)

        if not ticker:
            await self.capability_worker.speak("I couldn't identify that stock.")
            return

        while ticker:
            data = self._load_data()
            holding = next(
                (h for h in data.get("holdings", []) if h["ticker"] == ticker), None
            )
            if not holding:
                await self.capability_worker.speak(
                    f"{ticker} isn't in your portfolio — add it first."
                )
                return

            name = holding.get("name", ticker)

            await self.capability_worker.speak(
                f"Alert me if {name} drops how many percent in a day? Say a number or skip."
            )
            drop_reply = await self.capability_worker.user_response()
            drop_pct = None
            if not self._is_exit(drop_reply) and "skip" not in drop_reply.lower():
                m = re.search(r'[\d.]+', drop_reply)
                if m:
                    drop_pct = float(m.group())

            await self.capability_worker.speak(
                f"Alert me if {name} rises how many percent in a day? Say a number or skip."
            )
            rise_reply = await self.capability_worker.user_response()
            rise_pct = None
            if not self._is_exit(rise_reply) and "skip" not in rise_reply.lower():
                m = re.search(r'[\d.]+', rise_reply)
                if m:
                    rise_pct = float(m.group())

            if drop_pct is None and rise_pct is None:
                await self.capability_worker.speak("No thresholds set.")
            else:
                ticker_thresholds = data.setdefault("alert_thresholds", {}).setdefault(ticker, {})
                if drop_pct is not None:
                    ticker_thresholds["drop_pct"] = drop_pct
                if rise_pct is not None:
                    ticker_thresholds["rise_pct"] = rise_pct
                self._save_data(data)

                parts = []
                if drop_pct is not None:
                    parts.append(f"drops {drop_pct:.0f}%")
                if rise_pct is not None:
                    parts.append(f"rises {rise_pct:.0f}%")
                await self.capability_worker.speak(
                    f"Done — I'll alert you if {name} {' or '.join(parts)} in a day."
                )

            await self.capability_worker.speak(
                "Want to set an alert for another stock? Say a stock name or stop."
            )
            next_reply = await self.capability_worker.user_response()
            if self._is_exit(next_reply):
                return
            ticker = self._resolve_ticker(next_reply)
            if not ticker:
                await self.capability_worker.speak("I couldn't identify that stock.")
                return

    async def _handle_remove(self, trigger_text: str):
        data = self._load_data()
        holdings = data.get("holdings", [])
        if not holdings:
            await self.capability_worker.speak("Your portfolio is empty.")
            return

        ticker = self._resolve_ticker(trigger_text)

        if not ticker:
            await self.capability_worker.speak("Which stock do you want to remove?")
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            ticker = self._resolve_ticker(reply)

        if not ticker:
            await self.capability_worker.speak("I couldn't identify that stock.")
            return

        holding = next((h for h in holdings if h["ticker"] == ticker), None)
        if not holding:
            await self.capability_worker.speak(f"{ticker} isn't in your portfolio.")
            return

        name = holding.get("name", ticker)
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Remove {name} from your portfolio?"
        )
        if confirmed:
            data["holdings"] = [h for h in holdings if h["ticker"] != ticker]
            data.get("alert_thresholds", {}).pop(ticker, None)
            data.get("price_cache", {}).pop(ticker, None)
            self._save_data(data)
            await self.capability_worker.speak(f"Removed {name}.")
        else:
            await self.capability_worker.speak("Keeping it.")

    async def _handle_clear(self):
        data = self._load_data()
        count = len(data.get("holdings", []))
        if count == 0:
            await self.capability_worker.speak("Portfolio is already empty.")
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Clear all {count} {'stock' if count == 1 else 'stocks'} from your portfolio?"
        )
        if confirmed:
            data["holdings"] = []
            data["alert_thresholds"] = {}
            data["price_cache"] = {}
            data["alerted_today"] = []
            self._save_data(data)
            await self.capability_worker.speak("Portfolio cleared.")
        else:
            await self.capability_worker.speak("Keeping everything.")

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            self.finnhub_key = self.capability_worker.get_api_keys("finnhub_api_key") or ""
            self.av_key = self.capability_worker.get_api_keys("alphavantage_api_key") or ""

            if not self.finnhub_key:
                await self.capability_worker.speak(
                    "Portfolio Monitor needs a Finnhub API key to work. "
                    "Add it in Settings under API Keys — get a free one at finnhub dot io."
                )
                return

            trigger_text = await self.capability_worker.wait_for_complete_transcription()
            if not trigger_text or not isinstance(trigger_text, str):
                trigger_text = ""

            intent = self._classify_intent(trigger_text)
            self.worker.editor_logging_handler.info(
                f"[PortfolioMonitor] Intent: {intent} | Trigger: {trigger_text[:80]}"
            )

            if intent == "PORTFOLIO":
                await self._handle_portfolio()
            elif intent == "CHECK":
                await self._handle_check(trigger_text)
            elif intent == "COMPARE":
                await self._handle_compare()
            elif intent == "MOVERS":
                await self._handle_movers()
            elif intent == "ADD":
                await self._handle_add(trigger_text)
            elif intent == "UPDATE":
                await self._handle_update(trigger_text)
            elif intent == "SET_ALERT":
                await self._handle_set_alert(trigger_text)
            elif intent == "REMOVE":
                await self._handle_remove(trigger_text)
            elif intent == "CLEAR":
                await self._handle_clear()
            elif intent == "MARKET":
                await self._handle_market()
            else:
                await self.capability_worker.speak(
                    "I can show your portfolio, check a stock, track movers, "
                    "or add a stock. What would you like?"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PortfolioMonitor] Skill error: {e}")
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Try asking again in a moment."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())
