import json
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
LOCATION_KEY = "weather_user_location"
WEATHER_JSON = "weather_data.json"
WEATHER_MD = "local_weather.md"

SUMMARIZE_PROMPT = """
Here is current weather data: {weather_data}.
Summarize in 2-3 sentences, voice-friendly. Only mention what affects the user's day:
temperature, precipitation, wind if notable, and anything severe.
Do not read out every field. Keep it natural and conversational.
"""

WEATHER_MD_PROMPT = """
Here is current weather data: {weather_data} for {location}.
Write a concise markdown summary (under 200 words) for a voice assistant's background context.
Use bullet points under a ## header. Include: current conditions, today's high/low,
precipitation outlook, and any active severe conditions. Write current state only, not history.
"""


class WeatherCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def parse_location(self, raw: str) -> str:
        result = self.capability_worker.text_to_text_response(
            f"Extract ONLY the city name from this text: '{raw}'. "
            "Reply with the city name only — no other words, no punctuation, no explanation. "
            "Examples: 'Los Angeles' or 'London' or 'Chicago, IL'. "
            "If there is absolutely no city mentioned, reply with exactly: NONE"
        )
        result = result.strip()
        if result.upper() == "NONE" or not result:
            return ""
        return result

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            # confirm location is persistently saved
            trigger = await self.capability_worker.wait_for_complete_transcription()
            saved = self.capability_worker.get_single_key(LOCATION_KEY)
            self.worker.editor_logging_handler.info(f"[Weather] get_single_key returned: {saved}")

            # Check if we have a saved location
            saved = self.capability_worker.get_single_key(LOCATION_KEY)
            saved_value = saved.get("value") if saved else None
            if saved_value and saved_value.get("city"):
                location = saved_value["city"]
                await self.capability_worker.speak(f"Checking the weather in {location}.")
            else:
                # Try to extract location from the trigger phrase first
                extracted = self.parse_location(trigger)
                if extracted:
                    location = extracted
                    self.capability_worker.create_key(LOCATION_KEY, {"city": location})
                    await self.capability_worker.speak(f"Checking the weather in {location}.")
                else:
                    # Nothing in trigger, ask explicitly
                    raw = await self.capability_worker.run_io_loop(
                        "Which city would you like the weather for?"
                    )
                    location = self.parse_location(raw)
                    if not location:
                        await self.capability_worker.speak("I didn't catch that. Try again later.")
                        self.capability_worker.resume_normal_flow()
                        return
                    self.capability_worker.create_key(LOCATION_KEY, {"city": location})
                    self.worker.editor_logging_handler.info(f"[Weather] Saved location: {location}")  # confirm location is saved
                    await self.capability_worker.speak(f"Got it, checking {location}.")

            # Geocode
            lat, lon = self.geocode(location)
            if lat is None:
                await self.capability_worker.speak(
                    "I couldn't find that location. Try a different city name."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Fetch weather
            weather_data = self.fetch_weather(lat, lon)
            if not weather_data:
                await self.capability_worker.speak(
                    "Sorry, I couldn't get the weather right now."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Speak a concise summary
            summary = self.capability_worker.text_to_text_response(
                SUMMARIZE_PROMPT.format(weather_data=json.dumps(weather_data))
            )
            await self.capability_worker.speak(summary)

            # Write local_weather.md for the Memory Watcher
            await self.write_weather_md(location, weather_data)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Weather] Error: {e}")
            await self.capability_worker.speak("Sorry, something went wrong.")
        finally:
            self.capability_worker.resume_normal_flow()

    def geocode(self, location: str):
        try:
            resp = requests.get(
                GEOCODE_URL,
                params={"q": location, "format": "json", "limit": 1},
                headers={"User-Agent": "OpenHome-Weather-Ability"},
                timeout=10,
            )
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Weather] Geocode failed: {e}")
        return None, None

    def fetch_weather(self, lat: float, lon: float) -> dict:
        try:
            resp = requests.get(
                WEATHER_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weathercode,windspeed_10m,precipitation",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                    "temperature_unit": "fahrenheit",
                    "forecast_days": 1,
                    "timezone": "auto",
                },
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Weather] Fetch failed: {e}")
            return None

    async def write_weather_md(self, location: str, weather_data: dict):
        """Write local_weather.md for Memory Watcher injection into Personality prompt."""
        try:
            content = self.capability_worker.text_to_text_response(
                WEATHER_MD_PROMPT.format(
                    weather_data=json.dumps(weather_data),
                    location=location
                )
            )

            # required write pattern for context files
            exists = await self.capability_worker.check_if_file_exists(WEATHER_MD, in_ability_directory=False)
            if exists:
                await self.capability_worker.delete_file(WEATHER_MD, in_ability_directory=False)
            await self.capability_worker.write_file(WEATHER_MD, content, in_ability_directory=False)

            self.worker.editor_logging_handler.info("[Weather] Wrote local_weather.md")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Weather] Failed to write md: {e}")
