import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# BASIC TEMPLATE
# The simplest Ability pattern: Speak → Listen → Respond → Exit
# Replace the logic in run() with your own.
# =============================================================================


class BasicTemplateCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

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

    async def run(self):
        # Step 1: Greet the user
        await self.capability_worker.speak("Hi! How can I help you today?")

        # Step 2: Listen for their response
        user_input = await self.capability_worker.user_response()

        # Step 3: Generate a response using the LLM
        response = self.capability_worker.text_to_text_response(
            f"Give a short, helpful response to: {user_input}"
        )

        # Step 4: Speak the response
        await self.capability_worker.speak(response)

        # Step 5: ALWAYS resume normal flow when done
        self.capability_worker.resume_normal_flow()
