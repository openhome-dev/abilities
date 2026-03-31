import json
import requests
from datetime import datetime, timedelta
from time import time as epoch_now
from zoneinfo import ZoneInfo
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# CONFIGURATION  (shared with main.py)
# =============================================================================

CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
DEFAULT_TIMEZONE = "America/Los_Angeles"
LOCAL_TZ = None  # set in call() via SDK get_timezone()

# How often the daemon polls (seconds)
POLL_INTERVAL = 30.0

# Default reminder window (minutes before a meeting)
DEFAULT_REMINDER_MINUTES = 10

# Reminded entries older than this are pruned from gcal_reminded.json
REMINDED_TTL_SECONDS = 86400  # 24 hours

# File names (persistent storage, temp=False)
REMINDED_FILE = "gcal_reminded.json"
SCHEDULE_MD_FILE = "upcoming_schedule.md"
PREFERENCES_FILE = "user_preferences.md"
EVENTS_CACHE_FILE = "gcal_events_cache.json"


# =============================================================================
# HELPERS
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


def format_duration_label(minutes: int) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        hrs = minutes // 60
        return f"{hrs} hr"
    elif minutes > 60:
        hrs = minutes // 60
        mins = minutes % 60
        return f"{hrs} hr {mins} min"
    else:
        return f"{minutes} min"


def friendly_time(dt: datetime) -> str:
    """Format a datetime as a natural spoken time, e.g. '3 PM' or '9:30 AM'."""
    if dt.minute == 0:
        return dt.strftime("%-I %p")
    return dt.strftime("%-I:%M %p")


def friendly_date(dt: datetime) -> str:
    """Return 'Today', 'Tomorrow', or the weekday name."""
    now = get_local_now()
    today = now.date()
    target = dt.date()
    delta = (target - today).days
    if delta == 0:
        return "Today"
    elif delta == 1:
        return "Tomorrow"
    else:
        return dt.strftime("%A")  # e.g. "Wednesday"


# =============================================================================
# BACKGROUND DAEMON
# =============================================================================

class GcalReminderDaemon(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False
    access_token: str = None

    # {{register_capability}}

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        global LOCAL_TZ
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)
        tz = self.capability_worker.get_timezone() or DEFAULT_TIMEZONE
        LOCAL_TZ = ZoneInfo(tz)
        self.worker.session_tasks.create(self.reminder_loop())

    # =========================================================================
    # AUTH
    # =========================================================================

    def refresh_access_token(self) -> bool:
        try:
            token = self.capability_worker.get_token("google")
            if token:
                self.access_token = token
                return True
            else:
                self.log("No Google token available. Link your Google account in OpenHome settings.")
                return False
        except Exception as e:
            self.log(f"Auth exception: {e}")
            return False

    # =========================================================================
    # GOOGLE CALENDAR
    # =========================================================================

    def fetch_upcoming_events(self, days: int = 7) -> list:
        """Fetch events for the next N days from Google Calendar."""
        now = get_local_now()
        offset_str = get_utc_offset_str()
        time_min = now.strftime(f"%Y-%m-%dT%H:%M:%S{offset_str}")
        time_max = (now + timedelta(days=days)).strftime(f"%Y-%m-%dT23:59:59{offset_str}")

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
            if resp.ok:
                return resp.json().get("items", [])
            else:
                self.log(f"Fetch events failed ({resp.status_code}): {resp.text[:200]}")
                return []
        except Exception as e:
            self.log(f"Fetch events exception: {e}")
            return []

    def fetch_updated_events(self, updated_min_iso: str) -> list:
        """
        Fetch events modified since updated_min_iso (RFC 3339 format).
        Returns cancelled events too (status='cancelled').
        """
        try:
            resp = requests.get(
                CALENDAR_API_URL,
                headers={"Authorization": f"Bearer {self.access_token}"},
                params={
                    "updatedMin": updated_min_iso,
                    "singleEvents": "true",
                    "showDeleted": "true",
                    "timeZone": DEFAULT_TIMEZONE,
                    "maxResults": 50,
                },
            )
            if resp.ok:
                return resp.json().get("items", [])
            else:
                self.log(f"Fetch updated events failed ({resp.status_code}): {resp.text[:200]}")
                return []
        except Exception as e:
            self.log(f"Fetch updated events exception: {e}")
            return []

    # =========================================================================
    # EVENT STATE TRACKING (change detection)
    # =========================================================================

    EVENT_STATE_FILE = "gcal_event_state.json"

    async def load_event_state(self) -> dict:
        """
        Load the known state snapshot of upcoming events.
        Format: {event_id: {summary, start_iso, declined: [email, ...], status}}
        """
        try:
            exists = await self.capability_worker.check_if_file_exists(self.EVENT_STATE_FILE, False)
            if not exists:
                return {}
            raw = await self.capability_worker.read_file(self.EVENT_STATE_FILE, False)
            return json.loads(raw) if raw else {}
        except Exception as e:
            self.log(f"Load event state error: {e}")
            return {}

    async def save_event_state(self, state: dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(self.EVENT_STATE_FILE, False)
            if exists:
                await self.capability_worker.delete_file(self.EVENT_STATE_FILE, False)
            await self.capability_worker.write_file(
                self.EVENT_STATE_FILE, json.dumps(state, indent=2), False, mode="w"
            )
        except Exception as e:
            self.log(f"Save event state error: {e}")

    def snapshot_event(self, ev: dict) -> dict:
        """Build a minimal snapshot of an event for change comparison."""
        start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
        attendees = ev.get("attendees", [])
        declined = [
            a.get("email", "") for a in attendees
            if a.get("responseStatus") == "declined"
        ]
        accepted = [
            a.get("email", "") for a in attendees
            if a.get("responseStatus") == "accepted"
        ]
        all_attendees = [a.get("email", "") for a in attendees]
        organizer_self = ev.get("organizer", {}).get("self", False)
        self_att = next((a for a in attendees if a.get("self")), None)
        self_rsvp = self_att.get("responseStatus", "needsAction") if self_att else None
        return {
            "summary": ev.get("summary", "Untitled"),
            "start_iso": start,
            "declined": declined,
            "accepted": accepted,
            "all_attendees": all_attendees,
            "status": ev.get("status", "confirmed"),
            "organizer_self": organizer_self,
            "self_rsvp": self_rsvp,
        }

    def _display_name_for_email(self, email: str, attendees: list) -> str:
        """Return displayName from the attendee list, or the email prefix."""
        for a in attendees:
            if a.get("email", "").lower() == email.lower():
                return a.get("displayName") or email.split("@")[0]
        return email.split("@")[0]

    async def detect_and_notify_changes(self, events: list, known_state: dict) -> dict:
        """
        Compare current event list against known_state.
        Fires spoken notifications for:
          - Event cancelled externally
          - Event renamed
          - Event rescheduled (start time changed)
          - New attendee declines
          - New attendee acceptances
          - New attendees invited
        Returns an updated state dict.
        """
        updated_state = dict(known_state)
        # Track base IDs already notified this cycle to deduplicate recurring series changes
        notified_cancels: set = set()
        notified_renames: set = set()
        notified_reschedules: set = set()

        for ev in events:
            event_id = ev.get("id", "")
            if not event_id:
                continue

            current = self.snapshot_event(ev)
            previous = known_state.get(event_id)
            title = current["summary"]

            # ── First-seen event ──
            if previous is None:
                # Announce only if someone else organized it (not self-created)
                if current["status"] != "cancelled" and not current.get("organizer_self", True):
                    try:
                        date_label = ""
                        if current["start_iso"]:
                            start_dt = datetime.fromisoformat(
                                current["start_iso"].replace("Z", "+00:00")
                            ).astimezone(LOCAL_TZ)
                            day = friendly_date(start_dt)
                            time_str = friendly_time(start_dt)
                            if day in ("Today", "Tomorrow"):
                                date_label = f" {day.lower()} at {time_str}"
                            else:
                                date_label = f" on {day} at {time_str}"
                        self.log(f"New invite detected: '{title}'.")
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(
                            f"You got an invite to {title}{date_label}. "
                            f"You can accept or decline it whenever you're ready."
                        )
                    except Exception as e:
                        self.log(f"New invite notify error: {e}")
                updated_state[event_id] = current
                continue

            base_id = event_id.split("_")[0]

            # ── Cancelled by organizer ──
            if current["status"] == "cancelled" and previous["status"] != "cancelled":
                if base_id in notified_cancels:
                    updated_state.pop(event_id, None)
                    continue
                notified_cancels.add(base_id)
                self.log(f"Change detected: '{title}' was cancelled.")
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(
                    f"FYI — {title} was just cancelled."
                )
                # Remove from state so we don't re-notify
                updated_state.pop(event_id, None)
                continue

            # ── Renamed ──
            prev_title = previous.get("summary", "")
            if prev_title and current["summary"] != prev_title and base_id not in notified_renames:
                notified_renames.add(base_id)
                self.log(f"Change detected: '{prev_title}' renamed to '{current['summary']}'.")
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(
                    f"Heads up — {prev_title} was renamed to {current['summary']}."
                )

            # ── Rescheduled by organizer (start time changed) ──
            if current["start_iso"] and previous["start_iso"] and current["start_iso"] != previous["start_iso"] and base_id not in notified_reschedules:
                notified_reschedules.add(base_id)
                try:
                    new_dt = datetime.fromisoformat(current["start_iso"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
                    new_time_label = friendly_time(new_dt)
                    new_date_label = friendly_date(new_dt)
                    self.log(f"Change detected: '{title}' rescheduled to {new_time_label} {new_date_label}.")
                    await self.capability_worker.send_interrupt_signal()
                    await self.capability_worker.speak(
                        f"Heads up — {title} was moved to {new_time_label} {new_date_label}."
                    )
                except Exception as e:
                    self.log(f"Reschedule notify error: {e}")

            # ── New declines ──
            prev_declined = set(previous.get("declined", []))
            curr_declined = set(current.get("declined", []))
            new_declines = curr_declined - prev_declined
            for email in new_declines:
                name = self._display_name_for_email(email, ev.get("attendees", []))
                self.log(f"Change detected: {name} declined '{title}'.")
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(
                    f"Just so you know — {name} declined {title}."
                )

            # ── New acceptances ──
            prev_accepted = set(previous.get("accepted", []))
            curr_accepted = set(current.get("accepted", []))
            new_accepted = curr_accepted - prev_accepted
            for email in new_accepted:
                name = self._display_name_for_email(email, ev.get("attendees", []))
                self.log(f"Change detected: {name} accepted '{title}'.")
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(
                    f"Good news — {name} accepted {title}."
                )

            # ── New attendees invited ──
            prev_all = set(previous.get("all_attendees", []))
            curr_all = set(current.get("all_attendees", []))
            newly_invited = curr_all - prev_all
            for email in newly_invited:
                name = self._display_name_for_email(email, ev.get("attendees", []))
                self.log(f"Change detected: {name} was added to '{title}'.")
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(
                    f"Heads up — {name} was added to {title}."
                )

            updated_state[event_id] = current

        return updated_state

    # =========================================================================
    # REMINDED TRACKING
    # =========================================================================

    async def load_reminded(self) -> list:
        """Load the list of already-reminded event entries."""
        try:
            exists = await self.capability_worker.check_if_file_exists(REMINDED_FILE, False)
            if not exists:
                return []
            raw = await self.capability_worker.read_file(REMINDED_FILE, False)
            if not raw:
                return []
            return json.loads(raw)
        except Exception as e:
            self.log(f"Load reminded error: {e}")
            return []

    async def save_reminded(self, reminded: list):
        """Overwrite gcal_reminded.json with the current list."""
        try:
            # Delete first so write_file doesn't append
            exists = await self.capability_worker.check_if_file_exists(REMINDED_FILE, False)
            if exists:
                await self.capability_worker.delete_file(REMINDED_FILE, False)
            await self.capability_worker.write_file(
                REMINDED_FILE, json.dumps(reminded, indent=2), False, mode="w"
            )
        except Exception as e:
            self.log(f"Save reminded error: {e}")

    def prune_reminded(self, reminded: list) -> list:
        """Remove entries older than REMINDED_TTL_SECONDS."""
        cutoff = epoch_now() - REMINDED_TTL_SECONDS
        return [r for r in reminded if r.get("reminded_at_epoch", 0) > cutoff]

    # =========================================================================
    # USER PREFERENCES
    # =========================================================================

    async def load_preferences(self) -> dict:
        """
        Parse user_preferences.md into a usable dict:
        {
          "default_reminder_minutes": int,
          "overrides": {"title fragment (lowercase)": int_or_None}
          # None means skip (no reminder)
        }
        """
        defaults = {
            "default_reminder_minutes": DEFAULT_REMINDER_MINUTES,
            "overrides": {},
        }
        try:
            exists = await self.capability_worker.check_if_file_exists(PREFERENCES_FILE, False)
            if not exists:
                return defaults

            raw = await self.capability_worker.read_file(PREFERENCES_FILE, False)
            if not raw:
                return defaults

            prompt = (
                f"Parse this calendar preferences file and return a JSON object:\n\n"
                f"{raw}\n\n"
                "Return ONLY a JSON object with:\n"
                '- "default_reminder_minutes": integer (default reminder minutes before meetings)\n'
                '- "overrides": object where each key is a lowercase meeting title fragment and '
                'value is an integer (minutes before) or null (means skip/no reminder)\n'
                "Example: {\"default_reminder_minutes\": 5, "
                "\"overrides\": {\"weekly standup\": null, \"investor call\": 15}}\n"
                "Return ONLY valid JSON, no other text."
            )
            raw_result = self.capability_worker.text_to_text_response(prompt)
            clean = raw_result.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            defaults["default_reminder_minutes"] = int(parsed.get("default_reminder_minutes", DEFAULT_REMINDER_MINUTES))
            defaults["overrides"] = {k.lower(): v for k, v in parsed.get("overrides", {}).items()}
            self.log(f"Loaded preferences: {defaults}")
            return defaults
        except Exception as e:
            self.log(f"Load preferences error: {e} — using defaults")
            return defaults

    async def load_event_reminders(self) -> dict:
        """Load {event_id: reminder_minutes} from gcal_event_reminders.json."""
        try:
            exists = await self.capability_worker.check_if_file_exists("gcal_event_reminders.json", False)
            if not exists:
                return {}
            raw = await self.capability_worker.read_file("gcal_event_reminders.json", False)
            return json.loads(raw) if raw else {}
        except Exception as e:
            self.log(f"Load event reminders error: {e}")
            return {}

    def get_reminder_minutes(self, event_id: str, event_title: str,
                             prefs: dict, event_reminders: dict) -> int | None:
        """
        Return how many minutes before the meeting to remind, or None to skip.
        Priority: per-event ID override > title-fragment preference > default.
        """
        # 1. Per-event ID override (set when user says "remind me X minutes before" while scheduling)
        if event_id in event_reminders:
            val = event_reminders[event_id]
            return int(val) if val is not None else None

        # 2. Title-fragment preference from user_preferences.md
        title_lower = event_title.lower()
        for fragment, value in prefs.get("overrides", {}).items():
            if fragment in title_lower:
                if value is None:
                    return None  # skip
                return int(value)

        # 3. Default
        return prefs.get("default_reminder_minutes", DEFAULT_REMINDER_MINUTES)

    # =========================================================================
    # SCHEDULE MD (personality memory)
    # =========================================================================

    async def write_schedule_md(self, events: list):
        """
        Write upcoming_schedule.md for personality context injection.
        Shows events for the next 7 days in a concise, under-200-word format.
        """
        get_local_now()
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
                date_label = friendly_date(start_dt)
                time_label = friendly_time(start_dt)
                dur_label = ""
                if end_dt:
                    dur_mins = int((end_dt - start_dt).total_seconds() / 60)
                    dur_label = f" ({format_duration_label(dur_mins)})"

                attendees = ev.get("attendees", [])
                attendee_str = ""
                if attendees and 1 <= len(attendees) <= 3:
                    names = [a.get("displayName") or a.get("email", "").split("@")[0] for a in attendees]
                    attendee_str = f" with {', '.join(names)}"

                lines.append(f"- {date_label} {time_label} — {title}{dur_label}{attendee_str}")
            except Exception:
                continue

        # Cap at 20 events to stay within context budget
        if len(lines) > 21:
            lines = lines[:21]
            lines.append("- (...more events not shown)")

        content = "\n".join(lines) + "\n"

        try:
            exists = await self.capability_worker.check_if_file_exists(SCHEDULE_MD_FILE, False)
            if exists:
                await self.capability_worker.delete_file(SCHEDULE_MD_FILE, False)
            await self.capability_worker.write_file(SCHEDULE_MD_FILE, content, False, mode="w")
            self.log(f"Wrote upcoming_schedule.md ({len(lines)-1} events)")
        except Exception as e:
            self.log(f"Write schedule.md error: {e}")

    async def write_events_cache(self, events: list):
        """
        Write gcal_events_cache.json with full event objects + a timestamp.
        main.py reads this instead of making its own API calls.
        """
        payload = {
            "updated_at": epoch_now(),
            "events": events,
        }
        try:
            exists = await self.capability_worker.check_if_file_exists(EVENTS_CACHE_FILE, False)
            if exists:
                await self.capability_worker.delete_file(EVENTS_CACHE_FILE, False)
            await self.capability_worker.write_file(
                EVENTS_CACHE_FILE, json.dumps(payload), False, mode="w"
            )
            self.log(f"Wrote events cache ({len(events)} events).")
        except Exception as e:
            self.log(f"Write events cache error: {e}")

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def log(self, msg: str):
        self.worker.editor_logging_handler.info(f"[GCalDaemon] {msg}")

    async def reminder_loop(self):
        self.log("Reminder daemon started.")

        # Clear stale reminded entries from previous sessions on startup
        reminded = await self.load_reminded()
        reminded = self.prune_reminded(reminded)
        await self.save_reminded(reminded)
        self.log(f"Session start: {len(reminded)} active reminded entries carried over.")

        # Track last check time for change detection (RFC 3339)
        last_change_check: str = get_local_now().strftime("%Y-%m-%dT%H:%M:%S") + get_utc_offset_str()

        while True:
            try:
                # 1. Refresh token
                if not self.refresh_access_token():
                    self.log("Could not refresh access token — skipping cycle.")
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                # 2. Fetch upcoming events (for reminders + schedule.md)
                events = self.fetch_upcoming_events(days=7)
                self.log(f"Fetched {len(events)} events for next 7 days.")

                # 3. Update upcoming_schedule.md and events cache
                await self.write_schedule_md(events)
                await self.write_events_cache(events)

                # 4. Check for external changes (declines, reschedules, cancellations)
                known_state = await self.load_event_state()
                cycle_start_time = get_local_now().strftime("%Y-%m-%dT%H:%M:%S") + get_utc_offset_str()
                updated_events = self.fetch_updated_events(last_change_check)
                if updated_events:
                    self.log(f"Found {len(updated_events)} event(s) updated since last check.")
                    # Merge updated events into our known list for snapshot comparison
                    known_state = await self.detect_and_notify_changes(updated_events, known_state)
                    await self.save_event_state(known_state)
                else:
                    # On first run or quiet cycles, build initial state from upcoming events
                    if not known_state:
                        for ev in events:
                            eid = ev.get("id", "")
                            if eid:
                                known_state[eid] = self.snapshot_event(ev)
                        await self.save_event_state(known_state)
                last_change_check = cycle_start_time

                # 6. Load preferences, per-event reminders, and reminded list
                prefs = await self.load_preferences()
                event_reminders = await self.load_event_reminders()
                reminded = await self.load_reminded()
                reminded = self.prune_reminded(reminded)

                reminded_ids = {r["event_id"] for r in reminded}
                now = get_local_now()
                newly_reminded = []

                # 7. Check for events coming up within the reminder window
                for ev in events:
                    event_id = ev.get("id", "")
                    title = ev.get("summary", "Untitled")
                    start_str = ev.get("start", {}).get("dateTime", "")
                    if not start_str or not event_id:
                        continue

                    try:
                        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
                    except Exception:
                        continue

                    # Skip events already in the past
                    if start_dt <= now:
                        continue

                    # Skip if already reminded this session
                    if event_id in reminded_ids:
                        continue

                    # Determine reminder window for this event
                    reminder_mins = self.get_reminder_minutes(event_id, title, prefs, event_reminders)
                    if reminder_mins is None:
                        self.log(f"Skipping '{title}' — preference says no reminder.")
                        continue

                    minutes_until = (start_dt - now).total_seconds() / 60

                    if minutes_until <= reminder_mins:
                        mins_display = max(1, int(minutes_until))
                        self.log(f"Firing reminder for '{title}' in ~{mins_display} min.")

                        await self.capability_worker.send_interrupt_signal()

                        if mins_display <= 1:
                            msg = f"Hey, {title} is starting right now."
                        elif mins_display <= 2:
                            msg = f"Heads up — {title} is in just a couple minutes."
                        else:
                            msg = f"Hey, just a heads up — {title} kicks off in about {mins_display} minutes."

                        await self.capability_worker.speak(msg)

                        newly_reminded.append({
                            "event_id": event_id,
                            "reminded_at_epoch": int(epoch_now()),
                        })
                        reminded_ids.add(event_id)

                # 8. Persist updated reminded list
                if newly_reminded:
                    reminded.extend(newly_reminded)
                    await self.save_reminded(reminded)

            except Exception as e:
                self.log(f"Reminder loop error: {e}")

            await self.worker.session_tasks.sleep(POLL_INTERVAL)
