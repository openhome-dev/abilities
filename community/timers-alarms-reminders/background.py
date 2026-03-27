import json
from datetime import datetime
from time import time
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

EVENTS_FILE = "scheduled_events.json"
SCHEDULE_MD = "upcoming_schedule.md"
POLL_INTERVAL = 5.0
GC_MAX_AGE = 3600  # prune triggered events older than 1 hour


class TimersAlarmsRemindersCapabilityBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Safe file I/O
    # ------------------------------------------------------------------
    async def _read_events_safe(self) -> list:
        try:
            if not await self.capability_worker.check_if_file_exists(
                EVENTS_FILE, False
            ):
                return []
            raw = await self.capability_worker.read_file(EVENTS_FILE, False)
            if not (raw or "").strip():
                return []
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "%s: [TAR-W] events read failed: %s" % (time(), e)
            )
            return []

    async def _write_events_safe(self, events: list) -> None:
        try:
            if await self.capability_worker.check_if_file_exists(EVENTS_FILE, False):
                await self.capability_worker.delete_file(EVENTS_FILE, False)
            await self.capability_worker.write_file(
                EVENTS_FILE,
                json.dumps(events, ensure_ascii=False, indent=2),
                False,
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "%s: [TAR-W] events write failed: %s" % (time(), e)
            )

    # ------------------------------------------------------------------
    # Time parsing
    # ------------------------------------------------------------------
    def _parse_event_time(self, target_iso: str, tz_name: str):
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

    # ------------------------------------------------------------------
    # Fire events
    # ------------------------------------------------------------------
    async def _fire_event(self, event: dict) -> None:
        etype = event.get("type", "alarm")
        human_time = event.get("human_time", "")
        message = event.get("message", "")
        duration_label = event.get("duration_label", "")

        await self.capability_worker.send_interrupt_signal()

        if etype == "timer":
            label = duration_label or human_time
            await self.capability_worker.speak(
                "Your %s timer is done!" % label
            )
        elif etype == "alarm":
            try:
                await self.capability_worker.play_from_audio_file("alarm.mp3")
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    "%s: [TAR-W] alarm sound failed: %s" % (time(), e)
                )
            await self.capability_worker.speak(
                "Your %s alarm is going off!" % human_time
            )
        elif etype == "reminder":
            if message:
                await self.capability_worker.speak("Reminder: %s" % message)
            else:
                await self.capability_worker.speak(
                    "You have a reminder scheduled for now."
                )

    async def _mark_event_triggered(self, events: list, event_id: str) -> None:
        changed = False
        for e in events:
            if e.get("id") == event_id and e.get("status") == "scheduled":
                e["status"] = "triggered"
                e["triggered_at_epoch"] = int(time())
                changed = True
                break
        if changed:
            await self._write_events_safe(events)

    # ------------------------------------------------------------------
    # Garbage collection: prune old triggered events
    # ------------------------------------------------------------------
    def _gc_events(self, events: list) -> list:
        cutoff = int(time()) - GC_MAX_AGE
        return [
            e
            for e in events
            if not (
                e.get("status") == "triggered"
                and (e.get("triggered_at_epoch") or 0) < cutoff
            )
        ]

    # ------------------------------------------------------------------
    # upcoming_schedule.md writer
    # ------------------------------------------------------------------
    async def _update_schedule_md(self, events: list, tz_name: str) -> None:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        now = datetime.now(tz=tz)

        scheduled = [e for e in events if e.get("status") == "scheduled"]

        if not scheduled:
            content = (
                "## Upcoming Schedule\n\n"
                "No timers, alarms, or reminders currently scheduled.\n\n"
                "_Last updated: %s_\n" % now.strftime("%-I:%M %p")
            )
        else:
            timers = [e for e in scheduled if e.get("type") == "timer"]
            alarms = [e for e in scheduled if e.get("type") == "alarm"]
            reminders = [e for e in scheduled if e.get("type") == "reminder"]

            lines = ["## Upcoming Schedule\n"]

            if timers:
                lines.append("**Timers:**")
                for t in timers:
                    lines.append(
                        "- %s timer — fires at %s"
                        % (t.get("duration_label", ""), t.get("human_time", ""))
                    )
                lines.append("")

            if alarms:
                lines.append("**Alarms:**")
                for a in alarms:
                    lines.append("- %s alarm" % a.get("human_time", ""))
                lines.append("")

            if reminders:
                lines.append("**Reminders:**")
                for r in reminders:
                    lines.append(
                        "- %s — %s" % (r.get("message", ""), r.get("human_time", ""))
                    )
                lines.append("")

            lines.append("_Last updated: %s_\n" % now.strftime("%-I:%M %p"))
            content = "\n".join(lines)

        try:
            await self.capability_worker.write_file(
                SCHEDULE_MD, content, False, mode="w"
            )
        except Exception:
            try:
                if await self.capability_worker.check_if_file_exists(
                    SCHEDULE_MD, False
                ):
                    await self.capability_worker.delete_file(SCHEDULE_MD, False)
                await self.capability_worker.write_file(SCHEDULE_MD, content, False)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    "%s: [TAR-W] schedule md write failed: %s" % (time(), e)
                )

    # ------------------------------------------------------------------
    # Stale file cleanup on startup
    # ------------------------------------------------------------------
    async def _clear_stale_md(self) -> None:
        try:
            if await self.capability_worker.check_if_file_exists(SCHEDULE_MD, False):
                await self.capability_worker.delete_file(SCHEDULE_MD, False)
            self.worker.editor_logging_handler.info(
                "[TAR-W] Cleared stale schedule md on startup"
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Main watcher loop
    # ------------------------------------------------------------------
    async def watcher_loop(self):
        self.worker.editor_logging_handler.info(
            "%s: [TAR-W] Watcher started" % time()
        )

        await self._clear_stale_md()

        while True:
            try:
                events = await self._read_events_safe()

                tz_name = self.capability_worker.get_timezone()
                if not tz_name:
                    tz_name = "UTC"
                try:
                    tz = ZoneInfo(tz_name)
                except Exception:
                    tz = ZoneInfo("UTC")

                now = datetime.now(tz=tz)

                # Find due events
                due = []
                for e in events:
                    if e.get("status") != "scheduled":
                        continue
                    target_dt = self._parse_event_time(
                        e.get("target_iso"), e.get("timezone") or tz_name
                    )
                    if not target_dt:
                        continue
                    if now >= target_dt:
                        due.append((e, target_dt))

                # Fire due events in chronological order
                if due:
                    due.sort(key=lambda x: x[1])
                    for event, target_dt in due:
                        eid = event.get("id", "unknown")
                        self.worker.editor_logging_handler.info(
                            "%s: [TAR-W] FIRING %s id=%s target=%s"
                            % (time(), event.get("type"), eid, target_dt.isoformat())
                        )
                        await self._fire_event(event)
                        await self._mark_event_triggered(events, eid)

                    # Re-read after marking triggered (writes happened)
                    events = await self._read_events_safe()

                # Garbage collect old triggered events
                cleaned = self._gc_events(events)
                if len(cleaned) != len(events):
                    await self._write_events_safe(cleaned)
                    events = cleaned

                # Update personality context
                await self._update_schedule_md(events, tz_name)

            except Exception as e:
                self.worker.editor_logging_handler.error(
                    "%s: [TAR-W] watcher loop error: %s" % (time(), e)
                )
                await self.worker.session_tasks.sleep(5.0)
                continue

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)

        self.worker.editor_logging_handler.info(
            "[TAR-W] Timers Alarms Reminders watcher initialized"
        )
        self.worker.session_tasks.create(self.watcher_loop())
