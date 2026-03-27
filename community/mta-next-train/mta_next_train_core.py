from __future__ import annotations

import difflib
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


API_BASE_URL = "https://subwayinfo.nyc/api"
ACTION_SET_DEFAULT = "set_default"
ACTION_ARRIVALS = "arrivals"
ACTION_HELP = "help"
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
NORTHBOUND_WORDS = {"northbound", "uptown"}
SOUTHBOUND_WORDS = {"southbound", "downtown"}
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


def station_from_prefs(station_id: str, name: str, borough: str = "", lines: Optional[List[str]] = None) -> Station:
    return Station(
        station_id=station_id,
        name=name,
        normalized_name=normalize_text(name),
        borough=borough,
        lines=lines or [],
    )


def find_station_matches(stations: Sequence[Station], query: str, limit: int = 3) -> List[StationMatch]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        return []

    matches: List[StationMatch] = []
    query_tokens = set(normalized_query.split())
    for station in stations:
        ratio = difflib.SequenceMatcher(None, normalized_query, station.normalized_name).ratio()
        station_tokens = set(station.normalized_name.split())
        overlap = 0.0
        if station_tokens:
            overlap = len(query_tokens & station_tokens) / len(query_tokens | station_tokens)
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
    routes = extract_routes(normalized)
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

    if any(phrase in normalized for phrase in ("help", "what can you do", "how does this work")):
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
        r"(?:at|from)\s+(?P<station>[a-z0-9\s]+?)(?:\s+for\s+[a-z0-9]+\s+train|\s+for\s+[a-z0-9]+|\s+train|$)",
        r"next\s+(?:train|subway)\s+(?:at|from)\s+(?P<station>[a-z0-9\s]+)$",
        r"when(?:'s|\s+is)?\s+the\s+next\s+(?:train|subway)\s+(?:at|from)\s+(?P<station>[a-z0-9\s]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized_text)
        if match:
            return clean_station_phrase(match.group("station"))
    return None


def extract_routes(normalized_text: str) -> List[str]:
    routes: List[str] = []
    for alias, route in sorted(ROUTE_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(alias)}\b", normalized_text):
            routes.append(route)

    tokens = re.findall(r"\b[a-z0-9]{1,2}\b", normalized_text)
    for token in tokens:
        upper = token.upper()
        if upper in {"1", "2", "3", "4", "5", "6", "7", "A", "B", "C", "D", "E", "F", "G", "J", "L", "M", "N", "Q", "R", "S", "W", "Z"}:
            routes.append(upper)

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
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OpenHome-MTA-Next-Train/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def search_stations(query: str, limit: int = 5) -> List[Station]:
    params = urllib.parse.urlencode({"query": query, "limit": limit})
    payload = fetch_json(f"{API_BASE_URL}/stations?{params}")
    if not isinstance(payload, list):
        return []
    return [station_from_api_item(item) for item in payload if isinstance(item, dict)]


def fetch_arrivals(station_id: str, routes: Sequence[str], direction: Optional[str], limit: int = 8) -> List[Arrival]:
    params = {"station_id": station_id, "limit": limit}
    if routes:
        params["line"] = routes[0]
    if direction:
        params["direction"] = direction
    payload = fetch_json(f"{API_BASE_URL}/arrivals?{urllib.parse.urlencode(params)}")
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


def format_arrivals_for_voice(station: Station, arrivals: Sequence[Arrival], routes: Sequence[str], direction: Optional[str]) -> str:
    if not arrivals:
        return f"I am not seeing any matching trains for {station.name} right now."

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
    return f"At {station.name}, next trains: " + "; ".join(lead_bits) + "."


def render_minutes(minutes: int) -> str:
    if minutes <= 0:
        return "now"
    if minutes == 1:
        return "1 minute"
    return f"{minutes} minutes"
