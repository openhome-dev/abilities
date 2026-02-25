import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
from time import time

class ReadwritefileCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    async def perform_action(self):
        user_response = await self.capability_worker.wait_for_complete_transcription()
        await self.capability_worker.speak("Writing last transcription to file.")

        if await self.capability_worker.check_if_file_exists("temp_data.txt", False):
            self.worker.editor_logging_handler.info("File already exists.")
            await self.capability_worker.write_file("temp_data.txt", "\n%s: %s"%(time(),user_response), False)
            # self.capability_worker.delete_file("hash_token.txt", False)
        else:
            self.worker.editor_logging_handler.info("File doesn't exists. Creating new file")
            await self.capability_worker.write_file("temp_data.txt", "%s: %s"%(time(),user_response), False)
        file_data = await self.capability_worker.read_file("temp_data.txt", False)
        self.worker.editor_logging_handler.info(file_data)

        last_written_line = file_data.split("\n")[-1].split(":")[1]
        await self.capability_worker.speak("Last Written Line: %s"%last_written_line)
 
        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()
 
    def call(self, worker: AgentWorker):
        # Initialize the worker and capability worker
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
 
        # Start the advisor functionality
        self.worker.session_tasks.create(self.perform_action())