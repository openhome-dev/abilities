import json
import re
import requests
from datetime import datetime, timedelta
from time import time as epoch_now
from zoneinfo import ZoneInfo
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# CONFIGURATION
# =============================================================================

CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
DEFAULT_TIMEZONE = "America/Los_Angeles"
LOCAL_TZ = None  # set in call() via SDK get_timezone()

LATE_NIGHT_CUTOFF = 4

EVENTS_CACHE_FILE = "gcal_events_cache.json"
EVENTS_CACHE_MAX_AGE = 90  # seconds — fall back to API if cache is older than this

# =============================================================================
# TIMEZONE / DATE HELPERS
# =============================================================================


def get_local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def get_utc_offset_str() -> str:
    offset = get_local_now().utcoffset()
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def get_effective_today() -> datetime:
    now = get_local_now()
    if now.hour < LATE_NIGHT_CUTOFF:
        return now - timedelta(days=1)
    return now


def friendly_date_label(date_str: str) -> str:
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return date_str

    effective = get_effective_today().date()
    delta_days = (target - effective).days

    if delta_days == 0:
        return "today"
    elif delta_days == 1:
        return "tomorrow"
    elif 2 <= delta_days <= 6:
        return f"this {target.strftime('%A')}"
    elif 7 <= delta_days <= 13:
        return f"next {target.strftime('%A')}"
    else:
        day = target.day
        if 11 <= day <= 13:
            suffix = "th"
        elif day % 10 == 1:
            suffix = "st"
        elif day % 10 == 2:
            suffix = "nd"
        elif day % 10 == 3:
            suffix = "rd"
        else:
            suffix = "th"
        return f"{target.strftime('%B')} {day}{suffix}"


def get_time_bucket(hour: int) -> str:
    """Return time bucket based on hour."""
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def get_today_context() -> dict:
    effective = get_effective_today()
    real_now = get_local_now()
    hour = real_now.hour
    return {
        "today": effective.strftime("%Y-%m-%d"),
        "day_name": effective.strftime("%A"),
        "current_time": real_now.strftime("%-I:%M %p"),
        "late_night": real_now.hour < LATE_NIGHT_CUTOFF,
        "time_bucket": get_time_bucket(hour),
        "hour": hour,
    }

# =============================================================================
# LLM PROMPTS
# =============================================================================


# Behavioral context injected into extraction prompts so the LLM understands
# relative time phrases ("this afternoon", "tonight", "this evening") correctly.
TIME_CONTEXT_BLOCK = """RIGHT NOW it is {current_time} on {day_name}, {today}. It is currently {time_bucket}.
{late_night_note}
"Today" = {today}. "Tomorrow" = the day after {today}.
If they say a day of the week, use the NEXT occurrence of that day after {today}.

RELATIVE TIME INTERPRETATION:
- "this morning" = today before 12 PM
- "this afternoon" = today 12 PM to 5 PM
- "this evening" / "tonight" = today 5 PM to 10 PM
- "later today" = a few hours from now (use {current_time} as reference)
- "end of day" = around 5 PM or 6 PM
- "lunch" / "lunchtime" = around 12 PM
- "after work" = around 5 PM or 6 PM
- If the user says a bare time like "at 3" without AM/PM, infer based on context:
  - If it's currently morning and they say "at 3", they likely mean 3 PM
  - If it's currently evening and they say "at 7", they likely mean 7 PM today or tomorrow morning

OFFICE SLANG:
- "EOD" or "end of day" = 5 PM or 6 PM
- "COB" = end of business day = 5 PM
- "bump this/it" = reschedule
- "circle back" = revisit or reschedule
- "loop in [name]" = invite that person
- "block time" / "block off" = schedule a hold
- "spin up a meeting" = schedule a meeting
- "table it" / "drop it" = cancel or remove"""

# Voice personality prompt — shapes how the LLM generates spoken output.
VOICE_SYSTEM_PROMPT = """You are a sharp, friendly assistant who manages someone's calendar like a trusted EA.

Rules:
- Keep responses to 2-3 sentences max. This is voice, not text.
- Never feel like a phone menu. Talk like a real person who knows what's going on.
- Use natural acknowledgments: "On it", "Sure thing", "Let me grab that", "Got it"
- Vary your phrasing — don't repeat the same confirmation every time.
- When summarizing calendar events, mention time, title, and relevant context naturally.
- No bullet points, numbered lists, or markdown formatting.
- No emojis, no quotation marks around titles, no special characters.
- When reading email addresses, say "at" instead of "@".
- Speak directly to the person (use 'you').
- Do NOT be sycophantic. Be helpful and direct, not stiff.
- You understand office vernacular: "bump" means reschedule, "circle back" means revisit or reschedule,
  "loop in" means invite someone, "table it" means drop/cancel for now, "block time" means schedule a hold,
  "spin up a meeting" means schedule one, "EOD" means end of day around 5 PM."""

EXTRACT_MEETING_PROMPT = """You are a meeting detail extractor. Extract meeting information from the user's input.
Return ONLY a JSON object with these fields:
- "summary": string (meeting title/name)
- "date": string (date in YYYY-MM-DD format, or null if not specified)
- "time": string (time in HH:MM 24-hour format, or null if not specified)
- "duration_minutes": integer (duration in minutes, default 30 if not specified)
- "duration_explicit": boolean (true ONLY if the user explicitly stated a duration like '1 hour', '45 minutes', or an end time. false if you used the 30-minute default)
- "description": string (any additional notes, or empty string)
- "attendee_names": list of strings (names of people mentioned as attendees/participants, or empty list. e.g. if user says 'meeting with Jake', include 'Jake')
- "recurring_weekly": boolean (true if user says "every week", "weekly", "recurring", "every Monday", "weekly standup", etc. false otherwise)
- "reminder_minutes": integer or null (ONLY if the user explicitly requests a specific reminder window, e.g. "remind me 15 minutes before", "give me a 10 minute heads up", "ping me 5 min early". null if not specified)

IMPORTANT for recurring events: If "recurring_weekly" is true and the user names a specific day of the week (e.g. "every Friday", "every Monday"), resolve "date" to the next upcoming occurrence of that weekday using the today date from the time context below. Do NOT leave "date" as null in this case.

""" + TIME_CONTEXT_BLOCK + """

User input: "{user_input}"

Return ONLY valid JSON, no other text."""

EXTRACT_DATES_PROMPT = """""" + TIME_CONTEXT_BLOCK + """

The user said: "{user_input}"

Extract the date(s) the user is asking about.
Return ONLY a JSON array of objects like:
[{{"date": "YYYY-MM-DD", "label": "human readable label like tomorrow or Friday"}}]

If no specific date is mentioned, assume today ({today}).
Reply with ONLY valid JSON, no extra text."""

EXTRACT_RESCHEDULE_PROMPT = """You are a reschedule detail extractor. The user wants to move or reschedule a calendar event.
Extract the following from their input and return ONLY a JSON object:
- "event_hint": string (what they call the event — a name, keyword, or description fragment)
- "original_time": string or null (if they mention the event's current time, e.g. 'the 6 o'clock meeting', give HH:MM 24-hour format)
- "original_date": string or null (if they mention the event's current date, give YYYY-MM-DD)
- "new_date": string or null (the new date in YYYY-MM-DD, or null if not changing date)
- "new_time": string or null (the new time in HH:MM 24-hour format, or null if not changing time)
- "new_duration_minutes": integer or null (new duration if explicitly mentioned, otherwise null)

""" + TIME_CONTEXT_BLOCK + """

User input: "{user_input}"

Return ONLY valid JSON, no other text."""

FUZZY_MATCH_PROMPT = """The user wants to modify a calendar event. They described it as: "{event_hint}"
{original_time_hint}

Here are the upcoming events on their calendar (numbered):
{event_list}

Which event is the BEST match for what the user is referring to?
Reply with ONLY the number (1, 2, 3...) of the best match.
If absolutely none match, reply with NONE.
Reply with ONLY the number or NONE."""

EXTRACT_INVITE_PROMPT = """The user wants to add someone to an EXISTING calendar event.
Extract the following from their input and return ONLY a JSON object:
- "event_hint": string (how they describe the event — a name, keyword, or 'that meeting', 'the one we just made', etc.)
- "event_date": string or null (if they mention a date for the event, YYYY-MM-DD format)
- "event_time": string or null (if they mention the event's time, HH:MM 24-hour format)
- "attendee_names": list of strings (the names of people they want to invite)

""" + TIME_CONTEXT_BLOCK + """

User input: "{user_input}"

Return ONLY valid JSON, no other text."""

EXTRACT_REMOVE_ATTENDEE_PROMPT = """The user wants to REMOVE someone from an existing calendar event (uninvite them).
Extract the following from their input and return ONLY a JSON object:
- "event_hint": string (how they describe the event — a name, keyword, or 'that meeting', etc.)
- "event_date": string or null (if they mention a date for the event, YYYY-MM-DD format)
- "event_time": string or null (if they mention the event's time, HH:MM 24-hour format)
- "attendee_names": list of strings (the names of people they want to REMOVE/UNINVITE)

IMPORTANT: The user is asking to remove or uninvite these people. Extract their names even if the phrasing is 'uninvite X', 'remove X from', 'take X off', etc.

""" + TIME_CONTEXT_BLOCK + """

User input: "{user_input}"

Return ONLY valid JSON, no other text."""

EXIT_WORDS = ["stop", "exit", "quit", "done", "bye", "goodbye", "never mind", "go back"]

YES_WORDS = ["yes", "yeah", "yep", "yup", "sure", "ok", "okay", "sounds good",
             "go ahead", "do it", "correct", "right", "absolutely", "definitely", "please"]
NO_WORDS = ["no", "nah", "nope", "cancel", "don't", "stop", "never mind", "not"]


class GcalIntegrationCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    access_token: str = None
    last_api_error: str = None
    contacts: dict = None
    last_event: dict = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        global LOCAL_TZ
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        tz = self.capability_worker.get_timezone() or DEFAULT_TIMEZONE
        LOCAL_TZ = ZoneInfo(tz)
        self.access_token = None
        self.last_api_error = ""
        self.contacts = {}
        self.last_event = None  # tracks the most recently touched event for "that meeting" references
        self.worker.session_tasks.create(self.run_calendar())

    # =========================================================================
    # CONTACTS
    # =========================================================================

    async def load_contacts(self) -> dict:
        """
        Load contacts.json from the ability directory using SDK file helpers.
        Supports two formats:
          Simple:  {"Name": "email@example.com"}
          Aliases: {"Name": {"email": "email@example.com", "aliases": ["Von", "Vonne"]}}
        Normalizes to: {"Name": {"email": "...", "aliases": [...]}}
        """
        try:
            raw = await self.capability_worker.read_file("contacts.json", in_ability_directory=True)
            if not raw:
                self.worker.editor_logging_handler.info("[GCal] contacts.json is empty — attendee features disabled.")
                return {}
            data = json.loads(raw)
            # Normalize
            contacts = {}
            for name, value in data.items():
                if isinstance(value, str):
                    contacts[name] = {"email": value, "aliases": []}
                elif isinstance(value, dict):
                    contacts[name] = {
                        "email": value.get("email", ""),
                        "aliases": value.get("aliases", []),
                    }
            self.worker.editor_logging_handler.info(f"[GCal] Loaded {len(contacts)} contacts.")
            return contacts
        except Exception as e:
            self.worker.editor_logging_handler.info(f"[GCal] No contacts.json found or read error: {e} — attendee features disabled.")
            return {}

    def detect_attendees(self, user_input: str, llm_names: list = None) -> list:
        """
        Use LLM to match names from user input against the contacts list.
        Includes aliases so STT mishearings (Von→Vaughn, creche→Chris) get matched.
        """
        if not self.contacts:
            return []

        # Build a contact list with aliases for the LLM
        contact_lines = []
        for name, info in self.contacts.items():
            aliases = info.get("aliases", [])
            if aliases:
                contact_lines.append(f"- {name} (also sounds like: {', '.join(aliases)})")
            else:
                contact_lines.append(f"- {name}")
        contacts_list = "\n".join(contact_lines)

        name_hint = ""
        if llm_names:
            name_hint = (
                f"\nThe speech-to-text system detected these names: {', '.join(llm_names)}. "
                "These may be misspelled or phonetically approximated. "
                "Match them to the closest contact name using the aliases if needed."
            )

        prompt = (
            f'The user said: "{user_input}"\n'
            f"{name_hint}\n"
            f"Here is the list of known contacts with their phonetic aliases:\n{contacts_list}\n\n"
            "Which of these contacts (if any) did the user mention as attendees or participants?\n"
            "IMPORTANT: Match against BOTH the contact name AND their aliases. "
            "For example, if the user says 'Von' and a contact has 'Von' as an alias, that's a match.\n"
            "Return ONLY a JSON array of the matching contact names (use the primary name, not the alias).\n"
            "If no contacts are mentioned, return [].\n"
            "Reply with ONLY valid JSON, no other text."
        )

        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        self.worker.editor_logging_handler.info(f"[GCal] Attendee detection raw: {clean}")

        try:
            names = json.loads(clean)
            attendees = []
            for name in names:
                for contact_name, contact_info in self.contacts.items():
                    if contact_name.lower() == name.lower():
                        attendees.append({"name": contact_name, "email": contact_info["email"]})
                        break
            return attendees
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Attendee detection parse error: {e}")
            return []

    # =========================================================================
    # AUTH
    # =========================================================================

    def get_access_token(self) -> bool:
        try:
            token = self.capability_worker.get_token("google")
            if token:
                self.access_token = token
                self.worker.editor_logging_handler.info("[GCal] Got token from platform")
                return True
            else:
                self.worker.editor_logging_handler.error("[GCal] No Google token available. Link your Google account in OpenHome settings.")
                return False
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Auth exception: {e}")
            return False

    # =========================================================================
    # CALENDAR API
    # =========================================================================

    def create_event(self, summary: str, start_iso: str, end_iso: str,
                     description: str = "", attendees: list = None,
                     recurring_weekly: bool = False) -> dict:
        event_body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": DEFAULT_TIMEZONE},
            "end": {"dateTime": end_iso, "timeZone": DEFAULT_TIMEZONE},
        }
        if recurring_weekly:
            event_body["recurrence"] = ["RRULE:FREQ=WEEKLY"]
        if attendees:
            event_body["attendees"] = [{"email": a["email"]} for a in attendees]

        params = {}
        if attendees:
            params["sendUpdates"] = "all"

        self.worker.editor_logging_handler.info(f"[GCal] Creating event: {json.dumps(event_body)}")

        try:
            resp = requests.post(
                CALENDAR_API_URL,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                json=event_body,
                params=params,
            )
            if resp.ok:
                self.worker.editor_logging_handler.info(f"[GCal] Event created successfully ({resp.status_code}).")
                return resp.json()
            else:
                self.worker.editor_logging_handler.error(
                    f"[GCal] Create event failed ({resp.status_code}): {resp.text[:300]}"
                )
                self.last_api_error = f"status {resp.status_code}"
                try:
                    err_msg = resp.json().get("error", {}).get("message", "")
                    if err_msg:
                        self.last_api_error = err_msg
                except Exception:
                    pass
                return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Create event exception: {e}")
            self.last_api_error = str(e)
            return None

    def update_event(self, event_id: str, updates: dict) -> dict:
        """PATCH an existing calendar event. Returns updated event dict or None."""
        url = f"{CALENDAR_API_URL}/{event_id}"
        self.worker.editor_logging_handler.info(f"[GCal] Updating event {event_id}: {json.dumps(updates)}")

        try:
            resp = requests.patch(
                url,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                json=updates,
                params={"sendUpdates": "all"},
            )
            if resp.ok:
                self.worker.editor_logging_handler.info(f"[GCal] Event updated successfully ({resp.status_code}).")
                return resp.json()
            else:
                self.worker.editor_logging_handler.error(
                    f"[GCal] Update event failed ({resp.status_code}): {resp.text[:300]}"
                )
                self.last_api_error = f"status {resp.status_code}"
                try:
                    err_msg = resp.json().get("error", {}).get("message", "")
                    if err_msg:
                        self.last_api_error = err_msg
                except Exception:
                    pass
                return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Update event exception: {e}")
            self.last_api_error = str(e)
            return None

    def delete_event(self, event_id: str) -> bool:
        """DELETE a calendar event. Returns True on success."""
        url = f"{CALENDAR_API_URL}/{event_id}"
        self.worker.editor_logging_handler.info(f"[GCal] Deleting event {event_id}")

        try:
            resp = requests.delete(
                url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                params={"sendUpdates": "all"},
            )
            if resp.status_code in (200, 204):
                self.worker.editor_logging_handler.info(f"[GCal] Event deleted successfully ({resp.status_code}).")
                self.last_event = None  # event no longer exists
                return True
            else:
                self.worker.editor_logging_handler.error(
                    f"[GCal] Delete event failed ({resp.status_code}): {resp.text[:300]}"
                )
                self.last_api_error = f"status {resp.status_code}"
                try:
                    err_msg = resp.json().get("error", {}).get("message", "")
                    if err_msg:
                        self.last_api_error = err_msg
                except Exception:
                    pass
                return False
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Delete event exception: {e}")
            self.last_api_error = str(e)
            return False

    def get_event_by_id(self, event_id: str) -> dict:
        """Fetch a single event by ID to get its current state."""
        url = f"{CALENDAR_API_URL}/{event_id}"
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            if resp.ok:
                return resp.json()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] get_event_by_id error: {e}")
        return None

    def detect_conflicts(self, start_iso: str, end_iso: str, exclude_event_id: str = None) -> list:
        """
        Check if a proposed time slot conflicts with existing events.
        Returns a list of conflicting event dicts (with summary, start, end).
        """
        try:
            new_start = datetime.fromisoformat(start_iso)
            new_end = datetime.fromisoformat(end_iso)
        except Exception:
            return []

        # Get events for the day of the proposed slot
        date_str = new_start.strftime("%Y-%m-%d")
        events = self.list_events_for_date(date_str)
        conflicts = []

        for ev in events:
            # Skip the event itself (for reschedule)
            if exclude_event_id and ev.get("id") == exclude_event_id:
                continue

            ev_start_str = ev.get("start", {}).get("dateTime", "")
            ev_end_str = ev.get("end", {}).get("dateTime", "")
            if not ev_start_str or not ev_end_str:
                continue

            try:
                ev_start = datetime.fromisoformat(ev_start_str.replace("Z", "+00:00"))
                ev_end = datetime.fromisoformat(ev_end_str.replace("Z", "+00:00"))

                # Make naive for comparison if needed
                if new_start.tzinfo is None:
                    ev_start = ev_start.replace(tzinfo=None)
                    ev_end = ev_end.replace(tzinfo=None)

                # Overlap check: new event starts before existing ends AND new event ends after existing starts
                if new_start < ev_end and new_end > ev_start:
                    conflicts.append(ev)
            except Exception:
                continue

        return conflicts

    def format_conflict_warning(self, conflicts: list) -> str:
        """Format a spoken warning about conflicting events."""
        if len(conflicts) == 1:
            c = conflicts[0]
            title = c.get("summary", "another event")
            c_time = self.format_event_time(c)
            return f"Heads up, that overlaps with {title} at {c_time}."
        else:
            titles = [c.get("summary", "an event") for c in conflicts]
            return f"Heads up, that overlaps with {' and '.join(titles)}."

    def list_events_for_date(self, date_str: str) -> list:
        time_min = f"{date_str}T00:00:00"
        time_max = f"{date_str}T23:59:59"
        offset_str = get_utc_offset_str()
        try:
            resp = requests.get(
                CALENDAR_API_URL,
                headers={"Authorization": f"Bearer {self.access_token}"},
                params={
                    "timeMin": f"{time_min}{offset_str}",
                    "timeMax": f"{time_max}{offset_str}",
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "timeZone": DEFAULT_TIMEZONE,
                },
            )
            self.worker.editor_logging_handler.info(f"[GCal] List events for {date_str}: {resp.status_code}")
            if resp.ok:
                return resp.json().get("items", [])
            else:
                self.worker.editor_logging_handler.error(
                    f"[GCal] List events failed ({resp.status_code}): {resp.text[:200]}"
                )
                return []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] List events exception: {e}")
            return []

    def list_events_in_range(self, start_date: str, end_date: str) -> list:
        """List all events between two YYYY-MM-DD dates (inclusive)."""
        offset_str = get_utc_offset_str()
        time_min = f"{start_date}T00:00:00{offset_str}"
        time_max = f"{end_date}T23:59:59{offset_str}"
        try:
            resp = requests.get(
                CALENDAR_API_URL,
                headers={"Authorization": f"Bearer {self.access_token}"},
                params={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "timeZone": DEFAULT_TIMEZONE,
                    "maxResults": 50,
                },
            )
            self.worker.editor_logging_handler.info(
                f"[GCal] List events {start_date} to {end_date}: {resp.status_code}"
            )
            if resp.ok:
                return resp.json().get("items", [])
            return []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Range list exception: {e}")
            return []

    # =========================================================================
    # HELPERS
    # =========================================================================

    def get_late_night_note(self, ctx: dict) -> str:
        if ctx["late_night"]:
            return (
                "IMPORTANT: It is currently very late at night / early morning. "
                "The user likely still considers it the same day as yesterday. "
                f"Treat 'today' as {ctx['today']} and 'tomorrow' as the day after that."
            )
        return ""

    def safe_email(self, obj) -> str:
        """Safely extract a lowercase email string from a dict or return empty string."""
        if isinstance(obj, dict):
            email = obj.get("email", "")
            return email.lower() if isinstance(email, str) else ""
        return ""

    def interpret_yes_no(self, user_input: str) -> bool:
        lower = user_input.lower().strip()
        for word in YES_WORDS:
            if word in lower:
                return True
        for word in NO_WORDS:
            if word in lower:
                return False

        prompt = (
            f'The user was asked a yes/no question and replied: "{user_input}"\n'
            "Did they mean yes or no? Reply with ONLY the word YES or NO."
        )
        result = self.capability_worker.text_to_text_response(
            prompt,
            system_prompt="You interpret yes/no intent. Reply with one word only.",
        )
        return "YES" in result.strip().upper()

    def parse_confirmation_response(self, response: str) -> dict:
        """
        Parse a user's response to a confirmation prompt.
        Returns a dict with:
          - "confirmed": True/False — did they agree to the proposed action?
          - "followup": str or None — any additional request tacked on
          - "correction": True — if the 'no' part contains a time/date correction

        Examples:
          "Sounds good." -> {"confirmed": True, "followup": None}
          "Sounds good. But can you invite Vaughn?" -> {"confirmed": True, "followup": "can you invite Vaughn?"}
          "No, make it 3 PM" -> {"confirmed": False, "followup": None, "correction": True}
          "No. No. You need to reschedule." -> {"confirmed": False, "followup": "You need to reschedule."}
        """
        lower = response.lower().strip()

        # Check for yes first
        has_yes = any(w in lower for w in YES_WORDS)
        has_no = any(w in lower for w in NO_WORDS)

        # Compound: "sounds good. but can you also X"
        # Split on common connectors
        followup = None
        confirmed = False

        if has_yes:
            confirmed = True
            # Extract everything after the yes-word as a potential follow-up.
            # Strategy: strip the yes-phrase from the front, check if the remainder
            # contains an actionable calendar intent.
            yes_phrases = [
                "sounds good", "go ahead", "do it",
                "yes", "yeah", "yep", "yup", "sure", "ok", "okay",
                "correct", "right", "absolutely", "definitely", "please",
                "good",
            ]
            remainder = response
            # Remove the first matching yes-phrase from the response
            for phrase in yes_phrases:
                pattern = re.compile(r"\b" + re.escape(phrase) + r"\b[.,!]?\s*", re.IGNORECASE)
                match = pattern.search(remainder)
                if match and match.start() < 10:  # must be near the start
                    remainder = remainder[:match.start()] + remainder[match.end():]
                    remainder = remainder.strip()
                    break

            # Strip leading connectors (may be chained: "can you make sure to")
            prev = None
            while remainder != prev:
                prev = remainder
                remainder = re.sub(
                    r"^(?:but|also|and|can you|could you|please|make sure to|make sure|then)\s+",
                    "", remainder, flags=re.IGNORECASE,
                ).strip()

            if remainder:
                # Check if what's left looks like a calendar action
                remainder_intent = self.classify_intent(remainder)
                if remainder_intent not in ("EXIT", "SCHEDULE"):
                    # Clear intent detected (invite, rename, reschedule, etc.)
                    followup = remainder
                elif remainder_intent == "SCHEDULE" and any(
                    k in remainder.lower() for k in [
                        "invite", "add", "rename", "move", "cancel", "delete",
                        "reschedule", "remove", "uninvite", "who's",
                    ]
                ):
                    # Intent keywords present but classifier defaulted to SCHEDULE
                    followup = remainder

        elif has_no:
            confirmed = False
            # Check if it's a correction ("no, make it 3pm") vs redirect ("no, reschedule it instead")
            # Strip out the no-words and see what's left
            remainder = response
            for w in ["no", "nah", "nope"]:
                remainder = re.sub(rf"\b{w}\b[.,!]?\s*", "", remainder, flags=re.IGNORECASE)
            remainder = remainder.strip()

            if remainder:
                # Is this a redirect/new action?
                redirect_intent = self.classify_intent(remainder)
                if redirect_intent != "SCHEDULE":
                    # They want a specific different action
                    followup = remainder
                # Otherwise it might be a correction (time/date) — handled by caller

        else:
            # Ambiguous — fall back to LLM interpretation
            confirmed = self.interpret_yes_no(response)

        self.worker.editor_logging_handler.info(
            f"[GCal] Parsed confirmation: confirmed={confirmed} followup={'yes' if followup else 'no'} | '{response}'"
        )

        return {
            "confirmed": confirmed,
            "followup": followup,
        }

    async def dispatch_followup(self, followup_text: str):
        """
        Route follow-up requests from confirmations through the multi-intent
        parser so compound follow-ups work too.
        """
        actions = self.parse_multi_intent(followup_text)
        self.worker.editor_logging_handler.info(
            f"[GCal] Dispatching followup ({len(actions)}): {actions}"
        )
        for action_text in actions:
            intent = self.classify_intent(action_text)
            if intent == "EXIT":
                break
            await self.execute_action(action_text)

    def parse_multi_intent(self, user_input: str) -> list:
        """
        Split a compound user message into individual action strings.
        e.g. "Reschedule the standup to 3, invite Melody, and cancel the sync"
        -> ["Reschedule the standup to 3", "invite Melody", "cancel the sync"]

        For simple single-intent messages, returns a single-item list.
        """
        # Quick check: if the message clearly has only one intent, skip LLM
        conjunctions = [" and ", " and,", " also ", " also,", " plus ", " then ",
                        ", and ", ". and ", ". also ", ". then ", ". plus "]
        has_conjunction = any(c in user_input.lower() for c in conjunctions)

        # Check if multiple intent keywords appear
        intent_keywords = [
            "schedule", "book", "create", "reschedule", "move",
            "cancel", "delete", "invite", "uninvite",
            "remove", "rename", "call it", "what's on", "what do i have",
            "who's on", "who's attending",
        ]
        keyword_hits = sum(1 for k in intent_keywords if k in user_input.lower())

        if not has_conjunction or keyword_hits <= 1:
            return [user_input]

        # Use LLM to split compound requests
        prompt = (
            f'The user made a compound calendar request: "{user_input}"\n\n'
            "Split this into separate, standalone action requests. Each should be a complete "
            "phrase that could be understood on its own.\n\n"
            "Rules:\n"
            '- If the user says "that meeting" or "it" in later parts, keep those references as-is '
            "(context will be resolved separately).\n"
            "- Each action should be one of: schedule, reschedule, delete/cancel, invite, "
            "remove/uninvite, rename, list events, or query attendees.\n"
            "- Return a JSON array of strings.\n"
            '- If there\'s really only one action, return a single-item array.\n\n'
            "Return ONLY valid JSON, no other text."
        )
        raw = self.capability_worker.text_to_text_response(
            prompt,
            system_prompt="You split compound calendar requests into individual actions. Return only a JSON array.",
        )
        clean = raw.replace("```json", "").replace("```", "").strip()
        self.worker.editor_logging_handler.info(f"[GCal] Multi-intent parse: {clean}")

        try:
            actions = json.loads(clean)
            if isinstance(actions, list) and len(actions) > 0:
                return [a.strip() for a in actions if isinstance(a, str) and a.strip()]
        except Exception:
            pass

        return [user_input]

    async def execute_action(self, action_text: str):
        """Route a single action string to the appropriate handler."""
        intent = self.classify_intent(action_text)
        self.worker.editor_logging_handler.info(f"[GCal] Action: '{action_text}' -> {intent}")

        if intent == "LIST":
            await self.handle_list_events(action_text)
        elif intent == "QUERY_ATTENDEES":
            await self.handle_query_attendees(action_text)
        elif intent == "RENAME":
            await self.handle_rename_event(action_text)
        elif intent == "MAKE_RECURRING":
            await self.handle_make_recurring(action_text)
        elif intent == "RESCHEDULE":
            await self.handle_reschedule_event(action_text)
        elif intent == "INVITE":
            await self.handle_add_attendee(action_text)
        elif intent == "DELETE":
            await self.handle_delete_event(action_text)
        elif intent == "REMOVE_ATTENDEE":
            await self.handle_remove_attendee(action_text)
        elif intent == "ACCEPT_INVITE":
            await self.handle_respond_to_invite(action_text, "accepted")
        elif intent == "DECLINE_INVITE":
            await self.handle_respond_to_invite(action_text, "declined")
        elif intent == "SET_REMINDER":
            await self.handle_set_reminder(action_text)
        elif intent == "SCHEDULE":
            await self.handle_schedule_event(action_text)

    def classify_intent(self, user_input: str) -> str:
        lower = user_input.lower()

        if any(w in lower for w in EXIT_WORDS):
            return "EXIT"

        # "cancel" handling: bare "cancel" / "cancel that" = EXIT,
        # but "cancel [event name/description]" = DELETE
        if "cancel" in lower:
            # Strip "cancel" and see what's left
            after_cancel = re.sub(r"^.*?\bcancel\b\s*", "", lower, count=1).strip()
            # Remove trailing/leading punctuation before comparing
            after_cancel = after_cancel.strip(".,!?")
            # Bare cancel, or only vague words left → EXIT
            exit_remainders = ["", "that", "it", "this", "never mind", "nope"]
            if after_cancel in exit_remainders:
                return "EXIT"
            # Otherwise fall through — DELETE check below will catch it

        # ── QUERY_ATTENDEES: who's on / attending a specific event ──
        if any(s in lower for s in [
            "who's on", "whos on", "who is on",
            "who's attending", "whos attending", "who is attending",
            "who's invited", "whos invited", "who is invited",
            "who's going", "whos going", "who is going",
            "who's in", "whos in", "who is in",
            "attendees for", "attendees of", "guest list",
        ]):
            return "QUERY_ATTENDEES"

        # ── RENAME: change the title/name of an existing event ──
        if any(s in lower for s in [
            "rename", "change the name", "change the title",
            "call it", "name it", "retitle",
            "change it to", "update the name", "update the title",
        ]):
            return "RENAME"

        # ── LIST: user wants to see what's on their calendar ──
        list_signals = [
            "what's on", "whats on", "what is on",
            "what do i have", "what meetings do i have",
            "upcoming", "what's next", "whats next", "any meetings",
            "do i have any", "show me", "check my",
            "what are my", "tell me my", "events on",
            "what's happening", "whats happening", "what is happening",
            "what's going on", "whats going on",
            "am i free", "am i busy",
        ]
        if any(s in lower for s in list_signals):
            return "LIST"

        # ── REMOVE_ATTENDEE: uninvite / remove a *person* from an event ──
        # Must check before DELETE and INVITE — "off the invite" contains "invite"
        if "uninvite" in lower or "off the invite" in lower:
            return "REMOVE_ATTENDEE"
        if re.search(r"\bremove\b.+\bfrom\b", lower):
            if any(t in lower for t in ["from my calendar", "from calendar", "from the calendar"]):
                return "DELETE"
            return "REMOVE_ATTENDEE"

        # ── DELETE: remove an entire event ──
        # "cancel [something]" that wasn't caught as EXIT above → DELETE
        if re.search(r"\bcancel\b.+", lower):
            return "DELETE"
        delete_signals = [
            "delete the", "delete my", "delete this", "delete",
            "remove the event", "remove the meeting", "remove my meeting",
            "get rid of",
        ]
        if any(s in lower for s in delete_signals):
            return "DELETE"

        # ── ACCEPT_INVITE / DECLINE_INVITE — must come before INVITE ──
        if re.search(r"\b(accept|confirm|rsvp yes)\b", lower):
            if not any(s in lower for s in ["schedule", "book", "create", "set up", "new"]):
                return "ACCEPT_INVITE"
        if re.search(r"\b(decline|reject|rsvp no|turn down)\b", lower):
            if not any(s in lower for s in ["schedule", "book", "create", "set up", "new"]):
                return "DECLINE_INVITE"

        # ── INVITE: add a *person* to an existing event ──
        if "invite" in lower:
            if not any(s in lower for s in ["schedule", "book", "create", "set up", "new", "accept", "decline"]):
                return "INVITE"
        # "add X to the meeting/standup/call/etc."
        if re.search(r"\badd\b.+\bto\b.+\b(meeting|event|standup|call|sync|huddle|session|appointment)\b", lower):
            return "INVITE"
        # "include X in the meeting/standup/call/etc."
        if re.search(r"\binclude\b.+\bin\b.+\b(meeting|event|standup|call|sync|huddle|session|appointment)\b", lower):
            return "INVITE"
        if any(s in lower for s in [
            "add them to", "add him to", "add her to",
        ]):
            return "INVITE"

        # ── SET_REMINDER: update reminder preference for a meeting ──
        if re.search(r"\b(remind me|set a reminder|reminder for|ping me|alert me)\b", lower):
            if any(s in lower for s in ["before", "minutes", "minute", "mins", "min", "ahead"]):
                return "SET_REMINDER"
        if re.search(r"\bno reminder\b|\bskip.*reminder\b|\breminder.*off\b", lower):
            return "SET_REMINDER"

        # ── MAKE_RECURRING: convert an existing event to repeat weekly ──
        if re.search(r"\b(make|set|turn)\b.{0,20}\b(recurring|repeat|weekly|repeating)\b", lower):
            return "MAKE_RECURRING"
        if re.search(r"\b(recurring|repeat|weekly|repeating)\b.{0,20}\b(it|that|this)\b", lower):
            return "MAKE_RECURRING"

        # ── RESCHEDULE: move an existing event ──
        reschedule_signals = [
            "reschedule", "move my", "move the", "push my", "push the",
            "shift my", "shift the", "change the time", "change my",
            "instead of", "move it to", "push it to", "push to",
            "swap the time",
            # Corporate slang
            "bump this", "bump it", "bump the", "bump my",
            "circle back on", "circle back about",
        ]
        if any(s in lower for s in reschedule_signals):
            return "RESCHEDULE"
        # Catch "move [event name] to [time]" — e.g., "move test meeting to 8AM"
        if re.search(r"\bmove\b.+\bto\b", lower):
            return "RESCHEDULE"

        # ── INVITE: loop in [name] ──
        if re.search(r"\bloop\s+in\b", lower):
            return "INVITE"

        # ── DELETE: table it / drop it (corporate slang for cancel) ──
        if any(s in lower for s in ["table this", "table it", "table the", "drop this", "drop it", "drop the meeting"]):
            return "DELETE"

        # ── SCHEDULE: block time / spin up (corporate slang for create) ──
        if any(s in lower for s in ["block some time", "block off", "block out", "spin up a meeting", "spin up a call"]):
            return "SCHEDULE"

        # ── SCHEDULE: create a new event (default) ──
        return "SCHEDULE"

    def extract_meeting_details(self, user_input: str) -> dict:
        ctx = get_today_context()
        prompt = EXTRACT_MEETING_PROMPT.format(
            today=ctx["today"],
            day_name=ctx["day_name"],
            current_time=ctx["current_time"],
            late_night_note=self.get_late_night_note(ctx),
            time_bucket=ctx.get("time_bucket", ""),
            user_input=user_input,
        )
        raw = self.capability_worker.text_to_text_response(prompt)

        clean = raw.replace("```json", "").replace("```", "").strip()
        self.worker.editor_logging_handler.info(f"[GCal] LLM extraction: {clean}")

        try:
            return json.loads(clean)
        except Exception:
            self.worker.editor_logging_handler.error(f"[GCal] Failed to parse LLM JSON: {clean}")
            return None

    def extract_reschedule_details(self, user_input: str) -> dict:
        """Extract event hint and new time/date from a reschedule request."""
        ctx = get_today_context()
        prompt = EXTRACT_RESCHEDULE_PROMPT.format(
            today=ctx["today"],
            day_name=ctx["day_name"],
            current_time=ctx["current_time"],
            late_night_note=self.get_late_night_note(ctx),
            time_bucket=ctx.get("time_bucket", ""),
            user_input=user_input,
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        self.worker.editor_logging_handler.info(f"[GCal] Reschedule extraction: {clean}")

        try:
            return json.loads(clean)
        except Exception:
            self.worker.editor_logging_handler.error(f"[GCal] Failed to parse reschedule JSON: {clean}")
            return None

    def extract_dates_from_text(self, user_input: str) -> list:
        ctx = get_today_context()
        prompt = EXTRACT_DATES_PROMPT.format(
            today=ctx["today"],
            day_name=ctx["day_name"],
            current_time=ctx["current_time"],
            late_night_note=self.get_late_night_note(ctx),
            time_bucket=ctx.get("time_bucket", ""),
            user_input=user_input,
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        self.worker.editor_logging_handler.info(f"[GCal] Date extraction: {raw}")

        try:
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return [{"date": ctx["today"], "label": "today"}]

    def find_matching_event(self, event_hint: str, original_time: str = None,
                            original_date: str = None,
                            preloaded_events: list = None) -> dict:
        """
        Search upcoming events and fuzzy-match the user's description.
        Returns the matched event dict (with 'id', 'summary', 'start', etc.) or None.

        Pass preloaded_events (from load_events_cache) to skip the API call.
        """
        # Shortcut: if the user says "that meeting", "this meeting", "the same one", etc.
        # and we have a recently-touched event, use it directly
        vague_refs = [
            "that meeting", "this meeting", "that event", "this event",
            "the same", "that one", "the one we just", "thatmeeting",
            "the meeting", "the event",
            "that", "this", "it",
        ]
        hint_lower = event_hint.lower().strip()
        if self.last_event and (hint_lower in ["that", "this", "it"] or any(v in hint_lower for v in vague_refs)):
            self.worker.editor_logging_handler.info(
                f"[GCal] Matched vague ref '{event_hint}' to last_event: {self.last_event.get('summary')}"
            )
            # Re-fetch to get current state (attendees may have changed)
            event_id = self.last_event.get("id")
            if event_id:
                refreshed = self.get_event_by_id(event_id)
                if refreshed:
                    return refreshed
            return self.last_event

        if preloaded_events is not None:
            # Use the provided cache — filter by original_date if given
            events = preloaded_events
            if original_date:
                try:
                    orig = datetime.strptime(original_date, "%Y-%m-%d").date()
                    events = [
                        ev for ev in events
                        if abs((datetime.fromisoformat(
                            ev.get("start", {}).get("dateTime", "").replace("Z", "+00:00")
                        ).date() - orig).days) <= 1
                    ]
                except Exception:
                    pass
            self.worker.editor_logging_handler.info(
                f"[GCal] find_matching_event using preloaded cache ({len(events)} events after filter)."
            )
        else:
            today = get_effective_today().strftime("%Y-%m-%d")
            # If user mentioned the original date, search just that day ± 1
            # Otherwise search a 30-day window
            if original_date:
                orig = datetime.strptime(original_date, "%Y-%m-%d")
                start_date = (orig - timedelta(days=1)).strftime("%Y-%m-%d")
                end_date = (orig + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                start_date = today
                end_date = (get_effective_today() + timedelta(days=30)).strftime("%Y-%m-%d")
            events = self.list_events_in_range(start_date, end_date)

        if not events:
            return None

        # Build numbered list for the LLM
        event_lines = []
        for i, ev in enumerate(events, 1):
            title = ev.get("summary", "Untitled")
            start = ev.get("start", {})
            dt_str = start.get("dateTime", start.get("date", ""))
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                time_str = dt.strftime("%-I:%M %p")
                date_str = dt.strftime("%A %B %-d")
                event_lines.append(f"{i}. \"{title}\" on {date_str} at {time_str}")
            except Exception:
                event_lines.append(f"{i}. \"{title}\"")

        event_list_str = "\n".join(event_lines)

        original_time_hint = ""
        if original_time:
            spoken = self.format_time_for_speech(original_time)
            original_time_hint = f"They mentioned it's currently at {spoken}."

        prompt = FUZZY_MATCH_PROMPT.format(
            event_hint=event_hint,
            original_time_hint=original_time_hint,
            event_list=event_list_str,
        )

        raw = self.capability_worker.text_to_text_response(
            prompt,
            system_prompt="You match event descriptions to calendar entries. Reply with only a number or NONE.",
        ).strip()

        self.worker.editor_logging_handler.info(f"[GCal] Fuzzy match result: {raw}")

        if "NONE" in raw.upper():
            return None

        # Extract the number
        match = re.search(r"\d+", raw)
        if match:
            idx = int(match.group()) - 1
            if 0 <= idx < len(events):
                return events[idx]

        return None

    def get_attendee_display_names(self, attendees: list) -> list:
        """
        Turn a list of attendee dicts (with 'email') into friendly display names.
        Uses the contacts list for known people, falls back to email prefix.
        """
        names = []
        for a in attendees:
            email = a.get("email", "")
            if not email:
                continue
            friendly = None
            if self.contacts:
                for name, info in self.contacts.items():
                    contact_email = info.get("email", "") if isinstance(info, dict) else info
                    if isinstance(contact_email, str) and contact_email.lower() == email.lower():
                        friendly = name
                        break
            names.append(friendly or email.split("@")[0])
        return names

    def format_events_for_speech(self, events: list, date_label: str) -> str:
        if not events:
            return f"You've got nothing on the books {date_label}."

        now = get_local_now()
        event_lines = []
        for ev in events:
            title = ev.get("summary", "Untitled event")
            start = ev.get("start", {})
            end = ev.get("end", {})
            dt_str = start.get("dateTime", start.get("date", ""))
            end_str = end.get("dateTime", "")
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                time_str = dt.strftime("%-I:%M %p")
                line = f"- {title} at {time_str}"

                # Add attendee info
                attendees = ev.get("attendees", [])
                if attendees:
                    names = self.get_attendee_display_names(attendees)
                    if names:
                        line += f" (with {', '.join(names[:3])}{'...' if len(names) > 3 else ''})"

                # Add context: in progress or starting soon
                if end_str:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=LOCAL_TZ)
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=LOCAL_TZ)
                    now_aware = now if now.tzinfo else now.replace(tzinfo=LOCAL_TZ)

                    if dt <= now_aware < end_dt:
                        mins_left = int((end_dt - now_aware).total_seconds() / 60)
                        line += f" [IN PROGRESS - {mins_left}m left]"
                    elif timedelta(0) < (dt - now_aware) <= timedelta(minutes=30):
                        mins_until = int((dt - now_aware).total_seconds() / 60)
                        line += f" [STARTING IN {mins_until}m]"

                event_lines.append(line)
            except Exception:
                event_lines.append(f"- {title}")

        event_list_str = "\n".join(event_lines)

        prompt = (
            f"Read back this person's calendar for {date_label}.\n"
            f"Current time: {now.strftime('%-I:%M %p')}\n"
            f"Events:\n{event_list_str}\n\n"
            "Turn this into a short, natural spoken summary.\n"
            "For [IN PROGRESS] events, mention they're happening now and how much time is left.\n"
            "For [STARTING IN Xm] events, give a heads up that they're coming up soon.\n"
            "If attendees are listed, mention them naturally only if there are 1-3 people. "
            "For larger groups just note it's a group meeting.\n"
            "Connect events naturally. No bullet points, no numbering."
        )

        result = self.capability_worker.text_to_text_response(
            prompt,
            system_prompt=VOICE_SYSTEM_PROMPT,
        )
        return result.strip()

    def format_events_at_time(self, events: list, query_time: str, date_label: str) -> str:
        """
        Answer 'what's happening at X time' by finding events that span that time.
        """
        try:
            datetime.strptime(query_time, "%H:%M")
        except Exception:
            return self.format_events_for_speech(events, date_label)

        # Find the date from the first event or use today
        ref_date = get_today_context()["today"]
        if events:
            first_start = events[0].get("start", {}).get("dateTime", "")
            try:
                ref_date = datetime.fromisoformat(first_start.replace("Z", "+00:00")).strftime("%Y-%m-%d")
            except Exception:
                pass

        query_full = datetime.strptime(f"{ref_date} {query_time}", "%Y-%m-%d %H:%M")
        time_label = self.format_time_for_speech(query_time)

        active_events = []
        for ev in events:
            start_str = ev.get("start", {}).get("dateTime", "")
            end_str = ev.get("end", {}).get("dateTime", "")
            if not start_str or not end_str:
                continue
            try:
                ev_start = datetime.fromisoformat(start_str.replace("Z", "+00:00")).replace(tzinfo=None)
                ev_end = datetime.fromisoformat(end_str.replace("Z", "+00:00")).replace(tzinfo=None)
                if ev_start <= query_full < ev_end:
                    active_events.append(ev)
            except Exception:
                continue

        if not active_events:
            return f"You're free at {time_label} {date_label}."

        # Build a natural response
        parts = []
        for ev in active_events:
            title = ev.get("summary", "an event")
            ev_start_str = ev.get("start", {}).get("dateTime", "")
            ev_end_str = ev.get("end", {}).get("dateTime", "")
            try:
                ev_start = datetime.fromisoformat(ev_start_str.replace("Z", "+00:00"))
                ev_end = datetime.fromisoformat(ev_end_str.replace("Z", "+00:00"))
                start_label = ev_start.strftime("%-I:%M %p") if ev_start.minute else ev_start.strftime("%-I %p")
                end_label = ev_end.strftime("%-I:%M %p") if ev_end.minute else ev_end.strftime("%-I %p")

                mins_in = int((query_full - ev_start.replace(tzinfo=None)).total_seconds() / 60)
                mins_left = int((ev_end.replace(tzinfo=None) - query_full).total_seconds() / 60)

                desc = f"{title} from {start_label} to {end_label}"
                if mins_in > 0:
                    desc += f", about {mins_left} minutes left at that point"

                attendees = ev.get("attendees", [])
                if attendees:
                    names = self.get_attendee_display_names(attendees)
                    if 1 <= len(names) <= 3:
                        desc += f" with {', '.join(names)}"

                parts.append(desc)
            except Exception:
                parts.append(title)

        if len(active_events) == 1:
            return f"At {time_label} {date_label}, you'll be in {parts[0]}."
        else:
            joined = " and also ".join(parts)
            return f"At {time_label} {date_label}, you've got overlapping events: {joined}."

    def format_time_for_speech(self, time_24: str) -> str:
        try:
            dt = datetime.strptime(time_24, "%H:%M")
            if dt.minute == 0:
                return dt.strftime("%-I %p")
            return dt.strftime("%-I:%M %p")
        except Exception:
            return time_24

    def format_event_time(self, event: dict) -> str:
        """Extract and format the start time from an event dict for speech."""
        start = event.get("start", {})
        dt_str = start.get("dateTime", "")
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            if dt.minute == 0:
                return dt.strftime("%-I %p")
            return dt.strftime("%-I:%M %p")
        except Exception:
            return "unknown time"

    def format_event_date(self, event: dict) -> str:
        """Extract and format the start date from an event dict as YYYY-MM-DD."""
        start = event.get("start", {})
        dt_str = start.get("dateTime", start.get("date", ""))
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return get_today_context()["today"]

    # =========================================================================
    # SCHEDULE MD (personality memory)
    # =========================================================================

    def _format_schedule_duration(self, minutes: int) -> str:
        if minutes >= 60 and minutes % 60 == 0:
            hrs = minutes // 60
            return f"{hrs} hr"
        elif minutes > 60:
            hrs = minutes // 60
            mins = minutes % 60
            return f"{hrs} hr {mins} min"
        return f"{minutes} min"

    async def load_events_cache(self) -> list:
        """
        Return the cached event list written by background.py.
        Falls back to a direct 7-day API fetch if the cache is missing or stale.
        Direct API calls are only kept for: conflict checks, post-mutation refreshes,
        and fetching a single event by ID.
        """
        try:
            exists = await self.capability_worker.check_if_file_exists(EVENTS_CACHE_FILE, False)
            if exists:
                raw = await self.capability_worker.read_file(EVENTS_CACHE_FILE, False)
                if raw:
                    data = json.loads(raw)
                    age = epoch_now() - data.get("updated_at", 0)
                    if age <= EVENTS_CACHE_MAX_AGE:
                        events = data.get("events", [])
                        self.worker.editor_logging_handler.info(
                            f"[GCal] Using events cache ({age:.1f}s old, {len(events)} events)."
                        )
                        return events
                    else:
                        self.worker.editor_logging_handler.info(
                            f"[GCal] Cache stale ({age:.1f}s) — falling back to API."
                        )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Cache read error: {e} — falling back to API.")

        # Fallback: direct API call for next 7 days
        today = get_effective_today().strftime("%Y-%m-%d")
        end_date = (get_effective_today() + timedelta(days=7)).strftime("%Y-%m-%d")
        return self.list_events_in_range(today, end_date)

    async def save_event_reminder(self, event_id: str, reminder_minutes: int):
        """
        Persist a per-event reminder override in gcal_event_reminders.json.
        background.py checks this file by event ID before falling back to title-based prefs.
        """
        REMINDERS_FILE = "gcal_event_reminders.json"
        try:
            existing = {}
            exists = await self.capability_worker.check_if_file_exists(REMINDERS_FILE, False)
            if exists:
                raw = await self.capability_worker.read_file(REMINDERS_FILE, False)
                if raw:
                    existing = json.loads(raw)
            existing[event_id] = reminder_minutes
            exists2 = await self.capability_worker.check_if_file_exists(REMINDERS_FILE, False)
            if exists2:
                await self.capability_worker.delete_file(REMINDERS_FILE, False)
            await self.capability_worker.write_file(
                REMINDERS_FILE, json.dumps(existing, indent=2), False, mode="w"
            )
            self.worker.editor_logging_handler.info(
                f"[GCal] Saved reminder override for {event_id}: {reminder_minutes} min."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] save_event_reminder error: {e}")

    async def refresh_schedule_md(self):
        """
        Fetch the next 7 days of events and rewrite upcoming_schedule.md so the
        personality prompt always reflects the latest calendar state.
        Called after every create / reschedule / delete.
        """
        try:
            today = get_effective_today().strftime("%Y-%m-%d")
            end_date = (get_effective_today() + timedelta(days=7)).strftime("%Y-%m-%d")
            events = self.list_events_in_range(today, end_date)

            now = get_local_now()
            lines = ["## Upcoming Schedule (next 7 days)"]

            for ev in events:
                title = ev.get("summary", "Untitled")
                start_str = ev.get("start", {}).get("dateTime", "")
                end_str = ev.get("end", {}).get("dateTime", "")
                if not start_str:
                    continue
                try:
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(LOCAL_TZ) if end_str else None

                    delta = (start_dt.date() - now.date()).days
                    if delta == 0:
                        date_label = "Today"
                    elif delta == 1:
                        date_label = "Tomorrow"
                    else:
                        date_label = start_dt.strftime("%A")

                    if start_dt.minute == 0:
                        time_label = start_dt.strftime("%-I %p")
                    else:
                        time_label = start_dt.strftime("%-I:%M %p")

                    dur_label = ""
                    if end_dt:
                        dur_mins = int((end_dt - start_dt).total_seconds() / 60)
                        dur_label = f" ({self._format_schedule_duration(dur_mins)})"

                    attendees = ev.get("attendees", [])
                    attendee_str = ""
                    if attendees and 1 <= len(attendees) <= 3:
                        names = [a.get("displayName") or a.get("email", "").split("@")[0] for a in attendees]
                        attendee_str = f" with {', '.join(names)}"

                    lines.append(f"- {date_label} {time_label} — {title}{dur_label}{attendee_str}")
                except Exception:
                    continue

            if len(lines) > 21:
                lines = lines[:21]
                lines.append("- (...more events not shown)")

            content = "\n".join(lines) + "\n"

            exists = await self.capability_worker.check_if_file_exists("upcoming_schedule.md", False)
            if exists:
                await self.capability_worker.delete_file("upcoming_schedule.md", False)
            await self.capability_worker.write_file("upcoming_schedule.md", content, False, mode="w")
            self.worker.editor_logging_handler.info(
                f"[GCal] Refreshed upcoming_schedule.md ({len(lines)-1} events)."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] refresh_schedule_md error: {e}")

    # =========================================================================
    # MAIN ENTRY
    # =========================================================================

    async def run_calendar(self):
        try:
            self.contacts = await self.load_contacts()
            msg = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[GCal] User said: {msg}")

            if not self.get_access_token():
                await self.capability_worker.speak(
                    "I can't reach Google Calendar right now. Link your Google account in OpenHome settings."
                )
                return

            # Parse into potentially multiple actions
            actions = self.parse_multi_intent(msg)
            self.worker.editor_logging_handler.info(f"[GCal] Action queue ({len(actions)}): {actions}")

            for i, action_text in enumerate(actions):
                intent = self.classify_intent(action_text)
                if intent == "EXIT":
                    break
                if i > 0:
                    await self.capability_worker.speak("Alright, next one.")
                await self.execute_action(action_text)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Error: {e}")
            await self.capability_worker.speak("Something went wrong with Google Calendar.")
        finally:
            self.capability_worker.resume_normal_flow()

    # =========================================================================
    # HANDLERS
    # =========================================================================

    async def _find_event_with_retry(
        self,
        initial_hint: str,
        original_time: str = None,
        original_date: str = None,
        max_retries: int = 2,
    ):
        """
        Try to fuzzy-match an event; if not found, ask the user for the name
        and retry up to max_retries times.  Returns the matched event dict or None.
        """
        hint = initial_hint
        for attempt in range(max_retries + 1):
            cached_events = await self.load_events_cache()
            matched = self.find_matching_event(
                event_hint=hint,
                original_time=original_time,
                original_date=original_date,
                preloaded_events=cached_events,
            )
            if matched:
                return matched
            if attempt < max_retries:
                hint = await self.capability_worker.run_io_loop(
                    "I'm not finding that one. What's it called?"
                )
                if not hint or not hint.strip():
                    return None
        return None

    async def handle_list_events(self, user_input: str):
        await self.capability_worker.speak("Let's see.")

        # Extract date AND optional time from the query
        ctx = get_today_context()
        extract_prompt = (
            f"The user is asking about their calendar. Extract what they want to know.\n\n"
            f"RIGHT NOW it is {ctx['current_time']} on {ctx['day_name']}, {ctx['today']}. It is currently {ctx['time_bucket']}.\n"
            f"{self.get_late_night_note(ctx)}\n"
            f"User said: \"{user_input}\"\n\n"
            "Return ONLY a JSON object:\n"
            '{{"date": "YYYY-MM-DD or null", "time": "HH:MM 24-hour or null", "scope": "full_day|at_time|around_time"}}\n\n'
            "- scope 'full_day': they want the whole day's schedule (e.g. 'what's on tomorrow')\n"
            "- scope 'at_time': they want to know what's happening at a specific time (e.g. 'what do I have at 2 PM')\n"
            "- scope 'around_time': they want what's around a time (e.g. 'what's going on this afternoon')\n\n"
            "Return ONLY valid JSON."
        )
        raw = self.capability_worker.text_to_text_response(extract_prompt)
        self.worker.editor_logging_handler.info(f"[GCal] List query extraction: {raw}")

        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            query = json.loads(clean)
        except Exception:
            query = {}

        date_str = query.get("date") or ctx["today"]
        query_time = query.get("time")
        scope = query.get("scope", "full_day")

        label = friendly_date_label(date_str)

        # Use cached events from background.py; fall back to direct API only
        # if the cache is stale or the date is outside the 7-day window.
        cached = await self.load_events_cache()
        events = [
            ev for ev in cached
            if ev.get("start", {}).get("dateTime", "")[:10] == date_str
            or ev.get("start", {}).get("date", "") == date_str
        ]
        if not events and not cached:
            # True fallback: no cache at all, hit API directly
            events = self.list_events_for_date(date_str)

        if scope == "at_time" and query_time:
            # User wants to know what's happening at a specific time
            speech = self.format_events_at_time(events, query_time, label)
        else:
            speech = self.format_events_for_speech(events, label)

        self.worker.editor_logging_handler.info(f"[GCal] {speech}")
        await self.capability_worker.speak(speech)

    async def handle_query_attendees(self, user_input: str):
        """Answer 'who's on X meeting' / 'who's attending the standup'."""
        await self.capability_worker.speak("On it.")

        # Use the invite extractor to pull out the event hint
        ctx = get_today_context()
        prompt = (
            f"The user wants to know who is attending a calendar event.\n"
            f"Extract the event they're asking about.\n\n"
            f"RIGHT NOW it is {ctx['current_time']} on {ctx['day_name']}, {ctx['today']}.\n"
            f"User said: \"{user_input}\"\n\n"
            "Return ONLY a JSON object:\n"
            '{{"event_hint": "string", "event_date": "YYYY-MM-DD or null", "event_time": "HH:MM or null"}}\n'
            "Return ONLY valid JSON."
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        self.worker.editor_logging_handler.info(f"[GCal] Attendee query extraction: {clean}")

        try:
            details = json.loads(clean)
        except Exception:
            await self.capability_worker.speak("I didn't catch which event you mean.")
            return

        event_hint = details.get("event_hint", user_input)
        matched_event = await self._find_event_with_retry(
            initial_hint=event_hint,
            original_time=details.get("event_time"),
            original_date=details.get("event_date"),
        )

        if not matched_event:
            await self.capability_worker.speak("I still can't find that one. Check the name and try again.")
            return

        event_title = matched_event.get("summary", "that event")
        attendees = matched_event.get("attendees", [])
        self.last_event = matched_event

        if not attendees:
            await self.capability_worker.speak(f"There's no one else on {event_title}, it's just you.")
            return

        attendee_names = self.get_attendee_display_names(attendees)

        if len(attendee_names) == 1:
            names_str = attendee_names[0]
        elif len(attendee_names) == 2:
            names_str = f"{attendee_names[0]} and {attendee_names[1]}"
        else:
            names_str = ", ".join(attendee_names[:-1]) + f", and {attendee_names[-1]}"

        count = len(attendee_names)
        await self.capability_worker.speak(
            f"{event_title} has {count} {'person' if count == 1 else 'people'} on it: {names_str}."
        )

    async def handle_rename_event(self, user_input: str):
        """Rename an existing calendar event."""
        await self.capability_worker.speak("Sure thing, finding it.")

        ctx = get_today_context()
        prompt = (
            f"The user wants to rename or change the title of a calendar event.\n"
            f"Extract what they want.\n\n"
            f"RIGHT NOW it is {ctx['current_time']} on {ctx['day_name']}, {ctx['today']}.\n"
            f"User said: \"{user_input}\"\n\n"
            "Return ONLY a JSON object:\n"
            '{{"event_hint": "how they describe the current event (name, \'that meeting\', etc.)", '
            '"new_name": "the new name they want, or null if not specified", '
            '"event_date": "YYYY-MM-DD or null", '
            '"event_time": "HH:MM or null"}}\n'
            "Return ONLY valid JSON."
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        self.worker.editor_logging_handler.info(f"[GCal] Rename extraction: {clean}")

        try:
            details = json.loads(clean)
        except Exception:
            await self.capability_worker.speak("I didn't catch that. Which event do you want to rename?")
            return

        event_hint = details.get("event_hint", user_input)
        matched_event = await self._find_event_with_retry(
            initial_hint=event_hint,
            original_time=details.get("event_time"),
            original_date=details.get("event_date"),
        )

        if not matched_event:
            await self.capability_worker.speak("I still can't find that one. Check the name and try again.")
            return

        event_title = matched_event.get("summary", "Untitled")
        event_id = matched_event["id"]
        new_name = details.get("new_name")

        if not new_name:
            new_name = await self.capability_worker.run_io_loop(
                f"Found {event_title}. What do you want to call it instead?"
            )
            if not new_name or not new_name.strip():
                await self.capability_worker.speak("I didn't catch a name. Try again whenever.")
                return
            new_name = new_name.strip()

        response = await self.capability_worker.run_io_loop(
            f"I'll rename {event_title} to {new_name}. Good?"
        )
        parsed = self.parse_confirmation_response(response)

        if not parsed["confirmed"]:
            if parsed["followup"]:
                await self.dispatch_followup(parsed["followup"])
            else:
                await self.capability_worker.speak("Got it, keeping the name as is.")
            return

        await self.capability_worker.speak("One sec.")
        self.last_api_error = ""
        result = self.update_event(event_id, {"summary": new_name})

        if result:
            self.last_event = result
            await self.capability_worker.speak(f"Done. It's now called {new_name}.")
            if parsed["followup"]:
                await self.dispatch_followup(parsed["followup"])
        else:
            await self.capability_worker.speak(
                f"That didn't work. The error was: {self.last_api_error}."
            )

    async def handle_make_recurring(self, user_input: str):
        """Convert an existing event to repeat weekly."""
        lower = user_input.lower()
        vague_refs = ["it", "that", "this", "the meeting", "the event", "the call"]
        is_vague = any(v in lower for v in vague_refs) or not any(
            c.isalpha() for c in lower.replace("make", "").replace("recurring", "")
            .replace("repeat", "").replace("weekly", "").replace("it", "")
            .replace("that", "").replace("this", "").replace("set", "")
        )

        event = None
        if is_vague and self.last_event:
            event = self.last_event
        else:
            event = await self._find_event_with_retry(initial_hint=user_input)

        if not event:
            await self.capability_worker.speak("I still can't find that one. Check the name and try again.")
            return

        event_id = event.get("id", "")
        title = event.get("summary", "that event")
        response = await self.capability_worker.run_io_loop(
            f"I'll make {title} repeat every week. Sound good?"
        )
        parsed = self.parse_confirmation_response(response)

        if not parsed["confirmed"]:
            if parsed["followup"]:
                await self.dispatch_followup(parsed["followup"])
            else:
                await self.capability_worker.speak("Got it, leaving it as a one-time event.")
            return

        await self.capability_worker.speak("On it.")
        self.last_api_error = ""
        result = self.update_event(event_id, {"recurrence": ["RRULE:FREQ=WEEKLY"]})

        if result:
            self.last_event = result
            await self.capability_worker.speak(f"Done — {title} will now repeat every week.")
            if parsed["followup"]:
                await self.dispatch_followup(parsed["followup"])
        else:
            await self.capability_worker.speak(
                f"That didn't go through. Error: {self.last_api_error}."
            )

    async def handle_reschedule_event(self, user_input: str):
        await self.capability_worker.speak("On it.")

        details = self.extract_reschedule_details(user_input)
        if not details or not details.get("event_hint"):
            await self.capability_worker.speak(
                "Hmm, I'm not sure which event you mean. Can you give me the name?"
            )
            return

        self.worker.editor_logging_handler.info(f"[GCal] Reschedule details: {json.dumps(details)}")

        matched_event = await self._find_event_with_retry(
            initial_hint=details["event_hint"],
            original_time=details.get("original_time"),
            original_date=details.get("original_date"),
        )

        if not matched_event:
            await self.capability_worker.speak("I still can't find that one. Check the name and try again.")
            return

        event_title = matched_event.get("summary", "Untitled")
        event_id = matched_event["id"]
        current_time_str = self.format_event_time(matched_event)
        current_date_str = self.format_event_date(matched_event)
        current_date_label = friendly_date_label(current_date_str)

        self.worker.editor_logging_handler.info(
            f"[GCal] Matched event: {event_title} (id={event_id}) at {current_time_str} on {current_date_label}"
        )

        new_date = details.get("new_date") or current_date_str
        new_time = details.get("new_time")

        if not new_time:
            response = await self.capability_worker.run_io_loop(
                f"Found {event_title} at {current_time_str} {current_date_label}. When do you want it instead?"
            )
            time_details = self.extract_reschedule_details(f"move it to {response}")
            new_time = (time_details or {}).get("new_time")
            if not new_time:
                meeting_d = self.extract_meeting_details(f"meeting at {response}")
                new_time = (meeting_d or {}).get("time")
            if not new_time:
                await self.capability_worker.speak("I didn't quite get that. Try again whenever you're ready.")
                return
            if time_details and time_details.get("new_date"):
                new_date = time_details["new_date"]

        new_date_label = friendly_date_label(new_date)
        new_time_label = self.format_time_for_speech(new_time)

        if new_date != current_date_str:
            confirm_msg = (
                f"I'll move {event_title} from {current_time_str} {current_date_label} "
                f"to {new_time_label} {new_date_label}. Good?"
            )
        else:
            confirm_msg = (
                f"I'll move {event_title} from {current_time_str} to {new_time_label} "
                f"{current_date_label}. Good?"
            )

        response = await self.capability_worker.run_io_loop(confirm_msg)
        parsed = self.parse_confirmation_response(response)
        confirmed = parsed["confirmed"]
        followup = parsed["followup"]

        if not confirmed:
            # Check if the user is correcting the time/date instead of just saying no
            correction = self.extract_reschedule_details(f"move it to {response}")
            corrected_time = (correction or {}).get("new_time")
            corrected_date = (correction or {}).get("new_date")

            if corrected_time or corrected_date:
                if corrected_time:
                    new_time = corrected_time
                if corrected_date:
                    new_date = corrected_date
                new_date_label = friendly_date_label(new_date)
                new_time_label = self.format_time_for_speech(new_time)

                self.worker.editor_logging_handler.info(
                    f"[GCal] User corrected to: {new_time} on {new_date}"
                )

                if new_date != current_date_str:
                    confirm_msg2 = f"Got it, {new_time_label} {new_date_label} instead. Good?"
                else:
                    confirm_msg2 = f"Got it, {new_time_label} {current_date_label} instead. Good?"

                response2 = await self.capability_worker.run_io_loop(confirm_msg2)
                confirmed = self.interpret_yes_no(response2)
                if not confirmed:
                    await self.capability_worker.speak("Got it, leaving it where it is.")
                    return
            elif followup:
                # They said no but want something else — dispatch it
                await self.dispatch_followup(followup)
                return
            else:
                await self.capability_worker.speak("Got it, leaving it where it is.")
                return

        try:
            orig_start_str = matched_event["start"].get("dateTime", "")
            orig_end_str = matched_event["end"].get("dateTime", "")
            orig_start = datetime.fromisoformat(orig_start_str.replace("Z", "+00:00"))
            orig_end = datetime.fromisoformat(orig_end_str.replace("Z", "+00:00"))

            if details.get("new_duration_minutes"):
                duration = timedelta(minutes=details["new_duration_minutes"])
            else:
                duration = orig_end - orig_start

            new_start_dt = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M")
            new_end_dt = new_start_dt + duration
            new_start_iso = new_start_dt.strftime("%Y-%m-%dT%H:%M:%S")
            new_end_iso = new_end_dt.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Reschedule datetime error: {e}")
            await self.capability_worker.speak("Something got mixed up with the date. Let's try that again.")
            return

        # --- Conflict check ---
        conflicts = self.detect_conflicts(new_start_iso, new_end_iso, exclude_event_id=event_id)
        if conflicts:
            warning = self.format_conflict_warning(conflicts)
            self.worker.editor_logging_handler.info(
                f"[GCal] Reschedule conflict: {[c.get('summary') for c in conflicts]}"
            )
            conflict_response = await self.capability_worker.run_io_loop(
                f"{warning} Want me to move it anyway?"
            )
            if not self.interpret_yes_no(conflict_response):
                await self.capability_worker.speak("Alright, leaving it where it is.")
                return

        await self.capability_worker.speak("One sec.")
        self.last_api_error = ""
        updates = {
            "start": {"dateTime": new_start_iso, "timeZone": DEFAULT_TIMEZONE},
            "end": {"dateTime": new_end_iso, "timeZone": DEFAULT_TIMEZONE},
        }

        result = self.update_event(event_id, updates)

        if result:
            self.last_event = result
            await self.capability_worker.speak(
                f"All set. {event_title} is now at {new_time_label} {new_date_label}."
            )
            await self.refresh_schedule_md()
            # Dispatch any follow-up from the confirmation response
            if followup:
                await self.dispatch_followup(followup)
        else:
            await self.capability_worker.speak(
                f"Hmm, that didn't go through. The error was: {self.last_api_error}."
            )

    async def handle_delete_event(self, user_input: str):
        """Delete an event from the calendar."""
        await self.capability_worker.speak("Let me find it.")

        # Reuse reschedule extractor to identify which event
        details = self.extract_reschedule_details(user_input)
        event_hint = (details or {}).get("event_hint", "")
        if not event_hint:
            event_hint = user_input

        matched_event = await self._find_event_with_retry(
            initial_hint=event_hint,
            original_time=(details or {}).get("original_time"),
            original_date=(details or {}).get("original_date"),
        )

        if not matched_event:
            await self.capability_worker.speak("I still can't find that one. Check the name and try again.")
            return

        event_title = matched_event.get("summary", "Untitled")
        event_id = matched_event["id"]
        event_time_str = self.format_event_time(matched_event)
        event_date_str = self.format_event_date(matched_event)
        event_date_label = friendly_date_label(event_date_str)

        response = await self.capability_worker.run_io_loop(
            f"Found {event_title} at {event_time_str} {event_date_label}. Want me to delete it?"
        )
        parsed = self.parse_confirmation_response(response)
        confirmed = parsed["confirmed"]
        followup = parsed["followup"]

        if not confirmed:
            if followup:
                await self.dispatch_followup(followup)
            else:
                await self.capability_worker.speak("Works for me, leaving it on the books.")
            return

        await self.capability_worker.speak("One sec.")
        self.last_api_error = ""
        success = self.delete_event(event_id)

        if success:
            self.last_event = None
            await self.capability_worker.speak(f"Gone. {event_title} has been removed.")
            await self.refresh_schedule_md()
        else:
            await self.capability_worker.speak(
                f"That didn't work. The error was: {self.last_api_error}."
            )

    async def handle_remove_attendee(self, user_input: str):
        """Remove an attendee from an existing calendar event."""
        if not self.contacts:
            await self.capability_worker.speak("I don't have a contacts list set up, so I can't look anyone up.")
            return

        ctx = get_today_context()
        prompt = EXTRACT_REMOVE_ATTENDEE_PROMPT.format(
            today=ctx["today"],
            day_name=ctx["day_name"],
            current_time=ctx["current_time"],
            late_night_note=self.get_late_night_note(ctx),
            time_bucket=ctx.get("time_bucket", ""),
            user_input=user_input,
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        self.worker.editor_logging_handler.info(f"[GCal] Remove attendee extraction: {clean}")

        try:
            invite_details = json.loads(clean)
        except Exception:
            await self.capability_worker.speak("I didn't catch that. Who are you trying to remove?")
            return

        names = invite_details.get("attendee_names", [])
        if not names:
            await self.capability_worker.speak("Who did you want to take off the invite?")
            return

        people_to_remove = self.detect_attendees(user_input, llm_names=names)
        if not people_to_remove:
            names_str = " and ".join(names)
            await self.capability_worker.speak(
                f"I don't have {names_str} in my contacts, so I can't match them."
            )
            return

        await self.capability_worker.speak("Let me take a look.")
        event_hint = invite_details.get("event_hint", "") or user_input
        matched_event = await self._find_event_with_retry(
            initial_hint=event_hint,
            original_time=invite_details.get("event_time"),
            original_date=invite_details.get("event_date"),
        )

        if not matched_event:
            await self.capability_worker.speak("I still can't find that one. Check the name and try again.")
            return

        event_title = matched_event.get("summary", "Untitled")
        event_id = matched_event["id"]
        event_time_str = self.format_event_time(matched_event)
        event_date_str = self.format_event_date(matched_event)
        event_date_label = friendly_date_label(event_date_str)

        remove_names_str = " and ".join(p["name"] for p in people_to_remove)
        remove_emails = {self.safe_email(p) for p in people_to_remove} - {""}

        existing_attendees = matched_event.get("attendees", [])
        existing_emails = {self.safe_email(a) for a in existing_attendees} - {""}

        actually_on_event = remove_emails & existing_emails
        if not actually_on_event:
            await self.capability_worker.speak(
                f"{remove_names_str} isn't on {event_title}, so there's nothing to remove."
            )
            return

        response = await self.capability_worker.run_io_loop(
            f"I'll take {remove_names_str} off {event_title} at {event_time_str} "
            f"{event_date_label}. Good?"
        )
        parsed = self.parse_confirmation_response(response)
        confirmed = parsed["confirmed"]
        followup = parsed["followup"]

        if not confirmed:
            if followup:
                await self.dispatch_followup(followup)
            else:
                await self.capability_worker.speak("Got it, leaving the invite list as is.")
            return

        new_attendee_list = [
            a for a in existing_attendees
            if self.safe_email(a) not in remove_emails
        ]

        await self.capability_worker.speak("One sec.")
        self.last_api_error = ""
        result = self.update_event(event_id, {"attendees": new_attendee_list})

        if result:
            self.last_event = result
            await self.capability_worker.speak(f"Done. {remove_names_str} has been taken off {event_title}.")
            if followup:
                await self.dispatch_followup(followup)
        else:
            await self.capability_worker.speak(f"That didn't work. The error was: {self.last_api_error}.")

    async def handle_add_attendee(self, user_input: str):
        """Add attendees to an existing calendar event."""
        if not self.contacts:
            await self.capability_worker.speak("I don't have a contacts list set up, so I can't send invites.")
            return

        ctx = get_today_context()
        prompt = EXTRACT_INVITE_PROMPT.format(
            today=ctx["today"],
            day_name=ctx["day_name"],
            current_time=ctx["current_time"],
            late_night_note=self.get_late_night_note(ctx),
            time_bucket=ctx.get("time_bucket", ""),
            user_input=user_input,
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        self.worker.editor_logging_handler.info(f"[GCal] Invite extraction: {clean}")

        try:
            invite_details = json.loads(clean)
        except Exception:
            self.worker.editor_logging_handler.error(f"[GCal] Failed to parse invite JSON: {clean}")
            await self.capability_worker.speak("I didn't catch that. Who are you trying to invite?")
            return

        names = invite_details.get("attendee_names", [])
        if not names:
            await self.capability_worker.speak("Who did you want to add?")
            return

        attendees = self.detect_attendees(user_input, llm_names=names)
        if not attendees:
            names_str = " and ".join(names)
            await self.capability_worker.speak(
                f"I don't have {names_str} in my contacts."
            )
            return

        await self.capability_worker.speak("Let's see.")

        event_hint = invite_details.get("event_hint", "") or user_input
        matched_event = await self._find_event_with_retry(
            initial_hint=event_hint,
            original_time=invite_details.get("event_time"),
            original_date=invite_details.get("event_date"),
        )

        if not matched_event:
            await self.capability_worker.speak("I still can't find that one. Check the name and try again.")
            return

        event_title = matched_event.get("summary", "Untitled")
        event_id = matched_event["id"]
        event_time_str = self.format_event_time(matched_event)
        event_date_str = self.format_event_date(matched_event)
        event_date_label = friendly_date_label(event_date_str)

        attendee_names_str = " and ".join(a["name"] for a in attendees)

        response = await self.capability_worker.run_io_loop(
            f"I'll add {attendee_names_str} to {event_title} at {event_time_str} {event_date_label}. Good?"
        )
        parsed = self.parse_confirmation_response(response)
        confirmed = parsed["confirmed"]
        followup = parsed["followup"]

        if not confirmed:
            if followup:
                await self.dispatch_followup(followup)
            else:
                await self.capability_worker.speak("All good, no changes.")
            return

        # Merge with existing attendees
        try:
            existing_attendees = matched_event.get("attendees", [])
            existing_emails = {self.safe_email(a) for a in existing_attendees} - {""}
            new_attendee_list = list(existing_attendees)

            for a in attendees:
                email = self.safe_email(a)
                if email and email not in existing_emails:
                    new_attendee_list.append({"email": a.get("email", "")})
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[GCal] Merge error: {e} | attendees={attendees} | existing={existing_attendees}"
            )
            await self.capability_worker.speak("Something got mixed up. Let's try that again.")
            return

        await self.capability_worker.speak("One sec.")
        self.last_api_error = ""
        result = self.update_event(event_id, {"attendees": new_attendee_list})

        if result:
            self.last_event = result
            await self.capability_worker.speak(
                f"Done. {attendee_names_str} will get an invite to {event_title}."
            )
            # Dispatch any follow-up from the confirmation response
            if followup:
                await self.dispatch_followup(followup)
        else:
            await self.capability_worker.speak(
                f"That didn't work. The error was: {self.last_api_error}."
            )

    async def handle_respond_to_invite(self, user_input: str, response_status: str):
        """Accept or decline a meeting invite by PATCHing the self attendee's responseStatus."""
        lower = user_input.lower()
        vague_refs = ["it", "that", "this", "the invite", "the meeting", "the event"]

        event = None
        cached = await self.load_events_cache()

        if any(v in lower for v in vague_refs) and self.last_event:
            event = self.last_event
        else:
            event = self.find_matching_event(user_input, preloaded_events=cached)

        # Fallback: if still nothing found, look for a single pending invite in the cache
        if not event:
            pending = [
                ev for ev in cached
                if not ev.get("organizer", {}).get("self", False)
                and any(
                    a.get("self") and a.get("responseStatus") in ("needsAction", "tentative")
                    for a in ev.get("attendees", [])
                )
            ]
            if len(pending) == 1:
                event = pending[0]

        if not event:
            event = await self._find_event_with_retry(initial_hint=user_input)

        if not event:
            await self.capability_worker.speak("I still can't find that one. Check the name and try again.")
            return

        title = event.get("summary", "that event")
        attendees = event.get("attendees", [])
        self_att = next((a for a in attendees if a.get("self")), None)

        if not self_att:
            await self.capability_worker.speak(
                f"I don't see you as an attendee on {title}."
            )
            return

        action_label = "accept" if response_status == "accepted" else "decline"
        response = await self.capability_worker.run_io_loop(
            f"Go ahead and {action_label} {title}?"
        )
        parsed = self.parse_confirmation_response(response)
        if not parsed["confirmed"]:
            if parsed["followup"]:
                await self.dispatch_followup(parsed["followup"])
            else:
                await self.capability_worker.speak("Got it, leaving it as is.")
            return

        # Build updated attendees list with self RSVP changed
        updated_attendees = [
            {**a, "responseStatus": response_status} if a.get("self") else a
            for a in attendees
        ]
        event_id = event.get("id", "")
        self.last_api_error = ""
        result = self.update_event(event_id, {"attendees": updated_attendees})

        if result:
            self.last_event = result
            verb = "accepted" if response_status == "accepted" else "declined"
            await self.capability_worker.speak(f"Done — {title} is {verb}.")
            if parsed["followup"]:
                await self.dispatch_followup(parsed["followup"])
        else:
            await self.capability_worker.speak(
                f"That didn't go through. {self.last_api_error}."
            )

    async def handle_set_reminder(self, user_input: str):
        """Update user_preferences.md with a new per-meeting reminder override."""
        extract_prompt = (
            f'The user said: "{user_input}"\n'
            "They want to set a reminder preference for a specific meeting.\n"
            "Extract:\n"
            '- "event_fragment": string — the meeting title fragment (lowercase). '
            "If vague (e.g. 'that meeting', 'this one'), return null.\n"
            '- "reminder_minutes": integer minutes before the meeting, '
            'or "skip" if they want no reminder.\n'
            "Return ONLY valid JSON, e.g.: "
            '{"event_fragment": "standup", "reminder_minutes": 10}\n'
            '{"event_fragment": "investor call", "reminder_minutes": "skip"}'
        )
        raw = self.capability_worker.text_to_text_response(
            extract_prompt,
            system_prompt="Extract reminder preference. Reply with only JSON.",
        ).strip().replace("```json", "").replace("```", "").strip()

        try:
            extracted = json.loads(raw)
        except Exception:
            await self.capability_worker.speak(
                "I didn't catch that. Try something like 'remind me 10 minutes before the standup'."
            )
            return

        fragment = extracted.get("event_fragment")
        minutes = extracted.get("reminder_minutes")

        if not fragment:
            await self.capability_worker.speak("Which meeting should I update the reminder for?")
            return
        if minutes is None:
            await self.capability_worker.speak("How many minutes before should I remind you?")
            return

        # Read, update, write user_preferences.md
        try:
            exists = await self.capability_worker.check_if_file_exists("user_preferences.md", False)
            current_content = ""
            if exists:
                current_content = await self.capability_worker.read_file("user_preferences.md", False) or ""

            # Build the override line
            if minutes == "skip" or minutes == 0:
                override_line = f'- "{fragment}": skip'
            else:
                override_line = f'- "{fragment}": {int(minutes)}'

            # Replace existing override for this fragment if present, else append
            lines = current_content.splitlines()
            fragment_lower = fragment.lower()
            replaced = False
            new_lines = []
            for line in lines:
                if re.search(rf'"{re.escape(fragment_lower)}"', line.lower()):
                    new_lines.append(override_line)
                    replaced = True
                else:
                    new_lines.append(line)

            if not replaced:
                new_lines.append(override_line)

            new_content = "\n".join(new_lines)
            if exists:
                await self.capability_worker.delete_file("user_preferences.md", False)
            await self.capability_worker.write_file("user_preferences.md", new_content, False, mode="w")

            if minutes == "skip" or minutes == 0:
                await self.capability_worker.speak(
                    f"Got it — I'll skip reminders for {fragment} from now on."
                )
            else:
                await self.capability_worker.speak(
                    f"Done — I'll remind you {int(minutes)} minutes before {fragment}."
                )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] set_reminder error: {e}")
            await self.capability_worker.speak("Something went wrong updating your reminder preferences.")

    async def handle_schedule_event(self, user_input: str):
        details = self.extract_meeting_details(user_input)

        if not details:
            await self.capability_worker.speak("I didn't quite get that. Can you run it by me again?")
            return

        # --- Attendees: detect from user input with fuzzy matching ---
        attendees = []
        llm_names = details.get("attendee_names", [])
        if self.contacts:
            attendees = self.detect_attendees(user_input, llm_names=llm_names)

        if attendees:
            names_str = ", ".join(a["name"] for a in attendees)
            self.worker.editor_logging_handler.info(f"[GCal] Detected attendees: {names_str}")

        # --- Summary: fill in if missing or generic ---
        generic_names = ["meeting", "event", "appointment", "schedule a meeting",
                         "book a meeting", "new meeting", "a meeting", ""]
        summary = (details.get("summary") or "").strip()

        if summary.lower() in generic_names:
            existing_context = details.get("description", "").strip()
            combined_context = f"{user_input}. {existing_context}".strip(". ")

            name_prompt = (
                f'The user is scheduling a calendar event. Here is everything they said: "{combined_context}"\n\n'
                "Come up with a short, clear calendar event title (2-5 words) based on context clues.\n"
                "Examples: 'Coffee with Jake', 'Sprint Planning', 'Dentist Appointment', 'Swimming Session'\n"
                "Ignore scheduling details like dates and times — focus on WHAT the event is about.\n"
                "If there are no clues about the purpose, reply with exactly: UNCLEAR\n"
                "Reply with ONLY the title or UNCLEAR, nothing else."
            )
            suggested_name = self.capability_worker.text_to_text_response(
                name_prompt,
                system_prompt="You generate short calendar event titles. Reply with only the title.",
            ).strip().strip('"').strip("'")

            self.worker.editor_logging_handler.info(f"[GCal] Auto-suggested name: {suggested_name}")

            if "UNCLEAR" not in suggested_name.upper() and len(suggested_name) >= 2:
                details["summary"] = suggested_name
            else:
                occasion = await self.capability_worker.run_io_loop(
                    "What's it for?"
                )
                self.worker.editor_logging_handler.info(f"[GCal] User described occasion: {occasion}")

                # Re-extract full meeting details from the occasion response —
                # user often packs in time, duration, and attendees here too
                occasion_details = self.extract_meeting_details(occasion)
                if occasion_details:
                    if not details.get("time") and occasion_details.get("time"):
                        details["time"] = occasion_details["time"]
                        self.worker.editor_logging_handler.info(
                            f"[GCal] Captured time from occasion response: {occasion_details['time']}"
                        )
                    if not details.get("date") and occasion_details.get("date"):
                        details["date"] = occasion_details["date"]
                    if occasion_details.get("duration_explicit"):
                        details["duration_minutes"] = occasion_details["duration_minutes"]
                        details["duration_explicit"] = True
                        self.worker.editor_logging_handler.info(
                            f"[GCal] Captured duration from occasion response: {occasion_details['duration_minutes']} min"
                        )
                    # Pick up any new attendee names mentioned in the follow-up
                    new_names = occasion_details.get("attendee_names", [])
                    if new_names and self.contacts:
                        extra_attendees = self.detect_attendees(occasion, llm_names=new_names)
                        for ea in extra_attendees:
                            if ea["email"] not in [a["email"] for a in attendees]:
                                attendees.append(ea)
                                self.worker.editor_logging_handler.info(
                                    f"[GCal] Added attendee from occasion response: {ea['name']}"
                                )

                name_prompt2 = (
                    f'The user is scheduling a meeting. When asked what it\'s for, they said: "{occasion}"\n\n'
                    "Come up with a short, clear calendar event title (2-5 words).\n"
                    "Examples: 'Coffee with Jake', 'Sprint Planning', 'Dentist Appointment'\n"
                    "If their response is too vague, reply with exactly: UNCLEAR\n"
                    "Reply with ONLY the title or UNCLEAR, nothing else."
                )
                suggested_name2 = self.capability_worker.text_to_text_response(
                    name_prompt2,
                    system_prompt="You generate short calendar event titles. Reply with only the title.",
                ).strip().strip('"').strip("'")

                self.worker.editor_logging_handler.info(f"[GCal] Suggested name from follow-up: {suggested_name2}")

                if "UNCLEAR" in suggested_name2.upper() or len(suggested_name2) < 2:
                    name_response = await self.capability_worker.run_io_loop(
                        "What should I call it?"
                    )
                    details["summary"] = name_response.strip()
                else:
                    details["summary"] = suggested_name2

        # --- Date: ask if missing ---
        if not details.get("date"):
            response = await self.capability_worker.run_io_loop("What day?")
            followup = self.extract_meeting_details(f"meeting on {response}")
            if followup and followup.get("date"):
                details["date"] = followup["date"]
                if not details.get("time") and followup.get("time"):
                    details["time"] = followup["time"]
                    self.worker.editor_logging_handler.info(
                        f"[GCal] Also captured time from date response: {followup['time']}"
                    )
                if followup.get("duration_explicit"):
                    details["duration_minutes"] = followup["duration_minutes"]
                    details["duration_explicit"] = True
                if self.contacts:
                    extra_names = followup.get("attendee_names", [])
                    extra_attendees = self.detect_attendees(response, llm_names=extra_names)
                    for ea in extra_attendees:
                        if ea["email"] not in [a["email"] for a in attendees]:
                            attendees.append(ea)
                            self.worker.editor_logging_handler.info(
                                f"[GCal] Added attendee from date response: {ea['name']}"
                            )
            else:
                await self.capability_worker.speak("I didn't get the date. Try again whenever.")
                return

        # --- Time: ask if missing ---
        if not details.get("time"):
            response = await self.capability_worker.run_io_loop("What time?")
            followup = self.extract_meeting_details(f"meeting at {response}")
            if followup and followup.get("time"):
                details["time"] = followup["time"]
                if not details.get("date") and followup.get("date"):
                    details["date"] = followup["date"]
                if followup.get("duration_explicit"):
                    details["duration_minutes"] = followup["duration_minutes"]
                    details["duration_explicit"] = True
                # Check for attendees in this response too
                if self.contacts:
                    extra_names = followup.get("attendee_names", [])
                    extra_attendees = self.detect_attendees(response, llm_names=extra_names)
                    for ea in extra_attendees:
                        if ea["email"] not in [a["email"] for a in attendees]:
                            attendees.append(ea)
                            self.worker.editor_logging_handler.info(
                                f"[GCal] Added attendee from time response: {ea['name']}"
                            )
            else:
                await self.capability_worker.speak("I didn't get the time. Try again whenever.")
                return

        # --- Duration: ask if the user didn't explicitly mention one ---
        duration = details.get("duration_minutes", 30)
        duration_explicit = details.get("duration_explicit", False)

        if not duration_explicit:
            dur_response = await self.capability_worker.run_io_loop(
                "How long should it be?"
            )
            # Try to extract a number from the response
            dur_prompt = (
                f'The user was asked how long a meeting should be and said: "{dur_response}"\n'
                "Extract the duration in minutes as a single integer.\n"
                "Examples: '1 hour' -> 60, 'half hour' -> 30, '45 minutes' -> 45, '90 min' -> 90\n"
                "Reply with ONLY the integer, nothing else."
            )
            dur_raw = self.capability_worker.text_to_text_response(
                dur_prompt,
                system_prompt="Extract meeting duration in minutes. Reply with only an integer.",
            ).strip()

            dur_match = re.search(r"\d+", dur_raw)
            if dur_match:
                duration = int(dur_match.group())
                self.worker.editor_logging_handler.info(f"[GCal] User-specified duration: {duration} min")
            else:
                self.worker.editor_logging_handler.info("[GCal] Couldn't parse duration, using 30 min default.")
                duration = 30

            # Check if the user also mentioned attendees in the duration response
            if self.contacts:
                extra_attendees = self.detect_attendees(dur_response)
                for ea in extra_attendees:
                    if ea["email"] not in [a["email"] for a in attendees]:
                        attendees.append(ea)
                        self.worker.editor_logging_handler.info(
                            f"[GCal] Added attendee from duration response: {ea['name']}"
                        )

        # --- Confirmation ---
        date_label = friendly_date_label(details["date"])
        time_label = self.format_time_for_speech(details["time"])
        recurring_weekly = details.get("recurring_weekly", False)

        # Build readable duration
        if duration >= 60 and duration % 60 == 0:
            dur_label = f"{duration // 60} hour" + ("s" if duration >= 120 else "")
        elif duration > 60:
            hrs = duration // 60
            mins = duration % 60
            dur_label = f"{hrs} hour{'s' if hrs > 1 else ''} and {mins} minutes"
        else:
            dur_label = f"{duration} minute"

        if recurring_weekly:
            confirm_text = (
                f"a weekly recurring {details['summary']}, "
                f"starting {date_label} at {time_label} for {dur_label}"
            )
        else:
            confirm_text = (
                f"a {dur_label} event called {details['summary']} "
                f"{date_label} at {time_label}"
            )

        if attendees:
            names_str = " and ".join(a["name"] for a in attendees)
            confirm_text += f" with {names_str}"

        response = await self.capability_worker.run_io_loop(
            f"I'll set up {confirm_text}. Sound good?"
        )
        parsed = self.parse_confirmation_response(response)
        confirmed = parsed["confirmed"]
        followup = parsed["followup"]

        if not confirmed:
            # Check if the user is correcting details instead of cancelling
            correction = self.extract_meeting_details(response)
            corrected_time = (correction or {}).get("time")
            corrected_date = (correction or {}).get("date")
            corrected_dur = (correction or {}).get("duration_explicit") and (correction or {}).get("duration_minutes")

            if corrected_time or corrected_date or corrected_dur:
                if corrected_time:
                    details["time"] = corrected_time
                if corrected_date:
                    details["date"] = corrected_date
                if corrected_dur:
                    duration = correction["duration_minutes"]

                self.worker.editor_logging_handler.info(
                    f"[GCal] User corrected: time={details['time']} date={details['date']} dur={duration}"
                )

                date_label = friendly_date_label(details["date"])
                time_label = self.format_time_for_speech(details["time"])

                response2 = await self.capability_worker.run_io_loop(
                    f"Got it, {time_label} {date_label} instead. Good?"
                )
                confirmed = self.interpret_yes_no(response2)
                if not confirmed:
                    await self.capability_worker.speak("No worries, scrapping that.")
                    return
            elif followup:
                await self.dispatch_followup(followup)
                return
            else:
                await self.capability_worker.speak("No worries, scrapping that.")
                return

        # --- Build ISO datetimes ---
        try:
            start_dt = datetime.strptime(f"{details['date']} {details['time']}", "%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(minutes=duration)
            start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
            end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[GCal] Date parse error: {e}")
            await self.capability_worker.speak("Something got mixed up with the date. Let's try that again.")
            return

        self.worker.editor_logging_handler.info(
            f"[GCal] Scheduling: {details['summary']} from {start_iso} to {end_iso}"
        )

        # --- Conflict check ---
        conflicts = self.detect_conflicts(start_iso, end_iso)
        if conflicts:
            warning = self.format_conflict_warning(conflicts)
            self.worker.editor_logging_handler.info(f"[GCal] Conflict detected: {[c.get('summary') for c in conflicts]}")
            conflict_response = await self.capability_worker.run_io_loop(
                f"{warning} Want me to schedule it anyway?"
            )
            if not self.interpret_yes_no(conflict_response):
                await self.capability_worker.speak("Alright, didn't schedule it.")
                return

        await self.capability_worker.speak("One sec.")
        self.last_api_error = ""
        event = self.create_event(
            summary=details["summary"],
            start_iso=start_iso,
            end_iso=end_iso,
            description=details.get("description", ""),
            attendees=attendees if attendees else None,
            recurring_weekly=recurring_weekly,
        )

        if event:
            self.last_event = event
            event_link = event.get("htmlLink", "")
            self.worker.editor_logging_handler.info(f"[GCal] Event link: {event_link}")
            if recurring_weekly:
                done_msg = f"Done. {details['summary']} is locked in as a weekly recurring event."
            else:
                done_msg = f"All set. {details['summary']} is on your calendar."
            if attendees:
                names_str = " and ".join(a["name"] for a in attendees)
                done_msg += f" {names_str} will get an invite."

            # Save per-event reminder override if user specified one
            reminder_mins = details.get("reminder_minutes")
            if reminder_mins and isinstance(reminder_mins, int) and reminder_mins > 0:
                event_id = event.get("id", "")
                if event_id:
                    await self.save_event_reminder(event_id, reminder_mins)
                    done_msg += f" I'll remind you {reminder_mins} minutes before."

            await self.capability_worker.speak(done_msg)
            await self.refresh_schedule_md()

            # Dispatch any follow-up from the confirmation response
            if followup:
                await self.dispatch_followup(followup)
        else:
            await self.capability_worker.speak(
                f"That didn't work. The error was: {self.last_api_error}."
            )
