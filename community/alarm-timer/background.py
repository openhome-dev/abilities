import json
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# ALARM & TIMER — Background Watcher
# Starts automatically on session connect. Polls oh_alarms.json every 15 seconds.
# Fires alarm.mp3 in a loop when target time is reached. Survives idle/sleep mode.
# Dismissal: user speaks anything while alarm sounds → history length increases.
# =============================================================================


class AlarmTimerWatcher(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    async def save_json(self, data: dict):
        """Delete + write pattern for oh_alarms.json."""
        exists = await self.capability_worker.check_if_file_exists("oh_alarms.json", False)
        if exists:
            await self.capability_worker.delete_file("oh_alarms.json", False)
        await self.capability_worker.write_file(
            "oh_alarms.json", json.dumps(data, indent=2), False
        )

    async def fire_alarm_loop(self, alarm: dict):
        """Play alarm.mp3 on repeat until user speaks or safety cap (~5 min) reached."""
        alarm_id = alarm.get("id", "?")
        alarm_type = alarm.get("type", "alarm")
        human_time = alarm.get("human_time", "")
        self.worker.editor_logging_handler.info(
            f"[AlarmWatcher] fire_alarm_loop START id={alarm_id} type={alarm_type} time='{human_time}'"
        )

        # Snapshot message count BEFORE loop starts
        count_before = 0
        try:
            history_before = await self.capability_worker.get_full_message_history()
            count_before = len(history_before) if history_before else 0
            self.worker.editor_logging_handler.info(f"[AlarmWatcher] History snapshot: {count_before} messages")
        except Exception as e:
            self.worker.editor_logging_handler.info(f"[AlarmWatcher] get_full_message_history error: {e}")

        # Call send_interrupt_signal ONCE — never inside the loop
        self.worker.editor_logging_handler.info("[AlarmWatcher] Sending interrupt signal")
        await self.capability_worker.send_interrupt_signal()

        max_loops = 20
        loop_count = 0

        while loop_count < max_loops:
            self.worker.editor_logging_handler.info(f"[AlarmWatcher] Playing alarm.mp3 (loop {loop_count + 1}/{max_loops})")
            await self.capability_worker.play_from_audio_file("alarm.mp3")
            await self.worker.session_tasks.sleep(2.0)

            # Check if user spoke (new message appeared in history)
            try:
                history_now = await self.capability_worker.get_full_message_history()
                count_now = len(history_now) if history_now else 0
                if count_now > count_before:
                    self.worker.editor_logging_handler.info(
                        f"[AlarmWatcher] Dismissed by user (history {count_before} → {count_now})"
                    )
                    break
            except Exception as e:
                self.worker.editor_logging_handler.info(f"[AlarmWatcher] History check error: {e}")

            loop_count += 1

        if loop_count >= max_loops:
            self.worker.editor_logging_handler.info("[AlarmWatcher] Safety cap reached — auto-dismissing")

        if alarm_type == "timer":
            await self.capability_worker.speak(f"Your {human_time} timer is dismissed.")
        else:
            await self.capability_worker.speak(f"Alarm for {human_time} dismissed.")

        self.worker.editor_logging_handler.info(f"[AlarmWatcher] fire_alarm_loop END id={alarm_id}")

    async def check_alarms(self):
        """Infinite polling loop. Runs for the entire session duration."""
        self.worker.editor_logging_handler.info("[AlarmWatcher] ✓ background.py ACTIVE — poll loop started (15s interval)")
        poll_count = 0
        while True:
            poll_count += 1
            try:
                exists = await self.capability_worker.check_if_file_exists(
                    "oh_alarms.json", False
                )
                if not exists:
                    if poll_count % 4 == 1:  # Log every ~1 min to avoid spam
                        self.worker.editor_logging_handler.info(
                            f"[AlarmWatcher] Poll #{poll_count}: oh_alarms.json not found, sleeping"
                        )
                    await self.worker.session_tasks.sleep(15.0)
                    continue

                raw = await self.capability_worker.read_file("oh_alarms.json", False)
                try:
                    data = json.loads(raw)
                except Exception as e:
                    self.worker.editor_logging_handler.info(f"[AlarmWatcher] JSON parse error: {e}")
                    await self.worker.session_tasks.sleep(15.0)
                    continue

                now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                scheduled = [a for a in data.get("alarms", []) if a.get("status") == "scheduled"]
                self.worker.editor_logging_handler.info(
                    f"[AlarmWatcher] Poll #{poll_count}: now={now_iso}, scheduled={len(scheduled)}"
                )

                for alarm in scheduled:
                    target_iso = alarm.get("target_iso", "")
                    if not target_iso:
                        continue
                    self.worker.editor_logging_handler.info(
                        f"[AlarmWatcher] Checking id={alarm.get('id')} target={target_iso} — {'FIRE' if now_iso >= target_iso else 'waiting'}"
                    )
                    if now_iso >= target_iso:
                        alarm["status"] = "triggered"
                        await self.save_json(data)
                        await self.fire_alarm_loop(alarm)

            except Exception as e:
                self.worker.editor_logging_handler.info(f"[AlarmWatcher] Poll loop error: {e}")

            await self.worker.session_tasks.sleep(15.0)

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.editor_logging_handler.info("[AlarmWatcher] ✓ background.py call() — starting check_alarms task")
        self.worker.session_tasks.create(self.check_alarms())
