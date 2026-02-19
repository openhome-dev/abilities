import json
import os
from typing import Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# ── Algolia HN API endpoints ──────────────────────────────────────────
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
HN_ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"

# ── Config ────────────────────────────────────────────────────────────
DEFAULT_STORY_COUNT = 5       # Stories to surface in the digest
MAX_STORY_COUNT = 10          # Hard cap when user asks for more
REQUEST_TIMEOUT = 10          # Seconds

# ── LLM prompts ──────────────────────────────────────────────────────
DIGEST_PROMPT = (
    "You are a crisp, friendly tech-news anchor delivering a voice briefing. "
    "Summarise these {n} Hacker News stories into a short, conversational spoken "
    "digest. Number each: First, Second, Third (and so on). "
    "Do NOT use bullet points. Keep each story to one sentence — title + why it matters. "
    "Total length: under 60 words. No filler, no 'here's', no 'let me tell you'.\n\n"
    "{stories}"
)

EXPAND_PROMPT = (
    "You are a concise tech commentator. Expand on this Hacker News story in "
    "exactly 2 spoken sentences. Be direct and informative — no waffle.\n\n"
    "Title: {title}\n"
    "URL: {url}\n"
    "Points: {points} | Comments: {num_comments}\n"
    "Story text (if any): {text}\n"
)

TOPIC_PROMPT = (
    "Search Hacker News for the topic: \"{topic}\".\n"
    "Here are the top stories found:\n{stories}\n\n"
    "Summarise them in 2 spoken sentences, mentioning the count. Be conversational."
)

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "no", "nope", "nothing"}
TOPIC_HINT_WORDS = {"about", "search", "find", "look up", "topic", "show me", "anything on", "what about"}
MORE_WORDS = {"more", "another", "next", "continue", "keep going"}


class HNDigestCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    initial_request: Optional[str] = None
    stories: List[Dict] = []

    # ── Registration ──────────────────────────────────────────────────

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

    # ── Entry point ───────────────────────────────────────────────────

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.stories = []
        self.initial_request = None

        for attr in ("transcription", "last_transcription", "current_transcription"):
            try:
                val = getattr(worker, attr, None)
                if val and str(val).strip():
                    self.initial_request = str(val).strip()
                    break
            except Exception:
                pass

        self.worker.session_tasks.create(self.run())

    # ── Logging helpers ───────────────────────────────────────────────

    def _log(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(f"[HNDigest] {msg}")

    def _err(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(f"[HNDigest] {msg}")

    # ── API helpers ───────────────────────────────────────────────────

    def _fetch_front_page(self, count: int = DEFAULT_STORY_COUNT) -> List[Dict]:
        """Fetch top front-page stories via Algolia HN search."""
        try:
            resp = requests.get(
                HN_SEARCH_URL,
                params={"tags": "front_page", "hitsPerPage": count},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                self._err(f"front_page fetch returned {resp.status_code}")
                return []
            hits = resp.json().get("hits", [])
            self._log(f"Fetched {len(hits)} front-page stories")
            return hits
        except Exception as exc:
            self._err(f"front_page fetch error: {exc}")
            return []

    def _fetch_topic(self, topic: str, count: int = 5) -> List[Dict]:
        """Search HN for a specific topic."""
        try:
            resp = requests.get(
                HN_SEARCH_URL,
                params={"query": topic, "tags": "story", "hitsPerPage": count},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                self._err(f"topic search returned {resp.status_code}")
                return []
            hits = resp.json().get("hits", [])
            self._log(f"Topic '{topic}' returned {len(hits)} results")
            return hits
        except Exception as exc:
            self._err(f"topic search error: {exc}")
            return []

    def _fetch_item(self, object_id: str) -> Optional[Dict]:
        """Fetch a full item (with comment count) by objectID."""
        try:
            resp = requests.get(
                HN_ITEM_URL.format(id=object_id),
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            self._err(f"item fetch error: {exc}")
        return None

    # ── Format helpers ────────────────────────────────────────────────

    def _stories_to_text(self, hits: List[Dict]) -> str:
        lines = []
        for i, hit in enumerate(hits, 1):
            title = hit.get("title") or "Untitled"
            url = hit.get("url") or "(no URL)"
            points = hit.get("points") or 0
            comments = hit.get("num_comments") or 0
            lines.append(f"{i}. {title} ({points} pts, {comments} comments) — {url}")
        return "\n".join(lines)

    def _is_exit(self, text: str) -> bool:
        lowered = (text or "").lower().strip()
        return any(word in lowered for word in EXIT_WORDS)

    def _parse_story_number(self, text: str) -> Optional[int]:
        """Return 0-based index if user mentions story 1-10, else None."""
        lowered = (text or "").lower()
        word_map = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        for word, num in word_map.items():
            if word in lowered:
                return num - 1
        for n in range(10, 0, -1):
            if str(n) in lowered:
                return n - 1
        return None

    def _detect_topic_request(self, text: str) -> Optional[str]:
        """If user asks to search a topic, extract it via simple heuristics."""
        lowered = (text or "").lower()
        for hint in TOPIC_HINT_WORDS:
            if hint in lowered:
                # Everything after the hint keyword is the topic
                idx = lowered.find(hint) + len(hint)
                topic = text[idx:].strip().strip("?.,")
                if topic:
                    return topic
        return None

    # ── Core flows ────────────────────────────────────────────────────

    async def _deliver_digest(self, count: int = DEFAULT_STORY_COUNT):
        """Fetch and speak the front-page digest."""
        await self.capability_worker.speak("Fetching today's top Hacker News stories.")
        hits = self._fetch_front_page(count)
        if not hits:
            await self.capability_worker.speak(
                "I couldn't reach Hacker News right now. Please try again in a moment."
            )
            return False

        self.stories = hits
        stories_text = self._stories_to_text(hits)

        try:
            summary = self.capability_worker.text_to_text_response(
                DIGEST_PROMPT.format(n=len(hits), stories=stories_text)
            )
        except Exception as exc:
            self._err(f"LLM digest error: {exc}")
            # Graceful fallback — read raw titles
            summary = "Here are today's top stories: " + "; ".join(
                h.get("title", "Untitled") for h in hits[:3]
            )

        await self.capability_worker.speak(summary)
        return True

    async def _expand_story(self, index: int):
        """Speak an expanded 2-sentence take on a story."""
        if index < 0 or index >= len(self.stories):
            await self.capability_worker.speak("I don't have that story number.")
            return

        hit = self.stories[index]
        title = hit.get("title") or "Untitled"
        url = hit.get("url") or ""
        points = hit.get("points") or 0
        num_comments = hit.get("num_comments") or 0
        text = hit.get("story_text") or ""

        # Optionally enrich with full item for text field
        if not text and hit.get("objectID"):
            item = self._fetch_item(hit["objectID"])
            if item:
                text = item.get("text") or ""

        try:
            detail = self.capability_worker.text_to_text_response(
                EXPAND_PROMPT.format(
                    title=title, url=url,
                    points=points, num_comments=num_comments, text=text
                )
            )
        except Exception as exc:
            self._err(f"LLM expand error: {exc}")
            detail = f"{title}. It has {points} points and {num_comments} comments on Hacker News."

        await self.capability_worker.speak(detail)

    async def _deliver_topic_search(self, topic: str):
        """Search HN for a topic and give a spoken summary."""
        await self.capability_worker.speak(f"Searching Hacker News for {topic}.")
        hits = self._fetch_topic(topic)
        if not hits:
            await self.capability_worker.speak(
                f"I couldn't find any stories about {topic} right now."
            )
            return

        stories_text = self._stories_to_text(hits)
        try:
            summary = self.capability_worker.text_to_text_response(
                TOPIC_PROMPT.format(topic=topic, stories=stories_text)
            )
        except Exception as exc:
            self._err(f"LLM topic summary error: {exc}")
            summary = f"Found {len(hits)} results for {topic} on Hacker News."

        await self.capability_worker.speak(summary)

    # ── Main run loop ─────────────────────────────────────────────────

    async def run(self):
        try:
            # Check for an inline topic in the trigger phrase
            initial_topic = None
            if self.initial_request:
                initial_topic = self._detect_topic_request(self.initial_request)

            if initial_topic:
                # User said something like "HN digest about AI" → topic search
                await self._deliver_topic_search(initial_topic)
            else:
                ok = await self._deliver_digest()
                if not ok:
                    return  # API was unreachable; resume_normal_flow in finally

            next_prompt = "Say a number to hear more about that story, search a topic, or say done."
            max_turns = 8
            for _ in range(max_turns):
                user_input = await self.capability_worker.run_io_loop(next_prompt)

                if not user_input or not user_input.strip():
                    next_prompt = "Say a number, a topic, or done."
                    continue

                if self._is_exit(user_input):
                    await self.capability_worker.speak("Catch you next time.")
                    break

                # Check for "more stories" intent
                lowered = user_input.lower()
                if any(w in lowered for w in MORE_WORDS) and "about" not in lowered:
                    await self._deliver_digest(MAX_STORY_COUNT)
                    next_prompt = "Say a number for details, a topic to search, or done."
                    continue

                # Check for topic search
                topic = self._detect_topic_request(user_input)
                if topic:
                    await self._deliver_topic_search(topic)
                    next_prompt = "Want to dig deeper, search another topic, or say done?"
                    continue

                # Check for story number
                idx = self._parse_story_number(user_input)
                if idx is not None:
                    await self._expand_story(idx)
                    next_prompt = "Another story, a topic search, or done?"
                    continue

                # Fallback - treat the whole utterance as a topic search
                await self._deliver_topic_search(user_input.strip())
                next_prompt = "Another topic, a story number, or done?"

        except Exception as exc:
            self._err(f"Unexpected error in run(): {exc}")
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Something went wrong with the HN digest. Sorry about that."
                )

        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()
