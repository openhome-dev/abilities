import random

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


ANSWERS = [
    # Positive
    "It is certain.",
    "Without a doubt.",
    "You may rely on it.",
    "Yes, definitely.",
    "It is decidedly so.",
    "As I see it, yes.",
    "Most likely.",
    "Signs point to yes.",
    "Outlook good.",
    "Yes.",
    # Neutral
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again.",
    # Negative
    "Don't count on it.",
    "My reply is no.",
    "My sources say no.",
    "Outlook not so good.",
    "Very doubtful.",
]

INTROS = [
    "The spirits have spoken.",
    "The 8-ball swirls...",
    "Shaking the magic 8-ball...",
    "The mystic triangle surfaces.",
    "Consulting the ancient forces...",
]


class Magic8Ball(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _active: bool = False

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        if self._active:
            return
        self._active = True
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            await self.capability_worker.speak(
                "Magic 8-Ball activated. Ask your question."
            )

            question = await self.capability_worker.user_response()

            if not question or any(w in question.lower() for w in ["stop", "exit", "quit", "cancel"]):
                await self.capability_worker.speak("The spirits rest.")
                self.capability_worker.resume_normal_flow()
                return

            intro = random.choice(INTROS)
            answer = random.choice(ANSWERS)

            await self.capability_worker.speak(f"{intro} {answer}")
            self.capability_worker.resume_normal_flow()
        finally:
            self._active = False
