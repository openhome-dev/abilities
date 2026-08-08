import json
import base64
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

EXIT_WORDS = ("stop", "cancel", "exit", "quit", "goodbye", "bye", "never mind")


class FormFillerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}
    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    def _is_exit(self, text: str) -> bool:
        lowered = text.strip().lower()
        if lowered in EXIT_WORDS:
            return True
        words = lowered.split()
        return len(words) <= 3 and any(w in EXIT_WORDS for w in words)

    async def run(self):
        try:
            conversation = []
            await self.capability_worker.speak("I am your Agentic Form Filler. I can fill the Hackathon Registration, the Bug Report, or the Feedback Survey. Which one would you like?")

            while True:
                user_input = await self.capability_worker.user_response()
                if not user_input or len(user_input.strip()) < 2:
                    await self.capability_worker.speak("I didn't catch that. Goodbye!")
                    break

                if self._is_exit(user_input):
                    await self.capability_worker.speak("No problem, maybe another time!")
                    break

                history_so_far = list(conversation)
                conversation.append({"role": "user", "content": user_input})

                system_prompt = """
                Form Agent.
                Available Forms:
                1. "hackathon_registration.html" (Needs: Team, Email, Idea)
                2. "bug_report.html" (Needs: Title, Priority, Description)
                3. "feedback_survey.html" (Needs: Name, Rating, Comments)

                Rules:
                1. If missing form/fields, ask briefly. NEVER confirm.
                2. If you have ALL fields, output ONLY JSON:
                {"status": "READY", "form_name": "example.html", "data": {"key": "val"}}
                """

                llm_response = self.capability_worker.text_to_text_response(
                    user_input, history_so_far, system_prompt
                )

                if "READY" in llm_response and "{" in llm_response:
                    try:
                        json_str = llm_response[llm_response.find('{'):llm_response.rfind('}') + 1]
                        data_dict = json.loads(json_str)
                        target_form = data_dict.get("form_name", "hackathon_registration.html")
                        extracted_data = data_dict.get("data", {})

                        clean_name = target_form.replace('.html', '').replace('_', ' ')
                        await self.capability_worker.speak(f"Perfect, I have all the details. Launching the {clean_name} and filling it out now!")

                        # 1. Open browser in background to specific form
                        command_start = f"python local_runner.py start {target_form}"
                        self.worker.session_tasks.create(self.capability_worker.exec_local_command(command_start))

                        # Wait a bit for the browser to launch
                        await self.worker.session_tasks.sleep(2)

                        # 2. Inject data into the running browser
                        final_payload = json.dumps(extracted_data)
                        encoded_payload = base64.b64encode(final_payload.encode('utf-8')).decode('utf-8')
                        command_write = f"python local_runner.py write_data {encoded_payload}"
                        await self.capability_worker.exec_local_command(command_write)

                        await self.capability_worker.speak("Form submitted successfully. Let me know if you need anything else.")
                        break
                    except Exception as e:
                        self.worker.editor_logging_handler.error(f"[FormFiller] JSON parse error: {e}")
                        await self.capability_worker.speak("I got a bit confused. Let's start over.")
                        break
                else:
                    # Continue the conversation naturally!
                    conversation.append({"role": "assistant", "content": llm_response})
                    await self.capability_worker.speak(llm_response)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[FormFiller] Error: {e}")
            await self.capability_worker.speak("An error occurred.")
        finally:
            self.capability_worker.resume_normal_flow()
