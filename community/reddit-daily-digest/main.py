import json
import os

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class RedditDailyDigestCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    stories: list = []

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
        try:
            await self.capability_worker.speak(
                "Here's your Reddit technology digest."
            )

            await self._generate_digest()

            exit_words = ["stop", "exit", "quit", "done", "cancel"]

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or user_input.strip() == "":
                    await self.capability_worker.speak(
                        "Say one, two, three, or done."
                    )
                    continue

                user_input_lower = user_input.lower()

                if any(word in user_input_lower for word in exit_words):
                    await self.capability_worker.speak("Alright. Talk soon.")
                    break

                if "one" in user_input_lower or "1" in user_input_lower:
                    await self._expand_story(0)
                elif "two" in user_input_lower or "2" in user_input_lower:
                    await self._expand_story(1)
                elif "three" in user_input_lower or "3" in user_input_lower:
                    await self._expand_story(2)
                else:
                    await self.capability_worker.speak(
                        "Say one, two, three, or done."
                    )

        except Exception:
            await self.capability_worker.speak(
                "Something went wrong. Exiting."
            )

        finally:
            self.capability_worker.resume_normal_flow()

    async def _generate_digest(self):
        try:
            headlines_prompt = (
                "Generate three realistic trending Reddit technology headlines. "
                "Return ONLY the three headlines separated by ||| with no extra text."
            )

            raw_headlines = self.capability_worker.text_to_text_response(
                headlines_prompt
            )

            if "|||" in raw_headlines:
                self.stories = [h.strip() for h in raw_headlines.split("|||")]
            else:
                self.stories = [raw_headlines.strip()]

            while len(self.stories) < 3:
                self.stories.append("More trending tech discussion on Reddit.")

            digest_prompt = (
                "Turn these three headlines into a short conversational spoken digest. "
                "Number them clearly as First, Second, Third. "
                "Keep it under four sentences total.\n\n"
                f"{self.stories[:3]}"
            )

            summary = self.capability_worker.text_to_text_response(
                digest_prompt
            )

            await self.capability_worker.speak(summary)
            await self.capability_worker.speak(
                "Want more about one, two, or three?"
            )

        except Exception:
            await self.capability_worker.speak(
                "I couldn't generate the digest right now."
            )

    async def _expand_story(self, index):
        if index >= len(self.stories):
            await self.capability_worker.speak(
                "That story isn't available."
            )
            return

        try:
            headline = self.stories[index]

            expand_prompt = (
                "Give a short spoken explanation of this Reddit technology post "
                "in two sentences max. Be conversational, not robotic.\n\n"
                f"{headline}"
            )

            details = self.capability_worker.text_to_text_response(
                expand_prompt
            )

            await self.capability_worker.speak(details)
            await self.capability_worker.speak(
                "Want another one, or are you done?"
            )

        except Exception:
            await self.capability_worker.speak(
                "I couldn't expand that story."
            )
