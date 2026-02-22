from typing import ClassVar, Set, Dict, Any
import json
import os
from datetime import datetime
import requests
import re

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


COMPOSIO_API_KEY           = "ak_xxx" #Your api key
COMPOSIO_USER_ID           = "pg-test-xxxxxxxx" #Your user id
COMPOSIO_CONNECTED_ACCOUNT_ID = "ca_xxxx" #Your account i
COMPOSIO_BASE_URL          = "https://backend.composio.dev/api/v3"


class FlightInformationEmailCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    AMADEUS_API_KEY: ClassVar[str] = "YOUR_API_KEY"
    AMADEUS_API_SECRET: ClassVar[str] = "YOUR_API_SECRET"

    MONTH_MAP: ClassVar[Dict[str, int]] = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }

    COMMON_IATA: ClassVar[Dict[str, str]] = {
        "dhaka": "DAC", "dheka": "DAC", "dhaga": "DAC", "dha": "DAC", "dhka": "DAC",
        "ढाका": "DAC", "धाका": "DAC", "dhaka bangladesh": "DAC",
        "bangkok": "BKK", "बैंकोक": "BKK", "बैंकाक": "BKK", "bankok": "BKK",
        "singapore": "SIN", "singapur": "SIN", "सिंगापुर": "SIN", "सिंगापोर": "SIN",
        "dilli": "DEL", "delhi": "DEL", "new delhi": "DEL",
    }

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as file:
            data = json.load(file)
        return cls(unique_name=data["unique_name"], matching_hotwords=data["matching_hotwords"])

    PREFS_FILE: ClassVar[str] = "flight_email_prefs.json"

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            prefs = await self.load_prefs()

            prefs["amadeus_api_key"] = self.AMADEUS_API_KEY
            prefs["amadeus_api_secret"] = self.AMADEUS_API_SECRET
            prefs["amadeus_env"] = "test"
            await self.save_prefs(prefs)

            if not prefs.get("email_address"):
                await self.setup_email(prefs)

            history = self.worker.agent_memory.full_message_history
            trigger_text = ""
            if history:
                last_msg = history[-1]
                if isinstance(last_msg, dict):
                    trigger_text = last_msg.get("content", "")
                elif hasattr(last_msg, "content"):
                    trigger_text = last_msg.content
                else:
                    trigger_text = str(last_msg)

            lower_text = trigger_text.lower().strip()

            send_indicators = [
                "send", "mail", "email", "sent", "please send", "send please", "send it",
                "send this", "send that", "send those", "send details", "send the",
                "send my", "in my email", "to my email", "email me", "mail me",
                "send email", "send to email", "email those", "mail those", "yes send",
                "sure send", "ok send", "go ahead send", "send those details", "please mail",
                "just send", "send in my email", "those in my email", "sent those", "sent dos",
                "same in my email", "send same", "mail those details", "email the details"
            ]

            is_email_mode = any(ind in lower_text for ind in send_indicators)

            # Strong override: any short "yes" reply → send
            if "yes" in lower_text and len(lower_text.split()) <= 5:
                is_email_mode = True

            # Extra safety for "yes" + send context
            if "yes" in lower_text and ("send" in lower_text or "email" in lower_text or "mail" in lower_text):
                is_email_mode = True

            if is_email_mode:
                await self.handle_email(prefs)
            else:
                await self.handle_search(trigger_text, prefs)

        except Exception as e:
            await self.capability_worker.speak("Something went wrong. Try again?")

        finally:
            self.capability_worker.resume_normal_flow()

    async def load_prefs(self) -> Dict:
        prefs = {
            "amadeus_api_key": "", "amadeus_api_secret": "", "amadeus_env": "test",
            "email_address": "", "home_airport": "",
            "preferred_currency": "USD", "default_passengers": 1, "prefer_nonstop": False,
            "last_search": {}, "iata_cache": {}
        }
        if await self.capability_worker.check_if_file_exists(self.PREFS_FILE):
            raw = await self.capability_worker.read_file(self.PREFS_FILE)
            loaded = json.loads(raw)
            prefs.update(loaded)
        return prefs

    async def save_prefs(self, prefs: Dict):
        if await self.capability_worker.check_if_file_exists(self.PREFS_FILE):
            await self.capability_worker.delete_file(self.PREFS_FILE)
        await self.capability_worker.write_file(self.PREFS_FILE, json.dumps(prefs))

    async def setup_email(self, prefs: Dict):
        await self.capability_worker.speak("What email address should I send flight details to?")
        email = await self.capability_worker.user_response()
        prefs["email_address"] = email.strip()
        await self.save_prefs(prefs)
        await self.capability_worker.speak("Saved. Now say 'flight information from Dhaka to Bangkok' to search.")

    async def get_amadeus_token(self, prefs: Dict) -> str:
        url = "https://test.api.amadeus.com/v1/security/oauth2/token" if prefs["amadeus_env"] == "test" else "https://api.amadeus.com/v1/security/oauth2/token"
        data = {"grant_type": "client_credentials", "client_id": prefs["amadeus_api_key"], "client_secret": prefs["amadeus_api_secret"]}
        response = requests.post(url, data=data)
        if response.status_code != 200:
            raise Exception(f"Token failed: {response.status_code}")
        return response.json()["access_token"]

    async def search_iata(self, keyword: str, prefs: Dict, token: str) -> str:
        key = re.sub(r'[^a-z]', '', keyword.lower().strip())
        if key in self.COMMON_IATA:
            return self.COMMON_IATA[key]

        alpha = re.sub(r'[^a-z]', '', key)
        if len(alpha) >= 3:
            return alpha[:3].upper()

        return keyword.upper()[:3]

    def sanitize_date(self, date_str: str, current_year: int, current_month: int, current_day: int) -> str:
        if not date_str:
            return f"{current_year:04d}-{current_month:02d}-{current_day:02d}"

        date_str = date_str.lower().strip()
        date_str = re.sub(r'[^a-z0-9\s\-]', '', date_str)

        for month_name, month_num in self.MONTH_MAP.items():
            if month_name in date_str:
                date_str = date_str.replace(month_name, str(month_num))
                break

        numbers = re.findall(r'\d+', date_str)
        if len(numbers) >= 2:
            a, b = int(numbers[0]), int(numbers[1])
            if 1 <= a <= 12 and 1 <= b <= 31:
                month, day = a, b
            elif 1 <= b <= 12 and 1 <= a <= 31:
                month, day = b, a
            else:
                month, day = current_month, current_day
        elif len(numbers) == 1:
            day = int(numbers[0])
            month = current_month
        else:
            month, day = current_month, current_day

        return f"{current_year:04d}-{month:02d}-{day:02d}"

    async def handle_search(self, trigger_text: str, prefs: Dict):
        today = datetime.now()
        current_year = today.year
        current_month = today.month
        current_day = today.day

        parse_prompt = f"""Today's date is {today.strftime('%Y-%m-%d')}.

Extract origin, destination, departure date from the user's message.

Rules:
- origin and destination: city names only
- departure_date: strict YYYY-MM-DD or "ASK_DATE" if not clearly provided
- If year missing, use {current_year}
- If month/day missing or date vague, return "ASK_DATE"
- Only use today's date if user explicitly says "today" or "now"

User said: "{trigger_text}"

Return ONLY valid JSON:
{{
  "origin": "city name or empty string",
  "destination": "city name or empty string",
  "departure_date": "YYYY-MM-DD or ASK_DATE",
  "return_date": "YYYY-MM-DD or null",
  "nonstop": true/false,
  "passengers": number
}}"""

        raw = self.capability_worker.text_to_text_response(parse_prompt)
        raw = raw.replace("```json", "").replace("```", "").strip()
        try:
            params = json.loads(raw)
            departure_date_raw = params.get("departure_date", "")
            if departure_date_raw == "ASK_DATE" or not departure_date_raw:
                departure_date = None
            else:
                departure_date = self.sanitize_date(departure_date_raw, current_year, current_month, current_day)
        except Exception:
            params = {}
            departure_date = None

        origin = params.get("origin") or ""
        dest = params.get("destination") or ""

        origin_display = self.get_display_name(origin)
        dest_display = self.get_display_name(dest)

        return_date = params.get("return_date")
        nonstop_raw = params.get("nonstop", prefs.get("prefer_nonstop", False))
        nonstop = bool(nonstop_raw) if str(nonstop_raw).lower() in ['true', '1', 'yes'] else False
        passengers = int(params.get("passengers", prefs.get("default_passengers", 1)) or 1)

        if not departure_date:
            await self.capability_worker.speak("When do you want to depart?")
            date_response = await self.capability_worker.user_response()
            departure_date = self.sanitize_date(date_response, current_year, current_month, current_day)

        if not origin:
            await self.capability_worker.speak("Where are you flying from?")
            origin = await self.capability_worker.user_response() or prefs.get("home_airport") or ""
            origin_display = self.get_display_name(origin)

        if not dest:
            await self.capability_worker.speak("Where to?")
            dest = await self.capability_worker.user_response() or ""
            dest_display = self.get_display_name(dest)

        if origin.lower() == dest.lower():
            await self.capability_worker.speak("Origin and destination are the same. Please choose different cities.")
            return

        token = await self.get_amadeus_token(prefs)
        origin_iata = await self.search_iata(origin, prefs, token)
        dest_iata = await self.search_iata(dest, prefs, token)

        if origin_iata == dest_iata:
            await self.capability_worker.speak("Origin and destination airports are the same. Please choose different cities.")
            return

        base_url = "https://test.api.amadeus.com" if prefs["amadeus_env"] == "test" else "https://api.amadeus.com"
        url = f"{base_url}/v2/shopping/flight-offers"
        params = {
            "originLocationCode": origin_iata,
            "destinationLocationCode": dest_iata,
            "departureDate": departure_date,
            "adults": passengers,
            "currencyCode": prefs["preferred_currency"],
            "max": 6
        }
        if nonstop:
            params["nonStop"] = True

        if return_date:
            params["returnDate"] = return_date

        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            if response.status_code != 200:
                await self.capability_worker.speak("Sorry, couldn't find flights right now. Try different dates or cities?")
                prefs["last_search"] = {
                    "origin": origin_iata,
                    "destination": dest_iata,
                    "departure_date": departure_date,
                    "return_date": return_date,
                    "results": []
                }
                await self.save_prefs(prefs)
                await self.handle_email(prefs)
                return
            data = response.json()
            offers = data.get("data", [])[:3]
        except Exception:
            await self.capability_worker.speak("Flight search failed. Try again?")
            return

        if not offers:
            await self.capability_worker.speak("No flights found for those dates. Want to try different dates?")
            prefs["last_search"] = {
                "origin": origin_iata,
                "destination": dest_iata,
                "departure_date": departure_date,
                "return_date": return_date,
                "results": []
            }
            await self.save_prefs(prefs)
            await self.handle_email(prefs)
            return

        spoken = f"Found flights from {origin_display} to {dest_display} on {departure_date}. Top options:"
        for i, offer in enumerate(offers, 1):
            price = offer["price"]["grandTotal"]
            currency = offer["price"]["currency"]
            itinerary = offer["itineraries"][0]
            duration = itinerary["duration"].replace("PT", "").replace("H", " hours ").replace("M", " minutes")
            stops = len(itinerary["segments"]) - 1
            stops_str = "nonstop" if stops == 0 else f"{stops} stop"
            carrier = offer["validatingAirlineCodes"][0]
            spoken += f" {i}: {carrier}, {price} {currency}, {stops_str}, {duration}."

        await self.capability_worker.speak(spoken)
        await self.capability_worker.speak("Shall I send this to your email?")

        prefs["last_search"] = {
            "origin": origin_iata,
            "destination": dest_iata,
            "departure_date": departure_date,
            "return_date": return_date,
            "results": offers
        }
        await self.save_prefs(prefs)

    def get_display_name(self, code_or_name: str) -> str:
        code = code_or_name.upper()
        if len(code) == 3 and code.isalpha():
            return code
        return code_or_name.title()

    def send_via_composio(self, to_email: str, subject: str, body: str) -> bool:
        to_email = re.sub(r'[.,!?;:\s]+$', '', to_email.strip())

        url = f"{COMPOSIO_BASE_URL}/tools/execute/GMAIL_SEND_EMAIL"

        payload = {
            "user_id": COMPOSIO_USER_ID,
            "connected_account_id": COMPOSIO_CONNECTED_ACCOUNT_ID,
            "arguments": {
                "recipient_email": to_email,
                "subject": subject,
                "body": body
            }
        }

        headers = {
            "x-api-key": COMPOSIO_API_KEY,
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code not in (200, 201):
                return False

            data = response.json()
            return data.get("successful", False) is True
        except Exception:
            return False

    async def handle_email(self, prefs: Dict):
        last = prefs.get("last_search", {})
        if not last.get("origin") and not last.get("destination"):
            await self.capability_worker.speak("No recent flight search saved. Try searching first.")
            return

        offers = last.get("results", [])
        origin_iata = last.get("origin", "Unknown")
        dest_iata = last.get("destination", "Unknown")
        date = last.get("departure_date", datetime.now().strftime("%Y-%m-%d"))

        origin_display = origin_iata if len(origin_iata) == 3 else origin_iata.title()
        dest_display = dest_iata if len(dest_iata) == 3 else dest_iata.title()

        to_email = prefs.get("email_address", "")

        if not to_email:
            await self.capability_worker.speak("What email address should I send this to?")
            to_email = await self.capability_worker.user_response()
            prefs["email_address"] = to_email.strip()
            await self.save_prefs(prefs)

        body_lines = [
            f"Flight Options: {origin_display} → {dest_display} on {date}",
            f"Generated at {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]

        if not offers:
            body_lines.append("No flights found for the selected dates and route.")
            body_lines.append("Please try different dates or check airline websites directly.")
        else:
            body_lines.append("Top options:")
            for i, offer in enumerate(offers, 1):
                price = offer["price"]["grandTotal"]
                currency = offer["price"]["currency"]
                itinerary = offer["itineraries"][0]
                duration = itinerary["duration"].replace("PT", "").replace("H", " hours ").replace("M", " minutes")
                stops = len(itinerary["segments"]) - 1
                stops_str = "Nonstop" if stops == 0 else f"{stops} stop"
                carrier = offer["validatingAirlineCodes"][0]
                body_lines.append(f"{i}. {carrier} – {price} {currency} – {stops_str} – {duration}")

        body_lines.append("")
        body_lines.append("Booking links (live prices):")
        body_lines.append(f"• Google Flights → https://www.google.com/travel/flights?q=Flights+from+{origin_display}+to+{dest_display}+on+{date}")
        body_lines.append(f"• Kayak → https://www.kayak.com/flights/{origin_display}-{dest_display}/{date.replace('-','')}?sort=bestflight_a")
        body_lines.append("")
        body_lines.append("Prices change quickly — check soon if interested. Safe travels!")

        body_text = "\n".join(body_lines)
        subject = f"Flight Options: {origin_display} → {dest_display} on {date}"

        success = self.send_via_composio(to_email, subject, body_text)

        if success:
            await self.capability_worker.speak(
                f"Email sent to {to_email}! Check your inbox shortly. Safe travels!"
            )
        else:
            await self.capability_worker.speak(
                "Couldn't send the email right now — sorry. Let me read the details aloud instead."
            )
            spoken_text = body_text[:1200] + " ...and more. Want me to repeat anything?"
            await self.capability_worker.speak(spoken_text)