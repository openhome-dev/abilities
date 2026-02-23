import json
import os
from datetime import datetime

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# ASTRONOMY & STARGAZING GUIDE
# Provides stargazing information using IPGeolocation Astronomy API and
# NASA APOD. Reports moon phase, sun/moon times, and LLM-enriched planet
# visibility info. Requires IPGEO_API_KEY env variable (free, 1000 req/day).
# NASA APOD uses DEMO_KEY by default.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
ASTRONOMY_URL = "https://api.ipgeolocation.io/astronomy"
NASA_APOD_URL = "https://api.nasa.gov/planetary/apod"

STARGAZING_PROMPT = (
    "You are an astronomy and stargazing guide. Given the following astronomical "
    "data for a location, create an engaging spoken summary for someone wanting "
    "to stargaze tonight. Include:\n"
    "1) Moon phase and how bright the sky will be\n"
    "2) Best time to observe (after astronomical twilight)\n"
    "3) What planets and constellations are likely visible based on the season "
    "and location\n"
    "Keep it to 3-4 conversational sentences. Be enthusiastic about astronomy."
)

APOD_PROMPT = (
    "Briefly describe this NASA Astronomy Picture of the Day in one "
    "conversational sentence suitable for voice. Title: {title}. "
    "Description: {explanation}"
)


class AstronomyGuideCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info(
                "[AstronomyGuide] Ability started"
            )

            ipgeo_key = os.environ.get("IPGEO_API_KEY", "")

            await self.capability_worker.speak(
                "Welcome to the stargazing guide! "
                "What's your location? I'll tell you what's in the sky tonight."
            )

            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                await self.capability_worker.speak(
                    "I didn't catch that. Try again later."
                )
                return

            if any(w in user_input.lower() for w in EXIT_WORDS):
                await self.capability_worker.speak("Clear skies! Goodbye.")
                return

            location = user_input.strip()
            await self.capability_worker.speak(
                f"Looking up the sky above {location}."
            )

            coords = self._geocode(location)
            if not coords:
                await self.capability_worker.speak(
                    "I couldn't find that location. Try a different city name."
                )
                return

            lat, lon = coords

            astro_data = self._fetch_astronomy(lat, lon, ipgeo_key)

            if astro_data:
                summary = self._build_stargazing_summary(
                    astro_data, location, lat, lon
                )
                await self.capability_worker.speak(summary)
            else:
                fallback = self._build_fallback_summary(location, lat, lon)
                await self.capability_worker.speak(fallback)

            apod = self._fetch_apod()
            if apod:
                await self.capability_worker.speak(
                    f"Also, today's NASA astronomy picture: {apod}"
                )

            await self.capability_worker.speak(
                "Want to know about a specific object in the sky? "
                "Ask me, or say done to exit."
            )

            follow_up = await self.capability_worker.user_response()
            if follow_up and follow_up.strip() and not any(
                w in follow_up.lower() for w in EXIT_WORDS
            ):
                try:
                    response = self.capability_worker.text_to_text_response(
                        f"The user is stargazing from {location} (lat {lat}, "
                        f"lon {lon}) on {datetime.now().strftime('%B %d, %Y')}. "
                        f"They asked: {follow_up}",
                        system_prompt=(
                            "You are an astronomy expert. Answer the user's "
                            "question about the night sky concisely in 2-3 "
                            "sentences for voice. Include practical observation "
                            "tips if relevant."
                        ),
                    )
                    await self.capability_worker.speak(response)
                except Exception as e:
                    self.worker.editor_logging_handler.error(
                        f"[AstronomyGuide] Follow-up error: {e}"
                    )

            await self.capability_worker.speak(
                "Happy stargazing! Clear skies to you."
            )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[AstronomyGuide] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing the astronomy guide."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[AstronomyGuide] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _geocode(self, location: str) -> tuple:
        try:
            resp = requests.get(
                GEOCODE_URL,
                params={"q": location, "format": "json", "limit": 1},
                headers={"User-Agent": "OpenHome-Astronomy-Ability"},
                timeout=5,
            )
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[AstronomyGuide] Geocoding error: {e}"
            )
        return None

    def _fetch_astronomy(self, lat: float, lon: float, api_key: str) -> dict:
        if not api_key:
            self.worker.editor_logging_handler.info(
                "[AstronomyGuide] No IPGEO_API_KEY, skipping astronomy API"
            )
            return None
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            resp = requests.get(
                ASTRONOMY_URL,
                params={
                    "apiKey": api_key,
                    "lat": lat,
                    "long": lon,
                    "date": today,
                },
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json()
            self.worker.editor_logging_handler.error(
                f"[AstronomyGuide] Astronomy API returned {resp.status_code}"
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[AstronomyGuide] Astronomy API error: {e}"
            )
        return None

    def _fetch_apod(self) -> str:
        try:
            nasa_key = os.environ.get("NASA_API_KEY", "DEMO_KEY")
            resp = requests.get(
                NASA_APOD_URL,
                params={"api_key": nasa_key},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title", "")
                explanation = data.get("explanation", "")[:300]
                try:
                    result = self.capability_worker.text_to_text_response(
                        APOD_PROMPT.format(title=title, explanation=explanation)
                    )
                    return result.strip()
                except Exception:
                    return f"{title}."
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[AstronomyGuide] NASA APOD error: {e}"
            )
        return ""

    def _build_stargazing_summary(
        self, astro_data: dict, location: str, lat: float, lon: float
    ) -> str:
        data_text = json.dumps(astro_data, indent=2)
        today = datetime.now().strftime("%B %d, %Y")
        prompt = (
            f"Location: {location} (lat {lat}, lon {lon})\n"
            f"Date: {today}\n"
            f"Astronomical data:\n{data_text}"
        )
        try:
            response = self.capability_worker.text_to_text_response(
                prompt, system_prompt=STARGAZING_PROMPT
            )
            return response
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[AstronomyGuide] Summary error: {e}"
            )
            moon_phase = astro_data.get("moon_phase", "unknown")
            return (
                f"Tonight in {location}, the moon phase is {moon_phase}. "
                "Check the sky after sunset for the best viewing."
            )

    def _build_fallback_summary(
        self, location: str, lat: float, lon: float
    ) -> str:
        today = datetime.now().strftime("%B %d, %Y")
        try:
            response = self.capability_worker.text_to_text_response(
                f"Location: {location} (lat {lat}, lon {lon}), Date: {today}. "
                f"What would be visible in the night sky tonight?",
                system_prompt=STARGAZING_PROMPT,
            )
            return response
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[AstronomyGuide] Fallback summary error: {e}"
            )
            return (
                f"I couldn't get detailed astronomy data for {location}, "
                "but the best stargazing is usually after 9 PM when the sky "
                "is fully dark. Look for prominent constellations like Orion."
            )
