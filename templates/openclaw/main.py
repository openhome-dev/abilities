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
        try:
            user_inquiry = await self.capability_worker.wait_for_complete_transcription()

            await self.capability_worker.speak("Sending your request to OpenClaw.")

            # Route to the OpenClaw handler on the Local Link bridge (`openhome local`).
            # A plain string would run on the raw-shell `local-link` handler instead, so
            # the request is sent with an explicit target of "openclaw".
            payload = {"type": "command", "target": "openclaw", "data": user_inquiry}
            raw = await self.capability_worker.exec_local_command(
                json.dumps(payload), timeout=60.0
            )

            # Unwrap the bridge response envelope into speakable text.
            data = raw.get("data") if isinstance(raw, dict) and raw.get("type") == "response" else raw
            if isinstance(data, dict):
                reply = data.get("data") if data.get("status") == "ok" else data.get("error")
            else:
                reply = data
            reply = str(reply or "").strip() or "OpenClaw finished, but returned no output."

            self.worker.editor_logging_handler.info(reply)
            await self.capability_worker.speak(reply)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"OpenClaw ability failed: {e}")
            await self.capability_worker.speak("Something went wrong talking to OpenClaw.")
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        # Initialize the worker and capability worker
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        self.worker.session_tasks.create(self.first_function())
