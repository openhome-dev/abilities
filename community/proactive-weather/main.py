import asyncio
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
Plain spoken English only. No markdown, no bullet points, no lists, no formatting.
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
        """Extract city name from user text using LLM."""
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

    def is_update_city_intent(self, text: str) -> bool:
        """Check if user wants to change their saved city."""
        result = self.capability_worker.text_to_text_response(
            f"Does this text mean the user wants to change, update, or switch their weather city/location? "
            f"Examples that mean YES: 'change my city', 'update my location', 'switch to London', "
            f"'set my city to Paris', 'use a different city'. "
            f"Examples that mean NO: 'what's the weather', 'will it rain', 'weather in Tokyo'. "
            f'Text: "{text}"\nReply YES or NO only.'
        )
        return result.strip().upper().startswith("Y")

    def get_saved_location(self) -> str:
        """Get saved city from KV storage, or empty string."""
        saved = self.capability_worker.get_single_key(LOCATION_KEY)
        saved_value = saved.get("value") if saved else None
        if saved_value and saved_value.get("city"):
            return saved_value["city"]
        return ""

    def save_location(self, city: str):
        """Save city to KV storage using create-or-update pattern."""
        existing = self.capability_worker.get_single_key(LOCATION_KEY)
        if existing and existing.get("value"):
            self.capability_worker.update_key(LOCATION_KEY, {"city": city})
        else:
            self.capability_worker.create_key(LOCATION_KEY, {"city": city})
        self.worker.editor_logging_handler.info(f"[Weather] Saved location: {city}")

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[Weather] Trigger: {trigger}")

            # Check if user wants to update their city
            if trigger and self.is_update_city_intent(trigger):
                await self.handle_update_city(trigger)
                return

            # Check for saved location
            location = self.get_saved_location()

            if location:
                # Check if trigger mentions a different city (one-time override)
                extracted = self.parse_location(trigger) if trigger else ""
                if extracted and extracted.lower() != location.lower():
                    # User asked about a specific city — use it but don't overwrite saved
                    location = extracted
                await self.capability_worker.speak(f"Checking the weather in {location}.")
            else:
                # No saved location — try to extract from trigger
                extracted = self.parse_location(trigger) if trigger else ""
                if extracted:
                    location = extracted
                else:
                    raw = await self.capability_worker.run_io_loop(
                        "Which city would you like the weather for?"
                    )
                    location = self.parse_location(raw)
                    if not location:
                        await self.capability_worker.speak("I didn't catch that. Try again later.")
                        return

                # Ask if they want to save this city
                save = await self.capability_worker.run_confirmation_loop(
                    f"Would you like me to remember {location} for future weather checks?"
                )
                if save:
                    self.save_location(location)
                    await self.capability_worker.speak(f"Saved. Checking {location}.")
                else:
                    await self.capability_worker.speak(f"No problem. Checking {location}.")

            # Geocode
            lat, lon = await asyncio.to_thread(self.geocode, location)
            if lat is None:
                await self.capability_worker.speak(
                    "I couldn't find that location. Try a different city name."
                )
                return

            # Fetch weather
            weather_data = await asyncio.to_thread(self.fetch_weather, lat, lon)
            if not weather_data:
                await self.capability_worker.speak(
                    "Sorry, I couldn't get the weather right now."
                )
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

    async def handle_update_city(self, trigger: str):
        """Handle user intent to change their saved city."""
        current = self.get_saved_location()

        # Try to extract new city from trigger (e.g. "change my city to London")
        new_city = self.parse_location(trigger)

        if not new_city:
            raw = await self.capability_worker.run_io_loop(
                "Which city would you like to switch to?"
            )
            new_city = self.parse_location(raw)
            if not new_city:
                await self.capability_worker.speak("I didn't catch that.")
                return

        if current:
            confirm = await self.capability_worker.run_confirmation_loop(
                f"Change your weather city from {current} to {new_city}?"
            )
        else:
            confirm = await self.capability_worker.run_confirmation_loop(
                f"Save {new_city} as your weather city?"
            )

        if confirm:
            self.save_location(new_city)
            await self.capability_worker.speak(f"Done. {new_city} is your weather city now.")
        else:
            await self.capability_worker.speak("Okay, no changes.")

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
