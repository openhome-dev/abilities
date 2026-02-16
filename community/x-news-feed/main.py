import json
import os
import asyncio
import re

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# ============================================================================
# API CONFIGURATION
# ============================================================================
X_API_BEARER_TOKEN = "REPLACE_WITH_YOUR_KEY"

# ============================================================================
# CONSTANTS
# ============================================================================
EXIT_WORDS = [
    "exit", "stop", "quit", "done", "bye", "goodbye", "cancel",
    "nothing else", "all good", "nope", "no thanks", "i'm good",
    "that's all", "never mind", "leave", "that is all"
]

FULL_MODE_TRIGGERS = [
    "catch me up", "all trends", "full briefing", "everything",
    "run through", "brief me", "all of them", "the full list",
    "full list", "all five", "read all", "read them all",
    "dive in", "deep dive", "explore", "tell me everything"
]

MORE_WORDS = [
    "more", "rest", "continue", "yes", "yeah", "sure",
    "go ahead", "keep going", "read more", "next", "and"
]

FILLER_PHRASES = [
    "One sec, checking what's hot on X.",
    "Give me a moment, pulling the latest trends.",
    "Standby, grabbing the top topics from X.",
    "Let me see what's trending right now.",
    "Hang on, fetching the latest from X."
]

DEMO_TRENDS = [
    {"name": "Artificial Intelligence", "tweet_count": 125000},
    {"name": "Climate Summit 2026", "tweet_count": 98000},
    {"name": "Mars Mission Update", "tweet_count": 87000},
    {"name": "Tech Innovation Awards", "tweet_count": 76000},
    {"name": "Global Markets Rally", "tweet_count": 65000}
]

PREFERENCES_FILE = "x_news_prefs.json"


# ============================================================================
# MAIN ABILITY CLASS
# ============================================================================
class XNewsFeedCapability(MatchingCapability):
    """
    X News Feed Ability - fetches and reads aloud trending topics from X.
    Quick Mode: top 3, offer more.
    Full Mode: all 5, then interactive Q&A.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    trending_topics: list = []
    mode: str = "quick"
    user_name: str = "there"
    first_visit: bool = True
    trigger_phrase: str = ""

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

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.main_flow())

    # ========================================================================
    # MAIN FLOW
    # ========================================================================
    async def main_flow(self):
        try:
            # CRITICAL FIX: Wait for and capture the user's input FIRST
            await self.capture_user_input()

            # Now load preferences and detect mode
            await self.load_user_preferences()
            self.mode = self.detect_mode_from_trigger()
            self.worker.editor_logging_handler.info(f"Mode detected: {self.mode}")

            # Fetch trending topics
            await self.fetch_trending_topics_with_filler()

            if not self.trending_topics:
                await self.capability_worker.speak(
                    "I'm having trouble reaching X right now. Please try again in a moment."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Personalize greeting based on first visit
            if self.first_visit:
                await self.capability_worker.speak(
                    f"Hey {self.user_name}, welcome to X News! "
                    "First time here? I'll show you around."
                )
                self.first_visit = False
                await self.save_user_preferences()

            # Run appropriate mode
            if self.mode == "full":
                await self.full_mode()
            else:
                await self.quick_mode()

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error in main_flow: {e}")
            await self.capability_worker.speak(
                "Sorry, something went wrong. Please try again."
            )
            self.capability_worker.resume_normal_flow()

    # ========================================================================
    # CAPTURE USER INPUT - THE CRITICAL FIX
    # ========================================================================
    async def capture_user_input(self):
        """
        CRITICAL: Wait for and capture the user's input that triggered this ability.
        This must run before anything else.
        """
        try:
            self.worker.editor_logging_handler.info("Waiting for user input...")

            # Method 1: Use wait_for_complete_transcription() to ensure we get the full utterance
            # This waits until the user has completely finished speaking
            user_input = await self.capability_worker.wait_for_complete_transcription()

            if user_input and user_input.strip():
                self.trigger_phrase = user_input.strip().lower()
                self.worker.editor_logging_handler.info(
                    f"Captured user input: '{self.trigger_phrase}'"
                )
                return

            # Method 2: Fallback to regular user_response if wait_for_complete_transcription fails
            user_input = await self.capability_worker.user_response()
            if user_input and user_input.strip():
                self.trigger_phrase = user_input.strip().lower()
                self.worker.editor_logging_handler.info(
                    f"Captured user input (fallback): '{self.trigger_phrase}'"
                )
                return

            # Method 3: Try to get from history as last resort
            await self.worker.session_tasks.sleep(0.5)
            history = self.worker.agent_memory.full_message_history
            if history:
                last_msg = history[-1]
                try:
                    if isinstance(last_msg, dict):
                        if last_msg.get("role") == "user":
                            self.trigger_phrase = last_msg.get("content", "").lower()
                    else:
                        if hasattr(last_msg, "role") and last_msg.role == "user":
                            self.trigger_phrase = (last_msg.content or "").lower()
                except Exception:
                    pass

            self.worker.editor_logging_handler.info(
                f"Final trigger phrase: '{self.trigger_phrase}'"
            )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error capturing user input: {e}")
            self.trigger_phrase = ""

    # ========================================================================
    # MODE DETECTION
    # ========================================================================
    def detect_mode_from_trigger(self) -> str:
        """Detect quick vs full mode by checking the captured trigger phrase."""
        if not self.trigger_phrase:
            self.worker.editor_logging_handler.info("No trigger phrase, defaulting to quick")
            return "quick"

        for phrase in FULL_MODE_TRIGGERS:
            if phrase in self.trigger_phrase:
                self.worker.editor_logging_handler.info(f"Full mode triggered by: '{phrase}'")
                return "full"

        self.worker.editor_logging_handler.info(
            f"Quick mode (trigger: '{self.trigger_phrase[:50]}')"
        )
        return "quick"

    # ========================================================================
    # FILE PERSISTENCE
    # ========================================================================
    async def load_user_preferences(self):
        """Load user preferences from persistent storage."""
        try:
            if await self.capability_worker.check_if_file_exists(PREFERENCES_FILE, False):
                raw = await self.capability_worker.read_file(PREFERENCES_FILE, False)
                prefs = json.loads(raw)
                self.user_name = prefs.get("name", "there")
                self.first_visit = prefs.get("first_visit", False)
                self.worker.editor_logging_handler.info(f"Loaded preferences for {self.user_name}")
            else:
                self.first_visit = True
                self.user_name = "there"
                await self.save_user_preferences()
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Couldn't load preferences: {e}")
            self.first_visit = True
            self.user_name = "there"

    async def save_user_preferences(self):
        """Save user preferences to persistent storage."""
        try:
            prefs = {
                "name": self.user_name,
                "first_visit": self.first_visit,
                "last_used": "x_news_feed"
            }
            await self.capability_worker.delete_file(PREFERENCES_FILE, False)
            await self.capability_worker.write_file(PREFERENCES_FILE, json.dumps(prefs), False)
            self.worker.editor_logging_handler.info("Saved preferences")
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Couldn't save preferences: {e}")

    # ========================================================================
    # PATIENT INPUT HELPER
    # ========================================================================
    async def wait_for_input(
            self,
            max_attempts: int = 5,
            wait_seconds: float = 3.0,
            context: str = ""
    ) -> str:
        """Poll for user input patiently. Returns first non-empty response or empty string."""
        for attempt in range(max_attempts):
            await self.worker.session_tasks.sleep(wait_seconds)
            user_input = await self.capability_worker.user_response()
            if user_input and user_input.strip():
                self.worker.editor_logging_handler.info(
                    f"Got input on attempt {attempt + 1}: {user_input[:60]}"
                )
                return user_input.strip()
            self.worker.editor_logging_handler.info(
                f"Empty on attempt {attempt + 1}/{max_attempts}, retrying..."
            )

        if context == "initial":
            await self.capability_worker.speak(
                "I didn't catch that. Just say 'more' to hear the rest, or I'll sign off."
            )
            await self.worker.session_tasks.sleep(2)
            user_input = await self.capability_worker.user_response()
            if user_input and user_input.strip():
                return user_input.strip()

        return ""

    # ========================================================================
    # DATA FETCHING
    # ========================================================================
    async def fetch_trending_topics_with_filler(self):
        import random
        filler = random.choice(FILLER_PHRASES)
        await self.capability_worker.speak(filler)
        await self.fetch_trending_topics()

    async def fetch_trending_topics(self):
        try:
            self.worker.editor_logging_handler.info("Fetching trending topics from X...")

            if X_API_BEARER_TOKEN in ("REPLACE_WITH_YOUR_KEY", "", None):
                self.worker.editor_logging_handler.info("Demo mode - API key not configured.")
                self.trending_topics = DEMO_TRENDS.copy()
                return

            headers = {"Authorization": f"Bearer {X_API_BEARER_TOKEN}"}
            url = "https://api.twitter.com/1.1/trends/place.json"
            params = {"id": 1}

            resp = await asyncio.to_thread(
                requests.get, url, headers=headers, params=params, timeout=10
            )

            if resp.status_code == 200:
                data = resp.json()
                if data and "trends" in data[0]:
                    self.trending_topics = [
                        {
                            "name": t.get("name", "Unknown"),
                            "tweet_count": t.get("tweet_volume") or 0
                        }
                        for t in data[0]["trends"][:5]
                    ]
                    self.worker.editor_logging_handler.info(
                        f"Fetched {len(self.trending_topics)} live trends."
                    )
                    return

            self.worker.editor_logging_handler.warning(f"API {resp.status_code} - using demo data.")
            self.trending_topics = DEMO_TRENDS.copy()

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Fetch error: {e} - using demo data.")
            self.trending_topics = DEMO_TRENDS.copy()

    # ========================================================================
    # QUICK MODE
    # ========================================================================
    async def quick_mode(self):
        """Top 3, offer more, patient wait for response."""
        await self.capability_worker.speak(
            f"Hey {self.user_name}, here are the top 3 trending topics right now:"
        )
        await self.worker.session_tasks.sleep(0.4)

        for i, topic in enumerate(self.trending_topics[:3], 1):
            await self.speak_single_trend(i, topic)
            await self.worker.session_tasks.sleep(0.3)

        await self.capability_worker.speak("Want to hear more, or are you all set?")

        user_input = await self.wait_for_input(max_attempts=5, wait_seconds=3.0, context="initial")

        if not user_input:
            await self.capability_worker.speak("Catch you later!")
            self.capability_worker.resume_normal_flow()
            return

        user_input_lower = user_input.lower()

        if self.is_exit_command(user_input_lower):
            await self.generate_contextual_goodbye()
            self.capability_worker.resume_normal_flow()
            return

        if self.is_more_request(user_input_lower):
            await self.capability_worker.speak("Here are the remaining trends:")
            await self.worker.session_tasks.sleep(0.3)
            for i, topic in enumerate(self.trending_topics[3:], 4):
                await self.speak_single_trend(i, topic)
                await self.worker.session_tasks.sleep(0.3)
            await self.capability_worker.speak("That's all 5. Anything else?")

            final = await self.wait_for_input(max_attempts=3, wait_seconds=2.0)
            if not final or self.is_exit_command(final.lower()):
                await self.capability_worker.speak("Take care!")
        else:
            await self.capability_worker.speak("That's what's hot on X. Anything else?")
            final = await self.wait_for_input(max_attempts=3, wait_seconds=2.0)
            if not final or self.is_exit_command(final.lower()):
                await self.capability_worker.speak("Alright, catch you later!")

        self.capability_worker.resume_normal_flow()

    # ========================================================================
    # FULL MODE
    # ========================================================================
    async def full_mode(self):
        """Read all 5, then open interactive Q&A loop."""
        await self.capability_worker.speak(
            f"Hey {self.user_name}, here's your full rundown of the top 5 trending topics on X:"
        )
        await self.worker.session_tasks.sleep(0.5)

        for i, topic in enumerate(self.trending_topics, 1):
            await self.speak_single_trend(i, topic)
            await self.worker.session_tasks.sleep(0.4)

        await self.capability_worker.speak(
            "Want to know more about any of these? Ask away, or say done when you're finished."
        )

        await self.interactive_loop()

    async def interactive_loop(self):
        """Q&A loop with idle detection."""
        idle_count = 0

        while True:
            user_input = await self.wait_for_input(max_attempts=4, wait_seconds=3.0)

            if not user_input:
                idle_count += 1
                if idle_count >= 2:
                    await self.capability_worker.speak(
                        "I'm still here if you need anything. Otherwise I'll sign off."
                    )
                    await self.worker.session_tasks.sleep(3)
                    break
                continue

            idle_count = 0
            user_input_lower = user_input.lower()

            if self.is_exit_command(user_input_lower):
                await self.generate_contextual_goodbye()
                break

            if any(p in user_input_lower for p in ["again", "repeat", "read again"]):
                await self.capability_worker.speak("Sure, here they are again:")
                await self.worker.session_tasks.sleep(0.3)
                for i, topic in enumerate(self.trending_topics, 1):
                    await self.speak_single_trend(i, topic)
                    await self.worker.session_tasks.sleep(0.3)
                await self.capability_worker.speak("Anything else?")
                continue

            if any(w in user_input_lower for w in [
                "number", "topic", "tell me about", "more about"
            ]):
                await self.handle_topic_question(user_input_lower)
                continue

            await self.handle_general_question(user_input)

        self.capability_worker.resume_normal_flow()

    # ========================================================================
    # HELPERS
    # ========================================================================
    def is_exit_command(self, text: str) -> bool:
        for word in EXIT_WORDS:
            pattern = r'\b' + re.escape(word) + r'\b'
            if re.search(pattern, text):
                return True
        return False

    def is_more_request(self, text: str) -> bool:
        return any(word in text for word in MORE_WORDS)

    async def speak_single_trend(self, number: int, topic: dict):
        name = topic["name"]
        count = topic.get("tweet_count", 0)

        clean_name = re.sub(r'#', 'hashtag ', name)

        if count >= 1_000_000:
            count_text = f"{count / 1_000_000:.1f} million posts"
        elif count >= 1_000:
            count_text = f"{int(count / 1_000)} thousand posts"
        elif count > 0:
            count_text = f"{count} posts"
        else:
            count_text = None

        if count_text:
            msg = f"Number {number}: {clean_name}, with {count_text}."
        else:
            msg = f"Number {number}: {clean_name}."

        await self.capability_worker.speak(msg)

    async def handle_topic_question(self, user_input: str):
        topic_number = None
        for i in range(1, 6):
            if str(i) in user_input or self.number_to_word(i) in user_input:
                topic_number = i
                break

        if topic_number and topic_number <= len(self.trending_topics):
            name = self.trending_topics[topic_number - 1]["name"]
            prompt = (
                f"The topic '{name}' is trending on X. "
                f"Give a 2-sentence conversational explanation of why. "
                f"Be concise. Under 30 words. No markdown."
            )
            analysis = self.capability_worker.text_to_text_response(prompt)
            await self.capability_worker.speak(f"About {name}: {analysis}")
            await self.worker.session_tasks.sleep(0.3)
            await self.capability_worker.speak("What else would you like to know?")
        else:
            await self.capability_worker.speak(
                "I didn't catch that number. Try saying a number between 1 and 5."
            )

    async def handle_general_question(self, user_input: str):
        topics_context = ", ".join([t["name"] for t in self.trending_topics])
        prompt = (
            f"You are a helpful X news assistant. Current trending topics: {topics_context}.\n"
            f"User: {user_input}\n"
            f"Reply in 2 sentences max. Conversational. No markdown."
        )
        response = self.capability_worker.text_to_text_response(prompt)
        await self.capability_worker.speak(response)
        await self.worker.session_tasks.sleep(0.3)
        await self.capability_worker.speak("Anything else?")

    async def generate_contextual_goodbye(self):
        prompt = (
            "Generate a brief friendly goodbye under 10 words for a news briefing. "
            "Casual. Examples: 'Catch you later!', 'Stay informed!', 'Take care!'\nOne only:"
        )
        goodbye = self.capability_worker.text_to_text_response(prompt).strip()
        await self.capability_worker.speak(goodbye)

    def number_to_word(self, num: int) -> str:
        return {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}.get(num, "")
