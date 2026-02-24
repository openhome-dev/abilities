import json

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# AIR QUALITY & UV INDEX CHECKER
# Fetches air quality data from the WAQI API for a user-specified city.
# Reports AQI levels, individual pollutants, and health advice. Requires
# a free WAQI API token set as WAQI_API_TOKEN env variable.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

WAQI_BASE_URL = "https://api.waqi.info/feed"

SUMMARIZE_PROMPT = (
    "You are an air quality advisor. Given AQI data, provide a concise "
    "spoken summary including: 1) the overall AQI level and what it means, "
    "2) the dominant pollutant, 3) brief health advice. Use these ranges:\n"
    "0-50: Good. Enjoy outdoor activities.\n"
    "51-100: Moderate. Acceptable for most people.\n"
    "101-150: Unhealthy for sensitive groups. Reduce prolonged outdoor exertion.\n"
    "151-200: Unhealthy. Everyone may experience health effects.\n"
    "201-300: Very Unhealthy. Avoid outdoor activities.\n"
    "301+: Hazardous. Stay indoors.\n"
    "Keep response to 2-3 sentences for voice."
)


class AirQualityCheckerCapability(MatchingCapability):
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
                "[AirQuality] Ability started"
            )

            # Place your WAQI_API_KEY here
            api_token = "place your api key here"
            if not api_token:
                await self.capability_worker.speak(
                    "I need a WAQI API token to check air quality. "
                    "Please set the WAQI_API_TOKEN environment variable. "
                    "You can get a free token at aqicn.org."
                )
                return

            await self.capability_worker.speak(
                "I can check the air quality for any city. "
                "Which city would you like me to check?"
            )

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak(
                        "I didn't catch that. Which city should I check?"
                    )
                    continue

                if any(w in user_input.lower() for w in EXIT_WORDS):
                    await self.capability_worker.speak("Goodbye!")
                    break

                city = self._extract_city(user_input)
                await self.capability_worker.speak(
                    f"Checking air quality in {city}."
                )

                aqi_data = self._fetch_aqi(city, api_token)

                if aqi_data is None:
                    await self.capability_worker.speak(
                        f"I couldn't get air quality data for {city}. "
                        "Try a different city name or check back later."
                    )
                else:
                    summary = self._summarize(aqi_data, city)
                    await self.capability_worker.speak(summary)

                await self.capability_worker.speak(
                    "Want to check another city, or say done to exit?"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[AirQuality] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing the air quality checker."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[AirQuality] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _extract_city(self, user_input: str) -> str:
        try:
            result = self.capability_worker.text_to_text_response(
                f"Extract the city name from this text. Return ONLY the city name, "
                f"nothing else. Input: {user_input}"
            )
            cleaned = result.strip().strip('"').strip("'")
            if cleaned and len(cleaned) < 100:
                return cleaned
        except Exception:
            pass
        return user_input.strip()

    def _fetch_aqi(self, city: str, token: str) -> dict:
        try:
            resp = requests.get(
                f"{WAQI_BASE_URL}/{city}/",
                params={"token": token},
                timeout=5,
            )
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[AirQuality] WAQI API returned {resp.status_code}"
                )
                return None

            data = resp.json()
            if data.get("status") != "ok":
                self.worker.editor_logging_handler.error(
                    f"[AirQuality] WAQI API error: {data.get('data', 'unknown')}"
                )
                return None

            result = data.get("data", {})
            aqi = result.get("aqi")
            iaqi = result.get("iaqi", {})

            pollutants = {}
            for key in ("pm25", "pm10", "o3", "no2", "co", "so2"):
                val = iaqi.get(key, {}).get("v")
                if val is not None:
                    pollutants[key] = val

            dominant = result.get("dominentpol", "")

            return {
                "aqi": aqi,
                "pollutants": pollutants,
                "dominant_pollutant": dominant,
                "city": result.get("city", {}).get("name", city),
            }

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error(
                "[AirQuality] WAQI API timeout"
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[AirQuality] WAQI API error: {e}"
            )
            return None

    def _summarize(self, aqi_data: dict, city: str) -> str:
        data_text = json.dumps(aqi_data, indent=2)
        prompt = f"Air quality data for {city}:\n{data_text}"
        try:
            response = self.capability_worker.text_to_text_response(
                prompt, system_prompt=SUMMARIZE_PROMPT
            )
            return response
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[AirQuality] Summary error: {e}"
            )
            aqi = aqi_data.get("aqi", "unknown")
            return f"The air quality index in {city} is {aqi}."
