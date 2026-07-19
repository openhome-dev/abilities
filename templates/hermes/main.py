import json

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class HermesCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    async def send(self, payload: dict, timeout: float = 60.0):
        """Send the protocol as a JSON string to Local Link and unwrap the reply envelope."""
        raw = await self.capability_worker.exec_local_command(json.dumps(payload), timeout=timeout)
        if isinstance(raw, dict) and raw.get("type") == "response":
            return raw.get("data")
        return raw

    async def ask_agent(self, request: str) -> str:
        """Forward the request to Hermes and return its reply. Destructive requests
        (rm -rf, sudo, or a kill command) are confirmed with the user first."""
        lowered = request.lower()
        tokens = lowered.split()
        if ("rm -rf" in lowered or "rm -fr" in lowered
                or any(t in {"sudo", "kill", "killall", "pkill"} for t in tokens)):
            ok = await self.capability_worker.run_confirmation_loop(
                "That could run a destructive command on your computer. Should I go ahead?"
            )
            if not ok:
                return "Okay, I won't run that."
        try:
            data = await self.send({"type": "command", "target": "hermes", "data": request}, timeout=60)
        except Exception:
            return "That took too long, or I lost the connection to your computer. Please try again."
        if isinstance(data, dict):
            if data.get("status") == "error":
                return data.get("error") or "The agent reported an error."
            return str(data.get("data") or "There was no response.")
        return str(data or "There was no response.")

    async def run(self):
        """Announce, confirm Openhome Local Link is connected and Hermes agent is installed, forward the first request, then loop."""
        try:
            request = await self.capability_worker.wait_for_complete_transcription()
            await self.capability_worker.speak("Sending your inquiry to Hermes, one moment.")

            connected = False
            for attempt in range(5):
                try:
                    reply = await self.send({"type": "ping"}, timeout=8)
                except Exception:
                    reply = None
                if isinstance(reply, dict) and reply.get("pong"):
                    connected = True
                    break
                if attempt < 4:
                    await self.worker.session_tasks.sleep(0.5)
            if not connected:
                await self.capability_worker.speak(
                    "Openhome local Link isn't connected. Please connect it using openhome cli on your computer, then try again."
                )
                return

            try:
                info = await self.send({"type": "discover"}, timeout=15)
            except Exception:
                info = {}
            agents = info.get("agents") or [] if isinstance(info, dict) else []
            if "hermes" not in agents:
                await self.capability_worker.speak(
                    "Hermes isn't available on your computer. Please install it and try again."
                )
                return

            await self.capability_worker.speak(await self.ask_agent(request))

            while True:
                request = await self.capability_worker.user_response()
                if not (request or "").strip():
                    continue
                if request.strip().lower().rstrip(".!?,") in {
                    "stop", "exit", "quit", "cancel", "done", "bye", "goodbye",
                    "that's all", "never mind", "nevermind",
                }:
                    await self.capability_worker.speak("Exiting now.")
                    break
                await self.capability_worker.speak("Sending your inquiry to Hermes, one moment.")
                await self.capability_worker.speak(await self.ask_agent(request))
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run()) 
