from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

INTRO_PROMPT = "Welcome to OpenHome Hackathon!"
EXIT_PROMPT = "Build something great with OpenHome. Best of Luck!"

SYSTEM_PROMPT = (
    "You are a helpful, concise voice assistant. Respond in 2-3 sentences, "
    "spoken aloud, no markdown."
)

EXIT_WORDS = ("done", "stop", "quit", "exit", "goodbye", "bye", "that's all", "i'm good", "im good")


class HackathonDemoCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    async def qa_loop(self):
        await self.capability_worker.speak(INTRO_PROMPT)

        while True:
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                continue

            if any(word in user_input.lower() for word in EXIT_WORDS):
                break

            answer = self.capability_worker.text_to_text_response(
                user_input,
                system_prompt=SYSTEM_PROMPT,
            )
            await self.capability_worker.speak(answer)

        await self.capability_worker.speak(EXIT_PROMPT)
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.qa_loop())