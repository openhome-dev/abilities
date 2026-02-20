import json
import os

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# HACKER NEWS READER
# Voice-driven Hacker News browser. Hear top stories, drill into any story
# for a summary, or hear what the comments are saying. All by voice.
# Uses the official HN API — no keys, no auth, completely free.
# =============================================================================

HN_TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "bye", "goodbye",
    "leave", "cancel", "no thanks", "i'm good", "im good",
}

MAX_TURNS = 15
STORIES_PER_PAGE = 5
REQUEST_TIMEOUT = 10

HEADLINES_PROMPT = (
    "You are a tech news anchor reading headlines to a listener. "
    "Read these Hacker News stories as a brief spoken segment. "
    "Number each one. Keep each to one sentence max. "
    "Be conversational, not robotic.\n\n"
    "Stories:\n{stories}"
)

STORY_SUMMARY_PROMPT = (
    "You are a tech news reporter. Summarize this Hacker News story "
    "in 2-3 spoken sentences. Include what it's about and why people "
    "care. Be concise and conversational.\n\n"
    "Title: {title}\n"
    "URL: {url}\n"
    "Points: {score}\n"
    "Comments: {comments}\n"
    "Posted by: {by}"
)

COMMENTS_PROMPT = (
    "You are a tech news reporter summarizing the discussion on a "
    "Hacker News post. Summarize the top comments into a 3-4 sentence "
    "spoken overview. Capture the main opinions and any disagreements. "
    "Be conversational.\n\n"
    "Story: {title}\n"
    "Comments:\n{comments}"
)

EXTRACT_NUMBER_PROMPT = (
    "The user was asked to pick a story number and said: '{raw}'\n"
    "Extract the number they chose as a single digit. "
    "Handle words like 'the second one' (return 2), 'number 3' (return 3), "
    "'third' (return 3), 'first' (return 1), etc. "
    "Return ONLY the number, nothing else. If unclear, return 0."
)


def fetch_top_story_ids(count=30):
    """Fetch top story IDs from HN API."""
    try:
        resp = requests.get(HN_TOP_URL, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()[:count]
    except Exception:
        pass
    return []


def fetch_item(item_id):
    """Fetch a single HN item (story or comment)."""
    try:
        resp = requests.get(
            HN_ITEM_URL.format(id=item_id), timeout=REQUEST_TIMEOUT
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_top_comments(story, max_comments=8):
    """Fetch the top-level comments for a story."""
    kid_ids = story.get("kids", [])[:max_comments]
    comments = []
    for kid_id in kid_ids:
        item = fetch_item(kid_id)
        if item and item.get("text") and not item.get("deleted") and not item.get("dead"):
            # Strip HTML tags for voice readback
            text = item["text"]
            for tag in ["<p>", "</p>", "<i>", "</i>", "<b>", "</b>", "<pre>", "</pre>", "<code>", "</code>"]:
                text = text.replace(tag, " ")
            # Remove href links but keep link text
            import re
            text = re.sub(r'<a\s+href="[^"]*"[^>]*>', '', text)
            text = text.replace("</a>", "")
            text = re.sub(r'<[^>]+>', '', text)
            text = text.strip()
            if text:
                author = item.get("by", "someone")
                comments.append(f"{author}: {text}")
    return comments


class HackerNewsReaderCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

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
        self.stories = []
        self.story_data = {}
        self.current_page = 0
        self.worker.session_tasks.create(self.run())

    def _log(self, level, msg):
        try:
            handler = self.worker.editor_logging_handler
            getattr(handler, level, handler.info)(f"[HackerNews] {msg}")
        except Exception:
            pass

    def detect_command(self, text):
        lower = text.lower().strip()

        if any(w in lower for w in EXIT_WORDS):
            return "exit"
        if any(w in lower for w in ("next", "more stories", "more", "next page")):
            return "next"
        if any(w in lower for w in ("back", "previous", "go back", "last page")):
            return "previous"
        if any(w in lower for w in ("comment", "discussion", "what are people saying", "reactions")):
            return "comments"
        if any(w in lower for w in ("tell me more", "details", "about", "summarize", "what's that")):
            return "detail"
        if any(w in lower for w in ("top", "headlines", "front page", "refresh", "start over")):
            return "headlines"

        # Check if they just said a number
        for i in range(1, STORIES_PER_PAGE + 1):
            num_words = {
                1: ("one", "first"), 2: ("two", "second"),
                3: ("three", "third"), 4: ("four", "fourth"),
                5: ("five", "fifth"),
            }
            if str(i) in lower:
                return f"pick:{i}"
            for word in num_words.get(i, ()):
                if word in lower:
                    return f"pick:{i}"

        return "unknown"

    def get_page_stories(self):
        """Get stories for the current page."""
        start = self.current_page * STORIES_PER_PAGE
        end = start + STORIES_PER_PAGE
        page_ids = self.stories[start:end]

        results = []
        for story_id in page_ids:
            if story_id in self.story_data:
                results.append(self.story_data[story_id])
            else:
                item = fetch_item(story_id)
                if item:
                    self.story_data[story_id] = item
                    results.append(item)
        return results

    async def speak_headlines(self, page_stories):
        """Speak the current page of headlines."""
        if not page_stories:
            await self.capability_worker.speak(
                "Couldn't load any stories right now. Try again later."
            )
            return

        story_lines = []
        for i, story in enumerate(page_stories, 1):
            title = story.get("title", "Untitled")
            score = story.get("score", 0)
            comments = story.get("descendants", 0)
            story_lines.append(
                f"{i}. {title} ({score} points, {comments} comments)"
            )

        try:
            headlines = self.capability_worker.text_to_text_response(
                HEADLINES_PROMPT.format(stories="\n".join(story_lines))
            )
            await self.capability_worker.speak(headlines)
        except Exception as e:
            self._log("error", f"Headlines LLM error: {e}")
            # Fallback: just read titles
            for line in story_lines:
                await self.capability_worker.speak(line)

    async def speak_story_detail(self, story):
        """Summarize a single story."""
        try:
            summary = self.capability_worker.text_to_text_response(
                STORY_SUMMARY_PROMPT.format(
                    title=story.get("title", "Untitled"),
                    url=story.get("url", "no link"),
                    score=story.get("score", 0),
                    comments=story.get("descendants", 0),
                    by=story.get("by", "unknown"),
                )
            )
            await self.capability_worker.speak(summary)
        except Exception as e:
            self._log("error", f"Story detail error: {e}")
            await self.capability_worker.speak(
                f"{story.get('title', 'Untitled')}. "
                f"{story.get('score', 0)} points and "
                f"{story.get('descendants', 0)} comments."
            )

    async def speak_comments(self, story):
        """Summarize the comment discussion."""
        await self.capability_worker.speak("Let me check what people are saying.")

        comments = fetch_top_comments(story)
        if not comments:
            await self.capability_worker.speak(
                "No comments on this one yet."
            )
            return

        try:
            summary = self.capability_worker.text_to_text_response(
                COMMENTS_PROMPT.format(
                    title=story.get("title", "Untitled"),
                    comments="\n\n".join(comments[:6]),
                )
            )
            await self.capability_worker.speak(summary)
        except Exception as e:
            self._log("error", f"Comments summary error: {e}")
            await self.capability_worker.speak(
                f"There are {len(comments)} comments but I had "
                "trouble summarizing them."
            )

    async def pick_story(self, text, page_stories):
        """Extract which story the user wants and return it."""
        command = self.detect_command(text)

        # Direct number pick from detect_command
        if command.startswith("pick:"):
            num = int(command.split(":")[1])
            if 1 <= num <= len(page_stories):
                return page_stories[num - 1]

        # LLM fallback for natural language picks
        try:
            num_str = self.capability_worker.text_to_text_response(
                EXTRACT_NUMBER_PROMPT.format(raw=text)
            )
            num = int(num_str.strip())
            if 1 <= num <= len(page_stories):
                return page_stories[num - 1]
        except (ValueError, Exception):
            pass

        return None

    async def run(self):
        try:
            await self.capability_worker.speak(
                "Pulling up Hacker News for you."
            )

            self.stories = fetch_top_story_ids(30)
            if not self.stories:
                await self.capability_worker.speak(
                    "Couldn't reach Hacker News right now. Try again later."
                )
                self.capability_worker.resume_normal_flow()
                return

            self.current_page = 0
            page_stories = self.get_page_stories()
            await self.speak_headlines(page_stories)

            selected_story = None

            for _ in range(MAX_TURNS):
                prompt = "Pick a number for details, say comments, next for more stories, or done to exit."
                user_input = await self.capability_worker.run_io_loop(prompt)

                if not user_input or not user_input.strip():
                    continue

                command = self.detect_command(user_input)

                if command == "exit":
                    await self.capability_worker.speak("Enjoy your day.")
                    break

                elif command == "next":
                    max_page = (len(self.stories) - 1) // STORIES_PER_PAGE
                    if self.current_page < max_page:
                        self.current_page += 1
                        page_stories = self.get_page_stories()
                        await self.speak_headlines(page_stories)
                        selected_story = None
                    else:
                        await self.capability_worker.speak(
                            "That's all the stories I have. Say start over to go back to the top."
                        )

                elif command == "previous":
                    if self.current_page > 0:
                        self.current_page -= 1
                        page_stories = self.get_page_stories()
                        await self.speak_headlines(page_stories)
                        selected_story = None
                    else:
                        await self.capability_worker.speak(
                            "You're already at the top stories."
                        )

                elif command == "headlines":
                    self.current_page = 0
                    self.stories = fetch_top_story_ids(30)
                    page_stories = self.get_page_stories()
                    await self.speak_headlines(page_stories)
                    selected_story = None

                elif command == "comments":
                    if selected_story:
                        await self.speak_comments(selected_story)
                    else:
                        # Try to extract a number from the input
                        story = await self.pick_story(user_input, page_stories)
                        if story:
                            selected_story = story
                            await self.speak_comments(story)
                        else:
                            await self.capability_worker.speak(
                                "Which story? Pick a number first."
                            )

                elif command == "detail" or command.startswith("pick:"):
                    story = await self.pick_story(user_input, page_stories)
                    if story:
                        selected_story = story
                        await self.speak_story_detail(story)
                    else:
                        await self.capability_worker.speak(
                            "Which story number?"
                        )

                else:
                    # Maybe they just said a number or story reference
                    story = await self.pick_story(user_input, page_stories)
                    if story:
                        selected_story = story
                        await self.speak_story_detail(story)
                    else:
                        await self.capability_worker.speak(
                            "Pick a story number, say next for more, "
                            "or done to exit."
                        )

        except Exception as e:
            self._log("error", f"Hacker News reader error: {e}")
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Try again later."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()
