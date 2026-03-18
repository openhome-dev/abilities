import json
import re
import requests
from datetime import datetime
from typing import ClassVar

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# FLIGHT BOOKING
# Voice-controlled flight search and booking via Duffel API.
# Supports one-way and round-trip, reads back top 3 offers, collects passenger
# details, and creates a hold booking (pay-later). No payment by voice.
# =============================================================================


class FlightBookingCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    api_key: str = None

    # Do not change following tag of register capability
    # {{register capability}}

    DUFFEL_BASE: ClassVar[str] = "https://api.duffel.com"
    DUFFEL_API_KEY: ClassVar[str] = "duffel_test_YOUR_KEY_HERE"
    HISTORY_FILE: ClassVar[str] = "flight_booking_history.json"

    IATA_MAP: ClassVar[dict] = {
        "new york": "JFK", "london": "LHR", "dubai": "DXB",
        "paris": "CDG", "los angeles": "LAX", "chicago": "ORD",
        "toronto": "YYZ", "sydney": "SYD", "tokyo": "NRT",
        "karachi": "KHI", "lahore": "LHE", "islamabad": "ISB",
        "istanbul": "IST", "amsterdam": "AMS", "frankfurt": "FRA",
        "singapore": "SIN", "hong kong": "HKG", "bangkok": "BKK",
        "madrid": "MAD", "rome": "FCO", "milan": "MXP",
        "san francisco": "SFO", "miami": "MIA", "dallas": "DFW",
        "boston": "BOS", "seattle": "SEA", "washington": "IAD",
        "manchester": "MAN", "birmingham": "BHX", "edinburgh": "EDI",
        "mumbai": "BOM", "delhi": "DEL", "bangalore": "BLR",
        "cairo": "CAI", "nairobi": "NBO", "johannesburg": "JNB",
        "barcelona": "BCN", "lisbon": "LIS", "zurich": "ZRH",
        "vienna": "VIE", "brussels": "BRU", "copenhagen": "CPH",
        "oslo": "OSL", "stockholm": "ARN", "helsinki": "HEL",
        "athens": "ATH", "budapest": "BUD", "warsaw": "WAW",
        "prague": "PRG", "bucharest": "OTP", "kyiv": "KBP",
        "moscow": "SVO", "beijing": "PEK", "shanghai": "PVG",
        "seoul": "ICN", "taipei": "TPE", "kuala lumpur": "KUL",
        "jakarta": "CGK", "manila": "MNL", "ho chi minh": "SGN",
        "hanoi": "HAN", "dhaka": "DAC", "colombo": "CMB",
        "riyadh": "RUH", "jeddah": "JED", "doha": "DOH",
        "abu dhabi": "AUH", "kuwait": "KWI", "beirut": "BEY",
        "tel aviv": "TLV", "amman": "AMM", "casablanca": "CMN",
        "lagos": "LOS", "accra": "ACC", "addis ababa": "ADD",
        "mexico city": "MEX", "sao paulo": "GRU", "buenos aires": "EZE",
        "bogota": "BOG", "lima": "LIM", "santiago": "SCL",
        "montreal": "YUL", "vancouver": "YVR", "calgary": "YYC",
    }

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _is_exit_intent(self, response: str) -> bool:
        """Return True if the user wants to cancel or exit the current task."""
        prompt = (
            f"The user said: '{response}'. "
            "Are they trying to cancel, stop, or exit the current task? "
            "Reply ONLY with YES or NO."
        )
        return self.capability_worker.text_to_text_response(prompt).strip().upper().startswith("Y")

    def _normalize_city_name(self, raw: str, iata: str) -> str:
        """Return a clean display name for a city given its resolved IATA code."""
        for city, code in self.IATA_MAP.items():
            if code == iata:
                return city.title()
        words = raw.strip().split()
        if len(words) <= 3:
            return raw.strip().rstrip(".,!?").title()
        prompt = (
            f"What city does the IATA airport code '{iata}' primarily serve? "
            "Return ONLY the common city name, nothing else."
        )
        return self.capability_worker.text_to_text_response(prompt).strip().title()

    def _parse_phone(self, user_input: str) -> str:
        """Convert spoken phone number (words or digits) to E.164 format via LLM."""
        prompt = (
            f"The user said: '{user_input}'. "
            "This is a phone number including a country code spoken with a US/international accent. "
            "Convert it to E.164 format (e.g. +923013018173). "
            "Return ONLY the + sign followed by digits. No spaces, no hyphens, no other text."
        )
        result = self.capability_worker.text_to_text_response(prompt).strip()
        clean = re.sub(r"[^\d+]", "", result)
        if clean and not clean.startswith("+"):
            clean = "+" + clean
        self.worker.editor_logging_handler.info(f"[FlightBooking] Phone parsed: '{user_input}' → '{clean}'")
        return clean

    def _format_date_natural(self, date_str: str) -> str:
        """Convert '2026-04-25' → 'April 25th' for voice readback."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            d = dt.day
            sfx = "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
            return dt.strftime(f"%B {d}{sfx}")
        except Exception:
            return date_str

    def _fmt_time_12h(self, t: str) -> str:
        """Convert HH:MM (24-hour) to h:MM AM/PM for natural voice readback."""
        try:
            dt = datetime.strptime(t, "%H:%M")
            hour = dt.hour % 12 or 12
            minute = dt.strftime("%M")
            period = "AM" if dt.hour < 12 else "PM"
            return f"{hour}:{minute} {period}"
        except Exception:
            return t

    def _duffel_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Duffel-Version": "v2",
        }

    def _resolve_airport(self, city_or_code: str) -> str:
        """Map city name to IATA code. Falls back to LLM."""
        lower = city_or_code.lower().strip()
        if lower in self.IATA_MAP:
            return self.IATA_MAP[lower]
        upper = city_or_code.strip().upper()
        if len(upper) == 3 and upper.isalpha():
            return upper
        prompt = (
            f"Return ONLY the 3-letter IATA airport code for the main international "
            f"airport serving: {city_or_code}. No explanation, no punctuation, just 3 letters."
        )
        code = self.capability_worker.text_to_text_response(prompt).strip().upper()
        self.worker.editor_logging_handler.info(f"[FlightBooking] IATA resolve '{city_or_code}' → '{code}'")
        return code if len(code) == 3 and code.isalpha() else ""

    def _parse_date(self, user_input: str) -> str:
        """LLM parses natural language date to YYYY-MM-DD."""
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = (
            f"Today is {today}. The user said: '{user_input}'. "
            "Return ONLY the date in YYYY-MM-DD format. No other text."
        )
        result = self.capability_worker.text_to_text_response(prompt).strip()
        match = re.search(r"\d{4}-\d{2}-\d{2}", result)
        return match.group() if match else result

    def _extract_flight_details_from_utterance(self, utterance: str) -> dict:
        """Try to extract origin, destination, and date from the trigger sentence."""
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = (
            f"Today is {today}. The user said: '{utterance}'.\n"
            "Extract flight details. Return ONLY valid JSON with these fields (use null if not mentioned):\n"
            '{"origin": "city or airport", "destination": "city or airport", '
            '"date": "YYYY-MM-DD or null", "return_date": "YYYY-MM-DD or null", '
            '"trip_type": "one-way or round-trip or null", "cabin": "economy or business or first or null"}'
        )
        raw = self.capability_worker.text_to_text_response(prompt).strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _extract_passenger_fields(self, utterance: str, fields: list) -> dict:
        """Extract named passenger fields from a spoken utterance via LLM."""
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = (
            f"Today is {today}. The user said: '{utterance}'.\n"
            f"Extract these fields: {fields}.\n"
            "Return ONLY valid JSON. Use null for any field not clearly present.\n"
            "Rules: born_on → YYYY-MM-DD, email → lowercase ASCII, "
            "phone_number → E.164 (+countrycode digits, e.g. +12025551234).\n"
            'Example: {"given_name": "John", "family_name": "Smith", "born_on": "1990-03-05"}'
        )
        raw = self.capability_worker.text_to_text_response(prompt).strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
        try:
            return json.loads(raw)
        except Exception:
            return {f: None for f in fields}

    def _search_flights(self, origin: str, dest: str, date: str,
                        return_date: str, cabin: str) -> list:
        """Create Duffel offer request, return top 3 holdable offers sorted by price."""
        slices = [{"origin": origin, "destination": dest, "departure_date": date}]
        if return_date:
            slices.append({"origin": dest, "destination": origin, "departure_date": return_date})

        payload = {"data": {
            "slices": slices,
            "passengers": [{"type": "adult"}],
            "cabin_class": cabin,
            "return_offers": True,
        }}
        self.worker.editor_logging_handler.info(f"[FlightBooking] Search: {origin}→{dest} on {date}")
        resp = requests.post(
            f"{self.DUFFEL_BASE}/air/offer_requests",
            headers=self._duffel_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        offers = resp.json().get("data", {}).get("offers", [])
        self.worker.editor_logging_handler.info(f"[FlightBooking] {len(offers)} offer(s) returned (pre-filter)")

        holdable = [
            o for o in offers
            if not o.get("payment_requirements", {}).get("requires_instant_payment", True)
        ]
        self.worker.editor_logging_handler.info(
            f"[FlightBooking] {len(holdable)} holdable offer(s) after filter"
        )
        result = holdable if holdable else offers
        result.sort(key=lambda o: float(o.get("total_amount", "9999") or "9999"))
        return result[:3]

    def _format_offer(self, offer: dict, index: int) -> str:
        """Build a concise, voice-friendly offer summary with 12-hour times."""
        slice0 = offer.get("slices", [{}])[0]
        segments = slice0.get("segments", [])
        stops = max(len(segments) - 1, 0)
        carrier = "Unknown airline"
        if segments:
            carrier = segments[0].get("operating_carrier", {}).get("name", "Unknown airline")
        first_seg = segments[0] if segments else {}
        last_seg = segments[-1] if segments else {}
        dep_raw = first_seg.get("departing_at", "")
        arr_raw = last_seg.get("arriving_at", "")
        dep = self._fmt_time_12h(dep_raw[11:16]) if len(dep_raw) >= 16 else "TBD"
        arr = self._fmt_time_12h(arr_raw[11:16]) if len(arr_raw) >= 16 else "TBD"
        price = offer.get("total_amount", "?")
        currency = offer.get("total_currency", "USD")
        stop_str = "Non-stop" if stops == 0 else f"{stops} stop{'s' if stops > 1 else ''}"
        return (
            f"Option {index}: {carrier}. "
            f"Departs at {dep}, arrives at {arr}. "
            f"{stop_str}. {currency} {price}."
        )

    def _book_flight(self, offer_id: str, passengers: list) -> dict:
        """Create Duffel order with type hold."""
        payload = {"data": {
            "type": "hold",
            "selected_offers": [offer_id],
            "passengers": passengers,
        }}
        self.worker.editor_logging_handler.info(f"[FlightBooking] Booking offer {offer_id}")
        resp = requests.post(
            f"{self.DUFFEL_BASE}/air/orders",
            headers=self._duffel_headers(),
            json=payload,
            timeout=30,
        )
        if not resp.ok:
            self.worker.editor_logging_handler.error(
                f"[FlightBooking] Duffel {resp.status_code} body: {resp.text}"
            )
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def _save_booking(self, order: dict, origin: str, dest: str, date: str):
        """Append booking to persistent flight_booking_history.json."""
        entry = {
            "booking_ref": order.get("booking_reference", ""),
            "order_id": order.get("id", ""),
            "origin": origin,
            "destination": dest,
            "date": date,
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        history = []
        exists = await self.capability_worker.check_if_file_exists(self.HISTORY_FILE, False)
        if exists:
            try:
                raw = await self.capability_worker.read_file(self.HISTORY_FILE, False)
                history = json.loads(raw)
            except Exception:
                history = []
            await self.capability_worker.delete_file(self.HISTORY_FILE, False)
        history.append(entry)
        await self.capability_worker.write_file(self.HISTORY_FILE, json.dumps(history, indent=2), False)
        self.worker.editor_logging_handler.info(f"[FlightBooking] Saved booking {entry['booking_ref']}")

    # -------------------------------------------------------------------------
    # Change routing helper (deduplicates the 3 copy-pasted change blocks)
    # -------------------------------------------------------------------------

    async def _ask_and_apply_change(self, date_str, dest_city, dest_iata, cabin):
        """Ask what the user wants to change and return updated (date_str, dest_city, dest_iata, cabin).
        Returns None if the user wants to exit."""
        what = await self.capability_worker.run_io_loop(
            "What would you like to change — the date, destination, or cabin class?"
        )
        if self._is_exit_intent(what):
            return None

        change_prompt = (
            f"The user said: '{what}'. They want to change something about their flight search. "
            "Reply with exactly one of: DATE, DESTINATION, CABIN, OTHER"
        )
        change_intent = self.capability_worker.text_to_text_response(change_prompt).strip().upper()
        self.worker.editor_logging_handler.info(f"[FlightBooking] Change intent: '{what}' → {change_intent}")

        if change_intent == "DATE":
            date_raw = await self.capability_worker.run_io_loop("What date would you prefer?")
            if self._is_exit_intent(date_raw):
                return None
            date_str = self._parse_date(date_raw)
        elif change_intent == "DESTINATION":
            new_dest = await self.capability_worker.run_io_loop("Where would you like to fly?")
            if self._is_exit_intent(new_dest):
                return None
            dest_iata = self._resolve_airport(new_dest)
            dest_city = self._normalize_city_name(new_dest, dest_iata)
        elif change_intent == "CABIN":
            cabin_raw = await self.capability_worker.run_io_loop("Economy, business, or first class?")
            if self._is_exit_intent(cabin_raw):
                return None
            cabin_lower = cabin_raw.lower()
            cabin = ("business" if "business" in cabin_lower else
                     "first" if "first" in cabin_lower else
                     "premium_economy" if "premium" in cabin_lower else "economy")

        return date_str, dest_city, dest_iata, cabin

    # -------------------------------------------------------------------------
    # Passenger Details Collection
    # -------------------------------------------------------------------------

    async def _collect_passenger_details(self, passenger_id: str):
        """Collect passenger details using grouped prompts with LLM extraction.
        Returns a dict on success, or None if the user exits."""

        # Group 1: full name + DOB in one prompt
        group1_raw = await self.capability_worker.run_io_loop(
            "I need a few details for the booking. "
            "What's the passenger's full name and date of birth? "
            "For example: John Smith, born March 5th 1990."
        )
        if self._is_exit_intent(group1_raw):
            return None

        g1 = self._extract_passenger_fields(
            group1_raw, ["given_name", "family_name", "born_on"]
        )
        given = g1.get("given_name")
        family = g1.get("family_name")
        dob = g1.get("born_on")

        # Fall back to individual asks only for fields that weren't extracted
        if not given:
            given = await self.capability_worker.run_io_loop("What's the passenger's first name?")
            if self._is_exit_intent(given):
                return None
        if not family:
            family = await self.capability_worker.run_io_loop("And the last name?")
            if self._is_exit_intent(family):
                return None
        if not dob:
            dob_raw = await self.capability_worker.run_io_loop(
                "Date of birth? For example, March 5th 1990."
            )
            if self._is_exit_intent(dob_raw):
                return None
            dob = self._parse_date(dob_raw)

        # Title (kept separate — categorical choice, not reliably extracted from free-form)
        title_raw = await self.capability_worker.run_io_loop(
            "What's your title? Mister, Missus, Miss, Ms, or Doctor?"
        )
        if self._is_exit_intent(title_raw):
            return None
        t = title_raw.lower().strip()
        if "mrs" in t or "missus" in t:
            title, gender = "mrs", "f"
        elif "miss" in t:
            title, gender = "miss", "f"
        elif "ms" in t:
            title, gender = "ms", "f"
        elif "dr" in t or "doctor" in t:
            title, gender = "dr", "m"
        else:
            title, gender = "mr", "m"

        # Group 2: email + phone in one prompt
        group2_raw = await self.capability_worker.run_io_loop(
            "And what's the email address and phone number, including country code?"
        )
        if self._is_exit_intent(group2_raw):
            return None

        g2 = self._extract_passenger_fields(group2_raw, ["email", "phone_number"])
        email = g2.get("email") or ""
        phone_clean = g2.get("phone_number") or ""

        # Validate email — re-ask once if invalid or missing
        email_clean = re.sub(r"[^\x00-\x7F]", "", email).strip().lower()
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email_clean):
            email_raw = await self.capability_worker.run_io_loop(
                "I didn't catch the email clearly. Please say it again."
            )
            if self._is_exit_intent(email_raw):
                return None
            email_clean = re.sub(r"[^\x00-\x7F]", "", email_raw).strip().lower()
        email = email_clean

        # Validate phone — re-ask once if blank after LLM extraction
        if not phone_clean:
            phone_raw = await self.capability_worker.run_io_loop(
                "And the phone number with country code? For example, plus 44 7700 900 123."
            )
            if self._is_exit_intent(phone_raw):
                return None
            phone_clean = self._parse_phone(phone_raw)

        given_clean = re.sub(r"[^a-zA-Z\s'\-]", "", given).strip().title()
        family_clean = re.sub(r"[^a-zA-Z\s'\-]", "", family).strip().title()

        details = {
            "id": passenger_id,
            "title": title,
            "gender": gender,
            "given_name": given_clean,
            "family_name": family_clean,
            "born_on": dob,
            "email": email,
            "phone_number": phone_clean,
        }
        self.worker.editor_logging_handler.info(
            f"[FlightBooking] Passenger: {details['given_name']} {details['family_name']} ({title})"
        )
        return details

    # -------------------------------------------------------------------------
    # Main Flow
    # -------------------------------------------------------------------------

    async def run_booking_flow(self):
        """Orchestrate the full flight search → select → book flow."""
        try:
            self.worker.editor_logging_handler.info("[FlightBooking] ✓ run_booking_flow started")

            # Step 1: Capture the full trigger utterance
            full_utterance = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[FlightBooking] Utterance: '{full_utterance}'")

            # Step 2: Try to extract details from the utterance
            extracted = {}
            if full_utterance and full_utterance.strip():
                extracted = self._extract_flight_details_from_utterance(full_utterance)
                self.worker.editor_logging_handler.info(f"[FlightBooking] Extracted: {extracted}")

            # Step 3: Fill in any missing details by asking
            origin_city = extracted.get("origin") or ""
            dest_city = extracted.get("destination") or ""
            date_str = extracted.get("date") or ""
            return_date_str = extracted.get("return_date") or ""
            trip_type = extracted.get("trip_type") or ""
            cabin = extracted.get("cabin") or "economy"

            if not origin_city:
                origin_city = await self.capability_worker.run_io_loop("Where are you flying from?")
                if self._is_exit_intent(origin_city):
                    await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                    self.capability_worker.resume_normal_flow()
                    return

            if not dest_city:
                dest_city = await self.capability_worker.run_io_loop("Where are you flying to?")
                if self._is_exit_intent(dest_city):
                    await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                    self.capability_worker.resume_normal_flow()
                    return

            if not date_str:
                date_raw = await self.capability_worker.run_io_loop(
                    "What date are you travelling? For example, March 20th."
                )
                if self._is_exit_intent(date_raw):
                    await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                    self.capability_worker.resume_normal_flow()
                    return
                date_str = self._parse_date(date_raw)

            # Validate date is not in the past
            try:
                if date_str < datetime.now().strftime("%Y-%m-%d"):
                    date_raw = await self.capability_worker.run_io_loop(
                        f"{self._format_date_natural(date_str)} is in the past. What date did you mean?"
                    )
                    if self._is_exit_intent(date_raw):
                        await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                        self.capability_worker.resume_normal_flow()
                        return
                    date_str = self._parse_date(date_raw)
            except Exception:
                pass

            if not trip_type:
                trip_raw = await self.capability_worker.run_io_loop("Is that one-way or round trip?")
                if self._is_exit_intent(trip_raw):
                    await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                    self.capability_worker.resume_normal_flow()
                    return
                trip_type = "round-trip" if any(
                    w in trip_raw.lower() for w in ["round", "return", "both"]
                ) else "one-way"

            if trip_type == "round-trip" and not return_date_str:
                return_raw = await self.capability_worker.run_io_loop("When are you returning?")
                if self._is_exit_intent(return_raw):
                    await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                    self.capability_worker.resume_normal_flow()
                    return
                return_date_str = self._parse_date(return_raw)

            if cabin not in ("economy", "business", "first", "premium_economy"):
                cabin_raw = await self.capability_worker.run_io_loop("Economy, business, or first class?")
                if self._is_exit_intent(cabin_raw):
                    await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                    self.capability_worker.resume_normal_flow()
                    return
                cabin_lower = cabin_raw.lower()
                cabin = ("business" if "business" in cabin_lower else
                         "first" if "first" in cabin_lower else
                         "premium_economy" if "premium" in cabin_lower else "economy")

            # Step 4: Resolve airport codes (with one retry each)
            origin_iata = self._resolve_airport(origin_city)
            if not origin_iata:
                retry_city = await self.capability_worker.run_io_loop(
                    "I didn't catch the departure city. Could you say it again?"
                )
                origin_iata = self._resolve_airport(retry_city)
                if origin_iata:
                    origin_city = retry_city

            dest_iata = self._resolve_airport(dest_city)
            if not dest_iata:
                retry_city = await self.capability_worker.run_io_loop(
                    "And the destination — could you say that city again?"
                )
                dest_iata = self._resolve_airport(retry_city)
                if dest_iata:
                    dest_city = retry_city

            if not origin_iata or not dest_iata:
                await self.capability_worker.speak(
                    "I'm still having trouble with those city names. Please try again."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Normalise city names for clean voice readback
            origin_city = self._normalize_city_name(origin_city, origin_iata)
            dest_city = self._normalize_city_name(dest_city, dest_iata)

            self.worker.editor_logging_handler.info(
                f"[FlightBooking] Route: {origin_iata}→{dest_iata}, date={date_str}, "
                f"return={return_date_str}, cabin={cabin}"
            )

            # Steps 5–8: Search + select + confirm (retryable loop)
            selected_offer = None
            passenger_details = None

            while True:
                await self.capability_worker.speak("Let me search for flights, one moment.")
                try:
                    offers = self._search_flights(
                        origin_iata, dest_iata, date_str,
                        return_date_str if trip_type == "round-trip" else "",
                        cabin,
                    )
                except Exception as e:
                    self.worker.editor_logging_handler.error(f"[FlightBooking] Search error: {e}")
                    await self.capability_worker.speak(
                        "Sorry, I couldn't reach the flight search service. Please try again."
                    )
                    self.capability_worker.resume_normal_flow()
                    return

                if not offers:
                    retry = await self.capability_worker.run_io_loop(
                        "No flights found for that route and date. "
                        "Would you like to change the date or destination?"
                    )
                    if self._is_exit_intent(retry) or not any(
                        w in retry.lower() for w in ["yes", "sure", "ok", "try", "change", "different"]
                    ):
                        await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                        self.capability_worker.resume_normal_flow()
                        return
                    result = await self._ask_and_apply_change(date_str, dest_city, dest_iata, cabin)
                    if result is None:
                        await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                        self.capability_worker.resume_normal_flow()
                        return
                    date_str, dest_city, dest_iata, cabin = result
                    continue

                # ── Single offer: skip selection, ask yes/no directly ──────────
                if len(offers) == 1:
                    offer_summary = self._format_offer(offers[0], 1).replace("Option 1: ", "")
                    confirm_search = await self.capability_worker.run_io_loop(
                        f"I found one flight: {offer_summary} "
                        "Would you like to book it? Or say no to change something."
                    )
                    if self._is_exit_intent(confirm_search):
                        await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                        self.capability_worker.resume_normal_flow()
                        return
                    yes_prompt = (
                        f"The user said: '{confirm_search}'. "
                        "Are they agreeing to book this flight? Reply ONLY with YES or NO."
                    )
                    if self.capability_worker.text_to_text_response(yes_prompt).strip().upper().startswith("Y"):
                        selected_offer = offers[0]
                    else:
                        result = await self._ask_and_apply_change(date_str, dest_city, dest_iata, cabin)
                        if result is None:
                            await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                            self.capability_worker.resume_normal_flow()
                            return
                        date_str, dest_city, dest_iata, cabin = result
                        continue

                else:
                    # ── Multiple offers: present numbered list ──────────────────
                    options_text = " ".join(self._format_offer(o, i + 1) for i, o in enumerate(offers))
                    option_range = "1 or 2" if len(offers) == 2 else "1, 2, or 3"
                    choice_raw = await self.capability_worker.run_io_loop(
                        f"{options_text} Which option — {option_range}? Or say none to change something."
                    )
                    if self._is_exit_intent(choice_raw):
                        await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                        self.capability_worker.resume_normal_flow()
                        return

                    none_prompt = (
                        f"The user said: '{choice_raw}'. "
                        "Are they saying none / neither / they don't want any of these options? "
                        "Reply ONLY with YES or NO."
                    )
                    if self.capability_worker.text_to_text_response(none_prompt).strip().upper().startswith("Y"):
                        result = await self._ask_and_apply_change(date_str, dest_city, dest_iata, cabin)
                        if result is None:
                            await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                            self.capability_worker.resume_normal_flow()
                            return
                        date_str, dest_city, dest_iata, cabin = result
                        continue

                    num_prompt = (
                        f"The user was given {len(offers)} flight option(s) and said: '{choice_raw}'. "
                        "Return ONLY the number 1, 2, or 3. Nothing else."
                    )
                    num_str = self.capability_worker.text_to_text_response(num_prompt).strip()
                    self.worker.editor_logging_handler.info(
                        f"[FlightBooking] User chose: '{choice_raw}' → '{num_str}'"
                    )
                    try:
                        idx = int(num_str) - 1
                        if not 0 <= idx < len(offers):
                            raise ValueError("out of range")
                    except Exception:
                        await self.capability_worker.speak("I didn't catch that. Please say 1, 2, or 3.")
                        self.capability_worker.resume_normal_flow()
                        return
                    selected_offer = offers[idx]

                # ── Step 7: Collect passenger details ──────────────────────────
                await self.capability_worker.speak("Great choice. I'll need a few details for the booking.")
                offer_passengers = selected_offer.get("passengers", [])
                passenger_id = offer_passengers[0].get("id", "") if offer_passengers else ""
                passenger_details = await self._collect_passenger_details(passenger_id)

                if passenger_details is None:
                    await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                    self.capability_worker.resume_normal_flow()
                    return

                # ── Step 8: Confirmation with change routing ────────────────────
                slice0 = selected_offer.get("slices", [{}])[0]
                segments = slice0.get("segments", [])
                carrier = (segments[0].get("operating_carrier", {}).get("name", "the airline")
                           if segments else "the airline")
                price = selected_offer.get("total_amount", "?")
                currency = selected_offer.get("total_currency", "USD")
                pax_name = f"{passenger_details['given_name']} {passenger_details['family_name']}"
                offer_id = selected_offer.get("id", "")

                confirm_raw = await self.capability_worker.run_io_loop(
                    f"Booking {carrier} from {origin_city} to {dest_city} "
                    f"on {self._format_date_natural(date_str)} for {pax_name}. "
                    f"Total {currency} {price}. "
                    "This holds the seat — payment must be completed before the airline's deadline. "
                    "Say confirm to book, cancel to stop, or tell me what you'd like to change."
                )

                routing_prompt = (
                    f"The user was asked to confirm a flight booking. They said: '{confirm_raw}'. "
                    "Reply with exactly one of these words:\n"
                    "CONFIRM - they want to go ahead\n"
                    "CANCEL - they want to stop\n"
                    "CHANGE_DATE - they want to change the travel date\n"
                    "CHANGE_DESTINATION - they want to change origin or destination\n"
                    "CHANGE_PASSENGER - they want to correct passenger details\n"
                    "CHANGE_CABIN - they want a different cabin class\n"
                    "Reply ONLY with one of these exact words."
                )
                intent = self.capability_worker.text_to_text_response(routing_prompt).strip().upper()
                self.worker.editor_logging_handler.info(f"[FlightBooking] Confirmation intent: {intent}")

                if intent == "CONFIRM":
                    break  # proceed to booking

                if intent == "CANCEL":
                    await self.capability_worker.speak(
                        "Booking cancelled. Let me know if you'd like to search again."
                    )
                    self.capability_worker.resume_normal_flow()
                    return

                if intent == "CHANGE_PASSENGER":
                    # Re-collect passenger details without re-searching
                    passenger_details = await self._collect_passenger_details(passenger_id)
                    if passenger_details is None:
                        await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                        self.capability_worker.resume_normal_flow()
                        return
                    continue  # loop back to confirmation with updated details

                # CHANGE_DATE / CHANGE_DESTINATION / CHANGE_CABIN → re-search
                if intent == "CHANGE_DATE":
                    date_raw = await self.capability_worker.run_io_loop("What date would you prefer?")
                    if self._is_exit_intent(date_raw):
                        await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                        self.capability_worker.resume_normal_flow()
                        return
                    date_str = self._parse_date(date_raw)
                elif intent == "CHANGE_DESTINATION":
                    dest_city = await self.capability_worker.run_io_loop(
                        "Where would you like to fly instead?"
                    )
                    if self._is_exit_intent(dest_city):
                        await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                        self.capability_worker.resume_normal_flow()
                        return
                    dest_iata = self._resolve_airport(dest_city)
                    dest_city = self._normalize_city_name(dest_city, dest_iata)
                elif intent == "CHANGE_CABIN":
                    cabin_raw = await self.capability_worker.run_io_loop("Economy, business, or first class?")
                    if self._is_exit_intent(cabin_raw):
                        await self.capability_worker.speak("No problem. Let me know if you need anything else.")
                        self.capability_worker.resume_normal_flow()
                        return
                    cabin_lower = cabin_raw.lower()
                    cabin = ("business" if "business" in cabin_lower else
                             "first" if "first" in cabin_lower else "economy")

                selected_offer = None
                passenger_details = None
                continue  # re-search with updated params

            # Step 9: Book
            await self.capability_worker.speak("Placing your hold booking now.")
            try:
                order = self._book_flight(offer_id, [passenger_details])
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[FlightBooking] Booking error: {e}")
                await self.capability_worker.speak(
                    "Sorry, the booking didn't go through. The flight may no longer be available. "
                    "Please try again."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Step 10: Save and confirm
            booking_ref = order.get("booking_reference", "")
            await self._save_booking(order, origin_iata, dest_iata, date_str)
            self.worker.editor_logging_handler.info(f"[FlightBooking] ✓ Booking complete ref={booking_ref}")

            pay_by_raw = (
                order.get("payment_required_by")
                or order.get("payment_status", {}).get("payment_required_by", "")
            )
            if pay_by_raw:
                pay_by_date = self._format_date_natural(pay_by_raw[:10])
                deadline_str = f" You must complete payment by {pay_by_date}."
            else:
                deadline_str = ""

            ref_spoken = ", ".join(list(booking_ref)) if booking_ref else "unavailable"
            self.worker.editor_logging_handler.info(
                f"[FlightBooking] pay_by_raw={pay_by_raw!r} deadline_str={deadline_str!r}"
            )
            await self.capability_worker.speak(
                f"Done! Your booking reference is {ref_spoken}.{deadline_str} "
                f"Please complete payment before the deadline to confirm your seat."
            )
            self.capability_worker.resume_normal_flow()

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[FlightBooking] Unhandled error: {e}")
            await self.capability_worker.speak("Sorry, something went wrong. Please try again.")
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.api_key = self.DUFFEL_API_KEY
        self.worker.editor_logging_handler.info("[FlightBooking] ✓ call() — starting run_booking_flow")
        self.worker.session_tasks.create(self.run_booking_flow())
