import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# TRAFFIC & TRAVEL TIME
# Voice-powered traffic and travel time checker using Google Maps Routes API.
# Check live traffic, get travel times, plan departures, and manage saved
# locations — all by voice. BYOK pattern (user provides their own Google
# Maps API key).
#
# Modes:
#   - quick_check      — "How long to work?" (saved location + live traffic)
#   - custom_route     — "How long from downtown to the beach?"
#   - departure_plan   — "When should I leave to arrive by 6?"
#   - commute          — "How's my commute?" (home↔work shortcut)
#   - save_location    — "Save work as 456 Corporate Dr"
#
# APIs used:
#   - Google Maps Routes API (primary)
#   - Google Maps Distance Matrix API (fallback)
#   - Google Maps Geocoding API (address resolution fallback)
# =============================================================================

PREFS_FILE = "traffic_prefs.json"

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

MAX_SAVED_LOCATIONS = 20

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye",
    "leave", "nothing else", "all good", "nope", "no thanks",
    "i'm good", "that's it", "that's all",
}

TRIGGER_PHRASES = {
    "check traffic", "traffic", "travel time", "how long to get to",
    "traffic to", "how far is", "drive time", "commute check",
    "how's my commute", "check traffic.", "how's traffic",
}

CLOUD_INDICATORS = [
    "amazon", "aws", "google", "microsoft", "azure",
    "digitalocean", "linode", "vultr", "hetzner",
]

IP_GEO_URL = "http://ip-api.com/json/{ip}"

# -- LLM Prompts --------------------------------------------------------------

CLASSIFY_PROMPT = (
    "Classify this travel/traffic voice command. "
    "Return ONLY valid JSON. No markdown fences.\n"
    '{{\n'
    '  "mode": "quick_check|custom_route|departure_plan|commute|'
    'save_location|trip_status",\n'
    '  "origin": "<string or null>",\n'
    '  "destination": "<string or null>",\n'
    '  "arrival_time": "<HH:MM or null>",\n'
    '  "departure_time": "<HH:MM or null (null = now)>",\n'
    '  "location_name": "<name to save as, or null>",\n'
    '  "address": "<address to save, or null>"\n'
    '}}\n\n'
    "Rules:\n"
    '- "how long to work" -> quick_check, destination="work"\n'
    '- "how long to the airport" -> quick_check, destination="airport"\n'
    '- "how\'s my commute" -> commute\n'
    '- "how long from Bole to Piassa" -> custom_route, origin="Bole", '
    'destination="Piassa"\n'
    '- "from downtown to the beach" -> custom_route\n'
    '- "distance from home to work" -> custom_route\n'
    '- "time from X to Y" -> custom_route\n'
    '- "how far from here to the market" -> custom_route\n'
    '- "when should I leave to arrive by 6" -> departure_plan\n'
    '- "what time should I leave for work" -> departure_plan\n'
    '- "save work as 456 Corporate Dr" -> save_location\n'
    '- "my home address is 123 Main St" -> save_location\n'
    '- "how much is left" -> trip_status\n'
    '- "how far have I gone" -> trip_status\n'
    '- "where am I" -> trip_status\n'
    '- "how much longer" -> trip_status\n'
    '- "remaining time" -> trip_status\n'
    '- If origin is "here"/"current location"/"my location"/"where I am", '
    'set origin to "current"\n'
    '- If no origin given for quick_check, origin is null\n\n'
    "Saved locations the user has: {saved_names}\n\n"
    "User said: {user_input}"
)

ADDRESS_CLEANUP_PROMPT = (
    "The user spoke an address via voice. STT may have garbled it. "
    "Clean up the transcription into a valid address. "
    "Fix common STT errors:\n"
    "  'one twenty three' -> '123'\n"
    "  'main street' -> 'Main St'\n"
    "  'los angeles california' -> 'Los Angeles, CA'\n"
    "Return ONLY valid JSON. No markdown fences.\n"
    '{{\n'
    '  "cleaned_address": "<string>",\n'
    '  "confidence": <0.0-1.0>\n'
    '}}\n\n'
    "Spoken address: {address}"
)

TRAFFIC_RESPONSE_PROMPT = (
    "Generate a natural, concise voice response for a traffic/travel time result. "
    "Keep it to 1-2 sentences. Round times naturally. "
    "Only mention baseline when traffic adds significant delay (>25% longer). "
    "Include route name if available.\n\n"
    "Data:\n"
    "- Destination: {destination}\n"
    "- Duration with traffic: {duration}\n"
    "- Duration without traffic: {static_duration}\n"
    "- Distance: {distance}\n"
    "- Route: {route_name}\n"
    "- Traffic severity: {severity}\n"
    "- Delay minutes: {delay_minutes}\n\n"
    "Generate a spoken response:"
)

DEPARTURE_RESPONSE_PROMPT = (
    "Generate a natural voice response for a departure time recommendation. "
    "Keep it to 1-2 sentences. Speak time naturally (e.g., 'Leave by 2:05').\n\n"
    "Data:\n"
    "- Destination: {destination}\n"
    "- Desired arrival: {arrival_time}\n"
    "- Travel time with traffic: {duration} minutes\n"
    "- Recommended departure: {departure_time}\n\n"
    "Generate a spoken response:"
)

TRIP_STATUS_PROMPT = (
    "Generate a natural voice response for a mid-trip status update. "
    "Keep it to 1-2 sentences.\n\n"
    "Data:\n"
    "- Traveling from: {origin}\n"
    "- Heading to: {destination}\n"
    "- Current remaining time with traffic: {remaining_duration}\n"
    "- Remaining distance: {remaining_distance}\n"
    "- Traffic severity: {severity}\n\n"
    "Generate a spoken response:"
)


class TrafficTravelTimeCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    prefs: dict = None
    _ip_location: dict = None
    _current_location: str = None
    _last_origin: str = None
    _last_destination: str = None
    _last_dest_name: str = None

    # {{register capability}}  # noqa: E265

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.prefs = await self.load_prefs()
            api_key = self.prefs.get("api_key", "")

            # First-run: need API key
            if not api_key or api_key == "YOUR_GOOGLE_MAPS_API_KEY":
                await self.handle_api_key_setup()
                self.prefs = await self.load_prefs()
                api_key = self.prefs.get("api_key", "")
                if not api_key or api_key == "YOUR_GOOGLE_MAPS_API_KEY":
                    await self.capability_worker.speak(
                        "I need a Google Maps API key to check traffic. "
                        "Add it in your settings and try again."
                    )
                    self.capability_worker.resume_normal_flow()
                    return

            # Auto-detect location from IP
            self._ip_location = self._detect_location_by_ip()
            if self._ip_location:
                self._current_location = (
                    f"{self._ip_location['lat']},{self._ip_location['lon']}"
                )
                self._log(
                    "info",
                    f"IP location: {self._ip_location.get('city', '?')} "
                    f"({self._current_location})",
                )

            # First-run: no saved locations -> onboarding
            saved = self.prefs.get("saved_locations", {})
            if not saved.get("home") and not saved.get("work"):
                await self.handle_onboarding()
                self.prefs = await self.load_prefs()

            # Get trigger context
            trigger_text = self.get_trigger_context()

            # If trigger text is empty or just trigger phrases, ask user
            if not trigger_text or not trigger_text.strip() or self._is_trigger_leak(trigger_text):
                await self.capability_worker.speak(
                    "What would you like to check? "
                    "Say something like: how long to work, "
                    "or how long from Bole to Piassa."
                )
                trigger_text = await self._get_clean_response()
                if not trigger_text:
                    return

            # Filter STT noise
            if self._is_noise(trigger_text):
                await self.capability_worker.speak(
                    "I didn't catch that. "
                    "Say a destination like work, airport, "
                    "or from here to downtown."
                )
                retry = await self._get_clean_response()
                if not retry:
                    return
                trigger_text = retry

            # Classify intent
            saved_names = ", ".join(self.prefs.get("saved_locations", {}).keys()) or "none"
            raw = self.capability_worker.text_to_text_response(
                CLASSIFY_PROMPT.format(
                    saved_names=saved_names,
                    user_input=trigger_text,
                )
            )
            parsed = self._parse_json(raw)
            mode = parsed.get("mode", "quick_check")

            # Route to handler
            await self._dispatch(mode, parsed)

            # Follow-up loop: keep ability active for multiple queries
            while True:
                await self.capability_worker.speak(
                    "Need another traffic check? Say a destination, or done to exit."
                )
                followup = await self._get_clean_response()
                if not followup or self._is_exit(followup):
                    break
                # Re-classify the follow-up
                raw2 = self.capability_worker.text_to_text_response(
                    CLASSIFY_PROMPT.format(
                        saved_names=saved_names,
                        user_input=followup,
                    )
                )
                parsed2 = self._parse_json(raw2)
                mode2 = parsed2.get("mode", "quick_check")
                await self._dispatch(mode2, parsed2)

        except Exception as e:
            self._log("error", f"Unexpected error: {e}")
            await self.capability_worker.speak(
                "Something went wrong with the traffic check. Try again."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    async def _dispatch(self, mode: str, parsed: dict):
        """Route to the appropriate handler."""
        if mode == "save_location":
            await self.handle_save_location(parsed)
        elif mode == "commute":
            await self.handle_commute()
        elif mode == "departure_plan":
            await self.handle_departure_plan(parsed)
        elif mode == "custom_route":
            await self.handle_custom_route(parsed)
        elif mode == "trip_status":
            await self.handle_trip_status()
        else:
            await self.handle_quick_check(parsed)

    # ------------------------------------------------------------------
    # Trigger context
    # ------------------------------------------------------------------

    def get_trigger_context(self) -> str:
        try:
            history = self.worker.agent_memory.full_message_history
            if not history:
                return ""
            user_msgs = []
            for msg in reversed(history):
                try:
                    if isinstance(msg, dict):
                        role = msg.get("role")
                        content = msg.get("content")
                    else:
                        role = msg.role if hasattr(msg, "role") else None
                        content = msg.content if hasattr(msg, "content") else None
                    if role == "user" and content:
                        user_msgs.append(content)
                    if len(user_msgs) >= 5:
                        break
                except Exception:
                    continue
            return "\n".join(reversed(user_msgs))
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Mode handlers
    # ------------------------------------------------------------------

    async def handle_api_key_setup(self):
        """Guide user through Google Maps API key setup."""
        await self.capability_worker.speak(
            "To use traffic and travel times, I need a Google Maps API key. "
            "Go to console dot cloud dot google dot com, create a project, "
            "enable the Routes API, and create an API key under Credentials. "
            "Then type or paste it in the text box."
        )
        key_input = await self.capability_worker.user_response()
        if not key_input or self._is_exit(key_input):
            return

        key = key_input.strip()
        # Validate with a simple geocode test
        test_url = f"{GEOCODE_URL}?address=New+York&key={key}"
        try:
            resp = requests.get(test_url, timeout=10)
            data = resp.json()
            if data.get("status") == "OK":
                self.prefs["api_key"] = key
                await self.save_prefs()
                await self.capability_worker.speak(
                    "Google Maps is connected. Let's set up your locations."
                )
            elif data.get("status") == "REQUEST_DENIED":
                await self.capability_worker.speak(
                    "Your Google Maps API key didn't work. Double-check it in your settings."
                )
            else:
                await self.capability_worker.speak(
                    "I couldn't validate that key. Check that the Routes API is enabled."
                )
        except Exception:
            await self.capability_worker.speak(
                "I couldn't reach Google Maps right now. Try again in a moment."
            )

    async def handle_onboarding(self):
        """First-run: save home and work addresses."""
        # Flush residual STT from trigger phrase
        await self.capability_worker.wait_for_complete_transcription()

        await self.capability_worker.speak(
            "Welcome to Traffic and Travel Time! "
            "Let's set up your key locations. "
            "What's your home address? Say it or type it for accuracy."
        )
        home_input = await self._get_clean_response()
        if home_input:
            home_addr = self._clean_address(home_input)
            await self.capability_worker.speak(
                f"Got it. Your home address is {home_addr}. Is that right?"
            )
            confirmed = await self._ask_yes_no()
            if confirmed:
                self.prefs.setdefault("saved_locations", {})["home"] = {
                    "address": home_addr
                }
                await self.save_prefs()

        await self.capability_worker.speak(
            "And what about your work address?"
        )
        work_input = await self._get_clean_response()
        if work_input:
            work_addr = self._clean_address(work_input)
            await self.capability_worker.speak(
                f"Got it. Your work address is {work_addr}. Is that right?"
            )
            confirmed = await self._ask_yes_no()
            if confirmed:
                self.prefs.setdefault("saved_locations", {})["work"] = {
                    "address": work_addr
                }
                await self.save_prefs()

        await self.capability_worker.speak(
            "All set. Now you can just say how long to work or commute check "
            "and I'll give you live traffic."
        )

    async def handle_quick_check(self, parsed: dict):
        """Quick traffic check to a saved or spoken destination."""
        await self.capability_worker.speak("Let me check traffic.")

        destination_name = (parsed.get("destination") or "").strip().lower()
        origin_name = (parsed.get("origin") or "").strip().lower()

        saved = self.prefs.get("saved_locations", {})

        # Resolve destination
        dest_addr = self._resolve_location(destination_name, saved)
        if not dest_addr:
            saved_names = list(saved.keys())
            if saved_names:
                names_str = ", ".join(saved_names)
                await self.capability_worker.speak(
                    f"I don't have {destination_name or 'that'} saved. "
                    f"Your saved places are: {names_str}. "
                    "Which one, or tell me the address?"
                )
            else:
                await self.capability_worker.speak(
                    f"I don't have {destination_name or 'that'} saved. "
                    "What's the full address?"
                )
            addr_input = await self._get_clean_response()
            if not addr_input:
                return
            resolved = self._resolve_location(addr_input.strip().lower(), saved)
            dest_addr = resolved if resolved else self._clean_address(addr_input)

        # Resolve origin using smart resolver
        orig_addr = await self._resolve_origin(origin_name, saved)
        if not orig_addr:
            return

        # Call Routes API
        result = self._get_route(orig_addr, dest_addr)
        if not result:
            await self.capability_worker.speak(
                "I couldn't get live traffic data right now. "
                "Check that your Google Maps API key is valid and try again."
            )
            return

        # Track session
        self._last_origin = orig_addr
        self._last_destination = dest_addr
        self._last_dest_name = destination_name or dest_addr
        self._current_location = orig_addr

        # Generate voice response from real API data
        display_dest = destination_name or dest_addr
        response = self._format_traffic_response(result, display_dest)
        await self.capability_worker.speak(response)

        # Offer to save if custom address
        if destination_name and destination_name not in saved:
            await self.capability_worker.speak(
                "Want me to save that destination for next time?"
            )
            confirmed = await self._ask_yes_no()
            if confirmed:
                await self._save_location_flow(destination_name, dest_addr)

    async def handle_custom_route(self, parsed: dict):
        """Custom route with origin and destination from voice."""
        await self.capability_worker.speak("Let me check that route.")

        saved = self.prefs.get("saved_locations", {})
        origin_raw = parsed.get("origin") or ""
        dest_raw = parsed.get("destination") or ""

        # Resolve origin with smart resolver
        orig_addr = await self._resolve_origin(origin_raw, saved)
        if not orig_addr:
            return

        # Resolve destination
        dest_addr = self._resolve_location(dest_raw.lower(), saved)
        if not dest_addr:
            dest_addr = self._clean_address(dest_raw)
        if not dest_addr:
            await self.capability_worker.speak("Where are you going?")
            addr_input = await self._get_clean_response()
            if not addr_input:
                return
            resolved = self._resolve_location(addr_input.strip().lower(), saved)
            dest_addr = resolved if resolved else self._clean_address(addr_input)

        # Confirm addresses
        await self.capability_worker.speak(
            f"From {orig_addr} to {dest_addr}. Sound right?"
        )
        confirmed = await self._ask_yes_no()
        if not confirmed:
            await self.capability_worker.speak("Okay, cancelled.")
            return

        result = self._get_route(orig_addr, dest_addr)
        if not result:
            await self.capability_worker.speak(
                "I couldn't get live traffic data for that route. "
                "Check your API key or try again."
            )
            return

        # Track session
        self._last_origin = orig_addr
        self._last_destination = dest_addr
        self._last_dest_name = dest_raw or dest_addr
        self._current_location = orig_addr

        display_dest = dest_raw or dest_addr
        response = self._format_traffic_response(result, display_dest)
        await self.capability_worker.speak(response)

        # Offer to save destination
        dest_name = dest_raw.lower().strip()
        if dest_name and dest_name not in saved:
            await self.capability_worker.speak(
                "Want me to save that destination for next time?"
            )
            save_confirmed = await self._ask_yes_no()
            if save_confirmed:
                await self._save_location_flow(dest_name, dest_addr)

    async def handle_commute(self):
        """Quick commute check: home to work or work to home."""
        saved = self.prefs.get("saved_locations", {})
        home = saved.get("home", {}).get("address")
        work = saved.get("work", {}).get("address")

        if not home or not work:
            missing = []
            if not home:
                missing.append("home")
            if not work:
                missing.append("work")
            await self.capability_worker.speak(
                f"I don't have your {' or '.join(missing)} address yet. "
                f"What is it?"
            )
            for loc in missing:
                await self.capability_worker.speak(f"What's your {loc} address?")
                addr_input = await self.capability_worker.user_response()
                if addr_input and not self._is_exit(addr_input):
                    addr = self._clean_address(addr_input)
                    self.prefs.setdefault("saved_locations", {})[loc] = {
                        "address": addr
                    }
                    await self.save_prefs()
            saved = self.prefs.get("saved_locations", {})
            home = saved.get("home", {}).get("address")
            work = saved.get("work", {}).get("address")
            if not home or not work:
                await self.capability_worker.speak(
                    "I need both home and work to check your commute."
                )
                return

        # Detect direction by time of day
        hour = datetime.now().hour
        if hour < 12:
            origin, dest, dest_name = home, work, "work"
        else:
            origin, dest, dest_name = work, home, "home"

        await self.capability_worker.speak("Checking your commute.")
        result = self._get_route(origin, dest)
        if not result:
            await self.capability_worker.speak(
                "I couldn't get live traffic for your commute right now. Try again."
            )
            return

        # Track session
        self._last_origin = origin
        self._last_destination = dest
        self._last_dest_name = dest_name
        self._current_location = origin

        response = self._format_traffic_response(result, dest_name)
        await self.capability_worker.speak(response)

    async def handle_departure_plan(self, parsed: dict):
        """Calculate when to leave to arrive by a target time."""
        saved = self.prefs.get("saved_locations", {})
        dest_raw = parsed.get("destination") or ""
        arrival_str = parsed.get("arrival_time") or ""

        dest_addr = self._resolve_location(dest_raw.lower(), saved)
        if not dest_addr:
            dest_addr = self._clean_address(dest_raw)
        if not dest_addr:
            await self.capability_worker.speak("Where do you need to be?")
            addr_input = await self.capability_worker.user_response()
            if not addr_input or self._is_exit(addr_input):
                return
            dest_addr = self._clean_address(addr_input)

        # Parse arrival time
        if not arrival_str:
            await self.capability_worker.speak("What time do you need to arrive?")
            time_input = await self.capability_worker.user_response()
            if not time_input or self._is_exit(time_input):
                return
            arrival_str = time_input.strip()

        arrival_time = self._parse_time(arrival_str)
        if not arrival_time:
            await self.capability_worker.speak(
                "I couldn't understand that time. Try something like 6 PM or 18:00."
            )
            return

        # Resolve origin with smart resolver
        origin_raw = parsed.get("origin") or ""
        orig_addr = await self._resolve_origin(origin_raw, saved)
        if not orig_addr:
            return

        await self.capability_worker.speak("Let me calculate when you should leave.")

        # Get travel time with predictive traffic for arrival time
        result = self._get_route(orig_addr, dest_addr, departure_time=arrival_str)
        if not result:
            await self.capability_worker.speak(
                "I couldn't get travel time data for that route. Try again."
            )
            return

        # Track session
        self._last_origin = orig_addr
        self._last_destination = dest_addr
        self._last_dest_name = dest_raw or dest_addr
        self._current_location = orig_addr

        duration_sec = result.get("duration_seconds", 0)
        duration_min = round(duration_sec / 60)

        # Calculate departure time
        departure_dt = arrival_time - timedelta(minutes=duration_min + 5)
        dep_str = departure_dt.strftime("%-I:%M %p")

        display_dest = dest_raw or dest_addr
        response = self.capability_worker.text_to_text_response(
            DEPARTURE_RESPONSE_PROMPT.format(
                destination=display_dest,
                arrival_time=arrival_time.strftime("%-I:%M %p"),
                duration=duration_min,
                departure_time=dep_str,
            )
        )
        await self.capability_worker.speak(response)

    async def handle_trip_status(self):
        """Mid-trip status: re-check remaining time on the last route."""
        if not self._last_origin or not self._last_destination:
            await self.capability_worker.speak(
                "I don't have an active trip to check. "
                "Start by asking something like: how long from Bole to Piassa?"
            )
            return

        await self.capability_worker.speak(
            f"Let me re-check your route to {self._last_dest_name}."
        )

        # Use current location (IP-based) or last origin
        origin = self._current_location or self._last_origin
        result = self._get_route(origin, self._last_destination)
        if not result:
            await self.capability_worker.speak(
                "I couldn't get updated traffic data right now. Try again."
            )
            return

        duration_sec = result.get("duration_seconds", 0)
        static_sec = result.get("static_seconds", 0)
        duration_min = round(duration_sec / 60)
        static_min = round(static_sec / 60)

        if static_min > 0:
            ratio = duration_sec / max(static_sec, 1)
        else:
            ratio = 1.0
        if ratio < 1.1:
            severity = "clear"
        elif ratio < 1.25:
            severity = "light"
        elif ratio < 1.5:
            severity = "moderate"
        elif ratio < 2.0:
            severity = "heavy"
        else:
            severity = "severe"

        response = self.capability_worker.text_to_text_response(
            TRIP_STATUS_PROMPT.format(
                origin=self._last_origin,
                destination=self._last_dest_name,
                remaining_duration=result.get(
                    "duration_text", f"{duration_min} min"
                ),
                remaining_distance=result.get("distance_text", "?"),
                severity=severity,
            )
        )
        await self.capability_worker.speak(response)

    async def handle_save_location(self, parsed: dict):
        """Save a named location."""
        name = (parsed.get("location_name") or "").strip().lower()
        address = (parsed.get("address") or "").strip()

        if not name:
            await self.capability_worker.speak("What name should I save it as?")
            name_input = await self.capability_worker.user_response()
            if not name_input or self._is_exit(name_input):
                return
            name = name_input.strip().lower()

        if not address:
            await self.capability_worker.speak(f"What's the address for {name}?")
            addr_input = await self.capability_worker.user_response()
            if not addr_input or self._is_exit(addr_input):
                return
            address = self._clean_address(addr_input)

        await self._save_location_flow(name, address)

    async def _save_location_flow(self, name: str, address: str):
        """Save a location with confirmation."""
        saved = self.prefs.get("saved_locations", {})
        if len(saved) >= MAX_SAVED_LOCATIONS and name not in saved:
            await self.capability_worker.speak(
                f"You have {MAX_SAVED_LOCATIONS} saved locations. "
                "Want to replace one?"
            )
            return

        clean_addr = self._clean_address(address) if address else address
        await self.capability_worker.speak(
            f"Saving {name} as {clean_addr}. Is that right?"
        )
        confirmed = await self._ask_yes_no()
        if confirmed:
            self.prefs.setdefault("saved_locations", {})[name] = {
                "address": clean_addr
            }
            await self.save_prefs()
            await self.capability_worker.speak(f"Saved. You can now say how long to {name}.")
        else:
            await self.capability_worker.speak("Okay, not saved.")

    # ------------------------------------------------------------------
    # Google Maps API calls
    # ------------------------------------------------------------------

    def _get_route(
        self,
        origin: str,
        destination: str,
        departure_time: Optional[str] = None,
        traffic_model: str = "best_guess",
    ) -> Optional[dict]:
        """Call Google Maps Routes API. Falls back to Distance Matrix."""
        api_key = self.prefs.get("api_key", "")
        if not api_key:
            return None

        # Try Routes API first
        result = self._call_routes_api(origin, destination, departure_time, api_key)
        if result:
            return result

        # Fallback to Distance Matrix
        result = self._call_distance_matrix(
            origin, destination, traffic_model, api_key
        )
        return result

    @staticmethod
    def _make_waypoint(location: str) -> dict:
        """Format a waypoint for Routes API: lat,lon -> latLng, else address."""
        if not location:
            return {"address": ""}
        parts = location.split(",")
        if len(parts) == 2:
            try:
                lat = float(parts[0].strip())
                lon = float(parts[1].strip())
                return {
                    "location": {
                        "latLng": {"latitude": lat, "longitude": lon}
                    }
                }
            except ValueError:
                pass
        return {"address": location}

    def _call_routes_api(
        self,
        origin: str,
        destination: str,
        departure_time: Optional[str],
        api_key: str,
    ) -> Optional[dict]:
        """Call Google Maps Routes API (v2)."""
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "routes.duration,routes.staticDuration,routes.distanceMeters,"
                "routes.description,routes.localizedValues,"
                "routes.travelAdvisory"
            ),
        }
        body = {
            "origin": self._make_waypoint(origin),
            "destination": self._make_waypoint(destination),
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
            "computeAlternativeRoutes": False,
            "languageCode": "en-US",
            "units": self.prefs.get("units", "IMPERIAL").upper(),
        }
        if departure_time:
            dt = self._parse_time(departure_time)
            if dt:
                body["departureTime"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            resp = requests.post(
                ROUTES_API_URL, json=body, headers=headers, timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                routes = data.get("routes", [])
                if routes:
                    route = routes[0]
                    duration_str = route.get("duration", "0s")
                    static_str = route.get("staticDuration", "0s")
                    duration_sec = self._parse_duration(duration_str)
                    static_sec = self._parse_duration(static_str)

                    localized = route.get("localizedValues", {})
                    return {
                        "duration_seconds": duration_sec,
                        "static_seconds": static_sec,
                        "duration_text": localized.get("duration", {}).get(
                            "text", f"{round(duration_sec / 60)} min"
                        ),
                        "static_text": localized.get("staticDuration", {}).get(
                            "text", f"{round(static_sec / 60)} min"
                        ),
                        "distance_text": localized.get("distance", {}).get(
                            "text", f"{route.get('distanceMeters', 0)} m"
                        ),
                        "route_name": route.get("description", ""),
                        "distance_meters": route.get("distanceMeters", 0),
                    }
            else:
                self._log(
                    "error",
                    f"Routes API {resp.status_code}: {resp.text[:200]}",
                )
        except requests.exceptions.Timeout:
            self._log("error", "Routes API timed out")
        except Exception as e:
            self._log("error", f"Routes API error: {e}")
        return None

    def _call_distance_matrix(
        self,
        origin: str,
        destination: str,
        traffic_model: str,
        api_key: str,
    ) -> Optional[dict]:
        """Fallback: Google Maps Distance Matrix API."""
        params = {
            "origins": origin,
            "destinations": destination,
            "departure_time": "now",
            "traffic_model": traffic_model,
            "key": api_key,
        }
        try:
            resp = requests.get(
                DISTANCE_MATRIX_URL, params=params, timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") != "OK":
                    error_msg = data.get("error_message", data.get("status", ""))
                    self._log("error", f"Distance Matrix: {error_msg}")
                    return None
                rows = data.get("rows", [])
                if rows:
                    elem = rows[0].get("elements", [{}])[0]
                    if elem.get("status") != "OK":
                        return None
                    duration = elem.get("duration", {})
                    traffic = elem.get("duration_in_traffic", {})
                    distance = elem.get("distance", {})
                    return {
                        "duration_seconds": traffic.get(
                            "value", duration.get("value", 0)
                        ),
                        "static_seconds": duration.get("value", 0),
                        "duration_text": traffic.get(
                            "text", duration.get("text", "?")
                        ),
                        "static_text": duration.get("text", "?"),
                        "distance_text": distance.get("text", "?"),
                        "route_name": "",
                        "distance_meters": distance.get("value", 0),
                    }
        except requests.exceptions.Timeout:
            self._log("error", "Distance Matrix timed out")
        except Exception as e:
            self._log("error", f"Distance Matrix error: {e}")
        return None

    # ------------------------------------------------------------------
    # Traffic analysis + voice formatting
    # ------------------------------------------------------------------

    def _format_traffic_response(self, result: dict, destination: str) -> str:
        """Generate natural voice response from route data."""
        duration_sec = result.get("duration_seconds", 0)
        static_sec = result.get("static_seconds", 0)
        duration_min = round(duration_sec / 60)
        static_min = round(static_sec / 60)
        delay_min = max(0, duration_min - static_min)

        # Severity classification
        if static_min > 0:
            ratio = duration_sec / max(static_sec, 1)
        else:
            ratio = 1.0

        if ratio < 1.1:
            severity = "clear"
        elif ratio < 1.25:
            severity = "light"
        elif ratio < 1.5:
            severity = "moderate"
        elif ratio < 2.0:
            severity = "heavy"
        else:
            severity = "severe"

        response = self.capability_worker.text_to_text_response(
            TRAFFIC_RESPONSE_PROMPT.format(
                destination=destination,
                duration=result.get("duration_text", f"{duration_min} min"),
                static_duration=result.get("static_text", f"{static_min} min"),
                distance=result.get("distance_text", "?"),
                route_name=result.get("route_name", ""),
                severity=severity,
                delay_minutes=delay_min,
            )
        )
        return response

    # ------------------------------------------------------------------
    # IP Geolocation
    # ------------------------------------------------------------------

    def _detect_location_by_ip(self) -> Optional[dict]:
        """Auto-detect approximate location from the user's IP address."""
        try:
            ip = self.worker.user_socket.client.host
            self._log("info", f"Detecting location for IP: {ip}")
            resp = requests.get(
                IP_GEO_URL.format(ip=ip), timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    isp = data.get("isp", "").lower()
                    if any(c in isp for c in CLOUD_INDICATORS):
                        self._log(
                            "warning",
                            "Cloud IP detected, location may be inaccurate",
                        )
                        return None
                    return {
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "city": (
                            f"{data.get('city', '')}, "
                            f"{data.get('regionName', '')}"
                        ),
                    }
        except Exception as e:
            self._log("error", f"IP geolocation error: {e}")
        return None

    # ------------------------------------------------------------------
    # Smart origin resolution
    # ------------------------------------------------------------------

    async def _resolve_origin(
        self, origin_name: str, saved: dict
    ) -> Optional[str]:
        """Resolve origin using: explicit name > IP geo > ask user."""
        origin_name = (origin_name or "").strip().lower()

        # 1. If user gave a specific named origin (not "current")
        current_words = {
            "here", "current", "where i am", "my location",
            "from here", "current location",
        }
        is_current = origin_name in current_words or not origin_name

        if origin_name and not is_current:
            addr = self._resolve_location(origin_name, saved)
            if addr:
                return addr
            # Try as a raw address/place name
            cleaned = self._clean_address(origin_name)
            if cleaned:
                return cleaned

        # 2. Try IP-based location
        if self._current_location:
            city_name = ""
            if self._ip_location:
                city_name = self._ip_location.get("city", "")
            if city_name:
                await self.capability_worker.speak(
                    f"I see you're near {city_name}. "
                    "Using that as your starting point."
                )
            return self._current_location

        # 3. Fall back to asking the user
        saved_names = list(saved.keys())
        if saved_names:
            names_str = ", ".join(saved_names)
            await self.capability_worker.speak(
                f"Where are you right now? "
                f"Say {names_str}, or give me an address."
            )
        else:
            await self.capability_worker.speak(
                "Where are you right now? "
                "Give me an address or landmark."
            )
        addr_input = await self._get_clean_response()
        if not addr_input:
            return None
        resolved = self._resolve_location(addr_input.strip().lower(), saved)
        return resolved if resolved else self._clean_address(addr_input)

    # ------------------------------------------------------------------
    # Address / location helpers
    # ------------------------------------------------------------------

    def _resolve_location(self, name: str, saved: dict) -> Optional[str]:
        """Resolve a location name to an address from saved locations."""
        if not name:
            return None
        # Exact match
        loc = saved.get(name)
        if loc:
            return loc.get("address")
        # Fuzzy match via LLM
        if saved:
            names_list = list(saved.keys())
            for saved_name in names_list:
                if saved_name in name or name in saved_name:
                    return saved[saved_name].get("address")
        return None

    def _clean_address(self, raw: str) -> str:
        """Clean up a voice-captured address using LLM."""
        if not raw or not raw.strip():
            return raw
        try:
            result = self.capability_worker.text_to_text_response(
                ADDRESS_CLEANUP_PROMPT.format(address=raw)
            )
            parsed = self._parse_json(result)
            return parsed.get("cleaned_address", raw.strip())
        except Exception:
            return raw.strip()

    # ------------------------------------------------------------------
    # Time parsing
    # ------------------------------------------------------------------

    def _parse_time(self, time_str: str) -> Optional[datetime]:
        """Parse a time string into a datetime for today."""
        if not time_str:
            return None
        time_str = time_str.strip().lower()

        # Try common formats
        for fmt in ["%I:%M %p", "%I:%M%p", "%H:%M", "%I %p", "%I%p"]:
            try:
                t = datetime.strptime(time_str, fmt)
                now = datetime.now()
                return now.replace(
                    hour=t.hour, minute=t.minute, second=0, microsecond=0
                )
            except ValueError:
                continue

        # Try extracting from natural language like "6", "6 pm"
        match = re.search(r"(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)?", time_str)
        if match:
            hour = int(match.group(1))
            ampm = match.group(2)
            if ampm and "p" in ampm and hour < 12:
                hour += 12
            elif ampm and "a" in ampm and hour == 12:
                hour = 0
            now = datetime.now()
            return now.replace(hour=hour, minute=0, second=0, microsecond=0)
        return None

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """Parse Google's duration string (e.g., '2100s') to seconds."""
        if not duration_str:
            return 0
        match = re.search(r"(\d+)", duration_str)
        return int(match.group(1)) if match else 0

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _parse_json(self, raw: str) -> dict:
        """Parse JSON from LLM response, stripping markdown fences."""
        if not raw:
            return {}
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            return {}

    def _is_exit(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower().strip()
        lower = re.sub(r"[^\w\s']", "", lower)
        for word in EXIT_WORDS:
            if word in lower:
                return True
        return False

    def _is_noise(self, text: str) -> bool:
        """Detect STT noise: non-English, gibberish, or very short ambiguous input."""
        if not text or len(text.strip()) < 2:
            return True
        # Check if mostly non-ASCII (Hindi, Spanish fragments, etc.)
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        if len(text) > 3 and ascii_chars / len(text) < 0.5:
            return True
        return False

    def _is_trigger_leak(self, text: str) -> bool:
        """Check if response is just the trigger phrase leaking through."""
        if not text:
            return True
        lower = text.lower().strip().rstrip(".")
        return lower in TRIGGER_PHRASES

    async def _get_clean_response(self) -> Optional[str]:
        """Get user response, filtering out trigger leaks and noise."""
        resp = await self.capability_worker.user_response()
        if not resp:
            return None
        if self._is_exit(resp):
            return None
        if self._is_trigger_leak(resp):
            # Trigger phrase leaked — ask again
            await self.capability_worker.speak(
                "I heard the trigger phrase, not your answer. Please say it again."
            )
            resp = await self.capability_worker.user_response()
            if not resp or self._is_exit(resp) or self._is_trigger_leak(resp):
                return None
        if self._is_noise(resp):
            await self.capability_worker.speak(
                "I didn't catch that clearly. Try again?"
            )
            resp = await self.capability_worker.user_response()
            if not resp or self._is_exit(resp) or self._is_noise(resp):
                return None
        return resp

    async def _ask_yes_no(self, max_retries: int = 2) -> bool:
        """Custom yes/no prompt that won't loop forever on non-yes/no input."""
        for attempt in range(max_retries + 1):
            resp = await self.capability_worker.user_response()
            if not resp:
                return False
            lower = resp.lower().strip().rstrip(".")
            if lower in {"yes", "yeah", "yep", "yup", "sure", "ok", "okay",
                         "correct", "right", "affirmative", "si"}:
                return True
            if lower in {"no", "nah", "nope", "not really", "negative", "skip"}:
                return False
            if self._is_exit(resp):
                return False
            if attempt < max_retries:
                await self.capability_worker.speak(
                    "Just say yes or no."
                )
        return False

    def _log(self, level: str, message: str):
        handler = self.worker.editor_logging_handler
        if level == "error":
            handler.error(f"[TrafficTravelTime] {message}")
        elif level == "warning":
            handler.warning(f"[TrafficTravelTime] {message}")
        else:
            handler.info(f"[TrafficTravelTime] {message}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def load_prefs(self) -> dict:
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            try:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                return json.loads(raw)
            except (json.JSONDecodeError, Exception):
                self._log("error", "Corrupt prefs file, using defaults.")
        return {
            "api_key": GOOGLE_MAPS_API_KEY or "YOUR_GOOGLE_MAPS_API_KEY",
            "preferred_api": "routes",
            "units": "imperial",
            "default_traffic_model": "best_guess",
            "saved_locations": {},
            "times_used": 0,
        }

    async def save_prefs(self):
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            await self.capability_worker.delete_file(PREFS_FILE, False)
        await self.capability_worker.write_file(
            PREFS_FILE, json.dumps(self.prefs), False
        )
