import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

class OpentestCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    
    # Do not change following tag of register capability
    #{{register capability}}


    async def first_function(self):
        user_inquiry = await self.capability_worker.wait_for_complete_transcription()

        history = []
        
        history.append(
            {
                "role": "user",
                "content": user_inquiry,
            },
        )
        # history.append(
        #     {
        #         "role": "assistant",
        #         "content": terminal_command,
        #     },
        # )
        # Execute the generated command
        await self.capability_worker.speak(f"Sending Inquiry to OpenClaw")
        response = await self.capability_worker.exec_local_command(user_inquiry)

        self.worker.editor_logging_handler.info(response)
        # Speak the response
        
        await self.capability_worker.speak(response["data"])
        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        # Initialize the worker and capability worker
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        self.worker.session_tasks.create(self.first_function())
