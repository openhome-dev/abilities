import json

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

TRIGGERS = (
    "talk to hermes", "hermes agent", "relay to hermes",
    "hermes relay", "forward to hermes",
    "my agent", "call hermes", "ask my agent", "tell my agent",
)

REQUEST_TIMEOUT_S = 30


class HermesConnector(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    async def first_function(self):
        try:
            user_inquiry = await self.capability_worker.wait_for_complete_transcription()

            # Strip trigger prefix so Hermes gets the actual question
            lowered = user_inquiry.lower().strip()
            for trigger in TRIGGERS:
                if lowered.startswith(trigger):
                    user_inquiry = user_inquiry[len(trigger):].strip()
                    break

            if not user_inquiry:
                user_inquiry = "Hello"

            await self.capability_worker.speak("Sending your message to Hermes")

            try:
                # Local Link's bridge (openhome local start) has a built-in
                # "hermes" backend — it runs `hermes -z "<data>"` on the
                # user's own machine and returns the reply. No tunnel, no
                # API key, no public exposure: this never leaves localhost.
                command = json.dumps({
                    "type": "command",
                    "target": "hermes",
                    "data": user_inquiry,
                    "timeout": REQUEST_TIMEOUT_S,
                })
                response = await self.capability_worker.exec_local_command(
                    command, timeout=REQUEST_TIMEOUT_S,
                )

                answer = response
                if isinstance(response, dict):
                    answer = (
                        response.get("data")
                        or response.get("text")
                        or response.get("result")
                        or ""
                    )
                answer = str(answer).strip() if answer else ""

                await self.capability_worker.speak(
                    answer or "Hermes didn't return a response."
                )

            except Exception as exec_err:
                self.worker.editor_logging_handler.error(f"Hermes Local Link request failed: {exec_err}")
                await self.capability_worker.speak(
                    "Could not reach Hermes. Make sure `openhome local start` is running "
                    "and `hermes doctor` reports no problems."
                )

        except Exception as err:
            try:
                self.worker.editor_logging_handler.error(f"HermesConnector error: {err}")
                await self.capability_worker.speak("Hermes connector encountered an error.")
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.first_function())
