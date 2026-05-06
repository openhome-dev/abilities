from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

import asyncio
import difflib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import requests


API_BASE_URL = "https://subwayinfo.nyc/api"
ACTION_SET_DEFAULT = "set_default"
ACTION_ARRIVALS = "arrivals"
ACTION_HELP = "help"
ACTION_GET_DEFAULT = "get_default"
ROUTE_ALIASES = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "a": "A",
    "b": "B",
    "c": "C",
    "d": "D",
    "e": "E",
    "f": "F",
    "g": "G",
    "j": "J",
    "l": "L",
    "m": "M",
    "n": "N",
    "q": "Q",
    "r": "R",
    "s": "S",
    "w": "W",
    "z": "Z",
    "shuttle": "S",
}
NORTHBOUND_WORDS = {"northbound", "uptown", "north", "up"}
SOUTHBOUND_WORDS = {"southbound", "downtown", "south", "down"}
STREET_WORDS = {
    "st": "street",
    "street": "street",
    "ave": "avenue",
    "av": "avenue",
    "avenue": "avenue",
    "sq": "square",
    "square": "square",
    "plz": "plaza",
    "plaza": "plaza",
}
PREFS_KEY = "mta_next_train_prefs"
EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye",
    "nothing else", "i'm done", "that's it", "i'm good", "all set",
    "we're done", "no thanks", "never mind", "that's all",
    "all done", "i'm finished",
}

_ORDINAL_TO_IDX = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}


@dataclass
class Station:
    station_id: str
    name: str
    normalized_name: str
    borough: str = ""
    lines: List[str] = field(default_factory=list)


@dataclass
class StationMatch:
    station: Station
    score: float


@dataclass
class QueryIntent:
    action: str
    station_text: Optional[str] = None
    routes: List[str] = field(default_factory=list)
    direction: Optional[str] = None


@dataclass
class Arrival:
    route_id: str
    direction: str
    direction_label: str
    minutes_away: int
    headsign: str


def normalize_text(text: str) -> str:
    lowered = (text or "").strip().lower()
    lowered = lowered.replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    words = []
    for part in lowered.split():
        words.append(STREET_WORDS.get(part, part))
    return " ".join(words)


def station_from_api_item(item: Dict) -> Station:
    return Station(
        station_id=str(item.get("id", "")),
        name=str(item.get("name", "")).strip(),
        normalized_name=normalize_text(str(item.get("name", "")).strip()),
        borough=str(item.get("borough", "")).strip(),
        lines=[str(line) for line in item.get("lines", []) if str(line).strip()],
    )


def station_from_prefs(
    station_id: str,
    name: str,
    borough: str = "",
    lines: Optional[List[str]] = None,
) -> Station:
    return Station(
        station_id=station_id,
        name=name,
        normalized_name=normalize_text(name),
        borough=borough,
        lines=lines or [],
    )


def find_station_matches(
    stations: Sequence[Station], query: str, limit: int = 3
) -> List[StationMatch]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        return []

    matches: List[StationMatch] = []
    query_tokens = set(normalized_query.split())
    for station in stations:
        ratio = difflib.SequenceMatcher(
            None, normalized_query, station.normalized_name
        ).ratio()
        station_tokens = set(station.normalized_name.split())
        overlap = 0.0
        if station_tokens:
            overlap = len(query_tokens & station_tokens) / len(
                query_tokens | station_tokens
            )
        contains_bonus = 0.18 if normalized_query in station.normalized_name else 0.0
        prefix_bonus = 0.12 if station.normalized_name.startswith(normalized_query) else 0.0
        score = max(ratio, overlap) + contains_bonus + prefix_bonus
        if score >= 0.48:
            matches.append(StationMatch(station=station, score=score))

    matches.sort(key=lambda item: (-item.score, item.station.name))
    deduped: List[StationMatch] = []
    seen = set()
    for match in matches:
        key = (match.station.station_id, match.station.name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
        if len(deduped) == limit:
            break
    return deduped


def parse_query_intent(text: str) -> QueryIntent:
    normalized = normalize_text(text)
    routes = extract_routes(text, normalized)
    direction = extract_direction(normalized)

    for pattern in (
        r"(?:set|change|update|use)\s+(?:my\s+)?(?:default|home)\s+station(?:\s+to)?\s+(?P<station>.+)",
        r"my\s+(?:default\s+|home\s+)?station\s+is\s+(?P<station>.+)",
        r"use\s+(?P<station>.+)\s+as\s+(?:my\s+)?(?:default|home)\s+station",
    ):
        match = re.search(pattern, normalized)
        if match:
            return QueryIntent(
                action=ACTION_SET_DEFAULT,
                station_text=clean_station_phrase(match.group("station")),
                routes=routes,
                direction=direction,
            )

    # "change my default station" / "set my default" without a station name
    if re.search(r"(?:set|change|update)\s+(?:my\s+)?(?:default|home)\s+station", normalized):
        return QueryIntent(
            action=ACTION_SET_DEFAULT,
            station_text=None,
            routes=routes,
            direction=direction,
        )

    if any(
        phrase in normalized
        for phrase in (
            "what is my default station",
            "what s my default station",
            "what is the default station",
            "what s the default station",
            "what is my home station",
            "what s my home station",
            "what s my station",
            "which station am i using",
            "what station is saved",
        )
    ):
        return QueryIntent(action=ACTION_GET_DEFAULT, routes=routes, direction=direction)

    if any(
        phrase in normalized for phrase in (
            "help", "what can you do", "how does this work",
            "what can i say", "what are my options",
        )
    ):
        return QueryIntent(action=ACTION_HELP, routes=routes, direction=direction)

    return QueryIntent(
        action=ACTION_ARRIVALS,
        station_text=extract_station_phrase(normalized),
        routes=routes,
        direction=direction,
    )


def clean_station_phrase(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = normalize_text(text)
    cleaned = re.sub(r"\b(?:station|stop|train|subway)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def extract_station_phrase(normalized_text: str) -> Optional[str]:
    patterns = (
        r"\b(?:at|from|in|for)\b\s+(?P<station>[a-z0-9\s]+?)(?:\s+for\s+[a-z0-9]+\s+train|\s+for\s+[a-z0-9]+|\s+train|$)",
        r"\bnext\s+(?:train|subway)\s+(?:at|from|in)\b\s+(?P<station>[a-z0-9\s]+)$",
        r"\bwhen(?:'s|\s+is)?\s+the\s+next\s+(?:train|subway)\s+(?:at|from|in|per)\b\s+(?P<station>[a-z0-9\s]+)$",
        r"\b(?:check|get)\s+.*?(?:at|from|in|for|per)\b\s+(?P<station>[a-z0-9\s]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized_text)
        if match:
            return clean_station_phrase(match.group("station"))
    return None


def extract_routes(raw_text: str, normalized_text: str) -> List[str]:
    routes: List[str] = []

    # Spoken-out number routes are safe to match directly.
    spoken_number_aliases = {
        alias: route
        for alias, route in ROUTE_ALIASES.items()
        if len(alias) > 1 and alias not in {"shuttle"}
    }
    for alias, route in sorted(
        spoken_number_aliases.items(), key=lambda item: -len(item[0])
    ):
        if re.search(rf"\b{re.escape(alias)}\b", normalized_text):
            routes.append(route)

    route_context_patterns = (
        r"\b(?P<route>[1234567abcdefgjlmnqrswz])\s+(?:train|line)\b",
        r"\b(?:train|line)\s+(?P<route>[1234567abcdefgjlmnqrswz])\b",
        r"\bnext\s+(?P<route>[1234567abcdefgjlmnqrswz])\b",
        r"\b(?:uptown|downtown|northbound|southbound)\s+(?P<route>[1234567abcdefgjlmnqrswz])\b",
    )
    lowered_raw = (raw_text or "").lower()
    for pattern in route_context_patterns:
        for match in re.finditer(pattern, lowered_raw):
            routes.append(match.group("route").upper())

    if re.search(r"\bshuttle\b", normalized_text):
        routes.append("S")

    deduped: List[str] = []
    for route in routes:
        if route not in deduped:
            deduped.append(route)
    return deduped


def extract_direction(normalized_text: str) -> Optional[str]:
    for phrase in NORTHBOUND_WORDS:
        if phrase in normalized_text:
            return "N"
    for phrase in SOUTHBOUND_WORDS:
        if phrase in normalized_text:
            return "S"
    return None


def fetch_json(url: str, timeout: int = 12) -> object:
    response = requests.get(
        url,
        headers={
            "User-Agent": "OpenHome-MTA-Next-Train/1.0",
            "Accept": "application/json",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def urlencode(params: Dict[str, object]) -> str:
    parts = []
    for key, value in params.items():
        parts.append(f"{escape_query_value(str(key))}={escape_query_value(str(value))}")
    return "&".join(parts)


def escape_query_value(value: str) -> str:
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    out = []
    for ch in value:
        if ch in safe:
            out.append(ch)
        elif ch == " ":
            out.append("+")
        else:
            out.append(f"%{ord(ch):02X}")
    return "".join(out)


def search_stations(query: str, limit: int = 5) -> List[Station]:
    params = urlencode({"query": query, "limit": limit})
    payload = fetch_json(f"{API_BASE_URL}/stations?{params}")
    if not isinstance(payload, list):
        return []
    return [station_from_api_item(item) for item in payload if isinstance(item, dict)]


def fetch_arrivals(
    station_id: str, routes: Sequence[str], direction: Optional[str], limit: int = 8
) -> List[Arrival]:
    params = {"station_id": station_id, "limit": limit}
    if routes:
        params["line"] = routes[0]
    if direction:
        params["direction"] = direction
    payload = fetch_json(f"{API_BASE_URL}/arrivals?{urlencode(params)}")
    if not isinstance(payload, dict):
        return []
    raw_arrivals = payload.get("arrivals", [])
    if not isinstance(raw_arrivals, list):
        return []
    arrivals: List[Arrival] = []
    for item in raw_arrivals:
        if not isinstance(item, dict):
            continue
        route_id = str(item.get("line", "")).strip()
        item_direction = str(item.get("direction", "")).strip()
        if routes and route_id not in routes:
            continue
        if direction and item_direction != direction:
            continue
        arrivals.append(
            Arrival(
                route_id=route_id,
                direction=item_direction,
                direction_label=str(item.get("directionLabel", "")).strip(),
                minutes_away=int(item.get("minutesAway", 0)),
                headsign=str(item.get("headsign", "")).strip(),
            )
        )
    return arrivals


def format_arrivals_for_voice(
    station: Station,
    arrivals: Sequence[Arrival],
    routes: Sequence[str],
    direction: Optional[str],
) -> str:
    if not arrivals:
        return f"I'm not seeing any matching trains at {station.name} right now."

    grouped: Dict[tuple[str, str], List[Arrival]] = {}
    for arrival in arrivals:
        grouped.setdefault((arrival.route_id, arrival.direction), []).append(arrival)

    lead_bits: List[str] = []
    for (_, _), group in sorted(grouped.items(), key=lambda item: item[1][0].minutes_away):
        first = group[0]
        direction_label = "northbound" if first.direction == "N" else "southbound"
        bit = f"{direction_label} {first.route_id} in {render_minutes(first.minutes_away)}"
        if len(group) > 1:
            bit += f", then {render_minutes(group[1].minutes_away)}"
        lead_bits.append(bit)
        if len(lead_bits) == 3:
            break

    if len(lead_bits) == 1:
        return f"At {station.name}, the next train is {lead_bits[0]}."
    joined = ", ".join(lead_bits[:-1]) + f", and {lead_bits[-1]}"
    return f"At {station.name}, next trains: {joined}."


def render_minutes(minutes: int) -> str:
    if minutes <= 0:
        return "now"
    if minutes == 1:
        return "1 minute"
    return f"{minutes} minutes"


class MTANextTrainCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    prefs: Dict = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    def _get_trigger_text(self) -> str:
        history = self.capability_worker.get_full_message_history() or []
        for item in reversed(history):
            if item.get("role") == "user":
                content = (item.get("content") or "").strip()
                if content:
                    return content
        return ""

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("MTA Next Train triggered")
            self.prefs = self.load_prefs()
            trigger_text = self._get_trigger_text()

            # Parse trigger intent first — handle get_default/set_default/help
            # directly without prompting for a station
            if trigger_text:
                intent = parse_query_intent(trigger_text)
                if intent.action in (ACTION_GET_DEFAULT, ACTION_SET_DEFAULT, ACTION_HELP):
                    # Has a clear non-arrivals intent, use it directly
                    pass
                elif intent.action == ACTION_ARRIVALS and not intent.station_text and not self.prefs.get("default_station_id"):
                    # Arrivals but no station and no default — need to ask
                    trigger_text = await self.capability_worker.run_io_loop(
                        "What station or line do you want to check?"
                    )
                # else: arrivals with station or default — proceed
            else:
                trigger_text = await self.capability_worker.run_io_loop(
                    "What station or line do you want to check?"
                )
            if not trigger_text:
                return

            while True:
                if self._is_exit(trigger_text):
                    await self.capability_worker.speak("All good. See you next ride.")
                    return

                intent = parse_query_intent(trigger_text)
                if intent.action == ACTION_HELP:
                    await self.capability_worker.speak(
                        "You can ask for your next train at any station, "
                        "or a specific line like the Q at Union Square."
                    )
                    await self.capability_worker.speak(
                        "You can also set a default station so you "
                        "just have to say, when's my next train."
                    )
                elif intent.action == ACTION_GET_DEFAULT:
                    await self.handle_get_default()
                elif intent.action == ACTION_SET_DEFAULT:
                    await self.handle_set_default(intent)
                else:
                    await self.handle_arrivals(intent)

                trigger_text = await self.capability_worker.run_io_loop(
                    "Anything else?"
                )
                if not trigger_text:
                    return
        except Exception as exc:
            self.worker.editor_logging_handler.error(f"[MTANextTrain] {exc}")
            await self.capability_worker.speak(
                "Something went wrong checking live arrivals."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    def load_prefs(self) -> Dict:
        prefs = self.capability_worker.get_single_key(PREFS_KEY)
        if isinstance(prefs, dict):
            return prefs
        return {
            "default_station_id": "",
            "default_station_name": "",
            "default_station_borough": "",
            "default_station_lines": [],
        }

    def save_prefs(self):
        existing = self.capability_worker.get_single_key(PREFS_KEY)
        if existing:
            self.capability_worker.update_key(PREFS_KEY, self.prefs)
        else:
            self.capability_worker.create_key(PREFS_KEY, self.prefs)

    def _is_exit(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        for phrase in EXIT_WORDS:
            if lowered == phrase or lowered.startswith(phrase + " ") or lowered.endswith(" " + phrase):
                return True
        return False

    async def handle_set_default(self, intent: QueryIntent):
        station_text = intent.station_text
        if not station_text:
            station_text = await self.capability_worker.run_io_loop(
                "Which station should I save as your default?"
            )
            if not station_text:
                return
            follow_up_intent = parse_query_intent(station_text)
            if follow_up_intent.action == ACTION_SET_DEFAULT:
                station_text = follow_up_intent.station_text
            elif follow_up_intent.action == ACTION_GET_DEFAULT:
                await self.handle_get_default()
                return

        station = await self.resolve_station(station_text)
        if not station:
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Save {station.name} as your default station?"
        )
        if not confirmed:
            await self.capability_worker.speak("No problem.")
            return

        self.prefs["default_station_id"] = station.station_id
        self.prefs["default_station_name"] = station.name
        self.prefs["default_station_borough"] = station.borough
        self.prefs["default_station_lines"] = station.lines
        self.save_prefs()
        await self.capability_worker.speak(
            f"Done. {station.name} is your default now."
        )

    async def handle_get_default(self):
        if not self.prefs.get("default_station_id"):
            await self.capability_worker.speak(
                "You don't have a default station saved yet."
            )
            return
        await self.capability_worker.speak(
            f"Your default station is {self.prefs.get('default_station_name', 'unknown')}."
        )

    async def handle_arrivals(self, intent: QueryIntent):
        station = None
        if intent.station_text:
            station = await self.resolve_station(intent.station_text)
        elif self.prefs.get("default_station_id"):
            station = station_from_prefs(
                self.prefs["default_station_id"],
                self.prefs.get("default_station_name", ""),
                self.prefs.get("default_station_borough", ""),
                self.prefs.get("default_station_lines", []),
            )

        if not station:
            spoken_station = await self.capability_worker.run_io_loop(
                "Which station do you want to check?"
            )
            if not spoken_station:
                return
            if self._is_exit(spoken_station):
                await self.capability_worker.speak("All good. See you next ride.")
                return
            follow_up_intent = parse_query_intent(spoken_station)
            if follow_up_intent.action == ACTION_SET_DEFAULT:
                await self.handle_set_default(follow_up_intent)
                return
            if follow_up_intent.action == ACTION_GET_DEFAULT:
                await self.handle_get_default()
                return
            station = await self.resolve_station(spoken_station)
            if not station:
                return

        await self.capability_worker.speak(
            f"Checking {station.name}."
        )
        self.worker.editor_logging_handler.info(
            f"MTA arrivals request station_id={station.station_id} station={station.name} routes={intent.routes} direction={intent.direction}"
        )
        arrivals = await asyncio.to_thread(
            fetch_arrivals, station.station_id, intent.routes, intent.direction
        )
        self.worker.editor_logging_handler.info(
            f"MTA arrivals result count={len(arrivals)} station_id={station.station_id}"
        )
        summary = format_arrivals_for_voice(
            station,
            arrivals,
            intent.routes,
            intent.direction,
        )
        await self.capability_worker.speak(summary)

        # Offer to save as default if user doesn't have one yet
        if not self.prefs.get("default_station_id"):
            save = await self.capability_worker.run_confirmation_loop(
                f"Want me to save {station.name} as your default?"
            )
            if save:
                self.prefs["default_station_id"] = station.station_id
                self.prefs["default_station_name"] = station.name
                self.prefs["default_station_borough"] = station.borough
                self.prefs["default_station_lines"] = station.lines
                self.save_prefs()
                await self.capability_worker.speak("Saved.")

    async def resolve_station(self, station_text: str) -> Optional[Station]:
        await self.capability_worker.speak("One sec.")
        stations = await asyncio.to_thread(search_stations, station_text, 5)
        matches = find_station_matches(stations, station_text)
        if not matches:
            await self.capability_worker.speak(
                f"Couldn't find a station matching {station_text}."
            )
            return None

        top_match = matches[0]
        if len(matches) > 1 and (top_match.score - matches[1].score) < 0.08:
            # Deduplicate by name — if all close matches have the same name, just pick the first
            unique_names = list(dict.fromkeys(m.station.name for m in matches[:3]))
            if len(unique_names) == 1:
                return top_match.station

            options = ", ".join(unique_names)
            response = await self.capability_worker.run_io_loop(
                f"I found a few close matches: {options}. Which one?"
            )
            if not response:
                return None

            # Handle ordinal selection ("first one", "second one", "the first", etc.)
            lowered_resp = response.lower().strip()
            for word, idx in _ORDINAL_TO_IDX.items():
                if word in lowered_resp and idx < len(matches):
                    return matches[idx].station

            narrowed = find_station_matches(stations, response, limit=1)
            if not narrowed:
                await self.capability_worker.speak(
                    "Still couldn't pin down the station."
                )
                return None
            return narrowed[0].station

        return top_match.station
