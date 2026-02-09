import json
import os
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# WEATHER
# Fetches current weather for a user-specified location using the free
# Open-Meteo API and Nominatim geocoding. No API key required.
# =============================================================================

GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

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
        self.worker.session_tasks.create(self.get_weather())

    async def get_weather(self):
        # Ask for location
        await self.capability_worker.speak("Which city would you like the weather for?")
        location = await self.capability_worker.user_response()

        if not location:
            await self.capability_worker.speak("I didn't catch that. Please try again later.")
            self.capability_worker.resume_normal_flow()
            return

        await self.capability_worker.speak(f"Checking the weather in {location}.")

        try:
            # Geocode the location
            geo_resp = requests.get(
                GEOCODE_URL,
                params={"q": location, "format": "json", "limit": 1},
                headers={"User-Agent": "OpenHome-Weather-Ability"},
            )
            geo_data = geo_resp.json()

            if not geo_data:
                await self.capability_worker.speak(
                    "I couldn't find that location. Try a different city name."
                )
                self.capability_worker.resume_normal_flow()
                return

            lat = geo_data[0]["lat"]
            lon = geo_data[0]["lon"]
            display_name = geo_data[0].get("display_name", location)

            # Fetch weather
            weather_resp = requests.get(
                WEATHER_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,wind_speed_10m",
                },
            )
            weather_data = weather_resp.json()
            current = weather_data.get("current", {})
            temp = current.get("temperature_2m", "unknown")
            wind = current.get("wind_speed_10m", "unknown")

            report = (
                f"The current temperature in {location} is {temp} degrees Celsius "
                f"with wind speeds of {wind} kilometers per hour."
            )
            await self.capability_worker.speak(report)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Weather] Error: {e}")
            await self.capability_worker.speak(
                "Sorry, I couldn't get the weather right now. Try again later."
            )

        self.capability_worker.resume_normal_flow()
