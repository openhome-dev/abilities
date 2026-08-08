import requests
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "portfolio_data"
POLL_MARKET_OPEN = 300.0
POLL_MARKET_CLOSED = 1800.0
POLL_NO_HOLDINGS = 30.0
CACHE_TTL_SECONDS = 180
MAX_API_CALLS_PER_POLL = 50

FINNHUB_BASE = "https://finnhub.io/api/v1"
AV_BASE = "https://www.alphavantage.co/query"


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


def _new_state() -> dict:
    return {
        "current_day": "",
        "open_notified": False,
        "eod_spoken": False,
    }


class PortfolioMonitorBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False
    finnhub_key: str = ""
    av_key: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

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
    # Market hours (ET, no pytz)
    # ------------------------------------------------------------------

    def _et_now(self) -> datetime:
        utc = datetime.utcnow()
        m, y = utc.month, utc.year
        if 4 <= m <= 10:
            offset = -4
        elif m == 3:
            first_day = datetime(y, 3, 1)
            first_sun = first_day + timedelta(days=(6 - first_day.weekday()) % 7)
            second_sun = first_sun + timedelta(days=7)
            # 2am EST = 7am UTC
            offset = -4 if utc >= second_sun.replace(hour=7) else -5
        elif m == 11:
            first_day = datetime(y, 11, 1)
            first_sun = first_day + timedelta(days=(6 - first_day.weekday()) % 7)
            # 2am EDT = 6am UTC
            offset = -5 if utc >= first_sun.replace(hour=6) else -4
        else:
            offset = -5
        return utc + timedelta(hours=offset)

    def _is_market_open_et(self, et: datetime) -> bool:
        if et.weekday() >= 5:
            return False
        mins = et.hour * 60 + et.minute
        return 9 * 60 + 30 <= mins < 16 * 60

    def _is_eod_window_et(self, et: datetime) -> bool:
        if et.weekday() >= 5:
            return False
        mins = et.hour * 60 + et.minute
        return 16 * 60 <= mins <= 16 * 60 + 10

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

    def _is_cache_fresh(self, ticker: str, data: dict) -> bool:
        entry = data.get("price_cache", {}).get(ticker)
        if not entry:
            return False
        try:
            cached_at = datetime.strptime(entry["cached_at"], "%Y-%m-%dT%H:%M:%S")
            return (datetime.utcnow() - cached_at).total_seconds() < CACHE_TTL_SECONDS
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Alert logic
    # ------------------------------------------------------------------

    def _check_alerts(self, ticker: str, holding: dict, quote: dict, data: dict) -> list:
        thresholds = data.get("alert_thresholds", {}).get(ticker, {})
        drop_pct = thresholds.get("drop_pct")
        rise_pct = thresholds.get("rise_pct")
        if not drop_pct and not rise_pct:
            return []

        change_pct = quote.get("change_pct", 0)
        price = quote.get("price", 0)
        shares = holding.get("shares", 0)
        avg_cost = holding.get("avg_cost", 0)
        name = holding.get("name", ticker)

        alerts = []

        if drop_pct and change_pct <= -drop_pct:
            pnl = (price - avg_cost) * shares
            pnl_str = f"down ${abs(pnl):,.0f}" if pnl < 0 else f"up ${pnl:,.0f}"
            msg = (
                f"Heads up — {name} is down {abs(change_pct):.0f} percent today. "
                f"Your position is {pnl_str}. Say 'portfolio monitor' to review."
            )
            alerts.append(("drop", msg))

        if rise_pct and change_pct >= rise_pct:
            pnl = (price - avg_cost) * shares
            pnl_str = f"up ${pnl:,.0f}" if pnl >= 0 else f"down ${abs(pnl):,.0f}"
            msg = (
                f"Nice — {name} is up {change_pct:.0f} percent today. "
                f"Your position is {pnl_str}. Say 'portfolio monitor' to review."
            )
            alerts.append(("rise", msg))

        return alerts

    # ------------------------------------------------------------------
    # Proactive voice
    # ------------------------------------------------------------------

    async def _speak_morning_open(self, data: dict):
        holdings = data.get("holdings", [])
        count = len(holdings)
        names = ", ".join(h.get("name", h["ticker"]) for h in holdings[:3])
        suffix = f" and {count - 3} more" if count > 3 else ""
        try:
            await self.capability_worker.send_interrupt_signal()
            await self.capability_worker.speak(
                f"Market just opened. You're tracking {count} "
                f"{'stock' if count == 1 else 'stocks'}: {names}{suffix}. "
                "Say 'portfolio monitor' for an update."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PortfolioMonitor] Morning open error: {e}"
            )

    async def _speak_eod_summary(self, data: dict):
        holdings = data.get("holdings", [])
        if not holdings:
            return

        # Force fresh quotes at close so EOD summary reflects final prices
        cache = data.get("price_cache", {})
        changed = False
        for h in holdings:
            ticker = h["ticker"]
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

        total_value = 0.0
        total_cost = 0.0
        day_pnl = 0.0
        best = None
        best_pct = -float("inf")
        worst = None
        worst_pct = float("inf")

        for h in holdings:
            ticker = h["ticker"]
            q = cache.get(ticker)
            if not q:
                continue
            price = q["price"]
            prev_close = q.get("prev_close", price)
            shares = h.get("shares", 0)
            avg_cost = h.get("avg_cost", 0)
            change_pct = q.get("change_pct", 0)

            total_value += price * shares
            total_cost += avg_cost * shares
            day_pnl += (price - prev_close) * shares

            if change_pct > best_pct:
                best_pct = change_pct
                best = h.get("name", ticker)
            if change_pct < worst_pct:
                worst_pct = change_pct
                worst = h.get("name", ticker)

        if not total_value:
            return

        day_dir = "up" if day_pnl >= 0 else "down"
        overall_pnl = total_value - total_cost
        overall_dir = "up" if overall_pnl >= 0 else "down"

        parts = [
            f"Market's closed. Your portfolio ended at ${total_value:,.0f}, "
            f"{day_dir} ${abs(day_pnl):,.0f} today, "
            f"{overall_dir} ${abs(overall_pnl):,.0f} overall."
        ]
        if best and best_pct > 0:
            parts.append(f"{best} led, up {best_pct:.0f} percent.")
        if worst and worst_pct < 0:
            parts.append(f"{worst} lagged, down {abs(worst_pct):.0f} percent.")

        try:
            await self.capability_worker.send_interrupt_signal()
            await self.capability_worker.speak(" ".join(parts))
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PortfolioMonitor] EOD summary error: {e}"
            )

    # ------------------------------------------------------------------
    # Main daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        self.finnhub_key = self.capability_worker.get_api_keys("finnhub_api_key") or ""
        self.av_key = self.capability_worker.get_api_keys("alphavantage_api_key") or ""

        if not self.finnhub_key:
            self.worker.editor_logging_handler.warning(
                "[PortfolioMonitor] No Finnhub API key — daemon idle until key is configured."
            )

        s = _new_state()
        self.worker.editor_logging_handler.info("[PortfolioMonitor] daemon started")
        self.capability_worker.resume_normal_flow()

        while True:
            sleep_time = POLL_MARKET_CLOSED
            try:
                if not self.finnhub_key:
                    await self.worker.session_tasks.sleep(POLL_NO_HOLDINGS)
                    continue

                data = self._load_data()
                holdings = data.get("holdings", [])

                self.worker.editor_logging_handler.info(
                    f"[PortfolioMonitor] daemon tick — {len(holdings)} holding(s)"
                )
                if not holdings:
                    await self.worker.session_tasks.sleep(POLL_NO_HOLDINGS)
                    continue

                et = self._et_now()
                today_str = et.strftime("%Y-%m-%d")

                # Reset daily state
                if today_str != s["current_day"]:
                    s["current_day"] = today_str
                    s["open_notified"] = False
                    s["eod_spoken"] = False
                    data["alerted_today"] = []
                    meta = data.setdefault("meta", {})
                    meta["api_calls_today"] = 0
                    meta["api_calls_date"] = today_str
                    self._save_data(data)

                market_open = self._is_market_open_et(et)

                # Morning open notification
                if market_open and not s["open_notified"]:
                    s["open_notified"] = True
                    await self._speak_morning_open(data)

                # EOD summary
                if self._is_eod_window_et(et) and not s["eod_spoken"]:
                    await self._speak_eod_summary(data)
                    s["eod_spoken"] = True

                # Price polling during market hours
                if market_open:
                    sleep_time = POLL_MARKET_OPEN
                    calls_this_poll = 0
                    changed = False
                    pending_alerts = []

                    for holding in holdings:
                        if calls_this_poll >= MAX_API_CALLS_PER_POLL:
                            break
                        ticker = holding["ticker"]
                        if self._is_cache_fresh(ticker, data):
                            continue

                        quote = self._fetch_quote(ticker)
                        calls_this_poll += 1
                        if not quote:
                            continue

                        data.setdefault("price_cache", {})[ticker] = {
                            **quote,
                            "cached_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                        }
                        data.setdefault("meta", {})
                        data["meta"]["api_calls_today"] = (
                            data["meta"].get("api_calls_today", 0) + 1
                        )
                        changed = True

                        self.worker.editor_logging_handler.info(
                            f"[PortfolioMonitor] {ticker}: ${quote['price']:.2f} "
                            f"({quote['change_pct']:+.1f}%)"
                        )

                        alerts = self._check_alerts(ticker, holding, quote, data)
                        for direction, msg in alerts:
                            alert_key = f"{ticker}_{direction}"
                            if alert_key not in data.get("alerted_today", []):
                                data.setdefault("alerted_today", []).append(alert_key)
                                pending_alerts.append(msg)
                                changed = True

                    if changed:
                        self._save_data(data)

                    for msg in pending_alerts:
                        try:
                            await self.capability_worker.send_interrupt_signal()
                            await self.capability_worker.speak(msg)
                        except Exception as e:
                            self.worker.editor_logging_handler.error(
                                f"[PortfolioMonitor] Alert error: {e}"
                            )

            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[PortfolioMonitor] Loop error: {e}"
                )

            await self.worker.session_tasks.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.background_daemon_mode = background_daemon_mode
        self.worker.session_tasks.create(self.watch_loop())
