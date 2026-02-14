import json
import os
import re
from typing import Optional, Dict, Any, List

import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# ---------------------------
# AirLabs config
# ---------------------------
# Get an API key from AirLabs: https://airlabs.co/
# For testing, paste your key here.
# Before final submission, revert to:
# AIRLABS_API_KEY = "REPLACE_WITH_YOUR_KEY"
AIRLABS_API_KEY = "4e86e577-3e92-43af-90b2-ca826424896e"

AIRLABS_FLIGHT_URL = "https://airlabs.co/api/v9/flight"
AIRLABS_SCHEDULES_URL = "https://airlabs.co/api/v9/schedules"

STATE_FILE = "live_flight_state.json"  # persistent per-user storage


# ---------------------------
# Voice UX constants
# ---------------------------
EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave"}
REPEAT_PHRASES = {"repeat", "repeat last", "again", "say that again"}
SAMPLE_PHRASES = {"sample", "examples", "example", "show me flights", "sample flights"}
DETAIL_PHRASES = {"details", "more details", "more", "tell me more", "extra info", "gate info", "aircraft"}

AIRLINE_NAME_TO_IATA = {
    "delta": "DL",
    "american": "AA",
    "american airlines": "AA",
    "united": "UA",
    "southwest": "WN",
    "alaska": "AS",
    "jetblue": "B6",
    "spirit": "NK",
    "frontier": "F9",
    "ethiopian": "ET",
}

NUM_WORD = {
    "zero": "0", "oh": "0",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


def _clean(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _has_exit(text: str) -> bool:
    t = _clean(text)
    return any(w in t.split() for w in EXIT_WORDS)


def _is_repeat(text: str) -> bool:
    t = _clean(text)
    return any(p == t or p in t for p in REPEAT_PHRASES)


def _is_sample(text: str) -> bool:
    t = _clean(text)
    return any(p == t or p in t for p in SAMPLE_PHRASES)


def _is_details(text: str) -> bool:
    t = _clean(text)
    return any(p == t or p in t for p in DETAIL_PHRASES)


def _spell(code: str) -> str:
    code = (code or "").strip().upper()
    return " ".join(list(code)) if code else ""


def format_datetime_for_voice(s: Optional[str]) -> str:
    """
    Converts strings like:
    - "2026-02-14 08:59"
    - "2026-02-14 08:59:00"
    - "2026-02-14T08:59:00Z"
    - "2026-02-14T08:59:00+00:00"
    - "08:59"
    into voice-friendly output like:
    - "Feb 14 at 8 59 AM"
    - "8 59 AM"
    If parsing fails, returns the original string.
    """
    if not s:
        return "—"

    txt = str(s).strip()

    # Normalize ISO-like formats
    txt = txt.replace("T", " ")
    txt = txt.replace("Z", "")
    # Remove timezone offsets if present (e.g., +00:00, -05:00)
    txt = re.split(r"[+-]\d{2}:\d{2}$", txt)[0].strip()

    # Try: YYYY-MM-DD HH:MM(:SS)?
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::\d{2})?$", txt)
    if m:
        month = int(m.group(2))
        day = int(m.group(3))
        hh = int(m.group(4))
        mm = int(m.group(5))

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        mon = month_names[month - 1] if 1 <= month <= 12 else str(month)

        ampm = "AM"
        hh12 = hh
        if hh == 0:
            hh12 = 12
        elif hh == 12:
            ampm = "PM"
        elif hh > 12:
            hh12 = hh - 12
            ampm = "PM"

        # “8 59 AM” reads cleaner than “8:59 AM” on many TTS engines
        return f"{mon} {day} at {hh12} {mm:02d} {ampm}"

    # Try: HH:MM(:SS)?
    m2 = re.match(r"^(\d{2}):(\d{2})(?::\d{2})?$", txt)
    if m2:
        hh = int(m2.group(1))
        mm = int(m2.group(2))
        ampm = "AM"
        hh12 = hh
        if hh == 0:
            hh12 = 12
        elif hh == 12:
            ampm = "PM"
        elif hh > 12:
            hh12 = hh - 12
            ampm = "PM"
        return f"{hh12} {mm:02d} {ampm}"

    return txt


def parse_airport_code(text: str) -> Optional[str]:
    t = _clean(text)
    if not t:
        return None

    m = re.search(r"\b([a-z]{3})\b", t)
    if m:
        return m.group(1).upper()

    m2 = re.search(r"\b([a-z])\s+([a-z])\s+([a-z])\b", t)
    if m2:
        return (m2.group(1) + m2.group(2) + m2.group(3)).upper()

    return None


def parse_arrivals_or_departures(text: str) -> str:
    t = _clean(text)
    if "depart" in t or "leaving" in t:
        return "departures"
    return "arrivals"


def _extract_iata_from_text(text: str) -> Optional[str]:
    t = _clean(text)

    m = re.search(r"\b([a-z]{2})\b", t)
    if m:
        return m.group(1).upper()

    m2 = re.search(r"\b([a-z])\s+([a-z])\b", t)
    if m2:
        return (m2.group(1) + m2.group(2)).upper()

    for name, code in AIRLINE_NAME_TO_IATA.items():
        if name in t:
            return code

    return None


def _extract_digits_from_text(text: str) -> Optional[str]:
    t = _clean(text)

    digit_runs = re.findall(r"\d{1,5}", t)
    if digit_runs:
        digit_runs.sort(key=len, reverse=True)
        return digit_runs[0]

    parts = t.split()
    digits = []
    for p in parts:
        if p in NUM_WORD:
            digits.append(NUM_WORD[p])
    if digits:
        return "".join(digits)

    return None


def parse_flight_iata(text: str) -> Optional[str]:
    """
    Parses:
    - "AA 6"
    - "A A six"
    - "Delta one three three five"
    - "DL1335"
    """
    t = _clean(text)
    if not t:
        return None

    m = re.search(r"\b([a-z]{2})\s*(\d{1,5})\b", t)
    if m:
        return (m.group(1) + m.group(2)).upper()

    iata = _extract_iata_from_text(t)
    digits = _extract_digits_from_text(t)
    if iata and digits:
        return (iata + digits).upper()

    return None


class LiveFlightStatusCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    last_spoken: str = ""
    state: Dict[str, Any] = {}

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.main())

    # ---------------------------
    # Storage helpers (persistent)
    # ---------------------------
    async def load_state(self) -> Dict[str, Any]:
        try:
            exists = await self.capability_worker.check_if_file_exists(STATE_FILE, False)
            if not exists:
                return {}
            raw = await self.capability_worker.read_file(STATE_FILE, False)
            if not raw:
                return {}
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"State load failed: {e}")
            return {}

    async def save_state(self, state: Dict[str, Any]) -> None:
        try:
            exists = await self.capability_worker.check_if_file_exists(STATE_FILE, False)
            if exists:
                await self.capability_worker.delete_file(STATE_FILE, False)
            await self.capability_worker.write_file(STATE_FILE, json.dumps(state), False)
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"State save failed: {e}")

    # ---------------------------
    # Voice helpers
    # ---------------------------
    async def speak_short(self, text: str) -> None:
        self.last_spoken = text
        await self.capability_worker.speak(text)

    async def listen(self) -> str:
        try:
            if hasattr(self.capability_worker, "wait_for_complete_transcription"):
                text = await self.capability_worker.wait_for_complete_transcription()
            else:
                text = await self.capability_worker.user_response()
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Listen failed: {e}")
            text = ""
        return (text or "").strip()

    async def nap(self, seconds: float) -> None:
        await self.worker.session_tasks.sleep(seconds)

    # ---------------------------
    # AirLabs API
    # ---------------------------
    def fetch_flight(self, flight_iata: str) -> Optional[Dict[str, Any]]:
        params = {"api_key": AIRLABS_API_KEY, "flight_iata": flight_iata}
        r = requests.get(AIRLABS_FLIGHT_URL, params=params, timeout=20)
        r.raise_for_status()
        payload = r.json()
        return payload.get("response")

    def fetch_samples(self, airport_iata: str, mode: str, limit: int = 5) -> List[Dict[str, Any]]:
        params = {"api_key": AIRLABS_API_KEY, "limit": min(limit, 10), "offset": 0}
        if mode == "departures":
            params["dep_iata"] = airport_iata
        else:
            params["arr_iata"] = airport_iata

        r = requests.get(AIRLABS_SCHEDULES_URL, params=params, timeout=20)
        r.raise_for_status()
        payload = r.json()
        return payload.get("response") or []

    # ---------------------------
    # Formatting (voice-first)
    # ---------------------------
    def quick_summary(self, flight_iata: str, f: Dict[str, Any]) -> str:
        dep = f.get("dep_iata") or "—"
        arr = f.get("arr_iata") or "—"
        status = f.get("status") or "unknown"

        dep_time_raw = f.get("dep_time") or f.get("dep_estimated")
        arr_time_raw = f.get("arr_time") or f.get("arr_estimated")

        dep_time = format_datetime_for_voice(dep_time_raw)
        arr_time = format_datetime_for_voice(arr_time_raw)

        return f"{flight_iata}: {dep} to {arr}. Status {status}. Departs {dep_time}. Arrives {arr_time}."

    def detail_lines(self, f: Dict[str, Any]) -> List[str]:
        lines: List[str] = []

        airline = f.get("airline_name") or f.get("airline_iata")
        aircraft = f.get("aircraft_icao") or f.get("aircraft_iata")
        reg = f.get("reg_number")
        if airline or aircraft or reg:
            bits = []
            if airline:
                bits.append(f"Airline {airline}.")
            if aircraft:
                bits.append(f"Aircraft {aircraft}.")
            if reg:
                bits.append(f"Tail {reg}.")
            lines.append(" ".join(bits))

        dep_term = f.get("dep_terminal")
        dep_gate = f.get("dep_gate")
        arr_term = f.get("arr_terminal")
        arr_gate = f.get("arr_gate")
        if dep_term or dep_gate or arr_term or arr_gate:
            lines.append(
                f"Depart terminal {dep_term or '—'}, gate {dep_gate or '—'}. "
                f"Arrive terminal {arr_term or '—'}, gate {arr_gate or '—'}."
            )

        delay = f.get("delayed")
        if isinstance(delay, (int, float)) and delay > 0:
            lines.append(f"Delay looks like about {int(delay)} minutes.")

        dep_city = f.get("dep_city")
        arr_city = f.get("arr_city")
        if dep_city or arr_city:
            lines.append(f"Route: {dep_city or '—'} to {arr_city or '—'}.")

        return [ln for ln in lines if ln][:2]

    def summarize_schedule_item(self, item: Dict[str, Any]) -> str:
        flight = item.get("flight_iata") or "—"
        dep = item.get("dep_iata") or "—"
        arr = item.get("arr_iata") or "—"

        dep_time_raw = item.get("dep_time") or item.get("dep_estimated")
        dep_time = format_datetime_for_voice(dep_time_raw)

        return f"{flight}: {dep} to {arr}. Departs {dep_time}."

    # ---------------------------
    # Main flow
    # ---------------------------
    async def main(self):
        self.state = await self.load_state()

        if AIRLABS_API_KEY == "REPLACE_WITH_YOUR_KEY":
            await self.speak_short("Add your AirLabs API key in main dot py, then try again.")
            self.capability_worker.resume_normal_flow()
            return

        await self.speak_short("Tell me a flight, like A A six. Or say sample flights.")
        empty_count = 0

        try:
            while True:
                user_text = await self.listen()

                # Exit words first
                if user_text and _has_exit(user_text):
                    await self.speak_short("Okay. Goodbye.")
                    break

                if not user_text:
                    empty_count += 1
                    await self.nap(0.6)
                    if empty_count == 4:
                        empty_count = 0
                        await self.speak_short("I’m listening. Say a flight, or say sample flights.")
                    continue

                empty_count = 0

                if _is_repeat(user_text):
                    await self.speak_short(self.last_spoken or "Nothing to repeat yet.")
                    continue

                if _is_details(user_text):
                    last_f = (self.state or {}).get("last_flight")
                    if not last_f:
                        await self.speak_short("Say a flight first, then ask for details.")
                        continue
                    await self.speak_short(f"More details for {last_f}.")
                    await self.say_details_for(last_f)
                    await self.speak_short("You can say another flight, or say stop.")
                    continue

                if "last flight" in _clean(user_text) or "use last" in _clean(user_text):
                    last_f = (self.state or {}).get("last_flight")
                    if not last_f:
                        await self.speak_short("I don’t have a last flight saved yet.")
                        continue
                    await self.check_and_say(last_f)
                    await self.speak_short("You can say details, another flight, or say stop.")
                    continue

                if _is_sample(user_text):
                    await self.sample_flow()
                    await self.speak_short("Now say the flight you want me to check.")
                    continue

                flight_iata = parse_flight_iata(user_text)
                if not flight_iata:
                    await self.speak_short("Try airline letters and a number, like Delta one three three five.")
                    continue

                await self.check_and_say(flight_iata)
                await self.speak_short("Say details for more, or say another flight. Say stop to exit.")

        finally:
            self.capability_worker.resume_normal_flow()

    async def check_and_say(self, flight_iata: str) -> None:
        self.state = self.state or {}
        self.state["last_flight"] = flight_iata
        await self.save_state(self.state)

        await self.speak_short(f"Checking {flight_iata}.")
        try:
            f = self.fetch_flight(flight_iata)
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Flight fetch failed: {e}")
            f = None

        if not f:
            await self.speak_short("I couldn’t find that flight right now. Try another one.")
            return

        await self.speak_short(self.quick_summary(flight_iata, f))

    async def say_details_for(self, flight_iata: str) -> None:
        try:
            f = self.fetch_flight(flight_iata)
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Detail fetch failed: {e}")
            f = None

        if not f:
            await self.speak_short("I couldn’t pull the extra details right now.")
            return

        lines = self.detail_lines(f)
        if not lines:
            await self.speak_short("AirLabs didn’t return extra details for this flight.")
            return

        for ln in lines:
            await self.speak_short(ln)

    async def sample_flow(self) -> None:
        await self.speak_short("Say an airport code and arrivals or departures. Like A U S arrivals.")
        hint_used = False

        while True:
            txt = await self.listen()

            if txt and _has_exit(txt):
                await self.speak_short("Okay.")
                return

            if not txt:
                await self.nap(0.6)
                continue

            airport = parse_airport_code(txt)
            if not airport:
                if not hint_used:
                    hint_used = True
                    await self.speak_short("I need a three letter code, like J F K.")
                else:
                    await self.speak_short("Try again, or say stop.")
                continue

            mode = parse_arrivals_or_departures(txt)

            self.state = self.state or {}
            self.state["last_airport"] = airport
            self.state["last_mode"] = mode
            await self.save_state(self.state)

            await self.speak_short(f"Got it. {_spell(airport)} {mode}. One moment.")
            try:
                items = self.fetch_samples(airport, mode, limit=5)
            except Exception as e:
                self.worker.editor_logging_handler.warning(f"Schedules fetch failed: {e}")
                items = []

            if not items:
                await self.speak_short("I don’t see flights for that right now.")
                return

            for item in items[:2]:
                await self.speak_short(self.summarize_schedule_item(item))

            await self.speak_short("Say sample flights again for more, or say a flight to check.")
            return
