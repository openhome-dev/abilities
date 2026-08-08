import json
from datetime import datetime
from time import time
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

REMINDERS_FILE = "guardian_reminders.json"
WALK_FILE = "guardian_walk.json"


class HomeHelperBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # {{register capability}}

    async def _read_json_safe(self, filename: str, default):
        try:
            if not await self.capability_worker.check_if_file_exists(filename, False):
                return default
            raw = await self.capability_worker.read_file(filename, False)
            if not (raw or "").strip():
                return default
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"{time()}: failed reading {filename}: {e}"
            )
            return default

    async def _write_json_safe(self, filename: str, data) -> None:
        try:
            if await self.capability_worker.check_if_file_exists(filename, False):
                await self.capability_worker.delete_file(filename, False)
            await self.capability_worker.write_file(
                filename,
                json.dumps(data, ensure_ascii=False, indent=2),
                False,
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"{time()}: failed writing {filename}: {e}"
            )

    def _parse_iso(self, target_iso: str, tz_name: str):
        if not target_iso:
            return None
        try:
            dt = datetime.fromisoformat(target_iso)
            if dt.tzinfo is None:
                try:
                    dt = dt.replace(tzinfo=ZoneInfo(tz_name or "UTC"))
                except Exception:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            return dt
        except Exception:
            return None

    async def _fire_reminders(self, now, tz_name: str) -> None:
        reminders = await self._read_json_safe(REMINDERS_FILE, [])
        if not isinstance(reminders, list) or not reminders:
            return

        due = []
        for rem in reminders:
            if rem.get("status") != "scheduled":
                continue
            target = self._parse_iso(
                rem.get("target_iso"), rem.get("timezone") or tz_name
            )
            if target and now >= target:
                due.append(rem)

        if not due:
            return

        changed = False
        for rem in due:
            label = rem.get("label") or "your reminder"
            self.worker.editor_logging_handler.info(
                f"{time()}: reminder due id={rem.get('id')} label={label}"
            )
            try:
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(f"Reminder: {label}.")
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"{time()}: reminder speak failed: {e}"
                )
            rem["status"] = "triggered"
            rem["triggered_at_epoch"] = int(time())
            changed = True

        if changed:
            await self._write_json_safe(REMINDERS_FILE, reminders)

    async def _check_walk_session(self, now, tz_name: str) -> None:
        session = await self._read_json_safe(WALK_FILE, {})
        if not isinstance(session, dict) or session.get("status") != "active":
            return

        due = self._parse_iso(
            session.get("check_in_iso"), session.get("timezone") or tz_name
        )
        if not due or now < due:
            return

        missed = int(session.get("missed_count") or 0) + 1
        session["missed_count"] = missed
        session["last_nudge_epoch"] = int(time())

        # Push next check-in a few minutes out so we don't spam every loop
        try:
            from datetime import timedelta

            nxt = now + timedelta(minutes=5)
            session["check_in_iso"] = nxt.isoformat()
            session["human_time"] = nxt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            pass

        try:
            await self.capability_worker.send_interrupt_signal()
            if missed <= 1:
                await self.capability_worker.speak(
                    "Walk-home check-in. Are you okay? Say check in if you're safe."
                )
            else:
                session["status"] = "escalated"
                await self.capability_worker.speak(
                    "I haven't heard a check-in. If you can, say check in. "
                    "If you're in danger, call emergency services and get to a safe public place."
                )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"{time()}: walk nudge failed: {e}"
            )

        await self._write_json_safe(WALK_FILE, session)

    async def watcher_loop(self):
        self.worker.editor_logging_handler.info(f"{time()}: HouseMate background started")
        while True:
            try:
                tz_name = self.capability_worker.get_timezone() or "Asia/Karachi"
                try:
                    tz = ZoneInfo(tz_name)
                except Exception:
                    tz = ZoneInfo("Asia/Karachi")
                    tz_name = "Asia/Karachi"
                now = datetime.now(tz=tz)

                await self._fire_reminders(now, tz_name)
                await self._check_walk_session(now, tz_name)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"{time()}: HouseMate watcher error: {e}"
                )

            await self.worker.session_tasks.sleep(15.0)

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.watcher_loop())
