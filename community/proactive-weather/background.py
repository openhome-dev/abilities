import json
import requests
from time import time
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
LOCATION_KEY = "weather_user_location"
WEATHER_JSON = "weather_data.json"
WEATHER_MD = "local_weather.md"
ALERTS_JSON = "weather_alerts_state.json"
POLL_INTERVAL = 600.0  # 10 minutes

SEVERE_CODES = {
    55, 56, 57,
    65, 66, 67,
    75, 77,
    82,
    85, 86,
    95, 96, 99,
}

WMO_DESCRIPTIONS = {
    55: "heavy drizzle", 56: "light freezing drizzle", 57: "dense freezing drizzle",
    65: "heavy rain", 66: "light freezing rain", 67: "heavy freezing rain",
    75: "heavy snowfall", 77: "snow grains",
    82: "violent rain showers",
    85: "heavy snow showers", 86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}

ALERT_PROMPT = """
Severe weather detected: {description}.
Current conditions: {current}.
Write a short 1-2 sentence calm but urgent voice alert to warn the user.
Plain spoken English only. No markdown, no lists, no formatting, no codes or numbers the user wouldn't understand.
"""

WEATHER_MD_PROMPT = """
Here is current weather data: {weather_data} for {location}.
Write a concise markdown summary (under 200 words) for a voice assistant's background context.
Use bullet points under a ## header. Include: current conditions, today's high/low,
precipitation outlook, and any active severe conditions. Write current state only, not history.
"""


class WeatheralertCapabilityBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.watch_weather())

    async def watch_weather(self):
        self.worker.editor_logging_handler.info(f"[WeatherDaemon] Started at {time()}")

        # Clear stale files from previous session before first cycle
        await self.clear_stale_files()

        while True:
            try:
                saved = self.capability_worker.get_single_key(LOCATION_KEY)
                saved_value = saved.get("value") if saved else None
                if saved_value and saved_value.get("city"):
                    lat, lon = self.geocode(saved_value["city"])
                    if lat is not None:
                        weather_data = self.fetch_weather(lat, lon)
                        if weather_data:
                            await self.check_for_alerts(weather_data)
                            await self.write_weather_md(saved_value["city"], weather_data)
                else:
                    self.worker.editor_logging_handler.info(
                        "[WeatherDaemon] No saved location yet, skipping poll."
                    )
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[WeatherDaemon] Loop error: {e}")

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    async def clear_stale_files(self):
        """Clear .md and alerts state from previous session on startup."""
        for filename in [WEATHER_MD, ALERTS_JSON]:
            try:
                exists = await self.capability_worker.check_if_file_exists(filename, in_ability_directory=False)
                if exists:
                    await self.capability_worker.delete_file(filename, in_ability_directory=False)
                    self.worker.editor_logging_handler.info(
                        f"[WeatherDaemon] Cleared stale file: {filename}"
                    )
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[WeatherDaemon] Failed to clear {filename}: {e}"
                )

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
            self.worker.editor_logging_handler.error(f"[WeatherDaemon] Geocode failed: {e}")
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
            self.worker.editor_logging_handler.error(f"[WeatherDaemon] Fetch failed: {e}")
            return None

    async def check_for_alerts(self, weather_data: dict):
        try:
            current = weather_data.get("current", {})
            code = current.get("weathercode")
            if code not in SEVERE_CODES:
                return

            # Load dedup state
            fired_codes = []
            exists = await self.capability_worker.check_if_file_exists(ALERTS_JSON, False)
            if exists:
                raw = await self.capability_worker.read_file(ALERTS_JSON, False)
                try:
                    fired_codes = json.loads(raw).get("fired_codes", [])
                except Exception:
                    fired_codes = []

            if code in fired_codes:
                return

            # Generate and speak alert
            description = WMO_DESCRIPTIONS.get(code, "severe weather")
            alert_text = self.capability_worker.text_to_text_response(
                ALERT_PROMPT.format(
                    description=description,
                    current=json.dumps(current),
                )
            )
            await self.capability_worker.send_interrupt_signal()
            await self.capability_worker.speak(alert_text)

            # Save fired code to dedup state (delete-before-write)
            fired_codes.append(code)
            if await self.capability_worker.check_if_file_exists(ALERTS_JSON, False):
                await self.capability_worker.delete_file(ALERTS_JSON, False)
            await self.capability_worker.write_file(ALERTS_JSON, json.dumps({"fired_codes": fired_codes}), False)
            self.worker.editor_logging_handler.info(f"[WeatherDaemon] Fired alert for code {code}")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[WeatherDaemon] Alert error: {e}")

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
