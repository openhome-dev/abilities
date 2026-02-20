import json
import os
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# API TEMPLATE
# For Abilities that call an external API.
# Pattern: Speak → Collect input → Call API → Speak result → Exit
#
# Replace API_URL, API_HEADERS, and the fetch_data() logic with your own.
# =============================================================================

# --- CONFIGURATION ---
# Replace with your actual API endpoint and headers
API_URL = "https://api.example.com/data"
API_HEADERS = {
    "Authorization": "Bearer YOUR_API_KEY_HERE",
    "Content-Type": "application/json",
}

class ApiTemplateCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def fetch_data(self, query: str) -> str | None:
        """
        Call your external API here.
        Returns the result as a string, or None on failure.
        """
        try:
            response = requests.get(
                API_URL,
                headers=API_HEADERS,
                params={"q": query},
            )
            if response.status_code == 200:
                data = response.json()
                # --- Parse your API response here ---
                return str(data)
            else:
                self.worker.editor_logging_handler.error(
                    f"[ApiTemplate] API returned {response.status_code}: {response.text}"
                )
                return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ApiTemplate] Error: {e}")
            return None

    async def run(self):
        # Step 1: Ask what they need
        await self.capability_worker.speak("Sure! What would you like me to look up?")

        # Step 2: Get user input
        user_input = await self.capability_worker.user_response()

        # Step 3: Call the API
        await self.capability_worker.speak("Let me check on that.")
        result = await self.fetch_data(user_input)

        # Step 4: Respond
        if result:
            # Use LLM to turn raw data into a natural spoken response
            response = self.capability_worker.text_to_text_response(
                f"Summarize this data in one short sentence for a voice response: {result}"
            )
            await self.capability_worker.speak(response)
        else:
            await self.capability_worker.speak(
                "Sorry, I couldn't get that information right now. Try again later."
            )

        # Step 5: ALWAYS resume normal flow
        self.capability_worker.resume_normal_flow()
