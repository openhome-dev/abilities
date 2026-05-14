"""Local Event Explorer ability for OpenHome."""

import asyncio
import datetime
import difflib
import json
import random
import re
import zoneinfo
from typing import Optional

import httpx

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

_IDLE_THRESHOLD = 3
_WORD_LIMIT_SHORT = 5

IDLE_WARNING = "Still around if you want to keep looking."

PREFERENCE_PROMPT = (
    "What would you like to find? Tell me an event type, city, or date, like comedy, "
    "hackathons, workshops, or concerts in Dallas this weekend."
)


PREFS_FILE = "event_explorer_prefs.json"
DEFAULT_PREFS = {
    "home_city": None,
}

TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
SEATGEEK_URL = "https://api.seatgeek.com/2/events"
SERPER_URL = "https://google.serper.dev/search"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

# Common spoken city aliases → canonical names for API calls
_CITY_ALIASES = {
    "la": "Los Angeles",
    "nyc": "New York",
    "ny": "New York",
    "sf": "San Francisco",
    "dc": "Washington",
    "chi": "Chicago",
    "philly": "Philadelphia",
    "vegas": "Las Vegas",
    "nola": "New Orleans",
    "socal": "Los Angeles",
    "norcal": "San Francisco",
}

# Currency symbol map for spoken price hints
_CURRENCY_SYMBOLS = {
    "USD": "$", "GBP": "£", "EUR": "€", "AUD": "A$", "CAD": "C$",
}

SEARCH_FILLERS = [
    "Nice, let me see what's coming up.",
    "Give me a sec, I'll dig around for something good.",
    "On it — pulling up a few options now.",
    "Cool, let me check what's happening.",
]

MORE_FILLERS = [
    "Sure, let me keep looking.",
    "Got it, pulling up a few more.",
    "Alright, here's what else I've got.",
    "On it — more options coming up.",
]

DETAIL_FILLERS = [
    "Alright, let me tell you more about it.",
    "Sure, here's the rundown.",
    "Got it — let me share what I know about that one.",
    "Okay, here's what I've got on it.",
]

EXIT_MESSAGES = [
    "Alright, have a good one. Catch you later.",
    "Sure thing — hope you find something fun.",
    "Take care, talk soon.",
    "Cool, enjoy the rest of your day.",
]

ACTIVATION_ONLY = {
    "event", "events",
    "event finder", "events finder",
    "event explorer", "events explorer", "local event explorer",
    "find events", "find event",
    "find me events", "find me an event",
    "open events", "open event", "open event finder",
    "open events finder", "open event explorer",
    "start events", "start event", "start event finder",
    "hey events", "hey event", "hey event finder",
    "events please", "event please",
    "i want events", "i want an event",
    "show me events", "give me events",
    "looking for events", "look for events",
}

# Generic event-noun tokens that, on their own, are NOT a real search query.
# Used to exclude them from the "single keyword counts as actionable" check.
_GENERIC_ACTIVATION_TOKENS = {"event", "events", "find", "open", "start", "hey", "please", "show", "give"}

FOLLOWUPS = {
    "results": [
        "Want to hear more about any of these, or should I look for something else?",
        "Curious about one of these, or want to try a different search?",
    ],
    "details": [
        "Want me to add this to your calendar?",
        "Should I save this to your calendar?",
    ],
    "details_declined": [
        "Want to hear about another one, or change the search?",
        "Should I pull up something else?",
    ],
    "calendar": [
        "Want to find another event, or are you all set?",
        "Anything else I can look up?",
    ],
    "search": [
        "What are you in the mood for?",
        "Tell me a category, city, or date and I'll look.",
    ],
    "empty": [
        "Want to try a different city, date, or category?",
        "Should I try something else?",
    ],
}

# Generic words to strip from extracted category keyword before sending to APIs
_GENERIC_KEYWORD_TOKENS = {
    "concerts", "concert", "events", "event", "shows", "show",
    "tickets", "ticket", "live", "local", "nearby",
}

# SDK key names — stored in OpenHome Settings → API Keys
TM_KEY_NAME = "ticketmaster_api_key"
SEATGEEK_KEY_NAME = "seatgeek_api_key"
SERPER_KEY_NAME = "serper_api_key"

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

PIVOT_MARKERS = {
    "i want",
    "i need",
    "find",
    "search",
    "look for",
    "show me",
    "give me",
    "actually",
    "instead",
    "events",
    "event",
    "concert",
    "comedy",
    "sports",
    "festival",
    "hackathon",
    "tech",
    "startup",
    "business",
    "career",
    "networking",
    "workshop",
    "art",
    "food",
    "wellness",
    "nightlife",
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

    # Tech, startup, business, and career events.
    "hackathon", "hackathons", "startup", "startups", "tech", "technology",
    "networking", "workshop", "workshops", "seminar", "seminars", "coding",
    "developer", "developers", "programming", "ai", "artificial", "intelligence",
    "machine", "learning", "web3", "blockchain", "crypto", "demo", "pitch",
    "founder", "founders", "entrepreneur", "entrepreneurs", "entrepreneurship",
    "business", "career", "careers", "job", "jobs", "hiring", "recruiting",
    "jobfair", "job-fair", "training", "bootcamp", "bootcamps",

    # Community, culture, food, wellness, and family-friendly events.
    "art", "arts", "gallery", "museum", "film", "screening", "poetry",
    "literary", "book", "books", "author", "lecture", "talk", "talks",
    "food", "drink", "wine", "beer", "tasting", "market", "farmers",
    "yoga", "fitness", "wellness", "health", "meditation", "run", "running",
    "marathon", "kids", "family", "children", "community", "charity",
    "fundraiser", "volunteer", "nightlife", "party", "club", "dj",
    "event", "events", "tonight", "weekend", "tomorrow",
}

TECH_EVENT_TERMS = {
    "hackathon", "hackathons", "hack", "coding", "developer", "developers",
    "programming", "tech", "technology", "startup", "startups", "founder",
    "founders", "pitch", "demo", "ai", "artificial", "intelligence",
    "machine", "learning", "web3", "blockchain", "crypto", "workshop",
    "networking", "meetup", "conference", "bootcamp", "career", "hiring",
}

ORGANIC_EVENT_DOMAINS = {
    "devpost.com", "eventbrite.com", "meetup.com", "lu.ma", "luma.com",
    "mlh.io", "hackerearth.com", "devfolio.co", "unstop.com",
    "startupgrind.com", "techstars.com", "producthunt.com",
}

ORGANIC_LISTING_HINTS = {
    "events in", "things to do", "event calendar", "events calendar",
    "all events", "upcoming events", "search results", "browse events",
    "event listings", "tickets for", "near me", "discover ",
    "events activities", "events and activities", "top events",
    "best events", "find events", "what s on", "whats on",
    "events near", "hackathons in", "hackathon events",
}

# Title patterns that ALWAYS mean a category/landing page, never a real event.
# These bypass the date-hint exception because landing pages frequently
# include dates in their snippets ("Browse hackathons from May 30...") without
# being concrete events themselves.
DEFINITE_LISTING_PATTERNS = (
    re.compile(r"^discover\s+", re.I),
    re.compile(r"^find\s+(the\s+)?(best|top|upcoming)\s+", re.I),
    re.compile(r"^top\s+\d*\s*(events?|hackathons?|meetups?)", re.I),
    re.compile(r"^all\s+\w+\s+events?", re.I),
    re.compile(r"^upcoming\s+(events?|hackathons?|meetups?)", re.I),
    re.compile(r"^events?\s+(in|near)\s+", re.I),
    re.compile(r"^hackathons?\s+(in|near)\s+", re.I),
    re.compile(r"^things?\s+to\s+do\b", re.I),
    re.compile(r"\bevents?\s+calendar\b", re.I),
    re.compile(r"\bevent\s+listings?\b", re.I),
)

MONTH_RE = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)"
)

INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for a voice-activated local event explorer.
The user wants to find local events: concerts, sports, comedy, festivals, hackathons, workshops, networking events, and more.

Given the user's input, classify their intent into exactly ONE mode.
Return ONLY valid JSON on one line, with no code blocks or markdown fences.

Modes:
- "search": Look up events. Default to this mode whenever the user mentions ANY event type, category, or genre (e.g. "jazz", "comedy", "concert", "festival", "sports", "music", "hackathon", "tech", "networking", "workshop", "startup", "business", "career", "art", "food", "wellness", "family", "nightlife"). Also use for phrases like "I'm looking for X", "find X", "any X events", "X event". Even a single word like "Jazz", "Comedy", "Hackathon", or "Networking" is a search request.
- "expand": Get details about a SPECIFIC event from a list already shown to the user. Only use if the user says "the first one", "second one", "tell me more about [specific event name already listed]". Do NOT use for general discovery.
- "calendar": Add an event to calendar. Phrases like "add that", "save it", "put it in my calendar". Also use when the assistant just asked about adding to calendar and the user gives a clean affirmative ("yes", "sure", "ok", "please", "yeah"). NEVER classify as calendar when the user's reply starts with "no", "nope", "nah", or otherwise declines — even if "ok" or "sure" appears later in the sentence (e.g. "No, I'm ok" is a refusal, not consent).
- "city": Set default home city. Phrases like "I live in X", "my city is X", "change city to X".
- "clarify": ONLY use this if the input is truly gibberish, completely off-topic (not about events), or has zero useful content. Do NOT use clarify if any event type or location is mentioned.
- "exit": User wants to END the event explorer session. Recognize BROADLY.
  Examples that ARE exit: "goodbye", "bye", "alright bye", "ok I'm done",
  "yeah I'm good thanks", "that's all thanks", "that's enough", "nevermind",
  "thanks bye", "shut it down", "close it", "I am finished", "we're done",
  "stop", "stop now", "stop please", "okay stop", "alright stop", "just stop",
  "I don't want any events", "no more events", "I'm not interested",
  "forget it", "no thanks I'm good".
  Do NOT classify as exit:
    - "stop, find me X" — that is search with category X.
    - "no thanks, find something else" — that is search/clarify, not exit.

RULE: When in doubt between "search" and "clarify", always choose "search".
RULE: If the assistant's last question was about adding to calendar and the user says "yes"/"sure"/"ok"/"please"/"yeah", classify as "calendar".
RULE: If the assistant's last question was about searching again and the user says "yes"/"sure"/"ok", classify as "search".
RULE: Use conversation history to resolve references like "same city", "the second one", "no, next week instead".
RULE: If the user's reply starts with "no", "nope", "nah", or "never", they are refusing whatever was asked. Never classify as "calendar" in that case — choose "clarify" if they don't say anything else useful, or "search"/"city" if they pivot to a new request.
RULE: STT often mishears "may" as "day". If the user says "day 14", "day 20" etc. and the current or implied month is May, interpret it as that day in May.

Conversation history (most recent last):
{history}

User Input: "{user_input}"
Has events been shown to user already: {has_events}
Assistant's last question to the user: "{last_prompt}"

Format expected:
{{"mode": "search|expand|calendar|city|clarify|exit", "location": "city name or null", "category": "event type keyword or null", "time": "raw time phrase or null", "event_reference": "first|second|keyword or null"}}
"""

EVENT_RESPONSE_PROMPT = """Write a voice-friendly event finder response.
Use the user's request and the event data to sound natural, but do not invent anything.
Return plain text only. No markdown, bullets, URLs, IDs, raw JSON, or stage directions.

User request: "{user_request}"
Response type: {response_type}
Search context: {context}
Events:
{events}

Rules:
- Use event names exactly as provided.
- Do not mention events, venues, dates, times, prices, or performers that are not in the Events list.
- For search results, every event MUST be announced with at minimum its name AND date AND venue when any of those are provided. If time is provided, include it after the date. Do not drop any of these to make the response shorter — the user uses the spoken date+venue to decide whether to add the event to their calendar.
- For details, mention name, venue, date/time, genre or performers, and price only if provided.
- Speak each event as a short complete sentence: "<name> is at <venue> on <date> at <time>." Skip any field that's missing rather than guessing.
- Keep it suitable for speech, with enough detail to be useful.
- End with no follow-up question; the app asks follow-ups separately.
"""

EVENT_SELECTION_PROMPT = """You are helping a voice assistant user choose from event options.
Input is speech-to-text and may be imprecise. Match by meaning, not exact words.
Return ONLY valid JSON on one line. No markdown.

Options:
{options}

User said: "{user_input}"

Actions:
- details: user chose one option or asks for more detail.
- more: user wants to hear more results from the same search.
- calendar: user wants to save/add an event to calendar.
- new_search: user wants something else, a different city, date, or event type.
- exit: user is done.
- unclear: user did not give enough information.

Schema:
{{"action":"details|more|calendar|new_search|exit|unclear","index":1}}

Rules:
- index is 1-based. Use null if action is not details or calendar.
- "the second one" means index 2.
- "the jazz one", "the cheaper one", "the Saturday one", or "the arena one" should choose the closest option.
- If the user asks to save "it" or "that", choose calendar for the best current option.
- If unsure between an event and unclear, choose the closest event.
"""

DATE_PARSER_PROMPT = """Convert the following time phrase into a LOCAL date range. Do not do any timezone conversion — just return local calendar dates and clock times.
Today's local date is: {today}

Time phrase: "{phrase}"

Rules:
- "tonight" → start: today, start_time: 17:00, end: today, end_time: 23:59
- "tomorrow" → start: tomorrow, start_time: 00:00, end: tomorrow, end_time: 23:59
- "this weekend" or "weekend" → start: nearest Saturday, end: nearest Sunday, times 00:00–23:59
- "this week" → start: today, end: this coming Sunday, times 00:00–23:59
- "next week" → start: next Monday, end: next Sunday, times 00:00–23:59
- "this month" or month name (e.g. "May") → start: first day of that month, end: last day of that month, times 00:00–23:59
- Named day (e.g. "Saturday") → nearest upcoming that day, 00:00 to 23:59
- Specific date (e.g. "May 13", "May 13th") → start: that date, end: that date, times 00:00–23:59
- Bare day number ("14", "day 14", "the 14th", "on the 14") → that day in the CURRENT month if it has not passed yet, otherwise that day in the NEXT month. Start and end on that single day, times 00:00–23:59.
- STT confusion: "day N" often actually means "may N" (the word "may" is mis-heard as "day"). If the user says "day 14" / "day 20" / "day 31" etc., treat it the same as a bare day number per the rule above — the result is the same day in the current/next month.
- If you cannot parse it, return null for all fields.

Return ONLY valid JSON on one line (YYYY-MM-DD for dates, HH:MM for times):
{{"start_date": "YYYY-MM-DD or null", "end_date": "YYYY-MM-DD or null", "start_time": "HH:MM", "end_time": "HH:MM"}}
"""


def _strip_llm_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _normalize_city(city: str) -> str:
    """Expand common spoken city aliases to their full canonical name."""
    return _CITY_ALIASES.get(city.lower().strip(), city)


def _clean_keyword(keyword: str) -> str:
    """Strip generic words like 'concerts', 'events' from a category keyword.

    Keeps the specific genre so APIs get e.g. 'music' not 'music concerts'.
    """
    if not keyword:
        return keyword
    tokens = keyword.lower().split()
    kept = [t for t in tokens if t not in _GENERIC_KEYWORD_TOKENS]
    return " ".join(kept) if kept else keyword


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _domain_from_url(url: str) -> str:
    match = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    return match.group(1).lower() if match else ""


def _is_known_event_domain(url: str) -> bool:
    domain = _domain_from_url(url)
    return any(domain == d or domain.endswith(f".{d}") for d in ORGANIC_EVENT_DOMAINS)


def _looks_like_tech_event_query(keyword: str, time_context: str = "") -> bool:
    words = set(_normalize_text(f"{keyword} {time_context}").split())
    return bool(words & TECH_EVENT_TERMS)


def _looks_like_listing_page(title: str) -> bool:
    normalized = _normalize_text(title)
    return any(hint in normalized for hint in ORGANIC_LISTING_HINTS)


def _is_definite_listing_page(title: str) -> bool:
    """Title patterns that are always category/landing pages, regardless of
    whether the snippet happens to contain a date hint."""
    text = (title or "").strip()
    if not text:
        return False
    return any(p.search(text) for p in DEFINITE_LISTING_PATTERNS)


def _clean_organic_event_title(title: str) -> str:
    title = re.sub(
        r"\s*(?:[-|:]\s*)?(?:Eventbrite|Devpost|Meetup|Luma|MLH|"
        r"HackerEarth|Devfolio|Unstop)\s*$",
        "",
        title or "",
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", title).strip(" -|:")


def _extract_date_hint(text: str) -> str:
    match = re.search(
        rf"\b{MONTH_RE}\s+\d{{1,2}}(?:\s*[-–]\s*\d{{1,2}})?(?:,\s*\d{{4}})?\b",
        text or "",
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(0)
    match = re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", text or "")
    return match.group(0) if match else ""


def _parse_freeform_date(text: str) -> str:
    """Best-effort parse of a freeform date string into YYYY-MM-DD.

    Handles patterns like 'May 13', 'May 13th', 'Wednesday, May 13',
    'May 13, 2026', '2026-05-13', '5/13/2026'. Year is assumed current if
    not present. Returns empty string if the input can't be parsed.
    """
    if not text:
        return ""
    raw = text.strip()
    # Already ISO?
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        return raw[:10]
    today = datetime.date.today()
    # Strip ordinal suffix and any leading day-name prefix.
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", raw, flags=re.I)
    cleaned = re.sub(
        r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\.?,?\s*",
        "",
        cleaned,
        flags=re.I,
    ).strip()
    # Try formats that include a year first.
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Then year-less formats — assume current year.
    for fmt in ("%B %d", "%b %d", "%m/%d"):
        try:
            dt = datetime.datetime.strptime(cleaned, fmt).replace(year=today.year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _organic_result_to_event(result: dict, city: str, keyword: str) -> Optional[dict]:
    title = result.get("title", "")
    link = result.get("link", "")
    snippet = result.get("snippet", "")
    if not title or not link or not _is_known_event_domain(link):
        return None

    haystack = _normalize_text(f"{title} {snippet} {link}")
    keyword_words = {w for w in _normalize_text(keyword).split() if len(w) > 2}
    is_relevant = bool((keyword_words and keyword_words & set(haystack.split())) or (set(haystack.split()) & TECH_EVENT_TERMS))
    if not is_relevant:
        return None

    name = _clean_organic_event_title(title)
    if not name:
        return None

    # Drop category/landing pages even if the snippet happens to contain a
    # date — the title itself is the giveaway.
    if _is_definite_listing_page(name):
        return None

    has_date_hint = bool(_extract_date_hint(f"{title} {snippet}"))
    # Ambiguous listing-like titles: only reject if there's no date at all.
    if _looks_like_listing_page(name) and not has_date_hint:
        return None

    return {
        "name": name,
        "venue": "",
        "venue_city": city,
        "venue_address": "",
        "date": _parse_freeform_date(_extract_date_hint(f"{title} {snippet}")),
        "time": "",
        "url": link,
        "source": "Google Search",
        "genre": keyword or "Tech",
        "performers": [],
        "price_min": None,
        "price_max": None,
        "currency": "USD",
    }


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
    try:
        t = datetime.datetime.strptime(time_str[:5], "%H:%M")
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return time_str


def _format_spoken_date(date_str: str) -> str:
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        day = dt.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        today = datetime.date.today()
        delta = (dt.date() - today).days
        day_name = dt.strftime("%A")
        if delta == 0:
            return "today"
        elif delta == 1:
            return f"tomorrow the {day}{suffix}"
        elif 2 <= delta <= 6:
            return f"this {day_name} the {day}{suffix}"
        else:
            return f"{day_name}, {dt.strftime('%B')} {day}{suffix}"
    except Exception:
        return date_str


def _format_history(history: list[dict], max_turns: int = 6) -> str:
    if not history:
        return "(no prior conversation)"
    recent = history[-max_turns:]
    lines = []
    for entry in recent:
        role = "User" if entry["role"] == "user" else "Assistant"
        lines.append(f"{role}: {entry['content']}")
    return "\n".join(lines)


def _sanitize_voice(text: str) -> str:
    cleaned = re.sub(r"(?:https?://|www\.)\S+", "", text or "")
    cleaned = re.sub(r"`{1,3}|\*{1,2}|#{1,6}", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _pick_diverse_dates(events: list[dict], count: int) -> tuple[list[dict], list[dict]]:
    """Pick up to `count` events spanning distinct dates, plus the leftovers.

    When the search window is broad (e.g. "this week"), a date-ascending API
    response can dump several events on today's date and starve later days.
    This walks the list once, preferring events on dates we haven't picked
    yet, then falls back to same-date leftovers if it can't fill the quota
    with unique dates.

    Returns (picked, remaining) so the caller can stash remaining for "more".
    """
    picked: list[dict] = []
    seen_dates: set[str] = set()
    leftovers: list[dict] = []
    for ev in events:
        d = (ev.get("date") or "")[:10]
        if d and d not in seen_dates and len(picked) < count:
            picked.append(ev)
            seen_dates.add(d)
        else:
            leftovers.append(ev)
    # Fill remaining slots from leftovers if we couldn't find enough unique dates.
    while len(picked) < count and leftovers:
        picked.append(leftovers.pop(0))
    return picked, leftovers


class EventsFinderCapability(MatchingCapability):
    """Voice-activated local event explorer."""

    # {{register capability}}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    current_events: list = None
    remaining_events: list = None
    last_spoken_events: list = None
    conversation_history: list = None
    last_expanded_event: Optional[dict] = None
    last_searched_city: Optional[str] = None
    last_prompt: str = ""
    last_action: str = ""

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.current_events = []
        self.remaining_events = []
        self.last_spoken_events = []
        self.conversation_history = []
        self.last_expanded_event = None
        self.last_searched_city = None
        self.last_prompt = ""
        self.last_action = ""
        self.worker.session_tasks.create(self.run())

    def _get_api_key(self, key_name: str) -> str:
        try:
            value = self.capability_worker.get_api_keys(key_name)
            if isinstance(value, str):
                return value.strip()
        except Exception as exc:
            self._err(f"API key lookup failed for {key_name}: {exc}")
        return ""

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

    def _latest_user_request(self) -> str:
        for row in reversed(self.conversation_history):
            if row.get("role") == "user":
                return row.get("content", "")
        return ""

    def _event_option_lines(self, events: list[dict]) -> str:
        lines = []
        for idx, ev in enumerate(events, start=1):
            date_str = _format_spoken_date(ev.get("date", "")) if ev.get("date") else ""
            time_str = _format_time(ev.get("time", "")) if ev.get("time") else ""
            price = ""
            if ev.get("price_min"):
                symbol = _CURRENCY_SYMBOLS.get(ev.get("currency", "USD"), "")
                price = f"from {symbol}{ev['price_min']:.0f}"
            lines.append(
                "; ".join(
                    p for p in (
                        f"{idx}. name={ev.get('name', 'Unknown Event')}",
                        f"venue={ev.get('venue', '')}",
                        f"city={ev.get('venue_city', '')}",
                        f"date={date_str}",
                        f"time={time_str}",
                        f"genre={ev.get('genre', '')}",
                        f"price={price}",
                    )
                    if p and not p.endswith("=")
                )
            )
        return "\n".join(lines) or "(none)"

    async def _generate_event_response(
        self,
        events: list[dict],
        response_type: str,
        context: str,
        fallback: str,
    ) -> str:
        if not events:
            return fallback
        try:
            raw = await asyncio.to_thread(
                self.capability_worker.text_to_text_response,
                EVENT_RESPONSE_PROMPT.format(
                    user_request=self._latest_user_request(),
                    response_type=response_type,
                    context=context,
                    events=self._event_option_lines(events),
                ),
            )
            cleaned = _sanitize_voice(raw)
            return cleaned or fallback
        except Exception as exc:
            self._err(f"Event response generation failed: {exc}")
            return fallback

    def _split_spoken_chunks(self, text: str, max_chars: int = 220) -> list[str]:
        """Split generated speech into short chunks for voice playback."""
        cleaned = _sanitize_voice(text)
        if not cleaned:
            return []
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        chunks = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if current and len(current) + len(sentence) + 1 > max_chars:
                chunks.append(current)
                current = sentence
            elif current:
                current = f"{current} {sentence}"
            else:
                current = sentence
        if current:
            chunks.append(current)
        return chunks or [cleaned]

    async def _speak_chunks(self, text: str):
        for chunk in self._split_spoken_chunks(text):
            await self.capability_worker.speak(chunk)
            await self.worker.session_tasks.sleep(0.05)

    async def _ask(self, prompt: str) -> str:
        prompt = _sanitize_voice(prompt)
        self.last_prompt = prompt
        if prompt:
            self.conversation_history.append({"role": "assistant", "content": prompt})
        return await self.capability_worker.run_io_loop(prompt)

    def _followup_prompt(self, kind: str) -> str:
        prompts = FOLLOWUPS.get(kind) or FOLLOWUPS["search"]
        if kind == "details" and self.last_expanded_event:
            name = self.last_expanded_event.get("name", "that event")
            return f"Want me to add {name} to your calendar?"
        options = [p for p in prompts if p != self.last_prompt]
        return options[0] if options else prompts[0]

    def _is_prompt_echo(self, text: str) -> bool:
        cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        prompt = re.sub(r"[^a-z0-9\s]", " ", (self.last_prompt or "").lower())
        prompt = re.sub(r"\s+", " ", prompt).strip()
        if not cleaned or not prompt:
            return False
        return cleaned == prompt or (len(cleaned) > 40 and prompt in cleaned)

    def _is_exit_request(self, text: str) -> bool:
        cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return False
        words = set(cleaned.split())
        if len(words) > _WORD_LIMIT_SHORT and any(marker in cleaned for marker in PIVOT_MARKERS):
            return False
        if words & EVENT_KEYWORDS and any(marker in cleaned for marker in PIVOT_MARKERS):
            return False
        if cleaned in EXIT_WORDS or cleaned in EXIT_PHRASES:
            return True
        return len(cleaned.split()) <= _WORD_LIMIT_SHORT and any(
            phrase in cleaned for phrase in EXIT_PHRASES
        )

    def _has_search_pivot(self, text: str) -> bool:
        cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return False
        return bool(set(cleaned.split()) & EVENT_KEYWORDS) or any(
            marker in cleaned for marker in PIVOT_MARKERS
        )

    async def _speak_generated_event_response(
        self,
        events: list[dict],
        response_type: str,
        context: str,
        fallback: str,
    ):
        response = await self._generate_event_response(
            events,
            response_type,
            context,
            fallback,
        )
        await self._speak_chunks(response)

    async def _select_from_current_events(self, user_input: str) -> dict:
        options = self.last_spoken_events or self.current_events[:5]
        if not options:
            return {"action": "unclear", "index": None}
        try:
            raw = await asyncio.to_thread(
                self.capability_worker.text_to_text_response,
                EVENT_SELECTION_PROMPT.format(
                    options=self._event_option_lines(options),
                    user_input=user_input,
                ),
            )
            data = json.loads(_strip_llm_fences(raw))
            action = str(data.get("action") or "unclear").strip().lower()
            if action not in {"details", "more", "calendar", "new_search", "exit", "unclear"}:
                action = "unclear"
            index = data.get("index")
            if isinstance(index, int):
                index -= 1
            else:
                index = None
            return {"action": action, "index": index}
        except Exception as exc:
            self._err(f"Event selection failed: {exc}")
            return {"action": "unclear", "index": None}

    def _event_from_selection_index(self, index: Optional[int]) -> Optional[dict]:
        options = self.last_spoken_events or self.current_events[:5]
        if isinstance(index, int) and 0 <= index < len(options):
            return options[index]
        return None

    async def run(self):
        try:
            self._log("Ability started")
            prefs = await self._load_prefs()

            # Capture trigger transcription via SDK before speaking
            trigger_text = (
                await self.capability_worker.wait_for_complete_transcription() or ""
            ).strip()
            self._log(f"Trigger: {trigger_text!r}")

            current_prompt = PREFERENCE_PROMPT
            idle_count = 0
            idle_warned = False
            pending_input: Optional[str] = None

            _trigger_normalized = re.sub(r"[^a-z0-9\s]", " ", trigger_text.lower())
            _trigger_normalized = re.sub(r"\s+", " ", _trigger_normalized).strip()
            # Actionable only if (a) the phrase isn't a bare activation, AND
            # (b) it contains a SPECIFIC event keyword (genre, category, time)
            # — generic words like "event"/"events"/"find" don't count.
            _specific_keywords = (
                set(_trigger_normalized.split())
                & EVENT_KEYWORDS
            ) - _GENERIC_ACTIVATION_TOKENS
            _trigger_actionable = bool(
                trigger_text
                and _trigger_normalized not in ACTIVATION_ONLY
                and (
                    len(trigger_text.split()) > 3
                    or bool(_specific_keywords)
                )
            )
            if _trigger_actionable:
                # User already gave a search command — skip city confirmation, go straight to it
                ip_city = await asyncio.to_thread(self._fetch_ip_city)
                if ip_city and not prefs.get("home_city"):
                    prefs["home_city"] = ip_city
                pending_input = trigger_text
            else:
                current_prompt = PREFERENCE_PROMPT

            for _ in range(20):
                if pending_input is not None:
                    user_input = pending_input
                    pending_input = None
                    spoken_prompt = ""
                else:
                    spoken_prompt = current_prompt
                    user_input = await self._ask(current_prompt)

                if not user_input or not user_input.strip():
                    idle_count += 1
                    # After three silent turns, give one warning. If the next
                    # turn is also silent, exit quietly — no farewell speech.
                    if idle_warned:
                        self._log("Idle after warning — exiting silently")
                        break
                    if idle_count >= _IDLE_THRESHOLD:
                        idle_warned = True
                        idle_count = 0
                        current_prompt = IDLE_WARNING
                    else:
                        current_prompt = PREFERENCE_PROMPT
                    continue

                idle_count = 0
                idle_warned = False

                if self._is_prompt_echo(user_input):
                    current_prompt = PREFERENCE_PROMPT
                    continue

                self.conversation_history.append({"role": "user", "content": user_input})

                _lower = user_input.lower()
                _clean_words = {w.strip(".,!?;:'\"") for w in _lower.split()}
                if self._is_exit_request(user_input):
                    await self.capability_worker.speak(random.choice(EXIT_MESSAGES))
                    break

                # Pre-LLM denial guard: when the last spoken prompt was a yes/no
                # question (calendar, "search there?", "search again?"), a reply
                # that starts with no/nope/nah must NEVER be classified as
                # calendar — even if the user says "no, I'm ok".
                _denial_words = {"no", "nope", "nah", "never"}
                _first_word = next(iter(_lower.split()), "").strip(".,!?;:'\"")
                _is_denial = _first_word in _denial_words
                _last_prompt_lower = (spoken_prompt or "").lower()
                _last_was_yesno = any(
                    p in _last_prompt_lower
                    for p in (
                        "calendar", "save", "add it", "add that",
                        "search there", "search again", "want me to",
                        "sound good", "any of these",
                    )
                )
                if _is_denial and _last_was_yesno and not self._has_search_pivot(user_input):
                    self._log(f"Denial guard fired: {user_input!r} after prompt {_last_prompt_lower!r}")
                    await self.capability_worker.speak("No problem.")
                    # If events are still loaded (e.g. user declined calendar
                    # save after details), offer more-of-the-same options
                    # instead of starting from scratch.
                    if self.last_action == "expand" and self.current_events:
                        current_prompt = self._followup_prompt("details_declined")
                    elif self.current_events:
                        current_prompt = self._followup_prompt("results")
                    else:
                        current_prompt = self._followup_prompt("search")
                    continue

                # Fast "more" pre-check — route to pagination without LLM when results remain
                _more_phrases = ("what else", "read more", "hear more", "keep going", "show more")
                _more_triggered = (
                    bool(_clean_words & {"more", "others", "rest", "next", "another"})
                    or any(p in _lower for p in _more_phrases)
                )
                _detail_requested = any(
                    p in _lower
                    for p in ("tell me more about", "tell me about", "details", "detail", "open")
                )
                if _more_triggered and self.remaining_events and not _detail_requested:
                    found = await self._handle_more()
                    if found and self.remaining_events:
                        current_prompt = self._followup_prompt("results")
                    elif found:
                        current_prompt = self._followup_prompt("results")
                    else:
                        current_prompt = self._followup_prompt("empty")
                    self.last_action = "more"
                    continue

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
                    await self.capability_worker.speak(random.choice(EXIT_MESSAGES))
                    break

                elif mode == "search":
                    found = await self._handle_search(intent, prefs)
                    if found:
                        current_prompt = self._followup_prompt("results")
                    else:
                        current_prompt = self._followup_prompt("empty")
                    self.last_action = "search"

                elif mode == "expand":
                    expanded = await self._handle_expand(intent, prefs)
                    if expanded:
                        current_prompt = self._followup_prompt("details")
                    else:
                        current_prompt = "Which one would you like to hear about? You can say first, second, or the name."
                    self.last_action = "expand"

                elif mode == "calendar":
                    added = await self._handle_calendar(intent)
                    if added:
                        current_prompt = self._followup_prompt("calendar")
                    else:
                        current_prompt = "Which one should I save? You can say first, second, or the name."
                    self.last_action = "calendar"

                elif mode == "city":
                    city = intent.get("location")
                    if city and not _is_invalid_city(city):
                        prefs["home_city"] = city
                        await self.capability_worker.speak(f"Got it! Searching in {city} from now on.")
                    else:
                        await self.capability_worker.speak("Which city should I search in?")
                    current_prompt = self._followup_prompt("search")
                    self.last_action = "city"

                elif mode == "clarify":
                    current_prompt = "Sorry, I missed that. What would you like to find?"
                    self.last_action = "clarify"

        except Exception as e:
            self._err(f"Fatal error in run loop: {e}")
            if self.capability_worker:
                await self.capability_worker.speak("Something went wrong. Please try again.")
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

    async def _classify_intent(self, user_input: str, last_prompt: str = "") -> dict:
        has_events = "yes" if self.current_events else "no"
        history_block = _format_history(self.conversation_history)
        prompt = INTENT_CLASSIFIER_PROMPT.format(
            user_input=user_input,
            has_events=has_events,
            last_prompt=last_prompt,
            history=history_block,
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
        if self._is_exit_request(user_input):
            return {"mode": "exit"}
        if any(w in lower for w in ("add", "calendar", "save")):
            return {"mode": "calendar", "event_reference": None}
        if any(w in lower for w in ("detail", "more", "tell me", "expand")):
            return {"mode": "expand", "event_reference": None}
        return {"mode": "clarify", "location": None, "category": None, "time": None, "event_reference": None}

    async def _parse_time_context(self, time_string: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """Convert a natural language time phrase to UTC ISO-8601 start/end datetimes."""
        if not time_string:
            return None, None

        today_str = datetime.date.today().strftime("%Y-%m-%d")
        prompt = DATE_PARSER_PROMPT.format(today=today_str, phrase=time_string)

        try:
            raw = await asyncio.to_thread(
                self.capability_worker.text_to_text_response, prompt
            )
            data = json.loads(_strip_llm_fences(raw))
            start_date = data.get("start_date")
            end_date = data.get("end_date") or start_date
            if not start_date:
                return None, None

            start_time_str = data.get("start_time") or "00:00"
            end_time_str = data.get("end_time") or "23:59"

            # Convert local date+time to UTC using the user's timezone
            tz_name = self.capability_worker.get_timezone() or "UTC"
            try:
                tz_obj = zoneinfo.ZoneInfo(tz_name)
            except Exception:
                tz_obj = datetime.timezone.utc

            def _to_utc(date_str: str, time_str: str) -> str:
                d = datetime.date.fromisoformat(date_str)
                h, m = map(int, time_str.split(":"))
                local_dt = datetime.datetime(d.year, d.month, d.day, h, m, 0, tzinfo=tz_obj)
                return local_dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            start_dt = _to_utc(start_date, start_time_str)
            end_dt = _to_utc(end_date, end_time_str)
            self._log(f"Date parse '{time_string}' → local {start_date} {start_time_str} – {end_date} {end_time_str} ({tz_name}) → UTC {start_dt} – {end_dt}")
            return start_dt, end_dt
        except Exception as e:
            self._err(f"Date parsing failed for '{time_string}': {e}")
            return None, None

    def _resolve_event_ref(self, ref: str) -> Optional[dict]:
        """Resolve a spoken ordinal, digit, or keyword to an event in current_events."""
        if not self.current_events:
            return None

        ref = ref.lower().strip()
        options = self.last_spoken_events or self.current_events

        # Ordinal words and numeric equivalents
        word_to_idx = {
            "first": 0, "one": 0, "1": 0,
            "second": 1, "two": 1, "2": 1,
            "third": 2, "three": 2, "3": 2,
            "fourth": 3, "four": 3, "4": 3,
            "fifth": 4, "five": 4, "5": 4,
        }
        for word, idx in word_to_idx.items():
            if word in ref.split() or ref == word:
                if idx < len(options):
                    return options[idx]
                return None

        # Keyword match against event name
        for ev in options:
            if ref and ref in ev["name"].lower():
                return ev

        # Fuzzy match speech-to-text slips against the latest spoken options first.
        best_event = None
        best_score = 0.0
        for ev in options:
            name = ev.get("name", "").lower()
            if not ref or not name:
                continue
            score = difflib.SequenceMatcher(None, ref, name).ratio()
            for token in ref.split():
                if len(token) >= 4:
                    score = max(
                        score,
                        max(
                            (
                                difflib.SequenceMatcher(None, token, name_token).ratio()
                                for name_token in name.split()
                                if len(name_token) >= 4
                            ),
                            default=0.0,
                        ),
                    )
            if score > best_score:
                best_score = score
                best_event = ev
        if best_score >= 0.72:
            return best_event

        return None

    async def _fetch_ticketmaster(
        self,
        city: str,
        keyword: str,
        start_dt: Optional[str],
        end_dt: Optional[str],
    ) -> list[dict]:
        key = self._get_api_key(TM_KEY_NAME)
        if not key:
            return []

        params = {
            "apikey": key,
            "city": city,
            "size": 5,
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
            self._log(f"Ticketmaster request params: {params}")
            if resp.status_code == 200:
                events = resp.json().get("_embedded", {}).get("events", [])
                self._log(f"Ticketmaster returned {len(events)} events")
                parsed = []
                for e in events:
                    venues = e.get("_embedded", {}).get("venues", [])
                    v = venues[0] if venues else {}
                    venue_name = v.get("name", "an unknown venue")
                    venue_city = v.get("city", {}).get("name", "")
                    venue_addr = v.get("address", {}).get("line1", "")

                    start = e.get("dates", {}).get("start", {})

                    # Genre from classifications
                    genre = ""
                    for cl in e.get("classifications", []):
                        g = cl.get("genre", {}).get("name", "")
                        if g and g.lower() not in ("undefined", "other", ""):
                            genre = g
                            break

                    # Performer/artist names from attractions
                    performers = [
                        a["name"] for a in e.get("_embedded", {}).get("attractions", [])
                        if a.get("name") and a["name"].lower() != e.get("name", "").lower()
                    ]

                    # Ticket price range
                    price_min = price_max = None
                    currency = "USD"
                    for pr in e.get("priceRanges", []):
                        price_min = pr.get("min")
                        price_max = pr.get("max")
                        currency = pr.get("currency", "USD")
                        break

                    # Venue/event timezone for correct calendar conversion.
                    # Ticketmaster returns IANA timezones like "America/Los_Angeles"
                    # in dates.timezone — capture it so the calendar payload can
                    # preserve the actual venue clock time.
                    event_tz = e.get("dates", {}).get("timezone", "") or ""

                    parsed.append({
                        "name": e.get("name", "Unknown Event"),
                        "venue": venue_name,
                        "venue_city": venue_city,
                        "venue_address": venue_addr,
                        "date": start.get("localDate", ""),
                        "time": start.get("localTime", ""),
                        "timezone": event_tz,
                        "url": e.get("url", ""),
                        "source": "Ticketmaster",
                        "genre": genre,
                        "performers": performers,
                        "price_min": price_min,
                        "price_max": price_max,
                        "currency": currency,
                    })
                return parsed
        except Exception as e:
            self._err(f"Ticketmaster API error: {e}")
        return []

    async def _fetch_seatgeek(
        self, city: str, keyword: str,
        start_dt: Optional[str] = None, end_dt: Optional[str] = None,
    ) -> list[dict]:
        key = self._get_api_key(SEATGEEK_KEY_NAME)
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
        if start_dt:
            # SeatGeek expects local datetime without trailing Z
            params["datetime_local.gte"] = start_dt.replace("Z", "")
        if end_dt:
            params["datetime_local.lte"] = end_dt.replace("Z", "")

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(SEATGEEK_URL, params=params)
            if resp.status_code == 200:
                parsed = []
                for e in resp.json().get("events", []):
                    dt_local = e.get("datetime_local", "")
                    sg_venue = e.get("venue", {})

                    # Performers — skip the event title itself
                    event_title = e.get("title", "")
                    performers = [
                        p["name"] for p in e.get("performers", [])
                        if p.get("name") and p["name"].lower() != event_title.lower()
                    ]

                    # Price range from stats
                    stats = e.get("stats", {})
                    price_min = stats.get("lowest_price") or stats.get("average_price")
                    price_max = stats.get("highest_price")

                    parsed.append({
                        "name": event_title or "Unknown Event",
                        "venue": sg_venue.get("name", "an unknown venue"),
                        "venue_city": sg_venue.get("city", ""),
                        "venue_address": sg_venue.get("address", ""),
                        "date": dt_local.split("T")[0] if "T" in dt_local else "",
                        "time": dt_local.split("T")[1][:5] if "T" in dt_local else "",
                        "timezone": sg_venue.get("timezone", "") or "",
                        "url": e.get("url", ""),
                        "source": "SeatGeek",
                        "genre": e.get("type", ""),
                        "performers": performers,
                        "price_min": price_min,
                        "price_max": price_max,
                        "currency": "USD",
                    })
                return parsed
        except Exception as e:
            self._err(f"SeatGeek API error: {e}")
        return []

    async def _fetch_serper(
        self, city: str, keyword: str, time_context: str
    ) -> list[dict]:
        key = self._get_api_key(SERPER_KEY_NAME)
        if not key:
            return []

        query = f"{keyword or 'events'} in {city}"
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
                data = resp.json()
                parsed = []

                # Prefer Google's structured events widget when it exists.
                for e in data.get("events", [])[:5]:
                    parsed.append({
                        "name": e.get("title", "Unknown Event"),
                        "venue": e.get("address", "an unknown location"),
                        "venue_city": city,
                        "venue_address": "",
                        "date": _parse_freeform_date(e.get("date", "")),
                        "time": "",
                        "url": e.get("link", ""),
                        "source": "Google Events",
                        "genre": "",
                        "performers": [],
                        "price_min": None,
                        "price_max": None,
                        "currency": "USD",
                    })

                if parsed:
                    return parsed

                # Hackathons and startup/tech events often do not show up in
                # Ticketmaster, SeatGeek, or Google's events widget. For those
                # queries, allow organic results from event-focused sites.
                if _looks_like_tech_event_query(keyword, time_context):
                    for result in data.get("organic", [])[:8]:
                        event = _organic_result_to_event(result, city, keyword)
                        if event:
                            parsed.append(event)
                        if len(parsed) >= 5:
                            break

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
                _nearby_prompt = f"Near {ip_city} — search there?"
                ans = await self._ask(_nearby_prompt)
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
                    resp = await self._ask(_which_city_prompt)
                    if resp:
                        ex = await self._classify_intent(resp, _which_city_prompt)
                        city = ex.get("location") or (resp or "").strip()
        else:
            # Use last searched city as session context before falling back to saved home city
            city = raw_location or self.last_searched_city or prefs.get("home_city")

        # Normalize STT typos: if extracted city fuzzy-matches the confirmed home city, use the clean version
        if city and prefs.get("home_city"):
            ratio = difflib.SequenceMatcher(None, city.lower(), prefs["home_city"].lower()).ratio()
            if ratio > 0.7:
                city = prefs["home_city"]

        if not city or _is_invalid_city(city):
            _unsure_prompt = "I'm not sure which city to search in. What city would you like?"
            resp = await self._ask(_unsure_prompt)
            if resp:
                extracted = await self._classify_intent(resp, _unsure_prompt)
                city = extracted.get("location") or resp.strip()
            if not city or _is_invalid_city(city):
                await self.capability_worker.speak("Hmm, I didn't catch a city there — want to try again?")
                return False

        keyword = _clean_keyword(intent.get("category", "") or "")
        city = _normalize_city(city)
        time_context = (intent.get("time") or "").strip()

        # If the user didn't specify a time, default to "this week" rather
        # than searching across all dates. Keeps results timely and avoids
        # surfacing far-future or stale entries.
        if not time_context:
            time_context = "this week"
            self._log("No time given — defaulting to 'this week'")

        search_desc = f"{keyword or 'events'} in {city} for {time_context}"
        await self.capability_worker.speak(f"{random.choice(SEARCH_FILLERS)} Checking {search_desc}.")

        start_dt, end_dt = await self._parse_time_context(time_context)
        self._log(f"Date range for '{time_context}': start={start_dt} end={end_dt}")
        # User gave a time phrase but parser couldn't pin it down — flag for the result intro
        date_parse_failed = bool(time_context) and not start_dt and not end_dt

        tm_task = self._fetch_ticketmaster(
            city=city, keyword=keyword, start_dt=start_dt, end_dt=end_dt,
        )
        serper_task = self._fetch_serper(
            city=city, keyword=keyword, time_context=time_context,
        )
        tm_events, serper_events = await asyncio.gather(tm_task, serper_task)

        # Remember the city for follow-up queries in the same session
        self.last_searched_city = city

        if not tm_events:
            self._log("Ticketmaster returned 0 events — trying SeatGeek.")
            tm_events = await self._fetch_seatgeek(city=city, keyword=keyword, start_dt=start_dt, end_dt=end_dt)

        combined = []
        if tm_events:
            combined.extend(tm_events[:5])
        if serper_events:
            combined.extend(serper_events[:3])

        seen: set = set()
        final_events: list[dict] = []
        for e in combined:
            title_lower = e["name"].lower().strip()
            if title_lower not in seen:
                seen.add(title_lower)
                final_events.append(e)

        # Drop past events. If the date is missing or unparseable, keep the
        # event — it might be a valid listing without a structured date.
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        def _not_past(ev: dict) -> bool:
            d = (ev.get("date") or "").strip()
            if not d or len(d) < 10:
                return True
            return d[:10] >= today_str
        final_events = [e for e in final_events if _not_past(e)]

        self.current_events = final_events

        if not final_events:
            # If a time filter was active, retry without it and offer upcoming events instead
            if time_context and (start_dt or end_dt):
                fb_tm, fb_serper = await asyncio.gather(
                    self._fetch_ticketmaster(city=city, keyword=keyword, start_dt=None, end_dt=None),
                    self._fetch_serper(city=city, keyword=keyword, time_context=""),
                )
                if not fb_tm:
                    fb_tm = await self._fetch_seatgeek(city=city, keyword=keyword)
                fb_combined: list[dict] = []
                fb_seen: set = set()
                for e in list(fb_tm[:5]) + list(fb_serper[:3]):
                    t = e["name"].lower().strip()
                    if t not in fb_seen:
                        fb_seen.add(t)
                        fb_combined.append(e)
                fb_combined = [e for e in fb_combined if _not_past(e)]
                if fb_combined:
                    self.current_events = fb_combined
                    events_to_speak, remaining = _pick_diverse_dates(fb_combined, 2)
                    self.last_spoken_events = events_to_speak
                    self.remaining_events = remaining
                    fallback = self._fallback_event_results(
                        events_to_speak,
                        f"Nothing for {time_context} in {city}, but here's what's coming up.",
                    )
                    await self._speak_generated_event_response(
                        events_to_speak,
                        "search results",
                        f"{keyword or 'events'} in {city}; fallback because nothing matched {time_context}",
                        fallback,
                    )
                    return True

            has_tm_key = bool(self._get_api_key(TM_KEY_NAME))
            has_serper_key = bool(self._get_api_key(SERPER_KEY_NAME))
            if not has_tm_key and not has_serper_key:
                msg = "No API keys set up. Add your Ticketmaster key in OpenHome settings to get started."
            else:
                # Speak the fact only — the main loop will ask the next question
                # via the "empty" followup, so we don't double-up here.
                msg = (
                    f"I didn't find anything for {keyword or 'events'} in {city}"
                    + (f" {time_context}" if time_context else "")
                    + "."
                )
            await self.capability_worker.speak(msg)
            return False

        # Pick a date-diverse pair so a broad window (e.g. "this week") doesn't
        # speak two events from today and starve later days.
        events_to_speak, remaining = _pick_diverse_dates(final_events, 2)
        self.last_spoken_events = events_to_speak
        self.remaining_events = remaining

        if date_parse_failed:
            intro = f"Couldn't pin down the date, but here's what's coming up in {city}."
        elif len(final_events) == 1:
            intro = f"One show in {city}."
        else:
            intro = f"Here's what's coming up in {city}."

        fallback = self._fallback_event_results(events_to_speak, intro)
        await self._speak_generated_event_response(
            events_to_speak,
            "search results",
            search_desc,
            fallback,
        )
        return True

    def _fallback_event_results(self, events: list[dict], intro: str) -> str:
        ordinals = ["First", "Second", "Third", "Fourth", "Fifth"]
        parts = [intro]
        for i, ev in enumerate(events):
            date_str = _format_spoken_date(ev.get("date", "")) if ev.get("date") else ""
            line = f"{ordinals[i] if i < len(ordinals) else 'Also'}, {ev.get('name', 'Unknown Event')}"
            if date_str:
                line += f", {date_str}"
            if ev.get("venue"):
                line += f" at {ev['venue']}"
            if ev.get("price_min"):
                symbol = _CURRENCY_SYMBOLS.get(ev.get("currency", "USD"), "")
                line += f", from {symbol}{ev['price_min']:.0f}"
            line += "."
            parts.append(line)
        return " ".join(parts)

    async def _handle_more(self):
        if not self.remaining_events:
            await self.capability_worker.speak("That's all I found for this search.")
            return False

        batch = self.remaining_events[:3]
        self.remaining_events = self.remaining_events[3:]
        self.last_spoken_events = batch

        fallback = self._fallback_event_results(batch, "Here are a few more.")
        await self.capability_worker.speak(random.choice(MORE_FILLERS))
        await self._speak_generated_event_response(
            batch,
            "more results",
            "additional events from the previous search",
            fallback,
        )
        return True

    async def _handle_expand(self, intent: dict, prefs: dict = None):
        if not self.current_events:
            await self.capability_worker.speak("Let me find some events first — one moment.")
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
            selection = await self._select_from_current_events(ref)
            action = selection.get("action")
            if action == "exit":
                return False
            if action == "more":
                return await self._handle_more()
            if action == "new_search":
                await self.capability_worker.speak("Sure, what should I look for instead?")
                return False
            if action in ("details", "calendar"):
                ev = self._event_from_selection_index(selection.get("index"))
            if ev is None:
                # Speak the fact only — main loop's recovery prompt asks next.
                await self.capability_worker.speak("I didn't catch which one you meant.")
                return False

        self.last_expanded_event = ev

        await self.capability_worker.speak(random.choice(DETAIL_FILLERS))
        fallback = self._fallback_event_details(ev)
        await self._speak_generated_event_response(
            [ev],
            "details",
            "event details",
            fallback,
        )
        return True

    def _fallback_event_details(self, ev: dict) -> str:
        date_str = _format_spoken_date(ev["date"]) if ev["date"] else ""
        time_str = _format_time(ev["time"]) if ev["time"] else ""
        venue = ev.get("venue", "")
        venue_city = ev.get("venue_city", "")
        genre = ev.get("genre", "")
        performers = ev.get("performers", []) or []
        price_min = ev.get("price_min")
        price_max = ev.get("price_max")
        currency = ev.get("currency", "USD")

        parts = []

        # Line 1: name, venue, city
        venue_phrase = venue
        if venue and venue_city and venue_city.lower() not in venue.lower():
            venue_phrase = f"{venue} in {venue_city}"
        if venue_phrase:
            parts.append(f"{ev['name']} is at {venue_phrase}.")
        elif venue_city:
            parts.append(f"{ev['name']} is listed for {venue_city}.")
        else:
            parts.append(f"{ev['name']}.")

        # Line 2: date and time
        if date_str and time_str:
            parts.append(f"It's on {date_str} at {time_str}.")
        elif date_str:
            parts.append(f"It's on {date_str}.")

        # Line 3: genre and/or performers
        if performers and genre:
            perf_str = ", ".join(performers[:3])
            parts.append(f"It's a {genre} event featuring {perf_str}.")
        elif performers:
            perf_str = ", ".join(performers[:3])
            parts.append(f"Featuring {perf_str}.")
        elif genre:
            parts.append(f"It's a {genre} event.")

        # Line 4: ticket prices
        if price_min and price_max and price_max > price_min:
            parts.append(f"Tickets range from {currency} {price_min:.0f} to {price_max:.0f}.")
        elif price_min:
            parts.append(f"Tickets start from {currency} {price_min:.0f}.")

        return " ".join(parts)

    async def _handle_calendar(self, intent: dict):
        ref = intent.get("event_reference")
        # Fast paths — skip resolution entirely when the target is obvious:
        # 1. Only one event in view → that's the one, no need to disambiguate.
        # 2. User just heard details on a specific event → use that one.
        # 3. Pronoun reference ("it", "that") → use focused or the only event.
        if len(self.current_events) == 1:
            ev = self.current_events[0]
        elif not ref and self.last_expanded_event:
            ev = self.last_expanded_event
        elif ref and ref.lower().strip() in {"it", "that", "this", "that one", "this one"}:
            ev = self.last_expanded_event or (
                self.current_events[0] if self.current_events else None
            )
        else:
            ev = self._resolve_event_ref(ref or "first")

        if ev is None:
            selection = await self._select_from_current_events(ref or self._latest_user_request())
            if selection.get("action") == "calendar":
                ev = self._event_from_selection_index(selection.get("index"))
            elif selection.get("action") == "exit":
                return False

        if ev is None:
            # Speak the fact only — main loop's recovery prompt asks next.
            if not self.current_events:
                await self.capability_worker.speak("Let me find some events for you first.")
            else:
                await self.capability_worker.speak("I didn't catch which one to save.")
            return False

        # Build spoken confirmation with date and time when available
        _cal_date = _format_spoken_date(ev["date"]) if ev.get("date") else ""
        _cal_time = _format_time(ev["time"]) if ev.get("time") else ""
        if _cal_date and _cal_time:
            _cal_confirm = f"Added {ev['name']} to your calendar for {_cal_date} at {_cal_time}."
        elif _cal_date:
            _cal_confirm = f"Added {ev['name']} to your calendar for {_cal_date}."
        else:
            _cal_confirm = f"Added {ev['name']} to your calendar."

        google_token = self.capability_worker.get_token("google")
        if google_token:
            try:
                start_payload, end_payload = self._calendar_time_payload(ev)
                payload = {
                    "summary": ev.get("name", "Local Event"),
                    "location": ev.get("venue", ""),
                    "description": f"Found via OpenHome Local Event Explorer.\nLink: {ev.get('url', '')}",
                    "start": start_payload,
                    "end": end_payload,
                }
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.post(
                        CALENDAR_URL,
                        headers={"Authorization": f"Bearer {google_token}"},
                        json=payload,
                    )
                if response.status_code in (200, 201):
                    await self.capability_worker.speak(_cal_confirm)
                    return True
                else:
                    self._err(f"Calendar API error: {response.status_code}")
            except Exception as e:
                self._err(f"Calendar exception: {e}")

        title = _url_encode(ev["name"])
        location = _url_encode(ev["venue"])
        details = _url_encode(f"Found via OpenHome Local Event Explorer. Link: {ev['url']}")

        dates_param = ""
        ctz_param = ""
        try:
            if ev.get("date"):
                t_str = (ev.get("time") or "12:00:00")[:8]
                if len(t_str) == 5:
                    t_str += ":00"
                dt = datetime.datetime.strptime(f"{ev['date']} {t_str}", "%Y-%m-%d %H:%M:%S")
                end_dt = dt + datetime.timedelta(hours=2)
                dates_param = f"&dates={dt.strftime('%Y%m%dT%H%M%S')}/{end_dt.strftime('%Y%m%dT%H%M%S')}"
                tz_name = self._event_timezone(ev)
                if tz_name and tz_name != "UTC":
                    ctz_param = f"&ctz={_url_encode(tz_name)}"
        except Exception as e:
            self._log(f"Failed to parse dates for calendar link: {e}")

        cal_link = (
            f"https://calendar.google.com/calendar/r/eventedit"
            f"?text={title}&location={location}&details={details}{dates_param}{ctz_param}"
        )
        self._log(f"Generated calendar link: {cal_link}")
        link_msg = f"Check your device — I sent a calendar link for {ev['name']}"
        link_msg += f" on {_cal_date}." if _cal_date else "."
        await self.capability_worker.speak(link_msg)
        return True

    def _event_timezone(self, ev: dict) -> str:
        """Resolve the IANA timezone for this event. Order of preference:
        1. The venue/event's own timezone from the source API.
        2. The user's local timezone via the SDK.
        3. UTC as a last resort.
        """
        tz = (ev.get("timezone") or "").strip()
        if tz:
            return tz
        try:
            user_tz = self.capability_worker.get_timezone()
            if user_tz:
                return user_tz
        except Exception:
            pass
        return "UTC"

    def _calendar_time_payload(self, ev: dict) -> tuple[dict, dict]:
        """Build (start, end) dicts for the Google Calendar API payload.

        Each dict has a naive `dateTime` (local clock at the venue) and an
        explicit `timeZone` so Google stores the event at the correct moment
        regardless of the user's or server's timezone.
        """
        tz_name = self._event_timezone(ev)
        date_str = (ev.get("date") or "").strip()
        time_str = (ev.get("time") or "12:00:00")[:8]
        # Pad HH:MM → HH:MM:SS so strptime is happy
        if len(time_str) == 5:
            time_str += ":00"
        try:
            start_local = datetime.datetime.strptime(
                f"{date_str}T{time_str}", "%Y-%m-%dT%H:%M:%S"
            )
        except (ValueError, TypeError):
            # Date or time unparseable — fall back to now in the chosen tz.
            try:
                tz_obj = zoneinfo.ZoneInfo(tz_name)
            except Exception:
                tz_obj = datetime.timezone.utc
            start_local = datetime.datetime.now(tz_obj).replace(tzinfo=None)
        end_local = start_local + datetime.timedelta(hours=2)
        return (
            {"dateTime": start_local.isoformat(), "timeZone": tz_name},
            {"dateTime": end_local.isoformat(), "timeZone": tz_name},
        )
