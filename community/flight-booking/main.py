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

    def _llm_classify(self, prompt: str) -> str:
        """Call LLM classifier and return stripped lowercase result."""
        return self.capability_worker.text_to_text_response(prompt).strip().lower()

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
            "This is a phone number. Convert it to E.164 format (e.g. +14155552671). "
            "If no country code was spoken, assume +1 (United States). "
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
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            d = dt.day
            sfx = "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
            return dt.strftime(f"%B {d}{sfx}")
        except Exception:
            return date_str

    def _format_time_ampm(self, raw_dt: str) -> str:
        """Convert ISO datetime string to 12-hour AM/PM time for voice readback."""
        try:
            t = raw_dt[11:16]
            dt = datetime.strptime(t, "%H:%M")
            return dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return raw_dt[11:16] if len(raw_dt) >= 16 else raw_dt

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
            f"airport serving: {city_or_code}. "
            "The input may be noisy speech transcription (e.g. 'I want to fly to new york' "
            "or 'new york city'). Extract the city and return ONLY the 3-letter IATA code. "
            "No explanation, no punctuation."
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
            '"trip_type": "one-way or round-trip or null", '
            '"cabin": "economy or business or first or premium_economy or null"}'
        )
        raw = self.capability_worker.text_to_text_response(prompt).strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
        try:
            return json.loads(raw)
        except Exception:
            return {}

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
        data = resp.json().get("data", {})
        offers = data.get("offers", [])
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
        dep = self._format_time_ampm(first_seg.get("departing_at", ""))
        arr = self._format_time_ampm(last_seg.get("arriving_at", ""))
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
    # Change-routing helper (used in search-retry loop)
    # -------------------------------------------------------------------------

    async def _ask_and_apply_change(self, date_str: str, dest_city: str,
                                    dest_iata: str, cabin: str):
        """Ask what the user wants to change and update the relevant parameter."""
        what = await self.capability_worker.run_io_loop(
            "What would you like to change — the date, destination, or cabin class?"
        )
        answer = self._llm_classify(
            f"The user said: '{what}'. Are they changing the DATE, DESTINATION, or CABIN CLASS? "
            "Reply ONLY with one word: DATE, DESTINATION, or CABIN."
        )
        if "date" in answer:
            date_raw = await self.capability_worker.run_io_loop("What date would you prefer?")
            date_str = self._parse_date(date_raw)
        elif "destination" in answer:
            dest_city = await self.capability_worker.run_io_loop("Where would you like to fly?")
            dest_iata = self._resolve_airport(dest_city)
            dest_city = self._normalize_city_name(dest_city, dest_iata)
        else:
            cabin_raw = await self.capability_worker.run_io_loop(
                "Economy, business, or first class?"
            )
            cabin_lower = cabin_raw.lower()
            cabin = (
                "business" if "business" in cabin_lower else
                "first" if "first" in cabin_lower else
                "premium_economy" if "premium" in cabin_lower else
                "economy"
            )
        return date_str, dest_city, dest_iata, cabin

    # -------------------------------------------------------------------------
    # Passenger Details Collection
    # -------------------------------------------------------------------------

    async def _collect_passenger_details(self, passenger_id: str) -> dict:
        """Ask for passenger details with a combined prompt; re-ask only for null fields."""
        # One combined prompt — user can answer everything at once
        combined = await self.capability_worker.run_io_loop(
            "I need a few details. Please say your full name, date of birth, "
            "email address, and phone number with country code."
        )
        today = datetime.now().strftime("%Y-%m-%d")
        extract_prompt = (
            f"Today is {today}. The user said: '{combined}'.\n"
            "Extract passenger details. Return ONLY valid JSON with these exact keys "
            "(use null for any field not mentioned):\n"
            '{"given_name": null, "family_name": null, '
            '"born_on": "YYYY-MM-DD or null", "email": null, "phone": null}'
        )
        raw = self.capability_worker.text_to_text_response(extract_prompt).strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
        extracted = {}
        try:
            extracted = json.loads(raw)
        except Exception:
            pass

        given = extracted.get("given_name") or None
        family = extracted.get("family_name") or None
        dob = extracted.get("born_on") or None
        email_raw = extracted.get("email") or None
        phone_raw = extracted.get("phone") or None

        # Re-ask individually for any field still missing
        if not given:
            given = await self.capability_worker.run_io_loop("What's the passenger's first name?")
        if not family:
            family = await self.capability_worker.run_io_loop("And the last name?")
        if not dob:
            dob_raw = await self.capability_worker.run_io_loop(
                "Date of birth? For example, March 5th 1990."
            )
            dob = self._parse_date(dob_raw)
        else:
            # dob came from LLM extraction — validate it looks like a date
            if not re.match(r"\d{4}-\d{2}-\d{2}", str(dob)):
                dob = self._parse_date(str(dob))

        if not email_raw:
            email_raw = await self.capability_worker.run_io_loop("Email address?")
        email_clean = re.sub(r"[^\x00-\x7F]", "", email_raw).strip().lower()
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email_clean):
            email_raw = await self.capability_worker.run_io_loop(
                "I didn't catch that clearly. Please spell out your email address."
            )
            email_clean = re.sub(r"[^\x00-\x7F]", "", email_raw).strip().lower()

        if not phone_raw:
            phone_raw = await self.capability_worker.run_io_loop(
                "Phone number with country code? For example, plus 1 and then your ten-digit number."
            )
        phone_clean = self._parse_phone(str(phone_raw))

        # Title — separate question with LLM classifier (TTS-friendly phrasing)
        title_raw = await self.capability_worker.run_io_loop(
            "Are you Mister, Missus, Miss, or Doctor?"
        )
        title_answer = self._llm_classify(
            f"The user said: '{title_raw}'. Which title are they choosing? "
            "Reply ONLY with one of: mr, mrs, miss, ms, dr."
        )
        if "mrs" in title_answer:
            title, gender = "mrs", "f"
        elif "miss" in title_answer:
            title, gender = "miss", "f"
        elif "ms" in title_answer:
            title, gender = "ms", "f"
        elif "dr" in title_answer:
            title, gender = "dr", "m"
        else:
            title, gender = "mr", "m"

        given_clean = re.sub(r"[^a-zA-Z\s'\-]", "", str(given)).strip().title()
        family_clean = re.sub(r"[^a-zA-Z\s'\-]", "", str(family)).strip().title()

        details = {
            "id": passenger_id,
            "title": title,
            "gender": gender,
            "given_name": given_clean,
            "family_name": family_clean,
            "born_on": dob,
            "email": email_clean,
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

            # Step 3: Fill in missing details
            origin_city = extracted.get("origin") or ""
            dest_city = extracted.get("destination") or ""
            date_str = extracted.get("date") or ""
            return_date_str = extracted.get("return_date") or ""
            trip_type = extracted.get("trip_type") or ""
            cabin = extracted.get("cabin") or "economy"

            # Catch-all: if 2+ core fields are missing, ask one combined question first
            null_count = sum(1 for v in [origin_city, dest_city, date_str] if not v)
            if null_count >= 2:
                catch_all = await self.capability_worker.run_io_loop(
                    "Where are you flying, and when?"
                )
                extra = self._extract_flight_details_from_utterance(catch_all)
                origin_city = origin_city or extra.get("origin") or ""
                dest_city = dest_city or extra.get("destination") or ""
                date_str = date_str or extra.get("date") or ""
                trip_type = trip_type or extra.get("trip_type") or ""
                return_date_str = return_date_str or extra.get("return_date") or ""

            # Individual fallback prompts for any still-missing fields
            if not origin_city:
                origin_city = await self.capability_worker.run_io_loop(
                    "Where are you flying from?"
                )
            if not dest_city:
                dest_city = await self.capability_worker.run_io_loop(
                    "Where are you flying to?"
                )
            if not date_str:
                date_raw = await self.capability_worker.run_io_loop(
                    "What date are you travelling? For example, March 20th."
                )
                date_str = self._parse_date(date_raw)

            # Validate date is not in the past
            try:
                if date_str < datetime.now().strftime("%Y-%m-%d"):
                    date_raw = await self.capability_worker.run_io_loop(
                        f"{self._format_date_natural(date_str)} is in the past. What date did you mean?"
                    )
                    date_str = self._parse_date(date_raw)
            except Exception:
                pass

            if not trip_type:
                trip_raw = await self.capability_worker.run_io_loop(
                    "Is that one-way or round trip?"
                )
                answer = self._llm_classify(
                    f"The user said: '{trip_raw}'. Are they booking a one-way or round-trip flight? "
                    "Reply ONLY with ONE-WAY or ROUND-TRIP."
                )
                trip_type = "round-trip" if "round" in answer else "one-way"

            if trip_type == "round-trip" and not return_date_str:
                return_raw = await self.capability_worker.run_io_loop(
                    "When are you returning?"
                )
                return_date_str = self._parse_date(return_raw)

            if cabin not in ("economy", "business", "first", "premium_economy"):
                cabin_raw = await self.capability_worker.run_io_loop(
                    "Economy, business, or first class?"
                )
                cabin_lower = cabin_raw.lower()
                if "business" in cabin_lower:
                    cabin = "business"
                elif "first" in cabin_lower:
                    cabin = "first"
                elif "premium" in cabin_lower:
                    cabin = "premium_economy"
                else:
                    cabin = "economy"

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

            # Steps 5–6: Search + present options (retryable loop)
            selected_offer = None
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
                    answer = self._llm_classify(
                        f"The user said: '{retry}'. Did they agree to change their search? "
                        "Reply ONLY with YES or NO."
                    )
                    if answer.startswith("yes"):
                        date_str, dest_city, dest_iata, cabin = await self._ask_and_apply_change(
                            date_str, dest_city, dest_iata, cabin
                        )
                        continue
                    await self.capability_worker.speak(
                        "No problem. Let me know if you need anything else."
                    )
                    self.capability_worker.resume_normal_flow()
                    return

                # ── Single offer: skip selection, ask yes/no directly ──────────
                if len(offers) == 1:
                    offer_summary = self._format_offer(offers[0], 1).replace("Option 1: ", "")
                    confirm_search = await self.capability_worker.run_io_loop(
                        f"I found one flight: {offer_summary} "
                        "Would you like to book it? Or say no to change something."
                    )
                    answer = self._llm_classify(
                        f"The user said: '{confirm_search}'. "
                        "Do they want to book this flight? Reply ONLY with YES or NO."
                    )
                    if answer.startswith("yes"):
                        selected_offer = offers[0]
                        break
                    date_str, dest_city, dest_iata, cabin = await self._ask_and_apply_change(
                        date_str, dest_city, dest_iata, cabin
                    )
                    continue

                # ── Multiple offers: progressive reveal ─────────────────────────
                await self.capability_worker.speak(self._format_offer(offers[0], 1))
                await self.capability_worker.speak(self._format_offer(offers[1], 2))

                if len(offers) == 3:
                    want_more = await self.capability_worker.run_io_loop(
                        "Want to hear the third option, or go with one of those?"
                    )
                    want_ans = self._llm_classify(
                        f"The user said: '{want_more}'. "
                        "Do they want to hear the third option? Reply ONLY with YES or NO."
                    )
                    if want_ans.startswith("yes"):
                        await self.capability_worker.speak(self._format_offer(offers[2], 3))
                    else:
                        offers = offers[:2]

                option_range = "1 or 2" if len(offers) == 2 else "1, 2, or 3"
                choice_raw = await self.capability_worker.run_io_loop(
                    f"Which option — {option_range}? Or say none to change something."
                )

                change_answer = self._llm_classify(
                    f"The user said: '{choice_raw}'. "
                    "Do they want to change something instead of choosing a flight option? "
                    "Reply ONLY with YES or NO."
                )
                if change_answer.startswith("yes"):
                    date_str, dest_city, dest_iata, cabin = await self._ask_and_apply_change(
                        date_str, dest_city, dest_iata, cabin
                    )
                    continue

                # Extract choice number via LLM
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
                break

            offer_id = selected_offer.get("id", "")
            offer_passengers = selected_offer.get("passengers", [])
            passenger_id = offer_passengers[0].get("id", "") if offer_passengers else ""

            # Step 7: Collect passenger details
            await self.capability_worker.speak(
                "Great choice. I just need a few details for the booking."
            )
            passenger_details = await self._collect_passenger_details(passenger_id)

            # Step 8: Confirmation (~28 words, TTS-friendly)
            slice0 = selected_offer.get("slices", [{}])[0]
            segments = slice0.get("segments", [])
            carrier = (
                segments[0].get("operating_carrier", {}).get("name", "the airline")
                if segments else "the airline"
            )
            price = selected_offer.get("total_amount", "?")
            currency = selected_offer.get("total_currency", "USD")
            pax_name = f"{passenger_details['given_name']} {passenger_details['family_name']}"

            confirmed = await self.capability_worker.run_confirmation_loop(
                f"Confirm: {carrier}, {origin_city} to {dest_city}, "
                f"{self._format_date_natural(date_str)}, {currency} {price} for {pax_name}. "
                f"This is a hold — you'll pay later. Shall I book it?"
            )

            if not confirmed:
                await self.capability_worker.speak(
                    "Booking cancelled. Let me know if you want to search again."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Step 9: Book (with one retry on failure)
            await self.capability_worker.speak("Placing your hold booking now.")
            order = None
            for attempt in range(2):
                try:
                    order = self._book_flight(offer_id, [passenger_details])
                    break
                except Exception as e:
                    self.worker.editor_logging_handler.error(
                        f"[FlightBooking] Booking error (attempt {attempt + 1}): {e}"
                    )
                    if attempt == 0:
                        retry_ans = await self.capability_worker.run_io_loop(
                            "Sorry, I couldn't complete that booking. Want me to try again?"
                        )
                        retry_classify = self._llm_classify(
                            f"The user said: '{retry_ans}'. Do they want to retry? "
                            "Reply ONLY with YES or NO."
                        )
                        if not retry_classify.startswith("yes"):
                            self.capability_worker.resume_normal_flow()
                            return
                    else:
                        await self.capability_worker.speak(
                            "Sorry, the booking still didn't go through. Please try again later."
                        )
                        self.capability_worker.resume_normal_flow()
                        return

            # Step 10: Save and confirm
            booking_ref = order.get("booking_reference", "")
            await self._save_booking(order, origin_iata, dest_iata, date_str)
            self.worker.editor_logging_handler.info(
                f"[FlightBooking] ✓ Booking complete ref={booking_ref}"
            )

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
                f"A payment link will be sent to your email address. "
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
