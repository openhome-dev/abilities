import json
import requests
import time
import re
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class PerplexityWebSearchCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    async def give_advice(self):
        # Introduce the web search assistant
        msg = await self.capability_worker.wait_for_complete_transcription()
        self.worker.editor_logging_handler.error(f"User said: {msg}")

        api_key = "YOUR_API_KEY"
        INTRO_PROMPT = "Let me check that for you real quick"
        await self.capability_worker.speak(INTRO_PROMPT)

        # Create the request payload (matches your cURL example)
        payload = {
            "model": "sonar-pro",  # sonar or sonar-pro both work
            "temperature": 0.2,
            "disable_runs": False,
            "top_p": 0.9,
            "max_tokens": 150,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        """
                        Give a short, clear answer in simple spoken language.
                        Do not use symbols, citations, or abbreviations.
                        """
                    )
                },
                {
                    "role": "user",
                    "content": f"{msg}"
                }
            ]
        }

        start_time = time.time()

        # Send the request to Perplexity
        response = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=payload
        )


        # ✅ End API timer
        end_time = time.time()
        response_time = round(end_time - start_time, 3)

        # ✅ Log API response time
        self.worker.editor_logging_handler.info(f"⏱️ API Response Time: {response_time} seconds")


        # Log response status and raw text
        self.worker.editor_logging_handler.info(f"📡 Response Status: {response.status_code}")
        self.worker.editor_logging_handler.info(f"🧾 Raw Response Text:\n{response.text}")

        # Parse JSON response safely
        try:
            result = response.json()
            self.worker.editor_logging_handler.info(f"✅ Parsed JSON Response:\n{json.dumps(result, indent=2)}")
        except Exception as e:
            self.worker.editor_logging_handler.info(f"❌ Failed to parse JSON: {e}")
            result = {}

        # Extract the assistant’s message (final summary)
        search_result = result.get("choices", [{}])[0].get("message", {}).get("content", "Sorry, I couldn't find anything.")



        search_result = re.sub(r"\[\d+\]", "", search_result)
        search_result = search_result.replace("  ", " ").strip()

        # Speak the final summarized result
        await self.capability_worker.speak("Here's what I found:")
        await self.capability_worker.speak(search_result)

        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        # Initialize the worker and capability worker
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        # Start the advisor functionality
        self.worker.session_tasks.create(self.give_advice())
