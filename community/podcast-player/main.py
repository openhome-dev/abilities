import asyncio
import json
import re
import random
from typing import Optional

import httpx
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

BASE_URL = "https://listen-api.listennotes.com/api/v2"
TRENDING_POOL_SIZE = 10
TRENDING_SPOKEN_OPTIONS = 3

EXIT_WORDS = {
    "stop", "stop it", "stop the podcast", "stop playing",
    "exit", "exit podcast", "quit", "quit podcast",
    "cancel", "cancel podcast",
    "bye", "goodbye",
    "that's all", "that's all thanks", "that's enough",
    "i'm done", "im done", "all done", "we're done",
    "close podcast", "close it", "shut it down",
}

CONTINUE_PROMPTS = [
    "Want me to find you something else, or are you good for now?",
    "Shall I look for another episode, or are we done?",
    "Want to keep listening to something else, or should I stop here?",
    "I can find you another one if you like, or just say stop.",
]

EXIT_MESSAGES = [
    "Alright, happy listening. Catch you next time.",
    "Hope you enjoyed that one. Talk soon.",
    "That's it from me. Enjoy the rest of your day.",
    "Closing out. Hope it was a good listen.",
]

RANDOM_FILLERS = [
    "Give me just a moment, I will go through what is available and find you something good to listen to.",
    "Let me take a look at what is out there and find you a solid pick, just one second.",
    "One moment, I am going through the catalogue and will grab something worth listening to.",
    "Give me a second, I will look through and find a good episode for you right now.",
]

TRENDING_FILLERS = [
    "Let me check what people have been listening to lately and pull up the top shows, one moment.",
    "Give me just a second, I am pulling up what is trending right now and will have some picks for you.",
    "One moment, let me check what is popular right now and grab some options for you.",
    "Just a second, I am looking at the top shows right now and will have a few picks ready.",
]

SEARCH_FILLERS = [
    "Let me search for that right now and see what comes up, just one moment.",
    "Give me a second, I am searching for that and will have something for you shortly.",
    "One moment, let me look that up for you and see what is available.",
    "Just a second, searching for that right now and will be right back with results.",
]

EPISODE_FILLERS = [
    "Let me search for that episode right now, give me just a moment.",
    "Give me a second, I am looking through the episodes and will find the right one for you.",
    "One moment, I am searching for that specific episode and will have it for you shortly.",
    "Just a second, let me look that episode up right now and see what I can find.",
]


class ListennotesPodcastCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _log(self, msg: str):
        self.worker.editor_logging_handler.info(msg)

    def _log_err(self, msg: str):
        self.worker.editor_logging_handler.error(msg)

    def _headers(self, api_key: str):
        return {"X-ListenAPI-Key": api_key}

    def _normalize_text(self, text: str) -> str:
        normalized = (text or "").lower().strip()
        normalized = normalized.replace("'", "")
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _is_exit_phrase(self, user_input: str) -> bool:
        normalized = self._normalize_text(user_input)
        return normalized in {
            self._normalize_text(word) for word in EXIT_WORDS
        }

    def _is_explicit_random(self, user_input: str) -> bool:
        normalized = self._normalize_text(user_input)
        return any(word in normalized for word in {
            "random", "surprise", "anything", "whatever", "just pick",
            "you pick", "your pick", "pick for me", "dont care", "don t care",
            "up to you", "any podcast", "any episode",
        })

    def _podcast_title(self, podcast_dict: dict) -> str:
        return (
            podcast_dict.get("title_original")
            or podcast_dict.get("title")
            or "this podcast"
        )

    def _clean_json(self, raw: str) -> dict:
        """Strip markdown fences, whitespace, and parse JSON."""
        cleaned = raw.strip()
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()
        return json.loads(cleaned)

    def _recent_conversation_context(self, limit: int = 8) -> str:
        """Return compact recent history for resolving follow-up references."""
        try:
            history = self.capability_worker.get_full_message_history()
        except Exception as e:
            self._log_err(f"[History] Could not load message history: {e}")
            return ""

        if not history:
            return ""

        if isinstance(history, str):
            return history[-1800:]

        if not isinstance(history, list):
            return str(history)[-1800:]

        lines = []
        for item in history[-limit:]:
            if isinstance(item, dict):
                role = (
                    item.get("role")
                    or item.get("sender")
                    or item.get("type")
                    or "message"
                )
                content = (
                    item.get("content")
                    or item.get("text")
                    or item.get("message")
                    or item.get("transcript")
                    or ""
                )
                if isinstance(content, list):
                    content = " ".join(str(part) for part in content)
                elif isinstance(content, dict):
                    content = json.dumps(content)
                line = f"{role}: {content}".strip()
            else:
                line = str(item).strip()

            if line:
                lines.append(line)

        return "\n".join(lines)[-1800:]

    def _naturalize_for_voice(self, text: str) -> str:
        prompt = (
            "You are doing a voice naturalness pass for an OpenHome podcast "
            "player. Rewrite the following into one short, natural spoken "
            "line for a voice assistant. Keep it conversational and concise. "
            "Do not use numbering, bullets, markdown, stage directions, or "
            "extra commentary. Preserve podcast names, episode titles, guest "
            "names, and topics exactly when they appear.\n\n"
            f"{text}"
        )
        try:
            response = self.capability_worker.text_to_text_response(prompt)
            return (response or text).strip()
        except Exception as e:
            self._log_err(f"[Voice] Naturalness pass failed: {e}")
            return text

    def _summarize_for_voice(self, text: str) -> str:
        prompt = (
            "You are doing a voice naturalness pass for an OpenHome podcast "
            "player. Rewrite the following into a short, natural spoken "
            "summary for a voice assistant. Keep it under 2 sentences. "
            "Do not use numbering, bullets, markdown, stage directions, or "
            "extra commentary. Preserve podcast names, episode titles, guest "
            "names, and topics exactly when they appear.\n\n"
            f"{text}"
        )
        try:
            response = self.capability_worker.text_to_text_response(prompt)
            return (response or text).strip()
        except Exception as e:
            self._log_err(f"[Voice] Summary naturalness pass failed: {e}")
            return text

    async def _speak_natural(self, text: str):
        await self.capability_worker.speak(self._naturalize_for_voice(text))

    async def _speak_exit(self):
        await self.capability_worker.speak(random.choice(EXIT_MESSAGES))

    def _summarize_error(self, error: Exception) -> str:
        try:
            msg = self.capability_worker.text_to_text_response(
                f"Summarize this error into one short friendly spoken sentence for a voice assistant user. "
                f"No technical details, no URLs, no markdown, no stack traces. "
                f"Just say what went wrong in plain conversational English.\n\nError: {str(error)}"
            )
            return (msg or "").strip() or "Something went wrong."
        except Exception:
            return "Something went wrong."

    # -------------------------------------------------------------------------
    # Intent Classification
    # -------------------------------------------------------------------------

    def classify_intent(self, user_input: str) -> dict:
        """
        Returns structured JSON:
        {
            "intent": "browse_trending" | "play_random" | "play_podcast" | "play_episode" | "exit",
            "podcast": "podcast name or null",
            "guest": "guest name or null",
            "topic": "topic or null"
        }
        """
        history_context = self._recent_conversation_context()
        history_block = (
            f"RECENT CONVERSATION CONTEXT:\n{history_context}\n\n"
            if history_context
            else ""
        )

        prompt = (
            "You are an intent classifier for a voice-controlled podcast player. "
            "Input comes from speech-to-text — expect filler words, misspellings, "
            "and sentence fragments. Extract meaning, not exact words. "
            "Use recent conversation context to resolve follow-up references.\n\n"

            f"{history_block}"

            "INTENT DEFINITIONS:\n"
            "- browse_trending: user EXPLICITLY asks for trending, popular, top, or "
            "what's hot podcasts — must use words like 'trending', 'popular', 'top podcasts', "
            "'what's hot', 'what's popular', 'list some', 'show me some'. "
            "Do NOT use this for vague requests like 'play a podcast' or 'find me a podcast'.\n"
            "- play_random: user EXPLICITLY asks for something random or a surprise — "
            "must use words like 'random', 'surprise me', 'anything', 'whatever', "
            "'you pick', 'just pick something'. Do NOT use this for vague requests "
            "like 'play a podcast' or 'find me something'.\n"
            "- play_latest: user names a podcast AND explicitly asks for the latest, "
            "newest, most recent, or new episode — words like 'latest', 'newest', "
            "'most recent', 'new episode', 'last episode', 'recent episode'.\n"
            "- play_podcast: user names a podcast but NOT a specific episode, "
            "guest, topic, or latest request.\n"
            "- play_episode: user names a podcast AND at least one of: "
            "a guest name, a topic, or an episode title\n"
            "- exit: user explicitly wants to stop or leave the podcast player — "
            "must use clear stop/exit words like 'stop', 'quit', 'exit', 'bye', 'close', "
            "'I am done', 'that is all', 'shut it down'. "
            "Do NOT use exit for: 'no thanks', 'nah', 'not that one', 'something else', "
            "'never mind' when used mid-search, or any response that is still about finding a podcast.\n\n"

            "RESPONSE FORMAT — return ONLY this JSON structure, nothing else:\n"
            "{\n"
            '  "intent": "browse_trending | play_random | play_latest | play_podcast | play_episode | exit",\n'
            '  "podcast": "extracted podcast name or null",\n'
            '  "guest": "extracted guest name or null",\n'
            '  "topic": "extracted topic or null"\n'
            "}\n\n"

            "RULES:\n"
            "1. No markdown fences, no explanation, no extra text. JSON only.\n"
            "2. If the user mentions a podcast name + a person or topic, "
            "that is play_episode (they want a specific episode).\n"
            "3a. If the user names a podcast AND uses words like 'latest', 'newest', "
            "'most recent', 'new episode', 'last episode' — that is play_latest.\n"
            "3b. If the user only mentions a podcast name with no guest, topic, or latest request, "
            "that is play_podcast.\n"
            "4. If the user says random, surprise me, or anything random — "
            "that is play_random. All fields null.\n"
            "5. If the user asks for a general podcast with no specific show and no explicit random request, "
            "that is browse_trending. All fields null.\n"
            "6. Only use exit if the user uses a clear stop/leave word: "
            "'stop', 'quit', 'exit', 'bye', 'goodbye', 'close', 'I am done', "
            "'that is all', 'shut it down'. "
            "Words like 'nah', 'no', 'not that', 'something else', 'never mind' "
            "mid-search are NOT exit — the user is still looking for a podcast.\n"
            "7. Strip filler words (um, uh, like) from extracted values.\n"
            "8. If the user says things like 'the one with Peter', "
            "'that episode', or 'the second one', use recent context to infer "
            "the podcast and guest/topic/title when possible.\n"
            "9. If recent context says the assistant listed latest episodes "
            "from a podcast, and the user asks for one of those episodes, "
            "return play_episode with that podcast name and the referenced "
            "guest/topic/title.\n"
            "10. Do NOT invent intents beyond the six listed.\n\n"

            "EXAMPLES:\n"
            'User: "tell me a podcast" -> '
            '{"intent": "play_random", "podcast": null, '
            '"guest": null, "topic": null}\n'
            'User: "play a podcast" -> '
            '{"intent": "play_random", "podcast": null, '
            '"guest": null, "topic": null}\n'
            'User: "show me trending podcasts" -> '
            '{"intent": "browse_trending", "podcast": null, '
            '"guest": null, "topic": null}\n'
            'User: "what\'s popular right now" -> '
            '{"intent": "browse_trending", "podcast": null, '
            '"guest": null, "topic": null}\n'
            'User: "play lex fridman" -> '
            '{"intent": "play_podcast", "podcast": "Lex Fridman", '
            '"guest": null, "topic": null}\n'
            'User: "play lex fridman with jensen huang about nvidia" -> '
            '{"intent": "play_episode", "podcast": "Lex Fridman", '
            '"guest": "Jensen Huang", "topic": "NVIDIA"}\n'
            'User: "play joe rogan with elon musk" -> '
            '{"intent": "play_episode", "podcast": "Joe Rogan", '
            '"guest": "Elon Musk", "topic": null}\n'
            'User: "lex fridman episode on AI safety" -> '
            '{"intent": "play_episode", "podcast": "Lex Fridman", '
            '"guest": null, "topic": "AI safety"}\n'
            'User: "surprise me" -> '
            '{"intent": "play_random", "podcast": null, '
            '"guest": null, "topic": null}\n'
            'User: "nah I\'m done" -> '
            '{"intent": "exit", "podcast": null, '
            '"guest": null, "topic": null}\n'
            'User: "play huberman lab" -> '
            '{"intent": "play_podcast", "podcast": "Huberman Lab", '
            '"guest": null, "topic": null}\n'
            'User: "play the latest episode from lex fridman" -> '
            '{"intent": "play_latest", "podcast": "Lex Fridman", '
            '"guest": null, "topic": null}\n'
            'User: "play the newest huberman lab episode" -> '
            '{"intent": "play_latest", "podcast": "Huberman Lab", '
            '"guest": null, "topic": null}\n'
            'User: "play the most recent joe rogan" -> '
            '{"intent": "play_latest", "podcast": "Joe Rogan", '
            '"guest": null, "topic": null}\n\n'
            'Context: assistant listed latest episodes from Lex Fridman Podcast, '
            'including Peter Steinberger with OpenClaw.\n'
            'User: "play the one with peter stienburger" -> '
            '{"intent": "play_episode", "podcast": "Lex Fridman Podcast", '
            '"guest": "Peter Steinberger", "topic": "OpenClaw"}\n\n'

            f'User: "{user_input}"'
        )

        llm_response = self.capability_worker.text_to_text_response(prompt)
        self._log(f"[Intent] Raw: {llm_response}")

        try:
            result = self._clean_json(llm_response)
            self._log(f"[Intent] Parsed: {json.dumps(result)}")
            return result
        except Exception as e:
            self._log_err(f"[Intent] JSON parse failed: {e}")
            return {
                "intent": "unknown",
                "podcast": None,
                "guest": None,
                "topic": None,
            }

    # -------------------------------------------------------------------------
    # LLM-Based Selection
    # -------------------------------------------------------------------------

    def select_from_options(self, user_input: str, options: list[str]) -> dict:
        """
        Returns:
            {"action": "play", "index": <0-based>}
            {"action": "another"}
            {"action": "exit"}
        """
        numbered = "\n".join(
            [f"{i + 1}. {opt}" for i, opt in enumerate(options)]
        )
        history_context = self._recent_conversation_context()
        history_block = (
            f"RECENT CONVERSATION CONTEXT:\n{history_context}\n\n"
            if history_context
            else ""
        )

        prompt = (
            "You are helping a voice assistant user pick from a list. "
            "Input comes from speech-to-text and may be imprecise. "
            "Use recent context to resolve references like 'that one', "
            "'the one with Peter', or 'the second one'.\n\n"

            f"{history_block}"

            f"OPTIONS:\n{numbered}\n\n"
            f'USER SAID: "{user_input}"\n\n'

            "RESPONSE FORMAT — return ONLY this JSON, nothing else:\n"
            '{"action": "play | another | exit", "index": <1-based number or null>}\n\n'

            "RULES:\n"
            "1. No markdown fences, no explanation. JSON only.\n"
            "2. If user picks an option: "
            '{"action": "play", "index": <1-based>}\n'
            "3. If user wants to search again or something different: "
            '{"action": "another", "index": null}\n'
            "4. If user wants to stop or exit: "
            '{"action": "exit", "index": null}\n'
            "5. Match by meaning, not exact words. "
            '"The one with Jensen" matches an option mentioning Jensen Huang.\n'
            "6. Use recent assistant messages to understand what options were "
            "just read aloud, but choose only from OPTIONS.\n"
            "7. If unsure, pick the closest match.\n\n"

            "EXAMPLES:\n"
            "Given options: 1. Interview with Jensen Huang  "
            "2. Vikings History  3. AI Revolution\n"
            'User: "the one with jensen" -> {"action": "play", "index": 1}\n'
            "Given options: 1. Peter Steinberger with OpenClaw  "
            "2. Jensen Huang on NVIDIA  3. Vikings and Warriors\n"
            'User: "play the one with peter stienburger" -> {"action": "play", "index": 1}\n'
            'User: "something else" -> {"action": "another", "index": null}\n'
            'User: "nah done" -> {"action": "exit", "index": null}\n'
        )

        llm_response = self.capability_worker.text_to_text_response(prompt)
        self._log(f"[Select] Raw: {llm_response}")

        try:
            result = self._clean_json(llm_response)
            if result.get("action") == "play" and result.get("index"):
                result["index"] = result["index"] - 1
            self._log(f"[Select] Parsed: {json.dumps(result)}")
            return result
        except Exception as e:
            self._log_err(f"[Select] JSON parse failed: {e}")
            return {"action": "another", "index": None}

    # -------------------------------------------------------------------------
    # API Calls (all wrapped in try/except, logged)
    # -------------------------------------------------------------------------

    def fetch_best_podcasts(self, api_key: str) -> list:
        """GET /best_podcasts — curated popular podcasts."""
        url = f"{BASE_URL}/best_podcasts"
        params = {"page": random.randint(1, 5)}
        try:
            self._log("[API] Fetching best podcasts")
            response = requests.get(
                url, headers=self._headers(api_key), params=params, timeout=10
            )
            self._log(f"[API] best_podcasts status: {response.status_code}")
            response.raise_for_status()
            podcasts = response.json().get("podcasts", [])
            self._log(f"[API] best_podcasts returned {len(podcasts)} results")
            return podcasts
        except Exception as e:
            self._log_err(f"[API] best_podcasts error: {e}")
            raise

    def fetch_trending_podcasts(self, api_key: str, minimum: int = 10) -> list:
        """Use Listen Notes best_podcasts as the closest trending source."""
        podcasts = self.fetch_best_podcasts(api_key)
        if len(podcasts) >= minimum:
            return podcasts

        extra = self.fetch_best_podcasts(api_key)
        combined = []
        seen_ids = set()
        for podcast in podcasts + extra:
            podcast_id = podcast.get("id")
            if not podcast_id or podcast_id in seen_ids:
                continue
            seen_ids.add(podcast_id)
            combined.append(podcast)
        return combined

    def search_podcasts(self, query: str, api_key: str) -> list:
        """GET /search?type=podcast"""
        url = f"{BASE_URL}/search"
        params = {"q": query, "type": "podcast", "page_size": 5}
        try:
            self._log(f"[API] Searching podcasts: '{query}'")
            response = requests.get(
                url, headers=self._headers(api_key), params=params, timeout=10
            )
            self._log(f"[API] search_podcasts status: {response.status_code}")
            response.raise_for_status()
            results = response.json().get("results", [])
            self._log(f"[API] search_podcasts returned {len(results)} results")
            return results
        except Exception as e:
            self._log_err(f"[API] search_podcasts error: {e}")
            raise

    def search_episodes(
        self, query: str, api_key: str, podcast_id: str = None
    ) -> list:
        """GET /search?type=episode&sort_by_date=1 (newest first).
        If podcast_id provided, scopes to that podcast via ocid.
        """
        url = f"{BASE_URL}/search"
        params = {
            "q": query,
            "type": "episode",
            "sort_by_date": 1,
            "page_size": 5,
        }
        if podcast_id:
            params["ocid"] = podcast_id
        try:
            self._log(
                f"[API] Searching episodes: '{query}', "
                f"podcast_id={podcast_id}"
            )
            response = requests.get(
                url, headers=self._headers(api_key), params=params, timeout=10
            )
            self._log(
                f"[API] search_episodes status: {response.status_code}"
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            self._log(
                f"[API] search_episodes returned {len(results)} results"
            )
            return results
        except Exception as e:
            self._log_err(f"[API] search_episodes error: {e}")
            raise

    def get_podcast_episodes(self, podcast_id: str, api_key: str):
        """GET /podcasts/{id} — returns (episodes, full_podcast_data)."""
        url = f"{BASE_URL}/podcasts/{podcast_id}"
        params = {"sort": "recent_first"}
        try:
            self._log(f"[API] Fetching episodes for podcast: {podcast_id}")
            response = requests.get(
                url, headers=self._headers(api_key), params=params, timeout=10
            )
            self._log(
                f"[API] get_podcast_episodes status: {response.status_code}"
            )
            response.raise_for_status()
            data = response.json()
            episodes = data.get("episodes", [])
            self._log(
                f"[API] get_podcast_episodes returned {len(episodes)} episodes"
            )
            return episodes, data
        except Exception as e:
            self._log_err(f"[API] get_podcast_episodes error: {e}")
            raise

    def _latest_playable_episode(self, podcast: dict, api_key: str) -> Optional[dict]:
        """Return the latest episode with audio for a podcast."""
        podcast_id = podcast.get("id")
        if not podcast_id:
            return None

        episodes, podcast_data = self.get_podcast_episodes(podcast_id, api_key)
        if not episodes:
            return None

        podcast_info = {
            "title": podcast_data.get("title", self._podcast_title(podcast)),
            "title_original": podcast_data.get(
                "title_original", self._podcast_title(podcast)
            ),
        }

        for episode in episodes:
            if "podcast" not in episode:
                episode["podcast"] = podcast_info
            if episode.get("audio"):
                return episode

        return None

    async def _build_trending_episode_options(
        self, podcasts: list, api_key: str, limit: int = 5
    ) -> list:
        """Get latest playable episodes from trending podcasts in parallel."""
        candidates = podcasts[:limit * 2]
        results = await asyncio.gather(
            *[asyncio.to_thread(self._latest_playable_episode, p, api_key) for p in candidates]
        )
        return [ep for ep in results if ep][:limit]

    # -------------------------------------------------------------------------
    # Playback
    # -------------------------------------------------------------------------

    async def stream_episode_audio(self, stream_response):
        try:
            await self.capability_worker.stream_init()
            self._log("[Stream] Initialized")

            async for chunk in stream_response.aiter_bytes(chunk_size=25 * 1024):
                if not chunk:
                    continue

                if self.worker.music_mode_stop_event.is_set():
                    self._log("[Stream] Stop event — ending playback")
                    await self.capability_worker.stream_end()
                    return

                while self.worker.music_mode_pause_event.is_set():
                    await self.worker.session_tasks.sleep(0.1)

                await self.capability_worker.send_audio_data_in_stream(chunk)

            await self.capability_worker.stream_end()
            self._log("[Stream] Finished cleanly")

        except Exception as e:
            self._log_err(f"[Stream] Error: {e}")

    async def play_episode(self, episode: dict, state: dict):
        """Play a podcast episode. Music mode is already ON for the session."""
        state["current_episode"] = episode
        title = episode.get("title") or "this episode"
        podcast = self._podcast_title(episode.get("podcast", {}))
        audio_url = episode.get("audio")

        if not audio_url:
            self._log_err(f"[Play] No audio URL for: {title}")
            await self.capability_worker.speak("Couldn't find playable audio for that episode.")
            return

        self._log(f"[Play] Starting: {title} from {podcast}")
        await self.capability_worker.speak(f"Here's {title} from {podcast}.")

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET", audio_url, follow_redirects=True
                ) as stream_resp:
                    self._log(
                        f"[Play] Stream status: {stream_resp.status_code}"
                    )
                    if stream_resp.status_code == 200:
                        await self.stream_episode_audio(stream_resp)
                    else:
                        self._log_err(
                            f"[Play] Bad status: {stream_resp.status_code}"
                        )
                        await self.capability_worker.speak("Couldn't load that episode. Want to try another?")
        except Exception as e:
            self._log_err(f"[Play] Error: {e}")
            await self.capability_worker.speak(self._summarize_error(e))

    # -------------------------------------------------------------------------
    # Flow Handlers
    # -------------------------------------------------------------------------

    async def _handle_random(self, state: dict) -> str:
        """
        Ask for more specifics before playing. Only plays random if user confirms.
        Returns: "played", "another", "exit"
        """
        await self.capability_worker.speak(
            "Any particular show or topic you have in mind? "
            "Or should I just pick something for you?"
        )
        follow_up = await self.capability_worker.user_response()

        if not follow_up:
            return "another"

        if self._is_exit_phrase(follow_up):
            return "exit"

        intent_data = self.classify_intent(follow_up)
        intent = intent_data.get("intent")

        if intent == "play_podcast":
            return await self._handle_podcast(intent_data, state)
        elif intent == "play_latest":
            return await self._handle_latest(intent_data, state)
        elif intent == "play_episode":
            return await self._handle_episode(intent_data, state)
        elif intent == "browse_trending":
            return await self._handle_browse_trending(state)
        elif intent == "exit":
            return "exit"

        # Only play random if user explicitly asked for it
        if not self._is_explicit_random(follow_up):
            await self.capability_worker.speak(
                "Just let me know the podcast or episode you want and I'll find it for you."
            )
            return "another"

        # User explicitly asked for random — now go fetch
        api_key = state["api_key"]
        await self.capability_worker.speak(random.choice(RANDOM_FILLERS))

        try:
            trending_podcasts = await asyncio.to_thread(
                self.fetch_trending_podcasts, api_key, TRENDING_POOL_SIZE
            )
        except Exception as e:
            await self.capability_worker.speak(self._summarize_error(e))
            return "another"

        if not trending_podcasts:
            await self.capability_worker.speak("Having trouble fetching right now. Want to try again?")
            return "another"

        picks = trending_podcasts[:TRENDING_POOL_SIZE]
        random.shuffle(picks)

        episodes = await asyncio.gather(
            *[asyncio.to_thread(self._latest_playable_episode, p, api_key) for p in picks]
        )
        playable = [ep for ep in episodes if ep]
        if playable:
            await self.play_episode(playable[0], state)
            return "played"

        await self.capability_worker.speak("Couldn't find a playable episode right now. Want to try something specific?")
        return "another"

    async def _handle_browse_trending(self, state: dict) -> str:
        """
        Read out a few trending podcast episodes and let the user choose one.
        Returns: "played", "another", "exit"
        """
        api_key = state["api_key"]

        await self.capability_worker.speak(random.choice(TRENDING_FILLERS))

        try:
            trending_podcasts = await asyncio.to_thread(
                self.fetch_trending_podcasts, api_key, TRENDING_POOL_SIZE
            )
        except Exception as e:
            await self.capability_worker.speak(self._summarize_error(e))
            return "another"

        if not trending_podcasts:
            await self.capability_worker.speak("Having trouble loading right now. Want to try again?")
            return "another"

        trending_episodes = await self._build_trending_episode_options(
            trending_podcasts, api_key, limit=TRENDING_SPOKEN_OPTIONS
        )
        if not trending_episodes:
            await self.capability_worker.speak("Couldn't find trending episodes right now.")
            return "another"

        option_titles = [
            f"{episode.get('title') or 'latest episode'} from "
            f"{self._podcast_title(episode.get('podcast', {}))}"
            for episode in trending_episodes
        ]

        summary = self._summarize_for_voice(
            f"Here are three trending podcast picks: {', '.join(option_titles)}. "
            "Keep it concise and ask which one the user wants to hear."
        )
        await self.capability_worker.speak(summary)

        choice = await self.capability_worker.user_response()
        if not choice:
            return "another"

        pick = self.select_from_options(choice, option_titles)

        if pick.get("action") == "exit":
            return "exit"
        if pick.get("action") == "another":
            return "another"

        idx = pick.get("index", 0)
        if idx < 0 or idx >= len(trending_episodes):
            idx = 0

        await self.play_episode(trending_episodes[idx], state)
        return "played"

    async def _handle_latest(self, intent_data: dict, state: dict) -> str:
        """
        User asked for the latest episode of a named podcast — play it directly.
        Returns: "played", "another", "exit"
        """
        api_key = state["api_key"]
        podcast_name = intent_data.get("podcast")

        if not podcast_name:
            await self.capability_worker.speak("Which podcast do you want the latest episode from?")
            podcast_name = await self.capability_worker.user_response()
            if not podcast_name:
                return "another"

        await self.capability_worker.speak(random.choice(SEARCH_FILLERS))

        try:
            podcasts = await asyncio.to_thread(self.search_podcasts, podcast_name, api_key)
        except Exception as e:
            await self.capability_worker.speak(self._summarize_error(e))
            return "another"

        if not podcasts:
            await self.capability_worker.speak(f"Couldn't find {podcast_name}. Want to try something else?")
            return "another"

        selected_podcast = podcasts[0]
        selected_name = self._podcast_title(selected_podcast)
        state["last_podcast_name"] = selected_name

        try:
            episodes, podcast_data = await asyncio.to_thread(
                self.get_podcast_episodes, selected_podcast["id"], api_key
            )
        except Exception as e:
            await self.capability_worker.speak(self._summarize_error(e))
            return "another"

        if not episodes:
            await self.capability_worker.speak("Couldn't find any episodes for that one.")
            return "another"

        podcast_info = {
            "title": podcast_data.get("title", selected_name),
            "title_original": podcast_data.get("title", selected_name),
        }
        latest = episodes[0]
        if "podcast" not in latest:
            latest["podcast"] = podcast_info

        await self.play_episode(latest, state)
        return "played"

    async def _handle_podcast(self, intent_data: dict, state: dict) -> str:
        """
        Search for a podcast by name, show latest 5 episodes, let user pick.
        Returns: "played", "another", "exit"
        """
        api_key = state["api_key"]
        podcast_name = intent_data.get("podcast")

        if not podcast_name:
            await self.capability_worker.speak("Which podcast are you looking for?")
            podcast_name = await self.capability_worker.user_response()
            if not podcast_name:
                return "another"

        await self.capability_worker.speak(random.choice(SEARCH_FILLERS))

        try:
            podcasts = await asyncio.to_thread(self.search_podcasts, podcast_name, api_key)
        except Exception as e:
            await self.capability_worker.speak(self._summarize_error(e))
            return "another"

        if not podcasts:
            await self.capability_worker.speak(f"Couldn't find {podcast_name}. Want to try something else?")
            return "another"

        # Auto-select if top result clearly matches the requested name
        top_title = self._podcast_title(podcasts[0]).lower()
        query_lower = podcast_name.lower()
        name_match = (
            query_lower in top_title or top_title in query_lower
        )

        if name_match or len(podcasts) == 1:
            selected_podcast = podcasts[0]
            self._log(
                f"[Podcast] Auto-selected: "
                f"{self._podcast_title(selected_podcast)}"
            )
        else:
            # Ambiguous results — ask user to pick
            top_pods = podcasts[:3]
            pod_names = [self._podcast_title(p) for p in top_pods]

            pod_summary = self._summarize_for_voice(
                f"I found a few matches: {', '.join(pod_names)}. "
                "Ask which one the user means."
            )
            await self.capability_worker.speak(pod_summary)

            pod_choice = await self.capability_worker.user_response()
            if not pod_choice:
                return "another"

            pod_pick = self.select_from_options(pod_choice, pod_names)

            if pod_pick.get("action") == "exit":
                return "exit"
            if pod_pick.get("action") == "another":
                return "another"

            idx = pod_pick.get("index", 0)
            if idx < 0 or idx >= len(top_pods):
                idx = 0
            selected_podcast = top_pods[idx]

        selected_name = self._podcast_title(selected_podcast)
        state["last_podcast_name"] = selected_name

        try:
            episodes, podcast_data = await asyncio.to_thread(
                self.get_podcast_episodes, selected_podcast["id"], api_key
            )
        except Exception as e:
            await self.capability_worker.speak(self._summarize_error(e))
            return "another"

        if not episodes:
            await self.capability_worker.speak("Couldn't find any episodes for that one.")
            return "another"

        podcast_info = {
            "title": podcast_data.get("title", ""),
            "title_original": podcast_data.get("title", ""),
        }
        for ep in episodes:
            if "podcast" not in ep:
                ep["podcast"] = podcast_info

        latest = episodes[:5]
        ep_titles = [ep["title"] for ep in latest]
        state["last_episode_podcast_name"] = selected_name
        state["last_episode_options"] = ep_titles

        ep_summary = self._summarize_for_voice(
            f"The latest episodes from {selected_name} are: "
            f"{', '.join(ep_titles)}. "
            "Briefly mention topics or guests if obvious from the titles. "
            "Ask which one the user wants to hear."
        )
        await self.capability_worker.speak(ep_summary)

        ep_choice = await self.capability_worker.user_response()
        if not ep_choice:
            return "another"

        ep_pick = self.select_from_options(ep_choice, ep_titles)

        if ep_pick.get("action") == "exit":
            return "exit"
        if ep_pick.get("action") == "another":
            return "another"

        ep_idx = ep_pick.get("index", 0)
        if ep_idx < 0 or ep_idx >= len(latest):
            ep_idx = 0

        await self.play_episode(latest[ep_idx], state)
        return "played"

    async def _handle_episode(self, intent_data: dict, state: dict) -> str:
        """
        User specified podcast + guest/topic.
        Step 1: Resolve podcast name → podcast ID
        Step 2: Search episodes scoped to that podcast (ocid)
        Step 3: Present results, ask user to pick
        Step 4: Play
        Returns: "played", "another", "exit"
        """
        api_key = state["api_key"]
        podcast_name = intent_data.get("podcast") or ""
        guest = intent_data.get("guest") or ""
        topic = intent_data.get("topic") or ""

        if not podcast_name:
            podcast_name = (
                state.get("last_episode_podcast_name")
                or state.get("last_podcast_name")
                or ""
            )

        if not podcast_name:
            await self.capability_worker.speak("Which podcast is that from?")
            podcast_name = await self.capability_worker.user_response()
            if not podcast_name:
                return "another"

        await self.capability_worker.speak(random.choice(EPISODE_FILLERS))

        ep_query_parts = [p for p in [guest, topic] if p]
        ep_query = " ".join(ep_query_parts) if ep_query_parts else podcast_name

        self._log(f"[Episode] Query: '{ep_query}', podcast: {podcast_name}")

        # --- Step 1: Resolve podcast → ID ---
        try:
            podcasts = await asyncio.to_thread(self.search_podcasts, podcast_name, api_key)
        except Exception as e:
            await self.capability_worker.speak(self._summarize_error(e))
            return "another"

        podcast_id = None
        if podcasts:
            podcast_id = podcasts[0]["id"]
            self._log(f"[Episode] Resolved: {self._podcast_title(podcasts[0])} (id={podcast_id})")

        # --- Step 2: Search episodes scoped to that podcast ---
        try:
            results = await asyncio.to_thread(self.search_episodes, ep_query, api_key, podcast_id)
            if not results and podcast_id and guest:
                self._log(f"[Episode] Fallback: scoped search for '{guest}'")
                results = await asyncio.to_thread(self.search_episodes, guest, api_key, podcast_id)
        except Exception as e:
            await self.capability_worker.speak(self._summarize_error(e))
            return "another"

        if not results:
            await self.capability_worker.speak("Couldn't find that exact one. Let me show you the latest from that podcast instead.")
            return await self._handle_podcast({"podcast": podcast_name}, state)

        # --- Step 3: Single result → play directly, multiple → ask ---
        if len(results) == 1:
            self._log("[Episode] Single match — playing directly")
            await self.play_episode(results[0], state)
            return "played"

        top = results[:3]
        ep_options = []
        for ep in top:
            ep_title = ep.get(
                "title_original", ep.get("title") or "this episode"
            )
            ep_podcast = self._podcast_title(ep.get("podcast", {}))
            ep_options.append(f"{ep_title} from {ep_podcast}")

        summary = self._summarize_for_voice(
            f"Here's what I found: {', '.join(ep_options)}. "
            "Ask which one the user wants to play."
        )
        await self.capability_worker.speak(summary)

        choice = await self.capability_worker.user_response()
        if not choice:
            return "another"

        pick = self.select_from_options(choice, ep_options)

        if pick.get("action") == "exit":
            return "exit"
        if pick.get("action") == "another":
            return "another"

        # --- Step 4: Play ---
        ep_idx = pick.get("index", 0)
        if ep_idx < 0 or ep_idx >= len(top):
            ep_idx = 0

        await self.play_episode(top[ep_idx], state)
        return "played"

    # -------------------------------------------------------------------------
    # Main Flow
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            # --- API key gate ---
            api_key = self.capability_worker.get_api_keys("listen_notes_api_key")
            if not api_key:
                self._log_err("[Run] No API key found")
                await self.capability_worker.speak(
                    "The Listen Notes API key is not set. Please add it in Settings under API Keys."
                )
                return

            self._log("[Run] API key loaded, starting session")

            state = {
                "results": [],
                "current_episode": None,
                "api_key": api_key,
            }

            self.worker.music_mode_event.set()
            await self.capability_worker.send_data_over_websocket(
                "music-mode", {"mode": "on"}
            )
            self._log("[Run] Music mode ON")

            # --- Read trigger context ---
            trigger_text = await self.capability_worker.wait_for_complete_transcription()
            self._log(f"[Run] Trigger text: {trigger_text}")

            first_time = True
            episode_just_played = False

            while True:
                # --- Get user input ---
                if first_time:
                    first_time = False
                    stripped = (trigger_text or "").strip().lower()
                    _bare_phrases = {
                        "", "podcast", "podcasts", "podcast player",
                        "play podcast", "play podcasts", "play a podcast",
                        "play some podcasts", "play some podcast",
                        "open podcast", "open podcasts", "open podcast player",
                        "start podcast", "start podcasts", "start podcast player",
                        "hey podcast", "launch podcast", "launch podcast player",
                        "tell me a podcast", "find me a podcast", "give me a podcast",
                        "find a podcast", "get a podcast", "podcast please",
                        "listen to a podcast", "listen to podcast",
                        "i want to listen to a podcast", "i want a podcast",
                    }
                    bare_trigger = stripped in _bare_phrases
                    if trigger_text and trigger_text.strip() and not bare_trigger:
                        user_input = trigger_text
                    else:
                        await self.capability_worker.speak(
                            "What would you like to listen to? You can name a show, "
                            "ask for a specific episode, say trending for some popular picks, "
                            "or say random and I will surprise you."
                        )
                        user_input = await self.capability_worker.user_response()
                elif episode_just_played:
                    episode_just_played = False
                    user_input = await self.capability_worker.run_io_loop(
                        random.choice(CONTINUE_PROMPTS)
                    )
                else:
                    user_input = await self.capability_worker.user_response()

                if not user_input:
                    continue

                # --- Fast exit ---
                if self._is_exit_phrase(user_input):
                    await self._speak_exit()
                    break

                # --- Classify intent ---
                intent_data = self.classify_intent(user_input)
                intent = intent_data.get("intent")

                self._log(f"[Run] Intent: {json.dumps(intent_data)}")

                # --- Route to handler ---
                if intent == "exit":
                    await self._speak_exit()
                    break

                elif intent == "browse_trending":
                    result = await self._handle_browse_trending(state)

                elif intent == "play_random":
                    result = await self._handle_random(state)

                elif intent == "play_latest":
                    result = await self._handle_latest(intent_data, state)

                elif intent == "play_podcast":
                    result = await self._handle_podcast(intent_data, state)

                elif intent == "play_episode":
                    result = await self._handle_episode(intent_data, state)

                else:
                    await self.capability_worker.speak(
                        "Didn't catch that. Try a podcast name, say random, or say trending for some picks."
                    )
                    continue

                # --- Handle flow result ---
                if result == "played":
                    episode_just_played = True
                elif result == "exit":
                    await self._speak_exit()
                    break
                # "another" just loops back naturally

        except Exception as e:
            self._log_err(f"[Run] Unhandled error: {e}")
            await self.capability_worker.speak(self._summarize_error(e))
        finally:
            self._log("[Run] Cleaning up, exiting")
            await self.capability_worker.send_data_over_websocket(
                "music-mode", {"mode": "off"}
            )
            self.worker.music_mode_event.clear()
            self.worker.music_mode_stop_event.clear()
            await self.worker.session_tasks.sleep(0.2)
            self.capability_worker.resume_normal_flow()
