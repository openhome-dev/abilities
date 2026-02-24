import json
import os
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


# LOG 1: Module loaded successfully
# If you don't see LOG 2 in call(), the ability never triggered (hotword/platform issue)


class AaaCapability(MatchingCapability):
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

    # Do not change following tag
    # {{register capability}}

    def call(self, worker: AgentWorker):
        # LOG 2: call() entered — ability was triggered by hotword
        worker.editor_logging_handler.info("[TripAdvisor] LOG 2: call() entered")

        try:
            self.worker = worker
            worker.editor_logging_handler.info("[TripAdvisor] LOG 3: worker assigned")

            self.capability_worker = CapabilityWorker(self.worker)
            worker.editor_logging_handler.info("[TripAdvisor] LOG 4: CapabilityWorker created")

            self.worker.session_tasks.create(self.run())
            worker.editor_logging_handler.info("[TripAdvisor] LOG 5: run() task created")
        except Exception as e:
            worker.editor_logging_handler.error(f"[TripAdvisor] CRASH in call(): {e}")

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("[TripAdvisor] LOG 6: run() started")

            if self.worker:
                await self.worker.session_tasks.sleep(0.2)
            self.worker.editor_logging_handler.info("[TripAdvisor] LOG 7: sleep done")

            await self.capability_worker.speak(
                "Restaurant finder is working! This is a test. Say anything."
            )
            self.worker.editor_logging_handler.info("[TripAdvisor] LOG 8: speak done")

            user_input = await self.capability_worker.user_response()
            self.worker.editor_logging_handler.info(
                f"[TripAdvisor] LOG 9: user said: {user_input}"
            )

            await self.capability_worker.speak(
                f"I heard you say: {user_input}. Test complete. Goodbye!"
            )
            self.worker.editor_logging_handler.info("[TripAdvisor] LOG 10: response spoken")

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[TripAdvisor] CRASH in run(): {type(e).__name__}: {e}"
            )
        finally:
            self.worker.editor_logging_handler.info("[TripAdvisor] LOG 11: resuming normal flow")
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()
