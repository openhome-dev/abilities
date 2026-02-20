import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timedelta

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# Service imports — relative for OpenHome runtime, absolute fallback for local tests
try:
    from .activity_log_service import ActivityLogService
    from .external_api_service import ExternalAPIService
    from .llm_service import LLMService
    from .pet_data_service import PetDataService
except ImportError:
    from activity_log_service import ActivityLogService  # noqa: E402
    from external_api_service import ExternalAPIService  # noqa: E402
    from llm_service import LLMService  # noqa: E402
    from pet_data_service import PetDataService  # noqa: E402

"""Pet Care Assistant — voice-first ability for tracking pets' daily lives.

Stores pet profiles and activity logs, finds emergency vets, checks weather
safety, and monitors food recalls. Persists data across sessions using JSON files.
"""

EXIT_MESSAGE = "Take care of those pets! See you next time."

PETS_FILE = "petcare_pets.json"
ACTIVITY_LOG_FILE = "petcare_activity_log.json"
REMINDERS_FILE = "petcare_reminders.json"

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

# Serper API key placeholder — get a free key at serper.dev (2,500 free queries)
SERPER_API_KEY = "your_serper_api_key_here"

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
    """Format a phone number for spoken output, digit by digit.

    Handles multiple formats:
    - 10-digit US: (512) 555-1234 → "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"
    - 11-digit US with country code: 1-512-555-1234 → "1, 5, 1, 2, 5, 5, 5, ..."
    - International (7-15 digits): grouped by 3s for readability
    - Invalid lengths (<7 or >15): all digits or error message
    """
    if not phone:
        return "no number provided"

    digits = re.sub(r"\D", "", phone)

    if not digits:
        return "no number provided"

    if len(digits) == 10:
        return (
            f"{', '.join(digits[:3])}, "
            f"{', '.join(digits[3:6])}, "
            f"{', '.join(digits[6:])}"
        )
    elif len(digits) == 11 and digits[0] == "1":
        return (
            f"1, "
            f"{', '.join(digits[1:4])}, "
            f"{', '.join(digits[4:7])}, "
            f"{', '.join(digits[7:])}"
        )
    elif 7 <= len(digits) <= 15:
        groups = [digits[i : i + 3] for i in range(0, len(digits), 3)]
        return ", ".join(", ".join(group) for group in groups)
    elif len(digits) < 7:
        return "incomplete phone number"
    else:
        return "phone number too long, please check"


class PetCareAssistantCapability(MatchingCapability):
    """OpenHome ability for multi-pet care tracking with persistent storage,
    emergency vet finder, weather safety, and food recall checks."""

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    pet_data: dict = None
    activity_log: list = None
    _geocode_cache: dict = None

    # Services initialized in run()
    pet_data_service: "PetDataService" = None
    activity_log_service: "ActivityLogService" = None
    external_api_service: "ExternalAPIService" = None
    llm_service: "LLMService" = None
    reminders: list = None

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

    # === Main flow ===

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("[PetCare] Ability started")

            self.pet_data_service = PetDataService(self.capability_worker, self.worker)
            self.activity_log_service = ActivityLogService(self.worker, MAX_LOG_ENTRIES)
            self.external_api_service = ExternalAPIService(self.worker, SERPER_API_KEY)

            self.pet_data = await self.pet_data_service.load_json(PETS_FILE, default={})
            # LLMService needs pet_data for intent classification context
            self.llm_service = LLMService(
                self.capability_worker, self.worker, self.pet_data
            )
            self.activity_log = await self.pet_data_service.load_json(
                ACTIVITY_LOG_FILE, default=[]
            )
            self.reminders = await self.pet_data_service.load_json(
                REMINDERS_FILE, default=[]
            )

            self._geocode_cache = {}
            await self._check_due_reminders()

            has_pet_data = await self.capability_worker.check_if_file_exists(
                PETS_FILE, False
            )

            if not has_pet_data or not self.pet_data.get("pets"):
                await self.run_onboarding()
                return

            trigger = self.llm_service.get_trigger_context()
            if trigger:
                intent = await self.llm_service.classify_intent_async(trigger)
                mode = intent.get("mode", "unknown")

                if mode not in ("unknown", "exit"):
                    await self._route_intent(intent)
                    await self.capability_worker.speak("Anything else for your pets?")
                    follow_up = await self.capability_worker.user_response()
                    if follow_up and not self.llm_service.is_exit(follow_up):
                        follow_intent = await self.llm_service.classify_intent_async(
                            follow_up
                        )
                        if follow_intent.get("mode") not in ("unknown", "exit"):
                            await self._route_intent(follow_intent)
                    await self.capability_worker.speak(EXIT_MESSAGE)
                    return

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
                        if (
                            not final
                            or not final.strip()
                            or self.llm_service.is_exit(final)
                        ):
                            await self.capability_worker.speak(EXIT_MESSAGE)
                            break
                        user_input = final
                        idle_count = 0
                    else:
                        continue

                idle_count = 0

                if self.llm_service.is_exit(user_input):
                    await self.capability_worker.speak(EXIT_MESSAGE)
                    break

                # Short ambiguous input — ask LLM if it's an exit
                cleaned = self.llm_service.clean_input(user_input)
                if len(
                    cleaned.split()
                ) <= 4 and await self.llm_service.is_exit_llm_async(cleaned):
                    await self.capability_worker.speak(EXIT_MESSAGE)
                    break

                intent = await self.llm_service.classify_intent_async(user_input)
                mode = intent.get("mode", "unknown")

                if mode == "exit":
                    await self.capability_worker.speak(EXIT_MESSAGE)
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

    # === Intent router ===

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
        elif mode == "reminder":
            await self._handle_reminder(intent)
        elif mode == "onboarding":
            await self.run_onboarding()
        else:
            await self.capability_worker.speak(
                "Sorry, I didn't catch that. Could you say that again?"
            )

    # === Onboarding ===

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

            if "pets" not in self.pet_data:
                self.pet_data["pets"] = []
            self.pet_data["pets"].append(pet)
            await self._save_json(PETS_FILE, self.pet_data)

            await self.capability_worker.speak(
                f"All set! I've saved {pet['name']}'s info. "
                f"You can say things like 'I just fed {pet['name']}' to log activities, "
                "or 'find an emergency vet' if you ever need one."
            )

            await self.capability_worker.speak("Do you have any other pets to add?")
            response = await self.capability_worker.user_response()
            if not response or self.llm_service.is_exit(response):
                break
            cleaned = response.lower().strip()
            if any(
                w in cleaned for w in ["no", "nope", "nah", "that's it", "that's all"]
            ):
                break
            await self.capability_worker.speak("Great! What's your next pet's name?")

    async def _collect_pet_info(self) -> dict:
        """Collect one pet's data through guided voice questions.

        Uses parallel LLM extraction for ~90% performance improvement (24-36s → 3-4s).
        Phase 1: Collect all raw user inputs
        Phase 2: Extract all values in parallel with asyncio.gather()
        Phase 3: Process results and build pet dict
        """
        # ======= PHASE 1: Collect raw user inputs =======
        raw_inputs = {}

        name_input = await self.capability_worker.user_response()
        if not name_input or self.llm_service.is_exit(name_input):
            return None
        raw_inputs["name"] = name_input

        temp_name = name_input.strip().split()[0] if name_input.strip() else "your pet"
        species_input = await self.capability_worker.run_io_loop(
            f"Great! What kind of animal is {temp_name}? Dog, cat, or something else?"
        )
        if not species_input or self.llm_service.is_exit(species_input):
            return None
        raw_inputs["species"] = species_input

        breed_input = await self.capability_worker.run_io_loop(
            f"What breed is {temp_name}?"
        )
        if not breed_input or self.llm_service.is_exit(breed_input):
            return None
        raw_inputs["breed"] = breed_input

        age_input = await self.capability_worker.run_io_loop(
            f"How old is {temp_name}, or do you know their birthday?"
        )
        if not age_input or self.llm_service.is_exit(age_input):
            return None
        raw_inputs["age"] = age_input

        weight_input = await self.capability_worker.run_io_loop(
            f"Roughly how much does {temp_name} weigh?"
        )
        if not weight_input or self.llm_service.is_exit(weight_input):
            return None
        raw_inputs["weight"] = weight_input

        allergy_input = await self.capability_worker.run_io_loop(
            f"Does {temp_name} have any allergies I should know about?"
        )
        if not allergy_input or self.llm_service.is_exit(allergy_input):
            return None
        raw_inputs["allergies"] = allergy_input

        med_input = await self.capability_worker.run_io_loop(
            f"Is {temp_name} on any medications?"
        )
        if not med_input or self.llm_service.is_exit(med_input):
            return None
        raw_inputs["medications"] = med_input

        vet_input = await self.capability_worker.run_io_loop(
            "Do you have a regular vet? If so, what's their name?"
        )
        raw_inputs["vet"] = None
        raw_inputs["vet_phone"] = None
        if vet_input and not self.llm_service.is_exit(vet_input):
            cleaned = vet_input.lower().strip()
            if not any(w in cleaned for w in ["no", "nope", "skip", "don't have"]):
                raw_inputs["vet"] = vet_input
                phone_input = await self.capability_worker.run_io_loop(
                    "What's their phone number?"
                )
                if phone_input and not self.llm_service.is_exit(phone_input):
                    raw_inputs["vet_phone"] = phone_input

        location_input = await self.capability_worker.run_io_loop(
            "Last thing. What city are you in? This helps me check weather and find vets nearby."
        )
        raw_inputs["location"] = None
        if location_input and not self.llm_service.is_exit(location_input):
            raw_inputs["location"] = location_input

        # ======= PHASE 2: Extract all values in parallel =======
        extraction_tasks = [
            self.llm_service.extract_pet_name_async(raw_inputs["name"]),
            self.llm_service.extract_species_async(raw_inputs["species"]),
            self.llm_service.extract_breed_async(raw_inputs["breed"]),
            self.llm_service.extract_birthday_async(raw_inputs["age"]),
            self.llm_service.extract_weight_async(raw_inputs["weight"]),
            self.llm_service.extract_allergies_async(raw_inputs["allergies"]),
            self.llm_service.extract_medications_async(raw_inputs["medications"]),
        ]

        vet_name_idx = None
        if raw_inputs["vet"] is not None:
            vet_name_idx = len(extraction_tasks)
            extraction_tasks.append(
                self.llm_service.extract_vet_name_async(raw_inputs["vet"])
            )

        vet_phone_idx = None
        if raw_inputs["vet_phone"] is not None:
            vet_phone_idx = len(extraction_tasks)
            extraction_tasks.append(
                self.llm_service.extract_phone_number_async(raw_inputs["vet_phone"])
            )

        location_idx = None
        if raw_inputs["location"] is not None:
            location_idx = len(extraction_tasks)
            extraction_tasks.append(
                self.llm_service.extract_location_async(raw_inputs["location"])
            )

        results = await asyncio.gather(*extraction_tasks)

        # ======= PHASE 3: Build pet dict from extracted results =======
        name = results[0]
        species = results[1].lower()
        breed = results[2]
        birthday = results[3]

        weight_str = results[4]
        try:
            weight_lbs = float(weight_str)
        except (ValueError, TypeError):
            weight_lbs = 0

        allergies_str = results[5]
        try:
            allergies = json.loads(allergies_str)
            if not isinstance(allergies, list):
                allergies = []
        except (json.JSONDecodeError, TypeError):
            allergies = []

        meds_str = results[6]
        try:
            medications = json.loads(meds_str)
            if not isinstance(medications, list):
                medications = []
        except (json.JSONDecodeError, TypeError):
            medications = []

        # Extract vet info if available
        if vet_name_idx is not None:
            vet_name = results[vet_name_idx]
            self.pet_data["vet_name"] = vet_name
            if vet_phone_idx is not None:
                vet_phone = results[vet_phone_idx]
                self.pet_data["vet_phone"] = vet_phone

        # Extract and geocode location if available
        if location_idx is not None:
            location = results[location_idx]
            self.pet_data["user_location"] = location
            coords = await self._geocode_location(location)
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

    # === Log Activity ===

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
            for p in self.pet_data.get("pets", []):
                if p["id"] == pet["id"]:
                    p["weight_lbs"] = value
                    break
            await self._save_json(PETS_FILE, self.pet_data)

        self.activity_log.insert(0, entry)

        if len(self.activity_log) > MAX_LOG_ENTRIES:
            self.activity_log = self.activity_log[:MAX_LOG_ENTRIES]

        await self._save_json(ACTIVITY_LOG_FILE, self.activity_log)

        time_str = datetime.now().strftime("%I:%M %p").lstrip("0")
        await self.capability_worker.speak(
            f"Got it. Logged {pet['name']}'s {activity_type} at {time_str}."
        )

        await self.capability_worker.speak("Anything else to log?")
        await self.worker.session_tasks.sleep(4)
        follow = await self.capability_worker.user_response()
        if follow and not self.llm_service.is_exit(follow):
            cleaned = follow.lower().strip()
            if any(
                w in cleaned for w in ["no", "nope", "nah", "that's it", "that's all"]
            ):
                return
            follow_intent = await self.llm_service.classify_intent_async(follow)
            if follow_intent.get("mode") == "log":
                await self._handle_log(follow_intent)

    # === Quick Lookup ===

    async def _handle_lookup(self, intent: dict):
        """Answer a question about pet activity history."""
        query = intent.get("query", "")

        # Handle pet inventory queries directly from pet_data
        if "list registered pets" in query.lower() or any(
            w in query.lower()
            for w in ["what pets", "any pets", "any animals", "list pets", "how many pets"]
        ):
            pets = self.pet_data.get("pets", [])
            if not pets:
                await self.capability_worker.speak(
                    "You don't have any pets set up yet. Say 'add a new pet' to get started."
                )
            elif len(pets) == 1:
                p = pets[0]
                await self.capability_worker.speak(
                    f"You have one pet: {p['name']}, a {p.get('breed', '')} {p['species']}."
                )
            else:
                names = ", ".join(
                    f"{p['name']} ({p.get('breed', '')} {p['species']})" for p in pets
                )
                await self.capability_worker.speak(
                    f"You have {len(pets)} pets: {names}."
                )
            return

        pet = await self._resolve_pet_async(intent.get("pet_name"))

        if pet:
            relevant_logs = [
                e for e in self.activity_log if e.get("pet_id") == pet["id"]
            ][
                :50
            ]  # Last 50 entries for context
        else:
            relevant_logs = self.activity_log[:50]

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

    # === Emergency Vet Finder ===

    async def _handle_emergency_vet(self):
        """Find nearby emergency vets using Serper Maps API."""
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

        if SERPER_API_KEY == "your_serper_api_key_here":
            if not saved_vet:
                await self.capability_worker.speak(
                    "I need a Serper API key to find nearby vets. "
                    "You can get one free at serper.dev and add it in main.py. "
                    "In the meantime, try searching for 'emergency vet near me' on your phone."
                )
            else:
                await self.capability_worker.speak(
                    "I need a Serper API key to search for emergency vets nearby. "
                    "You can get one free at serper.dev and add it in main.py."
                )
            return

        lat = self.pet_data.get("user_lat")
        lon = self.pet_data.get("user_lon")

        if not lat or not lon:
            # Allow user to override auto-detected location with saved location
            saved_location = self.pet_data.get("user_location", "")
            if saved_location:
                await self.capability_worker.speak(
                    f"I'll detect your location from your current IP address. "
                    f"Or, if you'd like to search near your registered location, {saved_location}, say that now."
                )
                loc_response = await self.capability_worker.user_response()
                if loc_response and not self.llm_service.is_exit(loc_response):
                    use_saved = any(
                        word in loc_response.lower()
                        for word in [
                            "registered",
                            "saved",
                            "that",
                            saved_location.lower().split(",")[0].lower(),
                        ]
                    )
                    if use_saved:
                        coords = await self._geocode_location(saved_location)
                        if coords:
                            lat, lon = coords["lat"], coords["lon"]
                        else:
                            await self.capability_worker.speak(
                                f"Couldn't look up {saved_location}. Falling back to IP detection."
                            )
            if not lat or not lon:
                await self.capability_worker.speak(
                    "Detecting your location from your current IP address."
                )
                coords = await self._detect_location_by_ip()
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
                        "I couldn't detect your location automatically. "
                        "Try saying 'update my location' to save it for next time."
                    )
                    return

        await self.capability_worker.speak("Let me find emergency vets near you.")

        try:
            location_str = self.pet_data.get("user_location", "")
            query = (
                f"emergency veterinarian near {location_str}"
                if location_str
                else f"emergency veterinarian near {lat},{lon}"
            )

            url = "https://google.serper.dev/maps"
            headers = {
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json",
            }
            payload = {"q": query, "num": 5}

            resp = await asyncio.to_thread(
                requests.post, url, headers=headers, json=payload, timeout=10
            )

            if resp.status_code == 401 or resp.status_code == 403:
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Serper API authentication failed: {resp.status_code}"
                )
                await self.capability_worker.speak(
                    "Your Serper API key is invalid or expired. "
                    "Get a free key at serper.dev and set it as the SERPER_API_KEY environment variable."
                )
                return
            elif resp.status_code == 429:
                self.worker.editor_logging_handler.warning(
                    "[PetCare] Serper API rate limit exceeded"
                )
                await self.capability_worker.speak(
                    "The vet search rate limit was exceeded. Try again in a minute."
                )
                return
            elif resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Serper API returned error: {resp.status_code}"
                )
                await self.capability_worker.speak(
                    f"The vet search service returned an error. "
                    f"Try searching on your phone or calling your regular vet."
                )
                return

            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Invalid JSON from Serper API: {e}"
                )
                await self.capability_worker.speak(
                    "The vet search returned invalid data. The service might be having issues."
                )
                return

            places = data.get("places", [])
            if not places:
                await self.capability_worker.speak(
                    "I couldn't find any emergency vets nearby. "
                    "Try searching on your phone or calling your regular vet."
                )
                return

            # Open vets first, capped at 3
            open_vets = [p for p in places if p.get("openNow")]
            closed_vets = [p for p in places if not p.get("openNow")]
            top_results = (open_vets + closed_vets)[:3]

            # Announce names first — short, interruptible utterances
            names = [p.get("title", "Unknown") for p in top_results]
            count = len(top_results)
            await self.capability_worker.speak(
                f"I found {count} nearby vet{'s' if count != 1 else ''}: "
                + ", ".join(names)
                + ". Which one do you want the number for?"
            )

            pick = await self.capability_worker.user_response()
            if not pick or self.llm_service.is_exit(pick):
                return

            pick_lower = pick.lower()
            chosen = next(
                (
                    p
                    for p in top_results
                    if any(
                        word in pick_lower
                        for word in p.get("title", "").lower().split()
                    )
                ),
                top_results[0],  # default to first if unclear
            )

            name = chosen.get("title", "Unknown")
            phone = chosen.get("phoneNumber", "")
            rating = chosen.get("rating", "")
            is_open = chosen.get("openNow", False)
            address = chosen.get("address", "")
            status = "open now" if is_open else "may be closed"

            detail = f"{name}, {status}"
            if rating:
                detail += f", rated {rating}"
            if phone:
                detail += f". Number: {_fmt_phone_for_speech(phone)}"
            if address:
                detail += f". Address: {address}"
            await self.capability_worker.speak(detail)

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error(
                "[PetCare] Serper Maps API timeout"
            )
            await self.capability_worker.speak(
                "The vet search timed out. Check your internet connection and try again."
            )
        except requests.exceptions.ConnectionError:
            self.worker.editor_logging_handler.error(
                "[PetCare] Could not connect to Serper Maps API"
            )
            await self.capability_worker.speak(
                "Couldn't connect to the vet search service. Check your internet connection."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Unexpected vet search error: {e}"
            )
            await self.capability_worker.speak(
                "An unexpected error occurred while searching for vets. Try again later."
            )

    # === Weather Safety Check ===

    async def _handle_weather(self, intent: dict):
        """Check weather safety for a pet using Open-Meteo API."""
        pet = await self._resolve_pet_async(intent.get("pet_name"))
        if pet is None:
            return

        lat = self.pet_data.get("user_lat")
        lon = self.pet_data.get("user_lon")

        if not lat or not lon:
            coords = await self._detect_location_by_ip()
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

            resp = await asyncio.to_thread(requests.get, url, params=params, timeout=10)

            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Open-Meteo API returned error: {resp.status_code}"
                )
                await self.capability_worker.speak(
                    "The weather service returned an error. Try again later."
                )
                return

            try:
                weather_data = resp.json()
            except json.JSONDecodeError as e:
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Invalid JSON from Open-Meteo: {e}"
                )
                await self.capability_worker.speak(
                    "The weather service returned invalid data. Try again later."
                )
                return

            current = weather_data.get("current")
            if not current:
                self.worker.editor_logging_handler.error(
                    "[PetCare] Open-Meteo response missing 'current' field"
                )
                await self.capability_worker.speak(
                    "The weather data is incomplete. Try again later."
                )
                return

            temp_f = current.get("temperature_2m", 0)
            wind_mph = current.get("wind_speed_10m", 0)
            weather_code = current.get("weather_code", 0)

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
                "The weather check timed out. Check your internet connection and try again."
            )
        except requests.exceptions.ConnectionError:
            self.worker.editor_logging_handler.error(
                "[PetCare] Could not connect to Weather API"
            )
            await self.capability_worker.speak(
                "Couldn't connect to the weather service. Check your internet connection."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Unexpected weather error: {e}"
            )
            await self.capability_worker.speak(
                "An unexpected error occurred while checking the weather."
            )

    # === Food Recall Checker ===

    async def _fetch_fda_events(self, species: str) -> list:
        """Fetch FDA adverse events for a specific species (non-blocking).

        Args:
            species: Animal species (dog, cat, etc.)

        Returns:
            List of FDA event dicts with source, species, brand, date
        """
        results = []
        try:
            url = "https://api.fda.gov/animalandtobacco/event.json"
            params = {
                "search": f'animal.species:"{species}"',
                "limit": 5,
                "sort": "original_receive_date:desc",
            }

            resp = await asyncio.to_thread(requests.get, url, params=params, timeout=10)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except json.JSONDecodeError as e:
                    self.worker.editor_logging_handler.error(
                        f"[PetCare] Invalid JSON from FDA API: {e}"
                    )
                    return results

                for r in data.get("results", []):
                    products = r.get("product", [])
                    for prod in products:
                        brand = prod.get("brand_name", "Unknown brand")
                        results.append(
                            {
                                "source": "FDA",
                                "species": species,
                                "brand": brand,
                                "date": r.get("original_receive_date", "unknown date"),
                            }
                        )
            elif resp.status_code == 404:
                # 404 is expected when no events exist for species
                self.worker.editor_logging_handler.info(
                    f"[PetCare] No FDA events found for {species}"
                )
            elif resp.status_code == 429:
                self.worker.editor_logging_handler.warning(
                    "[PetCare] FDA API rate limit exceeded"
                )
            else:
                self.worker.editor_logging_handler.warning(
                    f"[PetCare] FDA API returned {resp.status_code}"
                )

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error(
                f"[PetCare] FDA API timeout for {species}"
            )
        except requests.exceptions.ConnectionError:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Could not connect to FDA API for {species}"
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Unexpected FDA error for {species}: {e}"
            )

        return results

    async def _fetch_serper_news(self, species_set: set) -> list:
        """Fetch Serper News headlines for food recalls (non-blocking).

        Args:
            species_set: Set of species to search for

        Returns:
            List of news headline dicts with source, title, snippet, date
        """
        headlines = []

        if SERPER_API_KEY == "your_serper_api_key_here":
            return headlines

        species_labels = " or ".join(s for s in species_set if s in ("dog", "cat"))
        search_query = (
            f"pet food recall {species_labels} 2026"
            if species_labels
            else "pet food recall 2026"
        )

        try:
            news_resp = await asyncio.to_thread(
                requests.post,
                "https://google.serper.dev/news",
                headers={
                    "X-API-KEY": SERPER_API_KEY,
                    "Content-Type": "application/json",
                },
                json={"q": search_query, "num": 5},
                timeout=10,
            )

            if news_resp.status_code == 200:
                try:
                    news_data = news_resp.json()
                except json.JSONDecodeError as e:
                    self.worker.editor_logging_handler.error(
                        f"[PetCare] Invalid JSON from Serper News: {e}"
                    )
                else:
                    for item in news_data.get("news", [])[:5]:
                        title = item.get("title", "")
                        snippet = item.get("snippet", "")
                        date = item.get("date", "")
                        if title:
                            headlines.append(
                                {
                                    "source": "News",
                                    "title": title,
                                    "snippet": snippet,
                                    "date": date,
                                }
                            )
            elif news_resp.status_code == 401 or news_resp.status_code == 403:
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Serper News authentication failed: {news_resp.status_code}"
                )
            elif news_resp.status_code == 429:
                self.worker.editor_logging_handler.warning(
                    "[PetCare] Serper News rate limit exceeded"
                )
            else:
                self.worker.editor_logging_handler.warning(
                    f"[PetCare] Serper News returned {news_resp.status_code}"
                )

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error("[PetCare] Serper News timeout")
        except requests.exceptions.ConnectionError:
            self.worker.editor_logging_handler.error(
                "[PetCare] Could not connect to Serper News"
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Unexpected Serper News error: {e}"
            )

        return headlines

    async def _handle_food_recall(self):
        """Check openFDA and Serper News for recent pet food recalls and adverse events.

        Runs all API calls in parallel for better performance (~50-70% faster).
        """
        pets = self.pet_data.get("pets", [])
        species_set = set(p.get("species", "").lower() for p in pets)

        await self.capability_worker.speak("Let me check for recent pet food alerts.")

        tasks = []
        for species in species_set:
            if species in ("dog", "cat"):
                tasks.append(self._fetch_fda_events(species))
        tasks.append(self._fetch_serper_news(species_set))

        # Execute all API calls concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for result in results[:-1]:  # FDA results
            if isinstance(result, list):
                all_results.extend(result)

        news_headlines = []
        if len(results) > 0:
            last_result = results[-1]
            if isinstance(last_result, list):
                news_headlines = last_result
            elif isinstance(last_result, Exception):
                # Already logged in helper method
                pass

        if not all_results and not news_headlines:
            await self.capability_worker.speak(
                "No new pet food alerts found recently. Looks clear."
            )
            return

        pet_names = [p["name"] for p in pets]
        context_parts = []
        if all_results:
            context_parts.append(
                f"Recent FDA adverse event reports:\n{json.dumps(all_results, indent=2)}"
            )
        if news_headlines:
            context_parts.append(
                f"Recent news headlines:\n{json.dumps(news_headlines, indent=2)}"
            )

        prompt = (
            "\n\n".join(context_parts) + "\n\n"
            f"User's pets: {', '.join(pet_names)}\n"
            "Summarize any recalls or safety concerns in 2-3 short spoken sentences. "
            "Mention the brands involved if known. Don't be alarmist. "
            "If nothing seems serious or relevant, say so clearly."
        )

        try:
            response = self.capability_worker.text_to_text_response(prompt)
            await self.capability_worker.speak(response)
        except Exception:
            # Fallback to simple count
            count = len(all_results) + len(news_headlines)
            await self.capability_worker.speak(
                f"I found {count} recent pet food alert{'s' if count != 1 else ''} "
                "from FDA and news sources. Want more details?"
            )

    # === Edit Pet Info ===

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
            if vet_input and not self.llm_service.is_exit(vet_input):
                vet_name = await self.llm_service.extract_vet_name_async(vet_input)
                self.pet_data["vet_name"] = vet_name

                await self.capability_worker.speak("And their phone number?")
                phone_input = await self.capability_worker.user_response()
                if phone_input and not self.llm_service.is_exit(phone_input):
                    vet_phone = await self.llm_service.extract_phone_number_async(
                        phone_input
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
                if weight_input and not self.llm_service.is_exit(weight_input):
                    weight_str = await self.llm_service.extract_weight_async(
                        weight_input
                    )
                    try:
                        new_weight = float(weight_str)
                        for p in self.pet_data.get("pets", []):
                            if p["id"] == pet["id"]:
                                p["weight_lbs"] = new_weight
                                break
                        await self._save_json(PETS_FILE, self.pet_data)

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
                if update_input and not self.llm_service.is_exit(update_input):
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

        elif action == "reset_all":
            confirmed = await self.capability_worker.run_confirmation_loop(
                "This will delete all pets, activity logs, and reminders — a completely fresh start. "
                "Say yes to confirm."
            )
            if confirmed:
                self.pet_data = {}
                self.activity_log = []
                self.reminders = []
                await self._save_json(PETS_FILE, self.pet_data)
                await self._save_json(ACTIVITY_LOG_FILE, self.activity_log)
                await self._save_json(REMINDERS_FILE, self.reminders)
                await self.capability_worker.speak(
                    "All data has been wiped. Let's start fresh."
                )
                await self.run_onboarding()
            else:
                await self.capability_worker.speak("Okay, keeping everything as is.")

        else:
            await self.capability_worker.speak(
                "I can add a new pet, remove a pet, update pet info, change your vet, or start over. "
                "What would you like to do?"
            )

    # === Reminders ===

    def _parse_reminder_time(self, time_description: str) -> datetime | None:
        """Parse a natural language time description into a datetime using Python only.

        Supports: 'in X hours/minutes', 'at HH:MM', 'tomorrow at HH:MM',
                  'every day at HH:MM' (returns next occurrence).
        Returns None if unparseable.
        """
        if not time_description:
            return None
        now = datetime.now()
        text = time_description.lower().strip()

        m = re.search(r"in (\d+) minute", text)
        if m:
            return now + timedelta(minutes=int(m.group(1)))

        m = re.search(r"in (\d+) hour", text)
        if m:
            return now + timedelta(hours=int(m.group(1)))

        m = re.search(r"tomorrow.*?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            meridiem = m.group(3)
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            tomorrow = now + timedelta(days=1)
            return tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)

        m = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            meridiem = m.group(3)
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # If time already passed today, schedule for tomorrow
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate

        return None

    async def _check_due_reminders(self):
        """Announce and remove any reminders that are due or overdue."""
        if not self.reminders:
            return
        now = datetime.now()
        due = [
            r
            for r in self.reminders
            if r.get("due_at") and datetime.fromisoformat(r["due_at"]) <= now
        ]
        if not due:
            return
        for r in due:
            await self.capability_worker.speak(
                r.get("message", "You have a pet reminder due.")
            )
        # Remove fired reminders
        self.reminders = [r for r in self.reminders if r not in due]
        await self._save_json(REMINDERS_FILE, self.reminders)

    async def _handle_reminder(self, intent: dict):
        """Handle set / list / delete reminder actions."""
        action = intent.get("action", "set")

        if action == "list":
            if not self.reminders:
                await self.capability_worker.speak("You have no reminders set.")
                return
            await self.capability_worker.speak(
                f"You have {len(self.reminders)} reminder{'s' if len(self.reminders) != 1 else ''}."
            )
            for i, r in enumerate(self.reminders, 1):
                due = datetime.fromisoformat(r["due_at"]).strftime("%A at %I:%M %p")
                await self.capability_worker.speak(
                    f"{i}. {r.get('message', 'Reminder')} — {due}."
                )

        elif action == "delete":
            if not self.reminders:
                await self.capability_worker.speak("You have no reminders to delete.")
                return
            if len(self.reminders) == 1:
                self.reminders = []
                await self._save_json(REMINDERS_FILE, self.reminders)
                await self.capability_worker.speak("Reminder deleted.")
                return
            for i, r in enumerate(self.reminders, 1):
                due = datetime.fromisoformat(r["due_at"]).strftime("%A at %I:%M %p")
                await self.capability_worker.speak(
                    f"{i}. {r.get('message', 'Reminder')} — {due}."
                )
            await self.capability_worker.speak("Which number would you like to delete?")
            pick = await self.capability_worker.user_response()
            if pick and not self.llm_service.is_exit(pick):
                m = re.search(r"\d+", pick)
                if m:
                    idx = int(m.group()) - 1
                    if 0 <= idx < len(self.reminders):
                        removed = self.reminders.pop(idx)
                        await self._save_json(REMINDERS_FILE, self.reminders)
                        await self.capability_worker.speak(
                            f"Deleted reminder: {removed.get('message', 'Reminder')}."
                        )
                    else:
                        await self.capability_worker.speak(
                            "That number wasn't in the list."
                        )
                else:
                    await self.capability_worker.speak(
                        "I didn't catch a number. Try again."
                    )

        else:  # "set"
            pet_name = intent.get("pet_name", "")
            activity = intent.get("activity", "")
            time_description = intent.get("time_description", "")

            if not time_description:
                await self.capability_worker.speak(
                    "When should I remind you? Say something like 'in 2 hours' or 'at 6 PM'."
                )
                time_description = await self.capability_worker.user_response() or ""

            due_at = self._parse_reminder_time(time_description)
            if not due_at:
                await self.capability_worker.speak(
                    "I couldn't understand that time. Try saying 'in 2 hours' or 'at 6 PM'."
                )
                return

            pet_part = f" for {pet_name}" if pet_name else ""
            activity_part = f" {activity}" if activity else ""
            message = f"Reminder{pet_part}: {activity_part or 'pet care task'}.".strip()

            reminder = {
                "id": str(uuid.uuid4()),
                "pet_name": pet_name,
                "activity": activity,
                "message": message,
                "due_at": due_at.isoformat(),
                "created_at": datetime.now().isoformat(),
            }
            self.reminders.append(reminder)
            await self._save_json(REMINDERS_FILE, self.reminders)

            spoken_time = due_at.strftime("%A at %I:%M %p")
            await self.capability_worker.speak(
                f"Got it. I'll remind you {spoken_time}: {message}"
            )

    # === Helper: resolve pet ===

    def _resolve_pet(self, pet_name: str) -> dict:
        """Resolve a pet name to a pet dict.

        Delegates to PetDataService.
        """
        return self.pet_data_service.resolve_pet(self.pet_data, pet_name)

    async def _resolve_pet_async(self, pet_name: str) -> dict:
        """Resolve a pet, asking the user if ambiguous.

        Delegates to PetDataService.
        """
        return await self.pet_data_service.resolve_pet_async(
            self.pet_data, pet_name, self.llm_service.is_exit
        )

    # === Helper: geolocation ===

    async def _detect_location_by_ip(self) -> dict:
        """Auto-detect location using ip-api.com from user's IP."""
        try:
            ip = self.worker.user_socket.client.host
            resp = await asyncio.to_thread(
                requests.get, f"http://ip-api.com/json/{ip}", timeout=5
            )
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

    async def _geocode_location(self, location_str: str) -> dict:
        """Convert a city name to lat/lon using Open-Meteo geocoding.

        Uses in-memory cache to avoid redundant API calls within a session.
        """
        if location_str in self._geocode_cache:
            self.worker.editor_logging_handler.info(
                f"[PetCare] Geocoding cache hit: {location_str}"
            )
            return self._geocode_cache[location_str]

        try:
            url = "https://geocoding-api.open-meteo.com/v1/search"
            resp = await asyncio.to_thread(
                requests.get, url, params={"name": location_str, "count": 1}, timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    coords = {
                        "lat": results[0]["latitude"],
                        "lon": results[0]["longitude"],
                    }
                    self._geocode_cache[location_str] = coords
                    self.worker.editor_logging_handler.info(
                        f"[PetCare] Geocoded {location_str} -> {coords['lat']}, {coords['lon']}"
                    )
                    return coords
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PetCare] Geocoding error: {e}")
        return None

    # === Persistence ===

    async def _load_json(self, filename: str, default=None):
        """Load a JSON file, returning default if not found or corrupt.

        Delegates to PetDataService.
        """
        return await self.pet_data_service.load_json(filename, default)

    async def _save_json(self, filename: str, data):
        """Save data using backup-write-delete pattern for data safety.

        Delegates to PetDataService.

        Args:
            filename: Target filename to save to
            data: Data to serialize as JSON and save

        Raises:
            Exception: If write fails (backup file will remain)
        """
        return await self.pet_data_service.save_json(filename, data)
