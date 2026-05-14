import json
import re
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

def _build_calendar_service_using_access_token(token):
    creds = Credentials(token=token)
    return build("calendar", "v3", credentials=creds)

def _format_event_for_speech(event: dict) -> str:
    title = event.get("summary", "No title")
    start = event.get("start", {})
    raw_dt = start.get("dateTime", start.get("date", ""))
    location = event.get("location", "")
    location_part = f" at {location}" if location else ""

    # Format datetime nicely for speech
    time_str = "unknown time"
    if raw_dt:
        try:
            # Handle both offset-aware and naive datetimes
            dt = datetime.fromisoformat(raw_dt)
            time_str = dt.strftime("%A %B %d at %I:%M %p").replace(" 0", " ").strip()
        except Exception:
            time_str = raw_dt  # fallback to raw if parsing fails

    return f"{title}{location_part}, starting {time_str}"

# Google Calendar operations
def create_event(
    service,
    title: str,
    description: str,
    start_dt: str,
    end_dt: str,
    timezone_str: str,
    attendees: list,
    location: str,
    reminder_minutes: int,
    add_google_meet: bool,
) -> dict:
    body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_dt, "timeZone": timezone_str},
        "end":   {"dateTime": end_dt,   "timeZone": timezone_str},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email",  "minutes": reminder_minutes},
                {"method": "popup",  "minutes": reminder_minutes},
            ],
        },
    }

    if location:
        body["location"] = location

    if attendees:
        body["attendees"] = [{"email": e.strip()} for e in attendees if e.strip()]

    conference_data_version = 0
    if add_google_meet:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": f"gcal-ability-{int(datetime.now().timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
        conference_data_version = 1

    return (
        service.events()
        .insert(
            calendarId="primary",
            body=body,
            conferenceDataVersion=conference_data_version,
            sendUpdates="all" if attendees else "none",
        )
        .execute()
    )

def list_events(service, time_min: str, time_max: str, max_results: int = 10) -> list:
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return result.get("items", [])

def update_event(service, event_id: str, updates: dict) -> dict:
    event = service.events().get(calendarId="primary", eventId=event_id).execute()
    event.update(updates)
    return (
        service.events()
        .update(
            calendarId="primary",
            eventId=event_id,
            body=event,
            sendUpdates="all",
        )
        .execute()
    )

def delete_event(service, event_id: str) -> None:
    service.events().delete(
        calendarId="primary",
        eventId=event_id,
        sendUpdates="all",
    ).execute()

def search_events_by_title(service, query: str, max_results: int = 5) -> list:
    now = datetime.now(timezone.utc).isoformat()
    result = (
        service.events()
        .list(
            calendarId="primary",
            q=query,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return result.get("items", [])


class GoogleCalendarOfficialCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    # -------------------- Voice helpers --------------------
    async def _ask(self, question: str) -> str:
        await self.capability_worker.speak(question)
        return (await self.capability_worker.user_response()).strip()
    
    async def _ask_yes_no(self, question: str) -> bool:
        answer = await self._ask(question)
        result = self.capability_worker.text_to_text_response(
            f"The user said: \"{answer}\"\n"
            "Are they saying yes or no?\n"
            "YES examples: 'yes', 'yeah', 'yep', 'sure', 'go ahead', 'do it', 'sounds good', 'go for it', 'absolutely', 'please', 'yup'\n"
            "Lean YES for: 'I guess', 'sure why not', 'if you want', 'might as well'\n"
            "NO examples: 'no', 'nah', 'nope', 'not really', 'never mind', 'skip it', 'don't bother', 'no thanks', 'pass'\n"
            "Reply with exactly one word: YES or NO"
        ).strip().upper()
        self.worker.editor_logging_handler.error(f"Yes/No check: '{answer}' → {result}")
        return result.strip() == "YES"
    
    def _is_valid_iso_dt(self, dt_str: Optional[str]) -> bool:
        """Check that a string is a parseable ISO 8601 datetime."""
        if not dt_str:
            return False
        try:
            datetime.fromisoformat(dt_str)
            return True
        except ValueError:
            return False
        
    # -------------------- LLM helpers --------------------
    def _parse_datetime_with_llm(
        self, raw_text: str, timezone_str: str, reference_dt: Optional[str] = None
    ) -> Optional[str]:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        reference_hint = (
            f"\nThe event starts at {reference_dt}. The end time MUST be after the start time. "
            "When AM/PM is not specified, choose whichever interpretation (AM or PM) results in the end time "
            "being as close as possible to — but still after — the start time. "
            "Prefer the shortest duration. For example: start=05:00, end='5:30' → pick 05:30 (not 17:30)."
        ) if reference_dt else ""

        hour_hint = (
            " If no AM/PM indicator is given, treat the time as 24-hour format"
            " (e.g. '3' → 03:00, '15' → 15:00)."
        ) if not reference_dt else ""

        prompt = (
            f"Current date/time: {now_str}, timezone: {timezone_str}.{reference_hint}{hour_hint}\n"
            f"Parse the following into an ISO 8601 datetime string (YYYY-MM-DDTHH:MM:SS), "
            f"no extra text: '{raw_text}'"
        )
        result = self.capability_worker.text_to_text_response(prompt)
        match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?", result)
        return match.group(0) if match else None
    
    def _get_location_from_timezone(self, timezone_str: str) -> str:
        """
        Derive a human-readable city/country from the IANA timezone string
        e.g. 'Asia/Karachi' → 'Karachi, Pakistan'
        Uses LLM for a clean natural-language result.
        """
        prompt = (
            f"Given the IANA timezone '{timezone_str}', what is the most likely city and country? "
            "Reply with only: City, Country — nothing else."
        )
        result = self.capability_worker.text_to_text_response(prompt).strip()
        self.worker.editor_logging_handler.error(f"Location from timezone '{timezone_str}' → '{result}'")
        return result
    
    def _extract_email_with_llm(self, raw_text: str) -> Optional[str]:
        """
        Use LLM to reconstruct a valid email address from voice transcription.
        """
        cleaned_input = raw_text.strip().rstrip(".,!?;:")
        direct_match = re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", cleaned_input)
        if direct_match:
            candidate = direct_match.group(0).rstrip(".,!?;:")  # strip any trailing punct
            if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", candidate):
                self.worker.editor_logging_handler.error(f"Email direct extract: '{raw_text}' → '{candidate}'")
                return candidate

        prompt = (
            "The following text is a voice transcription of someone saying an email address. "
            "Voice-to-text often spells letters individually or replaces '@' with 'at' and '.' with 'dot'. "
            "Reconstruct the single correct email address from the transcription. "
            "Reply with ONLY the email address, nothing else. "
            "If you cannot determine a valid email, reply with the single word: NONE\n\n"
            f"Transcription: \"{cleaned_input}\""
        )
        result = self.capability_worker.text_to_text_response(prompt).strip().lower().rstrip(".,!?;:")
        self.worker.editor_logging_handler.error(f"LLM email extraction: input='{raw_text}' → output='{result}'")
        if result == "none" or "@" not in result:
            return None
        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", result):
            return result
        self.worker.editor_logging_handler.error(f"LLM email failed sanity check: '{result}'")
        return None
    
    def _normalize_location(self, raw_location: str) -> str:
        """Normalize a voice-provided location into a Google Calendar-friendly format."""
        result = self.capability_worker.text_to_text_response(
            f"The user said this location: \"{raw_location}\"\n"
            "Rewrite it as a clean, Google Maps-compatible address or place name.\n"
            "Examples:\n"
            "  'starbucks on main street downtown' → 'Starbucks, Main Street, Downtown'\n"
            "  'the office in new york' → 'New York, NY, USA'\n"
            "  'dubai' → 'Dubai, UAE'\n"
            "  'karachi pakistan' → 'Karachi, Pakistan'\n"
            "  'conference room b' → 'Conference Room B'\n"
            "Reply with ONLY the normalized location string, nothing else."
        ).strip()
        return result

    # -------------------- Create Event --------------------
    async def _flow_create_event(self, service, tz: str, raw_utterance: str = "") -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        # ── Step 1: Try to extract title + start time from trigger phrase ──
        pre_extracted = {}
        if raw_utterance:
            extract_prompt = (
                f"Current date/time: {now_str}, timezone: {tz}.\n"
                f"The user said: \"{raw_utterance}\"\n"
                "Extract any event details they already mentioned.\n"
                "Reply with ONLY a JSON object, no markdown:\n"
                "{\n"                                # ← single braces
                "  \"title\": \"event title or null\",\n"
                "  \"start_time\": \"natural language start time or null\",\n"
                "  \"end_time\": \"natural language end time or null\"\n"
                "  \"attendees\": [\"email1\", \"email2\"] or [],\n"
                "  \"add_meet\": true or false,\n"
                "  \"location\": \"location or null\",\n"
                "  \"reminder_minutes\": number or null\n"
                "}"
            )

            raw = self.capability_worker.text_to_text_response(extract_prompt).strip()
            raw = re.sub(r"```(?:json)?", "", raw).strip()
            self.worker.editor_logging_handler.error(f"Pre-extracted from trigger: {raw}")
            try:
                pre_extracted = json.loads(raw)
            except Exception:
                pre_extracted = {}

        def clean(val):
            return None if not val or str(val).lower().strip() in ("null", "none", "") else val

        pre_title = clean(pre_extracted.get("title"))
        pre_start = clean(pre_extracted.get("start_time"))
        pre_end   = clean(pre_extracted.get("end_time"))
        pre_attendees = [e for e in pre_extracted.get("attendees", []) if e and "@" in e]
        pre_meet      = bool(pre_extracted.get("add_meet", False))
        pre_location  = clean(pre_extracted.get("location"))
        pre_reminder  = pre_extracted.get("reminder_minutes")

        self.worker.editor_logging_handler.error(
            f"Pre-extracted → title: '{pre_title}', start: '{pre_start}', end: '{pre_end}'"
        )

        # ── Step 2: Route smartly based on what was extracted ──
        if pre_title or pre_start:
            # Any partial info → quick mode, it handles missing fields itself
            await self._flow_create_quick(service, tz, now_str, pre_title, pre_start, pre_end, pre_attendees, pre_meet, pre_location, pre_reminder)
        else:
            mode_from_trigger = None
            if raw_utterance:
                mode_check = self.capability_worker.text_to_text_response(
                    f"The user said: \"{raw_utterance}\"\n"
                    "Did they already specify HOW they want to create the event?\n"
                    "DETAILED examples: 'step by step', 'walk me through it', 'detailed', 'all the details', 'the long way'\n"
                    "QUICK examples: 'quick', 'fast', 'just do it', 'simple', 'quickly'\n"
                    "NONE: they didn't specify a mode, just said something like 'create an event' or 'schedule a meeting'\n"
                    "Reply with exactly one word: DETAILED, QUICK, or NONE"
                ).strip().upper()
                self.worker.editor_logging_handler.error(f"Mode from trigger: {mode_check}")
                if mode_check.strip() in ("DETAILED", "QUICK"):
                    mode_from_trigger = mode_check.strip()

            if mode_from_trigger == "DETAILED":
                await self._flow_create_detailed(service, tz)
            elif mode_from_trigger == "QUICK":
                await self._flow_create_quick(service, tz, now_str, pre_title, pre_start, pre_end, pre_attendees, pre_meet, pre_location, pre_reminder)
            elif pre_title or pre_start:
                # Partial info extracted — quick mode handles missing fields
                await self._flow_create_quick(service, tz, now_str, pre_title, pre_start, pre_end, pre_attendees, pre_meet, pre_location, pre_reminder)
            else:
                # Nothing extracted — ask quick or step by step
                mode_raw = await self._ask(
                    "Want to do it quick, or go through it step by step?"
                )
                mode_intent = self.capability_worker.text_to_text_response(
                    f"The user said: \"{mode_raw}\"\n"
                    "Decide if this should be QUICK or DETAILED event creation mode.\n"
                    "Reply QUICK if ANY of these are true:\n"
                    "  - They used words like quick, fast, quickly, simple, short, just do it, go ahead\n"
                    "  - They already provided event details like a title, time, attendees, or other specifics\n"
                    "  - Their message contains enough info to create an event without step-by-step questions\n"
                    "Reply DETAILED only if they explicitly asked for step-by-step, full details, or provided no info at all.\n"
                    "Reply with exactly one word: QUICK or DETAILED"
                ).strip().upper()
                self.worker.editor_logging_handler.error(f"Mode intent: {mode_intent}")
                if mode_intent.strip() == "QUICK":
                    # Try to extract any details the user already provided in the same sentence
                    extract_prompt = (
                        f"Current date/time: {now_str}, timezone: {tz}.\n"
                        f"The user said: \"{mode_raw}\"\n"
                        "Extract any event details they already mentioned.\n"
                        "Reply with ONLY a JSON object, no markdown:\n"
                        "{\n"
                        "  \"title\": \"event title or null\",\n"
                        "  \"start_time\": \"natural language start time or null\",\n"
                        "  \"end_time\": \"natural language end time or null\",\n"
                        "  \"attendees\": [\"email1\", \"email2\"] or [],\n"
                        "  \"add_meet\": true or false,\n"
                        "  \"location\": \"location or null\",\n"
                        "  \"reminder_minutes\": number or null\n"
                        "}"
                    )
                    raw = self.capability_worker.text_to_text_response(extract_prompt).strip()
                    raw = re.sub(r"```(?:json)?", "", raw).strip()
                    self.worker.editor_logging_handler.error(f"Mode-raw pre-extract: {raw}")
                    try:
                        mode_extracted = json.loads(raw)
                    except Exception:
                        mode_extracted = {}

                    def clean(val):
                        return None if not val or str(val).lower().strip() in ("null", "none", "") else val

                    mode_title     = clean(mode_extracted.get("title"))
                    mode_start     = clean(mode_extracted.get("start_time"))
                    mode_end       = clean(mode_extracted.get("end_time"))
                    mode_attendees = [e for e in mode_extracted.get("attendees", []) if e and "@" in e]
                    mode_meet      = bool(mode_extracted.get("add_meet", False))
                    mode_location = clean(mode_extracted.get("location"))
                    mode_reminder  = mode_extracted.get("reminder_minutes")

                    
                    await self._flow_create_quick(service, tz, now_str, mode_title, mode_start, mode_end, mode_attendees, mode_meet, mode_location, mode_reminder)
                else:
                    await self._flow_create_detailed(service, tz)

    async def _flow_create_quick(
        self, service, tz: str, now_str: str,
        pre_title: Optional[str] = None,
        pre_start: Optional[str] = None,
        pre_end:   Optional[str] = None,
        pre_attendees: list = None,
        pre_meet: bool = False,
        pre_location: Optional[str] = None,
        pre_reminder: Optional[int] = None,
    ) -> None:
        """Quick mode: ask everything in one shot, extract with LLM, then create."""

        # ── Build context-aware single question ──
        # If all critical fields already known, skip asking entirely
        all_known = pre_title and pre_start and pre_end

        if all_known:
            # Skip one-shot — use pre values directly
            title            = pre_title
            start_raw        = pre_start
            end_raw          = pre_end
            attendees        = pre_attendees or []
            add_meet         = pre_meet
            reminder_minutes = int(str(pre_reminder or 60))
            location = self._normalize_location(pre_location) if pre_location else ""

            self.worker.editor_logging_handler.error("All fields pre-known, skipping one-shot question")
        else:
            if pre_title and pre_start:
                context = f"I'll create '{pre_title}' starting {pre_start}"
                if pre_end:
                    context += f" until {pre_end}"
                one_shot_raw = await self._ask(
                    f"{context}. Anything else to add? "
                )
            elif pre_title and not pre_start:
                one_shot_raw = await self._ask(
                    f"Got it, creating '{pre_title}'. "
                    "When does it start? You can also mention end time, attendees, Google Meet, location or a reminder."
                )
            elif pre_start and not pre_title:
                one_shot_raw = await self._ask(
                    f"Got it, starting at {pre_start}. "
                    "What should we call the event? You can also mention end time, attendees, Google Meet, or a reminder."
                )
            else:
                one_shot_raw = await self._ask(
                    "Go ahead — give me the title, time, and anything else you want to add."
                )

            self.worker.editor_logging_handler.error(f"Quick one-shot input: '{one_shot_raw}'")


            # ── Extract everything from the single response ──
            extract_prompt = (
                f"Current date/time: {now_str}, timezone: {tz}.\n"
                f"Pre-known title: {pre_title or 'null'}\n"
                f"Pre-known start: {pre_start or 'null'}\n"
                f"Pre-known end: {pre_end or 'null'}\n"
                f"The user said: \"{one_shot_raw}\"\n\n"
                "Extract all event details. If a pre-known value exists and user didn't override it, use the pre-known value.\n"
                "For attendees, extract all email addresses mentioned.\n"
                "Reply with ONLY a JSON object, no markdown:\n"
                "{\n"
                "  \"title\": \"event title or null\",\n"
                "  \"start_time\": \"natural language or null\",\n"
                "  \"end_time\": \"natural language or null\",\n"
                "  \"attendees\": [\"email1\", \"email2\"] or [],\n"
                "  \"add_meet\": true or false,\n"
                "  \"location\": \"location or null\",\n"
                "  \"reminder_minutes\": number or null\n"
                "}"
            )
            raw = self.capability_worker.text_to_text_response(extract_prompt).strip()
            raw = re.sub(r"```(?:json)?", "", raw).strip()
            self.worker.editor_logging_handler.error(f"Quick extracted: {raw}")

            try:
                extracted = json.loads(raw)
            except Exception:
                extracted = {}

            def clean(val):
                return None if not val or str(val).lower().strip() in ("null", "none", "") else val

            title     = clean(extracted.get("title"))
            start_raw = clean(extracted.get("start_time"))
            end_raw   = clean(extracted.get("end_time"))
            # ── Use pre_* as fallbacks so they're never lost ──
            attendees        = [e for e in extracted.get("attendees", []) if e and "@" in e] or (pre_attendees or [])
            add_meet         = bool(extracted.get("add_meet", False)) or pre_meet
            reminder_minutes = int(str(extracted.get("reminder_minutes") or pre_reminder or 60))
            raw_loc = clean(extracted.get("location")) or pre_location or ""
            location = self._normalize_location(raw_loc) if raw_loc else ""


        # ── Ask only for what's missing — no step-by-step fallback ──
        if not title:
            title_raw = await self._ask("What should we call the event?")
            title_extract = self.capability_worker.text_to_text_response(
                f"The user said: \"{title_raw}\"\n"
                "Extract ONLY the event title/name they mentioned.\n"
                "Reply with ONLY the title, nothing else."
            ).strip().rstrip(".,!?;:")
            title = title_extract if title_extract else title_raw
            self.worker.editor_logging_handler.error(f"Extracted title: '{title}'")

        if not start_raw:
            while True:
                start_raw_input = await self._ask("When does it start?")
                is_time = self.capability_worker.text_to_text_response(
                    f"The user said: \"{start_raw_input}\"\n"
                    "Does this contain a date or time? Examples of YES: '3 PM', 'tomorrow', 'Friday at 2', 'next week'.\n"
                    "Examples of NO: 'I know', 'okay', 'sure', 'never mind', 'skip'.\n"
                    "Reply with exactly one word: YES or NO"
                ).strip().upper()
                if "YES" in is_time:
                    start_extract = self.capability_worker.text_to_text_response(
                        f"The user said: \"{start_raw_input}\"\n"
                        "Extract ONLY the start date/time they mentioned in natural language.\n"
                        "Reply with ONLY the time/date, nothing else. Example: '4 PM', 'tomorrow at 3 PM'."
                    ).strip().rstrip(".,!?;:")
                    start_raw = start_extract if start_extract else start_raw_input
                    break
                else:
                    await self.capability_worker.speak(
                        "Sorry, I didn't catch a time. Please say something like 'tomorrow at 3 PM'."
                    )

        # ── Parse start time ──
        def _is_future_with_time(dt_str: str, raw_input: str = "") -> tuple[bool, str]:
            try:
                dt_naive = datetime.fromisoformat(dt_str).replace(tzinfo=None)
                now_local = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
                if dt_naive.hour == 0 and dt_naive.minute == 0 and dt_naive.second == 0:
                    # Only reject midnight if user didn't explicitly say a midnight-like time
                    if raw_input:
                        has_time = self.capability_worker.text_to_text_response(
                            f"The user said: \"{raw_input}\"\n"
                            "Does this explicitly mention a specific time of day?\n"
                            "YES examples: '12am', 'midnight', '12:00 AM', 'noon', '12pm', '3 PM', 'half past two'\n"
                            "NO examples: 'tomorrow', 'next Friday', 'March 15th', 'this weekend'\n"
                            "Reply with exactly one word: YES or NO"
                        ).strip().upper()
                        if has_time == "YES":
                            pass  # user said midnight explicitly — allow it
                        else:
                            return False, "no_time"
                    else:
                        return False, "no_time"
                if dt_naive < now_local:
                    return False, "past"
                return True, "ok"
            except Exception:
                return False, "invalid"

        await self.capability_worker.speak("Got it, one moment.")
        while True:
            start_dt = self._parse_datetime_with_llm(start_raw, tz)
            if not self._is_valid_iso_dt(start_dt):
                start_raw = await self._ask(
                    "I couldn't parse that. Please try again, like 'Friday at 2 PM'."
                )
                continue
            valid, reason = _is_future_with_time(start_dt, raw_input=start_raw)  # ← pass start_raw here
            if reason == "no_time":
                start_raw = await self._ask(
                    "Please include a specific time as well, like 'tomorrow at 3 PM'."
                )
                continue
            if reason == "past":
                start_raw = await self._ask(
                    "That time has already passed. Please choose a future date and time."
                )
                continue
            break

        # ── Parse end time — default to +1 hour if not provided or invalid ──
        end_dt = self._parse_datetime_with_llm(end_raw, tz, reference_dt=start_dt) if end_raw else None
        if not self._is_valid_iso_dt(end_dt) or (
            self._is_valid_iso_dt(end_dt) and
            datetime.fromisoformat(end_dt) <= datetime.fromisoformat(start_dt)
        ):
            end_dt = (datetime.fromisoformat(start_dt) + timedelta(hours=1)).isoformat()
            self.worker.editor_logging_handler.error(f"End time defaulted to +1hr: {end_dt}")

        self.worker.editor_logging_handler.error(
            f"Quick → title: {title}, start: {start_dt}, end: {end_dt}, "
            f"attendees: {attendees}, meet: {add_meet}, reminder: {reminder_minutes}m"
        )

        # ── Create ──
        await self.capability_worker.speak("Creating your event now...")
        try:
            created = create_event(
                service=service,
                title=title,
                description="",
                start_dt=start_dt,
                end_dt=end_dt,
                timezone_str=tz,
                attendees=attendees,
                location=location,
                reminder_minutes=reminder_minutes,
                add_google_meet=add_meet,
            )
            self.worker.editor_logging_handler.error(f"Quick event created: {created.get('id')}")

            meet_link = ""
            for ep in created.get("conferenceData", {}).get("entryPoints", []):
                if ep.get("entryPointType") == "video":
                    meet_link = ep.get("uri", "")
                    break

            summary = f"Done! '{title}' has been created"
            if meet_link:
                summary += " with a Google Meet link"
            if attendees:
                count = len(attendees)
                summary += f". Invites sent to {count} {'person' if count == 1 else 'people'}"
            summary += "."
            await self.capability_worker.speak(summary)
        except HttpError as e:
            await self.capability_worker.speak(f"Sorry, there was a problem: {e.reason}")

    async def _flow_create_detailed(
        self, service, tz: str,
        pre_title: Optional[str] = None,
        pre_start: Optional[str] = None
    ) -> None:
        """Full step-by-step create flow, optionally pre-filling title/start."""
        # Title
        if pre_title:
            await self.capability_worker.speak(f"Got it, '{pre_title}'.")
            title = pre_title
        else:
            title_raw = await self._ask("What should we call it?")
            title = self.capability_worker.text_to_text_response(
                f"The user said: \"{title_raw}\"\n"
                "Extract ONLY the event title or name they mentioned.\n"
                "Strip filler words like 'call it', 'name it', 'title is', 'let's call it'.\n"
                "Examples: 'call it team standup' → 'Team Standup', 'it's a dentist appointment' → 'Dentist Appointment'\n"
                "Reply with ONLY the clean title, nothing else."
            ).strip().rstrip(".,!?;:")
            title = title if title else title_raw
            self.worker.editor_logging_handler.error(f"Extracted title: '{title}'")

        # Description
        description_raw = await self._ask("Would you like to add a description? If not, say skip.")
        desc_words = re.sub(r"[^\w\s]", "", description_raw.lower()).strip().split()
        if desc_words == "skip":
            description = ""
        else:
            description = description_raw

        # Start date/time
        if pre_start:
            await self.capability_worker.speak(f"Using start time: {pre_start}. One moment.")
            start_dt = self._parse_datetime_with_llm(pre_start, tz)
        else:
            start_raw = await self._ask("When does it start? For example, 'tomorrow at 3 PM'.")
            await self.capability_worker.speak("Got it, one moment.")
            start_dt = self._parse_datetime_with_llm(start_raw, tz)

        while True:
            if not self._is_valid_iso_dt(start_dt):
                start_raw = await self._ask("I couldn't parse that. Try again, like 'Friday at 2 PM'.")
                await self.capability_worker.speak("Got it, one moment.")
                start_dt = self._parse_datetime_with_llm(start_raw, tz)
                continue
            dt_naive = datetime.fromisoformat(start_dt).replace(tzinfo=None)
            now_local = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
            
            if dt_naive.hour == 0 and dt_naive.minute == 0 and dt_naive.second == 0:
                has_time = self.capability_worker.text_to_text_response(
                    f"The user said: \"{start_raw}\"\n"
                    "Does this explicitly mention a specific time of day?\n"
                    "YES examples: '12am', 'midnight', '12:00 AM', 'noon', '12pm', '3 PM', 'half past two'\n"
                    "NO examples: 'tomorrow', 'next Friday', 'March 15th', 'this weekend'\n"
                    "Reply with exactly one word: YES or NO"
                ).strip().upper()
                if "YES" not in has_time:
                    start_raw = await self._ask(
                        "Please include a specific time as well, like 'tomorrow at 3 PM'."
                    )
                    await self.capability_worker.speak("Got it, one moment.")
                    start_dt = self._parse_datetime_with_llm(start_raw, tz)
                    continue
            if dt_naive < now_local:
                start_raw = await self._ask(
                    "That time has already passed. Please choose a future date and time."
                )
                await self.capability_worker.speak("Got it, one moment.")
                start_dt = self._parse_datetime_with_llm(start_raw, tz)
                continue
            break

        # End date/time
        end_raw = await self._ask("When does it end?")
        await self.capability_worker.speak("Got it, one moment.")
        end_dt = self._parse_datetime_with_llm(end_raw, tz, reference_dt=start_dt)
        while True:
            if not self._is_valid_iso_dt(end_dt):
                end_raw = await self._ask("I couldn't parse that end time. Please try again.")
                end_dt = self._parse_datetime_with_llm(end_raw, tz, reference_dt=start_dt)
                continue
            if datetime.fromisoformat(end_dt) <= datetime.fromisoformat(start_dt):
                end_raw = await self._ask(
                    f"The end time must be after the start at {start_dt[11:16]}. When should it end?"
                )
                end_dt = self._parse_datetime_with_llm(end_raw, tz, reference_dt=start_dt)
                continue
            break
        self.worker.editor_logging_handler.error(f"End time: {end_dt}")

        # Attendees
        attendees: list = []
        want_attendee = await self._ask_yes_no("Would you like to add an attendee?")
        while want_attendee:
            raw_email_input = await self._ask(
                "Please say the email address. You can spell it out."
            )
            email = self._extract_email_with_llm(raw_email_input)
            if email:
                attendees.append(email)
                await self.capability_worker.speak(f"Got it. Added {email}.")
            else:
                await self.capability_worker.speak("I couldn't recognise that email. Let's try again.")
                raw_email_input = await self._ask("Please spell it out clearly.")
                email = self._extract_email_with_llm(raw_email_input)
                if email:
                    attendees.append(email)
                    await self.capability_worker.speak(f"Got it. Added {email}.")
                else:
                    await self.capability_worker.speak("I still couldn't get that — skipping.")
            want_attendee = await self._ask_yes_no("Would you like to add another attendee?")

        # Location
        location     = ""
        want_location = await self._ask_yes_no("Would you like to add a location?")
        if want_location:
            location_raw = await self._ask("What is the location?")
            location = self._normalize_location(location_raw.strip())
        else:
            location = ""
        
        add_meet     = await self._ask_yes_no("Should I add a Google Meet video call link?")
        
        # Reminder
        reminder_raw = await self._ask("When should I remind you? Say skip to default to an hour before.")
        reminder_minutes_str = self.capability_worker.text_to_text_response(
            f"The user said: \"{reminder_raw}\"\n"
            "Extract the reminder duration in minutes as an integer.\n"
            "Examples: 'half an hour' → 30, 'an hour' → 60, '15 mins' → 15, 'skip' or unclear → 60.\n"
            "Reply with ONLY the integer, nothing else."
        ).strip()
        reminder_nums = re.findall(r"\d+", reminder_minutes_str)
        reminder_minutes = int(reminder_nums[0]) if reminder_nums else 60


        await self.capability_worker.speak("Creating your event now...")
        try:
            created = create_event(
                service=service,
                title=title,
                description=description,
                start_dt=start_dt,
                end_dt=end_dt,
                timezone_str=tz,
                attendees=attendees,
                location=location,
                reminder_minutes=reminder_minutes,
                add_google_meet=add_meet,
            )
            self.worker.editor_logging_handler.error(f"Detailed event created: {created.get('id')}")

            meet_link = ""
            for ep in created.get("conferenceData", {}).get("entryPoints", []):
                if ep.get("entryPointType") == "video":
                    meet_link = ep.get("uri", "")
                    break

            summary = f"Done! I created '{title}'"
            if meet_link:
                summary += ". A Google Meet link has been added"
            if attendees:
                count = len(attendees)
                summary += f". Invited {count} {'person' if count == 1 else 'people'}"
            summary += "."
            await self.capability_worker.speak(summary)
        except HttpError as e:
            await self.capability_worker.speak(f"Sorry, there was a problem creating the event: {e.reason}")

    # -------------------- List Events --------------------
    async def _flow_list_events(self, service, tz: str, raw_utterance: str = "") -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        classify_prompt = (
            f"Current date/time: {now_str}, timezone: {tz}.\n"
            f"The user said: \"{raw_utterance}\"\n"
            "Classify their calendar listing intent and extract any date info.\n"
            "Reply with ONLY a JSON object, no markdown, no explanation:\n"
            "{\n"
            "  \"type\": \"today\" | \"this_week\" | \"this_month\" | \"specific_date\" | \"date_range\" | \"upcoming\",\n"
            "  \"date\": \"YYYY-MM-DD or null\",\n"
            "  \"date_from\": \"YYYY-MM-DD or null\",\n"
            "  \"date_to\": \"YYYY-MM-DD or null\",\n"
            "  \"n\": <number or null>\n"
            "}"
        )
        raw_json = self.capability_worker.text_to_text_response(classify_prompt).strip()
        raw_json = re.sub(r"```(?:json)?", "", raw_json).strip().rstrip("`").strip()
        self.worker.editor_logging_handler.error(f"List intent classification: {raw_json}")

        try:
            parsed = json.loads(raw_json)
        except Exception:
            parsed = {"type": "unknown"}

        sub_type = parsed.get("type", "unknown")
        now_utc = datetime.now(timezone.utc)

        # If ambiguous, ask once
        if sub_type == "unknown":
            choice = (await self._ask(
                "Would you like today's events, this week's, this month's, "
                "events for a specific date, a date range, or upcoming events?"
            )).lower()
            sub_type = self.capability_worker.text_to_text_response(
                f"The user said: \"{choice}\"\n"
                "Classify their calendar listing intent.\n"
                "Examples:\n"
                "  'what's on today' → today\n"
                "  'what do I have on' → today\n"
                "  'this week' / 'next few days' / 'what's coming up this week' → this_week\n"
                "  'this month' / 'rest of the month' → this_month\n"
                "  'on the 15th' / 'next Friday' / 'March 20th' → specific_date\n"
                "  'from Monday to Thursday' / 'between the 1st and 5th' → date_range\n"
                "  'what's next' / 'coming up' / 'my next few events' → upcoming\n"
                "Reply with exactly one word: today, this_week, this_month, specific_date, date_range, or upcoming."
            ).strip().lower()

        # Execute sub-type
        if sub_type == "today":
            self.worker.editor_logging_handler.error("Listing today's events")
            start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            events = list_events(service, start_of_day.isoformat(), end_of_day.isoformat())
            if not events:
                await self.capability_worker.speak("You have no events scheduled for today.")
            else:
                await self.capability_worker.speak(f"You have {len(events)} events today.")
                for ev in events:
                    await self.capability_worker.speak(_format_event_for_speech(ev))

        elif sub_type == "specific_date":
            date_str = parsed.get("date")
            # If LLM already extracted the date, use it — otherwise ask
            if not date_str:
                date_raw = await self._ask("Which date would you like to check?")
                date_str = self._parse_datetime_with_llm(date_raw + " 00:00", tz)
                if date_str:
                    date_str = date_str[:10]  # keep YYYY-MM-DD only
            self.worker.editor_logging_handler.error(f"Specific date: {date_str}")
            if not date_str:
                await self.capability_worker.speak("I couldn't understand that date. Please try again.")
                return
            start_dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            end_dt = start_dt + timedelta(days=1)
            events = list_events(service, start_dt.isoformat(), end_dt.isoformat())
            if not events:
                readable = datetime.fromisoformat(date_str).strftime("%B %d")
                await self.capability_worker.speak(f"Nothing on {readable}.")
            else:
                await self.capability_worker.speak(f"Found {len(events)} events on {date_str}.")
                for ev in events:
                    await self.capability_worker.speak(_format_event_for_speech(ev))

        elif sub_type == "date_range":
            from_str = parsed.get("date_from")
            to_str   = parsed.get("date_to")
            # Ask for any missing piece
            if not from_str:
                raw = await self._ask("What is the start date of the range?")
                result = self._parse_datetime_with_llm(raw + " 00:00", tz)
                from_str = result[:10] if result else None
            if not to_str:
                raw = await self._ask("What is the end date of the range?")
                result = self._parse_datetime_with_llm(raw + " 23:59", tz)
                to_str = result[:10] if result else None
            self.worker.editor_logging_handler.error(f"Date range: {from_str} → {to_str}")
            if not from_str or not to_str:
                await self.capability_worker.speak("I couldn't parse those dates. Please try again.")
                return
            from_dt = datetime.fromisoformat(from_str).replace(tzinfo=timezone.utc)
            to_dt   = datetime.fromisoformat(to_str).replace(hour=23, minute=59, tzinfo=timezone.utc)
            events  = list_events(service, from_dt.isoformat(), to_dt.isoformat(), max_results=20)
            if not events:
                await self.capability_worker.speak("No events found in that range.")
            else:
                await self.capability_worker.speak(f"Found {len(events)} event(s) between {from_str} and {to_str}.")
                for ev in events:
                    await self.capability_worker.speak(_format_event_for_speech(ev))

        elif sub_type == "this_week":
            # Monday→Sunday of the current week
            today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today - timedelta(days=today.weekday())          # Monday
            week_end   = week_start + timedelta(days=7)
            self.worker.editor_logging_handler.error(f"Listing this week: {week_start.date()} → {week_end.date()}")
            events = list_events(service, now_utc.isoformat(), week_end.isoformat(), max_results=50)
            if not events:
                await self.capability_worker.speak("You have no events this week.")
            else:
                await self.capability_worker.speak(f"You have {len(events)} event(s) this week.")
                for ev in events:
                    await self.capability_worker.speak(_format_event_for_speech(ev))

        elif sub_type == "this_month":
            today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            month_start = today.replace(day=1)
            # First day of next month
            if today.month == 12:
                month_end = today.replace(year=today.year + 1, month=1, day=1)
            else:
                month_end = today.replace(month=today.month + 1, day=1)
            self.worker.editor_logging_handler.error(f"Listing this month: {month_start.date()} → {month_end.date()}")
            events = list_events(service, now_utc.isoformat(), month_end.isoformat(), max_results=100)
            if not events:
                await self.capability_worker.speak("You have no events this month.")
            else:
                await self.capability_worker.speak(f"You have {len(events)} event(s) this month.")
                for ev in events:
                    await self.capability_worker.speak(_format_event_for_speech(ev))

        else:  # upcoming
            n = parsed.get("n") or 5
            self.worker.editor_logging_handler.error(f"Listing next {n} upcoming events")
            far_future = (now_utc + timedelta(days=365)).isoformat()
            events = list_events(service, now_utc.isoformat(), far_future, max_results=n)
            if not events:
                await self.capability_worker.speak("You have no upcoming events.")
            else:
                await self.capability_worker.speak(f"Here are your next {len(events)} events.")
                for ev in events:
                    await self.capability_worker.speak(_format_event_for_speech(ev))

    # -------------------- Update Event --------------------
    async def _flow_update_event(self, service, tz: str, raw_utterance: str = "") -> None:
        now_utc = datetime.now(timezone.utc)
        one_month = (now_utc + timedelta(days=30)).isoformat()
        all_events = list_events(service, now_utc.isoformat(), one_month, max_results=50)

        if not all_events:
            await self.capability_worker.speak("You have no upcoming events to update.")
            return

        event_list_str = "\n".join(
            [f"- id: {ev['id']} | title: {ev.get('summary', 'Untitled')}" for ev in all_events]
        )

        event = None
        changes_raw = ""

        # ── Step 1: Try to extract event name from trigger phrase ──
        if raw_utterance:
            extract_prompt = (
                f"The user said: \"{raw_utterance}\"\n"
                f"Here are all upcoming calendar events:\n{event_list_str}\n\n"
                "Extract the event they want to update AND any changes they already mentioned.\n"
                "Match the event name using case-insensitive, partial, and phonetic matching.\n"
                "For example 'meeting' and 'gathering' are phonetic somewhat similar yet very different"
                "Reply with ONLY a JSON object, no markdown:\n"
                "{\n"
                "  \"extracted_name\": \"event name they mentioned, or null if none\",\n"
                "  \"matched_id\": \"matching event id, or null if no match\",\n"
                "  \"has_changes\": true or false,\n"
                "  \"changes_summary\": \"verbatim portion of the message describing what to change, or null\"\n"
                "}"
            )
            raw_result = self.capability_worker.text_to_text_response(extract_prompt).strip()
            raw_result = re.sub(r"```(?:json)?", "", raw_result).strip().rstrip("`").strip()
            self.worker.editor_logging_handler.error(f"Update trigger extract: {raw_result}")

            try:
                match_data = json.loads(raw_result)
            except Exception:
                match_data = {}

            extracted_name  = match_data.get("extracted_name")
            matched_id      = match_data.get("matched_id")
            has_changes     = bool(match_data.get("has_changes", False))
            changes_summary = match_data.get("changes_summary")

            # Clean nulls
            for key in ["extracted_name", "matched_id", "changes_summary"]:
                val = match_data.get(key)
                if isinstance(val, str) and val.lower() in ("null", "none", ""):
                    if key == "extracted_name": extracted_name = None
                    elif key == "matched_id": matched_id = None
                    elif key == "changes_summary": changes_summary = None

            self.worker.editor_logging_handler.error(
                f"Update → extracted: '{extracted_name}' | matched: '{matched_id}' | "
                f"has_changes: {has_changes} | changes: '{changes_summary}'"
            )

            if extracted_name and matched_id:
                event = next((ev for ev in all_events if ev["id"] == matched_id), None)
                if event and has_changes and changes_summary:
                    # Changes already in trigger — skip asking
                    changes_raw = changes_summary
                    self.worker.editor_logging_handler.error("Changes extracted from trigger, skipping ask")
                elif event:
                    # Event found but no changes in trigger — ask what to change with field menu
                    await self.capability_worker.speak(
                        f"Got '{event.get('summary', 'Untitled')}'. What do you want to change?"
                    )
                    changes_raw = await self.capability_worker.user_response()

            elif extracted_name and not matched_id:
                options_text = ", ".join([ev.get("summary", "Untitled") for ev in all_events[:3]])

                await self.capability_worker.speak(
                    f"I couldn't find an event called '{extracted_name}'. "
                    f"Your upcoming events are: {options_text}."
                )

        # ── Step 2: If event not resolved yet, ask which event + what to change in one go ──
        if not event:
            combined_raw = await self._ask(
                "Which event, and what do you want to change?"
            )
            self.worker.editor_logging_handler.error(f"Combined update input: '{combined_raw}'")

            pick_prompt = (
                f"The user said: \"{combined_raw}\"\n"
                f"Here are all upcoming calendar events:\n{event_list_str}\n\n"
                "Which event are they referring to? Use case-insensitive, partial, and phonetic matching.\n"
                "Reply with ONLY the event id, or NONE."
            )
            matched_id = self.capability_worker.text_to_text_response(pick_prompt).strip().rstrip(".,!?;:")
            event = next((ev for ev in all_events if ev["id"] == matched_id), None)

            if not event:
                options_text = ", ".join(
                    [f"option {i+1}: {ev.get('summary', 'Untitled')}" for i, ev in enumerate(all_events[:5])]
                )
                pick_raw = await self._ask(
                    f"I couldn't find that event. Your next 5 events are: {options_text}. Which one?"
                )
                pick_result = self.capability_worker.text_to_text_response(
                    f"The user said: \"{pick_raw}\". There are up to 5 options. "
                    "Reply with ONLY the integer (1-based) of the chosen option."
                ).strip()
                nums = re.findall(r"\d+", pick_result)
                idx = max(0, min(int(nums[0]) - 1 if nums else 0, len(all_events[:5]) - 1))
                event = all_events[idx]

            # The combined input already contains what to change — reuse it
            changes_raw = combined_raw
        elif not changes_raw:
            # Event resolved from trigger but no changes mentioned — ask what to change
            await self.capability_worker.speak(
                f"Got '{event.get('summary', 'Untitled')}'. What do you want to change?"
            )
            changes_raw = await self.capability_worker.user_response()
        # else: changes_raw already populated from trigger — proceed directly

        self.worker.editor_logging_handler.error(f"Updating event: '{event.get('summary')}' | changes: '{changes_raw}'")

        # ── Step 3: Extract fields + values from changes_raw ──
        def _classify_changes(text: str) -> dict:
            classify_prompt = (
                f"The user wants to update a calendar event and said: \"{text}\"\n"
                "Extract what they want to change and any values they already provided.\n"
                "For Google Meet: if they say 'add meet', 'add video call', set add_meet=true. "
                "If they say 'remove meet', 'remove video call', set remove_meet=true.\n"
                "Natural language examples and their field mappings:\n"
                "  'bump it to 3 PM' / 'push it to Thursday' → start_time or date\n"
                "  'move it back an hour' → start_time + end_time\n"
                "  'rename it to kickoff' → title\n"
                "  'add John to it' / 'invite sarah at gmail' → add_attendee\n"
                "  'drop the meet link' / 'remove video call' → remove_meet\n"
                "  'remind me earlier' / 'set a reminder for 30 minutes' → reminder\n"
                "Reply with ONLY a JSON object, no markdown:\n"
                "{\n"
                "  \"fields\": [list from: \"title\", \"description\", \"start_time\", \"end_time\", \"date\", \"location\", \"add_attendee\", \"remove_attendee\", \"update_attendee\", \"reminder\", \"add_meet\", \"remove_meet\"],\n"
                "  \"new_title\": \"extracted new title or null\",\n"
                "  \"new_description\": \"extracted new description or null\",\n"
                "  \"new_start_time\": \"extracted start time in natural language or null\",\n"
                "  \"new_end_time\": \"extracted end time in natural language or null\",\n"
                "  \"new_date\": \"extracted date in natural language or null\",\n"
                "  \"new_location\": \"extracted location or null\",\n"
                "  \"new_attendees\": [\"email1\", \"email2\"] or [],\n"
                "  \"reminder_minutes\": \"extracted number or null\"\n"
                "}"
            )
            raw = self.capability_worker.text_to_text_response(classify_prompt).strip()
            raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
            self.worker.editor_logging_handler.error(f"Update fields extracted: {raw}")
            try:
                return json.loads(raw)
            except Exception:
                return {"fields": []}

        extracted = _classify_changes(changes_raw)
        fields = extracted.get("fields", [])

        # ── Step 4: Apply changes in a loop ──
        while True:
            updates: dict = {}

            if "title" in fields:
                new_title = extracted.get("new_title")
                if new_title:
                    await self.capability_worker.speak(f"Got it, renaming to '{new_title}'.")
                    updates["summary"] = new_title
                else:
                    updates["summary"] = await self._ask("What should the new title be?")

            if "description" in fields:
                new_desc = extracted.get("new_description")
                # Guard against LLM returning placeholder text instead of null
                if new_desc and len(new_desc) < 500 and "extracted" not in new_desc.lower() and "null" not in new_desc.lower():
                    updates["description"] = new_desc
                else:
                    updates["description"] = await self._ask("What should the new description be?")
            
            if "location" in fields:
                new_location = extracted.get("new_location")
                # Guard against LLM placeholder values
                if new_location and str(new_location).lower().strip() not in ("null", "none", "extracted new location", ""):
                    normalized = self._normalize_location(new_location)
                    await self.capability_worker.speak(f"Got it, setting location to '{normalized}'.")
                else:
                    raw_loc = await self._ask("What should the new location be?")
                    normalized = self._normalize_location(raw_loc.strip())
                    await self.capability_worker.speak(f"Got it, setting location to '{normalized}'.")
                updates["location"] = normalized

            if "start_time" in fields and "end_time" not in fields:
                new_start_raw = extracted.get("new_start_time") or await self._ask("What is the new start time?")
                new_start_dt = self._parse_datetime_with_llm(new_start_raw, tz)
                if new_start_dt:
                    updates["start"] = {"dateTime": new_start_dt, "timeZone": tz}
                    existing_start = event.get("start", {}).get("dateTime", "")
                    existing_end   = event.get("end",   {}).get("dateTime", "")
                    if existing_start and existing_end:
                        duration = datetime.fromisoformat(existing_end.replace("Z", "+00:00")) - \
                                datetime.fromisoformat(existing_start.replace("Z", "+00:00"))
                        new_end = datetime.fromisoformat(new_start_dt) + duration
                        updates["end"] = {"dateTime": new_end.isoformat(), "timeZone": tz}

            if "end_time" in fields and "start_time" not in fields:
                new_end_raw = extracted.get("new_end_time") or await self._ask("What is the new end time?")
                new_end_dt = self._parse_datetime_with_llm(new_end_raw, tz)
                if new_end_dt:
                    updates["end"] = {"dateTime": new_end_dt, "timeZone": tz}
                    existing_start = event.get("start", {}).get("dateTime", "")
                    if existing_start and "start" not in updates:
                        updates["start"] = {"dateTime": existing_start, "timeZone": tz}

            if "start_time" in fields and "end_time" in fields:
                new_start_raw = extracted.get("new_start_time") or await self._ask("What is the new start time?")
                new_start_dt  = self._parse_datetime_with_llm(new_start_raw, tz)
                new_end_raw   = extracted.get("new_end_time")   or await self._ask("What is the new end time?")
                new_end_dt    = self._parse_datetime_with_llm(new_end_raw, tz, reference_dt=new_start_dt)
                if new_start_dt:
                    updates["start"] = {"dateTime": new_start_dt, "timeZone": tz}
                if new_end_dt:
                    updates["end"] = {"dateTime": new_end_dt, "timeZone": tz}

            if "date" in fields and "start_time" not in fields and "end_time" not in fields:
                new_date_raw    = extracted.get("new_date") or await self._ask("What is the new date?")
                new_date_parsed = self._parse_datetime_with_llm(new_date_raw, tz)
                existing_start  = event.get("start", {}).get("dateTime", "")
                existing_end    = event.get("end",   {}).get("dateTime", "")
                if new_date_parsed and existing_start:
                    old_start = datetime.fromisoformat(existing_start.replace("Z", "+00:00"))
                    old_end   = datetime.fromisoformat(existing_end.replace("Z", "+00:00"))
                    duration  = old_end - old_start
                    new_start = datetime.fromisoformat(new_date_parsed).replace(
                        hour=old_start.hour, minute=old_start.minute, second=0
                    )
                    updates["start"] = {"dateTime": new_start.isoformat(), "timeZone": tz}
                    updates["end"]   = {"dateTime": (new_start + duration).isoformat(), "timeZone": tz}

            if "add_meet" in fields:
                updates["conferenceData"] = {
                    "createRequest": {
                        "requestId": f"gcal-update-{int(datetime.now().timestamp())}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                }
                await self.capability_worker.speak("Got it, adding a Google Meet link.")

            if "remove_meet" in fields:
                updates["conferenceData"] = {}
                await self.capability_worker.speak("Got it, removing the Google Meet link.")

            if "add_attendee" in fields:
                new_emails = [e for e in extracted.get("new_attendees", []) if e and "@" in e]
                # Confirm pre-extracted emails
                for email in new_emails:
                    await self.capability_worker.speak(f"Got it. Adding {email}.")
                # Then ask for more
                adding = await self._ask_yes_no("Would you like to add another attendee?") if new_emails else True
                while adding:
                    raw_email = await self._ask("Say the email address to add, or spell it out.")
                    email = self._extract_email_with_llm(raw_email)
                    if email:
                        new_emails.append(email)
                        await self.capability_worker.speak(f"Got it. Adding {email}.")
                    else:
                        await self.capability_worker.speak("I couldn't recognise that email, skipping.")
                    adding = await self._ask_yes_no("Add another attendee?")
                existing = [a["email"] for a in event.get("attendees", [])]
                updates["attendees"] = [{"email": e} for e in list(set(existing + new_emails))]

            if "remove_attendee" in fields:
                existing = [a["email"] for a in event.get("attendees", [])]
                if not existing:
                    await self.capability_worker.speak("This event has no attendees to remove.")
                else:
                    to_remove = []
                    removing = True
                    while removing:
                        raw_email = await self._ask("Say the email address to remove.")
                        email = self._extract_email_with_llm(raw_email)
                        if email:
                            to_remove.append(email)
                            await self.capability_worker.speak(f"Got it. Removing {email}.")
                        else:
                            await self.capability_worker.speak("I couldn't recognise that email, skipping.")
                        removing = await self._ask_yes_no("Remove another attendee?")
                    updates["attendees"] = [{"email": e} for e in existing if e not in to_remove]

            if "update_attendee" in fields:
                existing = [a["email"] for a in event.get("attendees", [])]
                if not existing:
                    await self.capability_worker.speak("This event has no attendees to update.")
                else:
                    old_raw   = await self._ask("Say the old email address to replace.")
                    old_email = self._extract_email_with_llm(old_raw)
                    if old_email and old_email in existing:
                        new_raw   = await self._ask("Say the new email address.")
                        new_email = self._extract_email_with_llm(new_raw)
                        if new_email:
                            updates["attendees"] = [
                                {"email": new_email if e == old_email else e} for e in existing
                            ]
                            await self.capability_worker.speak(f"Replaced {old_email} with {new_email}.")
                        else:
                            await self.capability_worker.speak("Couldn't recognise the new email, skipping.")
                    else:
                        await self.capability_worker.speak("Couldn't find that attendee on the event.")

            if "reminder" in fields:
                mins = extracted.get("reminder_minutes")
                if mins:
                    reminder_minutes = int(str(mins))
                else:
                    reminder_raw = await self._ask("How many minutes before should the reminder fire?")
                    reminder_str = self.capability_worker.text_to_text_response(
                        f"The user said: \"{reminder_raw}\"\n"
                        "Extract the reminder duration in minutes as an integer.\n"
                        "Examples: 'half an hour' → 30, 'an hour' → 60, '15 mins' → 15, 'skip' or unclear → 60.\n"
                        "Reply with ONLY the integer, nothing else."
                    ).strip()
                    nums = re.findall(r"\d+", reminder_str)
                    reminder_minutes = int(nums[0]) if nums else 60

                updates["reminders"] = {
                    "useDefault": False,
                    "overrides": [
                        {"method": "email",  "minutes": reminder_minutes},
                        {"method": "popup",  "minutes": reminder_minutes},
                    ],
                }
                await self.capability_worker.speak(f"Got it, reminder set to {reminder_minutes} minutes.")

            # ── Apply ──
            if not updates:
                await self.capability_worker.speak("I didn't catch what you'd like to change. Please try again.")
            else:
                try:
                    conference_version = 1 if "conferenceData" in updates else 0
                    updated_body = service.events().get(calendarId="primary", eventId=event["id"]).execute()
                    updated_body.update(updates)
                    event = service.events().update(
                        calendarId="primary",
                        eventId=event["id"],
                        body=updated_body,
                        conferenceDataVersion=conference_version,
                        sendUpdates="all",
                    ).execute()
                    await self.capability_worker.speak(f"Done! '{event.get('summary', 'the event')}' has been updated.")
                    self.worker.editor_logging_handler.error(f"Event updated: {event.get('id')}")
                except HttpError as e:
                    await self.capability_worker.speak("Something went wrong on my end. Try again in a moment.")
                    self.worker.editor_logging_handler.error(f"HttpError: {e.reason}")
                    
            # ── Ask for more changes ──
            next_raw = await self._ask("Anything else to change? Or say done to finish.")
            done_check = self.capability_worker.text_to_text_response(
                f"The user said: \"{next_raw}\"\n"
                "Are they done or do they want more changes?\n"
                "DONE examples: 'done', 'that's it', 'all good', 'we're good', 'that's all', 'nothing else', 'no', 'nope', 'finished'\n"
                "CONTINUE examples: 'also change', 'and update', 'one more thing', 'actually', 'wait'\n"
                "Reply with exactly one word: DONE or CONTINUE"
            ).strip().upper()
            if done_check.strip() == "DONE":
                break

            extracted = _classify_changes(next_raw)
            fields = extracted.get("fields", [])

    # -------------------- Delete Event --------------------
    async def _flow_delete_event(self, service, tz: str, raw_utterance: str = "") -> None:
        # ── Step 1: Fetch all events in the next 30 days ──
        now_utc = datetime.now(timezone.utc)
        one_month = (now_utc + timedelta(days=30)).isoformat()
        all_events = list_events(service, now_utc.isoformat(), one_month, max_results=50)

        if not all_events:
            await self.capability_worker.speak("You have no upcoming events to delete.")
            return

        event_list_str = "\n".join(
            [f"- id: {ev['id']} | title: {ev.get('summary', 'Untitled')}" for ev in all_events]
        )
        self.worker.editor_logging_handler.error(f"Fetched {len(all_events)} events for delete match")

        # ── Step 2: Check if trigger phrase already contains an event name ──
        if raw_utterance:
            intent_prompt = (
                f"The user said: \"{raw_utterance}\"\n"
                f"Here are all upcoming calendar events in the next 30 days:\n"
                f"{event_list_str}\n\n"
                "Did the user clearly mention a specific event name?\n"
                "Rules for extracted_name:\n"
                "  - Only extract if the user actually said an event name or title\n"
                "  - Do NOT extract vague descriptions like 'the night event', 'my meeting', 'some event'\n"
                "  - If no clear event name was spoken, set extracted_name to null\n"
                "Rules for matched_id:\n"
                "  - Only match if the extracted name closely matches a calendar event (exact, near-exact, or clear voice transcription error)\n"
                "  - Do NOT match based on themes, loose associations, or vague similarity\n"
                "  - For example: 'diner' → 'dinner' is OK. 'night event' → 'dinner' is NOT OK\n"
                "  - If no confident match exists, set matched_id to null\n"
                "Reply with ONLY a JSON object, no markdown:\n"
                "{\n"
                "  \"extracted_name\": \"the event name the user mentioned, or null if none\",\n"
                "  \"matched_id\": \"matching event id, or null if no confident match\"\n"
                "}"
            )
            raw_result = self.capability_worker.text_to_text_response(intent_prompt).strip()
            raw_result = re.sub(r"```(?:json)?", "", raw_result).strip().rstrip("`").strip()
            self.worker.editor_logging_handler.error(f"Trigger intent match raw: '{raw_result}'")

            try:
                match_data = json.loads(raw_result)
            except Exception:
                match_data = {"extracted_name": None, "matched_id": None}

            extracted_name = match_data.get("extracted_name")
            matched_id     = match_data.get("matched_id")

            # Clean nulls
            if isinstance(extracted_name, str) and extracted_name.lower() in ("null", "none", ""):
                extracted_name = None
            if isinstance(matched_id, str) and matched_id.lower() in ("null", "none", ""):
                matched_id = None

            self.worker.editor_logging_handler.error(f"Extracted name: '{extracted_name}' | Matched id: '{matched_id}'")

            if extracted_name and matched_id:
                # ── Scenario 1: name extracted AND matched ──
                event = next((ev for ev in all_events if ev["id"] == matched_id), None)
                if event:
                    confirmed = await self._ask_yes_no(
                        f"I found '{event.get('summary', 'Untitled')}'. Should I delete it?"
                    )
                    if confirmed:
                        try:
                            delete_event(service, event["id"])
                            await self.capability_worker.speak(
                                f"Done. '{event.get('summary', 'Untitled')}' has been deleted."
                            )
                            self.worker.editor_logging_handler.error(f"Deleted event id: {event['id']}")
                        except HttpError as e:
                            await self.capability_worker.speak(f"Sorry, I couldn't delete it: {e.reason}")
                    else:
                        await self.capability_worker.speak("Okay, I'll leave it as is.")
                    return

            elif extracted_name and not matched_id:
                # ── Scenario 2: name extracted but NOT matched ──
                options_text = ", ".join([ev.get("summary", "Untitled") for ev in all_events[:5]])
                await self.capability_worker.speak(
                    f"I couldn't find an event called '{extracted_name}' in your calendar. "
                    f"Your upcoming events are: {options_text}. "
                )
                pick_raw = await self._ask("Which event should I delete?")
                cancel_check = self.capability_worker.text_to_text_response(
                    f"The user said: \"{pick_raw}\".\n"
                    "Are they cancelling or picking an event to delete?\n"
                    "CANCEL examples: 'never mind', 'forget it', 'leave it', 'don't bother', 'actually no', 'skip it'\n"
                    "PICK examples: naming an event, saying a number, 'the first one', 'that one'\n"
                    "Reply with exactly one word: CANCEL or PICK"
                ).strip().upper()
                if "CANCEL" in cancel_check:
                    await self.capability_worker.speak("Okay, no event deleted.")
                    return
                # Match their pick
                pick_prompt = (
                    f"The user said: \"{pick_raw}\"\n"
                    f"Here are all upcoming calendar events:\n{event_list_str}\n\n"
                    "Which event best matches? Reply with ONLY the event id, or NONE."
                )
                pick_id = self.capability_worker.text_to_text_response(pick_prompt).strip().rstrip(".,!?;:")
                event = next((ev for ev in all_events if ev["id"] == pick_id), None)
                if not event:
                    await self.capability_worker.speak("I still couldn't find that event. Please try again later.")
                    return
                confirmed = await self._ask_yes_no(
                    f"I found '{event.get('summary', 'Untitled')}'. Should I delete it?"
                )
                if confirmed:
                    try:
                        delete_event(service, event["id"])
                        await self.capability_worker.speak(f"Done. '{event.get('summary', 'Untitled')}' has been deleted.")
                        self.worker.editor_logging_handler.error(f"Deleted event id: {event['id']}")
                    except HttpError as e:
                        await self.capability_worker.speak(f"Sorry, I couldn't delete it: {e.reason}")
                else:
                    await self.capability_worker.speak("Okay, I'll leave it as is.")
                return

            # ── Scenario 3: no name in trigger — fall through to ask ──
            self.worker.editor_logging_handler.error("No event name in trigger, asking user")

        # ── Step 3: No event name in trigger — ask the user ──
        user_query = await self._ask(
            "Which event would you like to delete? Say the title or describe it."
        )
        self.worker.editor_logging_handler.error(f"Delete query from user: '{user_query}'")

        # ── Step 4: Match user query against event list ──
        match_prompt = (
            f"The user said: \"{user_query}\"\n"
            f"Here are all upcoming calendar events:\n"
            f"{event_list_str}\n\n"
            "Does the user clearly mention a specific event name that closely matches one of the events above?\n"
            "Rules:\n"
            "  - Only match if the user said an actual event name (exact, close spelling, or obvious voice transcription error)\n"
            "  - Do NOT match based on vague descriptions, themes, or loosely related words\n"
            "  - For example: 'diner' → 'dinner' is OK (typo). 'night event' → 'dinner' is NOT OK (too vague)\n"
            "  - If the user is describing rather than naming, return NONE\n"
            "Reply with ONLY the event id of the match, or NONE."
        )
        matched_id = self.capability_worker.text_to_text_response(match_prompt).strip().rstrip(".,!?;:")
        event = next((ev for ev in all_events if ev["id"] == matched_id), None)

        # ── Step 5: Fallback — list options manually ──
        if not event:
            retry_query = await self._ask(
                "I couldn't find that event. Please say the exact event title you'd like to delete."
            )
            self.worker.editor_logging_handler.error(f"Delete retry query: '{retry_query}'")

            retry_prompt = (
                f"The user said: \"{retry_query}\"\n"
                f"Here are all upcoming calendar events:\n"
                f"{event_list_str}\n\n"
                "Does the user clearly mention a specific event name that closely matches one of the events above?\n"
                "Rules:\n"
                "  - Only match if the user said an actual event name (exact, close spelling, or obvious voice transcription error)\n"
                "  - Do NOT match based on vague descriptions, themes, or loosely related words\n"
                "  - If no confident match, return NONE\n"
                "Reply with ONLY the event id of the match, or NONE."
            )
            retry_id = self.capability_worker.text_to_text_response(retry_prompt).strip().rstrip(".,!?;:")
            event = next((ev for ev in all_events if ev["id"] == retry_id), None)

            if not event:
                await self.capability_worker.speak(
                    "I still couldn't find a matching event. Please try again later."
                )
                return

        # ── Step 6: Confirm and delete ──
        confirmed = await self._ask_yes_no(
            f"I found '{event.get('summary', 'Untitled')}'. Should I delete it?"
        )
        if confirmed:
            try:
                delete_event(service, event["id"])
                await self.capability_worker.speak(
                    f"Done. '{event.get('summary', 'Untitled')}' has been deleted."
                )
                self.worker.editor_logging_handler.error(f"Deleted event id: {event['id']}")
            except HttpError as e:
                await self.capability_worker.speak(f"Sorry, I couldn't delete it: {e.reason}")
        else:
            await self.capability_worker.speak("Okay, I'll leave it as is.")

    # -------------------- Entry point --------------------
    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        first_msg = await self.capability_worker.wait_for_complete_transcription()

        # Build Calendar service
        token = self.capability_worker.get_token("google")
        self.worker.editor_logging_handler.error(f"Token: {token}")

        if not token:
            await self.capability_worker.speak(
                "Your Google account isn't linked yet. Head to Settings, then Linked Accounts to connect it."
            )
            self.capability_worker.resume_normal_flow()
            return

        try:
            service = _build_calendar_service_using_access_token(token)
        except Exception:
            await self.capability_worker.speak(
                "Couldn't connect to Google Calendar. Try again in a moment."
            )
            self.capability_worker.resume_normal_flow()
            return

        # Auto-detect timezone from IP
        user_timezone = self.capability_worker.get_timezone()

        # Determine intent
        intent_prompt = (
            f"Classify this intent: '{first_msg}'.\n"
            "Examples:\n"
            "  'set up a meeting' / 'add something to my calendar' / 'schedule a call' / 'make a new event' / 'put something on my calendar' / 'I need to schedule something' → CREATE\n"
            "  'what's on my calendar' / 'what do I have tomorrow' / 'show my events' / 'show me what's coming up' / 'what do I have on' / 'check my schedule' → LIST\n"
            "  'move my dentist appointment' / 'bump that call' / 'push the meeting to Friday' / 'reschedule' / 'change that meeting' → UPDATE\n"
            "  'cancel my standup' / 'get rid of that event' / 'remove the meeting' / 'delete that' / 'get rid of it' / 'take that off my calendar' / 'remove it' → DELETE\n"
            "Reply with exactly one word — CREATE, LIST, UPDATE, DELETE or UNKNOWN."
        )
        intent = self.capability_worker.text_to_text_response(intent_prompt).strip().upper()

        routing_msg = first_msg
        if intent == "UNKNOWN" or intent.lower() == "unknown":
            await self.capability_worker.speak("Google Calendar ready. What would you like to do?")
            intent_raw = (await self.capability_worker.user_response()).strip()
            routing_msg = intent_raw  # ← second message carries the real intent

            intent_prompt = (
                f"Classify this intent: '{intent_raw}'.\n"
                "Examples:\n"
                "  'make a new event' / 'schedule something' / 'create event step by step' → CREATE\n"
                "  'show my calendar' / 'what do I have on' → LIST\n"
                "  'change that meeting' / 'move it' → UPDATE\n"
                "  'delete it' / 'remove that event' → DELETE\n"
                "Reply with exactly one word — CREATE, LIST, UPDATE, or DELETE."
            )
            intent = self.capability_worker.text_to_text_response(intent_prompt).strip().upper()

        if intent.strip() == "CREATE":
            await self._flow_create_event(service, user_timezone, routing_msg)
        elif intent.strip() == "LIST":
            await self._flow_list_events(service, user_timezone, routing_msg)
        elif intent.strip() == "UPDATE":
            await self._flow_update_event(service, user_timezone, routing_msg)
        elif intent.strip() == "DELETE":
            await self._flow_delete_event(service, user_timezone, routing_msg)
        else:
            await self.capability_worker.speak(
                "I'm not sure what you'd like to do. "
                "You can ask me to create, list, update, or delete calendar events."
            )

        self.capability_worker.resume_normal_flow()
