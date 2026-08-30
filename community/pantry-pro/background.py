from datetime import datetime
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

import json

STORAGE_FILE = "pantrypro_inventory.json"
POLL_INTERVAL = 300.0
STARTUP_GRACE = 90
# tightest matching window first: expired, tomorrow, 3 days out
NUDGE_THRESHOLDS = [0, 1, 3]


def _empty_data() -> dict:
    return {"items": [], "shopping": []}


def _join_and(parts: list) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _format_days(days: int) -> str:
    if days < 0:
        return "already expired"
    if days == 0:
        return "expires today"
    if days == 1:
        return "expires tomorrow"
    return f"expires in {days} days"


class PantryProBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.watch_loop())

    def _today(self):
        try:
            tz = ZoneInfo(self.capability_worker.get_timezone())
            return datetime.now(tz).date()
        except Exception:
            return datetime.now().date()

    def _days_until(self, expires: str) -> int:
        if not expires:
            return 9999
        try:
            exp = datetime.strptime(expires[:10], "%Y-%m-%d").date()
            return (exp - self._today()).days
        except Exception:
            return 9999

    def _threshold_for(self, days: int) -> int:
        for threshold in NUDGE_THRESHOLDS:
            if days <= threshold:
                return threshold
        return -1

    async def _load(self):
        # returns (data, load_ok). missing file is ok; a failed read is not.
        try:
            exists = await self.capability_worker.check_if_file_exists(STORAGE_FILE, False)
            if not exists:
                return _empty_data(), True
            raw = await self.capability_worker.read_file(STORAGE_FILE, False)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("inventory is not a json object")
            parsed.setdefault("items", [])
            parsed.setdefault("shopping", [])
            return parsed, True
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PantryProBG] load failed: {e}")
            return None, False

    async def _save(self, data: dict, *, load_ok: bool) -> bool:
        if not load_ok:
            self.worker.editor_logging_handler.error(
                "[PantryProBG] save refused: inventory was not loaded cleanly"
            )
            return False
        try:
            await self.capability_worker.delete_file(STORAGE_FILE, False)
            await self.capability_worker.write_file(
                STORAGE_FILE, json.dumps(data), False
            )
            return True
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PantryProBG] save failed: {e}")
            return False

    def _alert_line(self, item: dict, days: int) -> str:
        name = item.get("name", "food")
        loc = item.get("location") or ""
        where = f" in the {loc}" if loc else ""
        return f"{name}{where} {_format_days(days)}"

    async def watch_loop(self):
        self.capability_worker.resume_normal_flow()
        self.worker.editor_logging_handler.info("[PantryProBG] daemon started")
        started_at = datetime.now().timestamp()

        while True:
            try:
                daemon_age = datetime.now().timestamp() - started_at
                if daemon_age <= STARTUP_GRACE:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                data, load_ok = await self._load()
                if not load_ok:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                items = data.get("items") or []
                if not items:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                today = self._today().isoformat()
                nudge_items = []
                changed = False

                for item in items:
                    days = self._days_until(item.get("expires", ""))
                    threshold = self._threshold_for(days)
                    if threshold == -1:
                        continue

                    last_date = item.get("last_nudge_date", "")
                    if last_date != today:
                        nudge_items.append((item, days))
                        item["last_nudge_date"] = today
                        item["last_nudge_threshold"] = threshold
                        changed = True

                if changed:
                    await self._save(data, load_ok=True)

                if not nudge_items:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                urgent = any(d <= 1 for _, d in nudge_items)
                prefix = "Urgent" if urgent else "Heads up"
                lines = [self._alert_line(item, days) for item, days in nudge_items[:3]]
                if len(nudge_items) == 1:
                    msg = f"{prefix} — {lines[0]}. Want a recipe that uses it? Say pantry pro."
                else:
                    extra = f" Plus {len(nudge_items) - 3} more." if len(nudge_items) > 3 else ""
                    msg = (
                        f"{prefix} — {len(nudge_items)} items need using: "
                        f"{_join_and(lines)}.{extra} Say pantry pro for recipe ideas."
                    )

                self.worker.editor_logging_handler.info(
                    f"[PantryProBG] alerting: {[i.get('name') for i, _ in nudge_items]}"
                )
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(msg)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[PantryProBG] loop error: {e}")
                await self.worker.session_tasks.sleep(60.0)
                continue

            await self.worker.session_tasks.sleep(POLL_INTERVAL)
