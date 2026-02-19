import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

class OpenclawCapability(MatchingCapability):
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
        check_response_system_prompt = """You are a voice assistant. Convert a command execution result into ONE short spoken sentence.

        Rules:
        - Maximum 1 sentence, 15 words or less
        - No JSON, no markdown, no code blocks, no quotes
        - No phrases like "Here's the raw response" or "The command ran"
        - If successful with no output: confirm the action was done (e.g. "Slack is now open." or "Slack has been closed.")
        - If successful with output: speak only the useful information (e.g. "Disk usage is at 42 percent.")
        - If failed: say what went wrong simply (e.g. "I couldn't find Slack on this machine.")
        - Sound natural, like a human assistant speaking out loud"""
        result = self.capability_worker.text_to_text_response(
            "Original user request: '%s'. Command result: %s" % (user_inquiry, response),
            history,
            check_response_system_prompt,
        )
        if result:
            await self.capability_worker.speak(result)
        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        # Initialize the worker and capability worker
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        self.worker.session_tasks.create(self.first_function())
