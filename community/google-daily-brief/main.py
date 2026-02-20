import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# GOOGLE OAUTH CREDENTIALS — Replace with your values (see README setup)
# =============================================================================
GOOGLE_CLIENT_ID = "YOUR_CLIENT_ID_HERE"
GOOGLE_CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"
GOOGLE_ACCESS_TOKEN = "YOUR_ACCESS_TOKEN_HERE"
GOOGLE_REFRESH_TOKEN = "YOUR_REFRESH_TOKEN_HERE"

# --- API URLs ---
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
IP_GEOLOCATION_URL = "http://ip-api.com/json"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GMAIL_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"

# --- Exit words ---
EXIT_WORDS = ["stop", "quit", "exit", "done", "cancel"]
PREFS_FILE = "daily_brief_prefs.json"

BRIEFING_SYSTEM_PROMPT = """You are a warm, professional morning briefing host on a voice assistant.

Synthesize the data into ONE concise ~60-second spoken briefing.

Rules:
- Always cover: weather, calendar, email (in that order)
- If calendar is clear, say so briefly (e.g. "Your calendar is clear today")
- Skip other sections only if they have NO data
- Be concise - under 120 words
- Natural spoken language, no jargon
- Use "you have" not "the API returned"
"""


class GoogleDailyBriefCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _access_token: str = GOOGLE_ACCESS_TOKEN

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_daily_briefing())

    def _refresh_google_token(self) -> bool:
        """Refresh access token using refresh token. Returns True on success."""
        try:
            response = requests.post(
                TOKEN_REFRESH_URL,
                data={
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "refresh_token": GOOGLE_REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                self._access_token = data.get("access_token", "")
                return True
            self.worker.editor_logging_handler.error(
                f"Token refresh failed: {response.status_code}"
            )
            return False
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Token refresh error: {e}")
            return False

    def _fetch_calendar_sync(self) -> Optional[List[Dict[str, str]]]:
        """Fetch today's calendar events from Google Calendar API."""
        try:
            now = datetime.utcnow()
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)

            headers = {"Authorization": f"Bearer {self._access_token}"}
            params = {
                "timeMin": start_of_day.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timeMax": end_of_day.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 10,
            }

            response = requests.get(
                CALENDAR_URL, headers=headers, params=params, timeout=3
            )

            if response.status_code == 401 and self._refresh_google_token():
                headers["Authorization"] = f"Bearer {self._access_token}"
                response = requests.get(
                    CALENDAR_URL, headers=headers, params=params, timeout=3
                )

            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"Calendar API error: {response.status_code}"
                )
                return None

            data = response.json()
            events = []

            for item in data.get("items", []):
                start = item.get("start", {})
                start_time = start.get("dateTime") or start.get("date")

                if start_time:
                    if "T" in start_time:
                        dt = datetime.fromisoformat(
                            start_time.replace("Z", "+00:00")
                        )
                        time_str = dt.strftime("%I:%M %p").lstrip("0")
                    else:
                        time_str = "All day"

                    events.append({
                        "time": time_str,
                        "title": item.get("summary", "Untitled"),
                        "location": item.get("location", ""),
                    })

            return events if events else None

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Calendar fetch error: {e}")
            return None

    def _fetch_gmail_sync(self) -> Optional[Dict[str, Any]]:
        """Fetch unread Gmail summary."""
        try:
            headers = {"Authorization": f"Bearer {self._access_token}"}
            params = {"q": "is:unread", "maxResults": 5}

            response = requests.get(
                GMAIL_LIST_URL, headers=headers, params=params, timeout=3
            )

            if response.status_code == 401 and self._refresh_google_token():
                headers["Authorization"] = f"Bearer {self._access_token}"
                response = requests.get(
                    GMAIL_LIST_URL, headers=headers, params=params, timeout=3
                )

            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"Gmail API error: {response.status_code}"
                )
                return None

            data = response.json()
            message_ids = [msg["id"] for msg in data.get("messages", [])]
            unread_count = data.get("resultSizeEstimate", 0)

            if not message_ids:
                return None

            messages = []
            for msg_id in message_ids[:5]:
                msg_url = f"{GMAIL_LIST_URL}/{msg_id}"
                msg_response = requests.get(
                    msg_url,
                    headers=headers,
                    params={"format": "metadata"},
                    timeout=3,
                )

                if msg_response.status_code == 200:
                    msg_data = msg_response.json()
                    headers_list = msg_data.get("payload", {}).get("headers", [])

                    sender = next(
                        (h["value"] for h in headers_list if h["name"] == "From"),
                        "Unknown",
                    )
                    subject = next(
                        (h["value"] for h in headers_list if h["name"] == "Subject"),
                        "No subject",
                    )

                    if "<" in sender:
                        sender = sender.split("<")[0].strip()

                    messages.append({"from": sender, "subject": subject[:60]})

            return {"unread_count": unread_count, "messages": messages}

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Gmail fetch error: {e}")
            return None

    async def _get_user_location(self) -> Optional[Dict[str, Any]]:
        """Get user location via IP geolocation, cache in prefs."""
        try:
            prefs = await self._load_prefs()
            if prefs.get("location"):
                return prefs["location"]

            try:
                user_ip = self.worker.user_socket.client.host
            except (AttributeError, TypeError):
                user_ip = None
            if not user_ip or user_ip in ("127.0.0.1", "localhost"):
                response = requests.get(IP_GEOLOCATION_URL, timeout=2)
            else:
                response = requests.get(
                    f"{IP_GEOLOCATION_URL}/{user_ip}",
                    headers={"User-Agent": "OpenHome-DailyBrief"},
                    timeout=2,
                )

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    location = {
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "city": data.get("city", "your area"),
                    }

                    prefs["location"] = location
                    await self._save_prefs(prefs)
                    return location

            return None

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Location detection error: {e}"
            )
            return None

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

    def _fetch_weather_sync(self, location: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetch weather from Open-Meteo API (free, no key). Sync for thread pool."""
        try:
            lat, lon = location["lat"], location["lon"]
            params = {
                "latitude": lat,
                "longitude": lon,
                "current_weather": True,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "temperature_unit": "fahrenheit",
            }
            response = requests.get(WEATHER_URL, params=params, timeout=3)
            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"Weather API error: {response.status_code}"
                )
                return None
            data = response.json()
            current = data.get("current_weather", {})
            daily = data.get("daily", {})
            return {
                "temp": round(current.get("temperature", 0)),
                "conditions": self._weather_code_to_text(
                    current.get("weathercode", 0)
                ),
                "high": round(daily.get("temperature_2m_max", [0])[0]),
                "low": round(daily.get("temperature_2m_min", [0])[0]),
                "rain_chance": (daily.get("precipitation_probability_max") or [0])[0],
                "city": location["city"],
            }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Weather fetch error: {e}")
            return None

    async def _fetch_all_data(self) -> Dict[str, Any]:
        """Fetch all data sources in parallel. Target: 2-3 seconds."""
        self.worker.editor_logging_handler.info("Starting parallel data fetch")

        location = await self._get_user_location()
        if not location:
            self.worker.editor_logging_handler.warning(
                "Could not determine location, using default"
            )
            location = {"lat": 40.7128, "lon": -74.0060, "city": "New York"}

        loop = asyncio.get_running_loop()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    loop.run_in_executor(
                        None, lambda: self._fetch_weather_sync(location)
                    ),
                    loop.run_in_executor(None, self._fetch_calendar_sync),
                    loop.run_in_executor(None, self._fetch_gmail_sync),
                    return_exceptions=True,
                ),
                timeout=4,
            )
        except asyncio.TimeoutError:
            self.worker.editor_logging_handler.warning("Data fetch timed out")
            return {"weather": None, "calendar": None, "gmail": None}

        weather = results[0] if not isinstance(results[0], BaseException) else None
        calendar = results[1] if not isinstance(results[1], BaseException) else None
        gmail = results[2] if not isinstance(results[2], BaseException) else None

        if weather:
            self.worker.editor_logging_handler.info("Weather fetched successfully")
        if calendar:
            self.worker.editor_logging_handler.info(
                f"Calendar: {len(calendar)} events"
            )
        if gmail:
            self.worker.editor_logging_handler.info(
                f"Gmail: {gmail['unread_count']} unread"
            )

        return {"weather": weather, "calendar": calendar, "gmail": gmail}

    def _synthesize_briefing(self, data: Dict[str, Any]) -> str:
        """
        Use LLM to create one cohesive spoken briefing.
        IMPORTANT: text_to_text_response is SYNCHRONOUS - no await!
        """
        try:
            context_parts = []

            if data.get("weather"):
                w = data["weather"]
                context_parts.append(
                    f"Weather: {w['temp']}°F and {w['conditions']} in {w['city']}. "
                    f"High of {w['high']}, low of {w['low']}. "
                    f"{w['rain_chance']}% chance of rain."
                )

            # Always include calendar (we fetch it with weather and gmail)
            if data.get("calendar"):
                events_str = "\n".join(
                    [
                        f"- {e['time']}: {e['title']}"
                        + (f" ({e['location']})" if e.get("location") else "")
                        for e in data["calendar"]
                    ]
                )
                context_parts.append(
                    f"Calendar events today:\n{events_str}"
                )
            else:
                context_parts.append(
                    "Calendar: No events today. Your calendar is clear."
                )

            if data.get("gmail"):
                g = data["gmail"]
                msgs_str = "\n".join(
                    [
                        f"- From {m['from']}: {m['subject']}"
                        for m in g["messages"][:3]
                    ]
                )
                context_parts.append(
                    f"Gmail: {g['unread_count']} unread emails. Top messages:\n{msgs_str}"
                )

            context = "\n\n".join(context_parts)

            if not context:
                return "Good morning! I'm having trouble getting your briefing right now."

            briefing = self.capability_worker.text_to_text_response(
                prompt_text=f"Create a morning briefing based on this data:\n\n{context}",
                system_prompt=BRIEFING_SYSTEM_PROMPT,
                history=[],
            )

            return briefing.strip()

        except Exception as e:
            self.worker.editor_logging_handler.error(f"LLM synthesis error: {e}")
            return "Good morning! I ran into trouble creating your briefing."

    def _split_for_speech(self, text: str, max_sentences: int = 3) -> List[str]:
        """Split text into chunks of 1-2 sentences for short speak() calls."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = []

        for s in sentences:
            current.append(s)
            if len(current) >= max_sentences:
                chunks.append(" ".join(current))
                current = []

        if current:
            chunks.append(" ".join(current))

        return chunks if chunks else [text]

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

    def _is_exit_word(self, text: str) -> bool:
        """Check if user said an exit word."""
        if not text:
            return False
        lower = text.lower().strip()
        return any(word in lower for word in EXIT_WORDS)

    async def run_daily_briefing(self) -> None:
        """
        Main briefing flow.
        Target: First word spoken within 6 seconds of trigger.
        """
        try:
            await self.capability_worker.speak(
                "Good morning! Let me get your brief."
            )

            data = await self._fetch_all_data()

            if not any(data.values()):
                await self.capability_worker.speak(
                    "I'm having trouble reaching some services right now. "
                    "Try again in a moment."
                )
                return

            briefing = self._synthesize_briefing(data)

            for chunk in self._split_for_speech(briefing):
                await self.capability_worker.speak(chunk)

            # Loop until user says exit or no
            repeat_phrases = ["repeat", "again", "continue"]
            calendar_phrases = [
                "calendar", "check my calendar", "check calendar",
                "what's on my calendar", "what's on calendar",
                "meetings", "my schedule", "my calendar", "let me know my calendar",
            ]
            empty_retries = 0
            while True:
                await self.capability_worker.speak("Anything else?")
                response = await self.capability_worker.user_response()

                if not response or not response.strip():
                    empty_retries += 1
                    if empty_retries >= 2:
                        break
                    await self.capability_worker.speak(
                        "I didn't catch that. Anything else?"
                    )
                    continue
                empty_retries = 0

                lower = response.lower().strip()
                if self._is_exit_word(response) or lower in ("no", "nope", "that's all"):
                    await self.capability_worker.speak("Have a great day!")
                    break
                if any(phrase in lower for phrase in repeat_phrases):
                    for chunk in self._split_for_speech(briefing):
                        await self.capability_worker.speak(chunk)
                elif any(phrase in lower for phrase in calendar_phrases):
                    if data.get("calendar"):
                        events = data["calendar"]
                        parts = [
                            f"{e['title']} at {e['time']}"
                            + (f" ({e['location']})" if e.get("location") else "")
                            for e in events
                        ]
                        cal_text = "Today you have " + ", ".join(parts) + "."
                        await self.capability_worker.speak(cal_text)
                    else:
                        await self.capability_worker.speak(
                            "There's nothing on your calendar today."
                        )
                else:
                    break

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Daily briefing error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()
