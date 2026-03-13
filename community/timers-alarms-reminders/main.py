import json
from datetime import datetime
from time import time
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

EVENTS_FILE = "scheduled_events.json"
SCHEDULE_MD = "upcoming_schedule.md"
QUIT_WORDS = {"quit", "exit", "never mind", "go back", "goodbye", "bye"}
EXIT_WORDS = {"no", "nope", "nah", "done", "all done", "nothing", "that's it", "thats it", "i'm good", "im good"}


def _strip_punctuation(text):
    return text.strip().rstrip(".,!?;:")


def _wants_to_quit(text):
    if not text:
        return False
    lower = _strip_punctuation(text).lower()
    if lower in QUIT_WORDS:
        return True
    words = [_strip_punctuation(w) for w in lower.split()]
    return "quit" in words or "exit" in words or "never mind" in lower or "go back" == lower


def _wants_to_exit(text):
    if not text:
        return False
    lower = _strip_punctuation(text).lower()
    return lower in EXIT_WORDS or _wants_to_quit(lower)


class TimersAlarmsRemindersCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # scheduled_events.json safe read / write
    # ------------------------------------------------------------------
    async def _reset_events_file(self, reason: str = "") -> None:
        try:
            if reason:
                self.worker.editor_logging_handler.warning(
                    "%s: scheduled_events.json reset. Reason: %s" % (time(), reason)
                )
            if await self.capability_worker.check_if_file_exists(EVENTS_FILE, False):
                await self.capability_worker.delete_file(EVENTS_FILE, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "%s: Failed to reset events file: %s" % (time(), e)
            )

    async def _read_events(self) -> list:
        if not await self.capability_worker.check_if_file_exists(EVENTS_FILE, False):
            return []
        raw = await self.capability_worker.read_file(EVENTS_FILE, False)
        if not (raw or "").strip():
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
            await self._reset_events_file("JSON is valid but not a list")
            return []
        except Exception as e:
            await self._reset_events_file("Corrupted JSON: %s" % e)
            return []

    async def _write_events(self, events: list) -> None:
        if not isinstance(events, list):
            events = []
        payload = json.dumps(events, ensure_ascii=False, indent=2)
        await self._reset_events_file("Pre-write delete to avoid append-concat")
        try:
            await self.capability_worker.write_file(EVENTS_FILE, payload, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "%s: Write events failed: %s" % (time(), e)
            )
            await self._reset_events_file("Write failed")
            try:
                await self.capability_worker.write_file(EVENTS_FILE, "[]", False)
            except Exception:
                pass

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
                    "%s: Failed to update schedule md: %s" % (time(), e)
                )

    # ------------------------------------------------------------------
    # LLM system prompt
    # ------------------------------------------------------------------
    def _format_events_for_prompt(self, events: list) -> str:
        scheduled = [e for e in events if e.get("status") == "scheduled"]
        if not scheduled:
            return "None"
        lines = []
        for e in scheduled:
            etype = e.get("type", "unknown")
            eid = e.get("id", "?")
            human = e.get("human_time", e.get("target_iso", "?"))
            msg = e.get("message")
            dur = e.get("duration_label")
            desc = human
            if etype == "timer" and dur:
                desc = "%s (%s)" % (dur, human)
            if etype == "reminder" and msg:
                desc = '"%s" at %s' % (msg, human)
            lines.append("- [id=%s] %s: %s" % (eid, etype, desc))
        return "\n".join(lines)

    def _build_system_prompt(self, now: datetime, tz_name: str, events: list) -> str:
        events_text = self._format_events_for_prompt(events)
        return """You are a scheduling assistant that handles timers, alarms, and reminders.

Current datetime (authoritative): %s
Timezone (authoritative): %s

EXISTING SCHEDULED EVENTS:
%s

TASK: Classify the user's intent and extract structured data.

INTENT TYPES:
1. CREATE_TIMER - duration-based ("set a timer for 20 minutes")
2. CREATE_ALARM - clock-based ("wake me up at 7am", "set an alarm for 7am")
3. CREATE_REMINDER - message + time ("remind me to call Sarah at 3pm")
4. LIST_EVENTS - user wants to see scheduled events ("what timers do I have?")
5. CANCEL_EVENT - user wants to cancel a specific event ("cancel my 7am alarm")
6. DELETE_ALL - user wants to clear everything ("delete all timers")

RULES:
- For CREATE_TIMER: convert duration to absolute target time. Example: "20 minutes" from current time = current time + 20 minutes.
  The "human_time" for timers should be the clock time it fires at (e.g. "3:45 PM"), NOT the duration.
  The "duration_label" should be the spoken duration (e.g. "20 minutes", "30 seconds").
- For CREATE_ALARM: if only time given without date, use today if time hasn't passed, otherwise tomorrow.
  "tomorrow" means next day. "next Friday" means coming Friday (if today is Friday, next week).
- For CREATE_REMINDER: extract both the reminder message AND the target time. If either is missing, ask.
- For CANCEL_EVENT: match against the EXISTING SCHEDULED EVENTS list by id. If ambiguous, ask which one.
- For LIST_EVENTS: determine what type the user wants to see, or "all".
- For DELETE_ALL: determine scope - all events, or just timers/alarms/reminders.
- If critical info is missing, respond with EXACTLY: QUESTION:<your clarifying question>
  Only ask ONE question at a time.
- You may ONLY respond with one of:
  * QUESTION:<clarifying question>
  * Valid JSON (when you have all required info)

RESPONSE JSON FORMATS:

For CREATE_TIMER:
{"intent": "CREATE_TIMER", "target_iso": "ISO8601 with tz offset", "human_time": "friendly time", "duration_label": "20 minutes", "timezone": "%s"}

For CREATE_ALARM:
{"intent": "CREATE_ALARM", "target_iso": "ISO8601 with tz offset", "human_time": "friendly time", "timezone": "%s"}

For CREATE_REMINDER:
{"intent": "CREATE_REMINDER", "target_iso": "ISO8601 with tz offset", "human_time": "friendly time", "message": "the reminder text", "timezone": "%s"}

For LIST_EVENTS:
{"intent": "LIST_EVENTS", "filter_type": "all" or "timer" or "alarm" or "reminder"}

For CANCEL_EVENT:
{"intent": "CANCEL_EVENT", "cancel_id": "the event id from the list above"}

For DELETE_ALL:
{"intent": "DELETE_ALL", "filter_type": "all" or "timer" or "alarm" or "reminder"}

Output ONLY the JSON or QUESTION line. No extra text.""" % (
            now.isoformat(),
            tz_name,
            events_text,
            tz_name,
            tz_name,
            tz_name,
        )

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------
    async def _handle_create(
        self, parsed: dict, original_request: str, tz_name: str
    ) -> str:
        """Returns confirmation message, or None if error already spoken."""
        intent = parsed.get("intent", "")
        type_map = {
            "CREATE_TIMER": "timer",
            "CREATE_ALARM": "alarm",
            "CREATE_REMINDER": "reminder",
        }
        etype = type_map.get(intent, "alarm")

        target_iso = parsed.get("target_iso")
        if not target_iso:
            return "I couldn't figure out the time. Could you try again?"

        # Check if target is in the past
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        now = datetime.now(tz=tz)
        try:
            from datetime import timedelta
            target_dt = datetime.fromisoformat(target_iso)
            if target_dt.tzinfo is None:
                target_dt = target_dt.replace(tzinfo=tz)
            if target_dt < now:
                if etype == "reminder":
                    # Reminders in the past never make sense — reject
                    return "That time has already passed. Could you give me a future time?"
                else:
                    # Alarms/timers: auto-advance to tomorrow
                    target_dt = target_dt + timedelta(days=1)
                    target_iso = target_dt.isoformat()
                    parsed["target_iso"] = target_iso
                    parsed["human_time"] = target_dt.strftime("%-I:%M %p") + " tomorrow"
        except Exception:
            pass

        event = {
            "id": "%s_%d" % (etype, int(time() * 1000)),
            "type": etype,
            "created_at_epoch": int(time()),
            "timezone": parsed.get("timezone", tz_name),
            "target_iso": target_iso,
            "human_time": parsed.get("human_time", target_iso),
            "duration_label": parsed.get("duration_label"),
            "message": parsed.get("message"),
            "source_text": original_request,
            "status": "scheduled",
            "triggered_at_epoch": None,
        }

        events = await self._read_events()
        events.append(event)
        await self._write_events(events)
        await self._update_schedule_md(events, tz_name)

        human_time = event["human_time"]
        if etype == "timer":
            duration = event.get("duration_label") or human_time
            return "%s timer started." % duration
        elif etype == "alarm":
            return "Alarm set for %s." % human_time
        elif etype == "reminder":
            msg = event.get("message") or "that"
            return "Got it. I'll remind you about %s at %s." % (msg, human_time)
        return "Done."

    async def _handle_list(self, parsed: dict) -> str:
        """Returns summary message."""
        filter_type = parsed.get("filter_type", "all")
        events = await self._read_events()
        scheduled = [e for e in events if e.get("status") == "scheduled"]

        if filter_type != "all":
            scheduled = [e for e in scheduled if e.get("type") == filter_type]

        if not scheduled:
            if filter_type == "all":
                return "You don't have anything scheduled right now. You can set a timer, alarm, or reminder."
            else:
                return "You don't have any %ss scheduled. Want to set one?" % filter_type

        # Build a spoken summary
        parts = []
        for e in scheduled:
            etype = e.get("type", "event")
            human = e.get("human_time", "")
            msg = e.get("message")
            dur = e.get("duration_label")

            if etype == "timer" and dur:
                parts.append("A %s timer, firing at %s" % (dur, human))
            elif etype == "alarm":
                parts.append("An alarm at %s" % human)
            elif etype == "reminder" and msg:
                parts.append("A reminder about %s at %s" % (msg, human))
            else:
                parts.append("A %s at %s" % (etype, human))

        count = len(parts)
        if count == 1:
            return "You have one thing scheduled. %s." % parts[0]
        else:
            summary = ". ".join(parts)
            return "You have %d things scheduled. %s." % (count, summary)

    async def _handle_cancel(self, parsed: dict) -> str:
        """Returns confirmation message."""
        cancel_id = parsed.get("cancel_id")
        if not cancel_id:
            return "I couldn't figure out which one to cancel. Could you be more specific?"

        events = await self._read_events()
        target = None
        remaining = []
        for e in events:
            if e.get("id") == cancel_id and e.get("status") == "scheduled":
                target = e
            else:
                remaining.append(e)

        if not target:
            return "I couldn't find that event. It may have already fired or been removed."

        await self._write_events(remaining)

        tz_name = target.get("timezone", "UTC")
        await self._update_schedule_md(remaining, tz_name)

        etype = target.get("type", "event")
        human = target.get("human_time", "")
        return "Done. Your %s %s has been cancelled." % (human, etype)

    async def _handle_delete_all(self, parsed: dict) -> str:
        """Returns confirmation message."""
        filter_type = parsed.get("filter_type", "all")

        if filter_type == "all":
            await self._write_events([])
            tz_name = self.capability_worker.get_timezone() or "UTC"
            await self._update_schedule_md([], tz_name)
            return "Done. Everything has been cleared."
        else:
            events = await self._read_events()
            matching = [e for e in events if e.get("type") == filter_type]
            remaining = [e for e in events if e.get("type") != filter_type]
            await self._write_events(remaining)
            tz_name = self.capability_worker.get_timezone() or "UTC"
            await self._update_schedule_md(remaining, tz_name)
            if not matching:
                return "You didn't have any %ss to delete." % filter_type
            elif len(matching) == 1:
                return "Deleted your %s." % filter_type
            else:
                return "Deleted all %d %ss." % (len(matching), filter_type)

    # ------------------------------------------------------------------
    # Main flow
    # ------------------------------------------------------------------
    def _is_bare_trigger(self, text: str) -> str:
        """Return the event category if user only said a bare trigger word, else empty string."""
        bare = text.strip().lower().rstrip("s")  # "alarms" -> "alarm", "timers" -> "timer"
        if bare in ("alarm", "timer", "reminder", "schedule"):
            return bare
        return ""

    def _build_summary(self, scheduled: list, filter_type: str = "all") -> str:
        """Build a spoken summary string for scheduled events."""
        items = scheduled
        if filter_type != "all":
            items = [e for e in items if e.get("type") == filter_type]

        if not items:
            return ""

        parts = []
        for e in items:
            etype = e.get("type", "event")
            human = e.get("human_time", "")
            msg = e.get("message")
            dur = e.get("duration_label")

            if etype == "timer" and dur:
                parts.append("a %s timer firing at %s" % (dur, human))
            elif etype == "alarm":
                parts.append("an alarm at %s" % human)
            elif etype == "reminder" and msg:
                parts.append("a reminder about %s at %s" % (msg, human))
            else:
                parts.append("a %s at %s" % (etype, human))

        if len(parts) == 1:
            return "You have %s." % parts[0]
        return "You have %d things scheduled. %s." % (len(parts), ". ".join(parts))

    async def _ask_followup(self, category: str) -> str:
        """If user said a bare trigger, show existing events of that type then ask what to do."""
        events = await self._read_events()
        scheduled = [e for e in events if e.get("status") == "scheduled"]

        if category == "schedule":
            if scheduled:
                summary = self._build_summary(scheduled, "all")
                return await self.capability_worker.run_io_loop(
                    "%s What would you like to do?" % summary
                )
            return await self.capability_worker.run_io_loop(
                "You don't have anything scheduled. Want to set a timer, alarm, or reminder?"
            )

        type_events = [e for e in scheduled if e.get("type") == category]
        if type_events:
            summary = self._build_summary(scheduled, category)
            return await self.capability_worker.run_io_loop(
                "%s What would you like to do?" % summary
            )
        return await self.capability_worker.run_io_loop(
            "You don't have any %ss. Want to set one?" % category
        )

    async def _process_request(self, user_text: str, category: str = "") -> str:
        """Process a single user request.
        Returns:
            str  — confirmation/response message to speak
            None — user quit (via QUESTION loop)
        """
        original_request = user_text
        lower = user_text.strip().lower()

        # Fast-path: delete / clear / remove commands
        if "delete" in lower or "clear" in lower or "remove" in lower:
            if "timer" in lower:
                return await self._handle_delete_all({"filter_type": "timer"})
            elif "alarm" in lower:
                return await self._handle_delete_all({"filter_type": "alarm"})
            elif "reminder" in lower:
                return await self._handle_delete_all({"filter_type": "reminder"})
            elif "all" in lower or "everything" in lower:
                return await self._handle_delete_all({"filter_type": "all"})
            elif category in ("alarm", "timer", "reminder"):
                return await self._handle_delete_all({"filter_type": category})
            else:
                return await self._handle_delete_all({"filter_type": "all"})

        # Fast-path: list commands
        if any(phrase in lower for phrase in ("list all", "list everything", "what do i have", "show all", "show everything", "show me everything")):
            return await self._handle_list({"filter_type": "all"})
        for etype in ("timer", "alarm", "reminder"):
            if ("list" in lower or "show" in lower) and etype in lower:
                return await self._handle_list({"filter_type": etype})

        # Handle bare affirmatives with category context (e.g. "yes" after "Want to set one?")
        affirmatives = {"yes", "yeah", "yep", "sure", "ok", "okay", "yea", "ya"}
        if lower in affirmatives and category:
            user_text = "set a %s" % category
            lower = user_text.lower()

        # If we have category context, prepend it for the LLM
        if category and category != "schedule":
            # Don't add context if user says "all", "everything", or mentions a different type
            if category not in lower and "all" not in lower and "everything" not in lower:
                other_types = {"timer", "alarm", "reminder"} - {category}
                if not any(t in lower for t in other_types):
                    user_text = "%s (context: user is working with %ss)" % (user_text, category)

        # Get timezone
        tz_name = self.capability_worker.get_timezone()
        if not tz_name:
            tz_name = "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
            tz_name = "UTC"

        now = datetime.now(tz=tz)
        events = await self._read_events()
        system_prompt = self._build_system_prompt(now, tz_name, events)
        history = []

        for _ in range(6):
            llm_response = self.capability_worker.text_to_text_response(
                user_text, history, system_prompt
            )

            self.worker.editor_logging_handler.info(
                "[TAR] user: %s" % user_text
            )
            self.worker.editor_logging_handler.info(
                "[TAR] llm: %s" % llm_response
            )

            history.append({"role": "user", "content": user_text})

            if isinstance(llm_response, str):
                stripped = llm_response.strip()

                # Handle QUESTION responses
                if stripped.startswith("QUESTION:"):
                    history.append({"role": "assistant", "content": stripped})
                    question = stripped.split("QUESTION:", 1)[1].strip()
                    user_text = await self.capability_worker.run_io_loop(question)
                    if _wants_to_quit(user_text):
                        return None
                    continue

                # Strip markdown fences if present
                if stripped.startswith("```"):
                    stripped = stripped.strip("`").strip()
                    if stripped.startswith("json"):
                        stripped = stripped[4:].strip()

            # Parse JSON
            try:
                if isinstance(llm_response, str):
                    parsed = json.loads(stripped)
                else:
                    parsed = llm_response
            except Exception:
                return "I had trouble understanding that. Could you try again?"

            intent = parsed.get("intent", "")

            if intent in ("CREATE_TIMER", "CREATE_ALARM", "CREATE_REMINDER"):
                return await self._handle_create(parsed, original_request, tz_name)
            elif intent == "LIST_EVENTS":
                return await self._handle_list(parsed)
            elif intent == "CANCEL_EVENT":
                return await self._handle_cancel(parsed)
            elif intent == "DELETE_ALL":
                return await self._handle_delete_all(parsed)
            else:
                return "I'm not sure what you'd like to do. You can set timers, alarms, or reminders, or ask me to list or cancel them."

        return "I asked too many questions. Let's start over — just tell me what you need."

    async def first_setup(self):
        try:
            user_text = await self.capability_worker.wait_for_complete_transcription()
            if not user_text or not user_text.strip():
                await self.capability_worker.speak(
                    "I didn't catch that. You can set timers, alarms, or reminders. Just tell me what you need."
                )
                return
            if _wants_to_quit(user_text):
                await self.capability_worker.speak("Quitting ability.")
                return

            # If user just said a bare trigger word, ask what they want to do
            category = ""
            bare = self._is_bare_trigger(user_text)
            if bare:
                category = bare
                user_text = await self._ask_followup(bare)
                if not user_text or not user_text.strip():
                    await self.capability_worker.speak(
                        "I didn't catch that. Let me know if you need anything."
                    )
                    return
                if _wants_to_quit(user_text):
                    await self.capability_worker.speak("Quitting ability.")
                    return

            # Process the first request
            msg = await self._process_request(user_text, category)
            if msg is None:
                await self.capability_worker.speak("Quitting ability.")
                return

            # Multi-action loop: combine confirmation with "Anything else?" in one speech act
            while True:
                user_text = await self.capability_worker.run_io_loop(
                    "%s Anything else?" % msg
                )
                if not user_text or not user_text.strip():
                    break
                if _wants_to_exit(user_text):
                    break
                msg = await self._process_request(user_text)
                if msg is None:
                    break

            await self.capability_worker.speak("All done. Handing you back.")

        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[TAR] first_setup error: %s" % e
            )
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Please try again."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        try:
            self.worker = worker
            self.capability_worker = CapabilityWorker(self)
            self.worker.editor_logging_handler.info(
                "[TAR] Timers Alarms Reminders capability triggered"
            )
            self.worker.session_tasks.create(self.first_setup())
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[TAR] call() error: %s" % e
            )
