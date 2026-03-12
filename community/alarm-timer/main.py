import json
import uuid
from datetime import datetime, timezone, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# ALARM & TIMER
# Set alarms and countdown timers by voice. The background daemon (background.py)
# polls oh_alarms.json every 15 seconds and fires alarm.mp3 when time is reached,
# even during idle/sleep mode. Alarms persist across sessions via oh_alarms.json.
# =============================================================================


class AlarmTimerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    user_timezone: str = None

    # Do not change following tag of register capability
    # {{register capability}}

    def detect_timezone(self) -> str:
        """Detect timezone. Priority: get_timezone() > UTC."""
        try:
            tz = self.capability_worker.get_timezone()
            if tz and tz.strip():
                self.worker.editor_logging_handler.info(f"[AlarmTimer] Timezone from get_timezone(): {tz.strip()}")
                return tz.strip()
        except Exception as e:
            self.worker.editor_logging_handler.info(f"[AlarmTimer] get_timezone() failed: {e}")
        self.worker.editor_logging_handler.info("[AlarmTimer] Falling back to UTC")
        return "UTC"

    def classify_intent(self, user_input: str) -> str:
        """LLM classifies intent: SET_ALARM, SET_TIMER, LIST, or CANCEL."""
        prompt = (
            f"The user said: '{user_input}'\n"
            "Classify their intent as exactly one of: SET_ALARM SET_TIMER LIST CANCEL\n"
            "SET_ALARM: alarm at a specific clock time (e.g. 'wake me at 7', 'alarm for 5 PM')\n"
            "SET_TIMER: countdown timer (e.g. 'timer for 30 minutes', 'remind me in 2 hours')\n"
            "LIST: wants to see their active alarms or timers\n"
            "CANCEL: wants to cancel or delete an alarm or timer\n"
            "Return ONLY one word."
        )
        result = self.capability_worker.text_to_text_response(prompt).strip().upper()
        self.worker.editor_logging_handler.info(f"[AlarmTimer] LLM intent raw: '{result}'")
        for intent in ["SET_ALARM", "SET_TIMER", "LIST", "CANCEL"]:
            if intent in result:
                return intent
        # Keyword fallback
        lower = user_input.lower()
        if any(w in lower for w in ["cancel", "delete", "remove", "stop alarm", "stop timer"]):
            return "CANCEL"
        if any(w in lower for w in ["list", "what alarms", "do i have", "show", "any alarms"]):
            return "LIST"
        if any(w in lower for w in ["in ", "for ", "minutes", "hours", "seconds", "timer"]):
            return "SET_TIMER"
        return "SET_ALARM"

    def parse_time_with_llm(self, user_input: str, tz: str) -> dict:
        """Extract alarm details via LLM. Returns dict with type, target_iso, human_time."""
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.worker.editor_logging_handler.info(f"[AlarmTimer] Parsing time — now={now_iso}, tz={tz}, input='{user_input}'")
        prompt = (
            f"Current datetime: {now_iso}\n"
            f"User timezone: {tz}\n"
            f"User said: '{user_input}'\n"
            "Parse this alarm or timer request. Return ONLY valid JSON, no markdown:\n"
            '{"type": "alarm" or "timer", '
            '"target_iso": "YYYY-MM-DDTHH:MM:SS", '
            '"human_time": "friendly description e.g. 7:00 AM tomorrow or 30 minutes"}\n'
            "Rules: for timers, target_iso = now + the duration. "
            "For ambiguous times without AM/PM (e.g. 'alarm for 5'), pick the next occurrence. "
            "If the clock time is already past today, set it for tomorrow."
        )
        raw = self.capability_worker.text_to_text_response(prompt).strip()
        self.worker.editor_logging_handler.info(f"[AlarmTimer] LLM time parse raw: '{raw}'")
        if raw.startswith("```"):
            lines = raw.splitlines()
            inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            raw = "\n".join(inner).strip()
        try:
            parsed = json.loads(raw)
            self.worker.editor_logging_handler.info(f"[AlarmTimer] Parsed: {parsed}")
            return parsed
        except Exception as e:
            self.worker.editor_logging_handler.info(f"[AlarmTimer] JSON parse failed: {e}")
            return {}

    async def load_alarms(self) -> dict:
        """Load oh_alarms.json, return empty default if missing or corrupted."""
        exists = await self.capability_worker.check_if_file_exists("oh_alarms.json", False)
        if not exists:
            self.worker.editor_logging_handler.info("[AlarmTimer] oh_alarms.json not found, using empty default")
            return {"timezone": self.user_timezone or "UTC", "alarms": []}
        try:
            raw = await self.capability_worker.read_file("oh_alarms.json", False)
            data = json.loads(raw)
            self.worker.editor_logging_handler.info(f"[AlarmTimer] Loaded {len(data.get('alarms', []))} alarm(s)")
            return data
        except Exception as e:
            self.worker.editor_logging_handler.info(f"[AlarmTimer] load_alarms error: {e}")
            return {"timezone": self.user_timezone or "UTC", "alarms": []}

    async def save_alarms(self, data: dict):
        """Delete + write pattern for oh_alarms.json."""
        exists = await self.capability_worker.check_if_file_exists("oh_alarms.json", False)
        if exists:
            await self.capability_worker.delete_file("oh_alarms.json", False)
        await self.capability_worker.write_file(
            "oh_alarms.json", json.dumps(data, indent=2), False
        )
        self.worker.editor_logging_handler.info(f"[AlarmTimer] Saved {len(data.get('alarms', []))} alarm(s)")

    async def handle_set(self, user_input: str):
        """Handle SET_ALARM or SET_TIMER intent."""
        self.worker.editor_logging_handler.info(f"[AlarmTimer] handle_set: '{user_input}'")
        await self.capability_worker.speak("Let me set that up for you.")
        parsed = self.parse_time_with_llm(user_input, self.user_timezone)

        if not parsed or not parsed.get("target_iso"):
            self.worker.editor_logging_handler.info("[AlarmTimer] Time parse returned empty — aborting")
            await self.capability_worker.speak(
                "Sorry, I couldn't understand that time. Please try saying it again."
            )
            self.capability_worker.resume_normal_flow()
            return

        alarm_type = parsed.get("type", "alarm")
        target_iso = parsed.get("target_iso", "")
        human_time = parsed.get("human_time", target_iso)

        # If time is in the past, shift to tomorrow
        try:
            target_dt = datetime.fromisoformat(target_iso)
            seconds_from_now = (target_dt - datetime.now()).total_seconds()
            self.worker.editor_logging_handler.info(f"[AlarmTimer] target_iso={target_iso}, seconds_from_now={seconds_from_now:.0f}")
            if seconds_from_now <= 0:
                target_dt = target_dt + timedelta(days=1)
                target_iso = target_dt.strftime("%Y-%m-%dT%H:%M:%S")
                self.worker.editor_logging_handler.info(f"[AlarmTimer] Shifted to tomorrow: {target_iso}")
                await self.capability_worker.speak(
                    f"It's past {human_time} today, so I've set that for tomorrow at {human_time}."
                )
        except Exception as e:
            self.worker.editor_logging_handler.info(f"[AlarmTimer] Date shift error: {e}")

        alarm_entry = {
            "id": str(uuid.uuid4())[:8],
            "type": alarm_type,
            "created_at_epoch": int(datetime.now(timezone.utc).timestamp()),
            "target_iso": target_iso,
            "human_time": human_time,
            "source_text": user_input,
            "status": "scheduled",
        }
        self.worker.editor_logging_handler.info(f"[AlarmTimer] Saving alarm: {alarm_entry}")

        data = await self.load_alarms()
        data.setdefault("alarms", []).append(alarm_entry)
        data["timezone"] = self.user_timezone
        await self.save_alarms(data)

        if alarm_type == "timer":
            await self.capability_worker.speak(
                f"Timer set for {human_time}. I'll let you know when it's up."
            )
        else:
            await self.capability_worker.speak(f"Alarm set for {human_time}.")

        self.capability_worker.resume_normal_flow()

    async def handle_list(self):
        """List active alarms and timers."""
        self.worker.editor_logging_handler.info("[AlarmTimer] handle_list")
        data = await self.load_alarms()
        active = [a for a in data.get("alarms", []) if a.get("status") == "scheduled"]
        self.worker.editor_logging_handler.info(f"[AlarmTimer] Active alarms: {len(active)}")

        if not active:
            await self.capability_worker.speak(
                "You don't have any alarms or timers set right now."
            )
            self.capability_worker.resume_normal_flow()
            return

        parts = []
        for i, alarm in enumerate(active, 1):
            alarm_type = alarm.get("type", "alarm").title()
            human_time = alarm.get("human_time", alarm.get("target_iso", "unknown time"))
            parts.append(f"{alarm_type} {i}: {human_time}")

        await self.capability_worker.speak(
            f"You have {len(active)} active. {'. '.join(parts)}."
        )
        self.capability_worker.resume_normal_flow()

    async def handle_cancel(self, user_input: str):
        """Cancel an alarm or timer."""
        self.worker.editor_logging_handler.info(f"[AlarmTimer] handle_cancel: '{user_input}'")
        data = await self.load_alarms()
        active = [a for a in data.get("alarms", []) if a.get("status") == "scheduled"]
        self.worker.editor_logging_handler.info(f"[AlarmTimer] Active alarms to cancel: {len(active)}")

        if not active:
            await self.capability_worker.speak(
                "You don't have any alarms or timers to cancel."
            )
            self.capability_worker.resume_normal_flow()
            return

        # Single alarm — cancel directly
        if len(active) == 1:
            alarm = active[0]
            for entry in data["alarms"]:
                if entry.get("id") == alarm.get("id"):
                    entry["status"] = "cancelled"
                    break
            await self.save_alarms(data)
            self.worker.editor_logging_handler.info(f"[AlarmTimer] Cancelled: {alarm.get('id')}")
            await self.capability_worker.speak(
                f"Cancelled: {alarm.get('human_time', 'your alarm')}."
            )
            self.capability_worker.resume_normal_flow()
            return

        # Multiple alarms — list and ask
        parts = []
        for i, alarm in enumerate(active, 1):
            alarm_type = alarm.get("type", "alarm").title()
            human_time = alarm.get("human_time", alarm.get("target_iso", "unknown"))
            parts.append(f"Number {i}: {alarm_type} at {human_time}")

        await self.capability_worker.speak(
            f"You have {len(active)} active. {'. '.join(parts)}. Which number do you want to cancel?"
        )
        response = await self.capability_worker.run_io_loop("Which number?")
        if not response or not response.strip():
            await self.capability_worker.speak("No selection. Nothing cancelled.")
            self.capability_worker.resume_normal_flow()
            return

        extract_prompt = (
            f"The user was asked which alarm to cancel (numbered 1 to {len(active)}). "
            f"They said: '{response.strip()}'. "
            "Return ONLY the number as a single integer. Nothing else."
        )
        num_str = self.capability_worker.text_to_text_response(extract_prompt).strip()
        self.worker.editor_logging_handler.info(f"[AlarmTimer] Cancel selection: '{response.strip()}' → '{num_str}'")
        try:
            idx = int(num_str) - 1
            if 0 <= idx < len(active):
                target_id = active[idx].get("id")
                for entry in data["alarms"]:
                    if entry.get("id") == target_id:
                        entry["status"] = "cancelled"
                        break
                await self.save_alarms(data)
                self.worker.editor_logging_handler.info(f"[AlarmTimer] Cancelled id={target_id}")
                await self.capability_worker.speak(
                    f"Cancelled: {active[idx].get('human_time', 'that alarm')}."
                )
            else:
                await self.capability_worker.speak(
                    "That number isn't valid. Nothing cancelled."
                )
        except Exception as e:
            self.worker.editor_logging_handler.info(f"[AlarmTimer] Cancel parse error: {e}")
            await self.capability_worker.speak(
                "I didn't catch a valid number. Nothing cancelled."
            )

        self.capability_worker.resume_normal_flow()

    async def run_alarm_flow(self):
        """Main entry point — detect timezone, classify intent, route."""
        try:
            self.user_timezone = self.detect_timezone()
            self.worker.editor_logging_handler.info(f"[AlarmTimer] Timezone: {self.user_timezone}")

            # Grab the triggering utterance
            initial_request = None
            if hasattr(self.worker, "transcription") and self.worker.transcription:
                initial_request = self.worker.transcription
                self.worker.editor_logging_handler.info(f"[AlarmTimer] Got transcription: '{initial_request}'")
            if not initial_request and hasattr(self.worker, "last_transcription") and self.worker.last_transcription:
                initial_request = self.worker.last_transcription
                self.worker.editor_logging_handler.info(f"[AlarmTimer] Got last_transcription: '{initial_request}'")
            if not initial_request:
                self.worker.editor_logging_handler.info("[AlarmTimer] No transcription — prompting user")
                initial_request = await self.capability_worker.run_io_loop(
                    "What would you like? You can set an alarm, set a timer, list your alarms, or cancel one."
                )

            if not initial_request or not initial_request.strip():
                self.worker.editor_logging_handler.info("[AlarmTimer] Empty input — exiting")
                await self.capability_worker.speak("I didn't catch that. Please try again.")
                self.capability_worker.resume_normal_flow()
                return

            intent = self.classify_intent(initial_request)
            self.worker.editor_logging_handler.info(f"[AlarmTimer] Intent={intent} input='{initial_request}'")

            if intent in ("SET_ALARM", "SET_TIMER"):
                await self.handle_set(initial_request)
            elif intent == "LIST":
                await self.handle_list()
            elif intent == "CANCEL":
                await self.handle_cancel(initial_request)
            else:
                await self.capability_worker.speak(
                    "You can set an alarm, set a timer, list your alarms, or cancel one."
                )
                self.capability_worker.resume_normal_flow()

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[AlarmTimer] Unhandled error: {e}")
            await self.capability_worker.speak("Sorry, I ran into an error.")
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.user_timezone = None
        self.worker.editor_logging_handler.info("[AlarmTimer] ✓ main.py ACTIVE — run_alarm_flow starting")
        self.worker.session_tasks.create(self.run_alarm_flow())
