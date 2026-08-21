import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

TRIGGERS = (
    "talk to hermes", "hermes agent", "relay to hermes",
    "hermes relay", "forward to hermes",
    "my agent", "call hermes", "ask my agent", "tell my agent",
)

REQUEST_TIMEOUT_S = 30


def _key_value(raw):
    """get_api_keys() is documented to return a plain string, but defends
    against a dict shape (e.g. {"value": "..."}) just in case."""
    if isinstance(raw, dict):
        for field in ("value", "key", "secret", "api_key"):
            if raw.get(field):
                return str(raw[field])
        for v in raw.values():
            if isinstance(v, str) and v:
                return v
        return ""
    return raw or ""


class HermesConnector(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    async def first_function(self):
        try:
            user_inquiry = await self.capability_worker.wait_for_complete_transcription()

            # Strip trigger prefix so Hermes gets the actual question
            lowered = user_inquiry.lower().strip()
            for trigger in TRIGGERS:
                if lowered.startswith(trigger):
                    user_inquiry = user_inquiry[len(trigger):].strip()
                    break

            if not user_inquiry:
                user_inquiry = "Hello"

            api_url = _key_value(self.capability_worker.get_api_keys("hermes_api_url"))
            api_key = _key_value(self.capability_worker.get_api_keys("hermes_api_key"))

            if not api_url or not api_key:
                await self.capability_worker.speak(
                    "Hermes is not configured. Add hermes_api_url and hermes_api_key as secrets."
                )
                self.capability_worker.resume_normal_flow()
                return

            await self.capability_worker.speak("Sending your message to Hermes")

            try:
                resp = requests.post(
                    f"{api_url.rstrip('/')}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "hermes-agent",
                        "messages": [{"role": "user", "content": user_inquiry}],
                        "stream": False,
                    },
                    timeout=REQUEST_TIMEOUT_S,
                )
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices") or []
                answer = (
                    choices[0].get("message", {}).get("content", "").strip()
                    if choices
                    else ""
                )
                await self.capability_worker.speak(
                    answer or "Hermes didn't return a response."
                )

            except Exception as exec_err:
                self.worker.editor_logging_handler.error(f"Hermes API request failed: {exec_err}")
                await self.capability_worker.speak(
                    "Could not reach Hermes. Check that the gateway's API server is running and reachable."
                )

        except Exception as err:
            try:
                self.worker.editor_logging_handler.error(f"HermesConnector error: {err}")
                await self.capability_worker.speak("Hermes connector encountered an error.")
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.first_function())
