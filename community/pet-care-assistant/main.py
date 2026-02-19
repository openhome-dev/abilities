import json
import os
import re
import uuid
from datetime import datetime

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# PET CARE ASSISTANT
# A voice-first ability that helps users track and manage their pets' daily
# lives. Stores pet info, logs activities, finds emergency vets, warns
# about dangerous weather, and checks for pet food recalls.
#
# What this ability does that the LLM cannot do alone:
#   - Persist data across sessions (pet info, activity logs)
#   - Call external APIs for real-time information (weather, vets, recalls)
#   - Track activity over time (feeding, medication, walks, weight)
# =============================================================================

EXIT_WORDS = {
    "stop",
    "exit",
    "quit",
    "done",
    "cancel",
    "bye",
    "goodbye",
    "leave",
    "that's all",
    "that's it",
    "no thanks",
    "i'm done",
    "nothing else",
    "all good",
    "nope",
    "i'm good",
}

PETS_FILE = "petcare_pets.json"
ACTIVITY_LOG_FILE = "petcare_activity_log.json"

MAX_LOG_ENTRIES = 500

ACTIVITY_TYPES = {
    "feeding",
    "medication",
    "walk",
    "weight",
    "vet_visit",
    "grooming",
    "other",
}

# Replace with your own Google Places API key
GOOGLE_PLACES_API_KEY = "your_google_places_api_key_here"

CLASSIFY_PROMPT = (
    "You are an intent classifier for a pet care assistant. "
    "The user manages one or more pets.\n"
    "Known pets: {pet_names}.\n\n"
    "Classify the user's intent. Return ONLY valid JSON with no markdown fences.\n\n"
    "Possible modes:\n"
    '- {{"mode": "log", "pet_name": "<name or null>", "activity_type": "feeding|medication|walk|weight|vet_visit|grooming|other", "details": "<short description>", "value": null}}\n'
    "  (value is a number ONLY for weight entries, null otherwise)\n"
    '- {{"mode": "lookup", "pet_name": "<name or null>", "query": "<the user\'s question>"}}\n'
    '- {{"mode": "emergency_vet"}}\n'
    '- {{"mode": "weather", "pet_name": "<name or null>"}}\n'
    '- {{"mode": "food_recall"}}\n'
    '- {{"mode": "edit_pet", "action": "add_pet|update_pet|change_vet|update_weight|remove_pet|clear_log", "pet_name": "<name or null>", "details": "<what to change>"}}\n'
    '- {{"mode": "exit"}}\n'
    '- {{"mode": "unknown"}}\n\n'
    "Rules:\n"
    "- 'I fed', 'ate', 'breakfast', 'dinner', 'kibble', 'food' => log feeding\n"
    "- 'medicine', 'medication', 'pill', 'flea', 'heartworm', 'dose' => log medication\n"
    "- 'walk', 'walked', 'run', 'jog', 'hike' => log walk\n"
    "- 'weighs', 'pounds', 'lbs', 'kilos', 'weight is' => log weight (extract numeric value)\n"
    "- 'vet visit', 'went to vet', 'checkup' => log vet_visit\n"
    "- 'groom', 'bath', 'nails', 'haircut' => log grooming\n"
    "- 'when did', 'last time', 'how many', 'has had', 'check on' => lookup\n"
    "- 'emergency vet', 'find a vet', 'vet near me', 'need a vet' => emergency_vet\n"
    "- 'safe outside', 'weather', 'too hot', 'too cold', 'can I walk' => weather\n"
    "- 'food recall', 'recall check', 'food safe' => food_recall\n"
    "- 'add a pet', 'new pet', 'update', 'change vet', 'edit pet' => edit_pet\n"
    "- 'remove pet', 'delete pet' => edit_pet with action remove_pet\n"
    "- 'clear log', 'clear activity log', 'delete all logs' => edit_pet with action clear_log\n"
    "- 'stop', 'done', 'quit', 'exit', 'bye' => exit\n"
    "- If only one pet exists and no name is mentioned, use that pet's name.\n"
    "- If multiple pets and no name mentioned, set pet_name to null.\n"
    "- Transcription may be garbled from speech-to-text. Be flexible.\n\n"
    "Examples:\n"
    '"I just fed Luna" -> {{"mode": "log", "pet_name": "Luna", "activity_type": "feeding", "details": "fed", "value": null}}\n'
    '"Luna got her flea medicine" -> {{"mode": "log", "pet_name": "Luna", "activity_type": "medication", "details": "flea medicine", "value": null}}\n'
    '"We walked for 30 minutes" -> {{"mode": "log", "pet_name": null, "activity_type": "walk", "details": "30 minute walk", "value": null}}\n'
    '"Luna weighs 48 pounds now" -> {{"mode": "log", "pet_name": "Luna", "activity_type": "weight", "details": "48 lbs", "value": 48}}\n'
    '"When did I last feed Luna?" -> {{"mode": "lookup", "pet_name": "Luna", "query": "when was last feeding"}}\n'
    '"Has Max had his heartworm pill this month?" -> {{"mode": "lookup", "pet_name": "Max", "query": "heartworm pill this month"}}\n'
    '"Find an emergency vet" -> {{"mode": "emergency_vet"}}\n'
    '"Is it safe for Luna outside?" -> {{"mode": "weather", "pet_name": "Luna"}}\n'
    '"Any pet food recalls?" -> {{"mode": "food_recall"}}\n'
    '"Add a new pet" -> {{"mode": "edit_pet", "action": "add_pet", "pet_name": null, "details": "add new pet"}}\n'
)

LOOKUP_SYSTEM_PROMPT = (
    "You are a pet care assistant answering a question about the user's "
    "pet activity log. Given the log entries and the user's question, "
    "give a short, clear spoken answer. Include when it happened "
    "(e.g., 'this morning', '3 days ago', 'last Tuesday'). "
    "Keep it to 1-2 sentences. If no matching entries exist, say so. "
    "Today's date is {today}."
)

WEATHER_SYSTEM_PROMPT = (
    "You are a pet care assistant checking weather safety for a pet. "
    "Given the current weather data and the pet's info (species, breed), "
    "assess if it's safe for the pet to be outside. "
    "Use these thresholds:\n"
    "- Temperature > 90F/32C: Warning (hot pavement, bring water)\n"
    "- Temperature > 100F/38C: Danger (heatstroke risk, do not go outside)\n"
    "- Temperature < 32F/0C: Warning for short-haired breeds and cats\n"
    "- Temperature < 20F/-7C: Danger (too cold for more than a few minutes)\n"
    "- Wind > 30 mph: Caution for small pets\n"
    "- UV > 7: Caution for light-colored or short-haired dogs\n"
    "If conditions are safe, say so positively. "
    "Add breed-specific nuance if you know the breed. "
    "Keep response to 1-2 sentences."
)

WEIGHT_SUMMARY_PROMPT = (
    "You are a pet care assistant summarizing weight history. "
    "Given the weight log entries for a pet, give a short spoken summary "
    "of their current weight and any trend. Keep it to 1-2 sentences. "
    "Today's date is {today}."
)


def _fmt_phone_for_speech(phone: str) -> str:
    """Format a phone number for spoken output, digit by digit."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return (
            f"{', '.join(digits[:3])}, "
            f"{', '.join(digits[3:6])}, "
            f"{', '.join(digits[6:])}"
        )
    return ", ".join(digits)


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences from LLM JSON output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class PetCareAssistantCapability(MatchingCapability):
    """OpenHome ability for multi-pet care tracking with persistent storage,
    emergency vet finder, weather safety, and food recall checks."""

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    pet_data: dict = None
    activity_log: list = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # ------------------------------------------------------------------
    # Main flow
    # ------------------------------------------------------------------

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("[PetCare] Ability started")

            # Load persistent data
            self.pet_data = await self._load_json(PETS_FILE, default={})
            self.activity_log = await self._load_json(ACTIVITY_LOG_FILE, default=[])

            # Check if first-time user (no pet data file)
            has_pet_data = await self.capability_worker.check_if_file_exists(
                PETS_FILE, False
            )

            if not has_pet_data or not self.pet_data.get("pets"):
                await self.run_onboarding()
                return

            # Returning user — classify trigger context
            trigger = self._get_trigger_context()
            if trigger:
                intent = self._classify_intent(trigger)
                mode = intent.get("mode", "unknown")

                if mode not in ("unknown", "exit"):
                    await self._route_intent(intent)
                    # Offer one follow-up
                    await self.capability_worker.speak("Anything else for your pets?")
                    follow_up = await self.capability_worker.user_response()
                    if follow_up and not self._is_exit(follow_up):
                        follow_intent = self._classify_intent(follow_up)
                        if follow_intent.get("mode") not in ("unknown", "exit"):
                            await self._route_intent(follow_intent)
                    await self.capability_worker.speak(
                        "Take care of those pets! See you next time."
                    )
                    return

            # Full mode — conversation loop
            pet_names = [p["name"] for p in self.pet_data.get("pets", [])]
            names_str = ", ".join(pet_names)
            await self.capability_worker.speak(
                f"Pet Care here. You have {len(pet_names)} "
                f"pet{'s' if len(pet_names) != 1 else ''}: {names_str}. "
                "What would you like to do?"
            )

            idle_count = 0
            for _ in range(20):
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Still here if you need me. Otherwise I'll close."
                        )
                        final = await self.capability_worker.user_response()
                        if not final or not final.strip() or self._is_exit(final):
                            await self.capability_worker.speak(
                                "Take care of those pets! See you next time."
                            )
                            break
                        user_input = final
                        idle_count = 0
                    else:
                        continue

                idle_count = 0

                if self._is_exit(user_input):
                    await self.capability_worker.speak(
                        "Take care of those pets! See you next time."
                    )
                    break

                intent = self._classify_intent(user_input)
                mode = intent.get("mode", "unknown")

                if mode == "exit":
                    await self.capability_worker.speak(
                        "Take care of those pets! See you next time."
                    )
                    break

                self.worker.editor_logging_handler.info(f"[PetCare] Intent: {intent}")
                await self._route_intent(intent)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PetCare] Unexpected error: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Closing Pet Care."
            )
        finally:
            self.worker.editor_logging_handler.info("[PetCare] Ability ended")
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    def _classify_intent(self, user_input: str) -> dict:
        """Use LLM to classify user intent and extract structured data."""
        pet_names = [p["name"] for p in self.pet_data.get("pets", [])]
        prompt_filled = CLASSIFY_PROMPT.format(
            pet_names=", ".join(pet_names) if pet_names else "none",
        )
        try:
            raw = self.capability_worker.text_to_text_response(
                f"User said: {user_input}",
                system_prompt=prompt_filled,
            )
            clean = _strip_json_fences(raw)
            return json.loads(clean)
        except (json.JSONDecodeError, Exception) as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Classification error: {e}"
            )
            return {"mode": "unknown"}

    # ------------------------------------------------------------------
    # Intent router
    # ------------------------------------------------------------------

    async def _route_intent(self, intent: dict):
        """Route to the correct handler based on classified intent."""
        mode = intent.get("mode", "unknown")

        if mode == "log":
            await self._handle_log(intent)
        elif mode == "lookup":
            await self._handle_lookup(intent)
        elif mode == "emergency_vet":
            await self._handle_emergency_vet()
        elif mode == "weather":
            await self._handle_weather(intent)
        elif mode == "food_recall":
            await self._handle_food_recall()
        elif mode == "edit_pet":
            await self._handle_edit_pet(intent)
        elif mode == "onboarding":
            await self.run_onboarding()
        else:
            await self.capability_worker.speak(
                "I can log activities, look up pet history, find emergency vets, "
                "check weather safety, or check food recalls. What would you like?"
            )

    # ------------------------------------------------------------------
    # Onboarding
    # ------------------------------------------------------------------

    async def run_onboarding(self):
        """Guided voice onboarding for first-time users."""
        self.worker.editor_logging_handler.info("[PetCare] Starting onboarding")

        await self.capability_worker.speak(
            "Hi! I'm your pet care assistant. Let's get set up. "
            "What's your pet's name?"
        )

        while True:
            pet = await self._collect_pet_info()
            if pet is None:
                await self.capability_worker.speak("No problem. Come back anytime!")
                return

            # Add pet to data
            if "pets" not in self.pet_data:
                self.pet_data["pets"] = []
            self.pet_data["pets"].append(pet)
            await self._save_json(PETS_FILE, self.pet_data)

            await self.capability_worker.speak(
                f"All set! I've saved {pet['name']}'s info. "
                f"You can say things like 'I just fed {pet['name']}' to log activities, "
                "or 'find an emergency vet' if you ever need one."
            )

            # Ask about additional pets
            await self.capability_worker.speak("Do you have any other pets to add?")
            response = await self.capability_worker.user_response()
            if not response or self._is_exit(response):
                break
            cleaned = response.lower().strip()
            if any(
                w in cleaned for w in ["no", "nope", "nah", "that's it", "that's all"]
            ):
                break
            # They said yes or gave a name — loop for another pet
            await self.capability_worker.speak("Great! What's your next pet's name?")

    async def _collect_pet_info(self) -> dict:
        """Collect one pet's data through guided voice questions."""
        # Name
        name_input = await self.capability_worker.user_response()
        if not name_input or self._is_exit(name_input):
            return None
        name = self._extract_value(
            name_input, "Extract the pet's name from this. Return just the name."
        )

        # Species
        species_input = await self.capability_worker.run_io_loop(
            f"Great! What kind of animal is {name}? Dog, cat, or something else?"
        )
        if not species_input or self._is_exit(species_input):
            return None
        species = self._extract_value(
            species_input,
            "Extract the animal species. Return one word: dog, cat, bird, rabbit, etc.",
        ).lower()

        # Breed
        breed_input = await self.capability_worker.run_io_loop(f"What breed is {name}?")
        if not breed_input or self._is_exit(breed_input):
            return None
        breed = self._extract_value(
            breed_input,
            "Extract the breed name. If they don't know or say mixed, return 'mixed'.",
        )

        # Age / birthday
        age_input = await self.capability_worker.run_io_loop(
            f"How old is {name}, or do you know their birthday?"
        )
        if not age_input or self._is_exit(age_input):
            return None
        birthday = self._extract_value(
            age_input,
            "Extract a birthday in YYYY-MM-DD format if possible. "
            "If they give an age like '3 years old', calculate the approximate birthday "
            f"from today ({datetime.now().strftime('%Y-%m-%d')}). "
            "Return just the date string.",
        )

        # Weight
        weight_input = await self.capability_worker.run_io_loop(
            f"Roughly how much does {name} weigh?"
        )
        if not weight_input or self._is_exit(weight_input):
            return None
        weight_str = self._extract_value(
            weight_input,
            "Extract the weight as a number in pounds. If they give kilos, convert to pounds. "
            "Return just the number.",
        )
        try:
            weight_lbs = float(weight_str)
        except (ValueError, TypeError):
            weight_lbs = 0

        # Allergies
        allergy_input = await self.capability_worker.run_io_loop(
            f"Does {name} have any allergies I should know about?"
        )
        if not allergy_input or self._is_exit(allergy_input):
            return None
        allergies_str = self._extract_value(
            allergy_input,
            "Extract allergies as a JSON array of strings. "
            'If none, return []. Example: ["chicken", "grain"]. Return only the array.',
        )
        try:
            allergies = json.loads(allergies_str)
            if not isinstance(allergies, list):
                allergies = []
        except (json.JSONDecodeError, TypeError):
            allergies = []

        # Medications
        med_input = await self.capability_worker.run_io_loop(
            f"Is {name} on any medications?"
        )
        if not med_input or self._is_exit(med_input):
            return None
        meds_str = self._extract_value(
            med_input,
            "Extract medications as a JSON array of objects with 'name' and 'frequency' keys. "
            'If none, return []. Example: [{"name": "Heartgard", "frequency": "monthly"}]. '
            "Return only the array.",
        )
        try:
            medications = json.loads(meds_str)
            if not isinstance(medications, list):
                medications = []
        except (json.JSONDecodeError, TypeError):
            medications = []

        # Vet info
        vet_input = await self.capability_worker.run_io_loop(
            "Do you have a regular vet? If so, what's their name?"
        )
        vet_name = ""
        vet_phone = ""
        if vet_input and not self._is_exit(vet_input):
            cleaned = vet_input.lower().strip()
            if not any(w in cleaned for w in ["no", "nope", "skip", "don't have"]):
                vet_name = self._extract_value(
                    vet_input, "Extract the veterinarian's name. Return just the name."
                )
                phone_input = await self.capability_worker.run_io_loop(
                    "What's their phone number?"
                )
                if phone_input and not self._is_exit(phone_input):
                    vet_phone = self._extract_value(
                        phone_input,
                        "Extract the phone number as digits only (e.g., 5125551234). Return just digits.",
                    )

        if vet_name:
            self.pet_data["vet_name"] = vet_name
            self.pet_data["vet_phone"] = vet_phone

        # Location
        location_input = await self.capability_worker.run_io_loop(
            "Last thing. What city are you in? This helps me check weather and find vets nearby."
        )
        if location_input and not self._is_exit(location_input):
            location = self._extract_value(
                location_input,
                "Extract the city and state/country. Return in format 'City, State' or 'City, Country'.",
            )
            self.pet_data["user_location"] = location
            # Get lat/lon from location
            coords = self._geocode_location(location)
            if coords:
                self.pet_data["user_lat"] = coords["lat"]
                self.pet_data["user_lon"] = coords["lon"]

        pet_id = f"pet_{uuid.uuid4().hex[:6]}"
        return {
            "id": pet_id,
            "name": name,
            "species": species,
            "breed": breed,
            "birthday": birthday,
            "weight_lbs": weight_lbs,
            "allergies": allergies,
            "medications": medications,
        }

    # ------------------------------------------------------------------
    # Log Activity
    # ------------------------------------------------------------------

    async def _handle_log(self, intent: dict):
        """Log a pet activity (feeding, medication, walk, weight, etc.)."""
        pet = await self._resolve_pet_async(intent.get("pet_name"))
        if pet is None:
            return

        activity_type = intent.get("activity_type", "other")
        details = intent.get("details", "")
        value = intent.get("value")

        entry = {
            "id": f"log_{uuid.uuid4().hex[:6]}",
            "pet_id": pet["id"],
            "pet_name": pet["name"],
            "type": activity_type,
            "details": details,
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if activity_type == "weight" and value is not None:
            entry["value"] = value
            # Also update weight in pet data
            for p in self.pet_data.get("pets", []):
                if p["id"] == pet["id"]:
                    p["weight_lbs"] = value
                    break
            await self._save_json(PETS_FILE, self.pet_data)

        # Add to log (newest first)
        self.activity_log.insert(0, entry)

        # Trim to MAX_LOG_ENTRIES
        if len(self.activity_log) > MAX_LOG_ENTRIES:
            self.activity_log = self.activity_log[:MAX_LOG_ENTRIES]

        await self._save_json(ACTIVITY_LOG_FILE, self.activity_log)

        # Confirm briefly
        time_str = datetime.now().strftime("%I:%M %p").lstrip("0")
        await self.capability_worker.speak(
            f"Got it. Logged {pet['name']}'s {activity_type} at {time_str}."
        )

        # Quick re-log loop: ask if they want to log more
        await self.capability_worker.speak("Anything else to log?")
        await self.worker.session_tasks.sleep(4)
        follow = await self.capability_worker.user_response()
        if follow and not self._is_exit(follow):
            cleaned = follow.lower().strip()
            if any(
                w in cleaned for w in ["no", "nope", "nah", "that's it", "that's all"]
            ):
                return
            # They said something — classify and handle if it's another log
            follow_intent = self._classify_intent(follow)
            if follow_intent.get("mode") == "log":
                await self._handle_log(follow_intent)

    # ------------------------------------------------------------------
    # Quick Lookup
    # ------------------------------------------------------------------

    async def _handle_lookup(self, intent: dict):
        """Answer a question about pet activity history."""
        pet = await self._resolve_pet_async(intent.get("pet_name"))
        query = intent.get("query", "")

        # Filter logs for the pet if specified
        if pet:
            relevant_logs = [
                e for e in self.activity_log if e.get("pet_id") == pet["id"]
            ][
                :50
            ]  # Last 50 entries for context
        else:
            relevant_logs = self.activity_log[:50]

        # Check for weight-specific queries
        if any(
            w in query.lower()
            for w in ["weight", "weigh", "gained", "lost", "pounds", "lbs"]
        ):
            await self._handle_weight_lookup(pet, relevant_logs)
            return

        today = datetime.now().strftime("%Y-%m-%d")
        system = LOOKUP_SYSTEM_PROMPT.format(today=today)

        log_text = (
            json.dumps(relevant_logs, indent=2)
            if relevant_logs
            else "No entries found."
        )

        prompt = f"User's question: {query}\n\n" f"Activity log entries:\n{log_text}"

        try:
            response = self.capability_worker.text_to_text_response(
                prompt, system_prompt=system
            )
            await self.capability_worker.speak(response)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PetCare] Lookup error: {e}")
            await self.capability_worker.speak(
                "I couldn't look that up right now. Try again?"
            )

    async def _handle_weight_lookup(self, pet: dict, logs: list):
        """Summarize weight history for a pet."""
        if not pet:
            await self.capability_worker.speak(
                "Which pet's weight would you like to check?"
            )
            return

        weight_entries = [e for e in logs if e.get("type") == "weight"]

        if not weight_entries:
            await self.capability_worker.speak(
                f"I don't have any weight entries for {pet['name']} yet. "
                f"You can say something like '{pet['name']} weighs 48 pounds' to log their weight."
            )
            return

        today = datetime.now().strftime("%Y-%m-%d")
        system = WEIGHT_SUMMARY_PROMPT.format(today=today)

        prompt = (
            f"Pet: {pet['name']} ({pet['species']}, {pet['breed']})\n"
            f"Current recorded weight: {pet.get('weight_lbs', 'unknown')} lbs\n\n"
            f"Weight history entries:\n{json.dumps(weight_entries, indent=2)}"
        )

        try:
            response = self.capability_worker.text_to_text_response(
                prompt, system_prompt=system
            )
            await self.capability_worker.speak(response)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Weight lookup error: {e}"
            )
            await self.capability_worker.speak(
                f"{pet['name']} is currently at {pet.get('weight_lbs', 'unknown')} pounds."
            )

    # ------------------------------------------------------------------
    # Emergency Vet Finder
    # ------------------------------------------------------------------

    async def _handle_emergency_vet(self):
        """Find nearby emergency vets using Google Places API."""
        # Mention saved vet first if available
        saved_vet = self.pet_data.get("vet_name", "")
        saved_phone = self.pet_data.get("vet_phone", "")

        if saved_vet:
            phone_spoken = (
                _fmt_phone_for_speech(saved_phone)
                if saved_phone
                else "no number on file"
            )
            await self.capability_worker.speak(
                f"Your regular vet is {saved_vet} at {phone_spoken}."
            )

        # Check for API key
        if GOOGLE_PLACES_API_KEY == "your_google_places_api_key_here":
            if not saved_vet:
                await self.capability_worker.speak(
                    "I need a Google Places API key to find nearby vets. "
                    "You can add one in your OpenHome settings. "
                    "In the meantime, try searching for 'emergency vet near me' on your phone."
                )
            else:
                await self.capability_worker.speak(
                    "I need a Google Places API key to search for emergency vets nearby. "
                    "You can add one in your OpenHome settings."
                )
            return

        # Get location
        lat = self.pet_data.get("user_lat")
        lon = self.pet_data.get("user_lon")

        if not lat or not lon:
            # Try IP-based location
            await self.capability_worker.speak("Let me check your location first.")
            coords = self._detect_location_by_ip()
            if coords:
                lat = coords["lat"]
                lon = coords["lon"]
                self.pet_data["user_lat"] = lat
                self.pet_data["user_lon"] = lon
                if coords.get("city"):
                    self.pet_data["user_location"] = coords["city"]
                await self._save_json(PETS_FILE, self.pet_data)
            else:
                await self.capability_worker.speak(
                    "I couldn't detect your location. "
                    "Try saying 'update my location' to set it manually."
                )
                return

        await self.capability_worker.speak("Let me find emergency vets near you.")

        try:
            location_str = self.pet_data.get("user_location", "")
            query = (
                f"emergency veterinarian near {location_str}"
                if location_str
                else "emergency veterinarian"
            )

            url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
            params = {
                "query": query,
                "location": f"{lat},{lon}",
                "radius": 16000,
                "key": GOOGLE_PLACES_API_KEY,
            }

            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            results = data.get("results", [])
            if not results:
                await self.capability_worker.speak(
                    "I couldn't find any emergency vets nearby. "
                    "Try searching on your phone or calling your regular vet."
                )
                return

            # Prioritize open locations, take top 3
            open_vets = [
                r for r in results if r.get("opening_hours", {}).get("open_now")
            ]
            closed_vets = [
                r for r in results if not r.get("opening_hours", {}).get("open_now")
            ]
            sorted_results = (open_vets + closed_vets)[:3]

            parts = []
            for r in sorted_results:
                name = r.get("name", "Unknown")
                rating = r.get("rating", "")
                is_open = r.get("opening_hours", {}).get("open_now", False)
                status = "open now" if is_open else "may be closed"

                part = f"{name}, {status}"
                if rating:
                    part += f", rated {rating}"
                parts.append(part)

            count = len(sorted_results)
            await self.capability_worker.speak(
                f"I found {count} emergency vet{'s' if count != 1 else ''} near you. "
                + ". ".join(parts)
                + ". Want the address for any of them?"
            )

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error(
                "[PetCare] Google Places API timeout"
            )
            await self.capability_worker.speak(
                "The vet search timed out. Try again in a moment."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PetCare] Vet search error: {e}")
            await self.capability_worker.speak(
                "I had trouble searching for vets right now. Try again later."
            )

    # ------------------------------------------------------------------
    # Weather Safety Check
    # ------------------------------------------------------------------

    async def _handle_weather(self, intent: dict):
        """Check weather safety for a pet using Open-Meteo API."""
        pet = await self._resolve_pet_async(intent.get("pet_name"))
        if pet is None:
            return

        lat = self.pet_data.get("user_lat")
        lon = self.pet_data.get("user_lon")

        if not lat or not lon:
            coords = self._detect_location_by_ip()
            if coords:
                lat = coords["lat"]
                lon = coords["lon"]
                self.pet_data["user_lat"] = lat
                self.pet_data["user_lon"] = lon
                if coords.get("city"):
                    self.pet_data["user_location"] = coords["city"]
                await self._save_json(PETS_FILE, self.pet_data)
            else:
                await self.capability_worker.speak(
                    "I need your location to check the weather. "
                    "Try saying 'update my location' to set it."
                )
                return

        await self.capability_worker.speak("Let me check the weather for you.")

        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "hourly": "uv_index",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "forecast_days": 1,
            }

            resp = requests.get(url, params=params, timeout=10)
            weather_data = resp.json()

            current = weather_data.get("current", {})
            temp_f = current.get("temperature_2m", 0)
            wind_mph = current.get("wind_speed_10m", 0)
            weather_code = current.get("weather_code", 0)

            # Get UV from hourly data (current hour)
            hourly = weather_data.get("hourly", {})
            uv_values = hourly.get("uv_index", [])
            current_hour = datetime.now().hour
            uv_index = uv_values[current_hour] if current_hour < len(uv_values) else 0

            weather_info = (
                f"Temperature: {temp_f}F, Wind: {wind_mph} mph, "
                f"UV Index: {uv_index}, Weather code: {weather_code}"
            )

            pet_info = (
                f"Pet: {pet['name']}, Species: {pet['species']}, "
                f"Breed: {pet['breed']}, Weight: {pet.get('weight_lbs', 'unknown')} lbs"
            )

            prompt = f"Current weather: {weather_info}\n{pet_info}"

            response = self.capability_worker.text_to_text_response(
                prompt, system_prompt=WEATHER_SYSTEM_PROMPT
            )
            await self.capability_worker.speak(response)

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error("[PetCare] Weather API timeout")
            await self.capability_worker.speak(
                "The weather check timed out. Try again in a moment."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PetCare] Weather error: {e}")
            await self.capability_worker.speak(
                "I had trouble checking the weather right now."
            )

    # ------------------------------------------------------------------
    # Food Recall Checker
    # ------------------------------------------------------------------

    async def _handle_food_recall(self):
        """Check openFDA for recent pet food adverse events."""
        pets = self.pet_data.get("pets", [])
        species_set = set(p.get("species", "").lower() for p in pets)

        await self.capability_worker.speak("Let me check for recent pet food alerts.")

        all_results = []

        for species in species_set:
            if species not in ("dog", "cat"):
                continue
            try:
                url = "https://api.fda.gov/animalandtobacco/event.json"
                params = {
                    "search": f'animal.species:"{species}"',
                    "limit": 5,
                    "sort": "original_receive_date:desc",
                }

                resp = requests.get(url, params=params, timeout=10)

                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    for r in results:
                        products = r.get("product", [])
                        for prod in products:
                            brand = prod.get("brand_name", "Unknown brand")
                            all_results.append(
                                {
                                    "species": species,
                                    "brand": brand,
                                    "date": r.get(
                                        "original_receive_date", "unknown date"
                                    ),
                                }
                            )
                else:
                    self.worker.editor_logging_handler.warning(
                        f"[PetCare] FDA API returned {resp.status_code}"
                    )

            except requests.exceptions.Timeout:
                self.worker.editor_logging_handler.error("[PetCare] FDA API timeout")
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[PetCare] FDA error: {e}")

        if not all_results:
            await self.capability_worker.speak(
                "No new pet food alerts found recently. Looks clear."
            )
            return

        # Summarize with LLM
        pet_names = [p["name"] for p in pets]
        prompt = (
            f"Recent FDA adverse event reports for pets:\n"
            f"{json.dumps(all_results, indent=2)}\n\n"
            f"User's pets: {', '.join(pet_names)}\n"
            "Summarize these reports in 2-3 short spoken sentences. "
            "Mention the brands involved. Don't be alarmist. "
            "If none of them seem to match common pet food brands, say so."
        )

        try:
            response = self.capability_worker.text_to_text_response(prompt)
            await self.capability_worker.speak(response)
        except Exception:
            # Fallback to simple count
            count = len(all_results)
            await self.capability_worker.speak(
                f"I found {count} recent adverse event report{'s' if count != 1 else ''} "
                "in the FDA database. Want more details?"
            )

    # ------------------------------------------------------------------
    # Edit Pet Info
    # ------------------------------------------------------------------

    async def _handle_edit_pet(self, intent: dict):
        """Handle pet edits: add pet, update info, change vet."""
        action = intent.get("action", "")

        if action == "add_pet":
            await self.capability_worker.speak(
                "Let's add a new pet. What's their name?"
            )
            new_pet = await self._collect_pet_info()
            if new_pet:
                self.pet_data.setdefault("pets", []).append(new_pet)
                await self._save_json(PETS_FILE, self.pet_data)
                await self.capability_worker.speak(
                    f"{new_pet['name']} has been added to your pets!"
                )
            else:
                await self.capability_worker.speak("Okay, not adding a new pet.")

        elif action == "change_vet":
            await self.capability_worker.speak("What's your new vet's name?")
            vet_input = await self.capability_worker.user_response()
            if vet_input and not self._is_exit(vet_input):
                vet_name = self._extract_value(
                    vet_input, "Extract the veterinarian's name. Return just the name."
                )
                self.pet_data["vet_name"] = vet_name

                await self.capability_worker.speak("And their phone number?")
                phone_input = await self.capability_worker.user_response()
                if phone_input and not self._is_exit(phone_input):
                    vet_phone = self._extract_value(
                        phone_input,
                        "Extract the phone number as digits only. Return just digits.",
                    )
                    self.pet_data["vet_phone"] = vet_phone

                await self._save_json(PETS_FILE, self.pet_data)
                await self.capability_worker.speak(f"Updated your vet to {vet_name}.")
            else:
                await self.capability_worker.speak(
                    "Okay, keeping your current vet info."
                )

        elif action == "update_weight":
            pet = await self._resolve_pet_async(intent.get("pet_name"))
            if pet:
                await self.capability_worker.speak(
                    f"What's {pet['name']}'s current weight?"
                )
                weight_input = await self.capability_worker.user_response()
                if weight_input and not self._is_exit(weight_input):
                    weight_str = self._extract_value(
                        weight_input,
                        "Extract the weight as a number in pounds. Return just the number.",
                    )
                    try:
                        new_weight = float(weight_str)
                        # Update pet data
                        for p in self.pet_data.get("pets", []):
                            if p["id"] == pet["id"]:
                                p["weight_lbs"] = new_weight
                                break
                        await self._save_json(PETS_FILE, self.pet_data)

                        # Also log it
                        weight_intent = {
                            "pet_name": pet["name"],
                            "activity_type": "weight",
                            "details": f"{new_weight} lbs",
                            "value": new_weight,
                        }
                        await self._handle_log(weight_intent)
                    except (ValueError, TypeError):
                        await self.capability_worker.speak(
                            "I couldn't understand that weight. Try again?"
                        )

        elif action == "update_pet":
            pet = await self._resolve_pet_async(intent.get("pet_name"))
            if pet:
                await self.capability_worker.speak(
                    f"What would you like to update for {pet['name']}? "
                    "You can change their breed, birthday, allergies, or medications."
                )
                update_input = await self.capability_worker.user_response()
                if update_input and not self._is_exit(update_input):
                    update_prompt = (
                        f"The user wants to update {pet['name']}'s info. "
                        f"Current info: {json.dumps(pet)}\n"
                        f"User said: {update_input}\n\n"
                        "Return ONLY valid JSON with the fields to update. "
                        "Only include fields that should change. "
                        "Possible fields: breed, birthday (YYYY-MM-DD), weight_lbs (number), "
                        "allergies (array of strings), medications (array of objects with name and frequency)."
                    )
                    try:
                        raw = self.capability_worker.text_to_text_response(
                            update_prompt
                        )
                        updates = json.loads(_strip_json_fences(raw))
                        for p in self.pet_data.get("pets", []):
                            if p["id"] == pet["id"]:
                                p.update(updates)
                                break
                        await self._save_json(PETS_FILE, self.pet_data)
                        await self.capability_worker.speak(
                            f"Updated {pet['name']}'s info."
                        )
                    except Exception as e:
                        self.worker.editor_logging_handler.error(
                            f"[PetCare] Pet update error: {e}"
                        )
                        await self.capability_worker.speak(
                            "I had trouble updating that. Try being more specific?"
                        )
        elif action == "remove_pet":
            pet = await self._resolve_pet_async(intent.get("pet_name"))
            if pet:
                confirmed = await self.capability_worker.run_confirmation_loop(
                    f"Remove {pet['name']} and all their activity logs? Say yes to confirm."
                )
                if confirmed:
                    self.pet_data["pets"] = [
                        p for p in self.pet_data.get("pets", []) if p["id"] != pet["id"]
                    ]
                    self.activity_log = [
                        e for e in self.activity_log if e.get("pet_id") != pet["id"]
                    ]
                    await self._save_json(PETS_FILE, self.pet_data)
                    await self._save_json(ACTIVITY_LOG_FILE, self.activity_log)
                    await self.capability_worker.speak(
                        f"{pet['name']} has been removed."
                    )
                else:
                    await self.capability_worker.speak(f"Okay, keeping {pet['name']}.")

        elif action == "clear_log":
            confirmed = await self.capability_worker.run_confirmation_loop(
                "Clear all activity logs for all pets? This can't be undone. Say yes to confirm."
            )
            if confirmed:
                self.activity_log = []
                await self._save_json(ACTIVITY_LOG_FILE, self.activity_log)
                await self.capability_worker.speak(
                    "All activity logs have been cleared."
                )
            else:
                await self.capability_worker.speak("Okay, keeping your logs.")

        else:
            await self.capability_worker.speak(
                "I can add a new pet, remove a pet, update pet info, or change your vet. "
                "What would you like to do?"
            )

    # ------------------------------------------------------------------
    # Helper: resolve pet from name
    # ------------------------------------------------------------------

    def _resolve_pet(self, pet_name: str) -> dict:
        """Resolve a pet name to a pet dict. Asks user if ambiguous."""
        pets = self.pet_data.get("pets", [])

        if not pets:
            return None

        # If only one pet, always use it
        if len(pets) == 1:
            return pets[0]

        # If name given, try to match
        if pet_name:
            name_lower = pet_name.lower().strip()
            for p in pets:
                if p["name"].lower() == name_lower:
                    return p
            # Fuzzy: check if name starts with input or vice versa
            for p in pets:
                if p["name"].lower().startswith(name_lower) or name_lower.startswith(
                    p["name"].lower()
                ):
                    return p

        # Multiple pets, no match — we can't block here with user_response
        # since this may be called from sync context. Return first pet as default.
        # The caller should handle ambiguity at a higher level.
        return pets[0]

    async def _resolve_pet_async(self, pet_name: str) -> dict:
        """Resolve a pet, asking the user if ambiguous."""
        pets = self.pet_data.get("pets", [])
        if not pets:
            await self.capability_worker.speak("You don't have any pets set up yet.")
            return None

        if len(pets) == 1:
            return pets[0]

        if pet_name:
            name_lower = pet_name.lower().strip()
            for p in pets:
                if p["name"].lower() == name_lower:
                    return p
            for p in pets:
                if p["name"].lower().startswith(name_lower) or name_lower.startswith(
                    p["name"].lower()
                ):
                    return p

        # Ask user
        names = " or ".join(p["name"] for p in pets)
        await self.capability_worker.speak(f"Which pet? {names}?")
        response = await self.capability_worker.user_response()
        if response and not self._is_exit(response):
            return self._resolve_pet(response)
        return None

    # ------------------------------------------------------------------
    # Helper: trigger context
    # ------------------------------------------------------------------

    def _get_trigger_context(self) -> str:
        """Get the transcription that triggered this ability."""
        initial_request = None
        try:
            initial_request = self.worker.transcription
        except (AttributeError, Exception):
            pass
        if not initial_request:
            try:
                initial_request = self.worker.last_transcription
            except (AttributeError, Exception):
                pass
        return initial_request.strip() if initial_request else ""

    # ------------------------------------------------------------------
    # Helper: extract value from messy voice input
    # ------------------------------------------------------------------

    def _extract_value(self, raw_input: str, instruction: str) -> str:
        """Use LLM to extract a clean value from messy voice input."""
        try:
            result = self.capability_worker.text_to_text_response(
                f"Input: {raw_input}",
                system_prompt=instruction,
            )
            return _strip_json_fences(result).strip().strip('"')
        except Exception:
            return raw_input.strip()

    # ------------------------------------------------------------------
    # Helper: exit detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_exit(text: str) -> bool:
        """Check if user input indicates exit intent."""
        if not text:
            return False
        cleaned = text.lower().strip()
        cleaned = re.sub(r"[^\w\s']", "", cleaned).strip()
        if not cleaned:
            return False
        for word in EXIT_WORDS:
            if word in cleaned:
                return True
        return False

    # ------------------------------------------------------------------
    # Helper: geolocation
    # ------------------------------------------------------------------

    def _detect_location_by_ip(self) -> dict:
        """Auto-detect location using ip-api.com from user's IP."""
        try:
            ip = self.worker.user_socket.client.host
            resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    isp = data.get("isp", "").lower()
                    cloud_indicators = [
                        "amazon",
                        "aws",
                        "google",
                        "microsoft",
                        "azure",
                        "digitalocean",
                    ]
                    if any(c in isp for c in cloud_indicators):
                        self.worker.editor_logging_handler.warning(
                            "[PetCare] Cloud IP detected, location may be inaccurate"
                        )
                    return {
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "city": f"{data.get('city', '')}, {data.get('regionName', '')}",
                    }
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] IP geolocation error: {e}"
            )
        return None

    def _geocode_location(self, location_str: str) -> dict:
        """Convert a city name to lat/lon using Open-Meteo geocoding."""
        try:
            url = "https://geocoding-api.open-meteo.com/v1/search"
            resp = requests.get(
                url, params={"name": location_str, "count": 1}, timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    return {
                        "lat": results[0]["latitude"],
                        "lon": results[0]["longitude"],
                    }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PetCare] Geocoding error: {e}")
        return None

    # ------------------------------------------------------------------
    # Persistence (delete + write pattern for JSON)
    # ------------------------------------------------------------------

    async def _load_json(self, filename: str, default=None):
        """Load a JSON file, returning default if not found or corrupt."""
        if await self.capability_worker.check_if_file_exists(filename, False):
            try:
                raw = await self.capability_worker.read_file(filename, False)
                return json.loads(raw)
            except json.JSONDecodeError:
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Corrupt file {filename}, resetting."
                )
                await self.capability_worker.delete_file(filename, False)
        return default if default is not None else {}

    async def _save_json(self, filename: str, data):
        """Save data using delete-then-write pattern."""
        if await self.capability_worker.check_if_file_exists(filename, False):
            await self.capability_worker.delete_file(filename, False)
        await self.capability_worker.write_file(filename, json.dumps(data), False)
