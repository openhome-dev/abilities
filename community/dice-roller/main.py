import json
import os
import random

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# DICE ROLLER
# Roll a D20 (or any die) with dramatic flair. Supports D4, D6, D8, D10,
# D12, D20, and D100. Reacts to critical hits and critical fails.
# Pattern: Speak → Listen for die type → Roll → React → Loop or Exit
# =============================================================================

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "no"}

DICE_TYPES = {
    "d4": 4, "d6": 6, "d8": 8, "d10": 10,
    "d12": 12, "d20": 20, "d100": 100,
}


class DiceRollerCapability(MatchingCapability):
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

    def parse_die(self, text: str) -> tuple[int, int]:
        """Parse user input for die type and count. Returns (sides, count)."""
        text = text.lower().strip()
        count = 1
        sides = 20  # Default to D20

        for key, val in DICE_TYPES.items():
            if key in text:
                sides = val
                break

        # Check for "2d6" or "3d20" pattern
        for word in text.split():
            word = word.strip()
            if "d" in word:
                parts = word.split("d")
                try:
                    if parts[0]:
                        count = min(int(parts[0]), 10)  # Cap at 10 dice
                    if parts[1]:
                        sides = int(parts[1])
                except ValueError:
                    pass

        return sides, max(1, count)

    async def run(self):
        await self.capability_worker.speak(
            "Time to roll! What are we rolling? D20 by default, or tell me something like 2d6 or d100."
        )

        while True:
            user_input = await self.capability_worker.user_response()

            if not user_input:
                continue

            if any(word in user_input.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak("May your rolls be ever natural twenties!")
                break

            sides, count = self.parse_die(user_input)
            rolls = [random.randint(1, sides) for _ in range(count)]
            total = sum(rolls)

            # Build the result announcement
            if count == 1:
                roll_text = str(rolls[0])
            else:
                roll_text = " + ".join(str(r) for r in rolls) + f" = {total}"

            # Generate dramatic reaction via LLM
            if sides == 20 and count == 1:
                if rolls[0] == 20:
                    context = "The user rolled a NATURAL 20 on a D20! Critical hit! Be extremely excited and dramatic."
                elif rolls[0] == 1:
                    context = "The user rolled a 1 on a D20... Critical fail! Be dramatically sympathetic."
                elif rolls[0] >= 15:
                    context = f"The user rolled a {rolls[0]} on a D20. That's a solid roll! Be encouraging."
                else:
                    context = f"The user rolled a {rolls[0]} on a D20. React naturally."
            else:
                context = f"The user rolled {count}d{sides} and got {roll_text}. React briefly."

            reaction = self.capability_worker.text_to_text_response(
                f"{context} Keep it to one short sentence."
            )

            await self.capability_worker.speak(f"{roll_text}! {reaction}")
            await self.capability_worker.speak("Roll again? Or say stop to exit.")

        self.capability_worker.resume_normal_flow()
