from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class MTATriggerTestCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("MTA ability triggered")
            await self.capability_worker.speak(
                "MTA ability triggered successfully."
            )
        finally:
            self.capability_worker.resume_normal_flow()
