from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "life_admin_tracker_data"

# Days-before-expiry thresholds, ascending so we find the tightest match first
NUDGE_THRESHOLDS = [0, 7, 30, 90]


class LifeAdminTrackerBackgroundCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.background_daemon_mode = background_daemon_mode
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.watch_loop())

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[LifeAdminBG] Load error: {e!r}")
        return {}

    def _save_data(self, data: dict):
        try:
            result = self.capability_worker.create_key(STORAGE_KEY, data)
            if not result.get("success"):
                self.capability_worker.update_key(STORAGE_KEY, data)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[LifeAdminBG] Save error: {e!r}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _days_until(self, expiry_date: str) -> int:
        try:
            exp = datetime.strptime(expiry_date, "%Y-%m-%d").date()
            return (exp - datetime.now().date()).days
        except Exception:
            return 9999

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _nudge_threshold_for(self, days: int) -> int:
        """Return the tightest matching nudge threshold, or -1 if >90 days out."""
        for threshold in NUDGE_THRESHOLDS:
            if days <= threshold:
                return threshold
        return -1

    def _format_days(self, days: int) -> str:
        if days <= 0:
            return "already expired"
        if days == 1:
            return "tomorrow"
        return f"in {days} days"

    # ------------------------------------------------------------------
    # Daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        self.capability_worker.resume_normal_flow()
        self.worker.editor_logging_handler.info("[LifeAdminBG] Daemon started")

        while True:
            try:
                await self.worker.session_tasks.sleep(3600.0)

                data = self._load_data()
                if not data.get("setup_complete"):
                    continue

                items = data.get("items", [])
                if not items:
                    continue

                name = data.get("user_name", "")
                today = self._today()
                nudge_items = []
                data_changed = False

                for item in items:
                    days = self._days_until(item.get("expiry_date", ""))
                    threshold = self._nudge_threshold_for(days)
                    if threshold == -1:
                        continue

                    last_threshold = item.get("last_nudge_threshold")
                    last_date = item.get("last_nudge_date", "")

                    if threshold <= 7:
                        # Daily nudges inside the 7-day window
                        if last_date != today:
                            nudge_items.append((item, days))
                            item["last_nudge_threshold"] = threshold
                            item["last_nudge_date"] = today
                            data_changed = True
                    else:
                        # One-time nudge per threshold (90-day, 30-day)
                        if last_threshold != threshold:
                            nudge_items.append((item, days))
                            item["last_nudge_threshold"] = threshold
                            data_changed = True

                if data_changed:
                    self._save_data(data)

                if not nudge_items:
                    continue

                name_str = f", {name}" if name else ""
                is_urgent = any(d <= 7 for _, d in nudge_items)
                prefix = f"Urgent{name_str}" if is_urgent else f"Heads up{name_str}"

                if len(nudge_items) == 1:
                    item, days = nudge_items[0]
                    if days <= 0:
                        msg = (
                            f"{prefix} — your {item['name']} has expired. "
                            f"Time to get it renewed."
                        )
                    else:
                        msg = (
                            f"{prefix} — your {item['name']} expires "
                            f"{self._format_days(days)}."
                        )
                else:
                    parts = []
                    for item, days in nudge_items[:3]:
                        parts.append(f"your {item['name']} {self._format_days(days)}")

                    if len(parts) == 2:
                        items_str = f"{parts[0]} and {parts[1]}"
                    else:
                        items_str = (
                            ", ".join(parts[:-1]) + f", and {parts[-1]}"
                        )
                    msg = f"{prefix} — {len(nudge_items)} things need attention: {items_str}."

                self.worker.editor_logging_handler.info(
                    f"[LifeAdminBG] Nudging: {[i['name'] for i, _ in nudge_items]}"
                )
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(msg)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[LifeAdminBG] Loop error: {e!r}")
                await self.worker.session_tasks.sleep(300.0)
