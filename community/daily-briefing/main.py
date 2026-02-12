import json
import os

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


# ── Default location (New York) — user can change via voice ──────────
DEFAULT_LAT = 40.71
DEFAULT_LON = -74.01
DEFAULT_CITY = "New York"

# ── Free API endpoints (no keys needed) ──────────────────────────────
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
QUOTE_URL = "https://zenquotes.io/api/today"
FACT_URL = "https://uselessfacts.jsph.pl/api/v2/facts/today"

# ── WMO weather codes → plain English ────────────────────────────────
WEATHER_DESCRIPTIONS = {
    0: "clear skies",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "rain showers",
    82: "heavy rain showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "thunderstorms with heavy hail",
}

# ── Well-known cities for quick location matching ────────────────────
CITY_COORDS = {
    "new york": (40.71, -74.01),
    "los angeles": (34.05, -118.24),
    "chicago": (41.88, -87.63),
    "houston": (29.76, -95.37),
    "phoenix": (33.45, -112.07),
    "san francisco": (37.77, -122.42),
    "seattle": (47.61, -122.33),
    "miami": (25.76, -80.19),
    "boston": (42.36, -71.06),
    "denver": (39.74, -104.98),
    "austin": (30.27, -97.74),
    "dallas": (32.78, -96.80),
    "atlanta": (33.75, -84.39),
    "london": (51.51, -0.13),
    "paris": (48.86, 2.35),
    "tokyo": (35.68, 139.69),
    "sydney": (-33.87, 151.21),
    "toronto": (43.65, -79.38),
    "dubai": (25.20, 55.27),
    "singapore": (1.35, 103.82),
    "berlin": (52.52, 13.41),
    "mumbai": (19.08, 72.88),
    "cairo": (30.04, 31.24),
    "rome": (41.90, 12.50),
    "istanbul": (41.01, 28.98),
    "lahore": (31.55, 74.35),
    "karachi": (24.86, 67.01),
    "islamabad": (33.69, 73.04),
}

# ── Briefing LLM prompt ─────────────────────────────────────────────
BRIEFING_PROMPT = (
    "You are a friendly morning radio host. Weave the following data into a "
    "natural, conversational 3-sentence morning briefing. Be warm and brief. "
    "Do NOT use bullet points or labels. Just talk like a person giving a "
    "quick morning update.\n\n"
    "Weather: {weather}\n"
    "Quote of the day: \"{quote}\" — {author}\n"
    "Fun fact: {fact}\n\n"
    "Start with 'Good morning!' and keep the whole thing under 50 words."
)

DETAIL_PROMPT = (
    "The user wants to know more about: {topic}. "
    "Here is the raw data:\n{data}\n\n"
    "Give a 2-sentence conversational expansion. Keep it voice-friendly."
)


class DailyBriefingCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

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
            category=data.get("category", "normal"),
        )

    # ── API helpers ──────────────────────────────────────────────────

    def fetch_weather(self, lat, lon):
        try:
            resp = requests.get(
                WEATHER_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weathercode",
                    "temperature_unit": "fahrenheit",
                    "timezone": "auto",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current", {})
                temp = current.get("temperature_2m")
                code = current.get("weathercode", 0)
                desc = WEATHER_DESCRIPTIONS.get(code, "mixed conditions")
                return {
                    "temp": temp,
                    "description": desc,
                    "raw": f"{temp} degrees Fahrenheit with {desc}",
                }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Weather API error: {e}")
        return None

    def fetch_quote(self):
        try:
            resp = requests.get(QUOTE_URL, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    return {
                        "quote": data[0].get("q", ""),
                        "author": data[0].get("a", "Unknown"),
                    }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Quote API error: {e}")
        return None

    def fetch_fun_fact(self):
        try:
            resp = requests.get(FACT_URL, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return {"fact": data.get("text", "")}
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Fact API error: {e}")
        return None

    # ── Location helper ──────────────────────────────────────────────

    def resolve_city(self, user_input):
        text = user_input.lower().strip()
        for city, (lat, lon) in CITY_COORDS.items():
            if city in text:
                return city.title(), lat, lon

        # LLM fallback to extract city name
        try:
            prompt = (
                f"The user said: '{user_input}'. "
                "Extract ONLY the city name. Return ONLY the city name, nothing else. "
                "If no city is mentioned, return 'none'."
            )
            result = self.capability_worker.text_to_text_response(prompt).strip().lower()
            if result and result != "none":
                for city, (lat, lon) in CITY_COORDS.items():
                    if city in result or result in city:
                        return city.title(), lat, lon
        except Exception:
            pass
        return None, None, None

    # ── Command detection ────────────────────────────────────────────

    def detect_command(self, user_input):
        text = user_input.lower().strip()

        if any(w in text for w in ("stop", "exit", "quit", "done", "bye", "no", "leave")):
            return "exit"
        if any(w in text for w in ("weather", "temperature", "forecast", "outside")):
            return "weather"
        if any(w in text for w in ("quote", "motivation", "inspire", "wisdom")):
            return "quote"
        if any(w in text for w in ("fact", "trivia", "history", "random")):
            return "fact"
        if any(w in text for w in ("change", "city", "location", "switch", "set")):
            return "location"
        if any(w in text for w in ("again", "repeat", "briefing", "morning", "full", "summary")):
            return "repeat"

        return "unknown"

    # ── Build and deliver the briefing ───────────────────────────────

    async def deliver_briefing(self, lat, lon, city_name):
        await self.capability_worker.speak("One moment, getting your morning update.")

        weather = self.fetch_weather(lat, lon)
        quote = self.fetch_quote()
        fact = self.fetch_fun_fact()

        # Store for "tell me more" follow-ups
        self.last_weather = weather
        self.last_quote = quote
        self.last_fact = fact

        weather_str = weather["raw"] if weather else "weather data unavailable"
        quote_str = quote["quote"] if quote else "Stay positive and keep going"
        author_str = quote["author"] if quote else "Anonymous"
        fact_str = fact["fact"] if fact else "No fun fact available right now"

        prompt = BRIEFING_PROMPT.format(
            weather=f"{weather_str} in {city_name}",
            quote=quote_str,
            author=author_str,
            fact=fact_str,
        )

        try:
            briefing = self.capability_worker.text_to_text_response(prompt)
            await self.capability_worker.speak(briefing)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"LLM briefing error: {e}")
            # Fallback: speak raw data directly
            await self.capability_worker.speak(
                f"Good morning! It's {weather_str} in {city_name}. "
                f"Here's your quote: {quote_str}, by {author_str}. "
                f"Fun fact: {fact_str}"
            )

    # ── Detail follow-ups ────────────────────────────────────────────

    async def expand_topic(self, topic, data):
        try:
            prompt = DETAIL_PROMPT.format(topic=topic, data=json.dumps(data))
            detail = self.capability_worker.text_to_text_response(prompt)
            await self.capability_worker.speak(detail)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Detail expand error: {e}")
            await self.capability_worker.speak("Sorry, I couldn't get more details on that.")

    # ── Main flow ────────────────────────────────────────────────────

    async def run_daily_briefing(self):
        lat = DEFAULT_LAT
        lon = DEFAULT_LON
        city_name = DEFAULT_CITY

        self.last_weather = None
        self.last_quote = None
        self.last_fact = None

        # Check if trigger phrase mentions a city
        if self.initial_request:
            found_city, found_lat, found_lon = self.resolve_city(self.initial_request)
            if found_city:
                city_name = found_city
                lat = found_lat
                lon = found_lon

        # Deliver the main briefing
        await self.deliver_briefing(lat, lon, city_name)

        # Interaction loop — let user ask follow-ups or exit
        max_turns = 10
        for _ in range(max_turns):
            try:
                response = await self.capability_worker.run_io_loop(
                    "Want details on weather, quote, or fact? Or say done."
                )

                if not response:
                    continue

                command = self.detect_command(response)

                if command == "exit":
                    await self.capability_worker.speak("Have a great day!")
                    break

                elif command == "weather":
                    if self.last_weather:
                        await self.expand_topic("weather", self.last_weather)
                    else:
                        await self.capability_worker.speak("Weather data wasn't available.")

                elif command == "quote":
                    if self.last_quote:
                        await self.expand_topic("quote", self.last_quote)
                    else:
                        await self.capability_worker.speak("Quote data wasn't available.")

                elif command == "fact":
                    if self.last_fact:
                        await self.expand_topic("fun fact", self.last_fact)
                    else:
                        await self.capability_worker.speak("Fun fact wasn't available.")

                elif command == "location":
                    city_response = await self.capability_worker.run_io_loop(
                        "Which city would you like the briefing for?"
                    )
                    found_city, found_lat, found_lon = self.resolve_city(city_response)
                    if found_city:
                        city_name = found_city
                        lat = found_lat
                        lon = found_lon
                        await self.deliver_briefing(lat, lon, city_name)
                    else:
                        await self.capability_worker.speak(
                            "I don't recognize that city yet. Try a major city name."
                        )

                elif command == "repeat":
                    await self.deliver_briefing(lat, lon, city_name)

                else:
                    await self.capability_worker.speak(
                        "You can say weather, quote, fact, change city, or done."
                    )

            except Exception as e:
                self.worker.editor_logging_handler.error(f"Loop error: {e}")
                break

        self.capability_worker.resume_normal_flow()

    # ── Entry point ──────────────────────────────────────────────────

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        # Grab the triggering transcription
        self.initial_request = None
        try:
            self.initial_request = worker.transcription
        except (AttributeError, Exception):
            pass
        if not self.initial_request:
            try:
                self.initial_request = worker.last_transcription
            except (AttributeError, Exception):
                pass
        if not self.initial_request:
            try:
                self.initial_request = worker.current_transcription
            except (AttributeError, Exception):
                pass

        self.worker.session_tasks.create(self.run_daily_briefing())
