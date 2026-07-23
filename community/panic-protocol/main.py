import asyncio
import requests
from xml.sax.saxutils import escape as xml_escape

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class PanicProtocolCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def trigger_twilio_call(self, account_sid: str, auth_token: str, from_number: str, to_number: str, emergency_message: str) -> bool:
        """Runs the HTTP POST request to Twilio API to initiate a phone call using requests."""
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"
        # emergency_message can embed live speech-to-text (e.g. the caller's own words),
        # which may contain &, <, or > - escape before embedding in TwiML or Twilio
        # will reject/mis-render the call on those characters.
        twiml = f"<Response><Say>{xml_escape(emergency_message)}</Say></Response>"

        try:
            response = requests.post(
                url,
                data={
                    "To": to_number,
                    "From": from_number,
                    "Twiml": twiml
                },
                auth=(account_sid, auth_token),
                timeout=10
            )
            if response.status_code in [200, 201]:
                return True
            self.worker.editor_logging_handler.error(
                f"[PanicProtocol] Twilio API returned {response.status_code}: {response.text[:300]}"
            )
            return False
        except Exception as error:
            self.worker.editor_logging_handler.error(f"[PanicProtocol] Twilio Error: {error!r}")
            return False

    async def run(self):
        try:
            # 1. Fetch the trigger spoken sentence that initiated the ability
            raw_prompt = await self.capability_worker.wait_for_complete_transcription()
            prompt = raw_prompt.lower() if raw_prompt else ""

            # 2. Fetch Secure API Keys supporting BOTH uppercase, lowercase, and typo fallbacks
            twilio_sid = (
                self.capability_worker.get_api_keys("twilio_account_sid")
                or self.capability_worker.get_api_keys("TWILIO_ACCOUNT_SID")
                or self.capability_worker.get_api_keys("TWILIO_ACCOUNT_SI")
            )
            twilio_token = (
                self.capability_worker.get_api_keys("twilio_auth_token")
                or self.capability_worker.get_api_keys("TWILIO_AUTH_TOKEN")
            )
            from_number = (
                self.capability_worker.get_api_keys("twilio_phone_number")
                or self.capability_worker.get_api_keys("TWILIO_PHONE_NUMBER")
            )
            to_number = (
                self.capability_worker.get_api_keys("emergency_contact_number")
                or self.capability_worker.get_api_keys("EMERGENCY_CONTACT_NUMBER")
            )

            if not all([twilio_sid, twilio_token, from_number, to_number]):
                missing_keys = []
                if not twilio_sid:
                    missing_keys.append("twilio_account_sid / TWILIO_ACCOUNT_SID")
                if not twilio_token:
                    missing_keys.append("twilio_auth_token / TWILIO_AUTH_TOKEN")
                if not from_number:
                    missing_keys.append("twilio_phone_number / TWILIO_PHONE_NUMBER")
                if not to_number:
                    missing_keys.append("emergency_contact_number / EMERGENCY_CONTACT_NUMBER")

                error_msg = f"Error. Missing Twilio API keys in settings: {', '.join(missing_keys)}"
                self.worker.editor_logging_handler.error(f"[PanicProtocol] {error_msg}")
                await self.capability_worker.speak("Error. Missing Twilio API keys in the dashboard settings.")
                return

            # Silent Alarm trigger phrases (Path A)
            silent_keywords = ["check the back yard", "turn off the kitchen lamp", "did you feed the dog", "red flower"]

            if any(keyword in prompt for keyword in silent_keywords):
                # PATH A: SILENT ALARM
                # Run completely silently without speaking aloud.
                silent_message = (
                    "Emergency Alert! A silent distress call has been initiated from the residence. "
                    "I repeat, a silent distress call was initiated from the residence. "
                    "Please dispatch emergency help immediately."
                )

                # Trigger call asynchronously in the background
                await asyncio.to_thread(self.trigger_twilio_call, twilio_sid, twilio_token, from_number, to_number, silent_message)

            else:
                # PATH B: INTERACTIVE PANIC PROTOCOL
                # Step 1: Speak professional greeting
                await self.capability_worker.speak(
                    "Emergency Protocol Active. Initiating panic sequence. "
                    "Please state the exact nature of your emergency, or say cancel to abort."
                )

                # Step 2: Capture user emergency response
                emergency_details = await self.capability_worker.user_response()

                # Step 3: Check for Abort/Exit keywords
                abort_words = ["cancel", "stop", "exit", "never mind", "close", "abort"]
                if not emergency_details or any(word in emergency_details.lower() for word in abort_words):
                    await self.capability_worker.speak("Emergency protocol aborted. Resuming normal operations.")
                    return

                # Step 4: Dispatch call with structured, repeating message
                distress_message = (
                    f"Emergency Alert! A panic protocol has been activated at the residence. "
                    f"The resident reports: {emergency_details}. "
                    f"I repeat, a panic protocol has been activated. The resident reports: {emergency_details}. "
                    f"Please dispatch emergency help immediately."
                )

                await asyncio.to_thread(self.trigger_twilio_call, twilio_sid, twilio_token, from_number, to_number, distress_message)

                # Step 5: Acknowledge dispatch with a reassuring confirmation
                await self.capability_worker.speak("Call request sent to emergency contacts.")

                # Step 6: Fetch situation-specific safety tips from LLM
                tips_prompt = (
                    f"The user is experiencing an emergency: '{emergency_details}'. "
                    f"List 3 short, critical safety measures/tips they can take while they wait for help. "
                    f"Keep each tip very brief, under 10 words, and formatted as a single sentence without bullet points."
                )
                safety_tips = self.capability_worker.text_to_text_response(tips_prompt)
                if safety_tips:
                    await self.capability_worker.speak(f"While help is on the way, please follow these safety measures: {safety_tips}")

                # Step 7: Context-aware follow-up question
                followup_prompt = (
                    f"The user is in a '{emergency_details}' emergency. "
                    f"Generate a specific, brief yes/no follow-up question (under 10 words) asking if they need help with a related task "
                    f"(e.g., for fire: 'Do you want me to unlock the front doors?'; "
                    f"for medical: 'Should I guide you through CPR?'; "
                    f"for general: 'Is there anything else I can do for you?')."
                )
                helper_question = self.capability_worker.text_to_text_response(followup_prompt)
                if helper_question:
                    await self.capability_worker.speak(helper_question)

                # Step 8: Interactive Assist Loop (Keep checking until exit is triggered)
                empty_streak = 0
                while True:
                    followup_response = await self.capability_worker.user_response()
                    if not followup_response:
                        empty_streak += 1
                        if empty_streak >= 3:
                            await self.capability_worker.speak("Understood. Stay safe. Resuming normal agent flow. Goodbye.")
                            break
                        await self.capability_worker.speak("Are you still there? Let me know if you need anything else.")
                        continue
                    empty_streak = 0

                    # Normalize input
                    response_lower = followup_response.lower()

                    # Check for exit/close commands or negative answers
                    if any(word in response_lower for word in abort_words) or any(word in response_lower for word in ["no", "nothing", "all good", "no thank you", "no thanks"]):
                        await self.capability_worker.speak("Understood. Stay safe. Resuming normal agent flow. Goodbye.")
                        break

                    # LLM dynamic response to handle follow-up actions and ask if they need anything else
                    assistant_prompt = (
                        f"The user is experiencing a '{emergency_details}' emergency. "
                        f"They responded with: '{followup_response}' when asked for help. "
                        f"Provide extremely actionable, specific, situation-based safety tips or guidelines to assist them with their request. "
                        f"Do not write generic support statements. State clearly what they should do in 1 or 2 sentences. "
                        f"End by asking: 'Is there any other help you need, or should we exit?'"
                    )
                    assistant_reply = self.capability_worker.text_to_text_response(assistant_prompt)
                    if assistant_reply:
                        await self.capability_worker.speak(assistant_reply)

        finally:
            # CRITICAL EXIT REQUIREMENT: Smoothly hand control back to the core OpenHome Agent
            self.capability_worker.resume_normal_flow()
