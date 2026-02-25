import json
from datetime import datetime, timedelta

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# EARTHQUAKE & SEISMIC MONITOR
# Fetches recent earthquake data from the USGS API for a user-specified
# location. Uses Nominatim geocoding (same as official/weather). No API key.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

SUMMARIZE_PROMPT = (
    "You are an earthquake information assistant. Summarize the following "
    "earthquake data for a voice response. Be concise and informative. "
    "Mention the number of earthquakes, the strongest one (magnitude, location, "
    "and how long ago), and any notable patterns. Keep it to 2-3 sentences."
)


class EarthquakeMonitorCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info(
                "[EarthquakeMonitor] Ability started"
            )

            await self.capability_worker.speak(
                "I can check for recent earthquakes near any location. "
                "What area would you like me to check?"
            )

            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                await self.capability_worker.speak(
                    "I didn't catch that. Try again later."
                )
                return

            if any(w in user_input.lower() for w in EXIT_WORDS):
                await self.capability_worker.speak("Goodbye!")
                return

            location = user_input.lower()

            # Remove trigger words
            location = location.replace("earthquake", "")
            location = location.replace("earthquakes", "")

            # Clean punctuation
            location = location.replace(".", " ").strip()

            # Normalize spaces
            location = " ".join(location.split())

            await self.capability_worker.speak(
                f"Checking for earthquakes near {location}."
            )

            coords = self._geocode(location)
            if not coords:
                await self.capability_worker.speak(
                    "I couldn't find that location. Try a different city name."
                )
                return

            lat, lon = coords

            quakes = self._fetch_earthquakes(lat, lon)

            if quakes is None:
                await self.capability_worker.speak(
                    "Sorry, I couldn't reach the earthquake database right now. "
                    "Try again later."
                )
                return

            if not quakes:
                await self.capability_worker.speak(
                    f"Good news! No significant earthquakes detected near "
                    f"{location} in the past week."
                )
                return

            summary = self._summarize(quakes, location)
            await self.capability_worker.speak(summary)

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[EarthquakeMonitor] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong checking earthquakes. Try again later."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[EarthquakeMonitor] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _geocode(self, location: str) -> tuple:
        try:
            resp = requests.get(
                GEOCODE_URL,
                params={"q": location, "format": "json", "limit": 1},
                headers={"User-Agent": "OpenHome-Earthquake-Ability"},
                timeout=5,
            )
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[EarthquakeMonitor] Geocoding error: {e}"
            )
        return None

    def _fetch_earthquakes(self, lat: float, lon: float) -> list:
        try:
            start_time = (datetime.utcnow() - timedelta(days=7)).strftime(
                "%Y-%m-%d"
            )
            resp = requests.get(
                USGS_URL,
                params={
                    "format": "geojson",
                    "starttime": start_time,
                    "latitude": lat,
                    "longitude": lon,
                    "maxradiuskm": 500,
                    "minmagnitude": 2.5,
                    "orderby": "time",
                    "limit": 5,
                },
                timeout=5,
            )
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[EarthquakeMonitor] USGS API returned {resp.status_code}"
                )
                return None

            data = resp.json()
            features = data.get("features", [])

            quakes = []
            for f in features:
                props = f.get("properties", {})
                quakes.append({
                    "magnitude": props.get("mag", 0),
                    "place": props.get("place", "Unknown location"),
                    "time": props.get("time", 0),
                })
            return quakes

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error(
                "[EarthquakeMonitor] USGS API timeout"
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[EarthquakeMonitor] USGS API error: {e}"
            )
            return None

    def _summarize(self, quakes: list, location: str) -> str:
        quake_text = json.dumps(quakes, indent=2)
        prompt = (
            f"Location searched: {location}\n"
            f"Earthquakes found in the past 7 days:\n{quake_text}"
        )
        try:
            response = self.capability_worker.text_to_text_response(
                prompt, system_prompt=SUMMARIZE_PROMPT
            )
            return response
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[EarthquakeMonitor] Summary error: {e}"
            )
            strongest = max(quakes, key=lambda q: q.get("magnitude", 0))
            return (
                f"I found {len(quakes)} earthquakes near {location} this week. "
                f"The strongest was magnitude {strongest['magnitude']} "
                f"at {strongest['place']}."
            )
