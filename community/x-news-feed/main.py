import json
import re
import random

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# ============================================================================
# API CONFIGURATION
# ============================================================================
X_API_BEARER_TOKEN = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# ============================================================================
# TOPIC SEEDS — selectable options shown to user in demo mode
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
    "that's all", "never mind", "leave", "that is all",
]

FULL_MODE_TRIGGERS = [
    "catch me up", "all trends", "full briefing", "everything",
    "run through", "brief me", "all of them", "the full list",
    "full list", "all five", "read all", "read them all",
    "dive in", "deep dive", "explore", "tell me everything", "all tweets",
    "all three", "show all",
]

MORE_WORDS = [
    "more", "rest", "continue", "yes", "yeah", "sure",
    "go ahead", "keep going", "read more", "next", "and",
]

FILLER_INTRO_TEMPLATES = [
    "Let me fetch the top tweets on {topic}, just a moment.",
    "Pulling the most popular tweets on {topic} right now.",
    "Give me a second, grabbing the top tweets on {topic}.",
    "One moment, fetching top tweets on {topic}.",
    "Looking up the best tweets on {topic} for you.",
]

# ============================================================================
# Demo tweet data — 3 representative tweets per TOPIC_SEED
# ============================================================================
DEMO_TRENDS = {
    "Artificial Intelligence": {
        "summary": "Developers are debating how AI changes workflows across every seniority level, from building basics to orchestrating full agent teams.",
        "tweets": [
            {"text": "2026 is the year of AI. But we use it differently at junior, mid, senior levels. Build foundations, collab with agents, orchestrate teams.", "score": 420},
            {"text": "Every company is now an AI company whether they like it or not. The ones who adapt their workflows will win. The rest will be left behind.", "score": 310},
            {"text": "AI agents are not replacing engineers. They are replacing the boring parts. The creative, architectural thinking? Still 100% human.", "score": 275},
        ],
    },
    "Crypto": {
        "summary": "Real-world asset tokenisation is gaining momentum, with developers blending physical infrastructure and digital tokens into new hybrid ecosystems.",
        "tweets": [
            {"text": "My new legacy is a global network of 12 luxury eco-hubs combined with a new token. Real assets on-chain is the future.", "score": 120},
            {"text": "Bitcoin just crossed 105k again. The institutional money did not leave, they were just waiting for the right regulatory green light.", "score": 98},
            {"text": "The next wave of DeFi will not be speculative. It will be boring, compliant, and massive. Real assets, real yields, real users.", "score": 85},
        ],
    },
    "Climate": {
        "summary": "Climate Summit 2026 has produced a landmark multi-nation commitment on emissions, reigniting optimism about coordinated global climate action.",
        "tweets": [
            {"text": "The Climate Summit 2026 concluded with 47 nations signing binding emissions targets, the most ambitious global agreement since Paris.", "score": 980},
            {"text": "Solar is now the cheapest energy source in history. Every new coal plant built today is a stranded asset within 10 years. The math is clear.", "score": 740},
            {"text": "Carbon capture tech just hit a new efficiency milestone. We might actually have more tools than we thought to pull this back.", "score": 610},
        ],
    },
    "Tech Innovation": {
        "summary": "Distributed GPU rendering is turning heads, with new platforms promising to make high-end graphics accessible on everyday consumer hardware.",
        "tweets": [
            {"text": "Ready to put your GPU to work? New platforms are bridging the gap between high-end rendering and everyday devices for developers and gamers alike.", "score": 350},
            {"text": "Spatial computing is finally hitting its stride. The hardware caught up with the vision. 2026 is the year it stops being a demo.", "score": 290},
            {"text": "The most underrated tech story right now: edge inference. Running large models locally on consumer devices is getting real, fast.", "score": 240},
        ],
    },
    "Global Markets": {
        "summary": "Better-than-expected inflation figures have sparked a broad market rally, lifting both traditional equities and digital assets simultaneously.",
        "tweets": [
            {"text": "Global markets rallied sharply today as inflation data came in below forecast, boosting investor confidence across equities and crypto alike.", "score": 650},
            {"text": "The Fed held rates again. Markets expected it. But the language in the statement shifted and traders caught it immediately.", "score": 520},
            {"text": "Emerging markets are quietly outperforming in 2026. Most retail investors have not noticed yet. That is the opportunity.", "score": 410},
        ],
    },
}

PREFERENCES_FILE = "x_news_prefs.json"

# X Recent Search API — 10 tweets per query, no retweets, no replies, English only
RECENT_SEARCH_URL = (
    "https://api.twitter.com/2/tweets/search/recent"
    "?query={query}%20-is%3Aretweet%20-is%3Areply%20lang%3Aen"
    "&tweet.fields=text,public_metrics"
    "&max_results=30"
)


# ============================================================================
# SCORING HELPER
# ============================================================================
def score_tweet(public_metrics):
    """Weighted engagement: likes x3 | retweets x2 | quotes x2 | replies x1 | bookmarks x1"""
    return (
        public_metrics.get("like_count", 0) * 3
        + public_metrics.get("retweet_count", 0) * 2
        + public_metrics.get("quote_count", 0) * 2
        + public_metrics.get("reply_count", 0) * 1
        + public_metrics.get("bookmark_count", 0) * 1
    )


# ============================================================================
# MAIN CAPABILITY CLASS
# ============================================================================
class XNewsFeedCapability(MatchingCapability):
    """
    X News Feed Capability for OpenHome.

    DEMO MODE (no API token configured):
      - Present the 5 static TOPIC_SEEDS as a numbered menu.
      - User picks one by number or name.
      - Show the top 3 pre-scored demo tweets for that topic.

    LIVE MODE (valid API token present):
      - Ask the user to name any topic freely.
      - Fetch up to 10 tweets from X Recent Search API (synchronous requests.get).
      - Score with weighted public_metrics, keep top 3.

    QUICK MODE (default): show top 2 tweets, offer the 3rd.
    FULL MODE (trigger phrases like "all tweets", "full briefing"):
               show all 3 upfront then open an interactive Q&A loop.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    selected_topic: str = ""
    fetched_tweets: list = []
    topic_summary: str = ""
    mode: str = "quick"
    user_name: str = "there"
    first_visit: bool = True
    trigger_phrase: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

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
            self.worker.editor_logging_handler.info(f"[XNews] Mode: {self.mode}")

            if self.first_visit:
                await self.capability_worker.speak(
                    f"Hey {self.user_name}, welcome to X News! "
                    "I will help you catch up on the latest tweets for any topic you care about."
                )
                self.first_visit = False
                await self.save_user_preferences()
            else:
                await self.capability_worker.speak(
                    f"Hey {self.user_name}, let us check what is buzzing on X."
                )

            if self._is_demo_mode():
                self.selected_topic = await self.ask_user_to_pick_topic()
                if not self.selected_topic:
                    await self.capability_worker.speak("No topic selected. Come back anytime!")
                    self.capability_worker.resume_normal_flow()
                    return
                self.fetched_tweets = DEMO_TRENDS[self.selected_topic]["tweets"]
                self.topic_summary = DEMO_TRENDS[self.selected_topic]["summary"]
            else:
                self.selected_topic = await self.ask_user_for_custom_topic()
                if not self.selected_topic:
                    await self.capability_worker.speak("No topic provided. Come back anytime!")
                    self.capability_worker.resume_normal_flow()
                    return
                await self.fetch_and_score_live_tweets(self.selected_topic)
                if not self.fetched_tweets:
                    await self.capability_worker.speak(
                        f"I could not find any tweets on {self.selected_topic} right now. "
                        "Try a different topic!"
                    )
                    self.capability_worker.resume_normal_flow()
                    return

            if self.mode == "full":
                await self.full_mode()
            else:
                await self.quick_mode()

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[XNews] main_flow error: {e}")
            await self.capability_worker.speak("Sorry, something went wrong. Please try again.")
            self.capability_worker.resume_normal_flow()

    # ========================================================================
    # DEMO vs LIVE
    # ========================================================================
    def _is_demo_mode(self):
        return X_API_BEARER_TOKEN in (
            "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "REPLACE_WITH_YOUR_KEY", "", None
        )

    # ========================================================================
    # TOPIC SELECTION — DEMO MODE
    # ========================================================================
    async def ask_user_to_pick_topic(self):
        topics_spoken = ", ".join(
            f"{i}. {name}" for i, name in enumerate(TOPIC_SEEDS, 1)
        )
        await self.capability_worker.speak(
            f"Here are the available topics: {topics_spoken}. "
            "Just say the number or the topic name."
        )

        for attempt in range(3):
            user_input = await self.wait_for_input(max_attempts=4, wait_seconds=3.0)
            if not user_input:
                if attempt < 2:
                    await self.capability_worker.speak(
                        "I did not catch that. Please say a number from 1 to 5, or a topic name."
                    )
                    continue
                return ""
            if self.is_exit_command(user_input.lower()):
                return ""
            matched = self._match_topic(user_input)
            if matched:
                self.worker.editor_logging_handler.info(f"[XNews] Topic picked: {matched}")
                return matched
            await self.capability_worker.speak(
                "I did not recognise that. Try a number from 1 to 5, "
                "or a name like Crypto or Climate."
            )

        return ""

    def _match_topic(self, user_input):
        text = user_input.strip().lower()
        for i, name in enumerate(TOPIC_SEEDS, 1):
            if str(i) in text or self.number_to_word(i) in text:
                return name
        for name in TOPIC_SEEDS:
            if any(word in text for word in name.lower().split()):
                return name
        return ""

    # ========================================================================
    # TOPIC INPUT — LIVE MODE
    # ========================================================================
    async def ask_user_for_custom_topic(self):
        await self.capability_worker.speak(
            "What topic would you like to explore? "
            "You can say anything, for example Space Exploration, Football, or Electric Vehicles."
        )
        for attempt in range(3):
            user_input = await self.wait_for_input(max_attempts=4, wait_seconds=4.0)
            if not user_input:
                if attempt < 2:
                    await self.capability_worker.speak(
                        "I did not catch that. What topic are you interested in?"
                    )
                    continue
                return ""
            if self.is_exit_command(user_input.lower()):
                return ""
            topic = user_input.strip()
            self.worker.editor_logging_handler.info(f"[XNews] Custom topic: {topic}")
            return topic
        return ""

    # ========================================================================
    # LIVE TWEET FETCHING + SCORING
    # Plain synchronous requests.get — same pattern as the OpenHome weather example.
    # No asyncio, no concurrent, no threading needed.
    # ========================================================================
    async def fetch_and_score_live_tweets(self, topic):
        filler = random.choice(FILLER_INTRO_TEMPLATES)
        await self.capability_worker.speak(filler.format(topic=topic))

        try:
            encoded_topic = requests.utils.quote(topic)
            url = RECENT_SEARCH_URL.format(query=encoded_topic)
            headers = {"Authorization": f"Bearer {X_API_BEARER_TOKEN}"}

            resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code != 200:
                self.worker.editor_logging_handler.warning(
                    f"[XNews] API {resp.status_code} for '{topic}'"
                )
                self.fetched_tweets = []
                return

            tweets = resp.json().get("data", [])
            if not tweets:
                self.worker.editor_logging_handler.warning(f"[XNews] No tweets for '{topic}'")
                self.fetched_tweets = []
                return

            scored = []
            for t in tweets:
                s = score_tweet(t.get("public_metrics", {}))
                self.worker.editor_logging_handler.info(
                    f"[XNews] score={s}  {t.get('text', '')[:60]}"
                )
                scored.append({"text": t.get("text", "").strip(), "score": s})

            scored.sort(key=lambda x: x["score"], reverse=True)
            self.fetched_tweets = scored[:3]
            self.worker.editor_logging_handler.info(
                f"[XNews] Top 3 selected for '{topic}'"
            )

            self.topic_summary = self._summarise_with_llm(topic, self.fetched_tweets)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[XNews] Fetch error for '{topic}': {e}")
            self.fetched_tweets = []

    def _summarise_with_llm(self, topic, tweets):
        """text_to_text_response is synchronous per the OpenHome docs."""
        try:
            tweet_block = "\n".join(
                f"{i + 1}. {t['text']}" for i, t in enumerate(tweets)
            )
            prompt = (
                f"You are a news analyst. Below are the top tweets on '{topic}'.\n"
                f"Write a short 1-2 sentence conversational summary capturing the key theme.\n"
                f"No markdown. No preamble. Just the summary.\n\nTweets:\n{tweet_block}"
            )
            return self.capability_worker.text_to_text_response(prompt).strip()
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"[XNews] LLM summary failed: {e}")
            return ""

    # ========================================================================
    # QUICK MODE — top 2 shown, offer the 3rd
    # ========================================================================
    async def quick_mode(self):
        count = len(self.fetched_tweets)
        show_first = min(2, count)

        await self.capability_worker.speak(
            f"Here are the top {show_first} tweets on {self.selected_topic}:"
        )
        await self.worker.session_tasks.sleep(0.4)

        for i in range(show_first):
            await self.speak_single_tweet(i + 1, self.fetched_tweets[i])
            await self.worker.session_tasks.sleep(0.3)

        if count >= 3:
            await self.capability_worker.speak(
                "There is one more tweet. Want to hear it, or are you all set?"
            )
            user_input = await self.wait_for_input(
                max_attempts=5, wait_seconds=3.0, context="initial"
            )

            if not user_input or self.is_exit_command(user_input.lower()):
                await self.generate_contextual_goodbye()
                self.capability_worker.resume_normal_flow()
                return

            if self.is_more_request(user_input.lower()) or self.is_full_mode_request(user_input.lower()):
                await self.speak_single_tweet(3, self.fetched_tweets[2])
                await self.worker.session_tasks.sleep(0.3)
                await self.capability_worker.speak("That is the top 3. Anything else?")
            else:
                await self.capability_worker.speak("No problem. Anything else you would like?")

            final = await self.wait_for_input(max_attempts=3, wait_seconds=2.0)
            if not final or self.is_exit_command(final.lower()):
                await self.capability_worker.speak("Take care!")
        else:
            await self.capability_worker.speak("That is all I found. Anything else?")
            final = await self.wait_for_input(max_attempts=3, wait_seconds=2.0)
            if not final or self.is_exit_command(final.lower()):
                await self.capability_worker.speak("Catch you later!")

        self.capability_worker.resume_normal_flow()

    # ========================================================================
    # FULL MODE — all 3 shown upfront, then Q&A loop
    # ========================================================================
    async def full_mode(self):
        count = len(self.fetched_tweets)
        await self.capability_worker.speak(
            f"Here is the full rundown of the top {count} tweets on {self.selected_topic}:"
        )
        await self.worker.session_tasks.sleep(0.5)

        for i, tweet in enumerate(self.fetched_tweets, 1):
            await self.speak_single_tweet(i, tweet)
            await self.worker.session_tasks.sleep(0.4)

        if self.topic_summary:
            await self.capability_worker.speak(f"Overall: {self.topic_summary}")
            await self.worker.session_tasks.sleep(0.3)

        await self.capability_worker.speak(
            "Want to know more about any of these? Ask away, or say done when finished."
        )
        await self.interactive_loop()

    # ========================================================================
    # INTERACTIVE Q&A LOOP
    # ========================================================================
    async def interactive_loop(self):
        idle_count = 0

        while True:
            user_input = await self.wait_for_input(max_attempts=4, wait_seconds=3.0)

            if not user_input:
                idle_count += 1
                if idle_count >= 2:
                    await self.capability_worker.speak(
                        "I am still here if you need anything. Otherwise I will sign off."
                    )
                    await self.worker.session_tasks.sleep(3)
                    break
                continue

            idle_count = 0
            lower = user_input.lower()

            if self.is_exit_command(lower):
                await self.generate_contextual_goodbye()
                break

            if any(p in lower for p in ["again", "repeat", "read again"]):
                await self.capability_worker.speak("Sure, here they are again:")
                await self.worker.session_tasks.sleep(0.3)
                for i, tweet in enumerate(self.fetched_tweets, 1):
                    await self.speak_single_tweet(i, tweet)
                    await self.worker.session_tasks.sleep(0.3)
                await self.capability_worker.speak("Anything else?")
                continue

            if any(w in lower for w in ["number", "tweet", "tell me about", "more about"]):
                await self.handle_tweet_question(lower)
                continue

            await self.handle_general_question(user_input)

        self.capability_worker.resume_normal_flow()

    # ========================================================================
    # CAPTURE INITIAL TRIGGER
    # ========================================================================
    async def capture_user_input(self):
        try:
            self.worker.editor_logging_handler.info("[XNews] Capturing trigger phrase...")

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
            self.worker.editor_logging_handler.error(f"[XNews] capture_user_input: {e}")
            self.trigger_phrase = ""

    # ========================================================================
    # MODE DETECTION
    # ========================================================================
    def detect_mode_from_trigger(self):
        if not self.trigger_phrase:
            return "quick"
        for phrase in FULL_MODE_TRIGGERS:
            if phrase in self.trigger_phrase:
                self.worker.editor_logging_handler.info(f"[XNews] Full mode via: '{phrase}'")
                return "full"
        return "quick"

    def is_full_mode_request(self, text):
        return any(phrase in text for phrase in FULL_MODE_TRIGGERS)

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
            self.worker.editor_logging_handler.warning(f"[XNews] load_prefs: {e}")
            self.first_visit = True
            self.user_name = "there"

    async def save_user_preferences(self):
        try:
            prefs = {"name": self.user_name, "first_visit": self.first_visit}
            await self.capability_worker.delete_file(PREFERENCES_FILE, False)
            await self.capability_worker.write_file(PREFERENCES_FILE, json.dumps(prefs), False)
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"[XNews] save_prefs: {e}")

    # ========================================================================
    # PATIENT INPUT HELPER
    # ========================================================================
    async def wait_for_input(self, max_attempts=5, wait_seconds=3.0, context=""):
        for attempt in range(max_attempts):
            await self.worker.session_tasks.sleep(wait_seconds)
            user_input = await self.capability_worker.user_response()
            if user_input and user_input.strip():
                return user_input.strip()
            self.worker.editor_logging_handler.info(
                f"[XNews] Empty input {attempt + 1}/{max_attempts}"
            )

        if context == "initial":
            await self.capability_worker.speak(
                "I did not catch that. Say more to hear the rest, or I will sign off."
            )
            await self.worker.session_tasks.sleep(2)
            user_input = await self.capability_worker.user_response()
            if user_input and user_input.strip():
                return user_input.strip()

        return ""

    # ========================================================================
    # PRESENTATION HELPERS
    # ========================================================================
    def clean_tweet_text(self, text):
        """
        Strip elements that are unnatural when read aloud:
          - URLs (http/https links)
          - Hashtags (#word)
          - Mentions (@word)
          - HTML entities (&amp; &lt; &gt; &quot; &#39;)
          - Excess whitespace left behind after stripping
        The cleaned text is then passed to the LLM to produce a
        single polished sentence before speaking.
        """
        # Remove URLs
        text = re.sub(r'https?://\S+', '', text)
        # Remove hashtags
        text = re.sub(r'#\S+', '', text)
        # Remove mentions
        text = re.sub(r'@\S+', '', text)
        # Decode common HTML entities
        text = text.replace('&amp;', 'and')
        text = text.replace('&lt;', 'less than')
        text = text.replace('&gt;', 'greater than')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")
        # Collapse extra spaces / newlines
        text = re.sub(r'[\r\n]+', ' ', text)
        text = re.sub(r' {2,}', ' ', text).strip()
        return text

    def polish_tweet_for_speech(self, raw_text):
        """
        Ask the LLM to rewrite the cleaned tweet as a single clean,
        natural-sounding sentence — removing leftover symbols, emoji,
        and any awkward phrasing introduced by stripping URLs/hashtags.
        """
        try:
            prompt = (
                "Rewrite the following tweet as a single clean, natural-sounding sentence "
                "suitable for being read aloud. Remove any emoji, symbols, or awkward fragments. "
                "Keep the core meaning. No markdown. No preamble. Just the sentence.\n\n"
                f"Tweet: {raw_text}"
            )
            result = self.capability_worker.text_to_text_response(prompt).strip()
            return result if result else raw_text
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"[XNews] polish_tweet failed: {e}")
            return raw_text

    async def speak_single_tweet(self, number, tweet):
        raw_text = tweet.get("text", "").strip()
        score = tweet.get("score", 0)
        if raw_text:
            cleaned = self.clean_tweet_text(raw_text)
            polished = self.polish_tweet_for_speech(cleaned)
            await self.capability_worker.speak(
                f"Tweet {number}: {polished}"
            )
        else:
            await self.capability_worker.speak(f"Tweet {number}: no content available.")

    # ========================================================================
    # Q&A HELPERS
    # ========================================================================
    async def handle_tweet_question(self, user_input):
        tweet_number = None
        for i in range(1, 4):
            if str(i) in user_input or self.number_to_word(i) in user_input:
                tweet_number = i
                break

        if tweet_number and tweet_number <= len(self.fetched_tweets):
            tweet = self.fetched_tweets[tweet_number - 1]
            text = tweet.get("text", "")
            prompt = (
                f"Topic: '{self.selected_topic}' is trending on X.\n"
                f"Tweet: \"{text}\"\n"
                f"Give an additional 1-2 sentence conversational insight about why this tweet matters. "
                f"Be concise. Under 40 words. No markdown."
            )
            analysis = self.capability_worker.text_to_text_response(prompt)
            await self.capability_worker.speak(f"More on tweet {tweet_number}: {analysis}")
            await self.worker.session_tasks.sleep(0.3)
            await self.capability_worker.speak("What else would you like to know?")
        else:
            await self.capability_worker.speak(
                f"I did not catch that. Try saying a number between 1 and {len(self.fetched_tweets)}."
            )

    async def handle_general_question(self, user_input):
        tweets_context = " | ".join(t.get("text", "") for t in self.fetched_tweets)
        prompt = (
            f"You are a helpful X news assistant. The user asked about '{self.selected_topic}'.\n"
            f"Top tweets: {tweets_context}\n"
            f"Summary: {self.topic_summary}\n"
            f"User question: {user_input}\n"
            f"Reply in 2 sentences max. Conversational. No markdown."
        )
        response = self.capability_worker.text_to_text_response(prompt)
        await self.capability_worker.speak(response)
        await self.worker.session_tasks.sleep(0.3)
        await self.capability_worker.speak("Anything else?")

    async def generate_contextual_goodbye(self):
        prompt = (
            "Generate a brief friendly goodbye under 10 words for a news briefing. "
            "Casual. Examples: Catch you later, Stay informed, Take care. One only:"
        )
        goodbye = self.capability_worker.text_to_text_response(prompt).strip()
        await self.capability_worker.speak(goodbye)

    # ========================================================================
    # UTILITY
    # ========================================================================
    def is_exit_command(self, text):
        for word in EXIT_WORDS:
            if re.search(r'\b' + re.escape(word) + r'\b', text):
                return True
        return False

    def is_more_request(self, text):
        return any(word in text for word in MORE_WORDS)

    def number_to_word(self, num):
        return {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}.get(num, "")
