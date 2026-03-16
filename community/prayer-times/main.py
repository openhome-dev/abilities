import json
from datetime import datetime
from time import time
from zoneinfo import ZoneInfo

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# ---------------------------------------------------------------------------
# Aladhan API — free, no API key required
# https://aladhan.com/prayer-times-api
# ---------------------------------------------------------------------------
ALADHAN_URL = "https://api.aladhan.com/v1/timingsByCity"
DATA_FILE = "prayer_data.json"

PRAYER_NAMES = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]

# Calculation methods: https://aladhan.com/prayer-times-api#GetTimings
# 2 = ISNA, 3 = MWL, 13 = Diyanet (Turkey)
DEFAULT_METHOD = 2

SYSTEM_PROMPT = """You are a prayer-times voice assistant.
Your ONLY job is to understand the user's intent about Islamic prayer times.

Respond with EXACTLY one JSON object (no extra text):

1. Query next prayer:
   {"intent": "next_prayer"}

2. Query all today's prayer times:
   {"intent": "all_times"}

3. Query a specific prayer:
   {"intent": "specific", "prayer": "<Fajr|Sunrise|Dhuhr|Asr|Maghrib|Isha>"}

4. Set up location (user mentions a city/country):
   {"intent": "setup", "city": "<city>", "country": "<country>"}

5. Change calculation method:
   {"intent": "method", "method": <number>}
   Methods: 1=Karachi, 2=ISNA, 3=MWL, 4=Makkah, 5=Egypt, 13=Diyanet

6. Cannot understand:
   {"intent": "unknown"}

IMPORTANT: Prayer names must be exactly one of: Fajr, Sunrise, Dhuhr, Asr, Maghrib, Isha (capitalize first letter).
"""


class PrayerTimesCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_time(raw: str) -> str:
        """Strip timezone suffix: '14:30 (EET)' -> '14:30'"""
        return raw.split("(")[0].strip()

    @staticmethod
    def _normalize_prayer(name: str) -> str:
        """Normalize LLM output to match API keys: 'fajr' -> 'Fajr'"""
        return name.strip().capitalize()

    # ------------------------------------------------------------------
    # File helpers (delete-before-write pattern from Alarm template)
    # ------------------------------------------------------------------
    async def _read_data(self) -> dict:
        try:
            if not await self.capability_worker.check_if_file_exists(DATA_FILE, False):
                return {}
            raw = await self.capability_worker.read_file(DATA_FILE, False)
            if not (raw or "").strip():
                return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    async def _write_data(self, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            await self.capability_worker.delete_file(DATA_FILE, False)
        except Exception:
            pass
        try:
            await self.capability_worker.write_file(DATA_FILE, payload, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PrayerTimes] Write failed: {e}"
            )

    # ------------------------------------------------------------------
    # Aladhan API
    # ------------------------------------------------------------------
    def _fetch_times(self, city: str, country: str, method: int) -> dict | None:
        try:
            resp = requests.get(
                ALADHAN_URL,
                params={"city": city, "country": country, "method": method},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("data", {}).get("timings", {})
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PrayerTimes] API error: {e}"
            )
        return None

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------
    def _get_now(self) -> datetime:
        tz_name = self.capability_worker.get_timezone()
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        return datetime.now(tz=tz)

    def _parse_time(self, time_str: str, now: datetime) -> datetime | None:
        """Parse 'HH:MM' or 'HH:MM (TZ)' into a datetime for today."""
        try:
            clean = self._clean_time(time_str)
            h, m = map(int, clean.split(":"))
            return now.replace(hour=h, minute=m, second=0, microsecond=0)
        except Exception:
            return None

    def _find_next_prayer(self, timings: dict, now: datetime) -> tuple[str, str] | None:
        for name in PRAYER_NAMES:
            t = timings.get(name)
            if not t:
                continue
            pt = self._parse_time(t, now)
            if pt and pt > now:
                return name, self._clean_time(t)
        return None

    def _format_all_times(self, timings: dict) -> str:
        parts = []
        for name in PRAYER_NAMES:
            t = self._clean_time(timings.get(name, "N/A"))
            parts.append(f"{name}: {t}")
        return ", ".join(parts)

    def _get_timings(self, data: dict, now: datetime) -> dict | None:
        """Return today's timings — use cache if fresh, otherwise fetch."""
        today_str = now.strftime("%Y-%m-%d")
        cached = data.get("last_timings", {})
        if data.get("last_fetch_date") == today_str and cached:
            return cached

        raw_timings = self._fetch_times(
            data["city"],
            data["country"],
            data.get("method", DEFAULT_METHOD),
        )
        if not raw_timings:
            return None

        timings = {
            name: self._clean_time(raw_timings.get(name, ""))
            for name in PRAYER_NAMES
        }
        data["last_timings"] = timings
        data["last_fetch_date"] = today_str
        return timings

    # ------------------------------------------------------------------
    # Setup flow
    # ------------------------------------------------------------------
    async def _setup(self, existing_data: dict | None = None) -> dict | None:
        await self.capability_worker.speak(
            "I need your location to get accurate prayer times. "
            "What city and country are you in?"
        )
        user_input = await self.capability_worker.user_response()

        extraction = self.capability_worker.text_to_text_response(
            user_input,
            [],
            'Extract city and country from user text. '
            'Return ONLY: {"city": "...", "country": "..."} '
            'If unclear, use your best guess.',
        )
        city = ""
        country = ""
        try:
            ext = json.loads(extraction)
            city = ext.get("city", "").strip()
            country = ext.get("country", "").strip()
        except Exception:
            pass

        if not city:
            await self.capability_worker.speak(
                "Sorry, I couldn't determine your location. Please try again."
            )
            return None

        data = {
            "city": city,
            "country": country,
            "method": (existing_data or {}).get("method", DEFAULT_METHOD),
            "setup_at": int(time()),
        }
        await self._write_data(data)
        await self.capability_worker.speak(
            f"Location set to {city}, {country}. You can change this anytime."
        )
        return data

    # ------------------------------------------------------------------
    # Intent parsing
    # ------------------------------------------------------------------
    def _parse_intent(self, user_text: str) -> dict:
        try:
            resp = self.capability_worker.text_to_text_response(
                user_text, [], SYSTEM_PROMPT
            )
            return json.loads(resp)
        except Exception:
            return {"intent": "unknown"}

    # ------------------------------------------------------------------
    # Speak helpers
    # ------------------------------------------------------------------
    async def _speak_next_prayer(self, timings: dict, now: datetime) -> None:
        result = self._find_next_prayer(timings, now)
        if result:
            name, t = result
            await self.capability_worker.speak(
                f"The next prayer is {name} at {t}."
            )
        else:
            await self.capability_worker.speak(
                "All prayers for today have passed. "
                "Fajr will be the next prayer tomorrow."
            )

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------
    async def run(self):
        try:
            user_text = await self.capability_worker.wait_for_complete_transcription()

            data = await self._read_data()
            intent_data = self._parse_intent(user_text)
            intent = intent_data.get("intent", "unknown")

            # Handle setup intent or first-time use
            if intent == "setup" or not data.get("city"):
                if intent == "setup":
                    city = intent_data.get("city", "").strip()
                    country = intent_data.get("country", "").strip()
                    if city and country:
                        data = {
                            "city": city,
                            "country": country,
                            "method": data.get("method", DEFAULT_METHOD),
                            "setup_at": int(time()),
                        }
                        await self._write_data(data)
                        await self.capability_worker.speak(
                            f"Location set to {city}, {country}."
                        )
                    else:
                        data = await self._setup(data)
                elif not data.get("city"):
                    data = await self._setup(data)

                if not data or not data.get("city"):
                    return
                if intent == "setup":
                    return

            # Handle method change
            if intent == "method":
                method = intent_data.get("method", DEFAULT_METHOD)
                data["method"] = method
                await self._write_data(data)
                await self.capability_worker.speak(
                    f"Calculation method updated to {method}."
                )
                return

            # Get today's timings (cached or fresh)
            now = self._get_now()
            timings = self._get_timings(data, now)

            if not timings:
                await self.capability_worker.speak(
                    "Sorry, I couldn't fetch prayer times right now. "
                    "Please check your internet connection."
                )
                return

            # Write back only if data changed (new fetch)
            await self._write_data(data)

            if intent == "next_prayer":
                await self._speak_next_prayer(timings, now)

            elif intent == "all_times":
                formatted = self._format_all_times(timings)
                await self.capability_worker.speak(
                    f"Today's prayer times for {data['city']}: {formatted}"
                )

            elif intent == "specific":
                prayer = self._normalize_prayer(intent_data.get("prayer", ""))
                t = timings.get(prayer, "")
                if t:
                    await self.capability_worker.speak(
                        f"{prayer} is at {t} today."
                    )
                else:
                    await self.capability_worker.speak(
                        f"I couldn't find the time for {prayer}. "
                        f"Available prayers are: {', '.join(PRAYER_NAMES)}."
                    )

            else:
                await self._speak_next_prayer(timings, now)

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PrayerTimes] Error: {e}"
            )
            await self.capability_worker.speak(
                "Sorry, something went wrong. Please try again."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())
