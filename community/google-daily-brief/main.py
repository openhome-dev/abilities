import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# --- API URLs ---
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
IP_GEOLOCATION_URL = "http://ip-api.com/json"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

# --- Fetch limits ---
LOCATION_TIMEOUT_SECONDS = 1.5
API_TIMEOUT_SECONDS = 2
CALENDAR_EVENT_LIMIT = 5

PREFS_FILE = "daily_brief_prefs.json"

TIMEZONE_LOCATION_FALLBACKS = {
    "America/New_York": {"lat": 40.7128, "lon": -74.0060, "city": "New York"},
    "America/Chicago": {"lat": 41.8781, "lon": -87.6298, "city": "Chicago"},
    "America/Denver": {"lat": 39.7392, "lon": -104.9903, "city": "Denver"},
    "America/Los_Angeles": {"lat": 34.0522, "lon": -118.2437, "city": "Los Angeles"},
    "America/Anchorage": {"lat": 61.2181, "lon": -149.9003, "city": "Anchorage"},
    "Pacific/Honolulu": {"lat": 21.3099, "lon": -157.8581, "city": "Honolulu"},
    "Asia/Karachi": {"lat": 24.8607, "lon": 67.0011, "city": "Karachi"},
}

BRIEFING_SYSTEM_PROMPT = """You are a warm, professional morning briefing host on a voice assistant.

Synthesize the data into three short spoken sections and return them as a JSON object with exactly these keys: "weather", "email", "calendar".

Rules for each section:
- One or two natural spoken sentences per section
- weather: mention the day, temperature, conditions, and rain chance
- email: mention unread count and specify it is from the inbox (e.g. "You have 5 unread emails in your inbox this morning.")
- calendar: list events or say the calendar is clear
- Say all temperatures in Celsius
- Use plain spoken English with no markdown, bullets, numbered lists, URLs, emojis, or stage directions
- Use "you have" not "the API returned"
- Sound warm, calm, and lightly conversational
- Do not include a greeting or goodbye in any section

Output ONLY a raw JSON object — no markdown fences, no extra text:
{"weather": "...", "email": "...", "calendar": "..."}
"""


class DailyBriefMarketplaceCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _access_token: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run_daily_briefing())

    def _load_google_access_token(self) -> bool:
        """Load the user's linked Google access token from OpenHome."""
        try:
            token = self.capability_worker.get_token("google")
            if isinstance(token, dict):
                token = token.get("access_token") or token.get("token") or ""
            if isinstance(token, str) and token.strip():
                self._access_token = token.strip()
                return True

            self.worker.editor_logging_handler.warning("Google token is not connected")
            return False
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Google token lookup error: {e}")
            return False

    def _get_user_timezone(self) -> ZoneInfo:
        """Return the user's timezone, falling back to UTC if unavailable."""
        try:
            return ZoneInfo(self._get_user_timezone_name())
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Timezone lookup failed: {e}")
            return ZoneInfo("UTC")

    def _get_user_timezone_name(self) -> str:
        """Return the user's OpenHome timezone name."""
        return self.capability_worker.get_timezone() or "UTC"

    def _get_spoken_today(self) -> str:
        """Return today's local date in a natural spoken format."""
        user_timezone = self._get_user_timezone()
        today = datetime.now(user_timezone)
        return today.strftime("%A, %B %d").replace(" 0", " ")

    def _get_intro_line(self) -> str:
        """Return a short, natural opening line for the morning brief."""
        now = datetime.now(self._get_user_timezone())
        if now.weekday() >= 5:
            return "Good morning. Give me just a moment while I pull together everything you need to know for the day ahead."
        return "Good morning. Let me take a quick look and walk you through what is coming up for you today."

    def _get_exit_line(self) -> str:
        """Return a warm but brief closing line."""
        now = datetime.now(self._get_user_timezone())
        if now.weekday() >= 5:
            return "Enjoy the rest of your morning."
        return "Hope your day gets off to a smooth start."

    def _fetch_calendar_sync(self, session: requests.Session) -> Dict[str, Any]:
        """Fetch today's calendar events from Google Calendar API."""
        try:
            user_timezone = self._get_user_timezone()
            now = datetime.now(user_timezone)
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)

            headers = {"Authorization": f"Bearer {self._access_token}"}
            params = {
                "timeMin": start_of_day.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "timeMax": end_of_day.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": CALENDAR_EVENT_LIMIT,
            }

            response = session.get(
                CALENDAR_URL,
                headers=headers,
                params=params,
                timeout=API_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"Calendar API error: {response.status_code}"
                )
                return {"ok": False, "events": [], "error": "calendar_unavailable"}

            data = response.json()
            events = []

            for item in data.get("items", []):
                start = item.get("start", {})
                start_time = start.get("dateTime") or start.get("date")

                if start_time:
                    if "T" in start_time:
                        dt = datetime.fromisoformat(
                            start_time.replace("Z", "+00:00")
                        ).astimezone(user_timezone)
                        time_str = dt.strftime("%I:%M %p").lstrip("0")
                    else:
                        time_str = "All day"

                    events.append({
                        "time": time_str,
                        "title": item.get("summary", "Untitled"),
                        "location": item.get("location", ""),
                    })

            return {"ok": True, "events": events, "error": None}

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Calendar fetch error: {e}")
            return {"ok": False, "events": [], "error": "calendar_error"}

    def _remove_generated_signoff(self, text: str) -> str:
        """Remove LLM sign-offs because the ability speaks its own exit message."""
        signoff_pattern = (
            r"\s*(?:that's your brief[.!]?\s*)?"
            r"(?:have|hope you have|wishing you)\s+a\s+"
            r"(?:great|good|wonderful|nice|fantastic|productive)\s+day[.!]?\s*$"
        )
        cleaned = re.sub(signoff_pattern, "", text, flags=re.IGNORECASE).strip()
        return cleaned or text.strip()

    def _remove_generated_greeting(self, text: str) -> str:
        """Remove LLM greetings because the ability already greets the user."""
        greeting_pattern = (
            r"^\s*(?:good\s+morning|morning|hi|hello|hey)"
            r"(?:\s+there)?[,.!]\s*"
        )
        cleaned = re.sub(greeting_pattern, "", text, flags=re.IGNORECASE).strip()
        return cleaned or text.strip()

    def _clean_generated_briefing(self, text: str) -> str:
        """Remove duplicate conversational wrappers from generated speech."""
        return self._sanitize_spoken_text(
            self._remove_generated_signoff(
                self._remove_generated_greeting(text)
            )
        )

    def _sanitize_spoken_text(self, text: str) -> str:
        """Strip text patterns that do not read well on a voice device."""
        cleaned = re.sub(r"https?://\S+", "", text)
        cleaned = re.sub(r"^[\s>*#-]+", "", cleaned, flags=re.MULTILINE)
        cleaned = cleaned.replace("**", "").replace("*", "")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _fetch_gmail_sync(self, session: requests.Session) -> Dict[str, Any]:
        """Fetch exact unread Gmail count from the INBOX label."""
        try:
            headers = {"Authorization": f"Bearer {self._access_token}"}
            user_tz = self._get_user_timezone()
            now = datetime.now(user_tz)
            start_of_today = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            start_of_tomorrow = start_of_today + 86400

            response = session.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=headers,
                params={
                    "labelIds": ["INBOX", "UNREAD"],
                    "q": f"after:{start_of_today} before:{start_of_tomorrow}",
                    "maxResults": 500,
                },
                timeout=API_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"Gmail API error: {response.status_code}"
                )
                return {
                    "ok": False,
                    "unread_count": None,
                    "error": "gmail_unavailable",
                }

            data = response.json()
            unread_count = len(data.get("messages", []))

            return {
                "ok": True,
                "unread_count": unread_count,
                "error": None,
            }

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Gmail fetch error: {e}")
            return {
                "ok": False,
                "unread_count": None,
                "error": "gmail_error",
            }

    def _is_valid_location(self, location: Any) -> bool:
        """Return True when a cached or detected location has usable coordinates."""
        if not isinstance(location, dict):
            return False
        try:
            lat = float(location.get("lat"))
            lon = float(location.get("lon"))
        except (TypeError, ValueError):
            return False
        return -90 <= lat <= 90 and -180 <= lon <= 180

    def _is_public_ip(self, value: Optional[str]) -> bool:
        """Return True only for public IP addresses."""
        if not value:
            return False
        try:
            parsed = ip_address(value)
        except ValueError:
            return False
        return not (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_reserved
            or parsed.is_multicast
        )

    def _location_from_timezone(self) -> Optional[Dict[str, Any]]:
        """Use timezone as a last-resort weather location fallback."""
        timezone_name = self._get_user_timezone_name()
        fallback = TIMEZONE_LOCATION_FALLBACKS.get(timezone_name)
        if not fallback:
            return None
        self.worker.editor_logging_handler.warning(
            f"Using timezone fallback location for {timezone_name}"
        )
        return {**fallback, "source": "timezone_fallback"}

    async def _get_user_location(
        self,
        session: requests.Session,
    ) -> Optional[Dict[str, Any]]:
        """Always try IP geolocation first, save result, fall back to saved JSON if IP fails."""
        prefs = await self._load_prefs()
        cached_location = prefs.get("location")

        try:
            user_ip = self.worker.user_socket.client.host
        except (AttributeError, TypeError):
            user_ip = None

        if self._is_public_ip(user_ip):
            try:
                response = await asyncio.to_thread(
                    lambda: session.get(
                        f"{IP_GEOLOCATION_URL}/{user_ip}",
                        headers={"User-Agent": "OpenHome-DailyBrief"},
                        timeout=LOCATION_TIMEOUT_SECONDS,
                    )
                )
                if response.status_code == 200:
                    data = response.json()
                    location = {
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "city": data.get("city", "your area"),
                        "source": "ip_geolocation",
                        "saved_at": datetime.now(timezone.utc).isoformat(),
                    }
                    if data.get("status") == "success" and self._is_valid_location(location):
                        prefs["location"] = location
                        await self._save_prefs(prefs)
                        return location
            except Exception as e:
                self.worker.editor_logging_handler.warning(f"IP geolocation failed: {e}")

        if self._is_valid_location(cached_location):
            self.worker.editor_logging_handler.info("IP lookup failed, using saved location.")
            return cached_location

        return self._location_from_timezone()

    def _weather_code_to_text(self, code: int) -> str:
        """Convert WMO weather code to readable text."""
        codes = {
            0: "clear skies",
            1: "mainly clear",
            2: "partly cloudy",
            3: "overcast",
            45: "foggy",
            48: "foggy",
            51: "light drizzle",
            53: "moderate drizzle",
            55: "heavy drizzle",
            61: "light rain",
            63: "moderate rain",
            65: "heavy rain",
            71: "light snow",
            73: "moderate snow",
            75: "heavy snow",
            95: "thunderstorms",
        }
        return codes.get(code, "variable conditions")

    def _fetch_weather_sync(
        self,
        location: Dict[str, Any],
        session: requests.Session,
    ) -> Dict[str, Any]:
        """Fetch weather from Open-Meteo API."""
        try:
            lat, lon = location["lat"], location["lon"]
            params = {
                "latitude": lat,
                "longitude": lon,
                "current_weather": True,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "temperature_unit": "celsius",
            }
            response = session.get(
                WEATHER_URL,
                params=params,
                timeout=API_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"Weather API error: {response.status_code}"
                )
                return {"ok": False, "error": "weather_unavailable"}
            data = response.json()
            current = data.get("current_weather", {})
            daily = data.get("daily", {})
            return {
                "ok": True,
                "temp": round(current.get("temperature", 0)),
                "conditions": self._weather_code_to_text(
                    current.get("weathercode", 0)
                ),
                "high": round(daily.get("temperature_2m_max", [0])[0]),
                "low": round(daily.get("temperature_2m_min", [0])[0]),
                "rain_chance": (daily.get("precipitation_probability_max") or [0])[0],
                "city": location["city"],
                "error": None,
            }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Weather fetch error: {e}")
            return {"ok": False, "error": "weather_error"}

    async def _fetch_all_data(self) -> Dict[str, Any]:
        """Fetch all data sources with short sequential requests."""
        self.worker.editor_logging_handler.info("Starting data fetch")

        with requests.Session() as session:
            location = await self._get_user_location(session)

            if location:
                weather, calendar, gmail = await asyncio.gather(
                    asyncio.to_thread(self._fetch_weather_sync, location, session),
                    asyncio.to_thread(self._fetch_calendar_sync, session),
                    asyncio.to_thread(self._fetch_gmail_sync, session),
                )
            else:
                self.worker.editor_logging_handler.warning(
                    "Could not determine location"
                )
                weather = {"ok": False, "error": "location_unavailable"}
                calendar, gmail = await asyncio.gather(
                    asyncio.to_thread(self._fetch_calendar_sync, session),
                    asyncio.to_thread(self._fetch_gmail_sync, session),
                )

        if weather.get("ok"):
            self.worker.editor_logging_handler.info("Weather fetched successfully")
        if calendar.get("ok"):
            self.worker.editor_logging_handler.info(
                f"Calendar: {len(calendar.get('events', []))} events"
            )
        if gmail.get("ok"):
            self.worker.editor_logging_handler.info(
                f"Gmail: {gmail.get('unread_count', 0)} unread"
            )

        return {"weather": weather, "calendar": calendar, "gmail": gmail}

    def _synthesize_briefing(self, data: Dict[str, Any]) -> Dict[str, str]:
        """
        Use LLM to create three spoken sections as a JSON dict.
        IMPORTANT: text_to_text_response is SYNCHRONOUS - no await!
        Returns {"weather": "...", "email": "...", "calendar": "..."}
        """
        try:
            context_parts = []
            context_parts.append(f"Today: {self._get_spoken_today()}.")

            weather = data.get("weather") or {}
            if weather.get("ok"):
                w = weather
                context_parts.append(
                    f"Weather: {w['temp']} degrees Celsius and {w['conditions']} "
                    f"in {w['city']}. High of {w['high']} degrees Celsius, "
                    f"low of {w['low']} degrees Celsius. "
                    f"{w['rain_chance']}% chance of rain."
                )
            else:
                context_parts.append(
                    "Weather: Unavailable because the user's location could not be determined."
                )

            gmail = data.get("gmail") or {}
            if gmail.get("ok"):
                g = gmail
                if g.get("unread_count", 0):
                    context_parts.append(f"Gmail: {g['unread_count']} unread emails.")
                else:
                    context_parts.append("Gmail: No unread email.")
            else:
                context_parts.append("Gmail: Unavailable right now.")

            calendar = data.get("calendar") or {}
            if calendar.get("ok"):
                events = calendar.get("events", [])
                if events:
                    events_str = "; ".join(
                        [
                            f"{e['title']} at {e['time']}"
                            + (f" ({e['location']})" if e.get("location") else "")
                            for e in events
                        ]
                    )
                    context_parts.append(f"Calendar events today: {events_str}.")
                else:
                    context_parts.append("Calendar: No events today. Your calendar is clear.")
            else:
                context_parts.append("Calendar: Unavailable right now.")

            context = "\n\n".join(context_parts)

            raw = self.capability_worker.text_to_text_response(
                prompt_text=f"Create a morning briefing based on this data:\n\n{context}",
                system_prompt=BRIEFING_SYSTEM_PROMPT,
                history=[],
            )

            cleaned = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", raw.strip())
            sections = json.loads(cleaned)
            return {
                "weather": self._sanitize_spoken_text(sections.get("weather", "")),
                "email": self._sanitize_spoken_text(sections.get("email", "")),
                "calendar": self._sanitize_spoken_text(sections.get("calendar", "")),
            }

        except Exception as e:
            self.worker.editor_logging_handler.error(f"LLM synthesis error: {e}")
            return {"weather": "", "email": "", "calendar": ""}

    async def _load_prefs(self) -> Dict[str, Any]:
        """Load user preferences from persistent storage."""
        try:
            if await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            ):
                content = await self.capability_worker.read_file(
                    PREFS_FILE, False
                )
                return json.loads(content)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error loading prefs: {e}")

        return {"location": None}

    async def _save_prefs(self, prefs: Dict[str, Any]) -> None:
        """Save user preferences to persistent storage."""
        try:
            if await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            ):
                await self.capability_worker.delete_file(PREFS_FILE, False)

            await self.capability_worker.write_file(
                PREFS_FILE,
                json.dumps(prefs, indent=2),
                False,
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error saving prefs: {e}")

    async def run_daily_briefing(self) -> None:
        """
        Main briefing flow.
        Target: First word spoken within 6 seconds of trigger.
        """
        try:
            if not self._load_google_access_token():
                await self.capability_worker.speak(
                    "Your Google account isn't connected. Go to Settings, Linked accounts, and connect Google."
                )
                return

            await self.capability_worker.speak(self._get_intro_line())

            data = await self._fetch_all_data()

            if not any((source or {}).get("ok") for source in data.values()):
                await self.capability_worker.speak(
                    "I'm having trouble reaching some services right now. "
                    "Try again in a moment."
                )
                return

            sections = self._synthesize_briefing(data)
            for key in ("weather", "email", "calendar"):
                text = sections.get(key, "")
                if text:
                    await self.capability_worker.speak(text)
                    await self.worker.session_tasks.sleep(0.05)
            await self.capability_worker.speak(self._get_exit_line())

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Daily briefing error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()
