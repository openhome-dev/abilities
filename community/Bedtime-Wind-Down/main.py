import asyncio
import json
import os
import random
import time
from datetime import datetime, timedelta
from typing import Any, ClassVar, Dict, List

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class BedtimeWindDownCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # --- BOILERPLATE REGISTRATION ---
    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        """Registers the capability and loads hotwords from config.json."""
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    # --- KEYS AND CONSTANTS ---
    CALM_VOICE_ID: ClassVar[str] = "GBv7mTt0atIp3Br8iCZE"
    ZENQUOTES_URL: ClassVar[str] = "https://zenquotes.io/api/random"
    PREFS_FILE: ClassVar[str] = "bedtime_prefs.json"

    # Composio API (Google Calendar Integration)
    COMPOSIO_API_KEY: ClassVar[str] = "YOUR_COMPOSIO_API_KEY"
    COMPOSIO_USER_ID: ClassVar[str] = "YOUR_COMPOSIO_USER_ID"
    COMPOSIO_BASE_URL: ClassVar[str] = "https://backend.composio.dev/api/v2"

    # --- SOUND LIBRARY ---
    SOUND_LIBRARY: ClassVar[Dict[str, Dict[str, Any]]] = {
        "ocean_sleep.mp3": {
            "url": "https://cdn.pixabay.com/audio/2025/07/09/audio_56227295c2.mp3",
            "duration": 132
        },
        "beach_sleep.mp3": {
            "url": "https://cdn.pixabay.com/audio/2025/09/13/audio_1854362bf0.mp3",
            "duration": 156
        },
        "rain_sleep.mp3": {
            "url": "https://cdn.pixabay.com/audio/2025/11/15/audio_3f7ff9f3e2.mp3",
            "duration": 600
        },
        "whitenoise_sleep.mp3": {
            "url": "https://cdn.pixabay.com/audio/2024/06/21/audio_f43364ca4a.mp3",
            "duration": 210
        }
    }

    # Prompt for dynamic LLM wind-down message generation
    WINDDOWN_MESSAGE_PROMPT: ClassVar[str] = """You are a calm bedtime assistant speaking in a soft, soothing tone.
Generate a brief goodnight message (3-4 sentences max).

Tomorrow's info:
{tomorrow_info}

Rules:
- If there is an event tomorrow, mention it gently and the suggested wake time
- If no events, say tomorrow is open and they can sleep in
- Keep it warm, calm, and brief
- Do not use exclamation marks
- Do not say "Hey" or anything energetic
- End with something like "rest well" or "sleep well"

Example (with event): "Tomorrow you have a team standup at 9 AM, so waking up around 8 would give you plenty of time. Everything else can wait until morning. Rest well."
Example (no events): "Tomorrow is wide open. No meetings, no deadlines pulling you out of bed early. Sleep as long as you need."
"""

    LOCAL_QUOTES: ClassVar[List[Dict[str, str]]] = [
        {
            "q": "The best bridge between despair and hope is a good night's sleep.",
            "a": "E. Joseph Cossman"
        },
        {
            "q": "Sleep is the best meditation.",
            "a": "Dalai Lama"
        },
        {
            "q": "Rest is not idleness.",
            "a": "John Lubbock"
        },
        {
            "q": "The moon stays bright when it doesn't avoid the night.",
            "a": "Rumi"
        }
    ]

    async def speak_calm(self, text: str):
        """Wrapper to always use the calming meditation voice."""
        await self.capability_worker.text_to_speech(text, self.CALM_VOICE_ID)

    # --- PREFERENCES MANAGEMENT ---
    async def load_preferences(self) -> Dict[str, Any]:
        """Loads user preferences or sets defaults if it's the first run."""
        default_prefs = {
            "include_tomorrow_preview": True,
            "include_quote": True,
            "sleep_sound_enabled": True,
            "sleep_sound": "rain_sleep.mp3",
            "sleep_sound_duration": 30,
            "wake_buffer_minutes": 60,
            "homeassistant_enabled": False,
            "ha_night_scene": "night",
            "voice_preference": self.CALM_VOICE_ID,
            "times_used": 0
        }

        exists = await self.capability_worker.check_if_file_exists(
            self.PREFS_FILE, False
        )
        if exists:
            try:
                content = await self.capability_worker.read_file(
                    self.PREFS_FILE, False
                )
                user_prefs = json.loads(content)
                for key, value in user_prefs.items():
                    default_prefs[key] = value
                return default_prefs
            except Exception:
                pass
        return default_prefs

    async def save_preferences(self, prefs: Dict[str, Any]):
        """Saves user preferences back to the persistence file."""
        try:
            json_str = json.dumps(prefs)
            await self.capability_worker.delete_file(self.PREFS_FILE, False)
            await self.capability_worker.write_file(
                self.PREFS_FILE, json_str, False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error saving prefs: {e}")

    # --- CALENDAR INTEGRATION ---
    async def calendar_get_tomorrow(self) -> list:
        """Fetches tomorrow's events from Google Calendar via Composio."""
        if self.COMPOSIO_API_KEY == "YOUR_COMPOSIO_API_KEY":
            self.worker.editor_logging_handler.info(
                "Composio API key not set. Returning empty calendar."
            )
            return []

        tomorrow = datetime.now() + timedelta(days=1)
        start_of_day = tomorrow.replace(
            hour=0, minute=0, second=0
        ).isoformat() + "Z"
        end_of_day = tomorrow.replace(
            hour=23, minute=59, second=59
        ).isoformat() + "Z"

        url = f"{self.COMPOSIO_BASE_URL}/actions/GOOGLECALENDAR_FIND_EVENT/execute"
        headers = {
            "X-API-KEY": self.COMPOSIO_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "connectedAccountId": self.COMPOSIO_USER_ID,
            "input": {
                "timeMin": start_of_day,
                "timeMax": end_of_day,
                "maxResults": 5,
                "orderBy": "startTime",
                "singleEvents": True
            }
        }

        try:
            response = await asyncio.to_thread(
                requests.post, url, json=payload, headers=headers, timeout=15
            )
            if response.status_code == 200:
                data = response.json()
                self.worker.editor_logging_handler.info(
                    "Calendar fetched successfully."
                )
                return data.get("data", {}).get("items", [])
            else:
                self.worker.editor_logging_handler.error(
                    f"Calendar API error {response.status_code}"
                )
                return []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Calendar fetch failed: {e}")
            return []

    def format_time_for_speech(self, dt: datetime) -> str:
        """Formats a datetime object into a natural spoken string."""
        hour = dt.strftime("%I").lstrip("0")
        minute = dt.strftime("%M")
        ampm = dt.strftime("%p").replace("AM", "A M").replace("PM", "P M")
        if minute == "00":
            return f"{hour} {ampm}"
        return f"{hour} {minute} {ampm}"

    def calculate_wake_time(self, first_event: dict, buffer_minutes: int) -> str:
        """Calculates suggested wake time based on first event and buffer."""
        try:
            start_str = first_event.get("start", {}).get("dateTime", "")
            if not start_str:
                return None
            event_time = datetime.fromisoformat(
                start_str.replace("Z", "+00:00")
            )
            wake_time = event_time - timedelta(minutes=buffer_minutes)
            return self.format_time_for_speech(wake_time)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Wake time calc error: {e}")
            return None

    # --- QUOTES ---
    async def get_quote(self) -> str:
        """Fetches a calming quote from ZenQuotes API or uses fallback."""
        quote_text = ""
        author = ""
        try:
            response = await asyncio.to_thread(
                requests.get, self.ZENQUOTES_URL, timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                if data:
                    quote_text = data[0]["q"]
                    author = data[0]["a"]
        except Exception:
            pass

        if not quote_text:
            pick = random.choice(self.LOCAL_QUOTES)
            quote_text = pick["q"]
            author = pick["a"]
        return f"{quote_text}. {author}."

    # --- SLEEP SOUNDS ---
    async def play_sleep_sounds(self, duration_minutes: int, sound_file_name: str):
        """Plays the selected ambient sound in a loop for the specified duration."""
        sound_data = self.SOUND_LIBRARY.get(
            sound_file_name, self.SOUND_LIBRARY["rain_sleep.mp3"]
        )
        sound_url = sound_data["url"]
        track_duration = sound_data["duration"]

        sound_bytes = None
        try:
            self.worker.editor_logging_handler.info(
                f"Downloading {sound_file_name} from {sound_url}..."
            )
            response = await asyncio.to_thread(
                requests.get, sound_url, timeout=10
            )
            if response.status_code == 200:
                sound_bytes = response.content
            else:
                self.worker.editor_logging_handler.error("Sound download failed.")
                self.capability_worker.resume_normal_flow()
                return
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Network error: {e}")
            self.capability_worker.resume_normal_flow()
            return

        spoken_name = sound_file_name.replace("_sleep.mp3", "")
        msg = (f"Starting {spoken_name} sounds. "
               f"They'll play for {duration_minutes} minutes. Sleep well.")
        await self.speak_calm(msg)
        await self.worker.session_tasks.sleep(2)

        total_seconds = duration_minutes * 60
        repetitions = int(total_seconds / track_duration) + 1
        trap_duration = track_duration - 3

        try:
            for i in range(repetitions):
                self.worker.editor_logging_handler.info(
                    f"Playing loop {i+1} of {repetitions} ({spoken_name})"
                )

                self.worker.music_mode_event.set()
                await self.capability_worker.send_data_over_websocket(
                    "music-mode", {"mode": "on"}
                )

                start_segment = time.time()
                await self.capability_worker.play_audio(sound_bytes)
                segment_duration = time.time() - start_segment

                if segment_duration < trap_duration:
                    self.worker.editor_logging_handler.info(
                        "Detected early stop by user. Exiting loop."
                    )
                    await self.capability_worker.send_data_over_websocket(
                        "music-mode", {"mode": "off"}
                    )
                    self.worker.music_mode_event.clear()
                    break

                await self.capability_worker.send_data_over_websocket(
                    "music-mode", {"mode": "off"}
                )
                self.worker.music_mode_event.clear()

                if i < repetitions - 1:
                    await self.worker.session_tasks.sleep(0.5)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Playback error: {e}")
        finally:
            self.worker.music_mode_event.clear()
            await self.capability_worker.send_data_over_websocket(
                "music-mode", {"mode": "off"}
            )
            self.capability_worker.resume_normal_flow()

    async def run(self):
        """Main sequence for the bedtime routine."""
        try:
            self.worker.editor_logging_handler.info("Bedtime ability started")
            prefs = await self.load_preferences()

            prefs["times_used"] = prefs.get("times_used", 0) + 1
            await self.save_preferences(prefs)

            tomorrow_info = "No events tomorrow."
            if prefs.get("include_tomorrow_preview", True):
                events = await self.calendar_get_tomorrow()
                if events and len(events) > 0:
                    first_event = events[0]
                    event_name = first_event.get("summary", "an event")
                    event_time = first_event.get("start", {}).get(
                        "dateTime", ""
                    )
                    wake_time = self.calculate_wake_time(
                        first_event, prefs.get("wake_buffer_minutes", 60)
                    )

                    tomorrow_info = f"First event: {event_name} at {event_time}."
                    if wake_time:
                        tomorrow_info += f" Suggested wake time: {wake_time}."

            winddown_prompt = self.WINDDOWN_MESSAGE_PROMPT.format(
                tomorrow_info=tomorrow_info
            )
            winddown_text = self.capability_worker.text_to_text_response(
                winddown_prompt
            )

            await self.speak_calm(winddown_text)
            await self.worker.session_tasks.sleep(2)

            if prefs.get("include_quote", True):
                quote = await self.get_quote()
                await self.speak_calm(quote)
                await self.worker.session_tasks.sleep(2)

            if prefs.get("sleep_sound_enabled", True):
                duration = prefs.get("sleep_sound_duration", 30)
                sound_file = prefs.get("sleep_sound", "rain_sleep.mp3")
                await self.play_sleep_sounds(duration, sound_file)
            else:
                await self.speak_calm("Sleep well.")
                self.capability_worker.resume_normal_flow()

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Bedtime wind-down error: {e}"
            )
            self.worker.music_mode_event.clear()
            await self.capability_worker.send_data_over_websocket(
                "music-mode", {"mode": "off"}
            )
            msg = "Something went wrong, but don't worry about it. Sleep well."
            await self.speak_calm(msg)
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        """Entry point called by the OpenHome SDK."""
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())