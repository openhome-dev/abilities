"""LLM Service - Handles all LLM/NLU operations.

Responsibilities:
- Intent classification
- Value extraction from voice input (typed methods)
- Exit detection (including LLM fallback)
- Trigger context retrieval
"""

import asyncio
import json
import re
from datetime import datetime

# Constants for exit detection (three-tier system)
FORCE_EXIT_PHRASES: list[str] = [
    "exit petcare",
    "close petcare",
    "shut down pets",
    "petcare out",
]

EXIT_COMMANDS: list[str] = [
    "exit",
    "stop",
    "quit",
    "cancel",
]

EXIT_RESPONSES: list[str] = [
    "no",
    "nope",
    "done",
    "bye",
    "goodbye",
    "thanks",
    "thank you",
    "no thanks",
    "nothing else",
    "all good",
    "i'm good",
    "that's all",
    "that's it",
    "i'm done",
    "we're done",
]

CLASSIFY_PROMPT = (
    "You are an intent classifier for a pet care assistant. "
    "The user manages one or more pets. Known pets: {pet_names}.\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "1. Input comes from speech-to-text and WILL be garbled, noisy, or incomplete. "
    "Always try to infer the most plausible intent, even from fragments.\n"
    "2. Only return mode 'unknown' if you truly cannot extract ANY plausible intent "
    "after trying hard. When in doubt, pick the closest match.\n"
    "3. Ignore filler words, background noise, repeated words, or STT artifacts.\n"
    "4. If the input sounds like an information request — contains words like 'give me', "
    "'tell me', 'show me', 'get me', 'what', 'when', 'how', 'information', 'info', "
    "'details', 'data', 'history', 'record' — classify as 'lookup', NOT 'unknown'.\n"
    "5. If the input sounds like reporting an activity (feeding, walk, weight, medication, "
    "grooming) — classify as 'log', NOT 'unknown'.\n"
    "6. IMPORTANT — past vs future distinction:\n"
    "   - PAST events (already happened): 'I fed', 'we walked', 'she ate', 'went to vet', "
    "'got groomed' → 'log'\n"
    "   - FUTURE plans (haven't happened yet): 'I wanna go', 'need to go', 'going to', "
    "'have an appointment', 'scheduled for', 'plan to', 'want to take', 'next Monday', "
    "'tomorrow', 'next week', 'this Friday' → 'reminder' with action 'set'\n"
    "   - If the input mentions a future time reference (next, tomorrow, this weekend, "
    "on Monday, at 5PM next week) AND an activity, it is a REMINDER, not a LOG.\n\n"
    "Return ONLY valid JSON with no markdown fences.\n\n"
    "Possible modes:\n"
    '- {{"mode": "log", "pet_name": "<name or null>", "activity_type": "feeding|medication|walk|weight|vet_visit|grooming|other", "details": "<short description>", "value": null}}\n'
    "  (value is a number ONLY for weight entries, null otherwise)\n"
    '- {{"mode": "lookup", "pet_name": "<name or null>", "query": "<the user\'s question>"}}\n'
    '- {{"mode": "emergency_vet"}}\n'
    '- {{"mode": "weather", "pet_name": "<name or null>"}}\n'
    '- {{"mode": "food_recall"}}\n'
    '- {{"mode": "edit_pet", "action": "add_pet|update_pet|change_vet|update_weight|remove_pet|clear_log|reset_all", "pet_name": "<name or null>", "details": "<what to change>"}}\n'
    '- {{"mode": "reminder", "action": "set|list|delete", "pet_name": "<name or null>", "activity": "<feeding|medication|walk|other>", "time_description": "<raw time the user said>"}}\n'
    '- {{"mode": "greeting"}}\n'
    '- {{"mode": "exit"}}\n'
    '- {{"mode": "unknown"}}\n\n'
    "Rules:\n"
    "- 'I fed', 'ate', 'breakfast', 'dinner', 'kibble', 'food' => log feeding\n"
    "- 'medicine', 'medication', 'pill', 'flea', 'heartworm', 'dose' => log medication\n"
    "- 'walk', 'walked', 'run', 'jog', 'hike' => log walk\n"
    "- 'weighs', 'pounds', 'lbs', 'kilos', 'weight is' => log weight (extract numeric value)\n"
    "- 'vet visit', 'went to vet', 'checkup' => log vet_visit\n"
    "- 'groom', 'bath', 'nails', 'haircut' => log grooming\n"
    "- 'when did', 'last time', 'how many', 'has had', 'check on', 'tell me about' => lookup\n"
    "- 'emergency vet', 'find a vet', 'vet near me', 'need a vet' => emergency_vet\n"
    "- 'safe outside', 'weather', 'too hot', 'too cold', 'can I walk', 'go outside' => weather\n"
    "- 'food recall', 'recall check', 'food safe' => food_recall\n"
    "- 'add a pet', 'new pet', 'update', 'change vet', 'edit pet' => edit_pet\n"
    "- 'remove pet', 'delete pet' => edit_pet with action remove_pet\n"
    "- 'clear log', 'clear activity log', 'delete all logs', 'clear history' => edit_pet with action clear_log (ONLY removes activity history, pets are kept)\n"
    "- 'start over', 'reset everything', 'delete everything', 'wipe all data', 'fresh start', 'wipe everything', 'clean slate', 'start from scratch', 'erase everything' => edit_pet with action reset_all (deletes ALL data: pets + logs + reminders)\n"
    "- IMPORTANT: 'delete everything' and 'start over' always mean reset_all, NOT clear_log\n"
    "- 'what pets', 'do I have any pets', 'any animals', 'list my pets', 'how many pets', 'what animals do I have', 'do you have any' => lookup with query 'list registered pets'\n"
    "- 'tell me about Luna', 'give me Luna info', 'Luna profile', 'Luna registered info', 'Luna details', 'Luna stats', 'what do you have on Luna' => lookup with pet_name and query containing 'profile info'\n"
    "- 'remind me', 'set a reminder', 'alert me' => reminder with action set\n"
    "- 'my reminders', 'list reminders', 'what reminders' => reminder with action list\n"
    "- 'delete reminder', 'cancel reminder', 'remove reminder' => reminder with action delete\n"
    "- 'stop', 'done', 'quit', 'exit', 'bye' => exit\n"
    "- Trigger phrases with no specific action ('pet care', 'dog care', 'hello', 'hey', 'hi') => greeting\n"
    "- If only one pet exists and no name is mentioned, use that pet's name.\n"
    "- If multiple pets and no name mentioned, set pet_name to null.\n\n"
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
    '"Clear activity log" -> {{"mode": "edit_pet", "action": "clear_log", "pet_name": null, "details": "clear logs"}}\n'
    '"Start over" -> {{"mode": "edit_pet", "action": "reset_all", "pet_name": null, "details": "reset all data"}}\n'
    '"Delete everything" -> {{"mode": "edit_pet", "action": "reset_all", "pet_name": null, "details": "reset all data"}}\n'
    '"I wanna start over" -> {{"mode": "edit_pet", "action": "reset_all", "pet_name": null, "details": "reset all data"}}\n'
    '"Wipe all data" -> {{"mode": "edit_pet", "action": "reset_all", "pet_name": null, "details": "reset all data"}}\n'
    '"What pets do I have?" -> {{"mode": "lookup", "pet_name": null, "query": "list registered pets"}}\n'
    '"Do I have any animals?" -> {{"mode": "lookup", "pet_name": null, "query": "list registered pets"}}\n'
    '"Do you have any animal?" -> {{"mode": "lookup", "pet_name": null, "query": "list registered pets"}}\n'
    '"pet care" -> {{"mode": "greeting"}}\n'
    '"dog dog care" -> {{"mode": "greeting"}}\n'
    '"Remind me to feed Luna in 2 hours" -> {{"mode": "reminder", "action": "set", "pet_name": "Luna", "activity": "feeding", "time_description": "in 2 hours"}}\n'
    '"What reminders do I have?" -> {{"mode": "reminder", "action": "list", "pet_name": null, "activity": null, "time_description": null}}\n'
    '"Animal animal, Give me loaner information" -> {{"mode": "lookup", "pet_name": null, "query": "owner information"}}\n'
    '"Dog dog, tell me about food" -> {{"mode": "lookup", "pet_name": null, "query": "food information"}}\n'
    '"I wanna go to the doctor with Luna next Monday" -> {{"mode": "reminder", "action": "set", "pet_name": "Luna", "activity": "vet_visit", "time_description": "next Monday"}}\n'
    '"I need to take Max to the vet on Friday at 3PM" -> {{"mode": "reminder", "action": "set", "pet_name": "Max", "activity": "vet_visit", "time_description": "Friday at 3PM"}}\n'
    '"Luna has a vet appointment tomorrow at 10AM" -> {{"mode": "reminder", "action": "set", "pet_name": "Luna", "activity": "vet_visit", "time_description": "tomorrow at 10AM"}}\n'
    '"Set a reminder to walk Luna next Monday at 5PM" -> {{"mode": "reminder", "action": "set", "pet_name": "Luna", "activity": "walk", "time_description": "next Monday at 5PM"}}\n'
    '"Went to the vet with Luna today" -> {{"mode": "log", "pet_name": "Luna", "activity_type": "vet_visit", "details": "vet visit today", "value": null}}\n'
)


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences from LLM JSON output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class LLMService:
    """Service for LLM/NLU operations (intent classification, extraction, exit detection)."""

    def __init__(self, capability_worker, worker, pet_data: dict):
        """Initialize LLMService.

        Args:
            capability_worker: CapabilityWorker for LLM access
            worker: AgentWorker for logging and transcription access
            pet_data: Current pet data dict (for intent classification context)
        """
        self.capability_worker = capability_worker
        self.worker = worker
        self.pet_data = pet_data

    def classify_intent(self, user_input: str) -> dict:
        """Use LLM to classify user intent and extract structured data (sync).

        Args:
            user_input: Raw user input string

        Returns:
            Intent dict with mode, pet_name, and mode-specific fields
        """
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

    async def classify_intent_async(self, user_input: str) -> dict:
        """Async wrapper for classify_intent (runs in thread pool to avoid blocking event loop)."""
        return await asyncio.to_thread(self.classify_intent, user_input)

    def extract_value(self, raw_input: str, instruction: str) -> str:
        """Use LLM to extract a clean value from messy voice input (sync).

        Args:
            raw_input: Raw user input (e.g., "His name is Max")
            instruction: Extraction instruction for LLM

        Returns:
            Extracted value or raw_input if extraction fails
        """
        if not raw_input:
            return ""
        try:
            result = self.capability_worker.text_to_text_response(
                f"Input: {raw_input}",
                system_prompt=instruction,
            )
            return _strip_json_fences(result).strip().strip('"')
        except Exception:
            return raw_input.strip()

    async def extract_value_async(self, raw_input: str, instruction: str) -> str:
        """Async wrapper for extract_value (runs LLM call in thread pool).

        Allows parallel LLM extraction during onboarding for ~90% performance improvement.

        Args:
            raw_input: Raw user input
            instruction: Extraction instruction for LLM

        Returns:
            Extracted value or raw_input if extraction fails
        """
        return await asyncio.to_thread(self.extract_value, raw_input, instruction)

    # === Typed Extraction Methods ===

    async def extract_pet_name_async(self, raw_input: str) -> str:
        """Extract pet name from user input.

        Args:
            raw_input: Raw user response (e.g., "His name is Max")

        Returns:
            Extracted pet name (e.g., "Max")
        """
        return await self.extract_value_async(
            raw_input, "Extract the pet's name from this. Return just the name."
        )

    async def extract_species_async(self, raw_input: str) -> str:
        """Extract animal species from user input.

        Args:
            raw_input: Raw user response (e.g., "She's a golden retriever")

        Returns:
            Species as single word (e.g., "dog"), or "unknown" if not mentioned
        """
        return await self.extract_value_async(
            raw_input,
            "Extract the animal species ONLY if it is explicitly mentioned in the text. "
            "Return one word: dog, cat, bird, rabbit, hamster, etc. "
            "If no species is clearly stated, return 'unknown'. "
            "Do NOT guess from pet names or context.",
        )

    async def extract_breed_async(self, raw_input: str) -> str:
        """Extract pet breed from user input.

        Args:
            raw_input: Raw user response (e.g., "golden retriever mix")

        Returns:
            Breed name or "mixed" (e.g., "golden retriever"), or "unknown" if not mentioned
        """
        return await self.extract_value_async(
            raw_input,
            "Extract the breed name ONLY if explicitly mentioned in the text. "
            "If they say mixed or don't know, return 'mixed'. "
            "If no breed is mentioned at all, return 'unknown'. "
            "Do NOT guess from pet names or context.",
        )

    async def extract_birthday_async(self, raw_input: str) -> str:
        """Extract or calculate pet birthday from user input.

        Args:
            raw_input: Raw user response (e.g., "3 years old" or "born in 2020")

        Returns:
            Birthday in YYYY-MM-DD format (e.g., "2020-01-15")
        """
        return await self.extract_value_async(
            raw_input,
            "Extract a birthday in YYYY-MM-DD format if possible. "
            "If they give an age like '3 years old', calculate the approximate birthday "
            f"from today ({datetime.now().strftime('%Y-%m-%d')}). "
            "Return just the date string.",
        )

    async def extract_weight_async(self, raw_input: str) -> str:
        """Extract pet weight from user input (converts to pounds).

        Args:
            raw_input: Raw user response (e.g., "55 pounds" or "25 kilos")

        Returns:
            Weight as string number in pounds (e.g., "55")
        """
        return await self.extract_value_async(
            raw_input,
            "Extract the weight as a number in pounds. If they give kilos, convert to pounds. "
            "Return just the number.",
        )

    async def extract_allergies_async(self, raw_input: str) -> str:
        """Extract pet allergies from user input as JSON array.

        Args:
            raw_input: Raw user response (e.g., "allergic to chicken and grain")

        Returns:
            JSON array string (e.g., '["chicken", "grain"]' or '[]')
        """
        return await self.extract_value_async(
            raw_input,
            "Extract allergies as a JSON array of strings. "
            'If none, return []. Example: ["chicken", "grain"]. Return only the array.',
        )

    async def extract_medications_async(self, raw_input: str) -> str:
        """Extract pet medications from user input as JSON array.

        Args:
            raw_input: Raw user response (e.g., "takes Heartgard monthly")

        Returns:
            JSON array string (e.g., '[{"name": "Heartgard", "frequency": "monthly"}]')
        """
        return await self.extract_value_async(
            raw_input,
            "Extract medications as a JSON array of objects with 'name' and 'frequency' keys. "
            'If none, return []. Example: [{"name": "Heartgard", "frequency": "monthly"}]. '
            "Return only the array.",
        )

    async def extract_vet_name_async(self, raw_input: str) -> str:
        """Extract veterinarian name from user input.

        Args:
            raw_input: Raw user response (e.g., "Dr. Smith at Austin Vet")

        Returns:
            Vet name (e.g., "Dr. Smith")
        """
        return await self.extract_value_async(
            raw_input, "Extract the veterinarian's name. Return just the name."
        )

    async def extract_phone_number_async(self, raw_input: str) -> str:
        """Extract phone number from user input (digits only).

        Args:
            raw_input: Raw user response (e.g., "(512) 555-1234")

        Returns:
            Phone number as digits only (e.g., "5125551234")
        """
        return await self.extract_value_async(
            raw_input,
            "Extract the phone number as digits only (e.g., 5125551234). Return just digits.",
        )

    async def extract_location_async(self, raw_input: str) -> str:
        """Extract location from user input in City, State format.

        Args:
            raw_input: Raw user response (e.g., "I live in Austin")

        Returns:
            Location string (e.g., "Austin, Texas")
        """
        return await self.extract_value_async(
            raw_input,
            "Extract the city and state/country. Return in format 'City, State' or 'City, Country'.",
        )

    # ------------------------------------------------------------------
    # Exit Detection
    # ------------------------------------------------------------------

    @staticmethod
    def clean_input(text: str) -> str:
        """Lowercase and strip punctuation from STT transcription.

        Converts 'Stop.' → 'stop', 'Done, thanks!' → 'done thanks', etc.

        Args:
            text: Raw transcribed text

        Returns:
            Cleaned text (lowercase, no punctuation except apostrophes)
        """
        if not text:
            return ""
        # Lowercase, strip whitespace, remove all punctuation except apostrophes
        cleaned = text.lower().strip()
        cleaned = re.sub(r"[^\w\s']", "", cleaned)
        return cleaned.strip()

    def is_hard_exit(self, text: str) -> bool:
        """Exit detection for mid-question contexts (Tier 1 + 2 only).

        Use this instead of is_exit() when 'no', 'done', 'thanks', etc. are
        valid answers to the current question (e.g. onboarding). Only matches
        explicit abort/reset commands; ignores EXIT_RESPONSES like 'no'.
        """
        if not text:
            return False
        cleaned = self.clean_input(text)
        if not cleaned:
            return False

        for phrase in FORCE_EXIT_PHRASES:
            if phrase in cleaned:
                return True

        words = cleaned.split()
        for cmd in EXIT_COMMANDS:
            if cmd in words:
                return True

        # Reset/restart phrases (user wants to start over during onboarding)
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

    def is_exit(self, text: str) -> bool:
        """Hybrid exit detection: force-exit → command match → response match.

        Processes cleaned (lowercased, punctuation-stripped) input through
        three tiers to robustly detect exit intent.

        Args:
            text: Raw transcribed text from the user.

        Returns:
            True if the user wants to exit.
        """
        if not text:
            return False
        cleaned = self.clean_input(text)
        if not cleaned:
            return False

        # Tier 1: Force-exit phrases (instant shutdown)
        for phrase in FORCE_EXIT_PHRASES:
            if phrase in cleaned:
                return True

        # Tier 2: Exit Commands (anywhere in the sentence)
        words = cleaned.split()
        for cmd in EXIT_COMMANDS:
            if cmd in words:
                return True

        # Tier 3: Exit Responses (must be exact match or start of sentence)
        # Allow "No thanks" or "No, I'm good" → "no thanks" or "no i'm good"
        for resp in EXIT_RESPONSES:
            if cleaned == resp:
                return True
            if cleaned.startswith(f"{resp} "):
                return True

        return False

    def is_exit_llm(self, text: str) -> bool:
        """Use the LLM to classify ambiguous exit intent.

        Only called when keyword matching fails but the input is short
        and doesn't look like a pet care query.

        Args:
            text: Cleaned user input.

        Returns:
            True if the LLM thinks the user wants to exit.
        """
        try:
            result = self.capability_worker.text_to_text_response(
                "Does this message mean the user wants to END the conversation? "
                "Reply with ONLY 'yes' or 'no'.\n\n"
                f'Message: "{text}"'
            )
            return result.strip().lower().startswith("yes")
        except Exception:
            return False

    async def is_exit_llm_async(self, text: str) -> bool:
        """Async wrapper for is_exit_llm (runs in thread pool to avoid blocking event loop)."""
        return await asyncio.to_thread(self.is_exit_llm, text)

    def get_trigger_context(self) -> str:
        """Get the transcription that triggered this ability.

        Returns:
            Trigger transcription string or empty string if not available
        """
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
