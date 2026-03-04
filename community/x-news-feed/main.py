import asyncio
import json
import re

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# ============================================================================
# API CONFIGURATION
# ============================================================================
X_API_BEARER_TOKEN = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# ============================================================================
# TOPIC SEEDS — one API call per topic, best tweet selected per topic
# ============================================================================
TOPIC_SEEDS = [
    "Artificial Intelligence",
    "Crypto",
    "Climate",
    "Tech Innovation",
    "Global Markets",
]

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
    "dive in", "deep dive", "explore", "tell me everything", 'all tweets'
]

MORE_WORDS = [
    "more", "rest", "continue", "yes", "yeah", "sure",
    "go ahead", "keep going", "read more", "next", "and"
]

FILLER_PHRASES = [
    "One sec, checking what's hot on X.",
    "Give me a moment, pulling the latest tweets.",
    "Standby, grabbing the top topics from X.",
    "Let me see what's trending right now.",
    "Hang on, fetching the latest from X."
]

FILLER_INTRO_TEMPLATES = [
    "Let me fetch the top tweets on {topics} — just a moment.",
    "Pulling the most popular tweets on {topics} right now.",
    "Give me a second, grabbing the top tweets on {topics}.",
    "One moment — fetching top tweets on {topics}.",
    "Looking up the best tweets on {topics} for you.",
]

# Demo data — one entry per TOPIC_SEED, mirrors live structure {name, top_tweet, score, summary}
DEMO_TRENDS = [
    {
        "name": "Artificial Intelligence",
        "top_tweet": "2026 is the year of AI. But we use it differently at junior, mid, senior levels. Build foundations, collab with agents, orchestrate teams.",
        "score": 42,
        "summary": "Developers are debating how AI changes workflows across every seniority level, from building basics to orchestrating full agent teams."
    },
    {
        "name": "Crypto",
        "top_tweet": "I'm Sergey Polonsky, the developer behind Moscow City. My new legacy is a global network of 12 luxury eco-hubs combined with the $OAZIS token.",
        "score": 12,
        "summary": "Real-world asset tokenisation is gaining momentum, with developers blending physical infrastructure and digital tokens into new hybrid ecosystems."
    },
    {
        "name": "Climate",
        "top_tweet": "The Climate Summit 2026 concluded with 47 nations signing binding emissions targets, the most ambitious global agreement since Paris.",
        "score": 98,
        "summary": "Climate Summit 2026 has produced a landmark multi-nation commitment on emissions, reigniting optimism about coordinated global climate action."
    },
    {
        "name": "Tech Innovation",
        "top_tweet": "Ready to put your GPU to work? YOM Official is bridging the gap between high-end rendering and everyday devices for developers and gamers alike.",
        "score": 35,
        "summary": "Distributed GPU rendering is turning heads, with new platforms promising to make high-end graphics accessible on everyday consumer hardware."
    },
    {
        "name": "Global Markets",
        "top_tweet": "Global markets rallied sharply today as inflation data came in below forecast, boosting investor confidence across equities and crypto alike.",
        "score": 65,
        "summary": "Better-than-expected inflation figures have sparked a broad market rally, lifting both traditional equities and digital assets simultaneously."
    },
]

PREFERENCES_FILE = "x_news_prefs.json"

# Recent Search API — fetches 10 tweets per query
RECENT_SEARCH_URL = (
    "https://api.twitter.com/2/tweets/search/recent"
    "?query={query} -is:retweet -is:reply lang:en"
    "&tweet.fields=text,public_metrics"
    "&max_results=10"
)


# ============================================================================
# SCORING HELPER
# ============================================================================
def score_tweet(public_metrics: dict) -> int:
    """
    Compute a weighted engagement score from public_metrics.
    Weights:  likes x3  |  retweets x2  |  quotes x2  |  replies x1  |  bookmarks x1
    Impression count excluded — it reflects reach, not engagement quality.
    """
    return (
        public_metrics.get("like_count", 0) * 3
        + public_metrics.get("retweet_count", 0) * 2
        + public_metrics.get("quote_count", 0) * 2
        + public_metrics.get("reply_count", 0) * 1
        + public_metrics.get("bookmark_count", 0) * 1
    )


# ============================================================================
# MAIN ABILITY CLASS
# ============================================================================
class XNewsFeedCapability(MatchingCapability):
    """
    X News Feed Ability — for each topic in TOPIC_SEEDS:
      1. Fetch 10 recent tweets via Recent Search API
      2. Score each tweet with weighted public_metrics engagement
      3. Keep the highest-scoring tweet as the topic representative
      4. Send all 5 top tweets to the LLM for trend-style summaries
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

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.main_flow())

    # ========================================================================
    # MAIN FLOW
    # ========================================================================
    async def main_flow(self):
        try:
            await self.capture_user_input()

            await self.load_user_preferences()
            self.mode = self.detect_mode_from_trigger()
            self.worker.editor_logging_handler.info(f"Mode detected: {self.mode}")

            await self.fetch_trending_topics_with_filler()

            if not self.trending_topics:
                await self.capability_worker.speak(
                    "I'm having trouble reaching X right now. Please try again in a moment."
                )
                self.capability_worker.resume_normal_flow()
                return

            if self.first_visit:
                await self.capability_worker.speak(
                    f"Hey {self.user_name}, welcome to X News! "
                    "First time here? I'll show you around."
                )
                self.first_visit = False
                await self.save_user_preferences()

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
    # CAPTURE USER INPUT
    # ========================================================================
    async def capture_user_input(self):
        try:
            self.worker.editor_logging_handler.info("Waiting for user input...")

            user_input = await self.capability_worker.wait_for_complete_transcription()
            if user_input and user_input.strip():
                self.trigger_phrase = user_input.strip().lower()
                return

            user_input = await self.capability_worker.user_response()
            if user_input and user_input.strip():
                self.trigger_phrase = user_input.strip().lower()
                return

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

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error capturing user input: {e}")
            self.trigger_phrase = ""

    # ========================================================================
    # MODE DETECTION
    # ========================================================================
    def detect_mode_from_trigger(self) -> str:
        if not self.trigger_phrase:
            return "quick"
        for phrase in FULL_MODE_TRIGGERS:
            if phrase in self.trigger_phrase:
                self.worker.editor_logging_handler.info(f"Full mode triggered by: '{phrase}'")
                return "full"
        return "quick"

    # ========================================================================
    # FILE PERSISTENCE
    # ========================================================================
    async def load_user_preferences(self):
        try:
            if await self.capability_worker.check_if_file_exists(PREFERENCES_FILE, False):
                raw = await self.capability_worker.read_file(PREFERENCES_FILE, False)
                prefs = json.loads(raw)
                self.user_name = prefs.get("name", "there")
                self.first_visit = prefs.get("first_visit", False)
            else:
                self.first_visit = True
                self.user_name = "there"
                await self.save_user_preferences()
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Couldn't load preferences: {e}")
            self.first_visit = True
            self.user_name = "there"

    async def save_user_preferences(self):
        try:
            prefs = {"name": self.user_name, "first_visit": self.first_visit, "last_used": "x_news_feed"}
            await self.capability_worker.delete_file(PREFERENCES_FILE, False)
            await self.capability_worker.write_file(PREFERENCES_FILE, json.dumps(prefs), False)
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Couldn't save preferences: {e}")

    # ========================================================================
    # PATIENT INPUT HELPER
    # ========================================================================
    async def wait_for_input(self, max_attempts: int = 5, wait_seconds: float = 3.0, context: str = "") -> str:
        for attempt in range(max_attempts):
            await self.worker.session_tasks.sleep(wait_seconds)
            user_input = await self.capability_worker.user_response()
            if user_input and user_input.strip():
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
    # DATA FETCHING — per-topic, scored, top-tweet selection
    # ========================================================================
    async def fetch_trending_topics_with_filler(self):
        import random

        # Build a natural-language list of the topic seeds
        # e.g. "Artificial Intelligence, Crypto, Climate, Tech Innovation, and Global Markets"
        if len(TOPIC_SEEDS) > 1:
            topics_spoken = ", ".join(TOPIC_SEEDS[:-1]) + ", and " + TOPIC_SEEDS[-1]
        else:
            topics_spoken = TOPIC_SEEDS[0]

        template = random.choice(FILLER_INTRO_TEMPLATES)
        filler_message = template.format(topics=topics_spoken)

        await self.capability_worker.speak(filler_message)
        await self.fetch_trending_topics()

    async def fetch_trending_topics(self):
        """
        For each topic in TOPIC_SEEDS:
          1. Fetch up to 10 recent tweets (no retweets, no replies, English only)
          2. Score every tweet using weighted public_metrics
          3. Select the highest-scoring tweet as the topic representative
        Then pass all 5 top tweets to the LLM for trend-style summaries.
        Falls back to DEMO_TRENDS if the API key is missing or all topic calls fail.
        """
        if X_API_BEARER_TOKEN in ("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "REPLACE_WITH_YOUR_KEY", "", None):
            self.worker.editor_logging_handler.info("Demo mode — API key not configured.")
            self.trending_topics = DEMO_TRENDS.copy()
            return

        # Fetch best tweet per topic concurrently
        tasks = [self._fetch_top_tweet_for_topic(topic) for topic in TOPIC_SEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        top_tweets = []  # [{name, top_tweet, score}, ...]
        for topic, result in zip(TOPIC_SEEDS, results):
            if isinstance(result, Exception) or result is None:
                self.worker.editor_logging_handler.warning(
                    f"No result for topic '{topic}', skipping."
                )
                continue
            top_tweets.append(result)

        if not top_tweets:
            self.worker.editor_logging_handler.warning("All topic fetches failed — using demo data.")
            self.trending_topics = DEMO_TRENDS.copy()
            return

        self.worker.editor_logging_handler.info(
            f"Collected top tweets for {len(top_tweets)} / {len(TOPIC_SEEDS)} topics. "
            "Sending to LLM for summarisation."
        )
        self.trending_topics = await self._summarise_top_tweets_with_llm(top_tweets)

    async def _fetch_top_tweet_for_topic(self, topic: str) -> dict | None:
        """
        Fetch 10 recent tweets for `topic`, score each one with public_metrics,
        and return the best as {name, top_tweet, score}.  Returns None on failure.

        Scoring formula (see score_tweet):
            likes x3  |  retweets x2  |  quotes x2  |  replies x1  |  bookmarks x1
        """
        try:
            url = RECENT_SEARCH_URL.format(query=requests.utils.quote(topic))
            headers = {"Authorization": f"Bearer {X_API_BEARER_TOKEN}"}

            resp = await asyncio.to_thread(
                requests.get, url, headers=headers, timeout=10
            )

            if resp.status_code != 200:
                self.worker.editor_logging_handler.warning(
                    f"[{topic}] API returned {resp.status_code}."
                )
                return None
            self.worker.editor_logging_handler.warning(
                f"[{topic}] API returned {resp.json()}."
            )

            tweets = resp.json().get("data", [])
            if not tweets:
                self.worker.editor_logging_handler.warning(
                    f"[{topic}] No tweets in response."
                )
                return None

            # Log all scores for debugging
            for t in tweets:
                s = score_tweet(t.get("public_metrics", {}))
                self.worker.editor_logging_handler.info(
                    f"  [{topic}] score={s:>4}  {t.get('text', '')[:60]}"
                )

            # Pick the winner
            best_tweet = max(
                tweets,
                key=lambda t: score_tweet(t.get("public_metrics", {}))
            )
            best_score = score_tweet(best_tweet.get("public_metrics", {}))

            self.worker.editor_logging_handler.info(
                f"[{topic}] WINNER score={best_score} | {best_tweet.get('text', '')[:80]}"
            )

            return {
                "name": topic,
                "top_tweet": best_tweet.get("text", "").strip(),
                "score": best_score,
            }

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[{topic}] Fetch error: {e}")
            return None

    async def _summarise_top_tweets_with_llm(self, top_tweets: list) -> list:
        """
        Send the best tweet per topic to the LLM and ask for trend-style summaries.
        Returns a list of {name, top_tweet, score, summary} dicts.
        Falls back to DEMO_TRENDS on any parsing error.
        """
        try:
            tweet_block = "\n".join(
                f"{i + 1}. Topic: {item['name']}\n   Top Tweet: {item['top_tweet']}"
                for i, item in enumerate(top_tweets)
            )

            prompt = (
                "You are a news analyst. Below are the highest-engagement tweets for each topic.\n"
                "For each topic write a short, conversational 1-2 sentence summary that captures "
                "the key theme or sentiment from that tweet.\n"
                "Return ONLY a valid JSON array — no markdown, no explanation — in this exact format:\n"
                '[{"name": "<Topic Name>", "summary": "<Short summary sentence.>"}, ...]\n\n'
                f"Topics and their top tweets:\n{tweet_block}"
            )

            raw_response = self.capability_worker.text_to_text_response(prompt)

            # Strip accidental markdown fences
            clean = raw_response.strip()
            if clean.startswith("```"):
                clean = re.sub(r"```[a-z]*\n?", "", clean).strip("` \n")

            parsed = json.loads(clean)
            if not isinstance(parsed, list) or not parsed:
                raise ValueError("LLM returned unexpected structure.")

            # Index summaries by topic name for easy lookup
            summaries_by_name = {item["name"]: item.get("summary", "") for item in parsed}

            # Merge LLM summaries back with original top-tweet data
            enriched = []
            for item in top_tweets:
                enriched.append({
                    "name": item["name"],
                    "top_tweet": item["top_tweet"],
                    "score": item["score"],
                    "summary": summaries_by_name.get(item["name"], ""),
                })

            self.worker.editor_logging_handler.info(
                f"LLM produced summaries for {len(enriched)} topics."
            )
            return enriched

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"LLM summarisation failed: {e} — using demo data."
            )
            return DEMO_TRENDS.copy()

    # ========================================================================
    # QUICK MODE
    # ========================================================================
    async def quick_mode(self):
        """Top 3 summaries, offer more, patient wait for response."""
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
            await self.capability_worker.speak("Here are the remaining topics:")
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
        """Read all 5 summaries, then open interactive Q&A loop."""
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

            if any(w in user_input_lower for w in ["number", "topic", "tell me about", "more about"]):
                await self.handle_topic_question(user_input_lower)
                continue

            await self.handle_general_question(user_input)

        self.capability_worker.resume_normal_flow()

    # ========================================================================
    # HELPERS
    # ========================================================================
    def is_exit_command(self, text: str) -> bool:
        for word in EXIT_WORDS:
            if re.search(r'\b' + re.escape(word) + r'\b', text):
                return True
        return False

    def is_more_request(self, text: str) -> bool:
        return any(word in text for word in MORE_WORDS)

    async def speak_single_trend(self, number: int, topic: dict):
        """Speak one trend. Reads the LLM summary; falls back to topic name only."""
        name = topic.get("name", "Unknown")
        summary = topic.get("summary", "")
        clean_name = re.sub(r'#', 'hashtag ', name)
        msg = f"Number {number}: {clean_name}. {summary}" if summary else f"Number {number}: {clean_name}."
        await self.capability_worker.speak(msg)

    async def handle_topic_question(self, user_input: str):
        topic_number = None
        for i in range(1, 6):
            if str(i) in user_input or self.number_to_word(i) in user_input:
                topic_number = i
                break

        if topic_number and topic_number <= len(self.trending_topics):
            topic = self.trending_topics[topic_number - 1]
            name = topic.get("name", "Unknown")
            existing_summary = topic.get("summary", "")
            top_tweet = topic.get("top_tweet", "")

            prompt = (
                f"Topic: '{name}' is trending on X.\n"
                f"Top tweet: \"{top_tweet}\"\n"
                f"Existing summary: {existing_summary}\n"
                f"Give an additional 1-2 sentence conversational insight about why this matters. "
                f"Be concise. Under 40 words. No markdown."
            )
            analysis = self.capability_worker.text_to_text_response(prompt)
            await self.capability_worker.speak(f"More on {name}: {analysis}")
            await self.worker.session_tasks.sleep(0.3)
            await self.capability_worker.speak("What else would you like to know?")
        else:
            await self.capability_worker.speak(
                "I didn't catch that number. Try saying a number between 1 and 5."
            )

    async def handle_general_question(self, user_input: str):
        topics_context = "; ".join(
            [f"{t['name']}: {t.get('summary', '')}" for t in self.trending_topics]
        )
        prompt = (
            f"You are a helpful X news assistant. Current trending topics and summaries: {topics_context}.\n"
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