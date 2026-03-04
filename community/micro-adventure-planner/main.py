"""Micro Adventure Planner ability for OpenHome (no booking flow)."""

import datetime
import json
import re
from typing import Optional

import httpx

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

PREFS_FILE = "micro_adventure_prefs.json"
ITINERARY_FILE = "micro_adventure_itineraries.json"
HISTORY_FILE = "micro_adventure_history.json"

EXIT_WORDS = {
    "stop", "exit", "quit", "cancel", "bye", "goodbye", "done", "no thanks", "leave"
}

VALID_MODES = {"plan", "refine", "city", "calendar", "save", "history", "tips", "clarify", "exit"}
VALID_FOCUS = {"activities", "lodging", "transport", "food", "sights", "mixed"}

_WORD_LIMIT_SHORT = 6
_IDLE_WARN = 2
_IDLE_MAX = 3

CITY_STOP_WORDS = {
    "tonight", "tomorrow", "today", "weekend", "now", "please", "under",
    "budget", "low", "medium", "high", "cheap", "indoor", "outdoor",
    "quiet", "social", "active", "romantic", "family", "plan", "ideas",
    "activity", "activities", "adventure", "micro", "for", "this", "next",
}

LODGING_WORDS = {"hotel", "hotels", "motel", "motels", "stay", "stays", "accommodation", "hostel", "resort"}
TRANSPORT_WORDS = {
    "transport", "transportation", "bus", "train", "flight", "flights", "taxi", "uber", "car", "rent", "rental"
}
FOOD_WORDS = {
    "food", "restaurant", "restaurants", "eat", "eating", "dining", "cafe", "cafes",
    "street food", "cuisine", "lunch", "dinner", "breakfast", "brunch", "snack",
}
SIGHTS_WORDS = {
    "sights", "attractions", "landmarks", "monument", "monuments", "museum", "museums",
    "sightseeing", "tourist", "places to see", "must see", "must-see", "iconic",
}


SERPER_API_KEY = ""
TICKETMASTER_API_KEY = ""

DEFAULT_PREFS = {
    "home_city": None,
    "api_key_serper": SERPER_API_KEY,
    "api_key_ticketmaster": TICKETMASTER_API_KEY,
    "default_budget": "medium",
    "default_vibe": "balanced",
    "default_indoor": "any",
}

_INTENT_TEMPLATE = """You classify voice input for a micro-adventure planning assistant.
Return ONLY valid JSON on one line.

Modes:
- plan: user asks to create/find/suggest activities, food, sights, or plans
- refine: user asks to change previous options (cheaper, indoor, closer, quieter, etc.)
- city: user sets/changes default city
- calendar: user asks to add selected plan to calendar
- save: user wants to save/bookmark current plans for later
- history: user asks about past trips or saved itineraries
- tips: user asks for travel tips, packing advice, currency, or language info
- clarify: unclear input
- exit: user wants to stop

User input: "{user_input}"
Last prompt: "{last_prompt}"
Has plans loaded: {has_plans}

Output JSON schema:
{{
  "mode": "plan|refine|city|calendar|save|history|tips|clarify|exit",
  "city": "city or null",
  "focus": "activities|lodging|transport|food|sights|mixed|null",
  "vibe": "quiet|social|active|romantic|family|balanced|null",
  "budget": "low|medium|high|null",
  "indoor": "indoor|outdoor|any|null",
  "time_context": "raw phrase or null",
  "reference": "first|second|third|keyword|null"
}}"""

_FOLLOWUP_TEMPLATE = (
    "You are a concise planner assistant. The user said: '{user_input}'. "
    "Current mode: {mode}. Reply with one short follow-up question."
)


SEARCH_URL = "https://google.serper.dev/search"
TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
IP_GEO_URL = "http://ip-api.com/json"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
# Free routing API — no key required
OSRM_ROUTE_URL = "http://router.project-osrm.org/route/v1/driving"
# Free country info API — no key required
RESTCOUNTRIES_URL = "https://restcountries.com/v3.1/capital"


class MicroAdventurePlannerAbility(MatchingCapability):
    """Create nearby short plans using weather + air quality + local discovery."""

    # {{register capability}}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    current_plans: list[dict] = None

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.current_plans = []
        self.worker.session_tasks.create(self.run())

    def _log(self, msg: str):
        try:
            self.worker.editor_logging_handler.info(f"[MicroAdventure] {msg}")
        except Exception:
            pass

    def _err(self, msg: str):
        try:
            self.worker.editor_logging_handler.error(f"[MicroAdventure] {msg}")
        except Exception:
            pass

    async def run(self):
        try:
            prefs = await self._load_prefs()
            await self.capability_worker.speak(
                "Micro Adventure Planner is ready. I can plan outings, find food and sights, "
                "estimate travel time and budget, and give packing tips."
            )

            if not prefs.get("home_city"):
                await self._first_run_city_setup(prefs)

            prompt = "What kind of adventure do you want? I can plan activities, find restaurants, sights, hotels, or transport."
            idle_count = 0

            for _ in range(20):
                user_input = await self.capability_worker.run_io_loop(prompt)
                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= _IDLE_MAX:
                        await self.capability_worker.speak("No response detected. Goodbye.")
                        break
                    prompt = (
                        "Still there? Try: find restaurants in Cairo, or plan sightseeing in Dahab."
                        if idle_count >= _IDLE_WARN
                        else "I can plan a quick nearby outing. What do you feel like?"
                    )
                    continue

                idle_count = 0
                lowered = user_input.lower().strip()
                if lowered in EXIT_WORDS or any(x in lowered for x in EXIT_WORDS if len(x.split()) > 1):
                    await self.capability_worker.speak("Great. Enjoy your day.")
                    break

                intent = await self._classify_intent(user_input, prompt)
                mode = intent.get("mode", "clarify")

                if mode == "exit":
                    await self.capability_worker.speak("Great. Enjoy your day.")
                    break

                if mode == "city":
                    city = (intent.get("city") or "").strip()
                    if city:
                        prefs["home_city"] = city
                        await self._save_prefs(prefs)
                        await self.capability_worker.speak(f"Saved. Default city is now {city}.")
                    else:
                        await self.capability_worker.speak("Tell me the city name you want to use.")
                    prompt = "What should I plan for you?"
                    continue

                if mode == "calendar":
                    ok = await self._calendar_handoff(intent)
                    prompt = "Want another plan?" if ok else "I can build a plan first. What do you want to do?"
                    continue

                if mode == "save":
                    ok = await self._save_itinerary(intent, prefs)
                    prompt = "Saved. Want another plan or check your trip history?" if ok else "I need a plan first. What should I search for?"
                    continue

                if mode == "history":
                    await self._speak_trip_history()
                    prompt = "Want to plan a new adventure?"
                    continue

                if mode == "tips":
                    city = (intent.get("city") or prefs.get("home_city") or "").strip()
                    await self._speak_travel_tips(city, prefs)
                    prompt = "Anything else? I can plan activities or search for food."
                    continue

                if mode == "refine" and self.current_plans:
                    await self._speak_refined(intent)
                    prompt = "Want details on one option, add to calendar, or refine again?"
                    continue

                found = await self._handle_plan(intent, prefs)
                prompt = (
                    "Want to save these, hear travel tips, or refine options?"
                    if found
                    else "I can try a different vibe, budget, or city."
                )

        except Exception as exc:
            self._err(f"Fatal run loop error: {exc}")
            await self.capability_worker.speak("Sorry, something went wrong while planning.")
        finally:
            self.capability_worker.resume_normal_flow()

    async def _load_prefs(self) -> dict:
        exists = await self.capability_worker.check_if_file_exists(PREFS_FILE, False)
        if exists:
            try:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                loaded = json.loads(raw)
                return {**DEFAULT_PREFS, **loaded}
            except Exception as exc:
                self._err(f"Load prefs failed: {exc}")
        return dict(DEFAULT_PREFS)

    async def _save_prefs(self, prefs: dict):
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            await self.capability_worker.delete_file(PREFS_FILE, False)
        await self.capability_worker.write_file(PREFS_FILE, json.dumps(prefs), False)

    async def _first_run_city_setup(self, prefs: dict):
        city = await self._fetch_ip_city()
        if city:
            await self.capability_worker.speak(
                f"It looks like you're in {city}. Should I use this as your default city?"
            )
            ans = await self.capability_worker.user_response()
            if ans and any(x in ans.lower() for x in ("yes", "sure", "ok", "yep", "yeah")):
                prefs["home_city"] = city
                await self._save_prefs(prefs)
                return
        await self.capability_worker.speak("What city should I use for your plans?")
        ans = await self.capability_worker.user_response()
        if ans:
            prefs["home_city"] = ans.strip()
            await self._save_prefs(prefs)

    async def _fetch_ip_city(self) -> Optional[str]:
        try:
            ip = self.worker.user_socket.client.host
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{IP_GEO_URL}/{ip}")
            if resp.status_code == 200 and resp.json().get("status") == "success":
                return resp.json().get("city")
        except Exception as exc:
            self._err(f"IP lookup failed: {exc}")
        return None

    async def _classify_intent(self, user_input: str, last_prompt: str) -> dict:
        lower = user_input.lower()
        detected_focus = self._detect_focus(lower)
        if any(x in lower for x in ("city is", "set city", "change city", "i live in")):
            city_guess = self._extract_city_from_text(user_input)
            return {"mode": "city", "city": city_guess}
        if any(x in lower for x in ("add to calendar", "calendar")):
            return {"mode": "calendar", "reference": "first"}
        if any(x in lower for x in ("save this", "save plan", "bookmark", "save itinerary", "keep this")):
            return {"mode": "save", "reference": "first"}
        if any(x in lower for x in ("trip history", "past trips", "saved plans", "my itineraries", "what have i")):
            return {"mode": "history"}
        if any(x in lower for x in ("travel tips", "packing", "currency", "language", "what to pack", "travel advice")):
            city_guess = self._extract_city_from_text(user_input)
            return {"mode": "tips", "city": city_guess}
        if any(x in lower for x in ("cheaper", "indoor", "outdoor", "closer", "quieter", "more active")):
            return {"mode": "refine", "budget": "low" if "cheap" in lower else None}
        travel_markers = ("travel to", "go to", "trip to", "in ", "at ")
        if any(x in lower for x in travel_markers):
            city_guess = self._extract_city_from_text(user_input)
            if city_guess:
                return {"mode": "plan", "city": city_guess, "focus": detected_focus}
        if len(lower.split()) <= _WORD_LIMIT_SHORT and any(x in lower for x in ("plan", "ideas", "suggest")):
            return {"mode": "plan", "focus": detected_focus}

        prompt = _INTENT_TEMPLATE.format(
            user_input=user_input,
            last_prompt=last_prompt,
            has_plans="yes" if self.current_plans else "no",
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            data = json.loads(self._strip_fences(raw))
            if data.get("mode") in VALID_MODES:
                focus = (data.get("focus") or "").lower().strip()
                if focus not in VALID_FOCUS:
                    data["focus"] = detected_focus
                return data
        except Exception as exc:
            self._err(f"Intent classify fallback: {exc}")
        return {"mode": "plan", "focus": detected_focus}

    def _detect_focus(self, lower_text: str) -> str:
        has_lodging = any(word in lower_text for word in LODGING_WORDS)
        has_transport = any(word in lower_text for word in TRANSPORT_WORDS)
        has_food = any(word in lower_text for word in FOOD_WORDS)
        has_sights = any(word in lower_text for word in SIGHTS_WORDS)
        hits = sum([has_lodging, has_transport, has_food, has_sights])
        if hits > 1:
            return "mixed"
        if has_food:
            return "food"
        if has_sights:
            return "sights"
        if has_lodging:
            return "lodging"
        if has_transport:
            return "transport"
        return "activities"

    def _extract_city_from_text(self, user_input: str) -> Optional[str]:
        text = (user_input or "").strip()
        if not text:
            return None

        patterns = [
            r"(?:travel to|trip to|go to)\s+([A-Za-z][A-Za-z\s\-']{1,60})",
            r"(?:in|at|to)\s+([A-Za-z][A-Za-z\s\-']{1,60})",
            r"(?:city is|set city to|change city to|my city is|i live in)\s+([A-Za-z][A-Za-z\s\-']{1,60})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            raw_city = match.group(1).strip(" .,!?:;\"'")
            tokens = []
            for token in raw_city.split():
                lowered = token.lower().strip(" .,!?:;\"'")
                if lowered in CITY_STOP_WORDS:
                    break
                tokens.append(token.strip(" .,!?:;\"'"))
            city = " ".join(t for t in tokens if t)
            if city:
                return city

        # Fallback for short direct city requests like "Dahab" or "Cairo"
        plain = re.sub(r"[^A-Za-z\s\-']", " ", text).strip()
        if plain and len(plain.split()) <= 3 and all(t.lower() not in CITY_STOP_WORDS for t in plain.split()):
            return plain
        return None

    async def _handle_plan(self, intent: dict, prefs: dict) -> bool:
        city = (intent.get("city") or prefs.get("home_city") or "").strip()
        if not city:
            await self.capability_worker.speak("I need a city first. Tell me where to plan.")
            return False

        origin_city = (prefs.get("home_city") or "").strip()

        budget = (intent.get("budget") or prefs.get("default_budget") or "medium").lower()
        vibe = (intent.get("vibe") or prefs.get("default_vibe") or "balanced").lower()
        indoor = (intent.get("indoor") or prefs.get("default_indoor") or "any").lower()
        time_context = (intent.get("time_context") or "today").strip()
        focus = (intent.get("focus") or "activities").lower().strip()
        if focus not in VALID_FOCUS:
            focus = "activities"

        if origin_city and origin_city.lower() != city.lower():
            await self.capability_worker.speak(
                f"Great, planning your trip from {origin_city} to {city}. One moment."
            )
        else:
            await self.capability_worker.speak(f"Planning options in {city}. One moment.")

        geo = await self._geocode_city(city)
        if not geo:
            await self.capability_worker.speak(f"I couldn't locate {city}. Try another city name.")
            return False

        lat, lon = geo
        weather_task = self._fetch_weather(lat, lon)
        aqi_task = self._fetch_aqi(lat, lon)
        search_task = self._fetch_serper_candidates(
            city=city,
            time_context=time_context,
            focus=focus,
            api_key=prefs.get("api_key_serper", ""),
        )
        event_task = self._fetch_ticketmaster(city, time_context, prefs.get("api_key_ticketmaster", ""))

        weather = await weather_task
        aqi = await aqi_task
        activities = await search_task
        events = await event_task

        candidates = self._build_candidates(
            activities=activities,
            events=events,
            city=city,
            focus=focus,
            origin_city=origin_city,
        )
        ranked = self._rank_candidates(candidates, budget, vibe, indoor, weather, aqi, focus)
        self.current_plans = ranked[:3]

        if not self.current_plans:
            await self.capability_worker.speak(
                "I could not build a solid plan right now. Try a different city or mood."
            )
            return False

        await self._speak_plans(city, budget, vibe, indoor, weather, aqi, focus=focus)
        self._log_plan_links(self.current_plans)
        return True

    async def _speak_refined(self, intent: dict):
        lower_budget = (intent.get("budget") == "low")
        reduced = sorted(
            self.current_plans,
            key=lambda x: (self._cost_score(x.get("cost", "medium")), x.get("score", 0)),
            reverse=not lower_budget,
        )
        self.current_plans = reduced[:3]
        await self._speak_plans(None, None, None, None, None, None, refined=True)

    async def _calendar_handoff(self, intent: dict) -> bool:
        if not self.current_plans:
            await self.capability_worker.speak("I don't have a current plan yet.")
            return False
        ref = (intent.get("reference") or "first").lower()
        idx = {"first": 0, "second": 1, "third": 2}.get(ref, 0)
        if idx >= len(self.current_plans):
            idx = 0
        item = self.current_plans[idx]

        title = self._url_encode(item["title"])
        details = self._url_encode(item.get("reason", "Created with Micro Adventure Planner"))
        location = self._url_encode(item.get("location", ""))

        now = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
        end = now + datetime.timedelta(hours=2)
        dates = f"{now.strftime('%Y%m%dT%H%M%SZ')}/{end.strftime('%Y%m%dT%H%M%SZ')}"
        link = (
            "https://calendar.google.com/calendar/r/eventedit"
            f"?text={title}&details={details}&location={location}&dates={dates}"
        )

        self._log(f"Calendar link: {link}")
        await self.capability_worker.speak(
            f"I prepared a calendar link for {item['title']}. I sent it to your device."
        )
        return True

    async def _geocode_city(self, city: str) -> Optional[tuple[float, float]]:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(GEOCODE_URL, params={"name": city, "count": 1, "language": "en"})
            if resp.status_code == 200:
                result = resp.json().get("results", [])
                if result:
                    return float(result[0]["latitude"]), float(result[0]["longitude"])
        except Exception as exc:
            self._err(f"Geocode error: {exc}")
        return None

    async def _fetch_weather(self, lat: float, lon: float) -> dict:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    WEATHER_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,precipitation,weather_code",
                    },
                )
            return resp.json().get("current", {}) if resp.status_code == 200 else {}
        except Exception as exc:
            self._err(f"Weather error: {exc}")
            return {}

    async def _fetch_aqi(self, lat: float, lon: float) -> dict:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    AIR_URL,
                    params={"latitude": lat, "longitude": lon, "current": "us_aqi"},
                )
            return resp.json().get("current", {}) if resp.status_code == 200 else {}
        except Exception as exc:
            self._err(f"AQI error: {exc}")
            return {}

    async def _fetch_serper_candidates(self, city: str, time_context: str, focus: str, api_key: str) -> list[dict]:
        key = (SERPER_API_KEY or api_key or "").strip()
        if not key:
            return []
        try:
            queries: list[tuple[str, str]] = []
            if focus in ("activities", "mixed"):
                queries.append((f"things to do in {city} {time_context}".strip(), "activity"))
            if focus in ("lodging", "mixed"):
                queries.append((f"best hotels and motels in {city}".strip(), "lodging"))
            if focus in ("transport", "mixed"):
                queries.append((f"local transportation options in {city} {time_context}".strip(), "transport"))
            if focus in ("food", "mixed"):
                queries.append((f"best restaurants and street food in {city}".strip(), "food"))
            if focus in ("sights", "mixed"):
                queries.append((f"top attractions and landmarks in {city}".strip(), "sights"))

            if not queries:
                queries.append((f"things to do in {city} {time_context}".strip(), "activity"))

            async with httpx.AsyncClient(timeout=10) as client:
                tasks = [
                    client.post(
                        SEARCH_URL,
                        headers={"X-API-KEY": key, "Content-Type": "application/json"},
                        json={"q": q},
                    )
                    for q, _ in queries
                ]
                responses = [await t for t in tasks]

            collected: list[dict] = []
            for idx, resp in enumerate(responses):
                result_type = queries[idx][1]
                if resp.status_code != 200:
                    continue
                organic = resp.json().get("organic", [])[:3]
                for row in organic:
                    collected.append(
                        {
                            "title": row.get("title", "Local option"),
                            "location": city,
                            "url": row.get("link", ""),
                            "type": result_type,
                        }
                    )
            return collected
        except Exception as exc:
            self._err(f"Serper candidate error: {exc}")
        return []

    async def _fetch_ticketmaster(self, city: str, time_context: str, api_key: str) -> list[dict]:
        key = (TICKETMASTER_API_KEY or api_key or "").strip()
        if not key:
            return []
        try:
            params = {
                "apikey": key,
                "city": city,
                "size": 3,
                "sort": "date,asc",
                "locale": "*",
            }
            if time_context:
                params["keyword"] = time_context
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(TICKETMASTER_URL, params=params)
            if resp.status_code == 200:
                events = resp.json().get("_embedded", {}).get("events", [])
                parsed = []
                for event in events:
                    venue = event.get("_embedded", {}).get("venues", [{}])[0].get("name", city)
                    parsed.append(
                        {
                            "title": event.get("name", "Live event"),
                            "location": venue,
                            "url": event.get("url", ""),
                            "type": "event",
                        }
                    )
                return parsed
        except Exception as exc:
            self._err(f"Ticketmaster error: {exc}")
        return []

    def _build_candidates(
        self,
        activities: list[dict],
        events: list[dict],
        city: str,
        focus: str,
        origin_city: Optional[str] = None,
    ) -> list[dict]:
        base = []
        for row in (activities + events):
            text = f"{row.get('title', '')} {row.get('location', '')}".lower()
            guessed_cost = "medium"
            if any(k in text for k in ("park", "walk", "museum free", "public")):
                guessed_cost = "low"
            if any(k in text for k in ("fine dining", "vip", "luxury", "premium")):
                guessed_cost = "high"

            indoor_guess = "indoor" if any(k in text for k in ("museum", "gallery", "cafe", "theater")) else "outdoor"
            if row.get("type") in ("lodging", "transport"):
                indoor_guess = "any"
            option_city = row.get("location", city)
            map_link = self._build_map_search_link(row.get("title", "Option"), option_city)
            route_link = ""
            if row.get("type") == "transport" and origin_city and origin_city.lower() != city.lower():
                route_link = self._build_route_link(origin_city, city, mode="transit")

            base.append(
                {
                    "title": row.get("title", "Option"),
                    "location": option_city,
                    "type": row.get("type", "activity"),
                    "cost": guessed_cost,
                    "indoor": indoor_guess,
                    "url": row.get("url", ""),
                    "map_url": map_link,
                    "route_url": route_link,
                }
            )

        if not base:
            if focus == "lodging":
                return [
                    {
                        "title": "Budget hotel near center",
                        "location": city,
                        "type": "lodging",
                        "cost": "low",
                        "indoor": "any",
                        "url": "",
                        "map_url": self._build_map_search_link("Budget hotel near center", city),
                        "route_url": "",
                    },
                    {
                        "title": "Comfort motel with parking",
                        "location": city,
                        "type": "lodging",
                        "cost": "medium",
                        "indoor": "any",
                        "url": "",
                        "map_url": self._build_map_search_link("Comfort motel with parking", city),
                        "route_url": "",
                    },
                    {
                        "title": "Premium resort stay",
                        "location": city,
                        "type": "lodging",
                        "cost": "high",
                        "indoor": "any",
                        "url": "",
                        "map_url": self._build_map_search_link("Premium resort stay", city),
                        "route_url": "",
                    },
                ]
            if focus == "transport":
                route_url = (
                    self._build_route_link(origin_city, city, mode="transit")
                    if origin_city and origin_city.lower() != city.lower()
                    else ""
                )
                return [
                    {
                        "title": "Intercity bus option",
                        "location": city,
                        "type": "transport",
                        "cost": "low",
                        "indoor": "any",
                        "url": "",
                        "map_url": self._build_map_search_link("Intercity bus station", city),
                        "route_url": route_url,
                    },
                    {
                        "title": "Private transfer and taxi",
                        "location": city,
                        "type": "transport",
                        "cost": "medium",
                        "indoor": "any",
                        "url": "",
                        "map_url": self._build_map_search_link("Taxi pickup", city),
                        "route_url": route_url,
                    },
                    {
                        "title": "Car rental and self-drive",
                        "location": city,
                        "type": "transport",
                        "cost": "medium",
                        "indoor": "any",
                        "url": "",
                        "map_url": self._build_map_search_link("Car rental", city),
                        "route_url": self._build_route_link(origin_city or city, city, mode="driving") if origin_city else "",
                    },
                ]
            if focus == "food":
                return self._build_food_fallback(city)
            if focus == "sights":
                return self._build_sights_fallback(city)
            return [
                {
                    "title": "Scenic walk + coffee",
                    "location": city,
                    "type": "activity",
                    "cost": "low",
                    "indoor": "outdoor",
                    "url": "",
                    "map_url": self._build_map_search_link("Scenic walk and coffee", city),
                    "route_url": "",
                },
                {
                    "title": "Local gallery and cafe",
                    "location": city,
                    "type": "activity",
                    "cost": "medium",
                    "indoor": "indoor",
                    "url": "",
                    "map_url": self._build_map_search_link("Local gallery and cafe", city),
                    "route_url": "",
                },
                {
                    "title": "Community event nearby",
                    "location": city,
                    "type": "event",
                    "cost": "medium",
                    "indoor": "any",
                    "url": "",
                    "map_url": self._build_map_search_link("Community event", city),
                    "route_url": "",
                },
            ]
        return base

    def _rank_candidates(
        self,
        candidates: list[dict],
        budget: str,
        vibe: str,
        indoor: str,
        weather: dict,
        aqi: dict,
        focus: str,
    ) -> list[dict]:
        rainy = float(weather.get("precipitation", 0) or 0) > 0.2
        aqi_value = float(aqi.get("us_aqi", 50) or 50)

        ranked = []
        for item in candidates:
            score = 50
            if item.get("cost") == budget:
                score += 18
            if indoor in ("indoor", "outdoor") and item.get("indoor") == indoor:
                score += 14
            if rainy and item.get("indoor") == "indoor":
                score += 10
            if aqi_value > 90 and item.get("indoor") == "indoor":
                score += 8
            if vibe == "active" and any(k in item["title"].lower() for k in ("walk", "hike", "bike", "climb")):
                score += 10
            if vibe == "quiet" and any(k in item["title"].lower() for k in ("gallery", "museum", "book", "park")):
                score += 10
            if vibe == "social" and any(k in item["title"].lower() for k in ("live", "event", "festival", "market")):
                score += 10
            if focus == "lodging" and item.get("type") == "lodging":
                score += 20
            if focus == "transport" and item.get("type") == "transport":
                score += 20
            if focus == "activities" and item.get("type") in ("activity", "event"):
                score += 10
            if focus == "food" and item.get("type") == "food":
                score += 20
            if focus == "sights" and item.get("type") == "sights":
                score += 20

            item["score"] = score
            item["reason"] = self._reason_text(item, budget, indoor, rainy, aqi_value)
            ranked.append(item)

        seen = set()
        deduped = []
        for item in sorted(ranked, key=lambda x: x["score"], reverse=True):
            key = item["title"].lower().strip()
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped

    async def _speak_plans(
        self,
        city: Optional[str],
        budget: Optional[str],
        vibe: Optional[str],
        indoor: Optional[str],
        weather: Optional[dict],
        aqi: Optional[dict],
        focus: Optional[str] = None,
        refined: bool = False,
    ):
        title = "Here are refined options." if refined else "I built three options for you."
        details = []
        ordinals = ["First", "Second", "Third"]
        for idx, item in enumerate(self.current_plans[:3]):
            details.append(f"{ordinals[idx]}, {item['title']} at {item['location']}. {item['reason']}")

        weather_note = ""
        if weather or aqi:
            rain = float((weather or {}).get("precipitation", 0) or 0)
            aqi_val = float((aqi or {}).get("us_aqi", 0) or 0)
            weather_note = f" Current rain level is {rain:.1f}, AQI is {aqi_val:.0f}."

        context_note = ""
        if city:
            context_note = f" For {city}"
            if focus:
                context_note += f", focus {focus}"
            if budget:
                context_note += f", budget {budget}"
            if vibe:
                context_note += f", vibe {vibe}"
            if indoor:
                context_note += f", preference {indoor}"
            context_note += "."

        links_note = " Map and route links are prepared for your top options."
        await self.capability_worker.speak(" ".join([title + context_note + weather_note] + details) + links_note)

    def _log_plan_links(self, plans: list[dict]):
        for idx, plan in enumerate(plans[:3], start=1):
            if plan.get("map_url"):
                self._log(f"Option {idx} map: {plan['map_url']}")
            if plan.get("route_url"):
                self._log(f"Option {idx} route: {plan['route_url']}")

    def _reason_text(self, item: dict, budget: str, indoor: str, rainy: bool, aqi_value: float) -> str:
        bits = []
        if item.get("cost") == budget:
            bits.append("matches your budget")
        if indoor in ("indoor", "outdoor") and item.get("indoor") == indoor:
            bits.append("fits your indoor/outdoor preference")
        if rainy and item.get("indoor") == "indoor":
            bits.append("works better with current rain")
        if aqi_value > 90 and item.get("indoor") == "indoor":
            bits.append("safer choice for current air quality")
        if not bits:
            bits.append("good overall balance for a short outing")
        return "This option " + ", ".join(bits) + "."

    def _strip_fences(self, text: str) -> str:
        text = (text or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _url_encode(self, text: str) -> str:
        safe = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")
        out = []
        for ch in str(text or ""):
            if ch == " ":
                out.append("+")
            elif ch in safe:
                out.append(ch)
            else:
                for b in ch.encode("utf-8"):
                    out.append(f"%{b:02X}")
        return "".join(out)

    def _build_map_search_link(self, title: str, location: str) -> str:
        query = self._url_encode(f"{title} {location}".strip())
        return f"https://www.google.com/maps/search/?api=1&query={query}"

    def _build_route_link(self, origin: str, destination: str, mode: str = "transit") -> str:
        origin_q = self._url_encode(origin)
        destination_q = self._url_encode(destination)
        travel_mode = mode if mode in ("driving", "walking", "bicycling", "transit") else "transit"
        return (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={origin_q}&destination={destination_q}&travelmode={travel_mode}"
        )

    def _cost_score(self, cost: str) -> int:
        return {"low": 3, "medium": 2, "high": 1}.get((cost or "medium").lower(), 2)

    # ------------------------------------------------------------------ #
    # Feature: Itinerary saving (#1) and Trip history (#7)
    # ------------------------------------------------------------------ #

    async def _save_itinerary(self, intent: dict, prefs: dict) -> bool:
        """Save current plans to persistent itinerary file."""
        if not self.current_plans:
            await self.capability_worker.speak("I don't have any plans to save yet.")
            return False
        itineraries = await self._load_json(ITINERARY_FILE, default=[])
        entry = {
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "city": self.current_plans[0].get("location", "unknown"),
            "plans": [
                {
                    "title": p.get("title", ""),
                    "location": p.get("location", ""),
                    "type": p.get("type", ""),
                    "cost": p.get("cost", ""),
                    "reason": p.get("reason", ""),
                    "map_url": p.get("map_url", ""),
                }
                for p in self.current_plans[:3]
            ],
        }
        itineraries.append(entry)
        # Keep last 20 itineraries
        itineraries = itineraries[-20:]
        await self._save_json(ITINERARY_FILE, itineraries)
        await self.capability_worker.speak(
            f"Saved your {entry['city']} itinerary. You now have {len(itineraries)} saved trips."
        )
        # Also log to trip history
        await self._log_trip_history(entry)
        return True

    async def _log_trip_history(self, entry: dict):
        """Append a trip entry to the history log."""
        history = await self._load_json(HISTORY_FILE, default=[])
        history.append({
            "date": entry["saved_at"],
            "city": entry["city"],
            "plan_count": len(entry["plans"]),
            "highlights": [p["title"] for p in entry["plans"]],
        })
        history = history[-50:]
        await self._save_json(HISTORY_FILE, history)

    async def _speak_trip_history(self):
        """Read back past saved trips."""
        history = await self._load_json(HISTORY_FILE, default=[])
        if not history:
            await self.capability_worker.speak("You don't have any saved trips yet.")
            return
        recent = history[-5:]
        summary = f"You have {len(history)} saved trips. Here are the most recent. "
        for idx, trip in enumerate(reversed(recent), 1):
            city = trip.get("city", "unknown")
            highlights = ", ".join(trip.get("highlights", [])[:2])
            summary += f"{idx}, {city} with {highlights}. "
        await self.capability_worker.speak(summary)

    # ------------------------------------------------------------------ #
    # Feature: Travel tips — currency, language, packing (#2, #3, #4, #8)
    # ------------------------------------------------------------------ #

    async def _speak_travel_tips(self, city: str, prefs: dict):
        """Generate travel tips using LLM + real weather + optional country API."""
        if not city:
            await self.capability_worker.speak("Which city do you need travel tips for?")
            return

        await self.capability_worker.speak(f"Getting travel tips for {city}. One moment.")

        # Fetch weather for packing advice
        geo = await self._geocode_city(city)
        weather = {}
        if geo:
            lat, lon = geo
            weather = await self._fetch_weather(lat, lon)

        # Fetch country info (currency, languages)
        country_info = await self._fetch_country_info(city)

        # Estimate travel distance from home city
        origin_city = (prefs.get("home_city") or "").strip()
        distance_info = ""
        if origin_city and origin_city.lower() != city.lower() and geo:
            origin_geo = await self._geocode_city(origin_city)
            if origin_geo:
                distance_info = await self._fetch_travel_distance(origin_geo, geo)

        # Build LLM prompt with all context
        temp = weather.get("temperature_2m", "unknown")
        rain = weather.get("precipitation", 0)
        currency = country_info.get("currency", "unknown")
        languages = country_info.get("languages", "unknown")

        tips_prompt = (
            f"You are a travel assistant. Give concise voice-friendly travel tips for {city}.\n"
            f"Current weather: {temp} degrees Celsius, precipitation {rain} mm.\n"
            f"Local currency: {currency}. Languages spoken: {languages}.\n"
            f"Travel distance from home: {distance_info or 'unknown'}.\n\n"
            "Include in 3-4 short sentences:\n"
            "1. Packing tips based on weather\n"
            "2. Currency and language tips\n"
            "3. Estimated travel time if distance is known\n"
            "4. Rough daily budget estimate in local currency\n"
            "Keep it short and spoken-friendly."
        )
        try:
            tips = self.capability_worker.text_to_text_response(tips_prompt)
            await self.capability_worker.speak(tips.strip())
        except Exception as exc:
            self._err(f"Travel tips LLM error: {exc}")
            # Fallback without LLM
            fallback = f"For {city}: currency is {currency}, languages include {languages}."
            if temp != "unknown":
                fallback += f" It's currently {temp} degrees."
            if distance_info:
                fallback += f" {distance_info}."
            await self.capability_worker.speak(fallback)

    async def _fetch_country_info(self, city: str) -> dict:
        """Fetch currency and language info via RestCountries API (free, no key)."""
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                resp = await client.get(RESTCOUNTRIES_URL, params={"fields": "currencies,languages"})
            if resp.status_code != 200:
                # Fallback: try searching by city name
                async with httpx.AsyncClient(timeout=6) as client:
                    resp = await client.get(
                        f"https://restcountries.com/v3.1/name/{city}",
                        params={"fields": "currencies,languages"},
                    )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    entry = data[0]
                    currencies = entry.get("currencies", {})
                    currency_str = ", ".join(
                        f"{v.get('name', k)} ({v.get('symbol', '')})" for k, v in currencies.items()
                    ) if currencies else "unknown"
                    langs = entry.get("languages", {})
                    lang_str = ", ".join(langs.values()) if langs else "unknown"
                    return {"currency": currency_str, "languages": lang_str}
        except Exception as exc:
            self._err(f"Country info error: {exc}")
        return {"currency": "unknown", "languages": "unknown"}

    async def _fetch_travel_distance(self, origin_geo: tuple, dest_geo: tuple) -> str:
        """Estimate driving distance and duration using OSRM (free, no key)."""
        try:
            o_lat, o_lon = origin_geo
            d_lat, d_lon = dest_geo
            url = f"{OSRM_ROUTE_URL}/{o_lon},{o_lat};{d_lon},{d_lat}"
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(url, params={"overview": "false"})
            if resp.status_code == 200:
                routes = resp.json().get("routes", [])
                if routes:
                    dist_km = routes[0]["distance"] / 1000
                    dur_hours = routes[0]["duration"] / 3600
                    if dur_hours < 1:
                        dur_text = f"{int(dur_hours * 60)} minutes"
                    else:
                        dur_text = f"{dur_hours:.1f} hours"
                    return f"About {dist_km:.0f} km, roughly {dur_text} by car"
        except Exception as exc:
            self._err(f"OSRM distance error: {exc}")
        return ""

    # ------------------------------------------------------------------ #
    # Feature: Food & Sights fallback candidates (#5, #6)
    # ------------------------------------------------------------------ #

    def _build_food_fallback(self, city: str) -> list[dict]:
        """Fallback food candidates when Serper returns nothing."""
        return [
            {
                "title": "Local street food tour",
                "location": city,
                "type": "food",
                "cost": "low",
                "indoor": "outdoor",
                "url": "",
                "map_url": self._build_map_search_link("street food", city),
                "route_url": "",
            },
            {
                "title": "Top-rated restaurant nearby",
                "location": city,
                "type": "food",
                "cost": "medium",
                "indoor": "indoor",
                "url": "",
                "map_url": self._build_map_search_link("top rated restaurant", city),
                "route_url": "",
            },
            {
                "title": "Cozy cafe with local coffee",
                "location": city,
                "type": "food",
                "cost": "low",
                "indoor": "indoor",
                "url": "",
                "map_url": self._build_map_search_link("best cafe", city),
                "route_url": "",
            },
        ]

    def _build_sights_fallback(self, city: str) -> list[dict]:
        """Fallback sights candidates when Serper returns nothing."""
        return [
            {
                "title": "Top landmark and viewpoint",
                "location": city,
                "type": "sights",
                "cost": "low",
                "indoor": "outdoor",
                "url": "",
                "map_url": self._build_map_search_link("famous landmark", city),
                "route_url": "",
            },
            {
                "title": "Local museum or gallery",
                "location": city,
                "type": "sights",
                "cost": "medium",
                "indoor": "indoor",
                "url": "",
                "map_url": self._build_map_search_link("museum", city),
                "route_url": "",
            },
            {
                "title": "Historic district walking tour",
                "location": city,
                "type": "sights",
                "cost": "low",
                "indoor": "outdoor",
                "url": "",
                "map_url": self._build_map_search_link("historic district", city),
                "route_url": "",
            },
        ]

    # ------------------------------------------------------------------ #
    # JSON persistence helpers
    # ------------------------------------------------------------------ #

    async def _load_json(self, filename: str, default=None):
        """Load a JSON file with fallback to default."""
        if await self.capability_worker.check_if_file_exists(filename, False):
            try:
                raw = await self.capability_worker.read_file(filename, False)
                return json.loads(raw)
            except Exception as exc:
                self._err(f"Load {filename} failed: {exc}")
        return default if default is not None else {}

    async def _save_json(self, filename: str, data):
        """Save data as JSON, using delete+write pattern."""
        if await self.capability_worker.check_if_file_exists(filename, False):
            await self.capability_worker.delete_file(filename, False)
        await self.capability_worker.write_file(filename, json.dumps(data), False)
