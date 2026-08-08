import json
import re
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# FIRST AID HERO ABILITY
# Humane, realistic, and immediate voice-guided emergency first-aid assistant.
# =============================================================================

HOTWORDS = {
    "first aid hero",
    "first aid",
    "medical emergency",
    "first aid guide",
    "emergency first aid",
    "start first aid",
}

# FIX 2: Removed "done" from EXIT_WORDS (was conflicting with NEXT_WORDS)
EXIT_WORDS = {"exit", "stop", "quit", "cancel", "end", "bye", "goodbye"}
NEXT_WORDS = {"next", "yes", "yeah", "yep", "ready", "done", "ok", "okay", "continue", "go", "forward", "proceed"}
BACK_WORDS = {"back", "previous", "go back"}
REPEAT_WORDS = {"repeat", "again", "say again", "pardon", "what was that"}
NO_WORDS = {"no", "nah", "nope", "wait", "hold on", "not ready", "stop for a second"}
SOMETHING_ELSE_PHRASES = {"something else", "other", "none of these", "different", "not sure", "don't know", "dont know"}

# FIX 5: Removed bare "where" — only match specific hospital/clinic/location keywords
HOSPITAL_KEYWORDS = {"hospital", "location", "clinic", "ambulance", "shamsabad", "rawalpindi", "islamabad", "eme", "nearest"}

# Known location names for extraction from free-text user input
KNOWN_LOCATIONS = [
    "shamsabad", "rawalpindi", "islamabad", "peshawar road", "saddar", "bahria",
    "eme", "g-8", "g-9", "f-10", "i-8", "dha", "gulberg", "johar town", "lahore",
    "karachi", "multan", "faisalabad", "quetta", "peshawar"
]

# Pre-mapped proximity landmarks for instant accurate local hospital matching
LANDMARK_HOSPITALS = {
    "shamsabad": {
        "hospitals": ["Holy Family Hospital (HFH Shamsabad)", "Rawalpindi Institute of Cardiology (RIC)"],
        "helpline": "1122"
    },
    "eme": {
        "hospitals": ["Quaid-e-Azam International Hospital (QIH, Peshawar Road)", "Military Hospital (MH) Rawalpindi"],
        "helpline": "1122"
    },
    "peshawar road": {
        "hospitals": ["Quaid-e-Azam International Hospital (QIH)", "MH Rawalpindi"],
        "helpline": "1122"
    },
    "saddar": {
        "hospitals": ["CMH Rawalpindi", "MH Rawalpindi"],
        "helpline": "1122"
    },
    "bahria": {
        "hospitals": ["Bahria International Hospital", "Shaafi International Hospital"],
        "helpline": "1122"
    },
    "islamabad": {
        "hospitals": ["PIMS Hospital (G-8)", "Shifa International Hospital (H-8)"],
        "helpline": "1122"
    },
    "rawalpindi": {
        "hospitals": ["Holy Family Hospital", "Rawalpindi Institute of Cardiology (RIC)"],
        "helpline": "1122"
    }
}

# FIX 6: Generic fallback steps when LLM returns empty steps
GENERIC_FALLBACK_STEPS = [
    "Keep the person as calm and warm as possible — sit or lie them down gently.",
    "Make sure their airway is clear and they can breathe freely. Tilt their head back slightly if needed.",
    "Stay right beside them, keep reassuring them, and call 1122 or your local emergency number now."
]


def extract_json(text: str) -> dict:
    """Extract valid JSON from raw text or markdown code block."""
    text_clean = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text_clean)
    except Exception:
        pass
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    raise ValueError(f"Could not extract valid JSON from response: {text}")


def extract_location_from_text(text: str) -> str:
    """
    FIX 3 & 4: Extract the most specific known location substring from free-form user text.
    Returns the matched location string or empty string if none found.
    Sorted by length descending so "peshawar road" matches before "peshawar".
    """
    text_lower = text.strip().lower()
    for loc in sorted(KNOWN_LOCATIONS, key=len, reverse=True):
        if loc in text_lower:
            return loc
    return ""


class FirstAidHeroCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def speak(self, text: str):
        """Speak text to user using agent voice."""
        await self.capability_worker.speak(text)

    def is_exit_command(self, text: str) -> bool:
        """
        FIX 1: Whole-word token matching instead of substring `in` check.
        Prevents false triggers like "I ended the bleeding" matching "end".
        """
        if not text:
            return False
        # Split into word tokens, strip punctuation from each token
        tokens = set(re.sub(r"[^\w]", "", t).lower() for t in text.strip().split())
        return bool(tokens & EXIT_WORDS)

    def is_next_command(self, text: str) -> bool:
        """Whole-word token match for next/advance words."""
        if not text:
            return False
        tokens = set(re.sub(r"[^\w]", "", t).lower() for t in text.strip().split())
        return bool(tokens & NEXT_WORDS)

    def is_no_command(self, text: str) -> bool:
        """Whole-word token match for pause/wait words."""
        if not text:
            return False
        tokens = set(re.sub(r"[^\w]", "", t).lower() for t in text.strip().split())
        # Multi-word phrases need separate check
        cmd_lower = text.strip().lower()
        for phrase in NO_WORDS:
            if phrase in cmd_lower:
                return True
        return bool(tokens & NO_WORDS)

    async def run_io_loop(self, text: str) -> str:
        """Speak text, wait for user response, and insert natural pause."""
        await self.speak(text)
        response = await self.capability_worker.user_response()
        await self.worker.session_tasks.sleep(1.0)
        return response if response else ""

    async def provide_hospital_info(self, emergency_type: str, location: str):
        """Look up and speak nearest local hospitals with geographic accuracy."""
        if not location or location.strip().lower() in ("unknown", ""):
            await self.speak(
                "If you need an ambulance, call your local emergency services number immediately."
            )
            return

        loc_lower = location.lower().strip()

        # Check instant landmark mapping first for guaranteed proximity accuracy
        for landmark, data in LANDMARK_HOSPITALS.items():
            if landmark in loc_lower:
                hospitals_str = " and ".join(data["hospitals"])
                await self.speak(
                    f"Got it. Right near {location}, the closest emergency medical centers are {hospitals_str}. "
                    f"Call {data['helpline']} for an ambulance immediately. Keep the patient calm during transport."
                )
                return

        # Fall back to LLM with strict geographic proximity rules
        hospital_prompt = (
            f"The user is at specific location/landmark: '{location}'.\n"
            f"Medical emergency: '{emergency_type}'.\n"
            "Task: Identify the 2 geographically CLOSEST emergency hospitals to this specific landmark.\n"
            "Calculate actual driving distance/proximity. Do NOT suggest distant hospitals across town.\n"
            "Examples:\n"
            "- Shamsabad Rawalpindi -> Holy Family Hospital (HFH Shamsabad), Rawalpindi Institute of Cardiology (RIC).\n"
            "- EME College Rawalpindi -> Quaid-e-Azam International Hospital (QIH), MH Rawalpindi.\n"
            "- Saddar Rawalpindi -> CMH Rawalpindi, MH Rawalpindi.\n"
            "Provide:\n"
            "1. Two closest hospitals with neighborhood.\n"
            "2. Emergency helpline (1122 Pakistan, 911 US, 999 UK, 112 Europe).\n"
            "3. One transport tip.\n"
            "Return ONLY raw JSON:\n"
            "{\n"
            '  "hospitals": ["Hospital Name 1 (Area)", "Hospital Name 2 (Area)"],\n'
            '  "helpline": "Number",\n'
            '  "transport_tip": "Keep patient calm"\n'
            "}"
        )

        try:
            hospital_raw = self.capability_worker.text_to_text_response(hospital_prompt)
            hospital = extract_json(hospital_raw)
            hospitals = hospital.get("hospitals", [])
            helpline = hospital.get("helpline", "emergency services")
            tip = hospital.get("transport_tip", "Keep them calm while getting medical help.")

            if hospitals:
                hospital_str = " or ".join(hospitals)
                await self.speak(
                    f"Near {location}, the closest emergency medical centers are {hospital_str}. "
                    f"Call {helpline} for an ambulance immediately. {tip}."
                )
            else:
                await self.speak(
                    f"Head to the nearest emergency room in {location} or call {helpline} for an ambulance."
                )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[FirstAidHero] Hospital info error: {e}")
            await self.speak(
                f"Please get to the nearest emergency room in {location} right away, or call local emergency services."
            )

    async def get_emergency_input(self) -> str:
        """Prompt user for emergency type. Asks for details if ambiguous."""
        prompt = (
            "I'm right here with you. Take a deep breath. "
            "Tell me what's happening — is someone choking, bleeding, needing CPR, burned, or something else?"
        )

        while True:
            response = await self.run_io_loop(prompt)
            if self.is_exit_command(response):
                return "exit"

            resp_clean = response.strip().lower() if response else ""

            if any(phrase in resp_clean for phrase in SOMETHING_ELSE_PHRASES):
                prompt = "Please describe what's happening — for example, a snake bite, allergic reaction, fracture, or deep cut."
                continue

            if resp_clean:
                return response.strip()

            prompt = "I didn't quite catch that. What is the emergency? Say choking, bleeding, CPR, burns, or describe the situation."

    async def answer_user_question(self, user_query: str, current_step: str, emergency_type: str):
        """Answer a mid-flow question using LLM and stay on current step."""
        qa_prompt = (
            f"The user is in a first aid session for '{emergency_type}'.\n"
            f"Current step being performed: '{current_step}'.\n"
            f"User asked: '{user_query}'.\n"
            "Provide a reassuring, direct, 1 to 2 sentence answer focused on safety."
        )
        try:
            answer = self.capability_worker.text_to_text_response(qa_prompt)
            if answer and answer.strip():
                await self.speak(answer.strip())
            else:
                await self.speak("Focus on keeping them calm and safe.")
        except Exception:
            await self.speak("Keep them comfortable and focus on the current step.")

    async def run(self):
        """Main execution flow for First Aid Hero capability."""
        # FIX 8: try/finally guarantees resume_normal_flow is always called
        try:
            await self._run_inner()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[FirstAidHero] Unexpected error: {e}")
            try:
                await self.speak("Something went wrong. Please call emergency services directly.")
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    async def _run_inner(self):
        """Inner execution separated from try/finally to keep logic clean."""
        emergency = await self.get_emergency_input()
        if emergency == "exit":
            await self.speak("I'm stopping now. Stay with them and call emergency services if you need help.")
            return

        emergency_lower = emergency.lower()
        steps = []
        emergency_type = ""

        if "choke" in emergency_lower or "choking" in emergency_lower:
            emergency_type = "Choking"
            steps = [
                "First, check if they can talk or cough. If they can cough hard, encourage them to keep coughing.",
                "If they can't breathe or make sound, stand right behind them and wrap your arms around their waist.",
                "Make a fist with one hand just above their belly button, thumb side facing inward.",
                "Grasp your fist with your other hand and push firmly inward and upward into their stomach.",
                "Give up to 5 quick abdominal thrusts until the object comes out or medical help arrives."
            ]
        elif "bleed" in emergency_lower or "bleeding" in emergency_lower:
            emergency_type = "Severe Bleeding"
            steps = [
                "Find exactly where the blood is coming from and keep them sitting or lying down.",
                "Grab any clean cloth — a t-shirt, towel, or even your hands — and press down firmly on the wound.",
                "Don't lift the cloth to check. Keep holding continuous pressure with both hands.",
                "If blood soaks through, add another cloth on top without removing the first one.",
                "Keep steady pressure without letting go until medical help takes over."
            ]
        elif "burn" in emergency_lower or "burns" in emergency_lower:
            emergency_type = "Burns"
            steps = [
                "Immediately run cool tap water over the burn for 10 full minutes. Tap water is all you need.",
                "Gently remove any rings, watches, or tight clothing near the area before it starts to swell.",
                "Never put ice, butter, toothpaste, or oil on the burn — cool running water only.",
                "If you have a clean plastic bag or cling wrap, cover the burn loosely. Otherwise leave it open.",
                "Keep them warm with a jacket or blanket and watch for dizziness or shivering."
            ]
        elif "cpr" in emergency_lower or "unconscious" in emergency_lower or "heart" in emergency_lower:
            emergency_type = "Cardiac Arrest / CPR"
            await self.speak(
                "This is urgent. Please call local emergency services right now if anyone else is nearby."
            )
            await self.run_cpr_flow()
            return
        else:
            await self.speak(f"Let me get practical first aid steps for {emergency} right now. One second...")
            recipe_prompt = (
                f"Create practical, realistic first aid instructions for: '{emergency}'.\n"
                "IMPORTANT: The helper has NO first aid kit. Use only everyday household items "
                "(tap water, clean t-shirts, towels, blankets, bare hands).\n"
                "Speak directly to a helper in calm, empathetic, simple language.\n"
                "Provide 4-5 brief, actionable physical steps.\n"
                "Return ONLY raw JSON:\n"
                "{\n"
                '  "emergency": "Title",\n'
                '  "steps": ["Step 1", "Step 2"]\n'
                "}"
            )
            try:
                recipe_raw = self.capability_worker.text_to_text_response(recipe_prompt)
                recipe = extract_json(recipe_raw)
                emergency_type = recipe.get("emergency", emergency.title())
                steps = recipe.get("steps", [])
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[FirstAidHero] Protocol error: {e}")
                emergency_type = emergency.title()
                steps = []

        # FIX 6: Guard against empty steps list
        if not steps:
            steps = GENERIC_FALLBACK_STEPS

        await self.speak(f"Okay, here is what we need to do for {emergency_type}. Let's take it one step at a time.")

        step_idx = 0
        while step_idx < len(steps):
            user_cmd = await self.run_io_loop(steps[step_idx])

            if self.is_exit_command(user_cmd):
                await self.speak("I'm stopping now. Stay with them and take care.")
                return

            cmd_lower = user_cmd.lower().strip() if user_cmd else ""

            # FIX 7: Empty response repeats the current step instead of silently skipping
            if not cmd_lower:
                await self.speak("Take your time. Let me know when you're ready to continue.")
                continue

            # FIX 3 & 5: Hospital lookup — extract location from user_cmd first, only ask if none found
            if any(w in cmd_lower for w in HOSPITAL_KEYWORDS):
                extracted_loc = extract_location_from_text(user_cmd)
                if extracted_loc:
                    await self.provide_hospital_info(emergency_type, extracted_loc)
                else:
                    loc = await self.run_io_loop("What city or neighbourhood are you in right now?")
                    if self.is_exit_command(loc):
                        await self.speak("Okay, take care.")
                        return
                    await self.provide_hospital_info(emergency_type, loc.strip())
                await self.speak("Let's continue with the first aid steps.")
                continue

            # Back / previous
            if any(w in cmd_lower for w in BACK_WORDS):
                if step_idx > 0:
                    step_idx -= 1
                else:
                    await self.speak("We're already at the very first step.")
                continue

            # Repeat / again
            if any(w in cmd_lower for w in REPEAT_WORDS):
                continue

            # Pause / wait / no
            if self.is_no_command(user_cmd):
                await self.speak("No problem, take your time. Tell me when you're ready to continue.")
                continue

            # Next / yes / ready
            if self.is_next_command(user_cmd):
                step_idx += 1
                continue

            # Mid-flow question
            if any(q in cmd_lower for q in ["?", "what if", "how", "why", "should i", "can i", "is it"]):
                await self.answer_user_question(user_cmd, steps[step_idx], emergency_type)
                continue

            # Unrecognised phrase — advance to next step
            step_idx += 1

        # Completion
        await self.speak("You've done everything you can right now. Keep them comfortable and stay with them.")

        ask_loc = await self.run_io_loop(
            "Would you like me to find the nearest emergency hospital? Tell me your city or area, or say 'no' to finish."
        )

        if not self.is_exit_command(ask_loc):
            loc_clean = ask_loc.strip().lower()
            if loc_clean not in ("no", "nah", "nope", "skip", ""):
                # FIX 3: Try to extract location from user's response before using raw string
                extracted = extract_location_from_text(ask_loc)
                await self.provide_hospital_info(emergency_type, extracted if extracted else ask_loc.strip())

        await self.speak("Take care and stay safe.")

    async def run_cpr_flow(self):
        """Interactive CPR counting and cycle management loop."""
        await self.speak(
            "Let's start CPR together. Lay the person flat on their back on a hard surface or the floor."
        )

        prep = await self.run_io_loop(
            "Place the heel of one hand on the center of their chest and put your other hand right on top. Tell me when you're ready."
        )
        if self.is_exit_command(prep):
            await self.speak("Stopping CPR guide.")
            loc_input = await self.run_io_loop("Would you like me to find the nearest emergency hospital? Tell me your location, or say 'no'.")
            if not self.is_exit_command(loc_input) and loc_input.strip().lower() not in ("no", "nah", "nope", "skip", ""):
                extracted = extract_location_from_text(loc_input)
                await self.provide_hospital_info("CPR / Emergency", extracted if extracted else loc_input.strip())
            return

        cpr_cycle = 1
        while True:
            # FIX 9: Removed sleep() gaps — count in one speak call to minimise dead-time where user input is lost
            await self.speak(
                f"Cycle {cpr_cycle}. Push down hard and fast. "
                "1, 2, 3, 4, 5, 6, 7, 8, 9, 10 — "
                "11, 12, 13, 14, 15, 16, 17, 18, 19, 20 — "
                "21, 22, 23, 24, 25, 26, 27, 28, 29, 30."
            )

            # This is the ONLY point where user input is captured — make it clear
            user_cmd = await self.run_io_loop(
                "Pause now. Tilt their head back, pinch the nose, and give 2 slow rescue breaths. "
                "Say 'next' to do another cycle, 'stop' to finish, or tell me your location for the nearest hospital."
            )

            if not user_cmd:
                # FIX 7: Empty response during CPR — repeat prompt, don't advance
                await self.speak("I didn't hear you. Say 'next' to continue, or 'stop' to finish.")
                continue

            cmd_lower = user_cmd.lower().strip()

            # FIX 4: Extract clean location instead of passing raw sentence
            if any(w in cmd_lower for w in HOSPITAL_KEYWORDS):
                extracted = extract_location_from_text(user_cmd)
                loc_to_use = extracted if extracted else user_cmd.strip()
                await self.provide_hospital_info("CPR / Emergency", loc_to_use)
                await self.speak("CPR guide finished. Keep watching their breathing closely until medical help arrives.")
                return

            if self.is_exit_command(user_cmd):
                await self.speak("CPR guide stopped. Keep watching their breathing closely.")
                loc_input = await self.run_io_loop("Would you like me to find the nearest emergency hospital? Tell me your location, or say 'no'.")
                if not self.is_exit_command(loc_input) and loc_input.strip().lower() not in ("no", "nah", "nope", "skip", ""):
                    extracted = extract_location_from_text(loc_input)
                    await self.provide_hospital_info("CPR / Emergency", extracted if extracted else loc_input.strip())
                return

            cpr_cycle += 1
