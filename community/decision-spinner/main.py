import json
import os
import random
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# DECISION SPINNER
# A voice-activated decision wheel. Comes with default options or the user
# can provide their own. Spins with dramatic buildup, then reacts to the result.
# Pattern: Ask → Collect options (or use defaults) → Spin → React → Loop or Exit
# =============================================================================

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "no thanks"}

DEFAULT_OPTIONS = [
    "Yes", "No", "Maybe", "Absolutely", "No way",
    "Try again", "Ask later", "Go for it",
]


class DecisionSpinnerCapability(MatchingCapability):
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

    def parse_options(self, text: str) -> list[str]:
        """Try to extract custom options from user input."""
        # Check for comma-separated or "or"-separated options
        if "," in text:
            options = [o.strip() for o in text.split(",") if o.strip()]
            if len(options) >= 2:
                return options
        if " or " in text.lower():
            options = [o.strip() for o in text.lower().split(" or ") if o.strip()]
            if len(options) >= 2:
                return options
        return []

    async def run(self):
        await self.capability_worker.speak(
            "Spinning the decision wheel! Do you want the default options, "
            "or give me your own? Say something like: pizza, tacos, or sushi."
        )

        user_input = await self.capability_worker.user_response()

        if any(word in user_input.lower() for word in EXIT_WORDS):
            await self.capability_worker.speak("No spin today. Maybe next time!")
            self.capability_worker.resume_normal_flow()
            return

        # Check if user provided custom options
        custom = self.parse_options(user_input)
        if custom:
            options = custom
            await self.capability_worker.speak(
                f"Got it! Spinning between {', '.join(options)}."
            )
        elif "default" in user_input.lower() or "sure" in user_input.lower() or "yes" in user_input.lower():
            options = DEFAULT_OPTIONS
            await self.capability_worker.speak("Using the default wheel!")
        else:
            # Try to parse their input as options anyway
            custom = self.parse_options(user_input)
            if custom:
                options = custom
            else:
                options = DEFAULT_OPTIONS
                await self.capability_worker.speak("Using the default wheel!")

        while True:
            # Dramatic buildup
            await self.capability_worker.speak("Spinning...")
            await self.worker.session_tasks.sleep(1.5)

            result = random.choice(options)

            # LLM reaction to the result
            reaction = self.capability_worker.text_to_text_response(
                f"The decision spinner landed on '{result}'. "
                f"React dramatically in one short sentence, like a game show host."
            )

            await self.capability_worker.speak(f"The wheel says... {result}! {reaction}")
            await self.capability_worker.speak("Spin again, or say stop to exit.")

            user_input = await self.capability_worker.user_response()

            if not user_input:
                continue

            if any(word in user_input.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak("The wheel rests. Until next time!")
                break

            # Check if they want new options
            new_options = self.parse_options(user_input)
            if new_options:
                options = new_options
                await self.capability_worker.speak(
                    f"New options loaded: {', '.join(options)}!"
                )

        self.capability_worker.resume_normal_flow()
