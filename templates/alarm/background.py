import json
from datetime import datetime
from zoneinfo import ZoneInfo
from time import time

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class BackgroundCapabilityBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    #{{register capability}}

    async def _read_alarms_safe(self):
        """
        Reads alarms.json safely.
        If corrupted / not a list -> return [] (do NOT crash watcher).
        """
        try:
            if not await self.capability_worker.check_if_file_exists("alarms.json", False):
                return []

            raw = await self.capability_worker.read_file("alarms.json", False)
            if not (raw or "").strip():
                return []

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"{time()}: alarms.json read/parse failed: {e}")
            return []

    def _parse_alarm_time(self, target_iso: str, tz_name: str):
        """
        Returns an aware datetime for target_iso.
        """
        if not target_iso:
            return None
        try:
            # target_iso already includes offset; datetime.fromisoformat handles it
            dt = datetime.fromisoformat(target_iso)
            if dt.tzinfo is None:
                # fallback: attach timezone if missing
                try:
                    dt = dt.replace(tzinfo=ZoneInfo(tz_name or "UTC"))
                except Exception:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            return dt
        except Exception:
            return None

    async def _mark_alarm_triggered(self, alarms: list, alarm_id: str):
        """
        Mark a triggered alarm as 'triggered' to prevent repeat firing.
        Best-effort write: if write fails, watcher may re-trigger next loop.
        """
        try:
            changed = False
            for a in alarms:
                if a.get("id") == alarm_id and a.get("status") == "scheduled":
                    a["status"] = "triggered"
                    a["triggered_at_epoch"] = int(time())
                    changed = True
                    break

            if not changed:
                return

            # write back (delete-first to avoid append corruption)
            try:
                if await self.capability_worker.check_if_file_exists("alarms.json", False):
                    await self.capability_worker.delete_file("alarms.json", False)
            except Exception:
                pass

            await self.capability_worker.write_file(
                "alarms.json",
                json.dumps(alarms, ensure_ascii=False, indent=2),
                False,
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"{time()}: failed to mark alarm triggered: {e}")

    async def first_function(self):
        self.worker.editor_logging_handler.info("%s: Watcher Alarm Called" % time())

        # Watch loop
        while True:
            try:
                self.worker.editor_logging_handler.info("%s: watcher alarm watching" % time())

                alarms = await self._read_alarms_safe()
                if not alarms:
                    await self.worker.session_tasks.sleep(5.0)
                    continue

                # Use watcher timezone as "now" reference (same as your alarm creation)
                tz_name = self.capability_worker.get_timezone()
                try:
                    tz = ZoneInfo(tz_name)
                except Exception:
                    tz = ZoneInfo("UTC")

                now = datetime.now(tz=tz)

                # Find scheduled alarms that are due
                due = []
                for a in alarms:
                    if a.get("status") != "scheduled":
                        continue
                    target_dt = self._parse_alarm_time(a.get("target_iso"), a.get("timezone") or tz_name)
                    if not target_dt:
                        continue
                    if now >= target_dt:
                        due.append((a, target_dt))

                # Fire due alarms (in order)
                if due:
                    due.sort(key=lambda x: x[1])
                    for a, target_dt in due:
                        alarm_id = a.get("id", "unknown")
                        human_time = a.get("human_time", a.get("target_iso", ""))

                        self.worker.editor_logging_handler.info(
                            f"{time()}: ALARM DUE id={alarm_id} target={target_dt.isoformat()} human='{human_time}'"
                        )

                        # Play alarm sound
                        try:
                            await self.capability_worker.play_from_audio_file("alarm.mp3")
                        except Exception as e:
                            self.worker.editor_logging_handler.error(
                                f"{time()}: Failed to play alarm sound for {alarm_id}: {e}"
                            )

                        # Mark as triggered to avoid repeat firing
                        await self._mark_alarm_triggered(alarms, alarm_id)

                await self.worker.session_tasks.sleep(5.0)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"{time()}: watcher loop error: {e}")
                await self.worker.session_tasks.sleep(2.0)

        # Resume the normal workflow (unreachable, but keep structure)
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        # Initialize the worker and capability worker
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)

        self.worker.session_tasks.create(self.first_function())
