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


def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences from LLM output (e.g. ```json ... ```)."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


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
        groups = [digits[i: i + 3] for i in range(0, len(digits), 3)]
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
    # Stash for a command embedded in a "no more pets" response during onboarding
    _pending_intent_text: str = None

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

    def _is_hard_exit(self, text: str) -> bool:
        """Exit check for onboarding — ignores 'no'/'done'/'bye' etc.

        Only matches explicit abort/reset commands so that 'no' to 'any allergies?'
        is treated as an answer, not an exit.
        """
        if not text:
            return False
        cleaned = re.sub(r"[^\w\s']", "", text.lower().strip())
        # Single-word abort commands
        if any(w in cleaned.split() for w in ["stop", "quit", "exit", "cancel"]):
            return True
        # Reset/restart phrases
        reset_phrases = [
            "start over",
            "wanna start over",
            "want to start over",
            "start from scratch",
            "restart",
            "reset everything",
            "start from beginning",
        ]
        return any(phrase in cleaned for phrase in reset_phrases)

    # === Main flow ===

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("[PetCare] Ability started")

            self.pet_data_service = PetDataService(self.capability_worker, self.worker)
            self.activity_log_service = ActivityLogService(self.worker, MAX_LOG_ENTRIES)
            self.external_api_service = ExternalAPIService(self.worker, SERPER_API_KEY)

            self.pet_data = await self.pet_data_service.load_json(PETS_FILE, default={})
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
            self._corrected_name = None
            await self._check_due_reminders()

            trigger = self.llm_service.get_trigger_context()

            has_pet_data = await self.capability_worker.check_if_file_exists(
                PETS_FILE, False
            )

            if not has_pet_data or not self.pet_data.get("pets"):
                await self.run_onboarding(initial_context=trigger)
                if not self.pet_data.get("pets"):
                    await self.capability_worker.speak(EXIT_MESSAGE)
                    return
                # If the user embedded a command in their "no more pets" answer
                # (e.g. "No, is it safe to walk Luna?"), handle it now instead of
                # prompting "What would you like to do?" and making them repeat.
                if self._pending_intent_text:
                    pending = self._pending_intent_text
                    self._pending_intent_text = None
                    pending_intent = await self.llm_service.classify_intent_async(
                        pending
                    )
                    if pending_intent.get("mode") not in ("unknown", "exit"):
                        await self._route_intent(pending_intent)
                    else:
                        await self.capability_worker.speak(
                            "What would you like to do? You can log activities, "
                            "look up history, find vets, check weather, or set reminders."
                        )
                else:
                    await self.capability_worker.speak(
                        "What would you like to do? You can log activities, "
                        "look up history, find vets, check weather, or set reminders."
                    )

            elif trigger:
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

            else:
                # Returning user (pet data already exists, no trigger matched)
                pet_names = [p["name"] for p in self.pet_data.get("pets", [])]
                names_str = ", ".join(pet_names)
                greeting = (
                    f"Pet Care here. You have {len(pet_names)} "
                    f"pet{'s' if len(pet_names) != 1 else ''}: {names_str}."
                )

                # Announce pending reminders and offer to read them
                pending = len(self.reminders) if self.reminders else 0
                if pending > 0:
                    greeting += (
                        f" You also have {pending} "
                        f"reminder{'s' if pending != 1 else ''} set."
                    )
                    await self.capability_worker.speak(
                        greeting + " Want me to read your reminders?"
                    )
                    resp = await self.capability_worker.user_response()
                    if resp and any(
                        w in resp.lower()
                        for w in ["yes", "yeah", "yep", "sure", "read", "go", "yup"]
                    ):
                        await self._handle_reminder({"action": "list"})
                    elif resp and not self.llm_service.is_exit(resp):
                        # Route non-exit response as the initial command
                        intent = await self.llm_service.classify_intent_async(resp)
                        if intent.get("mode") not in ("unknown", "exit"):
                            await self._route_intent(intent)
                else:
                    await self.capability_worker.speak(
                        greeting + " What would you like to do?"
                    )

            idle_count = 0
            consecutive_unknown = 0
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

                cleaned = self.llm_service.clean_input(user_input)

                # Reset/restart phrases map to edit_pet+reset_all and must not
                # be classified as exits; guard both code paths against that.
                _reset_phrases = [
                    "start over",
                    "start from scratch",
                    "restart",
                    "reset everything",
                    "start from beginning",
                ]
                _is_reset = any(p in cleaned for p in _reset_phrases)

                # Long inputs bypass keyword checks: "no <follow-up>" would
                # false-positive as an exit via Tier-3 prefix match, so send
                # them straight to the LLM classifier for accurate intent detection.
                if len(cleaned.split()) > 4:
                    intent = await self.llm_service.classify_intent_async(user_input)
                    mode = intent.get("mode", "unknown")
                    if mode == "exit" and not _is_reset:
                        await self.capability_worker.speak(EXIT_MESSAGE)
                        break
                else:
                    if not _is_reset:
                        if self.llm_service.is_exit(user_input):
                            await self.capability_worker.speak(EXIT_MESSAGE)
                            break
                        if await self.llm_service.is_exit_llm_async(cleaned):
                            await self.capability_worker.speak(EXIT_MESSAGE)
                            break

                    intent = await self.llm_service.classify_intent_async(user_input)
                    mode = intent.get("mode", "unknown")

                if mode == "exit" and not _is_reset:
                    await self.capability_worker.speak(EXIT_MESSAGE)
                    break

                self.worker.editor_logging_handler.info(f"[PetCare] Intent: {intent}")

                if mode == "unknown":
                    consecutive_unknown += 1
                    if consecutive_unknown >= 2:
                        consecutive_unknown = 0
                        await self.capability_worker.speak(
                            "Here's what I can do: log activities like feeding or walks, "
                            "look up history, find emergency vets, check weather safety, "
                            "check food recalls, or set reminders. What would you like?"
                        )
                    else:
                        await self.capability_worker.speak(
                            "Sorry, I didn't catch that. Could you say that again?"
                        )
                    continue

                consecutive_unknown = 0
                await self._route_intent(intent)

                await self.capability_worker.speak("What else can I help with?")
            else:
                await self.capability_worker.speak(EXIT_MESSAGE)

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
        elif mode == "greeting":
            await self.capability_worker.speak(
                "What can I help with? I can log activities, look up history, "
                "find emergency vets, check weather, check food recalls, or set reminders."
            )
        elif mode == "onboarding":
            await self.run_onboarding()
        else:
            await self.capability_worker.speak(
                "Sorry, I didn't catch that. Could you say that again?"
            )

    # === Onboarding ===

    async def run_onboarding(self, initial_context: str = ""):
        """Guided voice onboarding for first-time users.

        Args:
            initial_context: Trigger phrase already captured (e.g. "Pet care Luna").
                             Passed to _collect_pet_info() to avoid re-consuming it
                             from the STT queue as the first user response.
        """
        self.worker.editor_logging_handler.info("[PetCare] Starting onboarding")

        await self.capability_worker.speak(
            "Hi! I'm your pet care assistant. I'd love to help you out! "
            "Let's get started — what's your pet's name?"
        )

        while True:
            pet = await self._collect_pet_info(initial_context=initial_context)
            initial_context = ""  # Only use trigger for the first pet
            if pet is None:
                await self.capability_worker.speak("No problem. Come back anytime!")
                return

            if "pets" not in self.pet_data:
                self.pet_data["pets"] = []
            self.pet_data["pets"].append(pet)
            await self._save_json(PETS_FILE, self.pet_data)

            await self.capability_worker.speak(
                f"Awesome, {pet['name']} is all set! "
                f"You can say things like 'I just fed {pet['name']}' to log activities, "
                "set reminders, check the weather, or find an emergency vet."
            )

            await self.capability_worker.speak("Do you have any other pets to add?")
            response = await self.capability_worker.user_response()
            if not response:
                break
            cleaned = response.lower().strip()

            # If the response is only an exit phrase, leave
            if self.llm_service.is_exit(response) and len(cleaned.split()) <= 2:
                break

            # Only continue if user explicitly says yes — default to done
            if not any(
                w in cleaned
                for w in ["yes", "yeah", "yep", "yup", "sure", "another", "more", "add"]
            ):
                # User said no (possibly with an embedded follow-up command,
                # e.g. "No, is it safe to walk Luna?"). Strip leading negation
                # and stash any remaining content so the main loop handles it.
                _no_strip = re.compile(
                    r"^(?:no[,.]?|nope[,.]?|nah[,.]?)\s*", re.IGNORECASE
                )
                remainder = _no_strip.sub("", response).strip()
                if remainder and len(remainder.split()) >= 3:
                    self._pending_intent_text = remainder
                break
            await self.capability_worker.speak("Great! What's your next pet's name?")

    async def _ask_onboarding_step(self, prompt: str) -> str | None:
        """Ask an onboarding question, handling hard-exit and inline pet queries.

        Wraps run_io_loop with two guards applied in order:
        1. Hard-exit detection (returns None → caller should abort onboarding).
        2. Inline pet inventory query (re-asks the prompt once after answering).

        Returns:
            User response string (may be empty), or None if hard exit detected.
        """
        response = await self.capability_worker.run_io_loop(prompt)
        if not response:
            return ""
        if self._is_hard_exit(response):
            return None
        if await self._answer_inline_query(response):
            response = await self.capability_worker.run_io_loop(prompt)
            if not response:
                return ""
            if self._is_hard_exit(response):
                return None
        return response

    async def _answer_inline_query(self, response: str) -> bool:
        """Detect and answer a question embedded in an onboarding response.

        Handles two tiers:
        1. Fast keyword check — pet inventory questions ("do you have any animal?").
        2. LLM-based classification — general stored-info lookups (pet profile,
           activity history, vet info) for longer question-like inputs.

        Returns:
            True  — inline query found and answered; caller should re-ask its prompt.
            False — no inline query; caller should treat response as a normal answer.
        """
        if not response:
            return False
        lower = response.lower()

        # ── Tier 1: fast keyword check for pet inventory ──────────────────
        inventory_patterns = [
            "do you have any",
            "do i have any",
            "have any animal",
            "have any pet",
            "any animals",
            "any pets",
            "what animals",
            "what pets",
            "what the animal",
            "what animal",
            "the animal do i have",
            "the pet do i have",
            "how many pets",
            "how many animals",
            "list pet",
            "list animal",
            "animal do i have",
            "pets do i have",
        ]
        if any(p in lower for p in inventory_patterns):
            pets = self.pet_data.get("pets", [])
            if not pets:
                await self.capability_worker.speak(
                    "No pets are fully registered yet — we're setting one up right now!"
                )
            elif len(pets) == 1:
                p = pets[0]
                await self.capability_worker.speak(
                    f"You have one pet registered: {p['name']}, a {p.get('species', 'pet')}."
                )
            else:
                names = ", ".join(p["name"] for p in pets)
                await self.capability_worker.speak(
                    f"You have {len(pets)} pets registered: {names}."
                )
            return True

        # ── Tier 2: LLM classification for questions, commands & corrections ─
        # Only classify inputs that contain a question or correction signal;
        # plain answers are returned immediately.
        _question_signals = {
            "what",
            "when",
            "how",
            "who",
            "where",
            "why",
            "tell me",
            "give me",
            "show me",
            "do you",
            "can you",
            "did i",
            "did we",
            "have i",
        }
        _correction_signals = {
            "change",
            "changing",
            "rename",
            "wrong",
            "fix",
            "correct",
            "update",
            "redo",
            "go back",
            "not right",
            "wanna",
            "want to",
        }
        words = lower.split()
        cleaned_words = {w.strip(".,!?'\"") for w in words}
        has_signal = any(q in lower for q in _question_signals) or bool(
            cleaned_words & _correction_signals
        )
        if len(words) < 4 or not has_signal:
            return False

        try:
            intent = await self.llm_service.classify_intent_async(response)
            mode = intent.get("mode", "unknown")

            # Modes that can be handled inline during onboarding
            if mode == "lookup":
                await self._handle_lookup(intent)
                return True
            if mode == "weather":
                await self._handle_weather(intent)
                return True
            if mode == "emergency_vet":
                await self._handle_emergency_vet()
                return True
            if mode == "reminder":
                await self._handle_reminder(intent)
                return True
            if mode == "food_recall":
                await self._handle_food_recall()
                return True

            # Handle edit_pet during onboarding: name corrections inline
            if mode == "edit_pet":
                action = intent.get("action", "")
                details = (intent.get("details") or "").lower()
                # Name correction: prompt for the updated name
                if action in ("update_pet", "add_pet") or "name" in details:
                    resp = await self.capability_worker.run_io_loop(
                        "Sure! What should the name be?"
                    )
                    if resp and not self._is_hard_exit(resp):
                        new_name = await self.llm_service.extract_pet_name_async(resp)
                        if new_name and new_name.lower().strip() not in (
                            "unknown",
                            "none",
                            "",
                        ):
                            self._corrected_name = new_name
                            await self.capability_worker.speak(
                                f"Got it, I'll use {new_name}."
                            )
                    return True
                # Other edit_pet actions: defer until after onboarding
                await self.capability_worker.speak(
                    "I can help with that once we finish setting up! "
                    "Let's continue for now."
                )
                return True

            # Pet-care-related but not actionable inline (log, greeting)
            _PET_CARE_MODES = {"log", "greeting"}
            if mode in _PET_CARE_MODES:
                await self.capability_worker.speak(
                    "I can help with that once we finish setting up! "
                    "Let's continue for now."
                )
                return True

            # mode == "unknown" or "exit" — not related to assistant's role
            # Use LLM to confirm whether it's pet-care-related or truly off-topic
            is_related = await self._is_pet_care_related(response)
            if is_related:
                await self.capability_worker.speak(
                    "Good question! I'll be able to help with that once we finish "
                    "getting your pet set up. Let's keep going."
                )
                return True

            # Genuinely off-topic — not a question for this assistant
            return False

        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"[PetCare] Inline query classification failed: {e}"
            )

        return False

    async def _is_pet_care_related(self, text: str) -> bool:
        """Use LLM to check if a question is related to pet care.

        Returns True if the question is about pets, animals, or pet care tasks.
        Returns False for completely unrelated questions.
        """
        try:
            result = await asyncio.to_thread(
                self.capability_worker.text_to_text_response,
                f"Is this question related to pets, animals, or pet care? "
                f'Reply with ONLY "yes" or "no".\n\n'
                f'Question: "{text}"',
            )
            return result.strip().lower().startswith("yes")
        except Exception:
            return False

    async def _collect_pet_info(self, initial_context: str = "") -> dict:
        """Collect one pet's profile through natural conversation.

        Asks one open-ended question and extracts all fields from the answer.
        Only asks follow-ups for fields that are genuinely missing.
        Minimum 3 questions (overview + health + location), maximum 6.

        Args:
            initial_context: Pre-captured text (e.g. trigger phrase "Pet care Luna")
                             used as the overview so it isn't re-consumed from the queue.
        """
        # ── Step 1: free-form overview ───────────────────────────────────────
        if initial_context and not self._is_hard_exit(initial_context):
            overview = initial_context
            # If the trigger is a question, answer it and collect a
            # new overview from the user.
            if await self._answer_inline_query(overview):
                overview = await self.capability_worker.user_response()
        else:
            overview = await self.capability_worker.user_response()
        if not overview or self._is_hard_exit(overview):
            return None

        # Skip parallel extraction if the overview lacks species/breed keywords:
        # without explicit animal words the model may infer a species from the
        # pet's name alone, causing follow-up questions to be skipped incorrectly.
        _SPECIES_KEYWORDS = {
            # Species
            "dog",
            "cat",
            "bird",
            "rabbit",
            "hamster",
            "fish",
            "turtle",
            "snake",
            "lizard",
            "parrot",
            "puppy",
            "kitten",
            "guinea",
            "pig",
            "ferret",
            "horse",
            "pony",
            # Breed words that imply a species
            "retriever",
            "shepherd",
            "bulldog",
            "poodle",
            "terrier",
            "labrador",
            "husky",
            "beagle",
            "chihuahua",
            "dachshund",
            "corgi",
            "spaniel",
            "collie",
            "rottweiler",
            "doberman",
            "persian",
            "siamese",
            "tabby",
            "bengal",
            "sphynx",
            "cockatiel",
            "parakeet",
            "canary",
            "macaw",
        }
        overview_words = set(overview.lower().split())
        has_species_info = bool(overview_words & _SPECIES_KEYWORDS)

        if has_species_info:
            # Overview mentions an animal type — extract everything in parallel
            name, species, breed, birthday, weight_str = await asyncio.gather(
                self.llm_service.extract_pet_name_async(overview),
                self.llm_service.extract_species_async(overview),
                self.llm_service.extract_breed_async(overview),
                self.llm_service.extract_birthday_async(overview),
                self.llm_service.extract_weight_async(overview),
            )
            # Short overviews cannot reliably contain all fields.
            # Only trust breed/birthday/weight from longer, detailed inputs.
            if len(overview.split()) <= 8:
                breed, birthday, weight_str = "unknown", "", ""
        else:
            # No species info — only extract the name, force everything else
            # to "unknown" so the follow-up questions always trigger.
            name = await self.llm_service.extract_pet_name_async(overview)
            species, breed, birthday, weight_str = "unknown", "unknown", "", ""

        # Pronouns, articles, species words, and short strings the model
        # may return from noisy input — treat these as missing pet names.
        _INVALID_NAMES = {
            # Articles / determiners
            "it",
            "its",
            "the",
            "a",
            "an",
            # Pronouns / short function words
            "do",
            "to",
            "no",
            "yes",
            "none",
            "unknown",
            "not",
            "my",
            "your",
            "their",
            "him",
            "her",
            "he",
            "she",
            "they",
            # Generic responses and fillers
            "yeah",
            "yep",
            "yup",
            "nah",
            "ok",
            "okay",
            "sure",
            "uh",
            # Common species — valid species but not valid names
            "dog",
            "cat",
            "bird",
            "rabbit",
            "hamster",
            "fish",
            "turtle",
            "snake",
            "lizard",
            "guinea",
            "pig",
            "parrot",
            # Generic terms
            "pet",
            "animal",
        }

        _VALID_SPECIES = {
            "dog",
            "cat",
            "bird",
            "rabbit",
            "hamster",
            "fish",
            "turtle",
            "snake",
            "lizard",
            "parrot",
            "puppy",
            "kitten",
            "guinea pig",
            "ferret",
            "horse",
            "pony",
            "gecko",
            "frog",
            "rat",
            "mouse",
            "chinchilla",
            "hedgehog",
            "hermit crab",
            "cockatiel",
            "parakeet",
            "canary",
            "macaw",
            "iguana",
        }

        def _missing(v):
            return not v or v.lower().strip() in ("unknown", "none", "")

        def _valid_species(v):
            """Check if extracted species is a known animal type."""
            if _missing(v):
                return False
            return v.lower().strip() in _VALID_SPECIES

        def _bad_name(v):
            return _missing(v) or v.lower().strip() in _INVALID_NAMES

        if species and not _valid_species(species):
            species = "unknown"

        # ── Follow-up only for fields not found ──────────────────────────────
        if _bad_name(name):
            resp = await self._ask_onboarding_step("What's your pet's name?")
            if resp is None:
                return None
            if resp:
                name = await self.llm_service.extract_pet_name_async(resp)
        # Apply inline name correction if the user changed the name
        if self._corrected_name:
            name = self._corrected_name
            self._corrected_name = None

        temp_name = name.strip().split()[0] if name.strip() else "your pet"

        if not _valid_species(species):
            resp = await self._ask_onboarding_step(
                f"Nice name! Is {temp_name} a dog, cat, or something else? And what breed?"
            )
            if self._corrected_name:
                name = self._corrected_name
                temp_name = name.strip().split()[0] if name.strip() else "your pet"
                self._corrected_name = None
            if resp is None:
                return None
            if resp:
                species, breed_from_resp = await asyncio.gather(
                    self.llm_service.extract_species_async(resp),
                    self.llm_service.extract_breed_async(resp),
                )
                if _missing(breed):
                    breed = breed_from_resp
            # Retry once if species is still not a valid animal
            if not _valid_species(species):
                resp2 = await self._ask_onboarding_step(
                    f"Sorry, I didn't catch that. Is {temp_name} a dog, cat, or something else?"
                )
                if self._corrected_name:
                    name = self._corrected_name
                    temp_name = name.strip().split()[0] if name.strip() else "your pet"
                    self._corrected_name = None
                if resp2 is None:
                    return None
                if resp2:
                    species = await self.llm_service.extract_species_async(resp2)
                    if _missing(breed):
                        breed = await self.llm_service.extract_breed_async(resp2)

        # ── Step 1a: breed (if still unknown after species step) ─────────────
        if _missing(breed):
            breed_input = await self._ask_onboarding_step(
                f"Got it! What breed is {temp_name}? Say 'skip' or 'mixed' if you're not sure."
            )
            if self._corrected_name:
                name = self._corrected_name
                temp_name = name.strip().split()[0] if name.strip() else "your pet"
                self._corrected_name = None
            if breed_input is None:
                return None
            if breed_input and not any(
                w in breed_input.lower() for w in ["skip", "don't know", "no idea"]
            ):
                breed = await self.llm_service.extract_breed_async(breed_input)

        # ── Step 1b: age/birthday (if not in overview) ───────────────────────
        if _missing(birthday):
            age_input = await self._ask_onboarding_step(
                f"How old is {temp_name}? You can say an age like '3 years old' or a birthday. "
                "Say 'skip' if you're not sure."
            )
            if self._corrected_name:
                name = self._corrected_name
                temp_name = name.strip().split()[0] if name.strip() else "your pet"
                self._corrected_name = None
            if age_input is None:
                return None
            if age_input and "skip" not in age_input.lower():
                birthday = await self.llm_service.extract_birthday_async(age_input)

        # ── Step 1c: weight (if not in overview) ─────────────────────────────
        if _missing(weight_str):
            weight_input = await self._ask_onboarding_step(
                f"And how much does {temp_name} weigh? Say 'skip' if you don't know."
            )
            if self._corrected_name:
                name = self._corrected_name
                temp_name = name.strip().split()[0] if name.strip() else "your pet"
                self._corrected_name = None
            if weight_input is None:
                return None
            if weight_input and "skip" not in weight_input.lower():
                weight_str = await self.llm_service.extract_weight_async(weight_input)

        # ── Step 2: health (allergies + medications in one question) ─────────
        health_input = await self._ask_onboarding_step(
            f"Does {temp_name} have any allergies or medications I should know about? "
            "Say 'no' if none."
        )
        if self._corrected_name:
            name = self._corrected_name
            temp_name = name.strip().split()[0] if name.strip() else "your pet"
            self._corrected_name = None
        if health_input is None:
            return None
        if not health_input:
            allergies, medications = [], []
        else:
            allergies_str, meds_str = await asyncio.gather(
                self.llm_service.extract_allergies_async(health_input),
                self.llm_service.extract_medications_async(health_input),
            )
            try:
                allergies = json.loads(allergies_str)
                if not isinstance(allergies, list):
                    allergies = []
            except (json.JSONDecodeError, TypeError):
                allergies = []
            try:
                medications = json.loads(meds_str)
                if not isinstance(medications, list):
                    medications = []
            except (json.JSONDecodeError, TypeError):
                medications = []

        # ── Step 3: vet (optional, skip if already set) ────────────────────
        if not self.pet_data.get("vet_name"):
            vet_input = await self._ask_onboarding_step(
                f"Almost done! Do you have a regular vet for {temp_name}? "
                "Say their name, or 'no' to skip."
            )
            if vet_input is None:
                return None  # User wants to abort/restart

            def _is_skip(v): return any(
                w in v.lower() for w in ["no", "nope", "skip", "don't", "none"]
            )
            # Affirmative without a name ("yes", "yeah", "sure") → ask for the name

            def _is_affirmative(v): return v.lower().strip().rstrip(".!?") in {
                "yes",
                "yeah",
                "yep",
                "yup",
                "sure",
                "yea",
                "uh huh",
                "uh-huh",
            }
            if vet_input and _is_affirmative(vet_input):
                vet_input = await self.capability_worker.run_io_loop(
                    "What's their name?"
                )
                if vet_input and self._is_hard_exit(vet_input):
                    return None
            if vet_input and not _is_skip(vet_input):
                vet_name = await self.llm_service.extract_vet_name_async(vet_input)
                # Reject model error responses stored as vet names
                _bad_vet = (
                    not vet_name
                    or len(vet_name) > 60
                    or any(
                        w in vet_name.lower()
                        for w in [
                            "sorry",
                            "cannot",
                            "extract",
                            "provide",
                            "context",
                            "unknown",
                            "none",
                        ]
                    )
                )
                if _bad_vet:
                    vet_name = vet_input.strip()[:60]  # Use raw input as fallback
                self.pet_data["vet_name"] = vet_name
                phone_input = await self._ask_onboarding_step(
                    "What's their phone number? Say 'skip' if you don't know."
                )
                if phone_input is None:
                    return None  # User wants to abort/restart
                if phone_input and "skip" not in phone_input.lower():
                    vet_phone = await self.llm_service.extract_phone_number_async(
                        phone_input
                    )
                    # Only save if it looks like a real number (≥ 7 digits)
                    if len(re.sub(r"\D", "", vet_phone)) >= 7:
                        self.pet_data["vet_phone"] = vet_phone
                    else:
                        await self.capability_worker.speak(
                            "That doesn't look like a complete number. "
                            "I'll skip it for now — you can update it later."
                        )

        # ── Step 4: location (optional, skip if already set) ─────────────
        if not self.pet_data.get("user_location"):
            location_input = await self._ask_onboarding_step(
                "One last thing — what city are you in? This helps me check weather and find nearby vets."
            )
            if location_input is None:
                return None  # User wants to abort/restart
            if location_input:
                location = await self.llm_service.extract_location_async(location_input)
                self.pet_data["user_location"] = location
                coords = await self._geocode_location(location)
                if coords:
                    self.pet_data["user_lat"] = coords["lat"]
                    self.pet_data["user_lon"] = coords["lon"]

        # ── Build pet dict ────────────────────────────────────────────────────
        try:
            weight_lbs = float(weight_str)
        except (ValueError, TypeError):
            weight_lbs = 0

        return {
            "id": f"pet_{uuid.uuid4().hex[:6]}",
            "name": name,
            "species": (species or "unknown").lower(),
            "breed": breed or "unknown",
            "birthday": birthday or "",
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
            for w in [
                "what pets",
                "any pets",
                "any animals",
                "list pets",
                "how many pets",
            ]
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

        # Handle pet profile queries — return registered info, not activity log
        _profile_keywords = {
            "info",
            "information",
            "profile",
            "details",
            "registered",
            "register",
            "about",
            "stats",
            "data",
            "describe",
            "record",
        }
        if pet and any(w in query.lower() for w in _profile_keywords):
            parts = [
                f"{pet['name']} is a {pet.get('breed', 'unknown breed')} "
                f"{pet.get('species', 'unknown')}"
            ]
            w = pet.get("weight_lbs", 0)
            if w and float(w) > 0:
                parts.append(f"weighing {w} pounds")
            if pet.get("birthday"):
                parts.append(f"born {pet['birthday']}")
            allergies = pet.get("allergies", [])
            if allergies:
                parts.append(f"allergies: {', '.join(allergies)}")
            else:
                parts.append("no known allergies")
            meds = pet.get("medications", [])
            if meds:
                med_names = [
                    m.get("name", str(m)) if isinstance(m, dict) else str(m)
                    for m in meds
                ]
                parts.append(f"medications: {', '.join(med_names)}")
            vet = self.pet_data.get("vet_name", "")
            if vet:
                parts.append(f"vet: {vet}")
            await self.capability_worker.speak(". ".join(parts) + ".")
            return

        if pet:
            relevant_logs = [
                e for e in self.activity_log if e.get("pet_id") == pet["id"]
            ][:50]
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
            response = await asyncio.to_thread(
                self.capability_worker.text_to_text_response,
                prompt,
                system_prompt=system,
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
            response = await asyncio.to_thread(
                self.capability_worker.text_to_text_response,
                prompt,
                system_prompt=system,
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
            # Score each result against the user's pick.
            # Uses three keyword tiers; if no confident match is found,
            # falls back to an LLM call to handle paraphrases and nicknames.
            _generic = {
                "vet",
                "veterinary",
                "animal",
                "hospital",
                "clinic",
                "pet",
                "the",
                "and",
                "of",
                "a",
            }

            def _match_score(place):
                title = place.get("title", "").lower()
                title_words = set(title.split()) - _generic
                pick_words = set(pick_lower.split()) - _generic
                if not pick_words:
                    return 0
                # Tier 1: exact word overlap (highest confidence)
                exact = len(title_words & pick_words)
                # Tier 2: substring match — handles cases like "urgent" being
                # contained within a single-word title such as "UrgentVet".
                partial = sum(
                    1 for pw in pick_words for tw in title_words if pw in tw or tw in pw
                )
                # Tier 3: whole-title substring — catches business names written
                # as one word when spaces are removed from the user's pick
                title_compact = re.sub(r"\s+", "", title)
                pick_compact = re.sub(r"\s+", "", pick_lower)
                whole = 2 if pick_compact in title_compact else 0
                return exact * 3 + partial * 2 + whole

            best = max(top_results, key=_match_score)
            best_score = _match_score(best)

            if best_score == 0:
                best = await self._llm_pick_vet(pick, top_results) or top_results[0]
            chosen = best

            name = chosen.get("title", "Unknown")
            phone = chosen.get("phoneNumber", "")
            is_open = chosen.get("openNow", False)
            status = "open now" if is_open else "may be closed"

            detail = f"{name}, {status}"
            if phone:
                detail += f". Their number is {_fmt_phone_for_speech(phone)}"
            else:
                detail += ". No phone number listed"
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

    async def _llm_pick_vet(self, user_pick: str, candidates: list) -> dict | None:
        """Use the LLM to resolve which vet the user meant when keyword matching fails.

        Args:
            user_pick: What the user said (e.g. "the second one", "urgent care")
            candidates: List of place dicts from Serper Maps

        Returns:
            The best-matching place dict, or None if the LLM cannot decide.
        """
        numbered = "\n".join(
            f"{i+1}. {p.get('title', 'Unknown')}" for i, p in enumerate(candidates)
        )
        prompt = (
            f'A user was shown this list of vets and said: "{user_pick}"\n\n'
            f"Vet options:\n{numbered}\n\n"
            "Which number best matches what the user said? "
            "Reply with ONLY the number (1, 2, 3, ...). "
            "If none match at all, reply with 0."
        )
        try:
            raw = await asyncio.to_thread(
                self.capability_worker.text_to_text_response, prompt
            )
            m = re.search(r"\d+", raw.strip())
            if m:
                idx = int(m.group()) - 1
                if 0 <= idx < len(candidates):
                    return candidates[idx]
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"[PetCare] LLM vet picker failed: {e}"
            )
        return None

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

            response = await asyncio.to_thread(
                self.capability_worker.text_to_text_response,
                prompt,
                system_prompt=WEATHER_SYSTEM_PROMPT,
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
                pass  # Logged in _fetch_serper_news

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
            response = await asyncio.to_thread(
                self.capability_worker.text_to_text_response,
                prompt,
            )
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
                "I'd love to help with that! What's your new pet's name?"
            )
            new_pet = await self._collect_pet_info()
            if new_pet:
                self.pet_data.setdefault("pets", []).append(new_pet)
                await self._save_json(PETS_FILE, self.pet_data)
                await self.capability_worker.speak(
                    f"Awesome, {new_pet['name']} has been added to your pets!"
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
                        raw = await asyncio.to_thread(
                            self.capability_worker.text_to_text_response,
                            update_prompt,
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
                # Delete files directly rather than writing empty data.
                # Writing {} then {"pets": [...]} in quick succession triggers
                # append-corruption on OpenHome (write_file appends, not overwrites).
                # load_json returns the correct empty defaults when files are absent.
                # Also delete .backup files so no stale data survives a fresh start.
                for fname in (PETS_FILE, ACTIVITY_LOG_FILE, REMINDERS_FILE):
                    for f in (fname, f"{fname}.backup"):
                        try:
                            if await self.capability_worker.check_if_file_exists(
                                f, False
                            ):
                                await self.capability_worker.delete_file(f, False)
                        except Exception as del_err:
                            self.worker.editor_logging_handler.warning(
                                f"[PetCare] Could not delete {f} during reset: {del_err}"
                            )
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

    _WEEKDAY_MAP = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    def _parse_reminder_time(self, time_description: str) -> datetime | None:
        """Parse a natural language time description into a datetime using Python only.

        Supports: 'in X hours/minutes', 'at HH:MM', 'tomorrow at HH:MM',
                  'next Monday at 5PM', 'on Friday', 'this Wednesday'.
        Returns None if unparseable.
        """
        if not time_description:
            return None
        now = datetime.now()
        text = time_description.lower().strip()

        # --- "in X minutes/hours" ---
        m = re.search(r"in (\d+) minute", text)
        if m:
            return now + timedelta(minutes=int(m.group(1)))

        m = re.search(r"in (\d+) hour", text)
        if m:
            return now + timedelta(hours=int(m.group(1)))

        m = re.search(r"tomorrow.*?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
        if m:
            hour, minute = self._parse_hm(m)
            tomorrow = now + timedelta(days=1)
            return tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)

        day_pattern = "|".join(self._WEEKDAY_MAP.keys())
        m = re.search(
            rf"(?:next|this|on)\s+({day_pattern})"
            rf"(?:.*?(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm)?)?",
            text,
        )
        if m:
            target_weekday = self._WEEKDAY_MAP[m.group(1)]
            current_weekday = now.weekday()
            days_ahead = (target_weekday - current_weekday) % 7
            # "next X" when today is X means 7 days, not 0
            if days_ahead == 0:
                days_ahead = 7
            target_date = now + timedelta(days=days_ahead)
            if m.group(2):
                hour, minute = self._parse_hm(m, groups=(2, 3, 4))
            else:
                hour, minute = 9, 0  # default 9 AM
            return target_date.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

        m = re.search(
            rf"({day_pattern})" rf"(?:.*?(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm)?)?",
            text,
        )
        if m:
            target_weekday = self._WEEKDAY_MAP[m.group(1)]
            current_weekday = now.weekday()
            days_ahead = (target_weekday - current_weekday) % 7
            if days_ahead == 0:
                days_ahead = 7
            target_date = now + timedelta(days=days_ahead)
            if m.group(2):
                hour, minute = self._parse_hm(m, groups=(2, 3, 4))
            else:
                hour, minute = 9, 0
            return target_date.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

        m = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
        if m:
            hour, minute = self._parse_hm(m)
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate

        return None

    @staticmethod
    def _parse_hm(m, groups=(1, 2, 3)) -> tuple[int, int]:
        """Extract hour and minute from a regex match with am/pm handling.

        Args:
            m: Regex match object
            groups: Tuple of (hour_group, minute_group, meridiem_group) indices

        Returns:
            (hour, minute) tuple in 24-hour format
        """
        h_idx, m_idx, mer_idx = groups
        hour = int(m.group(h_idx))
        minute = int(m.group(m_idx)) if m.group(m_idx) else 0
        meridiem = m.group(mer_idx)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return hour, minute

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
                    "When should I remind you? Say something like 'in 2 hours', 'at 6 PM', or 'next Monday'."
                )
                time_description = await self.capability_worker.user_response() or ""

            due_at = self._parse_reminder_time(time_description)
            if not due_at:
                await self.capability_worker.speak(
                    "I couldn't understand that time. Try 'in 2 hours', 'at 6 PM', or 'next Monday at 5 PM'."
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
            # Strip state/region suffix for better API results
            city_only = location_str.split(",")[0].strip()
            resp = await asyncio.to_thread(
                requests.get, url, params={"name": city_only, "count": 1}, timeout=10
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
