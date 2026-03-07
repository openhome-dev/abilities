"""Micro Adventure Planner ability for OpenHome (no booking flow)."""

import asyncio
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
    "stop",
    "exit",
    "quit",
    "cancel",
    "bye",
    "goodbye",
    "done",
    "no thanks",
    "leave",
}

VALID_MODES = {
    "plan",
    "refine",
    "city",
    "calendar",
    "save",
    "history",
    "tips",
    "notion",
    "clarify",
    "exit",
}
VALID_FOCUS = {"activities", "lodging", "transport", "food", "sights", "mixed"}

_WORD_LIMIT_SHORT = 6
_IDLE_WARN = 2
_IDLE_MAX = 3

CITY_STOP_WORDS = {
    "tonight",
    "tomorrow",
    "today",
    "weekend",
    "now",
    "please",
    "under",
    "budget",
    "low",
    "medium",
    "high",
    "cheap",
    "indoor",
    "outdoor",
    "quiet",
    "social",
    "active",
    "romantic",
    "family",
    "plan",
    "ideas",
    "activity",
    "activities",
    "adventure",
    "micro",
    "for",
    "this",
    "next",
}

LODGING_WORDS = {
    "hotel",
    "hotels",
    "motel",
    "motels",
    "stay",
    "stays",
    "accommodation",
    "hostel",
    "resort",
}
TRANSPORT_WORDS = {
    "transport",
    "transportation",
    "bus",
    "train",
    "flight",
    "flights",
    "taxi",
    "uber",
    "car",
    "rent",
    "rental",
}
FOOD_WORDS = {
    "food",
    "restaurant",
    "restaurants",
    "eat",
    "eating",
    "dining",
    "cafe",
    "cafes",
    "street food",
    "cuisine",
    "lunch",
    "dinner",
    "breakfast",
    "brunch",
    "snack",
}
SIGHTS_WORDS = {
    "sights",
    "attractions",
    "landmarks",
    "monument",
    "monuments",
    "museum",
    "museums",
    "sightseeing",
    "tourist",
    "places to see",
    "must see",
    "must-see",
    "iconic",
}


SERPER_API_KEY = ""  # Set your key here or in micro_adventure_prefs.json
TICKETMASTER_API_KEY = ""  # Set your key here or in micro_adventure_prefs.json
NOTION_API_KEY = ""  # Set your key here or in micro_adventure_prefs.json
NOTION_DATABASE_ID = (
    ""  # Set your Notion database ID here or in micro_adventure_prefs.json
)

NOTION_PAGES_URL = "https://api.notion.com/v1/pages"
NOTION_VERSION = "2022-06-28"

DEFAULT_PREFS = {
    "home_city": None,
    "home_country_code": "",  # ISO 3166-1 alpha-2 (e.g. 'EG', 'US') -- set during IP detection
    "api_key_serper": SERPER_API_KEY,
    "api_key_ticketmaster": TICKETMASTER_API_KEY,
    "default_budget": "medium",
    "default_vibe": "balanced",
    "default_indoor": "any",
    "notion_api_key": NOTION_API_KEY,
    "notion_database_id": NOTION_DATABASE_ID,
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
- notion: user wants to post or share the plan to Notion
- clarify: unclear input
- exit: user wants to stop

trip_type rules (IMPORTANT - apply these before deciding city):
- Set trip_type to "outing" when the user wants ANY short local activity with NO named travel destination:
  Food/drink: "I wanna go eat", "find a restaurant", "grab lunch", "coffee shop", "I'm hungry"
  Sports/activity: "I wanna play paddle", "let's go hiking", "find a gym", "go swimming", "play tennis"
  Entertainment: "find a movie", "go to a park", "visit a museum", "catch a show", "go bowling"
  General: "something to do nearby", "explore locally", "get out of the house", "go somewhere fun"
  Rule: if no city is named AND it sounds like a self-contained local outing, use trip_type=outing.
  For outing: set city=null (rely on stored home city), time_context="today"
- Set trip_type to "travel" when the user clearly wants to go somewhere away (city named, or overnight/multi-day trip)
- Set trip_type to null when unclear

User input: "{user_input}"
Last prompt: "{last_prompt}"
Has plans loaded: {has_plans}

Output JSON schema:
{{
  "mode": "plan|refine|city|calendar|save|history|tips|notion|clarify|exit",
  "city": "city or null",
  "trip_type": "outing|travel|null",
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
# Free routing API -- no key required
OSRM_ROUTE_URL = "http://router.project-osrm.org/route/v1/driving"
# Free country info API -- no key required
RESTCOUNTRIES_URL = "https://restcountries.com/v3.1/capital"


class MicroAdventurePlannerAbility(MatchingCapability):
    """Create nearby short plans using weather + air quality + local discovery."""

    # {{register capability}}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    current_plans: list[dict] = None
    _is_running: bool = False

    def call(self, worker: AgentWorker):
        if MicroAdventurePlannerAbility._is_running:
            # Already active -- silently ignore the re-trigger
            return
        MicroAdventurePlannerAbility._is_running = True
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.current_plans = []
        self._last_plan_context: dict = {}
        self._ip_country_code: str = ""  # populated by _fetch_ip_city
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
                "Hey! Ready to plan your next adventure. "
                "Just tell me where you want to go and I'll sort everything out for you."
            )

            if not prefs.get("home_city"):
                await self._first_run_city_setup(prefs)

            prompt = "So, where do you want to go? Or just tell me the vibe -- relaxing, exploring, food, whatever."
            idle_count = 0

            for _ in range(20):
                user_input = await self.capability_worker.run_io_loop(prompt)
                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= _IDLE_MAX:
                        await self.capability_worker.speak(
                            "Looks like you stepped away -- talk soon!"
                        )
                        break
                    prompt = (
                        "Still with me? Just say something like 'restaurants in Paris' or 'weekend in Rome'."
                        if idle_count >= _IDLE_WARN
                        else "I'm here whenever you're ready. What sounds good?"
                    )
                    continue

                idle_count = 0
                lowered = user_input.lower().strip()
                if lowered in EXIT_WORDS or any(
                    x in lowered for x in EXIT_WORDS if len(x.split()) > 1
                ):
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
                        await self.capability_worker.speak(
                            f"Saved. Default city is now {city}."
                        )
                    else:
                        await self.capability_worker.speak(
                            "Tell me the city name you want to use."
                        )
                    prompt = "What should I plan for you?"
                    continue

                if mode == "calendar":
                    ok = await self._calendar_handoff(intent)
                    prompt = (
                        "Want another plan?"
                        if ok
                        else "I can build a plan first. What do you want to do?"
                    )
                    continue

                if mode == "save":
                    ok = await self._save_itinerary(intent, prefs)
                    prompt = (
                        "Saved. Want another plan or check your trip history?"
                        if ok
                        else "I need a plan first. What should I search for?"
                    )
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

                if mode == "notion":
                    ok = await self._post_to_notion(prefs)
                    prompt = (
                        "Posted to Notion. Want to plan something else or check travel tips?"
                        if ok
                        else "Notion posting failed. Make sure your Notion API key and database ID are set."
                    )
                    continue

                if mode == "refine" and self.current_plans:
                    await self._speak_refined(intent)
                    prompt = (
                        "Want details on one option, add to calendar, or refine again?"
                    )
                    continue

                found = await self._handle_plan(intent, prefs)
                prompt = (
                    "Want to save these, post to Notion, hear travel tips, or refine options?"
                    if found
                    else "I can try a different vibe, budget, or city."
                )

        except Exception as exc:
            self._err(f"Fatal run loop error: {exc}")
            await self.capability_worker.speak(
                "Sorry, something went wrong while planning."
            )
        finally:
            MicroAdventurePlannerAbility._is_running = False
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
            ans = await self.capability_worker.run_io_loop(
                f"Looks like you're in {city} -- want me to use that as your home base?"
            )
            if ans and any(
                x in ans.lower() for x in ("yes", "sure", "ok", "yep", "yeah")
            ):
                prefs["home_city"] = city
                prefs["home_country_code"] = self._ip_country_code
                await self._save_prefs(prefs)
                return
            # User may have said something like "Use Cairo instead" -- try to extract city
            alt = self._extract_city_from_text(ans or "")
            if alt and alt.lower() != city.lower():
                prefs["home_city"] = alt
                await self._save_prefs(prefs)
                await self.capability_worker.speak(
                    f"Perfect, I'll go with {alt} as your home base."
                )
                return
        ans = await self.capability_worker.run_io_loop(
            "Quick question -- what city should I use as your starting point?"
        )
        if ans:
            # Always extract city name -- avoids storing sentences like 'I plan to go to France.'
            extracted = self._extract_city_from_text(ans)
            city_to_save = extracted or ans.strip()
            prefs["home_city"] = city_to_save
            await self._save_prefs(prefs)
            await self.capability_worker.speak(
                f"Got it -- I'll remember {city_to_save} for you."
            )

    async def _fetch_ip_city(self) -> Optional[str]:
        try:
            ip = self.worker.user_socket.client.host
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{IP_GEO_URL}/{ip}")
            if resp.status_code == 200 and resp.json().get("status") == "success":
                data = resp.json()
                self._ip_country_code = data.get("countryCode", "")
                return data.get("city")
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
        if any(
            x in lower
            for x in (
                "save this",
                "save plan",
                "bookmark",
                "save itinerary",
                "keep this",
            )
        ):
            return {"mode": "save", "reference": "first"}
        if any(
            x in lower
            for x in (
                "trip history",
                "past trips",
                "saved plans",
                "my itineraries",
                "what have i",
            )
        ):
            return {"mode": "history"}
        if any(
            x in lower
            for x in (
                "travel tips",
                "packing",
                "currency",
                "language",
                "what to pack",
                "travel advice",
            )
        ):
            city_guess = self._extract_city_from_text(user_input)
            return {"mode": "tips", "city": city_guess}
        if any(
            x in lower
            for x in (
                "post to notion",
                "share to notion",
                "send to notion",
                "add to notion",
                "notion",
            )
        ):
            return {"mode": "notion"}
        if any(
            x in lower
            for x in (
                "cheaper",
                "indoor",
                "outdoor",
                "closer",
                "quieter",
                "more active",
            )
        ):
            return {"mode": "refine", "budget": "low" if "cheap" in lower else None}
        # ── Local outing fast-path ────────────────────────────────────────
        # If user says "restaurant today" / "cafe tonight" with no clear
        # multi-day destination, treat it as a local outing near home city.
        LOCAL_TIME_WORDS = ("today", "tonight", "now", "this evening", "right now")
        is_local_time = any(w in lower for w in LOCAL_TIME_WORDS)
        LOCAL_FOCUSES = ("food", "sights", "activities")
        if is_local_time and detected_focus in LOCAL_FOCUSES:
            return {
                "mode": "plan",
                "city": None,  # use home_city
                "focus": detected_focus,
                "trip_type": "outing",
                "time_context": "today",
                "vibe": self._parse_vibe_text(user_input),
                "budget": self._parse_budget_text(user_input)
                if any(c.isdigit() for c in user_input)
                else None,
                "raw_input": user_input,
            }

        travel_markers = ("travel to", "go to", "trip to", "in ", "at ")
        if any(x in lower for x in travel_markers):
            city_guess = self._extract_city_from_text(user_input)
            # Reject STT noise where the "city" is actually a common English verb/noun
            _NOT_A_CITY = {
                "eat",
                "drink",
                "play",
                "have",
                "get",
                "see",
                "do",
                "go",
                "find",
                "look",
                "try",
                "make",
                "take",
                "come",
                "know",
                "work",
                "run",
                "walk",
                "swim",
                "hike",
                "dance",
                "sleep",
                "food",
                "lunch",
                "dinner",
                "breakfast",
                "brunch",
                "meal",
                "fun",
                "heat",
                "beat",
                "meet",
                "gym",
                "park",
                "cafe",
                "restaurant",
                "shop",
                "mall",
                "beach",
                "home",
            }
            # Only trust the fast-path if it looks like a real city name (<=3 words, not a verb)
            if (
                city_guess
                and len(city_guess.split()) <= 3
                and city_guess.lower() not in _NOT_A_CITY
            ):
                # Decide trip type from duration hints
                is_week = any(w in lower for w in ("week", "7 day", "7day"))
                is_weekend = any(w in lower for w in ("weekend", "2 day", "2day"))
                trip_type = (
                    "travel" if is_week else ("weekend" if is_weekend else "travel")
                )
                return {
                    "mode": "plan",
                    "city": city_guess,
                    "focus": detected_focus,
                    "trip_type": trip_type,
                    "vibe": self._parse_vibe_text(user_input),
                    "budget": self._parse_budget_text(user_input)
                    if any(c.isdigit() for c in user_input)
                    else None,
                    "time_context": "today" if "today" in lower else None,
                    "raw_input": user_input,
                }
        if len(lower.split()) <= _WORD_LIMIT_SHORT and any(
            x in lower for x in ("plan", "ideas", "suggest")
        ):
            return {"mode": "plan", "focus": detected_focus, "raw_input": user_input}

        prompt = _INTENT_TEMPLATE.format(
            user_input=user_input,
            last_prompt=last_prompt,
            has_plans="yes" if self.current_plans else "no",
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            data = json.loads(self._strip_fences(raw))
            if data.get("mode") in VALID_MODES:
                # Reject a 'plan' decision from LLM if there's no city in the intent
                # and no valid home city is stored -- avoids single noise words triggering plans
                if (
                    data.get("mode") == "plan"
                    and not data.get("city")
                    and len(lower.split()) <= 2
                ):
                    return {"mode": "clarify", "raw_input": user_input}
                focus = (data.get("focus") or "").lower().strip()
                if focus not in VALID_FOCUS:
                    data["focus"] = detected_focus
                # If LLM returned a plan with no city and no outing flag, it may have been
                # confused by STT noise ("Travel Dravel"). Ask LLM directly rather than
                # relying on hardcoded keyword lists.
                if (
                    data.get("mode") == "plan"
                    and not data.get("city")
                    and data.get("trip_type") != "outing"
                ):
                    verdict = self.capability_worker.text_to_text_response(
                        f'Voice input (may contain STT noise): "{user_input}"\n'
                        "Ignoring any garbled words at the start, is the user's real intent to do a "
                        "LOCAL outing near their current city (eat out, play a sport, visit somewhere nearby) "
                        "with NO travel destination mentioned?\n"
                        "Reply with exactly one word: YES or NO."
                    )
                    if (verdict or "").strip().upper().startswith("Y"):
                        data["trip_type"] = "outing"
                        data["city"] = None
                        data["time_context"] = data.get("time_context") or "today"
                data["raw_input"] = (
                    user_input  # always attach so _gather_trip_details can read it
                )
                return data
        except Exception as exc:
            self._err(f"Intent classify fallback: {exc}")
        return {"mode": "plan", "focus": detected_focus, "raw_input": user_input}

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
        # Guard: reject exclusion phrases -- they name a region to AVOID, not a destination
        EXCLUSION_PREFIXES = (
            "outside ",
            "not ",
            "except ",
            "beyond ",
            "abroad",
            "other than",
            "international",
            "foreign",
            "be outside",
        )
        text_lower = text.lower().strip()
        if any(
            text_lower.startswith(p) or f" {p}" in text_lower
            for p in EXCLUSION_PREFIXES
        ):
            return None

        plain = re.sub(r"[^A-Za-z\s\-']", " ", text).strip()
        if (
            plain
            and len(plain.split()) <= 3
            and all(t.lower() not in CITY_STOP_WORDS for t in plain.split())
        ):
            # Cap to first 3 tokens to avoid accepting long STT noise
            return " ".join(plain.split()[:3])
        return None

    async def _handle_plan(self, intent: dict, prefs: dict) -> bool:
        city_from_intent = (intent.get("city") or "").strip()
        city_from_prefs = (prefs.get("home_city") or "").strip()
        city = city_from_intent or city_from_prefs
        if not city:
            await self.capability_worker.speak(
                "I need a city first. Tell me where to plan."
            )
            return False

        # ── Detect upfront "recommend a city" intent (no explicit destination given) ──
        RECOMMEND_TRIGGERS = (
            "recommend",
            "suggest",
            "where should",
            "where can",
            "best city",
            "good city",
            "nice city",
            "what city",
            "pick a city",
            "choose a city",
        )
        raw_input_lower = (intent.get("raw_input") or "").lower()
        wants_recommendation = any(t in raw_input_lower for t in RECOMMEND_TRIGGERS)

        # If LLM flagged this as an outing, ensure local_radius is set for nearby search
        if intent.get("trip_type") == "outing" and not intent.get("local_radius"):
            intent["local_radius"] = 20

        # ── When user gave no explicit destination, ask local-or-away ──────────────────
        if not city_from_intent and city_from_prefs and not intent.get("trip_type"):
            if wants_recommendation:
                # User asked for a city suggestion upfront -- skip local-or-away, go straight
                ans_lower = raw_input_lower
            else:
                ans = await self.capability_worker.run_io_loop(
                    f"Are you looking to explore somewhere near {city_from_prefs}, "
                    "or do you have a new destination in mind?"
                )
                ans_lower = (ans or "").lower()

            LOCAL_HINTS = (
                "near",
                "local",
                "here",
                "close",
                "around",
                "stay",
                "within",
                "nearby",
                "home",
                "yes",
                "current",
            )
            AWAY_RECOMMEND_HINTS = (
                "outside",
                "abroad",
                "international",
                "foreign",
                "not ",
                "except",
                "recommend",
                "suggest",
                "anywhere",
                "somewhere",
                "other country",
            )

            if any(w in ans_lower for w in LOCAL_HINTS) and not any(
                w in ans_lower for w in AWAY_RECOMMEND_HINTS
            ):
                # Local outing -- keep home city, flag for nearby search
                intent["trip_type"] = "outing"
                intent["local_radius"] = 20
            elif (
                any(w in ans_lower for w in AWAY_RECOMMEND_HINTS)
                or wants_recommendation
            ):
                # User wants a recommendation -- extract constraints from their input
                exclude_country = ""
                # Detect "outside X" / "not Egypt" / "except France" patterns
                excl_match = re.search(
                    r"(?:outside|not|except|beyond|other than)\s+([A-Za-z][A-Za-z\s]{1,40})",
                    ans_lower,
                )
                if excl_match:
                    exclude_country = excl_match.group(1).strip().title()
                elif prefs.get("home_country_code"):
                    # Default: exclude home country so we actually go abroad
                    exclude_country = prefs.get("home_country_code", "")

                vibe_hint = self._parse_vibe_text(ans_lower or raw_input_lower)
                budget_hint = (
                    intent.get("budget") or prefs.get("default_budget") or "medium"
                )
                await self.capability_worker.speak(
                    "Let me think of the perfect destination for you..."
                )
                suggested = await self._recommend_city(
                    vibe=vibe_hint,
                    budget=budget_hint,
                    exclude_country=exclude_country,
                    home_city=city_from_prefs,
                )
                if not suggested:
                    await self.capability_worker.speak(
                        "I couldn't come up with a suggestion right now. Could you name a city you have in mind?"
                    )
                    return False
                confirm = await self.capability_worker.run_io_loop(
                    f"How about {suggested}? Does that sound good?"
                )
                if confirm and any(
                    x in (confirm or "").lower()
                    for x in (
                        "yes",
                        "sure",
                        "ok",
                        "yep",
                        "yeah",
                        "great",
                        "perfect",
                        "sounds",
                        "let",
                        "go",
                    )
                ):
                    city = suggested
                    city_from_intent = suggested
                else:
                    # User rejected -- ask directly
                    dest_ans = await self.capability_worker.run_io_loop(
                        "Where would you like to go instead?"
                    )
                    city = (
                        self._extract_city_from_text(dest_ans or "")
                        or (dest_ans or "").strip()
                    )
                    if not city or city == city_from_prefs:
                        await self.capability_worker.speak(
                            "No problem -- just let me know when you have a place in mind."
                        )
                        return False
                    city_from_intent = city
            else:
                # User named a specific destination
                new_dest = self._extract_city_from_text(
                    ans if not wants_recommendation else raw_input_lower
                )
                if new_dest and new_dest.lower() != city_from_prefs.lower():
                    city = new_dest
                    city_from_intent = new_dest
                else:
                    dest_ans = await self.capability_worker.run_io_loop(
                        "Where do you want to go?"
                    )
                    new_dest = (
                        self._extract_city_from_text(dest_ans or "")
                        or (dest_ans or "").strip()
                    )
                    if new_dest:
                        city = new_dest
                        city_from_intent = new_dest
                    else:
                        await self.capability_worker.speak(
                            "No problem -- just tell me when you have a place in mind."
                        )
                        return False

        # Only show origin when it's genuinely different from the destination
        origin_city = (
            city_from_prefs
            if city_from_prefs and city_from_prefs.lower() != city.lower()
            else ""
        )

        # Parse budget from any dollar amounts in the raw intent before asking questions
        raw_budget = intent.get("budget") or ""
        if raw_budget:
            intent["budget"] = self._parse_budget_text(raw_budget)

        # Parse vibe if already mentioned
        raw_vibe = intent.get("vibe") or ""
        if raw_vibe:
            intent["vibe"] = self._parse_vibe_text(raw_vibe)

        # Gather any missing details conversationally before generating
        intent = await self._gather_trip_details(intent, prefs)

        # User corrected mid-intake (e.g. "No, I wanna go eat") -- re-classify and restart
        if intent.get("_abort"):
            abort_text = intent.pop("_abort")
            new_intent = await self._classify_intent(abort_text, "")
            new_intent.setdefault("raw_input", abort_text)
            if new_intent.get("mode") == "plan":
                return await self._handle_plan(new_intent, prefs)
            # Not a plan -- caller will handle any other mode
            return False

        budget = (
            intent.get("budget") or prefs.get("default_budget") or "medium"
        ).lower()
        vibe = (intent.get("vibe") or prefs.get("default_vibe") or "balanced").lower()
        indoor = (intent.get("indoor") or prefs.get("default_indoor") or "any").lower()
        time_context = (
            intent.get("duration") or intent.get("time_context") or "weekend"
        ).strip()
        focus = (intent.get("focus") or "activities").lower().strip()
        if focus not in VALID_FOCUS:
            focus = "activities"

        if origin_city:
            await self.capability_worker.speak(
                f"Great, planning your trip from {origin_city} to {city}. One moment."
            )
        else:
            await self.capability_worker.speak(
                f"Planning options in {city}. One moment."
            )

        # Pass country code when geocoding to avoid wrong-country matches (e.g. Badr EG vs SA)
        geocode_country = (
            prefs.get("home_country_code", "") if not city_from_intent else ""
        )
        geo = await self._geocode_city(city, country_code=geocode_country)
        if not geo:
            # If the bad city came from stored prefs, clear it so the user isn't stuck
            if not city_from_intent and city_from_prefs:
                prefs["home_city"] = None
                await self._save_prefs(prefs)
                await self.capability_worker.speak(
                    f"I couldn't locate your saved city '{city}'. "
                    "Please tell me which city you'd like to use."
                )
                return False

            # Try to recover via LLM city suggestion (handles noisy STT)
            suggestion = self._suggest_city(city)
            if suggestion and suggestion.lower() != city.lower():
                ans = await self.capability_worker.run_io_loop(
                    f"I couldn't locate '{city}'. Did you mean {suggestion}?"
                )
                if ans and any(
                    x in (ans or "").lower()
                    for x in ("yes", "sure", "ok", "yep", "yeah", "correct", "right")
                ):
                    geo = await self._geocode_city(suggestion)
                    if geo:
                        city = suggestion
                        # Update intent city so origin/destination display is correct
                        if (
                            not city_from_prefs
                            or city_from_prefs.lower() == suggestion.lower()
                        ):
                            origin_city = ""
                    if not geo:
                        await self.capability_worker.speak(
                            f"I still couldn't locate {suggestion}. Please tell me the city name."
                        )
                        return False
                else:
                    await self.capability_worker.speak(
                        "No problem. Tell me which city you'd like to plan for."
                    )
                    return False
            else:
                await self.capability_worker.speak(
                    f"I couldn't locate '{city}'. Try saying just the city name, like Rome or Cairo."
                )
                return False

        if not geo:
            return False

        lat, lon, country_name = geo
        weather_task = self._fetch_weather(lat, lon)
        aqi_task = self._fetch_aqi(lat, lon)
        search_task = self._fetch_serper_candidates(
            city=city,
            time_context=time_context,
            focus=focus,
            api_key=prefs.get("api_key_serper", ""),
            radius_km=int(intent.get("local_radius") or 0),
            country_name=country_name,
        )
        event_task = self._fetch_ticketmaster(
            city, time_context, prefs.get("api_key_ticketmaster", "")
        )

        weather, aqi, activities, events = await asyncio.gather(
            weather_task,
            aqi_task,
            search_task,
            event_task,
        )

        candidates = self._build_candidates(
            activities=activities,
            events=events,
            city=city,
            focus=focus,
            origin_city=origin_city,
        )
        ranked = self._rank_candidates(
            candidates, budget, vibe, indoor, weather, aqi, focus
        )
        self.current_plans = ranked[:3]

        if not self.current_plans:
            await self.capability_worker.speak(
                "I could not build a solid plan right now. Try a different city or mood."
            )
            return False

        dur = intent.get("duration") or time_context
        ttype = intent.get("trip_type") or "travel"

        # Store context so _speak_refined can reuse it without losing trip details
        self._last_plan_context = {
            "city": city,
            "budget": budget,
            "vibe": vibe,
            "indoor": indoor,
            "weather": weather,
            "aqi": aqi,
            "focus": focus,
            "duration": dur,
            "trip_type": ttype,
        }

        # Speak a short summary first, then let the user decide if they want the full plan
        await self._speak_plans_brief(
            city=city, focus=focus, duration=dur, trip_type=ttype
        )
        wants_full = await self.capability_worker.run_io_loop(
            "Want me to walk you through the full day-by-day plan, or is this a good start?"
        )
        if wants_full and any(
            x in (wants_full or "").lower()
            for x in (
                "yes",
                "sure",
                "full",
                "detail",
                "yeah",
                "yep",
                "tell",
                "go",
                "more",
                "please",
                "walk",
            )
        ):
            await self._speak_plans(
                city=city,
                budget=budget,
                vibe=vibe,
                indoor=indoor,
                weather=weather,
                aqi=aqi,
                focus=focus,
                duration=dur,
                trip_type=ttype,
            )
        self._log_plan_links(self.current_plans)
        return True

    # ------------------------------------------------------------------
    # Sequential intake -- gather missing trip details conversationally
    # ------------------------------------------------------------------
    async def _gather_trip_details(self, intent: dict, prefs: dict) -> dict:
        """Ask only about details that are genuinely missing from the intent."""
        trip_type = (intent.get("trip_type") or "").lower()

        # Local outings (restaurant/cafe/outing today) -- no need for any intake questions
        if trip_type == "outing":
            intent.setdefault("duration", "a few hours today")
            intent.setdefault("budget", prefs.get("default_budget") or "medium")
            return intent

        # --- Duration ---
        has_duration = bool(intent.get("duration"))
        has_time_ctx = bool(intent.get("time_context"))
        if not has_duration and not has_time_ctx:
            ans = await self.capability_worker.run_io_loop(
                "Nice! How long are you thinking -- a day, a weekend, or maybe a full week?"
            )
            if self._is_correction(ans):
                intent["_abort"] = ans
                return intent
            intent["duration"] = (ans or "weekend").strip()
        elif not has_duration and has_time_ctx:
            tc = (intent.get("time_context") or "").lower()
            if tc in ("today", "now", "tonight"):
                intent["duration"] = "a day trip"
            else:
                intent["duration"] = tc

        # --- Budget ---
        if not intent.get("budget"):
            ans = await self.capability_worker.run_io_loop(
                "And what's your rough budget? Could be low, medium, high -- or just say an amount like 2000 dollars."
            )
            if self._is_correction(ans):
                intent["_abort"] = ans
                return intent
            intent["budget"] = self._parse_budget_text(ans or "")

        # --- Vibe / mood ---
        VIBE_KEYWORDS = (
            "relax",
            "chill",
            "calm",
            "adventur",
            "active",
            "romantic",
            "romance",
            "cultur",
            "family",
            "social",
            "party",
            "thrill",
            "spa",
            "cozy",
            "fun",
        )
        raw_input = (intent.get("raw_input") or "").lower()
        vibe_in_input = any(w in raw_input for w in VIBE_KEYWORDS)
        if not vibe_in_input and (
            not intent.get("vibe") or intent.get("vibe") == "balanced"
        ):
            ans = await self.capability_worker.run_io_loop(
                "Last one -- what's the mood? Like relaxing, adventurous, cultural, romantic, or something else?"
            )
            if self._is_correction(ans):
                intent["_abort"] = ans
                return intent
            intent["vibe"] = self._parse_vibe_text(ans or "")

        return intent

    def _is_correction(self, text: str) -> bool:
        """Return True when the user is correcting/rejecting the current question
        rather than actually answering it (e.g. 'No, I wanna go eat')."""
        t = (text or "").strip().lower()
        if not t:
            return False
        # Repeated negations: "no no no", "no. no. no."
        if re.match(r"^(no[\s,.!]+){2,}", t):
            return True
        # Negation/correction starters
        NEGATION_START = (
            "no ",
            "no,",
            "no.",
            "nope",
            "nah ",
            "nah,",
            "wait ",
            "wait,",
            "actually",
            "never mind",
            "forget it",
            "stop ",
            "that's not",
            "i didn't",
            "i don't mean",
            "wrong",
            "not that",
        )
        if any(t.startswith(n) for n in NEGATION_START):
            return True
        # Fresh intent statement: re-intent signal without any duration words
        REINTENT_SIGNALS = (
            "i wanna",
            "i want to",
            "i'd like",
            "let's go",
            "let me go",
            "can we",
            "i need to",
            "how about",
            "what about",
        )
        DURATION_WORDS = (
            "day",
            "week",
            "weekend",
            "hour",
            "night",
            "month",
            "full",
            "short",
            "long",
            "few",
            "couple",
        )
        if any(s in t for s in REINTENT_SIGNALS):
            if not any(d in t for d in DURATION_WORDS):
                return True
        return False

    def _parse_budget_text(self, text: str) -> str:
        """Convert natural speech to low/medium/high, parsing dollar amounts."""
        lower = text.lower()
        # Extract dollar amounts: $22,000  22000  22k
        m = re.search(r"\$?([\d,]+)\s*k?", lower)
        if m:
            try:
                amount = int(m.group(1).replace(",", ""))
                if "k" in lower[m.end() - 1 : m.end() + 1]:
                    amount *= 1000
                if amount >= 5000:
                    return "high"
                if amount >= 1000:
                    return "medium"
                return "low"
            except ValueError:
                pass
        if any(
            w in lower for w in ("high", "luxury", "premium", "expensive", "unlimited")
        ):
            return "high"
        if any(w in lower for w in ("low", "budget", "cheap", "economy", "affordable")):
            return "low"
        return "medium"

    def _parse_vibe_text(self, text: str) -> str:
        """Convert natural vibe descriptions to internal vibe tokens."""
        lower = text.lower()
        if any(
            w in lower
            for w in ("relax", "calm", "chill", "rest", "spa", "peace", "mood")
        ):
            return "quiet"
        if any(
            w in lower
            for w in ("adventur", "active", "hike", "sport", "thrill", "outdoor")
        ):
            return "active"
        if any(w in lower for w in ("cultur", "museum", "history", "art", "heritage")):
            return "quiet"
        if any(w in lower for w in ("romantic", "couple", "honey", "date")):
            return "quiet"
        if any(w in lower for w in ("social", "party", "festival", "family", "kid")):
            return "social"
        return "balanced"

    async def _speak_refined(self, intent: dict):
        lower_budget = intent.get("budget") == "low"
        reduced = sorted(
            self.current_plans,
            key=lambda x: (
                self._cost_score(x.get("cost", "medium")),
                x.get("score", 0),
            ),
            reverse=not lower_budget,
        )
        self.current_plans = reduced[:3]
        ctx = self._last_plan_context
        await self._speak_plans(
            city=ctx.get("city"),
            budget=ctx.get("budget"),
            vibe=ctx.get("vibe"),
            indoor=ctx.get("indoor"),
            weather=ctx.get("weather"),
            aqi=ctx.get("aqi"),
            focus=ctx.get("focus"),
            duration=ctx.get("duration"),
            trip_type=ctx.get("trip_type"),
            refined=True,
        )

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
        details = self._url_encode(
            item.get("reason", "Created with Micro Adventure Planner")
        )
        location = self._url_encode(item.get("location", ""))

        now = datetime.datetime.now(datetime.timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
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

    async def _geocode_city(
        self, city: str, country_code: str = ""
    ) -> Optional[tuple[float, float, str]]:
        """Geocode a city name.  Pass country_code (ISO 3166-1 alpha-2) to prefer the
        correct country when city names are ambiguous (e.g. Badr in EG vs SA).
        Returns (lat, lon, country_name) so callers can inject country into Serper queries."""
        try:
            params: dict = {"name": city, "count": 5, "language": "en"}
            if country_code:
                params["countryCode"] = country_code.upper()
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(GEOCODE_URL, params=params)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    # Prefer a result that matches the requested country
                    if country_code:
                        for r in results:
                            if (
                                r.get("country_code", "").upper()
                                == country_code.upper()
                            ):
                                return (
                                    float(r["latitude"]),
                                    float(r["longitude"]),
                                    r.get("country", ""),
                                )
                    # Fallback: highest-relevance result (first returned)
                    return (
                        float(results[0]["latitude"]),
                        float(results[0]["longitude"]),
                        results[0].get("country", ""),
                    )
        except Exception as exc:
            self._err(f"Geocode error: {exc}")
        return None

    async def _recommend_city(
        self,
        vibe: str,
        budget: str,
        exclude_country: str = "",
        home_city: str = "",
    ) -> Optional[str]:
        """Use LLM to recommend a travel destination matching vibe, budget, and season."""
        month = datetime.datetime.now().strftime("%B")
        exclude_hint = (
            f"Do NOT suggest any city in {exclude_country}." if exclude_country else ""
        )
        origin_hint = f"The user is travelling from {home_city}." if home_city else ""
        prompt = (
            f"You are a travel expert. Suggest ONE specific city for a "
            f"{vibe or 'relaxing'} {budget or 'medium'}-budget trip in {month}.\n"
            f"{origin_hint} {exclude_hint}\n"
            "Consider pleasant weather for the season, tourism value, and safety.\n"
            "Reply with ONLY the city name and country, format: City, Country\n"
            "Example: Lisbon, Portugal"
        )
        try:
            raw = (self.capability_worker.text_to_text_response(prompt) or "").strip()
            cleaned = raw.strip(" .,!?\"'").strip()
            # Reject multi-word noise or empty
            if (
                cleaned
                and 1 <= len(cleaned.split()) <= 5
                and cleaned.lower() not in ("null", "none")
            ):
                return cleaned
        except Exception as exc:
            self._err(f"City recommendation error: {exc}")
        return None

    def _suggest_city(self, raw_city: str) -> Optional[str]:
        """Use LLM to guess the real city from noisy/garbled STT text."""
        prompt = (
            f"A voice assistant received this noisy speech-to-text: '{raw_city}'.\n"
            "What is the most likely real city or country name the user intended?\n"
            "Reply with ONLY the city/country name (e.g. 'Italy', 'Cairo', 'Rome').\n"
            "If you cannot guess a real place, reply with the single word: null"
        )
        try:
            raw = (self.capability_worker.text_to_text_response(prompt) or "").strip()
            # Strip punctuation and validate
            cleaned = raw.strip(" .,!?\"'").strip()
            if cleaned.lower() in ("null", "", "none", "unknown"):
                return None
            # Reject multi-word noise that crept through
            if len(cleaned.split()) > 4:
                return None
            return cleaned
        except Exception as exc:
            self._err(f"City suggestion error: {exc}")
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

    async def _fetch_serper_candidates(
        self,
        city: str,
        time_context: str,
        focus: str,
        api_key: str,
        radius_km: int = 0,
        country_name: str = "",
    ) -> list[dict]:
        key = (SERPER_API_KEY or api_key or "").strip()
        if not key:
            return []
        # Include country to prevent wrong-country results (e.g. "Badr" → Montana, USA)
        city_q = f"{city}, {country_name}" if country_name else city
        location_q = (
            f"within {radius_km} km of {city_q}" if radius_km else f"in {city_q}"
        )
        try:
            queries: list[tuple[str, str]] = []
            if focus in ("activities", "mixed"):
                queries.append(
                    (f"things to do {location_q} {time_context}".strip(), "activity")
                )
            if focus in ("lodging", "mixed"):
                queries.append(
                    (f"best hotels and motels {location_q}".strip(), "lodging")
                )
            if focus in ("transport", "mixed"):
                queries.append(
                    (
                        f"local transportation options {location_q} {time_context}".strip(),
                        "transport",
                    )
                )
            if focus in ("food", "mixed"):
                queries.append(
                    (f"best restaurants and street food {location_q}".strip(), "food")
                )
            if focus in ("sights", "mixed"):
                queries.append(
                    (f"top attractions and landmarks {location_q}".strip(), "sights")
                )

            if not queries:
                queries.append(
                    (f"things to do in {city} {time_context}".strip(), "activity")
                )

            async with httpx.AsyncClient(timeout=10) as client:
                tasks = [
                    client.post(
                        SEARCH_URL,
                        headers={"X-API-KEY": key, "Content-Type": "application/json"},
                        json={"q": q},
                    )
                    for q, _ in queries
                ]
                responses = list(await asyncio.gather(*tasks))

            collected: list[dict] = []
            for idx, resp in enumerate(responses):
                result_type = queries[idx][1]
                if resp.status_code != 200:
                    continue
                organic = resp.json().get("organic", [])[:3]
                for row in organic:
                    raw_title = row.get("title", "Local option")
                    # Strip SEO noise: site names, year tags, "THE N BEST" prefixes
                    clean = re.sub(
                        r"\s*[-|]\s*(Tripadvisor|TripAdvisor|Yelp|Booking\.com|Expedia|Google Maps)[^\n]*$",
                        "",
                        raw_title,
                        flags=re.IGNORECASE,
                    )
                    clean = re.sub(r"\s*\([Uu]pdated\s+\d{4}\)", "", clean).strip()
                    clean = re.sub(
                        r"^(?:THE\s+)?\d+\s+BEST\s+", "", clean, flags=re.IGNORECASE
                    ).strip()
                    clean = clean or raw_title
                    collected.append(
                        {
                            "title": clean,
                            "location": city,
                            "url": row.get("link", ""),
                            "type": result_type,
                        }
                    )
            return collected
        except Exception as exc:
            self._err(f"Serper candidate error: {exc}")
        return []

    async def _fetch_ticketmaster(
        self, city: str, time_context: str, api_key: str
    ) -> list[dict]:
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
                    venue = (
                        event.get("_embedded", {})
                        .get("venues", [{}])[0]
                        .get("name", city)
                    )
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
        for row in activities + events:
            text = f"{row.get('title', '')} {row.get('location', '')}".lower()
            guessed_cost = "medium"
            if any(k in text for k in ("park", "walk", "museum free", "public")):
                guessed_cost = "low"
            if any(k in text for k in ("fine dining", "vip", "luxury", "premium")):
                guessed_cost = "high"

            indoor_guess = (
                "indoor"
                if any(k in text for k in ("museum", "gallery", "cafe", "theater"))
                else "outdoor"
            )
            if row.get("type") in ("lodging", "transport"):
                indoor_guess = "any"
            option_city = row.get("location", city)
            map_link = self._build_map_search_link(
                row.get("title", "Option"), option_city
            )
            route_link = ""
            if (
                row.get("type") == "transport"
                and origin_city
                and origin_city.lower() != city.lower()
            ):
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
                        "map_url": self._build_map_search_link(
                            "Budget hotel near center", city
                        ),
                        "route_url": "",
                    },
                    {
                        "title": "Comfort motel with parking",
                        "location": city,
                        "type": "lodging",
                        "cost": "medium",
                        "indoor": "any",
                        "url": "",
                        "map_url": self._build_map_search_link(
                            "Comfort motel with parking", city
                        ),
                        "route_url": "",
                    },
                    {
                        "title": "Premium resort stay",
                        "location": city,
                        "type": "lodging",
                        "cost": "high",
                        "indoor": "any",
                        "url": "",
                        "map_url": self._build_map_search_link(
                            "Premium resort stay", city
                        ),
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
                        "map_url": self._build_map_search_link(
                            "Intercity bus station", city
                        ),
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
                        "route_url": self._build_route_link(
                            origin_city or city, city, mode="driving"
                        )
                        if origin_city
                        else "",
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
                    "map_url": self._build_map_search_link(
                        "Scenic walk and coffee", city
                    ),
                    "route_url": "",
                },
                {
                    "title": "Local gallery and cafe",
                    "location": city,
                    "type": "activity",
                    "cost": "medium",
                    "indoor": "indoor",
                    "url": "",
                    "map_url": self._build_map_search_link(
                        "Local gallery and cafe", city
                    ),
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
            if vibe == "active" and any(
                k in item["title"].lower() for k in ("walk", "hike", "bike", "climb")
            ):
                score += 10
            if vibe == "quiet" and any(
                k in item["title"].lower()
                for k in ("gallery", "museum", "book", "park")
            ):
                score += 10
            if vibe == "social" and any(
                k in item["title"].lower()
                for k in ("live", "event", "festival", "market")
            ):
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

    async def _speak_plans_brief(
        self,
        city: Optional[str],
        focus: Optional[str],
        duration: Optional[str],
        trip_type: Optional[str],
    ):
        """Speak a concise 3-option summary without the full day-by-day narrative."""
        ordinals = ["First", "Second", "Third"]
        cost_label = {
            "low": "budget-friendly",
            "medium": "mid-range",
            "high": "premium",
        }
        parts = []
        for i, p in enumerate(self.current_plans[:3]):
            title = p.get("title", "Option")
            loc = p.get("location", city or "your area")
            cost_str = cost_label.get(p.get("cost", "medium"), "mid-range")
            parts.append(f"{ordinals[i]}, {title} in {loc} -- {cost_str}.")
        label = (
            "nearby outing"
            if trip_type == "outing"
            else f"{duration or 'weekend'} trip"
        )
        summary = f"I've got 3 options for your {city or 'area'} {label}. " + " ".join(
            parts
        )
        await self.capability_worker.speak(summary)

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
        duration: Optional[str] = None,
        trip_type: Optional[str] = None,
    ):
        rain = float((weather or {}).get("precipitation", 0) or 0)
        aqi_val = float((aqi or {}).get("us_aqi", 0) or 0)
        options_text = "\n".join(
            f"- {p['title']} ({p.get('type', 'activity')}, {p.get('location', city)}) URL: {p.get('url', '')}"
            for p in self.current_plans[:3]
        )
        base = (
            f"You are a fun, knowledgeable travel buddy chatting with a friend.\n"
            f"Keep it warm, casual, and exciting.\n\n"
            f"Details:\n"
            f"- City: {city or 'unknown'}\n"
            f"- Duration: {duration or 'today'}\n"
            f"- Budget: {budget or 'medium'} (high=luxury, medium=comfortable, low=budget)\n"
            f"- Vibe: {vibe or 'balanced'}\n"
            f"- Focus: {focus or 'activities'}\n"
            f"- Weather: rain={rain:.1f}mm, AQI={aqi_val:.0f}\n"
            f"- Options:\n{options_text}\n\n"
        )

        if (trip_type or "travel") == "outing":
            prompt = (
                base
                + "This is a LOCAL OUTING (going out today, not a trip). Write 3-4 casual spoken sentences.\n"
                "Cover: (1) which place to go and why it's great, (2) what to order or do there, "
                "(3) how to get there from home, (4) rough cost in dollars.\n\n"
                "Example: 'You should definitely check out Le Petit Bistro -- it's cozy, great vibe, "
                "and their lamb tagine is amazing. It'll run you about $25 per person. "
                "Just grab an Uber and you're there in 15 minutes. Definitely worth it tonight!'\n\n"
                "No bullet points, no markdown. Sound like a friend texting a recommendation."
            )
        elif (trip_type or "travel") == "weekend":
            prompt = (
                base
                + "This is a WEEKEND TRIP (2-3 days). Write 5-7 casual spoken sentences.\n"
                "Cover: (1) Day 1 morning/afternoon/evening, (2) Day 2 highlights, "
                "(3) one specific food spot per day, (4) how to get there and around, "
                "(5) rough daily budget.\n\n"
                "Example: 'Kick off Friday evening by checking into your hotel and heading straight "
                "to the old town for dinner -- try the local seafood at Marina Grill, around $35. "
                "Saturday, start with the castle tour in the morning ($12 entry), "
                "grab a shawarma wrap for lunch for about $8, then explore the souks in the afternoon. "
                "Getting there is easy -- a 2-hour train ride, about $20 each way. "
                "Budget around $150 a day all in and you'll be comfortable.'\n\n"
                "No bullet points, no markdown. Sound like you just got back and want to share every detail."
            )
        else:  # travel / multi-day
            prompt = (
                base
                + "This is a MULTI-DAY TRAVEL TRIP. Write 7-10 casual spoken sentences.\n"
                "Cover all 4 sections WITH examples:\n\n"
                "1. DAYS -- walk through each day.\n"
                "   Example: 'Day 1, land in Paris, check in near the Marais, "
                "then wander to the Eiffel Tower for sunset.'\n\n"
                "2. FOOD -- one specific spot or dish per day.\n"
                "   Example: 'For dinner on Day 1 try Chez Janou -- their chocolate mousse is legendary, "
                "about $40 for two.'\n\n"
                "3. TRANSPORT -- flights, trains, local metro.\n"
                "   Example: 'Fly into CDG, grab the RER B for $12, metro day pass is $8.'\n\n"
                "4. BUDGET -- rough daily cost in dollars.\n"
                "   Example: 'Budget around $120 a day -- $40 food, $50 activities, $30 transport.'\n\n"
                "No bullet points, no markdown. Sound like a friend who can't wait to tell you about this trip."
            )

        try:
            summary = self.capability_worker.text_to_text_response(prompt)
        except Exception:
            summary = None
        if not summary or len(summary.strip()) < 20:
            ordinals = ["First", "Second", "Third"]
            parts = [
                f"{ordinals[i]}, {p['title']} in {p.get('location', city or 'your city')}."
                for i, p in enumerate(self.current_plans[:3])
            ]
            summary = (
                "Here are your refined options. "
                if refined
                else "Great news! Here is your plan. "
            ) + " ".join(parts)
        await self.capability_worker.speak(summary)

        # Speak place links so user can find them easily
        link_parts = []
        for p in self.current_plans[:3]:
            url = p.get("url") or p.get("map_url") or ""
            if url:
                link_parts.append(f"{p['title']}: {url}")
        if link_parts:
            await self.capability_worker.speak(
                "I've also got links for you -- " + ", and ".join(link_parts[:3])
            )

    def _log_plan_links(self, plans: list[dict]):
        for idx, plan in enumerate(plans[:3], start=1):
            if plan.get("map_url"):
                self._log(f"Option {idx} map: {plan['map_url']}")
            if plan.get("route_url"):
                self._log(f"Option {idx} route: {plan['route_url']}")

    def _reason_text(
        self, item: dict, budget: str, indoor: str, rainy: bool, aqi_value: float
    ) -> str:
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

    def _build_route_link(
        self, origin: str, destination: str, mode: str = "transit"
    ) -> str:
        origin_q = self._url_encode(origin)
        destination_q = self._url_encode(destination)
        travel_mode = (
            mode
            if mode in ("driving", "walking", "bicycling", "transit")
            else "transit"
        )
        return (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={origin_q}&destination={destination_q}&travelmode={travel_mode}"
        )

    def _cost_score(self, cost: str) -> int:
        return {"low": 3, "medium": 2, "high": 1}.get((cost or "medium").lower(), 2)

    # ------------------------------------------------------------------ #
    # Feature: Notion Integration -- post plans as a professional page
    # ------------------------------------------------------------------ #

    async def _post_to_notion(self, prefs: dict) -> bool:
        """Post current plans to Notion as a rich, professional planner page."""
        if not self.current_plans:
            await self.capability_worker.speak(
                "I don't have any plans to post yet. Generate a plan first."
            )
            return False

        api_key = (prefs.get("notion_api_key") or NOTION_API_KEY or "").strip()
        db_id = (prefs.get("notion_database_id") or NOTION_DATABASE_ID or "").strip()

        if not api_key:
            await self.capability_worker.speak(
                "I need your Notion API key. Set notion_api_key in your preferences or in the main.py constants."
            )
            return False
        if not db_id:
            await self.capability_worker.speak(
                "I need your Notion database ID. Set notion_database_id in your preferences or in the main.py constants."
            )
            return False

        city = self.current_plans[0].get("location", "Unknown City")
        now = datetime.datetime.now(datetime.timezone.utc)
        date_str = now.strftime("%B %d, %Y")
        time_str = now.strftime("%H:%M UTC")

        # -- Build Notion blocks -----------------------------------------
        blocks: list[dict] = []
        COMPASS = "\U0001f9ed"  # compass
        MAP = "\U0001f5fa\ufe0f"  # world map
        PIN = "\U0001f4cc"  # pushpin
        STAR = "\u2728"  # sparkles

        # Header callout -- plan summary
        blocks.append(
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"Adventure Plan for {city}  \u00b7  {date_str}  \u00b7  {time_str}"
                            },
                            "annotations": {"bold": True},
                        }
                    ],
                    "icon": {"type": "emoji", "emoji": COMPASS},
                    "color": "blue_background",
                },
            }
        )

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Section header
        blocks.append(
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": f"{MAP}  Your Top Options"},
                        }
                    ],
                    "color": "default",
                },
            }
        )

        type_label = {
            "activity": "Activity",
            "food": "Food",
            "sights": "Sights",
            "lodging": "Lodging",
            "transport": "Transport",
            "event": "Event",
        }
        cost_label = {"low": "Low ($)", "medium": "Medium ($$)", "high": "High ($$$)"}
        ordinals = ["Option 1", "Option 2", "Option 3"]

        for idx, plan in enumerate(self.current_plans[:3]):
            plan_type = plan.get("type", "activity")
            title_text = plan.get("title", "Option")
            location = plan.get("location", city)
            cost = cost_label.get(
                plan.get("cost", "medium"), plan.get("cost", "medium")
            )
            type_str = type_label.get(plan_type, plan_type.capitalize())
            reason = plan.get("reason", "")
            map_url = plan.get("map_url", "")
            route_url = plan.get("route_url", "")
            info_url = plan.get("url", "")

            # Sub-heading per option
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": f"{PIN}  {ordinals[idx]}: {title_text}"
                                },
                                "annotations": {"bold": True},
                            }
                        ],
                        "color": "default",
                    },
                }
            )

            # Details as a bulleted list
            detail_items = [
                f"Location: {location}",
                f"Type: {type_str}    |    Budget: {cost}",
                f"Note: {reason}" if reason else None,
            ]
            for detail in detail_items:
                if not detail:
                    continue
                blocks.append(
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [
                                {"type": "text", "text": {"content": detail}}
                            ],
                            "color": "default",
                        },
                    }
                )

            # Link bullets (map, route, info)
            link_items = []
            if map_url:
                link_items.append(("Open on Google Maps", map_url))
            if route_url:
                link_items.append(("Get Directions", route_url))
            if info_url:
                link_items.append(("More Info", info_url))

            for link_text, link_href in link_items:
                blocks.append(
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": link_text,
                                        "link": {"url": link_href},
                                    },
                                    "annotations": {"color": "blue", "underline": True},
                                }
                            ],
                            "color": "default",
                        },
                    }
                )

            # Spacer paragraph between options
            if idx < len(self.current_plans[:3]) - 1:
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": []},
                    }
                )

        # Footer divider + generated-by note
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"{STAR} Generated by Micro Adventure Planner \u00b7 OpenHome"
                            },
                            "annotations": {"italic": True, "color": "gray"},
                        }
                    ],
                },
            }
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

        # -- Detect the correct title property name from the database schema --
        title_prop_name = "Name"  # sensible default
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                db_resp = await client.get(
                    f"https://api.notion.com/v1/databases/{db_id}",
                    headers=headers,
                )
            if db_resp.status_code == 200:
                db_props = db_resp.json().get("properties", {})
                for k, v in db_props.items():
                    if v.get("type") == "title":
                        title_prop_name = k
                        break
        except Exception as exc:
            self._err(f"Notion schema fetch failed (using default 'Name'): {exc}")

        # -- POST to Notion -----------------------------------------------
        payload = {
            "parent": {"database_id": db_id},
            "icon": {"type": "emoji", "emoji": COMPASS},
            "cover": None,
            "properties": {
                title_prop_name: {
                    "title": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"Adventure Plan \u2014 {city}  ({date_str})"
                            },
                        }
                    ]
                }
            },
            "children": blocks,
        }

        try:
            await self.capability_worker.speak(
                f"Posting your {city} adventure plan to Notion..."
            )
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    NOTION_PAGES_URL, headers=headers, json=payload
                )
            if resp.status_code in (200, 201):
                page_url = resp.json().get("url", "")
                self._log(f"Notion page created: {page_url}")
                await self.capability_worker.speak(
                    f"Done! Your {city} adventure plan is now in Notion. The page link has been sent to your logs."
                )
                return True
            else:
                error_msg = resp.json().get("message", resp.text[:120])
                self._err(f"Notion API error {resp.status_code}: {error_msg}")
                await self.capability_worker.speak(
                    f"Notion returned an error: {error_msg}. Check your API key and database ID."
                )
                return False
        except Exception as exc:
            self._err(f"Notion post failed: {exc}")
            await self.capability_worker.speak(
                "Failed to connect to Notion. Check your internet connection."
            )
            return False

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
        history.append(
            {
                "date": entry["saved_at"],
                "city": entry["city"],
                "plan_count": len(entry["plans"]),
                "highlights": [p["title"] for p in entry["plans"]],
            }
        )
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
    # Feature: Travel tips -- currency, language, packing (#2, #3, #4, #8)
    # ------------------------------------------------------------------ #

    async def _speak_travel_tips(self, city: str, prefs: dict):
        """Generate travel tips using LLM + real weather + optional country API."""
        if not city:
            await self.capability_worker.speak(
                "Which city do you need travel tips for?"
            )
            return

        await self.capability_worker.speak(
            f"Getting travel tips for {city}. One moment."
        )

        # Fetch weather for packing advice
        geo = await self._geocode_city(city)
        weather = {}
        if geo:
            lat, lon = geo[0], geo[1]
            weather = await self._fetch_weather(lat, lon)

        # Fetch country info (currency, languages)
        country_info = await self._fetch_country_info(city)

        # Estimate travel distance from home city
        origin_city = (prefs.get("home_city") or "").strip()
        distance_info = ""
        if origin_city and origin_city.lower() != city.lower() and geo:
            origin_geo = await self._geocode_city(origin_city)
            if origin_geo:
                distance_info = await self._fetch_travel_distance(
                    origin_geo[:2], geo[:2]
                )

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
            fallback = (
                f"For {city}: currency is {currency}, languages include {languages}."
            )
            if temp != "unknown":
                fallback += f" It's currently {temp} degrees."
            if distance_info:
                fallback += f" {distance_info}."
            await self.capability_worker.speak(fallback)

    async def _fetch_country_info(self, city: str) -> dict:
        """Fetch currency and language info via RestCountries API (free, no key)."""
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                resp = await client.get(
                    f"https://restcountries.com/v3.1/capital/{city}",
                    params={"fields": "currencies,languages"},
                )
            if resp.status_code != 200:
                # Fallback: try searching by city/country name
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
                    currency_str = (
                        ", ".join(
                            f"{v.get('name', k)} ({v.get('symbol', '')})"
                            for k, v in currencies.items()
                        )
                        if currencies
                        else "unknown"
                    )
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
