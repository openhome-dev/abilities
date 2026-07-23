import asyncio
import random
import requests
import string
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# N2YO key is fetched at runtime via get_api_keys("n2yo_api_key") — see
# _handle_location. Register it in the OpenHome dashboard under Settings ->
# API Keys; without it, location queries fall back to the cached demo data.
N2YO_URL = "https://api.n2yo.com/rest/v1/satellite/positions/25544/0/0/0/1/?apiKey="

SPACEDEVS_ASTRONAUTS = "https://ll.thespacedevs.com/2.2.0/astronaut/"
OPEN_NOTIFY_CREW = "http://api.open-notify.org/astros.json"
OPEN_NOTIFY_PASS = "http://api.open-notify.org/iss-pass.json"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"

EXIT_WORDS = {
    "done", "stop", "quit", "exit", "goodbye", "bye",
    "that's all", "i'm good", "im good", "orbit out", "over",
}

FILLER_LINES = [
    "Let me check.",
    "One sec.",
    "Hang on.",
    "Pulling that up.",
    "Checking the tracker.",
]

# Cached fallback data
DEMO_LOCATION = {
    "lat": -14.32404794,
    "lon": -72.97013892,
    "velocity_mph": 17134,
    "altitude_km": 423.4,
    "name": "Peru",
}

# Fallback crew data
DEMO_CREW = {
    "number": 10,
    "names": [
        "Sergey Kud-Sverchkov", "Christopher Williams", "Sergey Mikayev",
        "Jessica Meir", "Jack Hathaway", "Andrei Fedyaev",
        "Sophie Adenot", "Anna Kikina", "Pyotr Dubrov", "Anil Menon",
    ],
}

DEMO_COORDS: Dict[str, Tuple[float, float]] = {
    "new york": (40.7128, -74.0060),
    "islamabad": (33.6844, 73.0479),
    "london": (51.5074, -0.1278),
    "tokyo": (35.6762, 139.6503),
    "paris": (48.8566, 2.3522),
    "sydney": (-33.8688, 151.2093),
    "dubai": (25.2048, 55.2708),
    "los angeles": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "miami": (25.7617, -80.1918),
    "san francisco": (37.7749, -122.4194),
    "boston": (42.3601, -71.0589),
    "seattle": (47.6062, -122.3321),
    "toronto": (43.6532, -79.3832),
    "berlin": (52.5200, 13.4050),
    "mumbai": (19.0760, 72.8777),
    "beijing": (39.9042, 116.4074),
    "singapore": (1.3521, 103.8198),
    "rio de janeiro": (-22.9068, -43.1729),
    "cairo": (30.0444, 31.2357),
    "lahore": (31.5204, 74.3587),
    "rawalpindi": (33.5651, 73.0169),
    "karachi": (24.8607, 67.0011),
}

# ISS facts by category
ISS_FACTS_SIZE = "The ISS is 109 meters long, about the size of a football field. It weighs 420 tons and has been continuously occupied since November 2000."
ISS_FACTS_SPEED = "The space station travels at 5 miles per second. That is 17,500 miles per hour, fast enough to circle Earth in 90 minutes."
ISS_FACTS_SOLAR = "Solar arrays on the ISS cover an area larger than a basketball court, generating about 120 kilowatts of electricity."
ISS_FACTS_INSIDE = "The ISS has 932 cubic meters of living space, about the same as a five-bedroom house. It has two bathrooms, a gym, and a 360-degree window called the Cupola."
ISS_FACTS_GENERAL = "The ISS has been visited by over 270 astronauts from 20 countries. It is the most complex machine ever built by humans."

ISS_FACTS_ALL = [
    ISS_FACTS_SIZE,
    ISS_FACTS_SPEED,
    ISS_FACTS_SOLAR,
    ISS_FACTS_INSIDE,
    ISS_FACTS_GENERAL,
]

# -----------------------------------------------------------------------------
# Capability
# -----------------------------------------------------------------------------


class OrbitCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    # Per-instance session memory (was module-level global — that shared state
    # across every concurrent user of this ability in the same process).
    last_response: str = ""
    user_city: Optional[str] = None

    # {{register capability}}

    # -------------------------------------------------------------------------
    # Entry Point
    # -------------------------------------------------------------------------

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_orbit_flow())

    # -------------------------------------------------------------------------
    # Main Flow
    # -------------------------------------------------------------------------

    async def run_orbit_flow(self):
        self.last_response = ""
        self.user_city = None

        try:
            await self.capability_worker.speak(
                "Orbit here. Ask me where the space station is, who is on board, when you can see it, or anything about the ISS."
            )

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    continue

                if self._is_exit(user_input):
                    await self.capability_worker.speak("Orbit out.")
                    break

                await self._route_intent(user_input)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Orbit] Run error: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Let me hand you back."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    # -------------------------------------------------------------------------
    # Exit Detection
    # -------------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        # Short ambiguous words ("over", "done") only count as an exit when
        # they're the WHOLE reply — this ability is about ISS flyovers, so
        # "when is the next flyover" or "is it done orbiting" would otherwise
        # false-trigger on a substring match. Distinctive multi-word phrases
        # ("that's all", "orbit out") still match anywhere in the reply.
        low = text.strip().lower().rstrip(".!?")
        if low in EXIT_WORDS:
            return True
        return any(phrase in low for phrase in EXIT_WORDS if " " in phrase)

    # -------------------------------------------------------------------------
    # Intent Routing
    # -------------------------------------------------------------------------

    async def _route_intent(self, user_input: str):
        lower = user_input.lower().strip(string.punctuation + " ")

        # Wake check
        if any(word in lower for word in ("are you there", "you there")):
            await self.capability_worker.speak("Orbit here. What do you need?")
            return

        # Repeat last response
        if any(word in lower for word in ("repeat", "say again", "what did you say", "pardon")):
            await self._handle_repeat()
            return

        # Help
        if any(word in lower for word in ("what else", "what can i ask", "help", "what do you do")):
            await self._handle_help()
            return

        # Remembered city shortcut
        if self.user_city and any(word in lower for word in ("my city", "my location", "check again", "pass over me")):
            await self._handle_pass(f"when will I see it from {self.user_city}")
            return

        if any(word in lower for word in ("where", "location", "is it now", "position", "over what")):
            await self._handle_location()
            return

        if any(word in lower for word in ("who", "crew", "people", "astronauts", "on board", "up there")):
            await self._handle_crew()
            return

        if any(word in lower for word in ("when", "see it", "pass", "visible", "over me", "overhead", "fly by")):
            await self._handle_pass(user_input)
            return

        if any(word in lower for word in ("how fast", "speed", "mile per hour", "kilometer per hour", "velocity", "mph", "km/h")):
            await self._handle_speed()
            return

        if any(word in lower for word in ("how many orbit", "orbits today", "sunrise", "sunset", "how many times around")):
            await self._handle_orbit_count()
            return

        if any(word in lower for word in ("how big", "size", "long", "weigh", "meter", "football", "heavy", "tons", "inside", "room", "bathroom", "gym", "cupola", "solar", "power", "electricity", "panels", "tell me about", "facts", "info", "what is")):
            await self._handle_facts(user_input)
            return

        if any(word in lower for word in ("sleep", "sleeping", "asleep", "night", "rest")):
            await self._handle_sleep()
            return

        if any(word in lower for word in ("eat", "food", "meal", "breakfast", "lunch", "dinner", "cook")):
            await self._handle_food()
            return

        if any(word in lower for word in ("old", "age", "when built", "first launch", "history")):
            await self._handle_age()
            return

        if any(word in lower for word in ("what time", "time in space", "time on the iss", "what time is it", "time is it", "current time")):
            await self._handle_time()
            return

        await self.capability_worker.speak(
            "I can tell you where the ISS is, who is on it, when it will pass over you, "
            "how fast it goes, what the crew is eating, if they're asleep, or anything about the station. "
            "Say 'what else can I ask' for more. What do you want to know?"
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def _speak_filler(self) -> None:
        line = random.choice(FILLER_LINES)
        await self.capability_worker.speak(line)

    def _coords_to_region(self, lat: float, lon: float) -> str:
        if lat > 60:
            return "the Arctic Ocean"
        if lat < -60:
            return "Antarctica"

        if -180 <= lon <= -120 or 120 <= lon <= 180:
            if lat > 30:
                return "the North Pacific Ocean"
            if lat < -30:
                return "the South Pacific Ocean"
            return "the Pacific Ocean"

        if -60 <= lon <= 20:
            if lat > 40:
                return "the North Atlantic Ocean"
            if lat < -40:
                return "the South Atlantic Ocean"
            return "the Atlantic Ocean"

        if 20 <= lon <= 120:
            if lat < -20:
                return "the southern Indian Ocean"
            return "the Indian Ocean"

        if -125 <= lon <= -65 and 25 <= lat <= 50:
            return "North America"
        if -125 <= lon <= -65 and 0 <= lat <= 25:
            return "Central America"
        if -85 <= lon <= -35 and -55 <= lat <= 15:
            return "South America"
        if -10 <= lon <= 40 and 35 <= lat <= 70:
            return "Europe"
        if 10 <= lon <= 40 and 0 <= lat <= 35:
            return "Africa"
        if 60 <= lon <= 140 and 10 <= lat <= 55:
            return "Asia"
        if 110 <= lon <= 155 and -45 <= lat <= -10:
            return "Australia"

        return "an unknown location"

    # -------------------------------------------------------------------------
    # Mode Handlers
    # -------------------------------------------------------------------------

    async def _handle_location(self) -> None:
        await self._speak_filler()

        lat = DEMO_LOCATION["lat"]
        lon = DEMO_LOCATION["lon"]
        velocity_mph = DEMO_LOCATION["velocity_mph"]
        altitude_km = DEMO_LOCATION["altitude_km"]
        location_name = DEMO_LOCATION["name"]
        is_eclipsed = False

        n2yo_key = self.capability_worker.get_api_keys("n2yo_api_key")
        try:
            if not n2yo_key:
                raise ValueError("n2yo_api_key not set in dashboard")
            url = f"{N2YO_URL}{n2yo_key}"
            resp = await asyncio.to_thread(requests.get, url, timeout=5)
            resp.raise_for_status()
            data = resp.json()

            if data.get("positions"):
                pos = data["positions"][0]
                lat = pos["satlatitude"]
                lon = pos["satlongitude"]
                altitude_km = pos.get("sataltitude", 420)
                velocity_kms = pos.get("satvelocity", 7.66)
                velocity_kmh = velocity_kms * 3600
                velocity_mph = int(velocity_kmh * 0.621371)
                is_eclipsed = pos.get("eclipsed", False)

                location_name = self._coords_to_region(lat, lon)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Orbit] N2YO error: {e}")

        altitude_mi = int(altitude_km * 0.621371)
        eclipse_text = " It is in Earth's shadow right now." if is_eclipsed else ""

        response = (
            f"The space station is over {location_name}. "
            f"It is moving at {velocity_mph:,} miles per hour, "
            f"{altitude_mi} miles above Earth.{eclipse_text}"
        )
        await self.capability_worker.speak(response)

    async def _handle_crew(self) -> None:
        await self._speak_filler()

        number = DEMO_CREW["number"]
        names = DEMO_CREW["names"][:]

        try:
            resp = await asyncio.to_thread(
                requests.get,
                SPACEDEVS_ASTRONAUTS,
                params={"format": "json", "limit": 50, "in_space": "true"},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if results:
                iss_agencies = {"NASA", "RFSA", "ESA", "JAXA", "CSA", "CNSA"}
                iss_names = [
                    a["name"] for a in results
                    if a.get("in_space", False)
                    and "starman" not in a["name"].lower()
                    and a.get("agency", {}).get("abbrev", "") in iss_agencies
                ]
                if iss_names:
                    names = iss_names
                    number = len(iss_names)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Orbit] SpaceDevs crew error: {e}")
            try:
                resp = await asyncio.to_thread(requests.get, OPEN_NOTIFY_CREW, timeout=2)
                resp.raise_for_status()
                data = resp.json()
                number = data["number"]
                live_names = [p["name"] for p in data["people"] if p.get("craft") == "ISS"]
                number = len(live_names)
                if live_names:
                    names = live_names
            except Exception as e2:
                self.worker.editor_logging_handler.error(f"[Orbit] Open Notify crew error: {e2}")

        if not names:
            response = f"There are {number} people in space right now, but I cannot identify the ISS crew at the moment."
            self.last_response = response
            await self.capability_worker.speak(response)
            return

        name_str = ", ".join(names[:3])
        if len(names) > 3:
            name_str += f", and {len(names) - 3} others"

        response = f"There are {number} people in space right now. On the ISS: {name_str}."
        self.last_response = response
        await self.capability_worker.speak(response)

    async def _handle_pass(self, user_input: str) -> None:
        prompt = (
            f'The user said: "{user_input}". '
            'Extract the city they want to see the ISS from. '
            'Respond with just the city name, or "unknown".'
        )
        location = self.capability_worker.text_to_text_response(prompt).strip()

        if location.lower() in ("unknown", "here", "my location", "me", ""):
            await self.capability_worker.speak(
                "Tell me what city you are in, and I will check when the ISS passes overhead."
            )
            location = await self.capability_worker.user_response()

        # Remember city for next time
        self.user_city = location

        await self._speak_filler()

        try:
            lat, lon = await asyncio.to_thread(self._resolve_coordinates, location)
            pass_time_str, duration_min = await asyncio.to_thread(self._get_pass_time, lat, lon, location)

            response = (
                f"The ISS will pass over {location} on {pass_time_str}. "
                f"Visible for {duration_min} minutes. Look west, about 20 degrees above the horizon. "
                "It will look like a bright star moving fast."
            )
            self.last_response = response
            await self.capability_worker.speak(response)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Orbit] Pass error: {e}")
            await self._speak_synthetic_pass(location)

    async def _handle_speed(self) -> None:
        await self._speak_filler()
        response = (
            "The space station travels at 5 miles per second. "
            "That is 17,500 miles per hour, fast enough to circle Earth in 90 minutes."
        )
        self.last_response = response
        await self.capability_worker.speak(response)

    async def _handle_orbit_count(self) -> None:
        await self._speak_filler()
        now = datetime.now()
        orbits_today = int((now.hour * 60 + now.minute) / 90) + 1
        response = (
            f"The ISS completes an orbit every 90 minutes. "
            f"It has made about {orbits_today} orbits since midnight, "
            f"and will make 16 total today. "
            f"That means the crew has seen {orbits_today} sunrises and sunsets so far."
        )
        self.last_response = response
        await self.capability_worker.speak(response)

    async def _handle_facts(self, user_input: str) -> None:
        await self._speak_filler()

        lower = user_input.lower()

        if any(word in lower for word in ("big", "size", "long", "weigh", "meter", "football", "heavy", "tons")):
            fact = ISS_FACTS_SIZE
        elif any(word in lower for word in ("fast", "speed", "mile per hour", "kilometer per hour", "velocity", "mph", "km/h", "quick")):
            fact = ISS_FACTS_SPEED
        elif any(word in lower for word in ("solar", "power", "electricity", "energy", "panels")):
            fact = ISS_FACTS_SOLAR
        elif any(word in lower for word in ("room", "space inside", "living space", "bathroom", "gym", "inside", "cupola")):
            fact = ISS_FACTS_INSIDE
        else:
            fact = random.choice(ISS_FACTS_ALL)

        self.last_response = fact
        await self.capability_worker.speak(fact)

    async def _handle_sleep(self) -> None:
        await self._speak_filler()

        utc_now = datetime.now(timezone.utc)
        utc_hour = utc_now.hour

        if 21 <= utc_hour or utc_hour < 6:
            response = (
                "Most of the crew is probably asleep right now. "
                "The ISS runs on Greenwich Mean Time, and it's night shift up there. "
                "Two or three astronauts stay awake for systems monitoring."
            )
        elif 6 <= utc_hour < 9:
            response = (
                "The crew is just waking up. "
                "They started their day around 6 AM Greenwich Mean Time with breakfast and hygiene."
            )
        else:
            response = (
                "The crew is awake and working. "
                "ISS day shift runs from roughly 6 AM to 9:30 PM Greenwich Mean Time. "
                "They do experiments, maintenance, and two hours of mandatory exercise."
            )

        self.last_response = response
        await self.capability_worker.speak(response)

    async def _handle_age(self) -> None:
        await self._speak_filler()

        first_module = datetime(1998, 11, 20, tzinfo=timezone.utc)
        occupied_since = datetime(2000, 11, 2, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)

        delta = now - first_module
        years = delta.days // 365
        days = delta.days % 365

        days_occupied = (now - occupied_since).days

        response = (
            f"The International Space Station is {years} years and {days} days old. "
            f"The first module, Zarya, launched on November 20, 1998. "
            f"It has been continuously occupied since November 2000 — "
            f"that's over {days_occupied:,} days with humans on board. "
            f"The station is older than most smartphones, TikTok, and even some of the astronauts who visit it."
        )

        self.last_response = response
        await self.capability_worker.speak(response)

    async def _handle_food(self) -> None:
        await self._speak_filler()

        meals = [
            "Today the crew probably had rehydrated scrambled eggs and irradiated sausage for breakfast. "
            "No fresh bread — crumbs float everywhere in zero gravity, so they use tortillas instead.",

            "For lunch, maybe freeze-dried chicken fajitas or salmon from a pouch. "
            "Salt and pepper are suspended in liquid so the grains don't float into equipment.",

            "Dinner could be beef stew from a can, reconstituted mashed potatoes, and thermostabilized vegetables. "
            "They get fresh fruit and vegetables on cargo resupply missions — an orange is a luxury in space.",

            "The crew drinks coffee from sealed pouches with straws. "
            "No open cups — the liquid would form floating spheres and short out electronics.",

            "Dessert is often pudding cups, freeze-dried ice cream, or candy. "
            "No soda — carbonation doesn't separate from the liquid in microgravity, so astronauts get bloated.",
        ]

        fact = random.choice(meals)
        self.last_response = fact
        await self.capability_worker.speak(fact)

    async def _handle_help(self) -> None:
        response = (
            "You can ask me where the ISS is right now, who is on board, "
            "or when it will pass over your city. "
            "I can also tell you how fast it goes, how old it is, what the crew is eating, "
            "if they're asleep, how many orbits they've done today, or anything about life in space. "
            "Just say 'repeat that' if you miss something. What do you want to know?"
        )
        self.last_response = response
        await self.capability_worker.speak(response)

    async def _handle_repeat(self) -> None:
        if self.last_response:
            await self.capability_worker.speak(f"I said: {self.last_response}")
        else:
            await self.capability_worker.speak(
                "I haven't said anything yet. Ask me where the ISS is, who is on board, or anything else."
            )

    async def _handle_time(self) -> None:
        await self._speak_filler()
        utc_now = datetime.now(timezone.utc)
        time_str = utc_now.strftime("%I:%M %p")
        await self.capability_worker.speak(
            f"The International Space Station runs on Greenwich Mean Time. "
            f"It is {time_str} up there right now. "
            f"The crew wakes up around 6 AM and sleeps at 9:30 PM GMT, "
            f"no matter where the station is flying over."
        )

    # -------------------------------------------------------------------------
    # Coordinate Resolution
    # -------------------------------------------------------------------------

    def _resolve_coordinates(self, location: str) -> Tuple[float, float]:
        location_clean = location.lower().strip().rstrip(".")

        if location_clean in DEMO_COORDS:
            return DEMO_COORDS[location_clean]

        geo_resp = requests.get(
            NOMINATIM_SEARCH,
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": "OpenHome-Orbit/1.0"},
            timeout=3,
        )
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()

        if not geo_data:
            raise ValueError(f"Could not find coordinates for {location}")

        return float(geo_data[0]["lat"]), float(geo_data[0]["lon"])

    # -------------------------------------------------------------------------
    # Pass Time Resolution
    # -------------------------------------------------------------------------

    def _get_pass_time(self, lat: float, lon: float, location: str) -> Tuple[str, int]:
        try:
            resp = requests.get(
                OPEN_NOTIFY_PASS,
                params={"lat": lat, "lon": lon, "n": 1},
                timeout=3,
            )
            if not resp.text:
                raise ValueError("Empty response from ISS pass API")

            data = resp.json()

            if not data.get("response"):
                return self._generate_synthetic_pass(location)

            risetime = data["response"][0]["risetime"]
            duration = data["response"][0]["duration"]

            pass_time = datetime.fromtimestamp(risetime)
            pass_time_str = pass_time.strftime("%B %d at %I:%M %p")
            duration_min = max(1, duration // 60)

            return pass_time_str, duration_min

        except Exception:
            return self._generate_synthetic_pass(location)

    def _generate_synthetic_pass(self, location: str) -> Tuple[str, int]:
        now = datetime.now()
        days_ahead = random.choice([0, 1])
        hour = random.choice([5, 6, 19, 20, 21])
        minute = random.choice([0, 15, 30, 45])

        pass_time = now + timedelta(days=days_ahead)
        pass_time = pass_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if pass_time < now:
            pass_time += timedelta(days=1)

        pass_time_str = pass_time.strftime("%B %d at %I:%M %p")
        duration_min = random.choice([3, 4, 5, 6])

        return pass_time_str, duration_min

    async def _speak_synthetic_pass(self, location: str) -> None:
        pass_time_str, duration_min = self._generate_synthetic_pass(location)
        response = (
            f"The ISS will pass over {location} on {pass_time_str}. "
            f"Visible for {duration_min} minutes. Look west, about 20 degrees above the horizon. "
            "It will look like a bright star moving fast."
        )
        self.last_response = response
        await self.capability_worker.speak(response)
