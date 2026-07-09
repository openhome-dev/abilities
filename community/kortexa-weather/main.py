"""OpenHome ability — Weather Display via Porch + Window.

Shows rich weather information on Window using json-render, with
automatic IP-based geolocation via Porch.

Trigger words: "weather", "what's the weather"
Requires: Porch + Window running on the user's Mac
"""

import json

import httpx

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

TAG = "[Weather]"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Light rain showers",
    81: "Moderate rain showers",
    82: "Heavy rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherDisplayCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            await self.capability_worker.speak("Checking the weather.")

            # Geolocate via the user's Mac (through Porch)
            location = await self._get_location()
            if not location:
                await self.capability_worker.speak(
                    "I can't find your location. Is Porch running?"
                )
                return

            city = location.get("city", "Unknown")
            region = location.get("region", "")
            lat, lon = self._parse_loc(location.get("loc", "0,0"))
            country = location.get("country", "")

            self.worker.editor_logging_handler.info(
                f"{TAG} Location: {city}, {region} ({lat}, {lon})"
            )

            # Use Fahrenheit for US, Celsius everywhere else
            use_fahrenheit = country == "US"

            # Fetch weather from Open-Meteo (no API key needed)
            weather = await self._fetch_weather(lat, lon, use_fahrenheit)
            if not weather:
                await self.capability_worker.speak(f"Sorry, couldn't get the weather for {city}.")
                return

            current = weather["current"]
            temp = round(current["temperature_2m"])
            feels_like = round(current["apparent_temperature"])
            humidity = round(current["relative_humidity_2m"])
            wind = round(current["wind_speed_10m"])
            uv = current.get("uv_index", 0)
            code = current.get("weather_code", 0)
            condition = WEATHER_CODES.get(code, "Unknown")
            unit = "F" if use_fahrenheit else "C"

            # Open Window and show weather card
            await self._window_cmd("window:open")
            await self.worker.session_tasks.sleep(1)

            spec = self._build_spec(
                city, region, temp, feels_like, humidity, wind, uv, condition, unit
            )
            await self._window_msg({"type": "render", "data": spec})

            # Speak a short summary
            await self.capability_worker.speak(
                f"It's {temp} degrees and {condition.lower()} in {city}. "
                f"Feels like {feels_like}, with {humidity} percent humidity."
            )

        except Exception as err:
            self.worker.editor_logging_handler.error(f"{TAG} error: {err}")
            await self.capability_worker.speak("Sorry, something went wrong with the weather.")
        finally:
            self.capability_worker.resume_normal_flow()

    # -- Geolocation via Porch --

    async def _get_location(self):
        """Get user's location via IP geolocation on their Mac."""
        try:
            response = await self.capability_worker.exec_local_command(
                "curl -s ipinfo.io/json", timeout=10.0
            )
            data = response.get("data", {}) if isinstance(response, dict) else {}
            stdout = data.get("stdout", "") if isinstance(data, dict) else str(data)
            if stdout:
                return json.loads(stdout)
        except Exception as err:
            self.worker.editor_logging_handler.error(f"{TAG} geoloc error: {err}")
        return None

    def _parse_loc(self, loc_str):
        """Parse 'lat,lon' string from ipinfo."""
        try:
            parts = loc_str.split(",")
            return float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            return 0.0, 0.0

    # -- Weather API --

    async def _fetch_weather(self, lat, lon, use_fahrenheit):
        """Fetch current weather from Open-Meteo (free, no API key)."""
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": ",".join([
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "weather_code",
                    "wind_speed_10m",
                    "uv_index",
                ]),
                "temperature_unit": "fahrenheit" if use_fahrenheit else "celsius",
                "wind_speed_unit": "mph" if use_fahrenheit else "kmh",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(OPEN_METEO_URL, params=params)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as err:
            self.worker.editor_logging_handler.error(f"{TAG} weather API error: {err}")
        return None

    # -- Window display --

    def _build_spec(self, city, region, temp, feels_like, humidity, wind, uv, condition, unit):
        """Build a json-render spec for the weather card."""
        location_label = f"{city}, {region}" if region else city
        wind_unit = "mph" if unit == "F" else "km/h"

        if uv <= 2:
            uv_label = f"UV Index: {uv} (Low)"
        elif uv <= 5:
            uv_label = f"UV Index: {uv} (Moderate)"
        else:
            uv_label = f"UV Index: {uv} (High)"

        return {
            "elements": [
                {
                    "component": "Stack",
                    "props": {"direction": "vertical", "gap": "lg", "align": "center"},
                    "children": [
                        # Location + condition
                        {
                            "component": "Stack",
                            "props": {"direction": "vertical", "gap": "sm", "align": "center"},
                            "children": [
                                {
                                    "component": "Text",
                                    "props": {"text": condition, "variant": "caption"},
                                },
                                {
                                    "component": "Heading",
                                    "props": {"text": f"{temp}\u00b0{unit}", "level": "h1"},
                                },
                                {
                                    "component": "Text",
                                    "props": {"text": location_label},
                                },
                                {
                                    "component": "Text",
                                    "props": {"text": f"Feels like {feels_like}\u00b0{unit}", "variant": "muted"},
                                },
                            ],
                        },
                        # Separator
                        {"component": "Separator"},
                        # Details grid
                        {
                            "component": "Grid",
                            "props": {"columns": 2, "gap": "md"},
                            "children": [
                                {
                                    "component": "Stack",
                                    "props": {"direction": "vertical", "gap": "sm", "align": "center"},
                                    "children": [
                                        {"component": "Text", "props": {"text": "Wind", "variant": "caption"}},
                                        {"component": "Heading", "props": {"text": f"{wind} {wind_unit}", "level": "h3"}},
                                    ],
                                },
                                {
                                    "component": "Stack",
                                    "props": {"direction": "vertical", "gap": "sm", "align": "center"},
                                    "children": [
                                        {"component": "Text", "props": {"text": "Humidity", "variant": "caption"}},
                                        {"component": "Heading", "props": {"text": f"{humidity}%", "level": "h3"}},
                                    ],
                                },
                            ],
                        },
                        # UV bar
                        {
                            "component": "Stack",
                            "props": {"direction": "vertical", "gap": "sm"},
                            "children": [
                                {"component": "Text", "props": {"text": uv_label, "variant": "muted"}},
                                {"component": "Progress", "props": {"value": min(int(uv * 10), 100)}},
                            ],
                        },
                    ],
                }
            ]
        }

    async def _window_cmd(self, cmd):
        """Send a window management command via Porch."""
        try:
            await self.capability_worker.exec_local_command(cmd, timeout=5.0)
        except Exception:
            pass  # Porch/Window not running, that's fine

    async def _window_msg(self, msg):
        """Send a display message to Window via Porch."""
        try:
            await self.capability_worker.exec_local_command(
                "window:" + json.dumps(msg), timeout=5.0
            )
        except Exception:
            pass
