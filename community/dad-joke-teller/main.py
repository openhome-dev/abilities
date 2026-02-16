import json
import os
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# Exit words — user can say any of these to stop
EXIT_WORDS = ["stop", "exit", "quit", "done", "no", "enough", "cancel", "that's enough"]

# Intent classification prompt for LLM
INTENT_PROMPT = """User said: "{user_input}"
Is this a request for a joke (yes/another/sure/one more) or asking to stop (no/done/stop/quit)?
Reply with ONLY one word: "joke" or "exit" """


class DadJokeTellerCapability(MatchingCapability):
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
        self.worker.session_tasks.create(self.run_dad_joke_flow())

    def _fetch_joke(self) -> Optional[str]:
        """Fetch a random dad joke from icanhazdadjoke.com. Returns None on failure."""
        try:
            response = requests.get(
                "https://icanhazdadjoke.com/",
                headers={"Accept": "application/json"},
                timeout=5,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("joke", None)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Dad joke API error: {e}")
        return None

    def _wants_exit(self, user_input: str) -> bool:
        """Check if user wants to stop. Uses simple keyword check first, then LLM fallback."""
        if not user_input or not user_input.strip():
            return False
        lower = user_input.lower().strip()
        if any(word in lower for word in EXIT_WORDS):
            return True
        # Use LLM for ambiguous cases
        intent = self.capability_worker.text_to_text_response(
            INTENT_PROMPT.format(user_input=user_input)
        )
        return "exit" in intent.lower().strip()

    async def run_dad_joke_flow(self):
        """Main conversation loop. Tell jokes, ask for more, exit on stop."""
        try:
            await self.capability_worker.speak(
                "Welcome to Dad Joke Time. Want a joke? Say stop when you're done."
            )

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak(
                        "I didn't catch that. Want a joke? Say stop when you're done."
                    )
                    continue

                if self._wants_exit(user_input):
                    await self.capability_worker.speak(
                        "Alright, no more jokes. Talk to you later."
                    )
                    break

                # Fetch and tell joke
                joke = self._fetch_joke()
                if joke:
                    await self.capability_worker.speak(joke)
                    await self.capability_worker.speak(
                        "Want another? Say stop when you're done."
                    )
                else:
                    await self.capability_worker.speak(
                        "I couldn't get a joke right now. Try again?"
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Dad joke ability error: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Come back for jokes later."
            )
        finally:
            self.capability_worker.resume_normal_flow()
