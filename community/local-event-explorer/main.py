"""Local Event Explorer ability for OpenHome."""

import asyncio
import datetime
import json
import re
from typing import Optional

import httpx

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

_IDLE_WARN = 2
_IDLE_MAX = 3
_WORD_LIMIT_SHORT = 5


class AppConfig:
    """Hardcoded API keys — override these for local development only."""

    TICKETMASTER_API_KEY = ""
    SEATGEEK_CLIENT_ID = ""
    SERPER_API_KEY = ""
    GOOGLE_CLIENT_ID = ""
    GOOGLE_CLIENT_SECRET = ""
    GOOGLE_ACCESS_TOKEN = ""
    GOOGLE_REFRESH_TOKEN = ""


PREFS_FILE = "event_explorer_prefs.json"
DEFAULT_PREFS = {
    "home_city": None,
    "api_key_ticketmaster": AppConfig.TICKETMASTER_API_KEY,
    "api_key_seatgeek": AppConfig.SEATGEEK_CLIENT_ID,
    "api_key_serper": AppConfig.SERPER_API_KEY,
}

TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
SEATGEEK_URL = "https://api.seatgeek.com/2/events"
SERPER_URL = "https://google.serper.dev/search"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"

EXIT_WORDS = {
    "exit", "stop", "quit", "cancel", "bye", "goodbye",
    "done", "leave", "nothing", "close", "end",
    "thanks", "thank", "nope",
}

EXIT_PHRASES = {
    "no thanks", "no thank you", "that's all", "that's it",
    "never mind", "nevermind", "not now", "i'm good", "im good",
    "nope",
}

INVALID_CITY_TOKENS = {
    "nearby", "here", "close", "around", "local", "near",
    "location", "area", "city", "place", "somewhere",
}

VALID_MODES = {"search", "expand", "calendar", "city", "clarify", "exit"}

EVENT_KEYWORDS = {
    "jazz", "concert", "comedy", "festival", "sports", "music", "theatre", "theater",
    "opera", "ballet", "dance", "show", "gig", "band", "rock", "pop", "classical",
    "hip-hop", "hiphop", "rap", "electronic", "edm", "blues", "country", "folk",
    "standup", "stand-up", "circus", "fair", "expo", "conference", "meetup",
    "event", "events", "tonight", "weekend", "tomorrow",
}

INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for a voice-activated local event explorer.
The user wants to find concerts, sports, comedy, or festivals.

Given the user's input, classify their intent into exactly ONE mode.
Return ONLY valid JSON on one line, with no code blocks or markdown fences.

Modes:
- "search": Look up events. Default to this mode whenever the user mentions ANY event type, category, or genre (e.g. "jazz", "comedy", "concert", "festival", "sports", "music"). Also use for phrases like "I'm looking for X", "find X", "any X events", "X event". Even a single word like "Jazz" or "Comedy" is a search request.
- "expand": Get details about a SPECIFIC event from a list already shown to the user. Only use if the user says "the first one", "second one", "tell me more about [specific event name already listed]". Do NOT use for general discovery.
- "calendar": Add an event to calendar. Phrases like "add that", "save it", "put it in my calendar". Also use when the assistant just asked about adding to calendar and the user says "yes", "sure", "ok", "please", "yeah".
- "city": Set default home city. Phrases like "I live in X", "my city is X", "change city to X".
- "clarify": ONLY use this if the input is truly gibberish, completely off-topic (not about events), or has zero useful content. Do NOT use clarify if any event type or location is mentioned.
- "exit": Stop/quit/cancel.

RULE: When in doubt between "search" and "clarify", always choose "search".
RULE: If the assistant's last question was about adding to calendar and the user says "yes"/"sure"/"ok"/"please"/"yeah", classify as "calendar".
RULE: If the assistant's last question was about searching again and the user says "yes"/"sure"/"ok", classify as "search".

User Input: "{user_input}"
Has events been shown to user already: {has_events}
Assistant's last question to the user: "{last_prompt}"

Format expected:
{{"mode": "search|expand|calendar|city|clarify|exit", "location": "city name or null", "category": "event type keyword or null", "time": "raw time phrase or null", "event_reference": "first|second|keyword or null"}}
"""

FOLLOWUP_PROMPT = """You are a helpful voice assistant for a local event explorer.
The user just had this interaction:

Last user message: "{user_input}"
What happened: {outcome}
Events currently loaded: {events_summary}

Generate a SHORT, natural followup question (1 sentence, voice-friendly, no lists).
Guide them toward what they can do next: search for events, get details, add to calendar, or change city.
Do not repeat what just happened. Be conversational and concise."""

DATE_PARSER_PROMPT = """Convert the following time phrase into ISO-8601 start and end datetimes.
Today's date and time (UTC) is: {now}

Time phrase: "{phrase}"

Rules:
- "tonight" = today 17:00 to tomorrow 04:00
- "tomorrow" = tomorrow 08:00 to tomorrow 23:59
- "this weekend" or "weekend" = nearest Friday 17:00 to Sunday 23:59
- "this week" = today to this Sunday 23:59
- "next week" = next Monday 00:00 to next Sunday 23:59
- Named day (e.g. "Saturday") = nearest upcoming that day, 00:00 to 23:59
- If you cannot parse it, return null for both fields.

Return ONLY valid JSON on one line:
{{"start": "YYYY-MM-DDTHH:MM:SSZ or null", "end": "YYYY-MM-DDTHH:MM:SSZ or null"}}
"""


def _strip_llm_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _resolve_key(config_key: str, prefs_key: Optional[str]) -> str:
    """Return the first non-empty key: AppConfig value takes priority over prefs."""
    return (config_key or prefs_key or "").strip()


def _is_invalid_city(city: str) -> bool:
    """Return True if the city string is a known STT artifact or generic token."""
    return _is_garbled_city(city) or city.lower().strip() in INVALID_CITY_TOKENS


def _is_garbled_city(city: str) -> bool:
    """Return True if the city name looks like an STT transcription artifact."""
    if not city:
        return False
    if len(city.split()) > 4:
        return True
    if len(city) > 40:
        return True
    non_ascii = sum(1 for c in city if ord(c) > 127)
    if non_ascii > 0 and (non_ascii / len(city)) > 0.3:
        return True
    return False


def _url_encode(text: str) -> str:
    """Percent-encode a string for use in URL query parameters."""
    if not text:
        return ""
    safe = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")
    result = []
    for char in str(text):
        if char == " ":
            result.append("+")
        elif char in safe:
            result.append(char)
        else:
            for byte in char.encode("utf-8"):
                result.append(f"%{byte:02X}")
    return "".join(result)


def _normalize_llm_str(val) -> Optional[str]:
    """Coerce LLM output fields to None when the model returns 'null'/'none'/empty."""
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ("null", "none", "n/a", "na", "unknown", ""):
        return None
    return str(val).strip()


def _format_time(time_str: str) -> str:
    """Convert '19:00:00' to '7:00 PM'. Returns original string on failure."""
    try:
        t = datetime.datetime.strptime(time_str[:5], "%H:%M")
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return time_str


class LocalEventExplorerAbility(MatchingCapability):
    """Voice-activated local event explorer."""

    # {{register capability}}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    current_events: list[dict] = None
    trigger_text: Optional[str] = None

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.current_events = []
        self.trigger_text = None

        try:
            if worker.transcription and worker.transcription.strip():
                self.trigger_text = worker.transcription.strip()
        except Exception:
            pass
        if not self.trigger_text:
            try:
                if worker.last_transcription and worker.last_transcription.strip():
                    self.trigger_text = worker.last_transcription.strip()
            except Exception:
                pass
        if not self.trigger_text:
            try:
                if worker.current_transcription and worker.current_transcription.strip():
                    self.trigger_text = worker.current_transcription.strip()
            except Exception:
                pass

        self.worker.session_tasks.create(self.run())

    def _log(self, msg: str):
        try:
            self.worker.editor_logging_handler.info(f"[EventExplorer] {msg}")
        except Exception:
            pass

    def _err(self, msg: str):
        try:
            self.worker.editor_logging_handler.error(f"[EventExplorer] {msg}")
        except Exception:
            pass

    async def run(self):
        try:
            self._log("Ability started")
            prefs = await self._load_prefs()

            await self.capability_worker.speak("Welcome to the Event Explorer.")

            if not prefs.get("home_city"):
                await self._handle_first_run(prefs)

            current_prompt = "What kind of events are you looking for?"
            idle_count = 0

            pending_input: Optional[str] = None
            if self.trigger_text and len(self.trigger_text.split()) > 1:
                pending_input = self.trigger_text

            for _ in range(20):
                if pending_input is not None:
                    user_input = pending_input
                    pending_input = None
                    spoken_prompt = ""
                else:
                    spoken_prompt = current_prompt
                    user_input = await self.capability_worker.run_io_loop(current_prompt)

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= _IDLE_MAX:
                        await self.capability_worker.speak("No response detected. Goodbye!")
                        break
                    if idle_count == _IDLE_WARN:
                        current_prompt = "Still here if you need me. What would you like to search for?"
                    else:
                        current_prompt = "Are you still there? You can ask for concerts tonight, or say exit."
                    continue

                idle_count = 0

                _lower = user_input.lower()
                _clean_words = {w.strip(".,!?;:'\"") for w in _lower.split()}
                _is_short = len(_lower.split()) <= _WORD_LIMIT_SHORT
                _is_exit = bool(_clean_words & EXIT_WORDS) or (
                    _is_short and any(p in _lower for p in EXIT_PHRASES)
                )
                if _is_exit:
                    await self.capability_worker.speak("Enjoy your events. Goodbye!")
                    break

                _nearby_words = {"nearby", "near me", "around me", "around here", "close by", "my location"}
                _user_wants_nearby = any(p in _lower for p in _nearby_words)

                _matched_kw = _clean_words & EVENT_KEYWORDS
                if _matched_kw and not self.current_events:
                    _kw = next(iter(_matched_kw))
                    intent = await self._classify_intent(user_input, spoken_prompt)
                    if intent.get("mode") == "clarify":
                        intent = {
                            "mode": "search",
                            "location": intent.get("location"),
                            "category": _kw,
                            "time": intent.get("time"),
                            "event_reference": None,
                        }
                else:
                    intent = await self._classify_intent(user_input, spoken_prompt)

                if intent.get("mode") == "clarify" and intent.get("location"):
                    intent["mode"] = "search"

                if _user_wants_nearby:
                    intent["_nearby_hint"] = True

                mode = intent.get("mode", "clarify")
                self._log(f"Classified intent: {intent}")

                if mode == "exit":
                    await self.capability_worker.speak("Enjoy your events. Goodbye!")
                    break

                elif mode == "search":
                    found = await self._handle_search(intent, prefs)
                    if found:
                        current_prompt = "Want details on one, or search again?"
                    else:
                        current_prompt = "What else can I search for?"

                elif mode == "expand":
                    expanded = await self._handle_expand(intent, prefs)
                    if expanded and self.current_events:
                        current_prompt = "Add it to your calendar, or search for something else?"
                    else:
                        current_prompt = await self._generate_followup(
                            user_input, "Expand could not find a matching event"
                        )

                elif mode == "calendar":
                    added = await self._handle_calendar(intent)
                    if added:
                        current_prompt = "Anything else?"
                    else:
                        current_prompt = "Search for events first, then I can add one to your calendar."

                elif mode == "city":
                    city = intent.get("location")
                    if city and not _is_invalid_city(city):
                        prefs["home_city"] = city
                        await self._save_prefs(prefs)
                        await self.capability_worker.speak(f"Got it. I've set your default city to {city}.")
                    else:
                        await self.capability_worker.speak("What city would you like to set as your default?")
                    current_prompt = "What events are you looking for?"

                elif mode == "clarify":
                    current_prompt = await self._generate_followup(
                        user_input, "User input was unclear or off-topic"
                    )

        except Exception as e:
            self._err(f"Fatal error in run loop: {e}")
            if self.capability_worker:
                await self.capability_worker.speak("Sorry, something went wrong with the Event Explorer.")
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()

    async def _load_prefs(self) -> dict:
        exists = await self.capability_worker.check_if_file_exists(PREFS_FILE, False)
        if exists:
            try:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                loaded = json.loads(raw)
                saved_city = loaded.get("home_city") or ""
                if saved_city and _is_invalid_city(saved_city):
                    self._log(f"Clearing invalid saved city: '{saved_city}'")
                    loaded["home_city"] = None
                    await self._save_prefs(loaded)
                return loaded
            except Exception as e:
                self._err(f"Error loading prefs: {e}")
        return dict(DEFAULT_PREFS)

    async def _save_prefs(self, prefs: dict):
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            await self.capability_worker.delete_file(PREFS_FILE, False)
        await self.capability_worker.write_file(PREFS_FILE, json.dumps(prefs), False)

    async def _handle_first_run(self, prefs: dict):
        ip_city = await asyncio.to_thread(self._fetch_ip_city)

        if ip_city:
            _ip_prompt = (
                f"It looks like you're in {ip_city}. "
                "Should I search for events near you, or would you prefer a different city?"
            )
            await self.capability_worker.speak(_ip_prompt)
            ans = await self.capability_worker.user_response()
            if ans:
                ans_lower = ans.lower()
                if any(w in ans_lower for w in ("yes", "sure", "ok", "nearby", "here", "that", "yep", "yeah")):
                    if not _is_invalid_city(ip_city):
                        prefs["home_city"] = ip_city
                        await self._save_prefs(prefs)
                    await self.capability_worker.speak(f"Got it, I'll search near {ip_city}.")
                    return
                intent = await self._classify_intent(ans, _ip_prompt)
                loc = intent.get("location") or ans.strip()
                if loc and not _is_invalid_city(loc):
                    prefs["home_city"] = loc
                    await self._save_prefs(prefs)
                    await self.capability_worker.speak(f"Got it, I've saved {loc} as your city.")
                    return

        _city_prompt = "What city would you like to search for events in?"
        await self.capability_worker.speak(_city_prompt)
        resp = await self.capability_worker.user_response()
        if resp:
            intent = await self._classify_intent(resp, _city_prompt)
            loc = intent.get("location") or resp.strip()
            if loc and not _is_invalid_city(loc):
                prefs["home_city"] = loc
                await self._save_prefs(prefs)
                await self.capability_worker.speak(f"Got it, I've saved {loc} as your city.")
            else:
                await self.capability_worker.speak(
                    "I didn't catch a city name. You can tell me your city anytime during our conversation."
                )

    def _fetch_ip_city(self) -> Optional[str]:
        try:
            ip = self.worker.user_socket.client.host
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"http://ip-api.com/json/{ip}")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    isp = data.get("isp", "").lower()
                    cloud_indicators = ["amazon", "aws", "google", "microsoft", "azure", "digitalocean"]
                    if not any(c in isp for c in cloud_indicators):
                        return data.get("city")
        except Exception as e:
            self._err(f"IP geolocation failed: {e}")
        return None

    def _refresh_google_token(self) -> bool:
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    TOKEN_REFRESH_URL,
                    data={
                        "client_id": AppConfig.GOOGLE_CLIENT_ID,
                        "client_secret": AppConfig.GOOGLE_CLIENT_SECRET,
                        "refresh_token": AppConfig.GOOGLE_REFRESH_TOKEN,
                        "grant_type": "refresh_token",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            if response.status_code == 200:
                AppConfig.GOOGLE_ACCESS_TOKEN = response.json().get("access_token", "")
                return True
            self._err(f"Token refresh failed: {response.status_code}")
            return False
        except Exception as e:
            self._err(f"Token refresh error: {e}")
            return False

    async def _classify_intent(self, user_input: str, last_prompt: str = "") -> dict:
        has_events = "yes" if self.current_events else "no"
        prompt = INTENT_CLASSIFIER_PROMPT.format(
            user_input=user_input,
            has_events=has_events,
            last_prompt=last_prompt,
        )

        for attempt in range(2):
            try:
                raw = await asyncio.to_thread(
                    self.capability_worker.text_to_text_response, prompt
                )
                clean = _strip_llm_fences(raw)
                result = json.loads(clean)
                mode = result.get("mode", "")
                if mode in VALID_MODES:
                    result["location"] = _normalize_llm_str(result.get("location"))
                    result["category"] = _normalize_llm_str(result.get("category"))
                    result["time"] = _normalize_llm_str(result.get("time"))
                    result["event_reference"] = _normalize_llm_str(result.get("event_reference"))
                    return result
                self._err(f"Unknown mode '{mode}' on attempt {attempt + 1}, retrying")
            except (json.JSONDecodeError, Exception) as e:
                self._err(f"Intent parsing failed on attempt {attempt + 1}: {e}")

        lower = user_input.lower()
        lower_words = {w.strip(".,!?;:'\"") for w in lower.split()}
        if lower_words & EXIT_WORDS:
            return {"mode": "exit"}
        if any(w in lower for w in ("add", "calendar", "save")):
            return {"mode": "calendar", "event_reference": None}
        if any(w in lower for w in ("detail", "more", "tell me", "expand")):
            return {"mode": "expand", "event_reference": None}
        return {"mode": "clarify", "location": None, "category": None, "time": None, "event_reference": None}

    async def _generate_followup(self, user_input: str, outcome: str) -> str:
        if self.current_events:
            names = ", ".join(e["name"] for e in self.current_events[:3])
            events_summary = f"Events shown: {names}"
        else:
            events_summary = "No events loaded"

        prompt = FOLLOWUP_PROMPT.format(
            user_input=user_input,
            outcome=outcome,
            events_summary=events_summary,
        )
        try:
            raw = await asyncio.to_thread(
                self.capability_worker.text_to_text_response, prompt
            )
            return raw.strip() or "What would you like to search for?"
        except Exception:
            return "What would you like to search for?"

    async def _parse_time_context(self, time_string: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """Convert a natural language time phrase to ISO-8601 start/end datetimes."""
        if not time_string:
            return None, None

        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        prompt = DATE_PARSER_PROMPT.format(now=now_str, phrase=time_string)

        try:
            raw = await asyncio.to_thread(
                self.capability_worker.text_to_text_response, prompt
            )
            data = json.loads(_strip_llm_fences(raw))
            start = data.get("start") or None
            end = data.get("end") or None
            return start, end
        except Exception as e:
            self._err(f"Date parsing failed for '{time_string}': {e}")
            return None, None

    def _resolve_event_ref(self, ref: str) -> Optional[dict]:
        """Resolve a spoken ordinal or keyword to an event in current_events."""
        if not self.current_events:
            return None

        ref = ref.lower().strip()

        word_to_idx = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
        for word, idx in word_to_idx.items():
            if word in ref:
                if idx < len(self.current_events):
                    return self.current_events[idx]
                return None

        for ev in self.current_events:
            if ref and ref in ev["name"].lower():
                return ev

        return None

    async def _fetch_ticketmaster(
        self,
        city: str,
        keyword: str,
        start_dt: Optional[str],
        end_dt: Optional[str],
        api_key: str,
    ) -> list[dict]:
        key = _resolve_key(AppConfig.TICKETMASTER_API_KEY, api_key)
        if not key:
            return []

        params = {
            "apikey": key,
            "city": city,
            "size": 3,
            "sort": "date,asc",
            "locale": "*",
        }
        if keyword:
            params["keyword"] = keyword
        if start_dt:
            params["startDateTime"] = start_dt
        if end_dt:
            params["endDateTime"] = end_dt

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(TICKETMASTER_URL, params=params)
            if resp.status_code == 200:
                events = resp.json().get("_embedded", {}).get("events", [])
                parsed = []
                for e in events:
                    venues = e.get("_embedded", {}).get("venues", [])
                    venue_name = venues[0].get("name", "an unknown venue") if venues else "an unknown venue"
                    start = e.get("dates", {}).get("start", {})
                    parsed.append({
                        "name": e.get("name", "Unknown Event"),
                        "venue": venue_name,
                        "date": start.get("localDate", ""),
                        "time": start.get("localTime", ""),
                        "url": e.get("url", ""),
                        "source": "Ticketmaster",
                    })
                return parsed
        except Exception as e:
            self._err(f"Ticketmaster API error: {e}")
        return []

    async def _fetch_seatgeek(self, city: str, keyword: str, client_id: str) -> list[dict]:
        key = _resolve_key(AppConfig.SEATGEEK_CLIENT_ID, client_id)
        if not key:
            return []

        params: dict = {
            "client_id": key,
            "venue.city": city,
            "per_page": 3,
            "sort": "datetime_local.asc",
        }
        if keyword:
            params["q"] = keyword

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(SEATGEEK_URL, params=params)
            if resp.status_code == 200:
                parsed = []
                for e in resp.json().get("events", []):
                    dt_local = e.get("datetime_local", "")
                    parsed.append({
                        "name": e.get("title", "Unknown Event"),
                        "venue": e.get("venue", {}).get("name", "an unknown venue"),
                        "date": dt_local.split("T")[0] if "T" in dt_local else "",
                        "time": dt_local.split("T")[1][:5] if "T" in dt_local else "",
                        "url": e.get("url", ""),
                        "source": "SeatGeek",
                    })
                return parsed
        except Exception as e:
            self._err(f"SeatGeek API error: {e}")
        return []

    async def _fetch_serper(
        self, city: str, keyword: str, time_context: str, api_key: str
    ) -> list[dict]:
        key = _resolve_key(AppConfig.SERPER_API_KEY, api_key)
        if not key:
            return []

        query = f"events in {city}"
        if keyword:
            query += f" {keyword}"
        if time_context:
            query += f" {time_context}"

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(
                    SERPER_URL,
                    headers={"X-API-KEY": key, "Content-Type": "application/json"},
                    json={"q": query},
                )
            if resp.status_code == 200:
                parsed = []
                for e in resp.json().get("events", [])[:3]:
                    parsed.append({
                        "name": e.get("title", "Unknown Event"),
                        "venue": e.get("address", "an unknown location"),
                        "date": e.get("date", ""),
                        "time": "",
                        "url": e.get("link", ""),
                        "source": "Google Events",
                    })
                return parsed
        except Exception as e:
            self._err(f"Serper API error: {e}")
        return []

    async def _handle_search(self, intent: dict, prefs: dict):
        raw_location = intent.get("location")
        nearby_words = {"nearby", "near", "here", "around", "local", "close", "me"}

        user_wants_nearby = raw_location and raw_location.lower() in nearby_words

        if user_wants_nearby or (not raw_location and intent.get("_nearby_hint")):
            ip_city = await asyncio.to_thread(self._fetch_ip_city)
            if ip_city:
                _nearby_prompt = (
                    f"It looks like you're near {ip_city}. Should I search there, "
                    "or would you prefer your saved city?"
                )
                await self.capability_worker.speak(_nearby_prompt)
                ans = await self.capability_worker.user_response()
                if ans and any(
                    w in ans.lower()
                    for w in ("yes", "sure", "ok", "there", "that", "yep", "yeah", "nearby")
                ):
                    city = ip_city
                else:
                    ans_intent = await self._classify_intent(ans or "", _nearby_prompt)
                    city = ans_intent.get("location") or (ans or "").strip() or prefs.get("home_city")
            else:
                city = prefs.get("home_city")
                if not city:
                    _which_city_prompt = "What city would you like to search in?"
                    await self.capability_worker.speak(_which_city_prompt)
                    resp = await self.capability_worker.user_response()
                    if resp:
                        ex = await self._classify_intent(resp, _which_city_prompt)
                        city = ex.get("location") or (resp or "").strip()
        else:
            city = raw_location or prefs.get("home_city")

        if not city or _is_invalid_city(city):
            _unsure_prompt = "I'm not sure which city to search in. What city would you like?"
            await self.capability_worker.speak(_unsure_prompt)
            resp = await self.capability_worker.user_response()
            if resp:
                extracted = await self._classify_intent(resp, _unsure_prompt)
                city = extracted.get("location") or resp.strip()
            if not city or _is_invalid_city(city):
                await self.capability_worker.speak("I still couldn't get a valid city. Please try again.")
                return False

        keyword = intent.get("category", "")
        time_context = intent.get("time", "")

        search_desc = f"{keyword or 'events'} in {city}"
        if time_context:
            search_desc += f" for {time_context}"
        await self.capability_worker.speak(f"Let me check for {search_desc}...")

        start_dt, end_dt = await self._parse_time_context(time_context)

        tm_task = self._fetch_ticketmaster(
            city=city,
            keyword=keyword,
            start_dt=start_dt,
            end_dt=end_dt,
            api_key=prefs.get("api_key_ticketmaster", ""),
        )
        serper_task = self._fetch_serper(
            city=city,
            keyword=keyword,
            time_context=time_context,
            api_key=prefs.get("api_key_serper", ""),
        )
        tm_events, serper_events = await asyncio.gather(tm_task, serper_task)

        if not tm_events:
            self._log("Ticketmaster returned 0 events — trying SeatGeek.")
            tm_events = await self._fetch_seatgeek(
                city=city,
                keyword=keyword,
                client_id=prefs.get("api_key_seatgeek", ""),
            )

        combined = []
        if tm_events:
            combined.extend(tm_events[:2])
        if serper_events:
            combined.extend(serper_events[:2])

        seen: set = set()
        final_events: list[dict] = []
        for e in combined:
            title_lower = e["name"].lower().strip()
            if title_lower not in seen:
                seen.add(title_lower)
                final_events.append(e)

        self.current_events = final_events

        if not final_events:
            tm_key = _resolve_key(AppConfig.TICKETMASTER_API_KEY, prefs.get("api_key_ticketmaster", ""))
            serper_key = _resolve_key(AppConfig.SERPER_API_KEY, prefs.get("api_key_serper", ""))
            if not tm_key and not serper_key:
                msg = (
                    "I couldn't find any events. It looks like no API keys are configured — "
                    "please add your Ticketmaster or Serper key to get started."
                )
            else:
                msg = (
                    f"I couldn't find any {keyword or 'events'} in {city}"
                    + (f" for {time_context}" if time_context else "")
                    + ". Try a different category, city, or time?"
                )
            await self.capability_worker.speak(msg)
            return False

        ordinals = ["First", "Second", "Third", "Fourth", "Fifth"]
        summary = f"I found {len(final_events)} event{'s' if len(final_events) != 1 else ''}."
        for i, ev in enumerate(final_events):
            time_str = _format_time(ev["time"]) if ev["time"] else ""
            summary += f" {ordinals[i]}, {ev['name']} at {ev['venue']}"
            if time_str:
                summary += f" at {time_str}"
            summary += "."

        await self.capability_worker.speak(summary)
        return True

    async def _handle_expand(self, intent: dict, prefs: dict = None):
        if not self.current_events:
            await self.capability_worker.speak(
                "I don't have any events loaded yet. Let me search for those now."
            )
            search_intent = {
                "mode": "search",
                "location": intent.get("location"),
                "category": intent.get("category"),
                "time": intent.get("time"),
                "event_reference": None,
            }
            await self._handle_search(search_intent, prefs or {})
            return True

        ref = intent.get("event_reference") or "first"
        ev = self._resolve_event_ref(ref)

        if ev is None:
            await self.capability_worker.speak("I didn't find that event in the last search.")
            return False

        desc = f"{ev['name']} is happening at {ev['venue']}."
        if ev["date"]:
            desc += f" The date is {ev['date']}."
        if ev["time"]:
            desc += f" Starts at {_format_time(ev['time'])}."

        await self.capability_worker.speak(desc)
        return True

    async def _handle_calendar(self, intent: dict):
        ref = intent.get("event_reference") or "first"
        ev = self._resolve_event_ref(ref)

        if ev is None:
            if not self.current_events:
                await self.capability_worker.speak("I don't have any events loaded right now.")
            else:
                await self.capability_worker.speak("I didn't find that event in the last search.")
            return False

        if AppConfig.GOOGLE_ACCESS_TOKEN or AppConfig.GOOGLE_REFRESH_TOKEN:
            try:
                start_dt_str, end_dt_str = self._build_calendar_datetimes(ev)
                payload = {
                    "summary": ev.get("name", "Local Event"),
                    "location": ev.get("venue", ""),
                    "description": f"Found via OpenHome Local Event Explorer.\nLink: {ev.get('url', '')}",
                    "start": {"dateTime": start_dt_str},
                    "end": {"dateTime": end_dt_str},
                }
                headers = {"Authorization": f"Bearer {AppConfig.GOOGLE_ACCESS_TOKEN}"}

                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.post(CALENDAR_URL, headers=headers, json=payload)

                if response.status_code == 401:
                    refreshed = await asyncio.to_thread(self._refresh_google_token)
                    if refreshed:
                        headers["Authorization"] = f"Bearer {AppConfig.GOOGLE_ACCESS_TOKEN}"
                        async with httpx.AsyncClient(timeout=5) as client:
                            response = await client.post(CALENDAR_URL, headers=headers, json=payload)

                if response.status_code in (200, 201):
                    await self.capability_worker.speak(
                        f"I have successfully added {ev['name']} to your Google Calendar."
                    )
                    return True
                else:
                    self._err(f"Calendar API error: {response.status_code}")

            except Exception as e:
                self._err(f"Calendar exception: {e}")

        title = _url_encode(ev["name"])
        location = _url_encode(ev["venue"])
        details = _url_encode(f"Found via OpenHome Local Event Explorer. Link: {ev['url']}")

        dates_param = ""
        try:
            if ev.get("date"):
                t_str = (ev.get("time") or "12:00:00")[:8]
                dt = datetime.datetime.strptime(f"{ev['date']} {t_str}", "%Y-%m-%d %H:%M:%S")
                end_dt = dt + datetime.timedelta(hours=2)
                dates_param = f"&dates={dt.strftime('%Y%m%dT%H%M%S')}/{end_dt.strftime('%Y%m%dT%H%M%S')}"
        except Exception as e:
            self._log(f"Failed to parse dates for calendar link: {e}")

        cal_link = (
            f"https://calendar.google.com/calendar/r/eventedit"
            f"?text={title}&location={location}&details={details}{dates_param}"
        )
        self._log(f"Generated calendar link: {cal_link}")
        await self.capability_worker.speak(
            f"I generated an 'Add to Calendar' link for {ev['name']}. I've sent it to your device."
        )
        return True

    def _build_calendar_datetimes(self, ev: dict) -> tuple[str, str]:
        """Build ISO-8601 start/end strings for the Calendar API payload."""
        try:
            if ev.get("date"):
                t_str = (ev.get("time") or "12:00:00")[:8]
                naive_dt = datetime.datetime.strptime(f"{ev['date']}T{t_str}", "%Y-%m-%dT%H:%M:%S")
                start = naive_dt.isoformat() + "Z"
                end = (naive_dt + datetime.timedelta(hours=2)).isoformat() + "Z"
                return start, end
        except Exception:
            pass
        now = datetime.datetime.utcnow()
        return now.isoformat() + "Z", (now + datetime.timedelta(hours=2)).isoformat() + "Z"
