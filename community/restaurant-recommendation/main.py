import json
import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# RESTAURANT FINDER
# Asks the user what they're looking for, searches Foursquare Places API,
# summarizes results, and offers to read details on a specific pick.
# Supports continuous conversation — user can keep searching until done.
# =============================================================================

FSQ_API_KEY = ""  # Add your own API key here
FSQ_SEARCH_URL = "https://places-api.foursquare.com/places/search"
FSQ_HEADERS = {
    "Authorization": f"Bearer {FSQ_API_KEY}",
    "Accept": "application/json",
    "X-Places-Api-Version": "2025-06-17",
}

EXIT_WORDS = {"exit", "stop", "quit", "done", "bye", "no thanks", "nothing"}

PARSE_REQUEST_PROMPT = (
    "Extract the food/restaurant type and location from this request: '{user_request}'. "
    "Reply with ONLY a raw JSON object with keys 'query' and 'location'. "
    "No markdown, no explanation, no code fences. "
    ""
    "Example: {{\"query\": \"sushi\", \"location\": \"Los Angeles, CA\"}}. "
    "If location is not mentioned, use empty string for location."
)

SUMMARIZE_RESULTS_PROMPT = (
    "Here are restaurant search results: {results}. "
    "Summarize the top 3 in 2-3 sentences, voice-friendly, mentioning name and neighborhood. "
    "Then ask if they'd like details on any of them, or if they want to search for something else."
)

DETAILS_PROMPT = (
    "Here are the details for this restaurant: {details}. "
    "Give the address, phone number (read digit by digit), and hours in 2-3 sentences."
)

INTENT_PROMPT = (
    "The user said: '{follow_up}'. The restaurant results were: {results}. "
    "Reply with ONLY one of the following: "
    "- The fsq_id of a specific restaurant if they want details on one. "
    "- 'search' if they want to search for something different. "
    "- 'done' if they are finished."
)


class RestaurantRecommendationCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.find_restaurant())

    async def parse_request(self, user_request: str) -> dict:
        """Use LLM to extract query and location from natural language."""
        try:
            raw = self.capability_worker.text_to_text_response(
                PARSE_REQUEST_PROMPT.format(user_request=user_request)
            )
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except json.JSONDecodeError:
            self.worker.editor_logging_handler.error(f"[RestaurantFinder] Failed to parse JSON, retrying. LLM response was: {raw}")
            return await self.parse_request(user_request)

    async def get_details(self, fsq_id: str) -> None:
        """Fetch and speak details for a specific restaurant."""
        response = requests.get(
            f"https://places-api.foursquare.com/places/{fsq_id}",
            headers=FSQ_HEADERS,
            timeout=10,
        )
        details = response.json()
        speech = self.capability_worker.text_to_text_response(
            DETAILS_PROMPT.format(details=json.dumps(details))
        )
        await self.capability_worker.speak(speech)

    async def find_restaurant(self):
        user_request = await self.capability_worker.run_io_loop(
            "Sure! What kind of food or restaurant are you looking for, and where?"
        )

        while True:
            if any(word in user_request.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak("Enjoy your meal!")
                self.capability_worker.resume_normal_flow()
                return

            # Parse request
            params = await self.parse_request(user_request)

            # Search Foursquare
            await self.capability_worker.speak("Let me look that up for you.")
            fsq_params = {"query": params["query"], "limit": 3}
            if params.get("location"):
                fsq_params["near"] = params["location"]
            response = requests.get(FSQ_SEARCH_URL, headers=FSQ_HEADERS, params=fsq_params, timeout=10)
            results = response.json().get("results", [])

            if not results:
                user_request = await self.capability_worker.run_io_loop(
                    "Sorry, I couldn't find anything matching that. What else can I search for?"
                )
                continue

            # Summarize results and ask what they want to do next
            summary = self.capability_worker.text_to_text_response(
                SUMMARIZE_RESULTS_PROMPT.format(results=json.dumps(results))
            )
            follow_up = await self.capability_worker.run_io_loop(summary)

            if any(word in follow_up.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak("Enjoy your meal!")
                self.capability_worker.resume_normal_flow()
                return

            # Determine intent: details, new search, or done
            intent = self.capability_worker.text_to_text_response(
                INTENT_PROMPT.format(follow_up=follow_up, results=json.dumps(results))
            )
            intent = intent.strip().lower()

            if intent == "done":
                await self.capability_worker.speak("Enjoy your meal!")
                self.capability_worker.resume_normal_flow()
                return
            elif intent == "search":
                user_request = await self.capability_worker.run_io_loop(
                    "Sure! What are you looking for?"
                )
                if any(word in user_request.lower() for word in EXIT_WORDS):
                    await self.capability_worker.speak("Enjoy your meal!")
                    self.capability_worker.resume_normal_flow()
                    return
            else:
                # intent is an fsq_id — fetch and speak details
                await self.get_details(intent)
                user_request = await self.capability_worker.run_io_loop(
                    "Would you like to search for something else?"
                )
                if any(word in user_request.lower() for word in EXIT_WORDS):
                    await self.capability_worker.speak("Enjoy your meal!")
                    self.capability_worker.resume_normal_flow()
                    return
