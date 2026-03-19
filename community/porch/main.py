"""OpenHome ability — Porch test ability.

A minimal ability to test the Porch macOS client connection.
Trigger word: "porch"

Supported commands:
  - "open dashboard" → opens app.openhome.com in the default browser
"""

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

EXIT_WORDS = {"stop", "cancel", "exit", "quit", "never mind"}
TAG = "[Porch]"


class PorchCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            await self.capability_worker.speak("Porch here. What should I do?")
            user_input = await self.capability_worker.user_response()

            if not user_input:
                await self.capability_worker.speak("I didn't catch that.")
                return

            lowered = user_input.lower().strip()

            if any(lowered == w or lowered.startswith(f"{w} ") for w in EXIT_WORDS):
                await self.capability_worker.speak("Okay, nevermind.")
                return

            if "dashboard" in lowered or "open" in lowered:
                await self.capability_worker.speak("Opening the OpenHome dashboard.")
                response = await self.capability_worker.exec_local_command(
                    "open https://app.openhome.com",
                    timeout=10.0,
                )
                self.worker.editor_logging_handler.info(f"{TAG} exec_local_command response: {response}")
                return

            # Unknown command — echo it back
            await self.capability_worker.speak(
                f"I don't know how to do that yet. You said: {user_input}"
            )

        except Exception as err:
            self.worker.editor_logging_handler.error(f"{TAG} error: {err}")
            await self.capability_worker.speak("Something went wrong.")
        finally:
            self.capability_worker.resume_normal_flow()
