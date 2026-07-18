import json
import asyncio
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

def extract_json(text: str) -> dict:
    text_clean = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text_clean)
    except Exception:
        pass
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass
    raise ValueError(f"Could not extract valid JSON from: {text}")

# Severity levels
SEVERITY_CRITICAL = "CRITICAL"   # Life-threatening — needs hospital immediately
SEVERITY_HIGH     = "HIGH"       # Serious — needs hospital after first aid
SEVERITY_MODERATE = "MODERATE"   # Can manage at home with care / GP visit

# Hardcoded severity for known emergency types
SEVERITY_MAP = {
    "Choking":        SEVERITY_CRITICAL,
    "Severe Bleeding": SEVERITY_CRITICAL,
    "Burns":          SEVERITY_HIGH,
    "CPR":            SEVERITY_CRITICAL,
    "General Trauma": SEVERITY_HIGH,
}

class FirstAidHeroCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    VOICE_ID = "onwK4e9ZLuTAKqWW03F9"  # Daniel — deep, calm, authoritative British male (medic specialist)

    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def speak(self, text: str):
        await self.capability_worker.text_to_speech(text, self.VOICE_ID)
        words_count = len(text.split())
        sleep_duration = max(1.5, words_count / 2.5)
        await self.worker.session_tasks.sleep(sleep_duration)

    async def run_io_loop(self, text: str) -> str:
        await self.speak(text)
        response = await self.capability_worker.user_response()
        # Wait 2.5 seconds after the user stops speaking before the agent responds.
        # This prevents the agent from cutting in too quickly and feels more natural.
        await self.worker.session_tasks.sleep(2.5)
        return response

    async def get_location(self) -> str:
        while True:
            location = await self.run_io_loop(
                "What city are you in? I will find the nearest hospital."
            )
            if location and location.strip() and location.lower() not in ["exit", "stop", "skip"]:
                return location.strip()
            if location.lower() in ["exit", "stop", "skip"]:
                return "unknown"
            await self.worker.session_tasks.sleep(0.5)

    async def recommend_hospital(self, emergency_type: str, severity: str, location: str):
        if location == "unknown":
            await self.speak(
                "Location unknown. Call emergency services now and ask them to send you to the right hospital."
            )
            return

        # LLM hospital recommendation
        hospital_prompt = (
            f"The user is in: '{location}'.\n"
            f"The medical emergency is: '{emergency_type}' with severity level: '{severity}'.\n"
            "Provide:\n"
            "1. The type of hospital department or facility best suited for this emergency.\n"
            "2. Two or three real, well-known hospitals or medical centers in or near that city that have relevant specializations.\n"
            "3. The emergency helpline number for that country/city if known (e.g. 115, 1122, 911, 999).\n"
            "4. One critical transport instruction (e.g. 'keep the patient still', 'keep them upright', 'do not give food or water').\n"
            "Return ONLY a JSON object (no markdown, just raw JSON):\n"
            "{\n"
            "  \"department\": \"Name of ideal hospital department\",\n"
            "  \"hospitals\": [\"Hospital Name 1\", \"Hospital Name 2\"],\n"
            "  \"helpline\": \"Emergency number\",\n"
            "  \"transport_tip\": \"One critical instruction for transporting the patient\"\n"
            "}"
        )

        hospital_raw = self.capability_worker.text_to_text_response(hospital_prompt)

        try:
            hospital = extract_json(hospital_raw)
            department  = hospital.get("department", "Emergency Department")
            hospitals   = hospital.get("hospitals", [])
            helpline    = hospital.get("helpline", "your local emergency number")
            tip         = hospital.get("transport_tip", "Keep the patient calm and still during transport.")

            hospital_list = " or ".join(hospitals) if hospitals else "your nearest major hospital"

            await self.speak(
                f"Go to the {department}. "
                f"Nearest hospitals in {location}: {hospital_list}. "
                f"Call {helpline} for an ambulance. "
                f"{tip}."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error parsing hospital JSON: {e}. Raw: {hospital_raw}")
            await self.speak(
                "Go to your nearest emergency room now. Call emergency services for an ambulance."
            )

    async def run(self):
        intro = (
            "First Aid Hero on. Call emergency services now if you haven't. "
            "What is the emergency? Say: choking, bleeding, CPR, burns, or describe it."
        )
        
        while True:
            emergency = await self.run_io_loop(intro)
            if not emergency or emergency.strip() == "":
                await self.worker.session_tasks.sleep(1.0)
                continue
            break

        emergency_lower = emergency.lower()
        steps = []
        emergency_type = ""
        severity = SEVERITY_HIGH  # Default

        # Direct standard triage mapping
        if "choke" in emergency_lower or "choking" in emergency_lower:
            emergency_type = "Choking"
            severity = SEVERITY_CRITICAL
            steps = [
                "Ask the person: can you cough? If yes, tell them to keep coughing hard.",
                "Stand behind them. Put your arms around their waist.",
                "Make a fist. Place it just above their belly button, thumb side in.",
                "Grab your fist with your other hand. Push in and up — hard and fast.",
                "Do 5 thrusts. Keep going until the object comes out or they collapse."
            ]
        elif "bleed" in emergency_lower or "bleeding" in emergency_lower:
            emergency_type = "Severe Bleeding"
            severity = SEVERITY_CRITICAL
            steps = [
                "Find where the blood is coming from.",
                "Press a clean cloth firmly onto the wound. Use your hand if nothing else is available.",
                "Keep pressing. Do not remove the cloth to check — it will restart the bleeding.",
                "If blood soaks through, add another cloth on top. Keep pressing.",
                "If bleeding doesn't stop after 10 minutes, press harder and hold until help arrives."
            ]
        elif "burn" in emergency_lower or "burns" in emergency_lower:
            emergency_type = "Burns"
            severity = SEVERITY_HIGH
            steps = [
                "Run cool water over the burn for 10 full minutes. Do it now.",
                "Do not use ice, butter, toothpaste, or any creams.",
                "Remove rings, bracelets, or tight clothing near the burn before it swells.",
                "Cover loosely with cling film or a clean plastic bag. Do not wrap tight.",
                "Watch for dizziness, pale skin, or fast breathing — these mean shock."
            ]
        elif "cpr" in emergency_lower or "unconscious" in emergency_lower or "heart" in emergency_lower:
            emergency_type = "Cardiac Arrest / CPR"
            severity = SEVERITY_CRITICAL
            await self.speak("This is critical. Go to the emergency room immediately. Do not wait.")
            location = await self.get_location()
            await self.run_cpr_flow()
            await self.recommend_hospital(emergency_type, severity, location)
            self.capability_worker.resume_normal_flow()
            return
        else:
            # Dynamic LLM generation for custom emergencies
            await self.speak("Fetching custom first aid protocol for your emergency. One moment.")
            recipe_prompt = (
                f"Create a strict, professional first aid step-by-step protocol for the emergency: '{emergency}'.\n"
                "Also assess its severity as one of: CRITICAL, HIGH, or MODERATE.\n"
                "Focus purely on immediate, safe physical actions that a bystander can take. "
                "Keep instructions extremely brief (1 sentence per step) and imperative.\n"
                "Return ONLY a JSON object (no markdown code blocks, just raw JSON):\n"
                "{\n"
                "  \"emergency\": \"Emergency Title\",\n"
                "  \"severity\": \"CRITICAL or HIGH or MODERATE\",\n"
                "  \"steps\": [\n"
                "    \"Step 1 description\",\n"
                "    \"Step 2 description\",\n"
                "    ...\n"
                "  ]\n"
                "}"
            )
            recipe_raw = self.capability_worker.text_to_text_response(recipe_prompt)
            try:
                recipe = extract_json(recipe_raw)
                emergency_type = recipe.get("emergency", "Unknown Emergency")
                severity = recipe.get("severity", SEVERITY_HIGH)
                steps = recipe.get("steps", [])
            except Exception as e:
                self.worker.editor_logging_handler.error(f"Error parsing custom emergency JSON: {e}")
                emergency_type = emergency.title()
                
                # Assess severity from conversational text
                raw_lower = recipe_raw.lower()
                if any(x in raw_lower for x in ["critical", "life-threatening", "unconscious", "cpr", "die", "fatal", "choking"]):
                    severity = SEVERITY_CRITICAL
                elif any(x in raw_lower for x in ["serious", "severe", "hospital", "urgent", "doctor", "snake", "poison"]):
                    severity = SEVERITY_HIGH
                else:
                    severity = SEVERITY_MODERATE
                
                # Split raw sentences into steps
                raw_steps = [s.strip() for s in recipe_raw.split('.') if len(s.strip()) > 8]
                if raw_steps:
                    cleaned_steps = []
                    for rs in raw_steps:
                        if any(rs.lower().startswith(x) for x in ["oh no", "that's serious", "sorry", "i can help", "here are", "first aid"]):
                            continue
                        cleaned_steps.append(rs)
                    steps = cleaned_steps if cleaned_steps else raw_steps
                else:
                    steps = [
                        "Keep the patient calm and warm.",
                        "Ensure their airway is open and they are breathing.",
                        "Wait safely for emergency responders to arrive."
                    ]

        # Conditional location capture based on severity
        location = "unknown"
        if severity in [SEVERITY_CRITICAL, SEVERITY_HIGH]:
            # Announce severity warning immediately
            if severity == SEVERITY_CRITICAL:
                await self.speak("This is critical. Go to the emergency room immediately. Do not wait.")
            else:
                await self.speak("This is serious. Get to a hospital as soon as you can.")
            location = await self.get_location()
        else:
            await self.speak("Not immediately life-threatening. Let's start first aid.")

        # General step walkthrough loop
        await self.speak(f"{emergency_type} guide. After each step, say: next, back, repeat, or done.")
        
        step_idx = 0
        while step_idx < len(steps):
            step_text = f"Step {step_idx + 1}: {steps[step_idx]}. Say next, back, or done."
            user_cmd = await self.run_io_loop(step_text)
            
            if not user_cmd or user_cmd.strip() == "":
                await self.worker.session_tasks.sleep(1.0)
                continue

            cmd_lower = user_cmd.lower()
            
            if "exit" in cmd_lower or "stop" in cmd_lower or "quit" in cmd_lower:
                await self.speak("Stopping. Stay with the patient.")
                if severity in [SEVERITY_CRITICAL, SEVERITY_HIGH]:
                    await self.recommend_hospital(emergency_type, severity, location)
                else:
                    await self.speak("Visit a clinic or doctor soon if needed.")
                self.capability_worker.resume_normal_flow()
                return
            elif "done" in cmd_lower or "resolved" in cmd_lower or "better" in cmd_lower:
                await self.speak("Good. Help is on the way.")
                break
            elif "back" in cmd_lower or "previous" in cmd_lower:
                if step_idx > 0:
                    step_idx -= 1
                else:
                    await self.speak("That is the first step. Say next to continue.")
            elif "repeat" in cmd_lower or "again" in cmd_lower:
                pass
            else:
                step_idx += 1

        if step_idx >= len(steps):
            await self.speak("All steps done. Keep the patient calm until help arrives.")

        # Always recommend hospital at the end based on severity
        if severity in [SEVERITY_CRITICAL, SEVERITY_HIGH]:
            await self.recommend_hospital(emergency_type, severity, location)
        else:
            await self.speak("First aid done. Visit a clinic or doctor soon if symptoms persist.")
        self.capability_worker.resume_normal_flow()

    async def run_cpr_flow(self):
        await self.speak(
            "CPR guide. Lay the person on their back on the floor. "
            "We do 30 chest pushes, then 2 breaths. Repeat until help arrives."
        )
        
        step_text = "Put the heel of one hand on the center of their chest. Put your other hand on top. Straighten your arms. Say ready when set."
        while True:
            resp = await self.run_io_loop(step_text)
            if not resp or resp.strip() == "":
                await self.worker.session_tasks.sleep(1.0)
                continue
            break

        cpr_cycle = 1
        while True:
            await self.speak(f"Cycle {cpr_cycle}. Push down hard and fast. Follow my count.")
            
            for i in range(1, 31):
                await self.capability_worker.text_to_speech(str(i), self.VOICE_ID)
                await self.worker.session_tasks.sleep(0.5)

            breath_text = "Stop. Tilt their head back. Pinch their nose. Give 2 slow breaths into their mouth. Say next for another cycle, or done to stop."
            
            while True:
                user_cmd = await self.run_io_loop(breath_text)
                if not user_cmd or user_cmd.strip() == "":
                    await self.worker.session_tasks.sleep(1.0)
                    continue
                break

            cmd_lower = user_cmd.lower()
            if "done" in cmd_lower or "stop" in cmd_lower or "exit" in cmd_lower or "revived" in cmd_lower:
                await self.speak("CPR stopped. Keep watching their breathing until help arrives.")
                break
            
            cpr_cycle += 1
