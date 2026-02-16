import asyncio
import datetime
import json
import random
import re

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CONFIG
# =============================================================================

GRAPH_ACCESS_TOKEN = "YOUR_TOKEN_HERE"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
YOUR_EMAIL = "YOUR_EMAIL_HERE"

EXIT_WORDS = [
    "done",
    "that's it",
    "thats it",
    "exit",
    "stop",
    "quit",
    "go to sleep",
    "goodbye",
    "bye",
    "nothing else",
    "all good",
    "nope",
    "no thanks",
    "i'm good",
    "im good",
]

# =============================================================================
# WEATHER & GEO CONSTANTS
# =============================================================================

CLOUD_INDICATORS = [
    "amazon",
    "aws",
    "google",
    "microsoft",
    "azure",
    "digitalocean",
    "linode",
    "vultr",
    "hetzner",
    "ovh",
    "oracle",
    "cloudflare",
    "rackspace",
    "ibm cloud",
]

WEATHER_DESCRIPTIONS = {
    0: "clear skies",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy with frost",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "heavy rain showers",
    85: "light snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with light hail",
    99: "thunderstorm with heavy hail",
}

IMPERIAL_COUNTRIES = ["US"]

# =============================================================================
# DYNAMIC GREETINGS
# =============================================================================

TIME_GREETINGS = {
    "morning": ["Good morning", "Morning", "Hey, good morning"],
    "afternoon": ["Good afternoon", "Afternoon", "Hey"],
    "evening": ["Good evening", "Evening", "Hey there"],
    "night": ["Hey", "Hi there", "Hey there"],
}

FILLER_LINES = {
    "morning": [
        "One sec, pulling up your day.",
        "Let me check what's on tap today.",
        "Grabbing your schedule.",
    ],
    "afternoon": [
        "One sec, checking what's left today.",
        "Let me see what's coming up.",
        "Pulling up the rest of your day.",
    ],
    "evening": [
        "One sec, checking your evening.",
        "Let me see what's left tonight.",
        "Pulling up the rest of your day.",
    ],
    "night": [
        "One sec, checking your schedule.",
        "Let me see what's on the books.",
        "Hang on, pulling things up.",
    ],
}


def get_time_bucket(hour):
    """Return time bucket based on hour."""
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

HUB_SYSTEM_PROMPT = """You are Smart Hub, a concise voice assistant that gives quick, natural spoken briefings.

USER CONTEXT:
- Name: {user_name}
- Location: {city}, {region}
- Local time: {current_time} ({time_bucket})
- Day: {day_of_week}, {current_date}
{weather_line}

Rules:
- Keep responses to 2-4 sentences max. This is voice, not text.
- Be conversational and natural, like a sharp assistant who knows their day.
- Never use bullet points, numbered lists, or markdown formatting.
- When summarizing calendar events, mention time, title, and relevant context.
- For events marked [IN PROGRESS], say they're "happening now" or "going on right now" and mention how much time is left.
- For events marked [STARTING IN Xm], give a heads up that they're coming up soon.
- If there's nothing notable, say so briefly.
- When the user seems done or says goodbye, respond with a short sign-off.
- Use the user's name naturally when it fits.
- ONLY mention weather if there's an in-person meeting with a physical address/location.
- When reading email addresses, say "at" instead of "@" (e.g., "jane at example dot com").
- You can help reschedule, push back, shorten, cancel, or invite people to calendar events when asked.
"""

# =============================================================================
# TRIGGER CONTEXT CLASSIFIER (determines Quick vs Full mode)
# =============================================================================

TRIGGER_INTENT_PROMPT = """What does the user want from their calendar based on their CURRENT request?

The user just said: "{trigger}"

IMPORTANT: Only classify based on what the user JUST said (the trigger above). Ignore any previous conversation context.

Classify the intent:
- "read_today" - wants to know their schedule (e.g. "what's on my calendar", "my schedule today")
- "read_specific" - asking about a specific time or event
- "create" - explicitly wants to create/schedule a new event
- "modify" - wants to change an existing event
- "cancel" - wants to cancel/delete an event
- "invite" - wants to add someone to an event
- "full_briefing" - wants a comprehensive catch-up (e.g. "catch me up", "what's going on")

Determine mode:
- "quick" - specific question or action
- "full" - wants comprehensive briefing

If the trigger is about CREATING an event, extract specifics:
- time: the time mentioned (e.g. "3pm", "8 PM")
- person: any person name mentioned
- event_name: the meeting/event title
- duration: how long (if mentioned)

Return JSON only:
{{"intent": "...", "mode": "quick|full", "details": {{"time": null, "person": null, "event_name": null, "duration": null, "email": null}}}}
"""

# =============================================================================
# CALENDAR INTENT CLASSIFIER (for in-session modifications)
# =============================================================================

CALENDAR_INTENT_PROMPT = """Analyze if the user wants to modify their calendar. Return ONLY valid JSON.

User message: "{user_message}"

Current calendar context:
{calendar_context}

Classify the intent:
- "none" - No calendar modification requested (just asking questions, chatting)
- "reschedule" - Move an event to a different time (push back, bump, move, reschedule)
- "shorten" - Make an event shorter/end earlier
- "extend" - Make an event longer
- "cancel" - Cancel/delete an event
- "create" - Create a new event/meeting
- "invite" - Add a person/guest/attendee to an existing event (invite someone, add guest, include someone)

CRITICAL - change_minutes sign convention:
- POSITIVE = event moves to a LATER time (into the future)
- NEGATIVE = event moves to an EARLIER time (into the past)

Common phrases and their CORRECT sign:
- "push back 30 minutes" → change_minutes: 30 (positive, later)
- "move back 30 minutes" → change_minutes: 30 (positive, later)
- "bump back an hour" → change_minutes: 60 (positive, later)
- "delay by 15 minutes" → change_minutes: 15 (positive, later)
- "move up 30 minutes" → change_minutes: -30 (negative, earlier)
- "bump up an hour" → change_minutes: -60 (negative, earlier)
- "make it earlier by 15" → change_minutes: -15 (negative, earlier)

"Back" = LATER = POSITIVE. "Up" = EARLIER = NEGATIVE.

If a calendar action is detected, identify:
- Which event (by title, attendee name, or time) for modify/cancel/invite actions
- What change (minutes to push, new duration, etc.)
- For CREATE: extract the title, time, and duration if mentioned
- For INVITE: extract the email address if mentioned, and which meeting to add them to

Return JSON only:
{{"intent": "none|reschedule|shorten|extend|cancel|create|invite", "event_match": "string describing which event or null", "change_minutes": number_or_null, "new_duration_minutes": number_or_null, "new_event_title": "title for new event or null", "new_event_time": "time like '4AM' or '3:30 PM' or null", "new_event_duration_minutes": number_or_null, "invite_email": "email address to invite or null", "reason": "brief explanation"}}
"""

CONFLICT_CHECK_PROMPT = """Check if this calendar change causes conflicts.

Proposed change: {change_description}

All events today (with times):
{all_events}

Current time: {current_time}

Analyze:
1. Will moving/extending this event overlap with another?
2. Which events are affected?
3. What adjustments would fix the conflicts?

Return JSON only:
{{"has_conflict": true|false, "conflicting_events": ["event titles"], "suggested_fix": "brief suggestion", "cascade_needed": true|false}}
"""

# =============================================================================
# MAIN CLASS
# =============================================================================


class OutlookCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    context: dict = None
    session_history: list = None
    geo_context: dict = None
    last_session_timestamp: str = None
    user_name: str = ""
    user_email: str = ""
    pending_calendar_action: dict = None  # Tracks pending cascade/confirmation
    pending_create: dict = (
        None  # Tracks create flow: {"title": "...", "waiting_for": "title|time"}
    )
    pending_invite: dict = (
        None  # Tracks invite flow: {"event": ..., "waiting_for": "email|event"}
    )
    calendar_timezone: str = (
        "America/New_York"  # Default, will be overridden by calendar data
    )
    session_mode: str = "full"  # "quick" or "full"
    trigger_data: dict = None  # Stores classified trigger intent

    # {{register capability}}
    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        # OpenHome sandbox requires no os/path usage — config.json is available
        with open("config.json") as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"], matching_hotwords=data["matching_hotwords"]
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.context = {}
        self.session_history = []
        self.geo_context = {}
        self.last_session_timestamp = None
        self.user_name = ""
        self.user_email = ""
        self.pending_calendar_action = None
        self.pending_create = None
        self.pending_invite = None
        self.calendar_timezone = "America/New_York"
        self.session_mode = "full"
        self.trigger_data = {}
        self.worker.session_tasks.create(self.run_hub())

    def log(self, msg):
        self.worker.editor_logging_handler.info(f"[Hub] {msg}")

    def log_err(self, msg):
        self.worker.editor_logging_handler.error(f"[Hub] {msg}")

    async def user_response_with_timeout(self, timeout_seconds: float = 15.0):
        """Wait for user response with timeout. Returns None on silence/timeout."""
        try:
            response = await asyncio.wait_for(
                self.capability_worker.user_response(), timeout=timeout_seconds
            )
            return response
        except asyncio.TimeoutError:
            self.log("User response timeout - silence detected")
            return None
        except Exception as e:
            self.log_err(f"User response error: {e}")
            return None

    # =========================================================================
    # COMPOSIO LAYER
    # =========================================================================

    def execute_tool(self, tool_slug, params):
        """
        Microsoft Graph adapter.
        Converts Graph responses into the Google-shaped format
        expected by the rest of SmartHub.
        """

        headers = {
            "Authorization": f"Bearer {GRAPH_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

        try:

            # ==========================================================
            # PROFILE
            # ==========================================================
            if tool_slug == "OUTLOOKSUPER_GET_PROFILE":
                url = f"{GRAPH_BASE_URL}/me"
                resp = requests.get(url, headers=headers, timeout=15)

                if resp.status_code != 200:
                    self.log_err(f"Graph profile error: {resp.text}")
                    return None

                data = resp.json()

                # Normalize to expected format
                return {
                    "emailAddress": data.get("mail") or data.get("userPrincipalName"),
                    "displayName": data.get("displayName"),
                }

            # ==========================================================
            # FIND EVENTS
            # ==========================================================
            if tool_slug == "OUTLOOKCALENDAR_FIND_EVENT":

                url = f"{GRAPH_BASE_URL}/users/{YOUR_EMAIL}/calendarView"

                query = {
                    "startDateTime": params.get("timeMin"),
                    "endDateTime": params.get("timeMax"),
                    "$orderby": "start/dateTime",
                    "$top": params.get("maxResults", 15),
                }

                resp = requests.get(url, headers=headers, params=query, timeout=15)

                if resp.status_code != 200:
                    self.log_err(f"Graph fetch error: {resp.text}")
                    return None

                graph_data = resp.json()
                items = graph_data.get("value", [])

                # Normalize Graph → Google-style shape
                WINDOWS_TZ_MAP = {
                    "Eastern Standard Time": "America/New_York",
                    "Central Standard Time": "America/Chicago",
                    "Mountain Standard Time": "America/Denver",
                    "Pacific Standard Time": "America/Los_Angeles",
                }

                def trim_iso(dt):
                    if dt and "." in dt:
                        return dt[:26]  # Fix 7-digit microseconds
                    return dt

                normalized_items = []

                for event in items:

                    # ---- TIMEZONE FIX ----
                    raw_start_tz = event.get("start", {}).get("timeZone")
                    raw_end_tz = event.get("end", {}).get("timeZone")

                    start_tz = WINDOWS_TZ_MAP.get(raw_start_tz, raw_start_tz)
                    end_tz = WINDOWS_TZ_MAP.get(raw_end_tz, raw_end_tz)

                    # ---- ATTENDEES FIX ----
                    attendees = []
                    for a in event.get("attendees", []):
                        email_obj = a.get("emailAddress", {})
                        attendees.append(
                            {
                                "displayName": email_obj.get("name") or "",
                                "email": email_obj.get("address") or "",
                            }
                        )

                    # ---- LOCATION SAFE ----
                    location_obj = event.get("location") or {}
                    location = location_obj.get("displayName") or ""

                    # ---- ONLINE MEETING SAFE ----
                    online = event.get("onlineMeeting") or {}
                    join_url = online.get("joinUrl")

                    normalized_items.append(
                        {
                            "id": event.get("id", ""),
                            "summary": event.get("subject") or "Untitled",
                            "start": {
                                "dateTime": trim_iso(
                                    event.get("start", {}).get("dateTime")
                                ),
                                "timeZone": start_tz or "UTC",
                            },
                            "end": {
                                "dateTime": trim_iso(
                                    event.get("end", {}).get("dateTime")
                                ),
                                "timeZone": end_tz or "UTC",
                            },
                            "location": location,
                            "attendees": attendees,
                            "description": event.get("bodyPreview") or "",
                            "status": event.get("showAs") or "",
                            "hangoutLink": join_url,
                            "htmlLink": event.get("webLink"),
                            "conferenceData": online or None,
                        }
                    )

                return {"items": normalized_items}

            # ==========================================================
            # CREATE EVENT
            # ==========================================================
            if tool_slug == "OUTLOOKCALENDAR_CREATE_EVENT":

                url = f"{GRAPH_BASE_URL}/me/events"

                start_dt = datetime.datetime.fromisoformat(
                    params["start_datetime"].replace("Z", "+00:00")
                )

                duration_minutes = params.get(
                    "event_duration_hour", 0
                ) * 60 + params.get("event_duration_minutes", 0)

                end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)

                body = {
                    "subject": params.get("summary"),
                    "start": {
                        "dateTime": start_dt.isoformat(),
                        "timeZone": params.get("timezone", "UTC"),
                    },
                    "end": {
                        "dateTime": end_dt.isoformat(),
                        "timeZone": params.get("timezone", "UTC"),
                    },
                }

                if params.get("location"):
                    body["location"] = {"displayName": params.get("location")}

                if params.get("description"):
                    body["body"] = {
                        "contentType": "text",
                        "content": params.get("description"),
                    }

                if params.get("attendees"):
                    body["attendees"] = [
                        {"emailAddress": {"address": email}, "type": "required"}
                        for email in params.get("attendees", [])
                    ]

                resp = requests.post(url, headers=headers, json=body, timeout=15)

                if resp.status_code not in [200, 201]:
                    self.log_err(f"Graph create error: {resp.text}")
                    return None

                return {"success": True}

            # ==========================================================
            # UPDATE EVENT
            # ==========================================================
            if tool_slug == "OUTLOOKCALENDAR_UPDATE_EVENT":

                event_id = params.get("eventId")
                url = f"{GRAPH_BASE_URL}/me/events/{event_id}"

                start_dt = datetime.datetime.fromisoformat(
                    params["start_datetime"].replace("Z", "+00:00")
                )

                duration_minutes = params.get(
                    "event_duration_hour", 0
                ) * 60 + params.get("event_duration_minutes", 0)

                end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)

                body = {
                    "subject": params.get("summary"),
                    "start": {
                        "dateTime": start_dt.isoformat(),
                        "timeZone": params.get("timezone", "UTC"),
                    },
                    "end": {
                        "dateTime": end_dt.isoformat(),
                        "timeZone": params.get("timezone", "UTC"),
                    },
                }

                if params.get("location"):
                    body["location"] = {"displayName": params.get("location")}

                if params.get("description"):
                    body["body"] = {
                        "contentType": "text",
                        "content": params.get("description"),
                    }

                if params.get("attendees"):
                    body["attendees"] = [
                        {"emailAddress": {"address": email}, "type": "required"}
                        for email in params.get("attendees", [])
                    ]

                resp = requests.patch(url, headers=headers, json=body, timeout=15)

                if resp.status_code not in [200, 202]:
                    self.log_err(f"Graph update error: {resp.text}")
                    return None

                return {"success": True}

            # ==========================================================
            # DELETE EVENT
            # ==========================================================
            if tool_slug == "OUTLOOKCALENDAR_DELETE_EVENT":

                event_id = params.get("eventId")
                url = f"{GRAPH_BASE_URL}/me/events/{event_id}"

                resp = requests.delete(url, headers=headers, timeout=15)

                if resp.status_code != 204:
                    self.log_err(f"Graph delete error: {resp.text}")
                    return None

                return {"success": True}

            self.log_err(f"Unknown tool slug: {tool_slug}")
            return None

        except Exception as e:
            self.log_err(f"Graph exception: {e}")
            return None

    # =========================================================================
    # USER PROFILE (from Outlook Super)
    # =========================================================================

    def fetch_user_profile(self):
        """Get user's email and extract name from Outlook Super."""
        data = self.execute_tool("OUTLOOKSUPER_GET_PROFILE", {})
        if data:
            pdata = data.get("response_data") or data
            self.log(f"Profile data: {json.dumps(pdata)[:300]}")

            email = pdata.get("emailAddress") or pdata.get("email") or ""
            if email:
                self.user_email = email
                local_part = email.split("@")[0]
                name_part = local_part.split(".")[0].split("_")[0]
                self.user_name = name_part.capitalize()
                self.log(f"Extracted name '{self.user_name}' from email '{email}'")
                return

        self.log("Could not fetch user profile from Outlook Super")

    # =========================================================================
    # TRIGGER CONTEXT (reads Main Flow history)
    # =========================================================================

    def get_trigger_context(self):
        """Extract recent conversation context that triggered this ability."""
        recent_user_messages = []

        # Primary source: agent_memory.full_message_history
        try:
            history = self.worker.agent_memory.full_message_history

            if not history:
                self.log("full_message_history is empty or None")
            else:
                self.log(f"Message history length: {len(history)}")

                # Debug: log the last 5 messages
                for i, msg in enumerate(history[-5:]):
                    try:
                        msg_type = type(msg).__name__
                        if hasattr(msg, "content"):
                            content_preview = str(msg.content)[:50]
                        else:
                            content_preview = str(msg)[:50]

                        role = (
                            str(msg.role).lower() if hasattr(msg, "role") else "unknown"
                        )
                        self.log(
                            f"History[{i}]: type={msg_type}, role={role}, content={content_preview}"
                        )
                    except Exception as e:
                        self.log(f"History[{i}]: error - {e}")

                # Extract the most recent USER messages (skip assistant messages)
                for msg in reversed(history):
                    try:
                        if hasattr(msg, "content"):
                            content = str(msg.content).strip()
                        else:
                            content = str(msg).strip()

                        # Skip empty or system content
                        if (
                            not content
                            or "[HUB_SESSION_END|" in content
                            or "[SYSTEM CONTEXT]" in content
                        ):
                            continue

                        # Check if this is a user message
                        if hasattr(msg, "role"):
                            role = str(msg.role).lower()
                            is_user = "user" in role
                        else:
                            is_user = True

                        if is_user and content not in recent_user_messages:
                            recent_user_messages.append(content)
                            if len(recent_user_messages) >= 5:
                                break
                    except Exception as e:
                        self.log_err(f"Error parsing message: {e}")
                        continue

        except Exception as e:
            self.log_err(f"Error reading message history: {e}")

        # The FIRST item in recent_user_messages is the most recent (we iterated in reverse)
        trigger_message = recent_user_messages[0] if recent_user_messages else ""

        self.log(
            f"Trigger context: {len(recent_user_messages)} messages, trigger: '{trigger_message[:80] if trigger_message else 'none'}'"
        )

        return {
            "messages": list(reversed(recent_user_messages)),  # Chronological order
            "trigger": trigger_message,
        }

    def classify_trigger_intent(self, trigger_context: dict):
        """Use LLM to classify the trigger intent and determine mode."""
        trigger = trigger_context.get("trigger", "")

        if not trigger:
            # No trigger found - will ask user what they need
            self.log("No trigger message found, will ask user")
            return {
                "intent": "ask_user",
                "mode": "quick",
                "details": {},
                "no_trigger": True,
            }

        # Check for explicit full briefing triggers
        full_triggers = [
            "catch me up",
            "smart hub",
            "what's going on",
            "brief me",
            "run through my day",
            "overview",
        ]
        if any(ft in trigger.lower() for ft in full_triggers):
            self.log("Full briefing trigger detected")
            return {"intent": "full_briefing", "mode": "full", "details": {}}

        prompt = TRIGGER_INTENT_PROMPT.format(trigger=trigger)

        try:
            response = self.capability_worker.text_to_text_response(prompt)
            clean = response.replace("```json", "").replace("```", "").strip()
            result = json.loads(clean)

            self.log(
                f"Trigger classification: intent={result.get('intent')}, mode={result.get('mode')}, details={result.get('details')}"
            )
            return result
        except Exception as e:
            self.log_err(f"Trigger classification error: {e}")

            # Simple keyword fallback
            lower = trigger.lower()
            if any(
                w in lower
                for w in ["what's on", "schedule", "calendar today", "my day"]
            ):
                return {"intent": "read_today", "mode": "quick", "details": {}}
            elif any(
                w in lower
                for w in ["create", "schedule a", "set up", "new meeting", "new event"]
            ):
                return {"intent": "create", "mode": "quick", "details": {}}

            # Default to asking user
            return {"intent": "ask_user", "mode": "quick", "details": {}}

    # =========================================================================
    # SESSION SIGNATURE (Cross-Session Timestamp Tracking)
    # =========================================================================

    def find_last_session_signature(self):
        """Scan message history for the most recent HUB_SESSION_END marker."""
        try:
            history = self.worker.agent_memory.full_message_history
            if not history:
                self.log("No message history found")
                return None

            for msg in reversed(history):
                try:
                    content = msg.content
                except AttributeError:
                    content = str(msg)

                if "[HUB_SESSION_END|" in content:
                    start = content.find("[HUB_SESSION_END|") + len("[HUB_SESSION_END|")
                    end = content.find("|", start)
                    if end > start:
                        timestamp = content[start:end]
                        self.log(f"Found last session: {timestamp}")
                        return timestamp

            self.log("No previous session signature found")
            return None

        except Exception as e:
            self.log_err(f"Error reading session signature: {e}")
            return None

    def stamp_session_signature(self):
        """Generate a signature to embed in the exit message."""
        now = datetime.datetime.utcnow().isoformat()
        cal_count = len(self.context.get("calendar", []))
        signature = f"[HUB_SESSION_END|{now}|cal:{cal_count}]"
        return signature

    # =========================================================================
    # GEO + WEATHER
    # =========================================================================

    def fetch_ip_geo(self):
        """Fetch geolocation from IP."""
        try:
            user_ip = self.worker.user_socket.client.host
            self.log(f"User IP: {user_ip}")
            resp = requests.get(f"http://ip-api.com/json/{user_ip}", timeout=5)
            data = resp.json()
            self.log(f"Geo response: {json.dumps(data)[:200]}")
            return data
        except Exception as e:
            self.log_err(f"IP geo failed: {e}")
            return {}

    def is_cloud_ip(self, geo_data):
        """Check if IP belongs to a cloud provider."""
        isp = geo_data.get("isp", "").lower()
        org = geo_data.get("org", "").lower()
        combined = isp + " " + org
        for indicator in CLOUD_INDICATORS:
            if indicator in combined:
                return True
        return False

    def fetch_weather(self, lat, lon, use_fahrenheit=True):
        """Fetch current weather from Open-Meteo."""
        try:
            temp_unit = "fahrenheit" if use_fahrenheit else "celsius"
            speed_unit = "mph" if use_fahrenheit else "kmh"
            url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
                f"&temperature_unit={temp_unit}"
                f"&wind_speed_unit={speed_unit}"
            )
            resp = requests.get(url, timeout=5)
            data = resp.json()
            current = data.get("current", {})
            weather_code = current.get("weather_code", 0)
            return {
                "temp": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
                "condition": WEATHER_DESCRIPTIONS.get(
                    weather_code, "unclear conditions"
                ),
                "wind": current.get("wind_speed_10m"),
            }
        except Exception as e:
            self.log_err(f"Weather failed: {e}")
            return {}

    def collect_geo_context(self):
        """Collect IP geo and weather data."""
        geo = self.fetch_ip_geo()

        if geo and geo.get("status") == "success" and not self.is_cloud_ip(geo):
            city = geo.get("city", "")
            region = geo.get("regionName", "")
            country = geo.get("countryCode", "US")
            lat = geo.get("lat", 0)
            lon = geo.get("lon", 0)
            timezone = geo.get("timezone", "America/New_York")
        else:
            # Fallback defaults — replace with your own location if desired
            city = "New York"
            region = "New York"
            country = "US"
            lat = 40.71
            lon = -74.01
            timezone = "America/New_York"

        is_imperial = country in IMPERIAL_COUNTRIES
        weather = self.fetch_weather(lat, lon, use_fahrenheit=is_imperial)

        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(timezone)
            now = datetime.datetime.now(tz)
        except Exception:
            now = datetime.datetime.now()

        hour = now.hour
        time_bucket = get_time_bucket(hour)

        self.geo_context = {
            "city": city,
            "region": region,
            "country": country,
            "timezone": timezone,
            "lat": lat,
            "lon": lon,
            "weather_temp": weather.get("temp", "unknown"),
            "weather_condition": weather.get("condition", "unknown"),
            "weather_humidity": weather.get("humidity", "unknown"),
            "weather_wind": weather.get("wind", "unknown"),
            "time_bucket": time_bucket,
            "current_time": now.strftime("%I:%M %p").lstrip("0"),
            "current_date": now.strftime("%B %d, %Y"),
            "day_of_week": now.strftime("%A"),
            "hour": hour,
            "is_imperial": is_imperial,
        }

        self.log(
            f"Geo context: {city}, {region} | {time_bucket} | {weather.get('temp')}°"
        )

    def has_in_person_meeting(self):
        """Check if any calendar event has a physical location (address)."""
        for event in self.context.get("calendar", []):
            location = event.get("location", "")
            if location and not any(
                x in location.lower()
                for x in ["http", "zoom", "meet.google", "teams.microsoft"]
            ):
                return True
        return False

    def build_weather_remark(self):
        """Build a natural spoken weather remark - only if there's an in-person meeting."""
        if not self.has_in_person_meeting():
            return ""

        condition = self.geo_context.get("weather_condition", "")
        temp = self.geo_context.get("weather_temp", "")
        city = self.geo_context.get("city", "there")

        if not temp or temp == "unknown":
            return ""

        try:
            temp_rounded = int(round(float(temp)))
        except (TypeError, ValueError):
            return ""

        if "rain" in condition or "drizzle" in condition:
            return f"A bit wet out in {city} right now."
        elif "snow" in condition:
            return f"Snowy in {city} right now."
        elif "thunder" in condition:
            return f"Sounds like some thunder out in {city}."
        elif temp_rounded < 40:
            return f"Pretty cold out there at {temp_rounded} degrees."
        elif temp_rounded > 85:
            return f"Hot one today, about {temp_rounded} degrees."
        elif "clear" in condition:
            return f"Nice and clear out in {city}."

        return ""

    # =========================================================================
    # CALENDAR MODULE
    # =========================================================================

    def fetch_upcoming_today(self):
        """Fetch calendar events from now through rest of today (in user's local timezone)."""
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        # To properly get "rest of today", we need to account for user's timezone
        # Most US timezones are UTC-5 to UTC-10, so looking ahead 12 hours
        # from any UTC time should capture until midnight local time
        hours_ahead = 12

        # If we have timezone info, calculate more precisely
        user_tz = self.geo_context.get("timezone", "")
        if user_tz:
            # Rough timezone offset mapping for common US timezones
            tz_offsets = {
                "America/New_York": -5,
                "America/Chicago": -6,
                "America/Denver": -7,
                "America/Los_Angeles": -8,
                "America/Phoenix": -7,
                "America/Anchorage": -9,
                "Pacific/Honolulu": -10,
                "America/Detroit": -5,
                "America/Indiana/Indianapolis": -5,
                "America/Boise": -7,
            }
            offset = tz_offsets.get(user_tz, -5)  # Default to Eastern

            # Calculate hours until midnight local time
            # Local time = UTC + offset
            local_hour = (now_utc.hour + offset) % 24
            hours_until_midnight = 24 - local_hour
            hours_ahead = min(
                hours_until_midnight + 1, 14
            )  # Cap at 14 hours, add 1 for buffer

        end_time = now_utc + datetime.timedelta(hours=hours_ahead)

        time_min = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        self.log(f"Calendar fetch: {time_min} to {time_max} ({hours_ahead}h window)")

        params = {
            "calendarId": "primary",
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "maxResults": 15,
            "orderBy": "startTime",
        }

        raw = self.execute_tool("OUTLOOKCALENDAR_FIND_EVENT", params)

        if not raw:
            self.log("No calendar data retrieved")
            return []

        events = []
        items = []

        event_data_wrapper = raw.get("event_data", {})
        if isinstance(event_data_wrapper, dict):
            items = event_data_wrapper.get("event_data", [])

        if not items:
            raw_data = raw.get("response_data") or raw
            event_data_wrapper = raw_data.get("event_data", {})
            if isinstance(event_data_wrapper, dict):
                items = event_data_wrapper.get("event_data", [])

        if not items:
            items = raw.get("items") or raw.get("events") or []

        if isinstance(raw, list):
            items = raw

        self.log(f"Found {len(items)} raw calendar items")

        if items:
            first_start = items[0].get("start", {})
            first_end = items[0].get("end", {})
            event_tz = first_start.get("timeZone") or first_end.get("timeZone")

            start_dt = first_start.get("dateTime", "")
            has_local_offset = start_dt and (
                "+" in start_dt[-6:] or start_dt[-6:-5] == "-"
            )

            if event_tz and event_tz != "UTC":
                self.calendar_timezone = event_tz
            elif has_local_offset and self.geo_context.get("timezone"):
                self.calendar_timezone = self.geo_context.get("timezone")
            elif event_tz:
                self.calendar_timezone = event_tz

            self.log(f"Calendar timezone: {self.calendar_timezone}")

        now = datetime.datetime.now(datetime.timezone.utc)

        for item in items:
            start = item.get("start", {})
            start_time = start.get("dateTime") or start.get("date", "")
            end = item.get("end", {})
            end_time = end.get("dateTime") or end.get("date", "")

            in_progress = False
            mins_remaining = None
            mins_until_start = None

            try:
                if start_time and end_time and "T" in start_time:
                    start_dt = datetime.datetime.fromisoformat(
                        start_time.replace("Z", "+00:00")
                    )
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)

                    end_dt = datetime.datetime.fromisoformat(
                        end_time.replace("Z", "+00:00")
                    )
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)

                    if start_dt <= now <= end_dt:
                        in_progress = True
                        remaining = end_dt - now
                        mins_remaining = int(remaining.total_seconds() / 60)
                    elif now < start_dt:
                        until = start_dt - now
                        mins_until_start = int(until.total_seconds() / 60)
            except Exception as e:
                self.log(f"Time parse error: {e}")

            attendees_raw = item.get("attendees", [])
            attendees = []
            attendee_emails = []
            for a in attendees_raw:
                name = a.get("displayName") or a.get("email", "")
                if name:
                    attendees.append(name)
                email = a.get("email")
                if email:
                    attendee_emails.append(email)

            events.append(
                {
                    "id": item.get("id", ""),
                    "title": item.get("summary", "Untitled"),
                    "start": start_time,
                    "end": end_time,
                    "location": item.get("location", ""),
                    "attendees": attendees,
                    "attendee_emails": attendee_emails,
                    "description": (item.get("description") or "")[:200],
                    "status": item.get("status", ""),
                    "link": item.get("hangoutLink") or item.get("htmlLink", ""),
                    "conferenceData": item.get("conferenceData"),
                    "in_progress": in_progress,
                    "mins_remaining": mins_remaining,
                    "mins_until_start": mins_until_start,
                }
            )

        self.log(f"Calendar: {len(events)} upcoming events today")
        return events

    # =========================================================================
    # CALENDAR WRITE OPERATIONS
    # =========================================================================

    def normalize_for_match(self, text: str) -> str:
        """Normalize text for fuzzy matching - remove punctuation and special chars."""
        # Remove common separators and punctuation
        normalized = text.lower()
        for char in [
            "<>",
            "<",
            ">",
            "-",
            "_",
            ",",
            ".",
            ":",
            ";",
            "|",
            "/",
            "\\",
            "(",
            ")",
            "[",
            "]",
            "{",
            "}",
        ]:
            normalized = normalized.replace(char, " ")
        # Collapse multiple spaces
        normalized = " ".join(normalized.split())
        return normalized

    def get_content_words(self, text: str) -> set:
        """Get content words from text, excluding common stop words."""
        stop_words = {
            "the",
            "a",
            "an",
            "with",
            "my",
            "to",
            "on",
            "at",
            "for",
            "of",
            "in",
            "and",
            "or",
            "is",
            "it",
            "can",
            "you",
            "i",
            "me",
            "we",
            "our",
            "event",
            "meeting",
            "call",
            "sync",
            "one",
            "that",
            "this",
        }
        words = set(self.normalize_for_match(text).split())
        return words - stop_words

    def clean_title_for_speech(self, title: str) -> str:
        """Clean event title for natural speech output."""
        # Remove special characters that sound weird when spoken
        clean = title.replace("<>", "and").replace("|", "and")
        clean = clean.replace("  ", " ").strip()
        return clean

    def strip_shorten_preamble(self, text: str) -> str:
        """Strip accumulated preamble phrases from shorten/modify requests."""
        clean = text.strip()
        preambles = [
            "can you shorten one of my meetings",
            "can you shorten my meeting with",
            "can you shorten my meeting",
            "can you shorten the",
            "shorten my meeting with",
            "shorten the meeting with",
            "the one with",
            "meeting with",
            "the meeting with",
        ]
        lower = clean.lower()
        for phrase in preambles:
            if lower.startswith(phrase):
                clean = clean[len(phrase):].strip()
                clean = clean.lstrip(".,;:").strip()
                break
        # Also strip trailing punctuation
        clean = clean.rstrip(".,;:?!")
        return clean

    def find_event_by_match(self, match_text: str):
        """Find an event from context by fuzzy matching title or attendee."""
        if not self.context.get("calendar"):
            return None

        calendar = self.context["calendar"]

        # Strip any preamble first
        original_text = match_text
        match_text = self.strip_shorten_preamble(match_text)
        self.log(f"Event match: '{original_text}' -> '{match_text}'")

        # Handle ordinal references: "the first one", "first", "second", etc.
        ordinals = {
            "first": 0,
            "1st": 0,
            "the first": 0,
            "the first one": 0,
            "second": 1,
            "2nd": 1,
            "the second": 1,
            "the second one": 1,
            "third": 2,
            "3rd": 2,
            "the third": 2,
            "the third one": 2,
            "last": -1,
            "the last": -1,
            "the last one": -1,
        }

        match_lower = match_text.lower().strip()
        for ordinal, idx in ordinals.items():
            if match_lower == ordinal or match_lower.startswith(ordinal + " "):
                if idx == -1:
                    return calendar[-1] if calendar else None
                elif idx < len(calendar):
                    return calendar[idx]
                return None

        # Get content words (excluding stop words like "with", "the", "my")
        match_content_words = self.get_content_words(match_text)
        match_normalized = self.normalize_for_match(match_text)

        self.log(f"Content words for matching: {match_content_words}")

        best_match = None
        best_score = 0

        for event in calendar:
            title = event["title"]
            title_normalized = self.normalize_for_match(title)
            title_content_words = self.get_content_words(title)

            # Check for CONTENT word overlap (not counting "with", "the", etc.)
            content_overlap = len(match_content_words & title_content_words)

            # Also check for fuzzy name matching (prefix/substring)
            fuzzy_match_score = 0
            for match_word in match_content_words:
                if len(match_word) < 3:
                    continue  # Skip very short words
                for title_word in title_content_words:
                    if len(title_word) < 3:
                        continue
                    # Check if one is a prefix of the other (at least 3 chars)
                    if match_word.startswith(title_word[:3]) or title_word.startswith(
                        match_word[:3]
                    ):
                        fuzzy_match_score += 0.5
                        self.log(f"  Fuzzy match: '{match_word}' ~ '{title_word}'")
                    # Check if one contains the other
                    elif match_word in title_word or title_word in match_word:
                        fuzzy_match_score += 0.7
                        self.log(
                            f"  Substring match in words: '{match_word}' in '{title_word}' or vice versa"
                        )

            total_score = content_overlap + fuzzy_match_score

            # Score based on content overlap + fuzzy matching
            if total_score > best_score:
                best_score = total_score
                best_match = event
                self.log(
                    f"  '{title}' - score: {total_score} (exact: {content_overlap}, fuzzy: {fuzzy_match_score})"
                )

            # Also check if match text is contained in title (substring match)
            # But only if it has content words (not just "the meeting")
            if match_normalized in title_normalized and len(match_content_words) >= 1:
                self.log(f"  Substring match: '{match_text}' in '{title}'")
                return event

            # Check attendees for person names
            for attendee in event.get("attendees", []):
                attendee_normalized = self.normalize_for_match(attendee)
                # Check if any content word matches attendee (exact or fuzzy)
                for word in match_content_words:
                    if word in attendee_normalized:
                        self.log(f"  Attendee match: '{word}' in '{attendee}'")
                        return event
                    # Fuzzy match on attendee name
                    if len(word) >= 3:
                        attendee_words = attendee_normalized.split()
                        for att_word in attendee_words:
                            if len(att_word) >= 3 and (
                                word.startswith(att_word[:3])
                                or att_word.startswith(word[:3])
                            ):
                                self.log(
                                    f"  Fuzzy attendee match: '{word}' ~ '{att_word}'"
                                )
                                return event
                # Check name part of email
                if "@" in attendee:
                    name_part = self.normalize_for_match(attendee.split("@")[0])
                    for word in match_content_words:
                        if word in name_part:
                            self.log(f"  Email name match: '{word}' in '{name_part}'")
                            return event

        # Return best match if we found at least some match
        # Exact word match = 1, fuzzy prefix = 0.5, substring = 0.7
        if best_score >= 0.5:
            self.log(
                f"Matched event: '{best_match['title']}' (ID: {best_match.get('id', 'N/A')}) with score {best_score}"
            )
            return best_match

        self.log(f"No event match found for '{match_text}'")
        return None

    def find_most_recent_event(self):
        """Find the most recently created/discussed event (usually the last one we just created)."""
        if not self.context.get("calendar"):
            return None

        # Check session history for recently created events
        for turn in reversed(self.session_history):
            content = turn.get("content", "").lower()
            if "created" in content or "i've created" in content:
                # Try to extract event name from the response
                for event in self.context["calendar"]:
                    if event["title"].lower() in content:
                        return event

        # Fallback: return the last event in the calendar (most recent by time)
        if self.context["calendar"]:
            return self.context["calendar"][-1]

        return None

    def detect_conflicts(self, event_id: str, new_start: str, new_end: str):
        """Check if the new time slot conflicts with other events."""
        conflicts = []

        try:
            new_start_dt = datetime.datetime.fromisoformat(
                new_start.replace("Z", "+00:00")
            )
            new_end_dt = datetime.datetime.fromisoformat(new_end.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return conflicts

        for event in self.context.get("calendar", []):
            if event["id"] == event_id:
                continue

            try:
                evt_start = datetime.datetime.fromisoformat(
                    event["start"].replace("Z", "+00:00")
                )
                evt_end = datetime.datetime.fromisoformat(
                    event["end"].replace("Z", "+00:00")
                )

                if new_start_dt < evt_end and new_end_dt > evt_start:
                    conflicts.append(event)
            except (TypeError, ValueError):
                continue

        return conflicts

    def reschedule_event(self, event: dict, minutes_delta: int):
        """Push an event forward or backward by X minutes."""
        if not event.get("id"):
            return None, "Could not find event ID"

        try:
            old_start = datetime.datetime.fromisoformat(
                event["start"].replace("Z", "+00:00")
            )
            old_end = datetime.datetime.fromisoformat(
                event["end"].replace("Z", "+00:00")
            )

            original_duration = int((old_end - old_start).total_seconds() / 60)
            duration_hours = original_duration // 60
            duration_minutes = original_duration % 60

            new_start = old_start + datetime.timedelta(minutes=minutes_delta)

            self.log(
                f"Reschedule: {event['title']} | duration: {original_duration}m | delta: {minutes_delta}m"
            )
            self.log(f"  Old: {old_start.isoformat()} to {old_end.isoformat()}")
            self.log(
                f"  New start: {new_start.isoformat()}, duration: {duration_hours}h {duration_minutes}m"
            )

            new_end = new_start + datetime.timedelta(minutes=original_duration)
            conflicts = self.detect_conflicts(
                event["id"], new_start.isoformat(), new_end.isoformat()
            )

            if conflicts:
                conflict_titles = [c["title"] for c in conflicts]
                return None, f"Conflict with: {', '.join(conflict_titles)}"

            update_params = {
                "calendarId": "primary",
                "eventId": event["id"],
                "summary": event.get("title", "Meeting"),
                "start_datetime": new_start.isoformat(),
                "event_duration_hour": duration_hours,
                "event_duration_minutes": duration_minutes,
                "timezone": self.calendar_timezone,
            }

            if event.get("location"):
                update_params["location"] = event["location"]

            if event.get("description"):
                update_params["description"] = event["description"]

            if event.get("attendee_emails"):
                update_params["attendees"] = event["attendee_emails"]
                self.log(f"  Preserving {len(event['attendee_emails'])} attendees")

            self.log(f"Update params: {update_params}")

            update_result = self.execute_tool(
                "OUTLOOKCALENDAR_UPDATE_EVENT", update_params
            )

            if update_result:
                self.log(f"Updated event '{event['title']}'")
                return update_result, None
            else:
                return None, "Failed to update event"

        except Exception as e:
            self.log_err(f"Reschedule error: {e}")
            return None, str(e)

    def shorten_event(self, event: dict, new_duration_minutes: int):
        """Change an event's duration (shorten or extend)."""
        if not event.get("id"):
            return None, "Could not find event ID"

        try:
            old_start = datetime.datetime.fromisoformat(
                event["start"].replace("Z", "+00:00")
            )

            duration_hours = new_duration_minutes // 60
            duration_minutes = new_duration_minutes % 60

            self.log(
                f"Shorten: {event['title']} to {new_duration_minutes}m ({duration_hours}h {duration_minutes}m)"
            )
            self.log(f"  Start: {old_start.isoformat()}")

            update_params = {
                "calendarId": "primary",
                "eventId": event["id"],
                "summary": event.get("title", "Meeting"),
                "start_datetime": old_start.isoformat(),
                "event_duration_hour": duration_hours,
                "event_duration_minutes": duration_minutes,
                "timezone": self.calendar_timezone,
            }

            if event.get("location"):
                update_params["location"] = event["location"]

            if event.get("description"):
                update_params["description"] = event["description"]

            if event.get("attendee_emails"):
                update_params["attendees"] = event["attendee_emails"]
                self.log(f"  Preserving {len(event['attendee_emails'])} attendees")

            self.log(f"Update params: {update_params}")

            update_result = self.execute_tool(
                "OUTLOOKCALENDAR_UPDATE_EVENT", update_params
            )

            if update_result:
                self.log(
                    f"Changed '{event['title']}' duration to {new_duration_minutes} minutes"
                )
                return update_result, None
            else:
                return None, "Failed to update event"

        except Exception as e:
            self.log_err(f"Shorten error: {e}")
            return None, str(e)

    def extend_event(self, event: dict, new_duration_minutes: int):
        """Extend an event's duration (uses same logic as shorten)."""
        return self.shorten_event(event, new_duration_minutes)

    def parse_duration_minutes(self, text: str) -> int:
        """Parse a duration string like '30 minutes', 'half an hour', '1 hour' into minutes.
        Does NOT parse time formats like '9PM' - those should go through parse_time_to_datetime.
        """
        lower = text.lower().strip()

        # FIRST: Reject if this looks like a time format (e.g., "9pm", "9:30am", "9 pm")
        # This prevents "9pm" from being parsed as "9 minutes"
        if re.search(r"\d+\s*(?:am|pm|a\.m\.|p\.m\.)", lower):
            return None
        if re.search(r"\d+:\d+", lower):  # Time with colon like "9:30"
            return None

        # Direct minute patterns: "30 minutes", "45 mins", "30"
        match = re.search(r"(\d+)\s*(?:min|minute|mins|minutes|m\b)?", lower)
        if match:
            mins = int(match.group(1))
            # If just a number and it's reasonable for minutes, use it
            if mins <= 180:  # Up to 3 hours
                return mins

        # Hour patterns: "1 hour", "2 hours", "an hour"
        hour_match = re.search(r"(\d+)\s*(?:hour|hours|hr|hrs)", lower)
        if hour_match:
            hours = int(hour_match.group(1))
            # Check for "and X minutes" addition
            min_add = re.search(r"and\s*(\d+)\s*(?:min|minute|mins|minutes)?", lower)
            extra_mins = int(min_add.group(1)) if min_add else 0
            return (hours * 60) + extra_mins

        # "an hour" / "one hour"
        if "an hour" in lower or "one hour" in lower:
            return 60

        # "half an hour", "half hour"
        if "half" in lower and "hour" in lower:
            return 30

        # "quarter hour"
        if "quarter" in lower and "hour" in lower:
            return 15

        # Word numbers
        word_to_num = {
            "five": 5,
            "ten": 10,
            "fifteen": 15,
            "twenty": 20,
            "twenty-five": 25,
            "thirty": 30,
            "forty-five": 45,
            "forty": 40,
            "fifty": 50,
            "sixty": 60,
        }

        for word, num in word_to_num.items():
            if word in lower:
                return num

        return None

    def cancel_event(self, event: dict):
        """Cancel/delete an event."""
        if not event.get("id"):
            return None, "Could not find event ID"

        params = {"calendarId": "primary", "eventId": event["id"]}

        result = self.execute_tool("OUTLOOKCALENDAR_DELETE_EVENT", params)

        if result:
            self.log(f"Cancelled '{event['title']}'")
            return result, None
        else:
            return None, "Failed to cancel event"

    def add_attendee_to_event(self, event: dict, email: str):
        """Add an attendee to an existing event."""
        if not event.get("id"):
            return None, "Could not find event ID"

        try:
            # Get current attendees and add the new one
            current_emails = event.get("attendee_emails", [])

            # Check if already invited
            if email.lower() in [e.lower() for e in current_emails]:
                return None, f"{email} is already invited to this meeting"

            # Add new attendee
            updated_emails = current_emails + [email]

            self.log(f"Adding attendee '{email}' to '{event['title']}'")
            self.log(f"  Current attendees: {current_emails}")
            self.log(f"  Updated attendees: {updated_emails}")

            # Parse start time and calculate duration
            old_start = datetime.datetime.fromisoformat(
                event["start"].replace("Z", "+00:00")
            )
            old_end = datetime.datetime.fromisoformat(
                event["end"].replace("Z", "+00:00")
            )
            original_duration = int((old_end - old_start).total_seconds() / 60)
            duration_hours = original_duration // 60
            duration_minutes = original_duration % 60

            update_params = {
                "calendarId": "primary",
                "eventId": event["id"],
                "summary": event.get("title", "Meeting"),
                "start_datetime": old_start.isoformat(),
                "event_duration_hour": duration_hours,
                "event_duration_minutes": duration_minutes,
                "timezone": self.calendar_timezone,
                "attendees": updated_emails,
            }

            if event.get("location"):
                update_params["location"] = event["location"]

            if event.get("description"):
                update_params["description"] = event["description"]

            self.log(f"Update params: {json.dumps(update_params)[:300]}")

            update_result = self.execute_tool(
                "OUTLOOKCALENDAR_UPDATE_EVENT", update_params
            )

            if update_result:
                self.log(f"Added '{email}' to '{event['title']}'")
                return update_result, None
            else:
                return None, "Failed to update event with new attendee"

        except Exception as e:
            self.log_err(f"Add attendee error: {e}")
            return None, str(e)

    def create_event(
        self, title: str, start_time: str, duration_minutes: int, attendees: list = None
    ):
        """Create a new calendar event."""
        try:
            if "+" in start_time or start_time.endswith("Z"):
                start_dt = datetime.datetime.fromisoformat(
                    start_time.replace("Z", "+00:00")
                )
            else:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(self.calendar_timezone)
                start_dt = datetime.datetime.fromisoformat(start_time).replace(
                    tzinfo=tz
                )

            duration_hours = duration_minutes // 60
            duration_mins = duration_minutes % 60

            self.log(
                f"Creating event '{title}' at {start_dt.isoformat()} for {duration_minutes}m"
            )

            create_params = {
                "calendarId": "primary",
                "summary": title,
                "start_datetime": start_dt.isoformat(),
                "event_duration_hour": duration_hours,
                "event_duration_minutes": duration_mins,
                "timezone": self.calendar_timezone,
            }

            if attendees:
                create_params["attendees"] = attendees

            self.log(f"Create params: {create_params}")

            result = self.execute_tool("OUTLOOKCALENDAR_CREATE_EVENT", create_params)

            if result:
                self.log(f"Created event '{title}'")
                return result, None
            else:
                return None, "Failed to create event"

        except Exception as e:
            self.log_err(f"Create error: {e}")
            return None, str(e)

    def cascade_reschedule(self, starting_event: dict, minutes_delta: int):
        """Push back events that are in the conflict chain only.

        Only moves events that would actually overlap after the reschedule,
        NOT all events after the starting time.
        """
        results = []
        events_to_move = []

        try:
            start_time = datetime.datetime.fromisoformat(
                starting_event["start"].replace("Z", "+00:00")
            )
            start_end = datetime.datetime.fromisoformat(
                starting_event["end"].replace("Z", "+00:00")
            )
            start_duration = int((start_end - start_time).total_seconds() / 60)
        except (TypeError, ValueError):
            return [], "Could not parse event time"

        # Get all calendar events sorted by start time
        all_events = []
        for event in self.context.get("calendar", []):
            try:
                evt_start = datetime.datetime.fromisoformat(
                    event["start"].replace("Z", "+00:00")
                )
                evt_end = datetime.datetime.fromisoformat(
                    event["end"].replace("Z", "+00:00")
                )
                all_events.append(
                    {
                        "event": event,
                        "start": evt_start,
                        "end": evt_end,
                        "duration": int((evt_end - evt_start).total_seconds() / 60),
                    }
                )
            except (TypeError, ValueError):
                continue

        all_events.sort(key=lambda e: e["start"])

        # Start with the target event
        events_to_move.append(
            {
                "event": starting_event,
                "start": start_time,
                "end": start_end,
                "duration": start_duration,
            }
        )

        # Calculate where the starting event will end up
        current_new_end = (
            start_time
            + datetime.timedelta(minutes=minutes_delta)
            + datetime.timedelta(minutes=start_duration)
        )

        # Walk through subsequent events and only add those that would conflict
        for evt_data in all_events:
            # Skip the starting event itself
            if evt_data["event"]["id"] == starting_event["id"]:
                continue

            # Only consider events that start after our starting event
            if evt_data["start"] <= start_time:
                continue

            # Check if this event would conflict with where we're moving to
            # Conflict = event starts before current_new_end
            if evt_data["start"] < current_new_end:
                events_to_move.append(evt_data)
                # Update current_new_end to this event's new end time
                new_evt_start = evt_data["start"] + datetime.timedelta(
                    minutes=minutes_delta
                )
                current_new_end = new_evt_start + datetime.timedelta(
                    minutes=evt_data["duration"]
                )
            else:
                # No more conflicts in the chain - we're done
                break

        self.log(f"Cascade: Moving {len(events_to_move)} events (conflict chain only)")

        # Move events in REVERSE order (last first) to avoid conflicts during the move
        events_to_move.reverse()

        for evt_data in events_to_move:
            event = evt_data["event"]
            result, error = self.reschedule_event_no_conflict_check(
                event, minutes_delta
            )
            if error:
                results.append(f"Failed to move '{event['title']}': {error}")
            else:
                results.append(f"Moved '{event['title']}' by {minutes_delta} minutes")

        return results, None

    def reschedule_event_no_conflict_check(self, event: dict, minutes_delta: int):
        """Push an event forward or backward by X minutes WITHOUT conflict checking.
        Used by cascade_reschedule where we're intentionally moving multiple events."""
        if not event.get("id"):
            return None, "Could not find event ID"

        try:
            old_start = datetime.datetime.fromisoformat(
                event["start"].replace("Z", "+00:00")
            )
            old_end = datetime.datetime.fromisoformat(
                event["end"].replace("Z", "+00:00")
            )

            original_duration = int((old_end - old_start).total_seconds() / 60)
            duration_hours = original_duration // 60
            duration_minutes = original_duration % 60

            new_start = old_start + datetime.timedelta(minutes=minutes_delta)

            self.log(
                f"Cascade move: {event['title']} | {old_start.strftime('%H:%M')} -> {new_start.strftime('%H:%M')}"
            )

            update_params = {
                "calendarId": "primary",
                "eventId": event["id"],
                "summary": event.get("title", "Meeting"),
                "start_datetime": new_start.isoformat(),
                "event_duration_hour": duration_hours,
                "event_duration_minutes": duration_minutes,
                "timezone": self.calendar_timezone,
            }

            if event.get("location"):
                update_params["location"] = event["location"]

            if event.get("description"):
                update_params["description"] = event["description"]

            if event.get("attendee_emails"):
                update_params["attendees"] = event["attendee_emails"]

            update_result = self.execute_tool(
                "OUTLOOKCALENDAR_UPDATE_EVENT", update_params
            )

            if update_result:
                self.log(f"Moved '{event['title']}'")
                return update_result, None
            else:
                return None, "Failed to update event"

        except Exception as e:
            self.log_err(f"Cascade reschedule error: {e}")
            return None, str(e)

    def parse_time_to_datetime(self, time_str: str):
        """Parse a time string like '4AM', '3:30 PM', '14:00' into a datetime for today in user's timezone."""
        import re
        from zoneinfo import ZoneInfo

        if not time_str:
            return None

        time_str = time_str.strip().upper()
        time_str = re.sub(r"[,\.!?]", "", time_str)

        # Remove "tonight", "today", etc. but remember if it was specified
        original_time_str = time_str
        time_str = re.sub(r"\s*(TONIGHT|TODAY|THIS EVENING)\s*", " ", time_str).strip()

        words = time_str.split()
        if len(words) > 1 and words[0] == words[-1]:
            time_str = words[0]
        elif len(words) > 1:
            for word in words:
                if re.search(r"\d", word):
                    time_str = word
                    break

        time_str = time_str.replace(" ", "")

        # Use user's timezone, not server time
        try:
            tz = ZoneInfo(self.calendar_timezone)
            now = datetime.datetime.now(tz)
        except Exception:
            now = datetime.datetime.now()

        patterns = [
            (
                r"^(\d{1,2}):(\d{2})(AM|PM)$",
                lambda m: (
                    int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0),
                    int(m.group(2)),
                ),
            ),
            (
                r"^(\d{1,2})(AM|PM)$",
                lambda m: (int(m.group(1)) % 12 + (12 if m.group(2) == "PM" else 0), 0),
            ),
            (r"^(\d{1,2}):(\d{2})$", lambda m: (int(m.group(1)), int(m.group(2)))),
            (
                r"^(\d)(\d{2})(AM|PM)$",
                lambda m: (
                    int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0),
                    int(m.group(2)),
                ),
            ),
            (
                r"^(\d{2})(\d{2})(AM|PM)$",
                lambda m: (
                    int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0),
                    int(m.group(2)),
                ),
            ),
        ]

        for pattern, extractor in patterns:
            match = re.match(pattern, time_str)
            if match:
                hour, minute = extractor(match)
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    result = now.replace(
                        hour=hour, minute=minute, second=0, microsecond=0
                    )
                    self.log(
                        f"Parsed time '{original_time_str}' -> {result.isoformat()} (user tz: {self.calendar_timezone})"
                    )
                    return result

        return None

    def extract_email_from_text(self, text: str):
        """Extract an email address from user input."""
        import re

        # Clean up speech-to-text quirks
        # e.g. "jane at example dot com" -> "jane@example.com"
        cleaned = text.lower().strip()
        cleaned = cleaned.replace(" at ", "@").replace(" dot ", ".")
        cleaned = cleaned.replace("at ", "@").replace(" dot", ".")

        # Remove trailing punctuation
        cleaned = cleaned.rstrip("?.,!")

        # Try to find email pattern
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        match = re.search(email_pattern, cleaned)
        if match:
            return match.group(0)

        # If the whole thing looks like an email after cleanup
        if "@" in cleaned and "." in cleaned:
            # Remove extra words
            words = cleaned.split()
            for word in words:
                if "@" in word and "." in word:
                    return word

        return None

    def classify_calendar_intent(self, user_message: str):
        """Use LLM to classify if user wants to modify calendar."""
        cal_context = "No events loaded."
        if self.context.get("calendar"):
            lines = []
            for e in self.context["calendar"]:
                status = "[NOW]" if e.get("in_progress") else ""
                lines.append(
                    f"- {status} {e['title']} | {e['start']} to {e['end']} | attendees: {', '.join(e.get('attendees', []))}"
                )
            cal_context = "\n".join(lines)

        prompt = CALENDAR_INTENT_PROMPT.format(
            user_message=user_message, calendar_context=cal_context
        )

        try:
            response = self.capability_worker.text_to_text_response(prompt)
            clean = response.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except Exception as e:
            self.log_err(f"Intent classification error: {e}")
            return {"intent": "none", "reason": "parse error"}

    async def handle_calendar_write(self, intent_data: dict, user_message: str):
        """Process a calendar write intent and execute the action."""
        intent = intent_data.get("intent", "none")
        event_match = intent_data.get("event_match", "")
        change_mins = intent_data.get("change_minutes")
        new_duration = intent_data.get("new_duration_minutes")
        invite_email = intent_data.get("invite_email")

        self.log(
            f"Calendar write intent: {intent} | match: {event_match} | mins: {change_mins}"
        )

        if intent == "none":
            return None

        # Check if event_match is actually ambiguous or empty
        is_ambiguous = (
            not event_match
            or "ambiguous" in event_match.lower()
            or "asking which" in event_match.lower()
            or "unclear" in event_match.lower()
            or "user asking" in event_match.lower()
            or len(event_match) > 60  # LLM explanation, not a real match
        )

        # Find the event (only if we have a real match)
        event = None
        if event_match and not is_ambiguous:
            event = self.find_event_by_match(event_match)

        if event:
            self.log(
                f"Matched event: '{event['title']}' (ID: {event.get('id', 'none')})"
            )
        else:
            self.log(f"No event matched for: {event_match}")

        # If we need an event but don't have one, set up pending state
        if intent in ["reschedule", "shorten", "extend", "cancel"] and not event:
            # Set up pending action so we can continue when user specifies which event
            action_word = {
                "reschedule": "reschedule",
                "shorten": "shorten",
                "extend": "extend",
                "cancel": "cancel",
            }.get(intent, "modify")

            self.pending_calendar_action = {
                "type": f"{intent}_pending_event",
                "intent": intent,
                "change_mins": change_mins,
                "new_duration": new_duration,
                "waiting_for": "event",
            }

            # List their events to help them choose
            calendar = self.context.get("calendar", [])
            if calendar and len(calendar) <= 3:
                event_names = [
                    self.clean_title_for_speech(e.get("title", "Untitled"))
                    for e in calendar
                ]
                return f"Which meeting do you want to {action_word}? You have: {', '.join(event_names)}."
            else:
                return f"Which meeting do you want to {action_word}?"

        # =====================================================================
        # INVITE INTENT - Add attendee to event
        # =====================================================================
        if intent == "invite":
            # If no event specified, try to find the most recently discussed one
            if not event:
                event = self.find_most_recent_event()
                if event:
                    self.log(f"Using most recent event: '{event['title']}'")

            if not event:
                # No event found - ask which meeting
                self.pending_invite = {"waiting_for": "event"}
                return "Which meeting should I add them to?"

            # Check if we have an email
            if invite_email:
                # We have everything - but ask for confirmation first
                email_spoken = invite_email.replace("@", " at ").replace(".", " dot ")
                self.pending_invite = {
                    "event": event,
                    "email": invite_email,
                    "waiting_for": "confirm",
                }
                return f"Just to confirm, I'll add {email_spoken} to '{event['title']}'. Sound good?"
            else:
                # No email provided - ask for it
                self.pending_invite = {"event": event, "waiting_for": "email"}
                return f"Who would you like me to add to '{event['title']}'? Just give me their email."

        if intent == "reschedule":
            if not change_mins:
                # Set pending state to wait for time change amount
                self.pending_calendar_action = {
                    "type": "reschedule_pending_time",
                    "event": event,
                    "waiting_for": "time_change",
                }
                return f"Got it, '{self.clean_title_for_speech(event['title'])}'. How many minutes should I push it?"

            try:
                old_start = datetime.datetime.fromisoformat(
                    event["start"].replace("Z", "+00:00")
                )
                old_end = datetime.datetime.fromisoformat(
                    event["end"].replace("Z", "+00:00")
                )
                new_start = old_start + datetime.timedelta(minutes=change_mins)
                new_end = old_end + datetime.timedelta(minutes=change_mins)

                conflicts = self.detect_conflicts(
                    event["id"], new_start.isoformat(), new_end.isoformat()
                )

                if conflicts:
                    conflict_names = [c["title"] for c in conflicts]
                    self.pending_calendar_action = {
                        "type": "reschedule_with_conflict",
                        "event": event,
                        "change_mins": change_mins,
                        "conflicts": conflicts,
                    }
                    direction = "up" if change_mins < 0 else "back"
                    return f"Moving '{event['title']}' {direction} {abs(change_mins)} minutes would overlap with {', '.join(conflict_names)}. Want me to adjust those too, or would you rather shorten the current meeting?"
            except Exception as e:
                self.log_err(f"Conflict check error: {e}")

            result, error = self.reschedule_event(event, change_mins)
            if error:
                return f"Couldn't reschedule: {error}"

            if change_mins < 0:
                return f"Done! I've moved '{event['title']}' up {abs(change_mins)} minutes."
            else:
                return (
                    f"Done! I've pushed '{event['title']}' back {change_mins} minutes."
                )

        elif intent == "shorten":
            if not new_duration:
                # Set pending state to wait for duration
                self.pending_calendar_action = {
                    "type": "shorten_pending_duration",
                    "event": event,
                    "waiting_for": "duration",
                }
                return f"Got it, '{self.clean_title_for_speech(event['title'])}'. How long should it be?"

            result, error = self.shorten_event(event, new_duration)
            if error:
                return f"Couldn't shorten the event: {error}"
            return f"Done! '{event['title']}' is now {new_duration} minutes."

        elif intent == "extend":
            if not new_duration:
                return "How long should the meeting be?"

            try:
                old_start = datetime.datetime.fromisoformat(
                    event["start"].replace("Z", "+00:00")
                )
                new_end = old_start + datetime.timedelta(minutes=new_duration)
                conflicts = self.detect_conflicts(
                    event["id"], event["start"], new_end.isoformat()
                )

                if conflicts:
                    return f"Extending to {new_duration} minutes would overlap with '{conflicts[0]['title']}'. Want me to push that back or keep the current duration?"
            except (TypeError, ValueError):
                pass

            result, error = self.shorten_event(event, new_duration)
            if error:
                return f"Couldn't extend the event: {error}"
            return f"Done! '{event['title']}' is now {new_duration} minutes."

        elif intent == "cancel":
            result, error = self.cancel_event(event)
            if error:
                return f"Couldn't cancel: {error}"
            return f"Done! I've cancelled '{event['title']}'."

        elif intent == "create":
            title = intent_data.get("new_event_title")
            time_str = intent_data.get("new_event_time")
            duration = intent_data.get("new_event_duration_minutes") or 60

            if not title:
                self.pending_create = {"waiting_for": "title"}
                return "What should I call this meeting?"

            if not time_str:
                self.pending_create = {
                    "title": title,
                    "duration": duration,
                    "waiting_for": "time",
                }
                return f"Got it, '{title}'. What time should it be?"

            self.pending_create = None

            try:
                start_time = self.parse_time_to_datetime(time_str)
                if not start_time:
                    return f"I couldn't understand the time '{time_str}'. Could you give me something like '4 PM' or '3:30'?"

                result, error = self.create_event(
                    title, start_time.isoformat(), duration
                )
                if error:
                    return f"Couldn't create the event: {error}"
                return f"Done! I've created '{title}' at {time_str} for {duration} minutes."
            except Exception as e:
                self.log_err(f"Create event error: {e}")
                return f"Had trouble creating that event: {e}"

        return None

    async def handle_pending_invite(self, user_input: str):
        """Handle follow-up to a pending invite action."""
        if not self.pending_invite:
            return None

        waiting_for = self.pending_invite.get("waiting_for")

        # Check for cancel
        lower = user_input.lower()
        if any(
            phrase in lower
            for phrase in [
                "never mind",
                "nevermind",
                "cancel",
                "forget it",
                "no",
                "nope",
                "don't",
                "dont",
            ]
        ):
            self.pending_invite = None
            return "Okay, I've cancelled that."

        if waiting_for == "event":
            # User should provide which meeting
            event = self.find_event_by_match(user_input)
            if event:
                # Check if we already have an email stored from the initial request
                stored_email = self.pending_invite.get("email")
                if stored_email:
                    # We have both - go straight to confirm
                    email_spoken = stored_email.replace("@", " at ").replace(
                        ".", " dot "
                    )
                    self.pending_invite = {
                        "event": event,
                        "email": stored_email,
                        "waiting_for": "confirm",
                    }
                    clean_title = self.clean_title_for_speech(event["title"])
                    return f"I'll add {email_spoken} to '{clean_title}'. Sound good?"
                else:
                    # Need to get email
                    self.pending_invite = {"event": event, "waiting_for": "email"}
                    clean_title = self.clean_title_for_speech(event["title"])
                    return f"Got it, '{clean_title}'. Who would you like me to invite? Just give me their email."
            else:
                return f"I couldn't find a meeting matching '{user_input}'. Could you try again?"

        elif waiting_for == "email":
            # User should provide email address
            event = self.pending_invite.get("event")

            # Try to extract email from input
            email = self.extract_email_from_text(user_input)

            if email:
                # Store email and ask for confirmation
                email_spoken = email.replace("@", " at ").replace(".", " dot ")
                self.pending_invite = {
                    "event": event,
                    "email": email,
                    "waiting_for": "confirm",
                }
                clean_title = self.clean_title_for_speech(event["title"])
                return f"Just to confirm, I'll add {email_spoken} to '{clean_title}'. Sound good?"
            else:
                return "I couldn't catch the email address. Could you say it again? Something like 'jane at example dot com'."

        elif waiting_for == "confirm":
            # User should confirm or deny
            event = self.pending_invite.get("event")
            email = self.pending_invite.get("email")
            clean_title = self.clean_title_for_speech(event["title"])

            # Check for confirmation
            if any(
                phrase in lower
                for phrase in [
                    "yes",
                    "yeah",
                    "yep",
                    "sure",
                    "okay",
                    "ok",
                    "correct",
                    "right",
                    "do it",
                    "go ahead",
                    "sounds good",
                    "that's right",
                    "thats right",
                ]
            ):
                self.pending_invite = None
                result, error = self.add_attendee_to_event(event, email)
                if error:
                    return f"Couldn't add them: {error}"

                email_spoken = email.replace("@", " at ").replace(".", " dot ")
                return f"Done! I've added {email_spoken} to '{clean_title}'."

            # Check if they're correcting the email
            corrected_email = self.extract_email_from_text(user_input)
            if corrected_email and corrected_email != email:
                # They provided a different email - confirm that one instead
                email_spoken = corrected_email.replace("@", " at ").replace(
                    ".", " dot "
                )
                self.pending_invite = {
                    "event": event,
                    "email": corrected_email,
                    "waiting_for": "confirm",
                }
                return f"Got it, I'll add {email_spoken} instead. Sound good?"

            # Unclear response - ask again
            email_spoken = email.replace("@", " at ").replace(".", " dot ")
            return f"Should I add {email_spoken} to the meeting? Say yes to confirm or no to cancel."

        return None

    async def handle_pending_create(self, user_input: str):
        """Handle follow-up to a pending create action."""
        if not self.pending_create:
            return None

        waiting_for = self.pending_create.get("waiting_for")

        # Check for cancel
        lower = user_input.lower().strip()
        if any(
            phrase in lower
            for phrase in ["never mind", "nevermind", "cancel", "forget it"]
        ):
            self.pending_create = None
            return "Okay, I've cancelled that."

        if waiting_for == "title":
            # Use LLM to extract just the meeting name from whatever the user said
            # This handles all the variations without hardcoding phrases
            title = self.extract_meeting_title(user_input)

            if not title or len(title) < 2:
                return "I didn't catch that. What should I call this meeting?"

            self.pending_create = {
                "title": title,
                "duration": self.pending_create.get("duration", 60),
                "waiting_for": "time",
            }
            self.log(f"Create flow: got title '{title}', asking for time")
            return f"Got it, '{title}'. What time should it be?"

        elif waiting_for == "time":
            title = self.pending_create.get("title")
            duration = self.pending_create.get("duration", 60)

            # Use LLM to extract time from user input
            time_str = self.extract_time_from_input(user_input)

            self.log(f"Create flow: got time '{time_str}' for '{title}'")

            try:
                start_time = self.parse_time_to_datetime(time_str)
                if not start_time:
                    return (
                        "I couldn't understand that time. Could you give me something "
                        "like '4 PM' or '3:30'?"
                    )

                self.pending_create = None

                result, error = self.create_event(
                    title, start_time.isoformat(), duration
                )
                if error:
                    return f"Couldn't create the event: {error}"

                formatted_time = (
                    start_time.strftime("%-I:%M %p").lower().replace(":00", "")
                )
                return f"Done! I've created '{title}' at {formatted_time}."
            except Exception as e:
                self.log_err(f"Create event error: {e}")
                return f"Had trouble creating that event: {e}"

        return None

    def extract_meeting_title(self, user_input: str) -> str:
        """Use LLM to extract just the meeting title from user input."""
        prompt = f"""Extract ONLY the meeting/event title from this user input.
The user was just asked "What should I call this meeting?" so they're providing a name.

User said: "{user_input}"

Rules:
- Return ONLY the meeting title, nothing else
- Remove any preamble like "I want to create a meeting called..." or "Let's call it..."
- Remove filler words like "um", "uh", "like"
- If the input contains accumulated speech (multiple sentences), extract just the title portion
- Keep it concise - just the actual name/title
- If you can't identify a clear title, return the most likely candidate

Examples:
- "I think I need to add a new event. Meeting with Jesse." → "Meeting with Jesse"
- "Call it Team Standup" → "Team Standup"
- "Um, meeting with Carlos" → "Meeting with Carlos"
- "I wanna schedule a call. Doctor appointment." → "Doctor appointment"
- "Jesse sync" → "Jesse sync"

Return ONLY the title, no quotes, no explanation:"""

        try:
            response = self.capability_worker.text_to_text_response(prompt)
            title = response.strip().strip("\"'").strip()
            self.log(f"LLM extracted title: '{user_input[:40]}...' -> '{title}'")
            return title
        except Exception as e:
            self.log_err(f"Title extraction error: {e}")
            # Fallback: just clean up the input directly
            return user_input.strip().rstrip(".")

    def extract_time_from_input(self, user_input: str) -> str:
        """Extract time from user input, handling accumulated transcription."""
        # First try direct parsing
        clean = user_input.strip().rstrip(".")

        # If it looks simple enough, just return it
        if len(clean.split()) <= 4:
            return clean

        # Otherwise use LLM to extract just the time part
        prompt = f"""Extract ONLY the time from this user input.
The user was just asked "What time should the meeting be?"

User said: "{user_input}"

Rules:
- Return ONLY the time portion (e.g., "9pm", "3:30 PM", "tomorrow at 2")
- Remove any preamble or extra words
- If multiple times mentioned, use the most recent/relevant one

Return ONLY the time, no explanation:"""

        try:
            response = self.capability_worker.text_to_text_response(prompt)
            time_str = response.strip().strip("\"'").strip()
            self.log(f"LLM extracted time: '{user_input[:40]}...' -> '{time_str}'")
            return time_str
        except Exception as e:
            self.log_err(f"Time extraction error: {e}")
            return clean

    async def handle_pending_action(self, user_input: str):
        """Handle follow-up to a pending calendar action (like cascade confirmation or event selection)."""
        if not self.pending_calendar_action:
            return None

        lower = user_input.lower()
        action = self.pending_calendar_action
        action_type = action.get("type", "")

        # Check for cancel
        cancel = any(
            phrase in lower
            for phrase in ["never mind", "nevermind", "cancel", "forget it", "no don't"]
        )

        if cancel:
            self.pending_calendar_action = None
            return "Okay, I've cancelled that."

        # =====================================================================
        # PENDING EVENT SELECTION (user needs to specify which event)
        # =====================================================================
        if action.get("waiting_for") == "event":
            # User should be specifying which event they want to modify
            event = self.find_event_by_match(user_input)

            if not event:
                # List their events to help
                calendar = self.context.get("calendar", [])
                if calendar and len(calendar) <= 3:
                    event_names = [
                        self.clean_title_for_speech(e.get("title", "Untitled"))
                        for e in calendar
                    ]
                    return f"I couldn't find that one. You have: {', '.join(event_names)}. Which one?"
                return "I couldn't find that event. Could you try again?"

            intent = action.get("intent")
            change_mins = action.get("change_mins")
            new_duration = action.get("new_duration")

            self.log(f"User selected event '{event['title']}' for {intent}")

            if intent == "shorten":
                if new_duration:
                    self.pending_calendar_action = None
                    result, error = self.shorten_event(event, new_duration)
                    if error:
                        return f"Couldn't shorten the event: {error}"
                    return f"Done! '{event['title']}' is now {new_duration} minutes."
                else:
                    # Ask how long they want it
                    self.pending_calendar_action = {
                        "type": "shorten_pending_duration",
                        "event": event,
                        "waiting_for": "duration",
                    }
                    return f"Got it, '{event['title']}'. How long should it be?"

            elif intent == "extend":
                if new_duration:
                    self.pending_calendar_action = None
                    result, error = self.extend_event(event, new_duration)
                    if error:
                        return f"Couldn't extend the event: {error}"
                    return f"Done! '{event['title']}' is now {new_duration} minutes."
                else:
                    self.pending_calendar_action = {
                        "type": "extend_pending_duration",
                        "event": event,
                        "waiting_for": "duration",
                    }
                    return f"Got it, '{event['title']}'. How long should it be?"

            elif intent == "reschedule":
                if change_mins:
                    self.pending_calendar_action = None
                    result, error = self.reschedule_event(event, change_mins)
                    if error:
                        return f"Couldn't reschedule: {error}"
                    direction = "up" if change_mins < 0 else "back"
                    return f"Done! I've moved '{event['title']}' {direction} {abs(change_mins)} minutes."
                else:
                    self.pending_calendar_action = {
                        "type": "reschedule_pending_time",
                        "event": event,
                        "waiting_for": "time_change",
                    }
                    return f"Got it, '{event['title']}'. How much should I move it?"

            elif intent == "cancel":
                # Ask for confirmation before cancelling
                clean_title = self.clean_title_for_speech(event["title"])
                self.pending_calendar_action = {
                    "type": "cancel_confirm",
                    "event": event,
                    "waiting_for": "confirm",
                }
                return f"Cancel '{clean_title}'? Say yes to confirm."

            # Fallback
            self.pending_calendar_action = None
            return (
                f"I've selected '{event['title']}'. What would you like to do with it?"
            )

        # =====================================================================
        # PENDING DURATION (user needs to specify how long)
        # =====================================================================
        if action.get("waiting_for") == "duration":
            event = action.get("event")

            # Try to parse duration from input
            duration_mins = self.parse_duration_minutes(user_input)

            if not duration_mins:
                return "I didn't catch that. How many minutes should it be? Something like '30 minutes' or 'half an hour'."

            self.pending_calendar_action = None

            if "shorten" in action_type:
                result, error = self.shorten_event(event, duration_mins)
                if error:
                    return f"Couldn't shorten: {error}"
                return f"Done! '{event['title']}' is now {duration_mins} minutes."
            else:  # extend
                result, error = self.extend_event(event, duration_mins)
                if error:
                    return f"Couldn't extend: {error}"
                return f"Done! '{event['title']}' is now {duration_mins} minutes."

        # =====================================================================
        # PENDING TIME CHANGE (user needs to specify how much to move)
        # =====================================================================
        if action.get("waiting_for") == "time_change":
            event = action.get("event")
            lower = user_input.lower()

            # First, check if user specified a TARGET TIME (e.g., "9PM", "to 9 o'clock")
            # This is different from a duration like "30 minutes"
            target_time = self.parse_time_to_datetime(user_input)

            if target_time:
                # User wants to move to a specific time
                try:
                    old_start = datetime.datetime.fromisoformat(
                        event["start"].replace("Z", "+00:00")
                    )

                    # Make target_time timezone-aware if it isn't
                    if target_time.tzinfo is None:
                        from zoneinfo import ZoneInfo

                        tz = ZoneInfo(self.calendar_timezone)
                        target_time = target_time.replace(tzinfo=tz)

                    # Calculate how many minutes to move
                    delta = target_time - old_start
                    change_mins = int(delta.total_seconds() / 60)

                    self.log(
                        f"Reschedule to target time: {target_time.strftime('%I:%M %p')} (delta: {change_mins}m)"
                    )

                    if change_mins == 0:
                        self.pending_calendar_action = None
                        return f"'{self.clean_title_for_speech(event['title'])}' is already at that time."

                    # Check for conflicts
                    old_end = datetime.datetime.fromisoformat(
                        event["end"].replace("Z", "+00:00")
                    )
                    duration = old_end - old_start
                    new_end = target_time + duration

                    conflicts = self.detect_conflicts(
                        event["id"], target_time.isoformat(), new_end.isoformat()
                    )

                    if conflicts:
                        conflict_names = [c["title"] for c in conflicts]
                        self.pending_calendar_action = {
                            "type": "reschedule_with_conflict",
                            "event": event,
                            "change_mins": change_mins,
                            "conflicts": conflicts,
                        }
                        return f"Moving '{event['title']}' to {target_time.strftime('%-I:%M %p').lower()} would overlap with {', '.join(conflict_names)}. Want me to adjust those too?"

                    self.pending_calendar_action = None
                    result, error = self.reschedule_event(event, change_mins)
                    if error:
                        return f"Couldn't reschedule: {error}"

                    clean_title = self.clean_title_for_speech(event["title"])
                    formatted_time = (
                        target_time.strftime("%-I:%M %p").lower().replace(":00", "")
                    )
                    return f"Done! I've moved '{clean_title}' to {formatted_time}."

                except Exception as e:
                    self.log_err(f"Target time reschedule error: {e}")

            # Fall back to parsing as a duration (e.g., "30 minutes", "an hour")
            change_mins = self.parse_duration_minutes(user_input)

            # Check for direction words
            move_earlier = any(
                w in lower for w in ["earlier", "up", "forward", "sooner", "before"]
            )
            move_later = any(w in lower for w in ["later", "back", "after", "push"])

            if not change_mins:
                return "I didn't catch that. You can say a time like '9 PM' or a duration like '30 minutes'."

            # If they said "earlier" or "up", make it negative
            if move_earlier and not move_later:
                change_mins = -abs(change_mins)
            else:
                # Default to pushing back (positive)
                change_mins = abs(change_mins)

            self.pending_calendar_action = None

            # Check for conflicts
            try:
                old_start = datetime.datetime.fromisoformat(
                    event["start"].replace("Z", "+00:00")
                )
                old_end = datetime.datetime.fromisoformat(
                    event["end"].replace("Z", "+00:00")
                )
                new_start = old_start + datetime.timedelta(minutes=change_mins)
                new_end = old_end + datetime.timedelta(minutes=change_mins)

                conflicts = self.detect_conflicts(
                    event["id"], new_start.isoformat(), new_end.isoformat()
                )

                if conflicts:
                    conflict_names = [c["title"] for c in conflicts]
                    self.pending_calendar_action = {
                        "type": "reschedule_with_conflict",
                        "event": event,
                        "change_mins": change_mins,
                        "conflicts": conflicts,
                    }
                    direction = "up" if change_mins < 0 else "back"
                    return f"Moving '{event['title']}' {direction} {abs(change_mins)} minutes would overlap with {', '.join(conflict_names)}. Want me to adjust those too?"
            except Exception as e:
                self.log_err(f"Conflict check error: {e}")

            result, error = self.reschedule_event(event, change_mins)
            if error:
                return f"Couldn't reschedule: {error}"

            clean_title = self.clean_title_for_speech(event["title"])
            if change_mins < 0:
                return (
                    f"Done! I've moved '{clean_title}' up {abs(change_mins)} minutes."
                )
            else:
                return f"Done! I've pushed '{clean_title}' back {change_mins} minutes."

        # =====================================================================
        # RESCHEDULE WITH CONFLICT (existing cascade handling)
        # =====================================================================
        cascade_yes = any(
            phrase in lower
            for phrase in [
                "push them",
                "move them",
                "yes",
                "yeah",
                "yep",
                "sure",
                "okay",
                "ok",
                "push everything",
                "move everything",
                "push all",
                "move all",
                "cascade",
                "all of them",
                "do it",
                "both",
                "adjust them",
                "adjust those",
                "go ahead",
                "sounds good",
                "that works",
            ]
        )

        shorten_pref = any(
            phrase in lower
            for phrase in [
                "shorten",
                "shorter",
                "cut it",
                "make it shorter",
                "just shorten",
                "end earlier",
                "end early",
            ]
        )

        if action_type == "reschedule_with_conflict":
            event = action["event"]
            change_mins = action["change_mins"]
            conflicts = action["conflicts"]

            if shorten_pref:
                try:
                    event_start = datetime.datetime.fromisoformat(
                        event["start"].replace("Z", "+00:00")
                    )
                    next_event = conflicts[0]
                    next_start = datetime.datetime.fromisoformat(
                        next_event["start"].replace("Z", "+00:00")
                    )

                    available_mins = int(
                        (next_start - event_start).total_seconds() / 60
                    )

                    result, error = self.shorten_event(event, available_mins)
                    self.pending_calendar_action = None

                    if error:
                        return f"Couldn't shorten: {error}"
                    return f"Done! I've shortened '{event['title']}' to {available_mins} minutes so it ends before your next meeting."
                except Exception as e:
                    self.log_err(f"Shorten calc error: {e}")
                    self.pending_calendar_action = None
                    return (
                        "Had trouble calculating the new duration. Want to try again?"
                    )

            if cascade_yes:
                results, error = self.cascade_reschedule(event, change_mins)
                self.pending_calendar_action = None

                if error:
                    return f"Had some trouble: {error}"

                moved_count = len([r for r in results if "Moved" in r])
                direction = "up" if change_mins < 0 else "back"
                return f"Done! I've moved {moved_count} events {direction} by {abs(change_mins)} minutes."

        # =====================================================================
        # CANCEL CONFIRMATION (user needs to confirm cancellation)
        # =====================================================================
        if action_type == "cancel_confirm" and action.get("waiting_for") == "confirm":
            event = action.get("event")

            # Check for yes/confirmation
            confirm_yes = any(
                phrase in lower
                for phrase in [
                    "yes",
                    "yeah",
                    "yep",
                    "sure",
                    "okay",
                    "ok",
                    "do it",
                    "go ahead",
                    "confirm",
                    "that's right",
                    "correct",
                ]
            )

            if confirm_yes:
                self.pending_calendar_action = None
                result, error = self.cancel_event(event)
                if error:
                    return f"Couldn't cancel: {error}"
                clean_title = self.clean_title_for_speech(event["title"])
                return f"Done! I've cancelled '{clean_title}'."

            # Check for no
            deny = any(
                phrase in lower for phrase in ["no", "nope", "don't", "dont", "stop"]
            )

            if deny:
                self.pending_calendar_action = None
                return "Okay, I won't cancel it."

            # Unclear - ask again
            clean_title = self.clean_title_for_speech(event["title"])
            return f"Should I cancel '{clean_title}'? Say yes or no."

        return None

    # =========================================================================
    # LLM HELPERS
    # =========================================================================

    def get_system_prompt(self):
        """Build the system prompt with user context injected."""
        if self.has_in_person_meeting():
            weather_line = f"- Weather: {self.geo_context.get('weather_temp', 'unknown')} degrees, {self.geo_context.get('weather_condition', 'unknown')}"
        else:
            weather_line = ""

        return HUB_SYSTEM_PROMPT.format(
            user_name=self.user_name if self.user_name else "the user",
            city=self.geo_context.get("city", "your area"),
            region=self.geo_context.get("region", ""),
            current_time=self.geo_context.get("current_time", ""),
            time_bucket=self.geo_context.get("time_bucket", ""),
            day_of_week=self.geo_context.get("day_of_week", ""),
            current_date=self.geo_context.get("current_date", ""),
            weather_line=weather_line,
        )

    def build_context_message(self):
        """Package all fetched data into a single context message for the LLM."""
        cal_text = "No upcoming events today."
        if self.context.get("calendar"):
            lines = []
            for e in self.context["calendar"]:
                if e.get("in_progress"):
                    mins = e.get("mins_remaining", 0)
                    if mins > 60:
                        time_left = f"{mins // 60}h {mins % 60}m"
                    else:
                        time_left = f"{mins}m"
                    line = f"- [IN PROGRESS - {time_left} remaining] {e['title']} (started {e['start']}, ends {e['end']})"
                else:
                    mins_until = e.get("mins_until_start")
                    if mins_until is not None and mins_until <= 30:
                        line = (
                            f"- [STARTING IN {mins_until}m] {e['start']}: {e['title']}"
                        )
                    else:
                        line = f"- {e['start']}: {e['title']}"

                if e["attendees"]:
                    line += f" (with {', '.join(e['attendees'][:5])})"
                if e["location"]:
                    line += f" at {e['location']}"
                lines.append(line)
            cal_text = "\n".join(lines)

        since_text = ""
        if self.last_session_timestamp:
            since_text = f"\nLast Hub session: {self.last_session_timestamp}\n"

        context_block = (
            f"=== CALENDAR (upcoming today) ===\n{cal_text}\n"
            f"{since_text}"
            f"\n=== END OF CONTEXT ===\n"
            f"Use this data to answer the user's questions naturally. "
            f"Don't read it out literally — synthesize and summarize."
        )

        return {"role": "user", "content": f"[SYSTEM CONTEXT]\n{context_block}"}

    def build_history(self):
        """Build the full history list for an LLM call."""
        history = []
        history.append(self.build_context_message())
        history.append(
            {
                "role": "assistant",
                "content": "Got it, I have your latest data. Ready to help.",
            }
        )
        for turn in self.session_history:
            history.append(turn)
        return history

    def ask_llm(self, user_input):
        """Send a query to the LLM with full context and history."""
        history = self.build_history()
        response = self.capability_worker.text_to_text_response(
            prompt_text=user_input,
            history=history,
            system_prompt=self.get_system_prompt(),
        )
        return response

    # =========================================================================
    # BOOT SEQUENCE
    # =========================================================================

    async def collect_context(self):
        """Fetch all data sources (calendar, profile, geo) without speaking."""
        self.collect_geo_context()
        self.fetch_user_profile()
        self.context["calendar"] = self.fetch_upcoming_today()
        self.context["boot_time"] = datetime.datetime.now().isoformat()
        self.last_session_timestamp = self.find_last_session_signature()

    async def boot_full(self):
        """Full session boot: filler → fetch → briefing."""
        time_bucket = self.geo_context.get("time_bucket", "morning")
        greeting = random.choice(TIME_GREETINGS.get(time_bucket, ["Hey"]))
        filler = random.choice(FILLER_LINES.get(time_bucket, ["One sec."]))

        # Speak filler while fetching
        await self.capability_worker.speak(filler)

        # Data already collected in collect_context()

        # Generate briefing
        event_count = len(self.context.get("calendar", []))
        weather_note = self.build_weather_remark()

        since_note = ""
        if self.last_session_timestamp:
            try:
                ts = datetime.datetime.fromisoformat(
                    self.last_session_timestamp.replace("Z", "+00:00")
                )
                since_note = f"I last checked in around {ts.strftime('%I:%M %p').lstrip('0').lower()}. "
            except (TypeError, ValueError):
                pass

        name_part = self.user_name if self.user_name else ""

        briefing_prompt = (
            f"{greeting} {name_part}. Give a quick spoken briefing of my upcoming schedule. "
            f"I have {event_count} events remaining today. "
            f"{weather_note} {since_note}"
            f"Be concise and conversational. If nothing's on the calendar, say so briefly."
        )

        briefing = self.ask_llm(briefing_prompt)
        self.log(f"Briefing: {briefing[:200]}")

        self.session_history.append({"role": "user", "content": briefing_prompt})
        self.session_history.append({"role": "assistant", "content": briefing})

        await self.capability_worker.speak(briefing)

    async def handle_quick_intent(self):
        """Handle the initial quick intent from trigger context."""
        intent = self.trigger_data.get("intent", "read_today")
        details = self.trigger_data.get("details", {})
        trigger = self.trigger_data.get("trigger", "")
        no_trigger = self.trigger_data.get("no_trigger", False)

        self.log(f"Handling quick intent: {intent} | details: {details}")

        # =====================================================================
        # READ INTENTS - Just answer the question
        # =====================================================================
        if intent in ["read_today", "read_specific"]:
            events = self.context.get("calendar", [])
            event_count = len(events)

            # If we don't have a trigger, just give a brief calendar summary
            if not trigger or no_trigger:
                if event_count == 0:
                    response = "You don't have any more events today."
                else:
                    # Build a quick summary
                    prompt = (
                        f"Give a very brief spoken summary of the user's remaining schedule today. "
                        f"They have {event_count} events. Be conversational, 1-2 sentences max."
                    )
                    response = self.ask_llm(prompt)
            else:
                # Use LLM to answer their specific question from context
                prompt = (
                    f"The user asked: '{trigger}'\n\n"
                    f"Answer their specific question based on the calendar context. "
                    f"Be concise - 1-2 sentences. Don't give a full briefing unless they asked for one."
                )
                response = self.ask_llm(prompt)

            self.session_history.append(
                {"role": "user", "content": trigger or "calendar check"}
            )
            self.session_history.append({"role": "assistant", "content": response})
            await self.capability_worker.speak(response)
            return

        # =====================================================================
        # CREATE INTENT
        # =====================================================================
        if intent == "create":
            title = details.get("event_name") or details.get("person")
            time_str = details.get("time")
            duration = details.get("duration") or 60

            # If we have a person but no title, make title "Meeting with [person]"
            if details.get("person") and not details.get("event_name"):
                title = f"Meeting with {details['person']}"

            if not title:
                self.pending_create = {"waiting_for": "title"}
                await self.capability_worker.speak("What should I call this meeting?")
                return

            if not time_str:
                self.pending_create = {
                    "title": title,
                    "duration": duration,
                    "waiting_for": "time",
                }
                await self.capability_worker.speak(
                    f"Got it, '{title}'. What time should it be?"
                )
                return

            # We have everything - create the event
            try:
                start_time = self.parse_time_to_datetime(time_str)
                if not start_time:
                    self.pending_create = {
                        "title": title,
                        "duration": duration,
                        "waiting_for": "time",
                    }
                    await self.capability_worker.speak(
                        f"I couldn't catch the time. When should '{title}' be?"
                    )
                    return

                result, error = self.create_event(
                    title, start_time.isoformat(), duration
                )
                if error:
                    await self.capability_worker.speak(
                        f"Couldn't create the event: {error}"
                    )
                else:
                    formatted_time = (
                        start_time.strftime("%-I:%M %p")
                        .lower()
                        .replace(":00", "")
                        .replace(" 0", " ")
                    )
                    await self.capability_worker.speak(
                        f"Done! I've created '{title}' at {formatted_time}."
                    )
                    self.context["calendar"] = self.fetch_upcoming_today()
            except Exception as e:
                self.log_err(f"Create error: {e}")
                await self.capability_worker.speak(
                    "Had trouble creating that event. Could you try again?"
                )
            return

        # =====================================================================
        # MODIFY INTENT (reschedule, shorten, extend)
        # =====================================================================
        if intent == "modify":
            # Re-classify with full calendar intent to get specifics
            intent_data = self.classify_calendar_intent(trigger)
            if intent_data.get("intent") != "none":
                response = await self.handle_calendar_write(intent_data, trigger)
                if response:
                    self.session_history.append({"role": "user", "content": trigger})
                    self.session_history.append(
                        {"role": "assistant", "content": response}
                    )
                    await self.capability_worker.speak(response)
                    self.context["calendar"] = self.fetch_upcoming_today()
                    return

            # Couldn't parse - ask for clarification
            await self.capability_worker.speak(
                "Which event do you want to change, and how?"
            )
            return

        # =====================================================================
        # CANCEL INTENT
        # =====================================================================
        if intent == "cancel":
            event_match = (
                details.get("event_name")
                or details.get("person")
                or details.get("time")
            )
            self.log(f"Cancel intent: event_match='{event_match}'")

            if event_match:
                event = self.find_event_by_match(str(event_match))
                if event:
                    # Ask for confirmation before cancelling
                    clean_title = self.clean_title_for_speech(event["title"])
                    self.pending_calendar_action = {
                        "type": "cancel_confirm",
                        "event": event,
                        "waiting_for": "confirm",
                    }
                    self.log(
                        f"Set pending_calendar_action for confirm: {event['title']}"
                    )
                    await self.capability_worker.speak(
                        f"Cancel '{clean_title}'? Say yes to confirm."
                    )
                    return

            # No event found or no match - set up pending state to get event selection
            self.pending_calendar_action = {
                "type": "cancel_pending_event",
                "intent": "cancel",
                "waiting_for": "event",
            }
            self.log('Set pending_calendar_action for event selection')

            # List their events
            calendar = self.context.get("calendar", [])
            self.log(f"Calendar has {len(calendar)} events for cancel prompt")
            if calendar and len(calendar) <= 5:
                event_names = [
                    self.clean_title_for_speech(e.get("title", "Untitled"))
                    for e in calendar
                ]
                await self.capability_worker.speak(
                    f"Which event do you want to cancel? You have: {', '.join(event_names)}."
                )
            else:
                await self.capability_worker.speak("Which event do you want to cancel?")
            return

        # =====================================================================
        # INVITE INTENT
        # =====================================================================
        if intent == "invite":
            email = details.get("email")
            event_match = details.get("event_name") or details.get("person")

            # Find the event
            event = None
            if event_match:
                event = self.find_event_by_match(str(event_match))

            # If no specific event mentioned and user has multiple events, ask which one
            calendar = self.context.get("calendar", [])
            if not event and len(calendar) > 1:
                self.pending_invite = {"waiting_for": "event", "email": email}
                event_names = [
                    self.clean_title_for_speech(e.get("title", "Untitled"))
                    for e in calendar[:5]
                ]
                await self.capability_worker.speak(
                    f"Which meeting? You have: {', '.join(event_names)}."
                )
                return

            # If user only has one event, use that one
            if not event and len(calendar) == 1:
                event = calendar[0]

            # Still no event? Ask for clarification
            if not event:
                self.pending_invite = {"waiting_for": "event", "email": email}
                await self.capability_worker.speak(
                    "Which meeting should I add them to?"
                )
                return

            if email:
                email_spoken = email.replace("@", " at ").replace(".", " dot ")
                self.pending_invite = {
                    "event": event,
                    "email": email,
                    "waiting_for": "confirm",
                }
                clean_title = self.clean_title_for_speech(event["title"])
                await self.capability_worker.speak(
                    f"Just to confirm, I'll add {email_spoken} to '{clean_title}'. Sound good?"
                )
            else:
                self.pending_invite = {"event": event, "waiting_for": "email"}
                clean_title = self.clean_title_for_speech(event["title"])
                await self.capability_worker.speak(
                    f"Who would you like me to add to '{clean_title}'? Just give me their email."
                )
            return

        # =====================================================================
        # ASK_USER INTENT - Couldn't get trigger, ask what they need
        # =====================================================================
        if intent == "ask_user":
            await self.capability_worker.speak("Hey, what can I help you with?")

            # Wait for their response
            user_input = await self.user_response_with_timeout(15.0)

            if not user_input:
                # No response, just exit
                return

            # Now classify their actual request
            self.log(f"User clarified: {user_input}")

            # Check for exit words
            lower = user_input.lower().strip()
            if any(w in lower for w in EXIT_WORDS):
                return

            # Re-classify with the actual input
            intent_data = self.classify_calendar_intent(user_input)
            cal_intent = intent_data.get("intent", "none")

            if cal_intent == "create":
                # Handle create
                title = intent_data.get("title")
                time_str = intent_data.get("time")
                duration = intent_data.get("duration_minutes", 60)

                if not title:
                    self.pending_create = {"waiting_for": "title"}
                    await self.capability_worker.speak(
                        "What should I call this meeting?"
                    )
                elif not time_str:
                    self.pending_create = {
                        "title": title,
                        "duration": duration,
                        "waiting_for": "time",
                    }
                    await self.capability_worker.speak(f"Got it, '{title}'. What time?")
                else:
                    # We have everything
                    start_time = self.parse_time_to_datetime(time_str)
                    if start_time:
                        result, error = self.create_event(
                            title, start_time.isoformat(), duration
                        )
                        if error:
                            await self.capability_worker.speak(
                                f"Couldn't create that: {error}"
                            )
                        else:
                            formatted = (
                                start_time.strftime("%-I:%M %p")
                                .lower()
                                .replace(":00", "")
                            )
                            await self.capability_worker.speak(
                                f"Done! Created '{title}' at {formatted}."
                            )
                            self.context["calendar"] = self.fetch_upcoming_today()
                    else:
                        self.pending_create = {
                            "title": title,
                            "duration": duration,
                            "waiting_for": "time",
                        }
                        await self.capability_worker.speak(
                            f"Couldn't catch the time. When should '{title}' be?"
                        )
                return

            elif cal_intent in ["reschedule", "shorten", "extend", "cancel"]:
                # Handle modification
                response = await self.handle_calendar_write(intent_data, user_input)
                if response:
                    await self.capability_worker.speak(response)
                    self.context["calendar"] = self.fetch_upcoming_today()
                return

            elif cal_intent == "invite":
                # Handle invite
                event = self.find_most_recent_event()
                if event:
                    self.pending_invite = {"event": event, "waiting_for": "email"}
                    await self.capability_worker.speak(
                        f"Who should I add to '{event['title']}'? Just give me their email."
                    )
                else:
                    await self.capability_worker.speak(
                        "Which meeting should I add someone to?"
                    )
                return

            else:
                # Treat as a calendar read question
                events = self.context.get("calendar", [])
                if events:
                    prompt = (
                        f"The user asked about their calendar: '{user_input}'\n"
                        f"Answer based on their schedule. Be concise - 1-2 sentences."
                    )
                    response = self.ask_llm(prompt)
                    await self.capability_worker.speak(response)
                else:
                    await self.capability_worker.speak(
                        "You don't have any more events today."
                    )
                return

        # =====================================================================
        # FALLBACK - shouldn't hit this in quick mode
        # =====================================================================
        await self.capability_worker.speak(
            "I'm not sure what you need. Could you say that again?"
        )

    # =========================================================================
    # SESSION LOOPS
    # =========================================================================

    async def quick_answer_loop(self):
        """Quick mode follow-up loop: one chance for follow-up, then exit."""

        # If there's a pending state, don't say the follow-up message - just wait for input
        has_pending = (
            self.pending_create or self.pending_invite or self.pending_calendar_action
        )
        self.log(
            f"Quick loop: has_pending={has_pending} (create={bool(self.pending_create)}, invite={bool(self.pending_invite)}, action={bool(self.pending_calendar_action)})"
        )

        if not has_pending:
            # No pending state - ask if there's anything else
            await self.capability_worker.speak(
                "Let me know if you have any other questions about your calendar."
            )

        # Use longer timeout when waiting for pending input (user needs time to respond)
        # Shorter timeout for "any other questions" check
        timeout = 25.0 if has_pending else 15.0

        # Wait for response with appropriate timeout
        user_input = await self.user_response_with_timeout(timeout)

        # No response or timeout = exit
        if not user_input or len(user_input.strip()) < 3:
            self.log("Quick mode: no follow-up or timeout, exiting")
            return

        # User said something - check if it's an exit
        lower = user_input.lower().strip()
        if any(w in lower for w in EXIT_WORDS):
            self.log("Quick mode: exit word detected")
            return

        # Check for noise/non-responses (only if no pending state expecting real input)
        if not has_pending:
            noise_words = [
                "um",
                "uh",
                "hmm",
                "okay",
                "ok",
                "alright",
                "sure",
                "thanks",
                "thank you",
                "cool",
                "great",
            ]
            if lower in noise_words or all(w in noise_words for w in lower.split()):
                self.log("Quick mode: noise response, exiting")
                return

        # User has a follow-up question - process it
        self.log(f"Quick mode follow-up: {user_input}")

        # Check pending states first
        if self.pending_invite:
            response = await self.handle_pending_invite(user_input)
            if response:
                await self.capability_worker.speak(response)
                if "added" in response.lower():
                    self.context["calendar"] = self.fetch_upcoming_today()
                # Ask again
                await self.quick_answer_loop()
                return

        if self.pending_create:
            response = await self.handle_pending_create(user_input)
            if response:
                await self.capability_worker.speak(response)
                if "created" in response.lower():
                    self.context["calendar"] = self.fetch_upcoming_today()
                await self.quick_answer_loop()
                return

        if self.pending_calendar_action:
            response = await self.handle_pending_action(user_input)
            if response:
                await self.capability_worker.speak(response)
                self.context["calendar"] = self.fetch_upcoming_today()
                await self.quick_answer_loop()
                return

        # Check for calendar write intent
        intent_data = self.classify_calendar_intent(user_input)
        if intent_data.get("intent") != "none":
            response = await self.handle_calendar_write(intent_data, user_input)
            if response:
                await self.capability_worker.speak(response)
                self.context["calendar"] = self.fetch_upcoming_today()
                await self.quick_answer_loop()
                return

        # Normal LLM response
        response = self.ask_llm(user_input)
        self.session_history.append({"role": "user", "content": user_input})
        self.session_history.append({"role": "assistant", "content": response})
        await self.capability_worker.speak(response)

        # Recurse for another follow-up chance
        await self.quick_answer_loop()

    async def session_loop(self):
        """Full session Q&A loop — user asks questions, Hub answers from context."""
        idle_count = 0

        while True:
            user_input = await self.user_response_with_timeout(15.0)

            if not user_input:
                idle_count += 1
                if idle_count >= 2:
                    await self.capability_worker.speak(
                        "I'm still here if you need anything. Otherwise I'll sign off."
                    )
                    final = await self.user_response_with_timeout(15.0)
                    if not final or any(w in (final or "").lower() for w in EXIT_WORDS):
                        break
                    else:
                        user_input = final
                        idle_count = 0
                else:
                    continue

            idle_count = 0

            lower = user_input.lower().strip()
            if any(w in lower for w in EXIT_WORDS):
                response = self.ask_llm(
                    f"The user said '{user_input}' and wants to end the session. "
                    f"Give a brief, friendly sign-off."
                )
                await self.capability_worker.speak(response)
                break

            self.log(f"User: {user_input}")

            # Check for pending invite first (multi-turn attendee addition)
            if self.pending_invite:
                self.log(
                    f"Pending invite: waiting for {self.pending_invite.get('waiting_for')}"
                )
                invite_response = await self.handle_pending_invite(user_input)
                if invite_response:
                    self.log(f"Invite response: {invite_response[:100]}")
                    self.session_history.append({"role": "user", "content": user_input})
                    self.session_history.append(
                        {"role": "assistant", "content": invite_response}
                    )
                    await self.capability_worker.speak(invite_response)

                    # Refresh calendar if attendee was added
                    if "added" in invite_response.lower():
                        self.context["calendar"] = self.fetch_upcoming_today()
                    continue

            # Check for pending create (multi-turn event creation)
            if self.pending_create:
                self.log(
                    f"Pending create: waiting for {self.pending_create.get('waiting_for')}"
                )
                create_response = await self.handle_pending_create(user_input)
                if create_response:
                    self.log(f"Create response: {create_response[:100]}")
                    self.session_history.append({"role": "user", "content": user_input})
                    self.session_history.append(
                        {"role": "assistant", "content": create_response}
                    )
                    await self.capability_worker.speak(create_response)

                    if "created" in create_response.lower():
                        self.context["calendar"] = self.fetch_upcoming_today()
                    continue

            # Check for pending calendar action (cascade confirmation, etc.)
            if self.pending_calendar_action:
                self.log(
                    f"Pending action exists: {self.pending_calendar_action.get('type', 'unknown')}"
                )
                pending_response = await self.handle_pending_action(user_input)
                if pending_response:
                    self.log(f"Pending action response: {pending_response[:100]}")
                    self.session_history.append({"role": "user", "content": user_input})
                    self.session_history.append(
                        {"role": "assistant", "content": pending_response}
                    )
                    await self.capability_worker.speak(pending_response)

                    self.context["calendar"] = self.fetch_upcoming_today()
                    continue
                else:
                    self.log("Pending action: user response not understood")
                    clarify = "I still have that calendar change pending. Want me to go ahead and adjust those events, or should I forget it?"
                    await self.capability_worker.speak(clarify)
                    continue

            # Check for calendar write intent
            intent_data = self.classify_calendar_intent(user_input)
            self.log(f"Intent: {intent_data.get('intent', 'none')}")

            if intent_data.get("intent") != "none":
                write_response = await self.handle_calendar_write(
                    intent_data, user_input
                )
                if write_response:
                    self.log(f"Calendar write response: {write_response[:100]}")
                    self.session_history.append({"role": "user", "content": user_input})
                    self.session_history.append(
                        {"role": "assistant", "content": write_response}
                    )
                    await self.capability_worker.speak(write_response)

                    self.context["calendar"] = self.fetch_upcoming_today()
                    continue

            # Normal LLM response for questions/chat
            response = self.ask_llm(user_input)
            self.log(f"Response: {response[:200]}")

            self.session_history.append({"role": "user", "content": user_input})
            self.session_history.append({"role": "assistant", "content": response})

            await self.capability_worker.speak(response)

    # =========================================================================
    # MAIN FLOW
    # =========================================================================

    async def run_hub(self):
        """Main entry point: determine mode → boot → handle → exit."""
        self.log("Starting Smart Hub session")

        try:
            # Quick acknowledgment so user knows we heard them
            await self.capability_worker.speak("One sec.")

            # Record the current history length BEFORE collecting context
            initial_history_len = 0
            try:
                initial_history = self.worker.agent_memory.full_message_history
                initial_history_len = len(initial_history) if initial_history else 0
                self.log(f"Initial history length: {initial_history_len}")
            except Exception:
                pass

            # 1. Collect data (calendar, profile, geo) - takes 2-3 seconds
            await self.collect_context()

            # 2. Wait for the current utterance to appear in history
            # Poll up to 3 seconds total, checking every 0.5s
            trigger_context = None
            for attempt in range(6):  # 6 attempts x 0.5s = 3 seconds max
                await self.worker.session_tasks.sleep(0.5)

                try:
                    current_history = self.worker.agent_memory.full_message_history
                    current_len = len(current_history) if current_history else 0

                    if current_len > initial_history_len:
                        self.log(
                            f"History updated: {initial_history_len} -> {current_len}"
                        )
                        trigger_context = self.get_trigger_context()
                        break
                except Exception:
                    pass

            # If history didn't update, get what we have anyway
            if trigger_context is None:
                self.log("History didn't update, using current state")
                trigger_context = self.get_trigger_context()

            # 3. Classify the trigger to determine mode
            self.trigger_data = self.classify_trigger_intent(trigger_context)
            self.log(f"Trigger data: {self.trigger_data}")
            # Preserve trigger text if not already set by classifier
            if not self.trigger_data.get("trigger"):
                self.trigger_data["trigger"] = trigger_context.get("trigger", "")
            self.session_mode = self.trigger_data.get("mode", "full")

            self.log(f"Session mode: {self.session_mode}")

            # 4. Handle based on mode
            if self.session_mode == "quick":
                # Quick mode: answer the specific question, then short follow-up loop
                await self.handle_quick_intent()

                # Check if we have pending actions (multi-turn flows)
                if (
                    self.pending_create
                    or self.pending_invite
                    or self.pending_calendar_action
                ):
                    # Need to complete the pending action first
                    await self.quick_answer_loop()
                else:
                    # Direct answer given, offer follow-up
                    await self.quick_answer_loop()
            else:
                # Full mode: full briefing then Q&A session
                await self.boot_full()
                await self.session_loop()

        except Exception as e:
            self.log_err(f"Fatal error: {e}")
            await self.capability_worker.speak("Something went wrong. Signing off.")

        # Exit with signature
        signature = self.stamp_session_signature()
        self.log(f"Session ended. Signature: {signature}")

        # Exit message - only for full mode
        if self.session_mode == "full":
            await self.capability_worker.speak(f"Signing off. {signature}")
        # Quick mode: silent exit - just hand back to personality

        self.capability_worker.resume_normal_flow()
