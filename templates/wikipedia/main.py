import requests
import re
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class WikipediaCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}
    
    WIKIPEDIA_API_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"

    def extract_topic(self, msg: str) -> str:
        """
        Strips 'what is' and returns just the topic.
        Example: "what is a black hole" -> "black hole"
        """
        msg = msg.lower().strip()
        if "what is" in msg:
            topic = msg.split("what is", 1)[1].strip()
            # Remove leading articles like "a", "an", "the"
            topic = re.sub(r"^(a|an|the)\s+", "", topic).strip()
            return topic
        return msg

    def query_wikipedia(self, topic: str) -> str:
        """
        Calls Wikipedia's free summary API and returns a short plain text summary.
        No API key needed — completely free and open.
        """
        # Wikipedia expects underscores instead of spaces
        formatted_topic = topic.replace(" ", "_")

        try:
            response = requests.get(
                f"{self.WIKIPEDIA_API_URL}{formatted_topic}",
                headers={"User-Agent": "BrainSkillBot/1.0"}
            )

            self.worker.editor_logging_handler.info(f"Wikipedia status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()

                # "extract" is the plain text summary Wikipedia provides
                summary = data.get("extract", "")

                # Trim to first 2 sentences for spoken brevity
                sentences = summary.split(". ")
                short_summary = ". ".join(sentences[:2]).strip()
                if not short_summary.endswith("."):
                    short_summary += "."

                return short_summary

            elif response.status_code == 404:
                return ""  # Topic not found on Wikipedia

            else:
                self.worker.editor_logging_handler.error(f"Unexpected status: {response.status_code}")
                return ""

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Wikipedia API error: {e}")
            return ""

    async def give_advice(self):
        # Step 1: Listen — capture the full "what is ..." question
        msg = await self.capability_worker.wait_for_complete_transcription()
        self.worker.editor_logging_handler.info(f"User said: {msg}")

        # Step 2: Extract the topic
        topic = self.extract_topic(msg)
        self.worker.editor_logging_handler.info(f"Topic extracted: {topic}")

        if not topic:
            await self.capability_worker.speak("Sorry, I didn't catch the topic. Try saying: what is gravity.")
            self.capability_worker.resume_normal_flow()
            return

        # Step 3: Acknowledge while fetching
        await self.capability_worker.speak(f"Let me look up {topic} for you.")

        # Step 4: Query Wikipedia
        answer = self.query_wikipedia(topic)
        self.worker.editor_logging_handler.info(f"Answer: {answer}")

        # Step 5: Speak the answer or fallback
        if answer:
            await self.capability_worker.speak(f"Here is what I found about {topic}.")
            await self.capability_worker.speak(answer)
        else:
            await self.capability_worker.speak(
                f"Sorry, I could not find anything about {topic} on Wikipedia. Please try a different word."
            )

        # Step 6: Resume normal flow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        # Initialize worker references
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        # Kick off the async ability
        self.worker.session_tasks.create(self.give_advice())