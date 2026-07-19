import asyncio
import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# API TEMPLATE
# For abilities that call an external API.
# Pattern: speak -> collect input -> call API -> speak result -> exit
#
# Replace API_URL, API_KEY_NAME, and the fetch_data() parsing with your own.
# Store the API key in OpenHome Settings -> API Keys under the name API_KEY_NAME.
# =============================================================================

API_URL = "https://api.example.com/data"
API_KEY_NAME = "your_api_key_name"   # the label your key is saved under in Settings -> API Keys
REQUEST_TIMEOUT = 10


class ApiTemplateCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def fetch_data(self, query: str, api_key: str) -> str | None:
        """Call your external API and return the result as a string, or None on
        failure. Runs in a worker thread (see run) so the blocking request never
        stalls the event loop."""
        try:
            response = requests.get(
                API_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                params={"q": query},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[ApiTemplate] API returned {response.status_code}: {response.text[:300]}"
                )
                return None
            data = response.json()
            # --- Parse your API response here ---
            return str(data)
        except Exception as error:
            self.worker.editor_logging_handler.error(f"[ApiTemplate] Error: {error!r}")
            return None

    async def run(self):
        try:
            api_key = self.capability_worker.get_api_keys(API_KEY_NAME)
            if not api_key:
                await self.capability_worker.speak(
                    "I need an API key set up in settings before I can do that."
                )
                return

            await self.capability_worker.speak("Sure! What would you like me to look up?")
            query = await self.capability_worker.user_response()

            await self.capability_worker.speak("Let me check on that.")
            result = await asyncio.to_thread(self.fetch_data, query, api_key)

            if result:
                response = self.capability_worker.text_to_text_response(
                    f"Summarize this data in one short sentence for a voice response: {result}"
                )
                await self.capability_worker.speak(response)
            else:
                await self.capability_worker.speak(
                    "Sorry, I couldn't get that information right now. Try again later."
                )
        finally:
            self.capability_worker.resume_normal_flow()
