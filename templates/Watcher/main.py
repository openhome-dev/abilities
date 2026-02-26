import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
from time import time

class WatcherCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    watcher_mode: bool = False
    
    # Do not change following tag of register capability
    #{{register capability}}

    async def first_function(self):
        self.worker.editor_logging_handler.info("%s: Watcher Called"%time())
        while True:
            self.worker.editor_logging_handler.info("%s: watcher watching"%time())
            
            message_history = self.capability_worker.get_full_message_history()[-10:]
            for message in message_history:
                self.worker.editor_logging_handler.info("Role: %s, Message: %s"%(message.get("role",""), message.get("content","")))
            # await self.capability_worker.speak("watching")
            # await self.capability_worker.play_from_audio_file("alarm.mp3")
            await self.worker.session_tasks.sleep(20.0)


        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker, watcher_mode: bool):
        # Initialize the worker and capability worker
        self.worker = worker
        self.watcher_mode = watcher_mode
        self.capability_worker = CapabilityWorker(self)

        self.worker.session_tasks.create(self.first_function())
