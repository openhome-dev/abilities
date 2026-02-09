import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# LOOP TEMPLATE
# For interactive Abilities with multi-turn conversations.
# Pattern: Greet → Loop (Listen → Process → Respond) → Exit on command
#
# Replace the processing logic inside the while loop with your own.
# =============================================================================

# Words that will exit the Ability and return to normal flow
EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave"}


class LoopTemplateCapability(MatchingCapability):
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
        # Greet the user
        await self.capability_worker.speak(
            "I'm ready to help. Ask me anything, or say stop when you're done."
        )

        while True:
            # Listen for user input
            user_input = await self.capability_worker.user_response()

            # Skip empty input
            if not user_input:
                continue

            # Check for exit commands
            if any(word in user_input.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak("Goodbye!")
                break

            # --- YOUR LOGIC HERE ---
            # Process the input and generate a response.
            # This example uses the LLM, but you can do anything:
            # call APIs, play audio, run calculations, etc.

            response = self.capability_worker.text_to_text_response(
                f"Respond in one short sentence: {user_input}"
            )
            await self.capability_worker.speak(response)

        # ALWAYS resume normal flow when the loop ends
        self.capability_worker.resume_normal_flow()
