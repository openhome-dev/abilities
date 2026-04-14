import json
import re
import random

import httpx
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

BASE_URL = "https://listen-api.listennotes.com/api/v2"

EXIT_WORDS = {
    "stop", "exit", "quit", "cancel", "done",
    "bye", "that's all", "no thanks", "leave it",
    "forget it", "never mind", "nevermind"
}

CONTINUE_PROMPTS = [
    "Want to listen to something else, or are you done?",
    "Another podcast, or should I stop?",
    "What's next? Another episode or we're done?",
    "Shall I find you something else?",
]

EXIT_MESSAGES = [
    "Thanks for listening. See you next time!",
    "Hope you enjoyed that. Catch you later!",
    "Signing off. Happy listening!",
    "That's a wrap. Talk soon!",
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

    def _podcast_title(self, podcast_dict: dict) -> str:
        return (
            podcast_dict.get("title_original")
            or podcast_dict.get("title")
            or "Unknown Podcast"
        )

    def _clean_json(self, raw: str) -> dict:
        """Strip markdown fences, whitespace, and parse JSON."""
        cleaned = raw.strip()
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()
        return json.loads(cleaned)

    def _summarize_for_voice(self, text: str) -> str:
        prompt = (
            "You are a voice assistant. Rewrite the following into a short, "
            "natural spoken summary. Keep it under 2 sentences. "
            "No numbering, no bullet points, no extra commentary.\n\n"
            f"{text}"
        )
        return self.capability_worker.text_to_text_response(prompt)

    async def _speak_exit(self):
        await self.capability_worker.speak(random.choice(EXIT_MESSAGES))

    # -------------------------------------------------------------------------
    # Intent Classification
    # -------------------------------------------------------------------------

    def classify_intent(self, user_input: str) -> dict:
        """
        Returns structured JSON:
        {
            "intent": "play_random" | "play_podcast" | "play_episode" | "exit",
            "podcast": "podcast name or null",
            "guest": "guest name or null",
            "topic": "topic or null"
        }
        """
        prompt = (
            "You are an intent classifier for a voice-controlled podcast player. "
            "Input comes from speech-to-text — expect filler words, misspellings, "
            "and sentence fragments. Extract meaning, not exact words.\n\n"

            "INTENT DEFINITIONS:\n"
            "- play_random: user wants any random podcast, no specific preference\n"
            "- play_podcast: user names a podcast but NOT a specific episode, "
            "guest, or topic within that podcast\n"
            "- play_episode: user names a podcast AND at least one of: "
            "a guest name, a topic, or an episode title\n"
            "- exit: user wants to stop, quit, or is done\n\n"

            "RESPONSE FORMAT — return ONLY this JSON structure, nothing else:\n"
            "{\n"
            '  "intent": "play_random | play_podcast | play_episode | exit",\n'
            '  "podcast": "extracted podcast name or null",\n'
            '  "guest": "extracted guest name or null",\n'
            '  "topic": "extracted topic or null"\n'
            "}\n\n"

            "RULES:\n"
            "1. No markdown fences, no explanation, no extra text. JSON only.\n"
            "2. If the user mentions a podcast name + a person or topic, "
            "that is play_episode (they want a specific episode).\n"
            "3. If the user only mentions a podcast name with no guest or topic, "
            "that is play_podcast.\n"
            "4. If the user says random, surprise me, anything, play something — "
            "that is play_random. All fields null.\n"
            "5. If the user says stop, done, quit, bye, nah, I'm good — "
            "that is exit. All fields null.\n"
            "6. Strip filler words (um, uh, like) from extracted values.\n"
            "7. Do NOT invent intents beyond the four listed.\n\n"

            "EXAMPLES:\n"
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
            '"guest": null, "topic": null}\n\n'

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

        prompt = (
            "You are helping a voice assistant user pick from a list. "
            "Input comes from speech-to-text and may be imprecise.\n\n"

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
            "6. If unsure, pick the closest match.\n\n"

            "EXAMPLES:\n"
            "Given options: 1. Interview with Jensen Huang  "
            "2. Vikings History  3. AI Revolution\n"
            'User: "the one with jensen" -> {"action": "play", "index": 1}\n'
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
            return []

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
            return []

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
            return []

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
            return [], {}

    # -------------------------------------------------------------------------
    # Playback
    # -------------------------------------------------------------------------

    async def stream_episode_audio(self, stream_response):
        """Stream audio chunks with stop/pause handling (Audius v1 pattern)."""
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
        title = episode.get("title", "Unknown")
        podcast = self._podcast_title(episode.get("podcast", {}))
        audio_url = episode.get("audio")

        if not audio_url:
            self._log_err(f"[Play] No audio URL for: {title}")
            await self.capability_worker.speak(
                "No audio URL found for this episode."
            )
            return

        self._log(f"[Play] Starting: {title} from {podcast}")
        await self.capability_worker.speak(f"Playing {title} from {podcast}.")

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
                        await self.capability_worker.speak(
                            "Couldn't load that episode. Want to try another?"
                        )
        except Exception as e:
            self._log_err(f"[Play] Error: {e}")
            await self.capability_worker.speak(
                "Had trouble loading that episode."
            )

    # -------------------------------------------------------------------------
    # Flow Handlers
    # -------------------------------------------------------------------------

    async def _handle_random(self, state: dict) -> str:
        """
        Fetch 5 random podcasts, let user pick one, play latest episode.
        Returns: "played", "another", "exit"
        """
        api_key = state["api_key"]

        # Filler before API call
        await self.capability_worker.speak(
            "Finding some random podcasts for you."
        )

        all_pods = self.fetch_best_podcasts(api_key)
        if not all_pods:
            await self.capability_worker.speak(
                "Couldn't fetch podcasts right now. Try again?"
            )
            return "another"

        picks = random.sample(all_pods, min(5, len(all_pods)))
        pod_names = [self._podcast_title(p) for p in picks]

        summary = self._summarize_for_voice(
            f"Here are some podcasts: {', '.join(pod_names)}. "
            "Ask which one the user wants to check out."
        )
        await self.capability_worker.speak(summary)

        choice = await self.capability_worker.user_response()
        if not choice:
            return "another"

        pick = self.select_from_options(choice, pod_names)

        if pick.get("action") == "exit":
            return "exit"
        if pick.get("action") == "another":
            return "another"

        idx = pick.get("index", 0)
        if idx < 0 or idx >= len(picks):
            idx = 0
        selected = picks[idx]
        selected_name = self._podcast_title(selected)

        # Filler before fetching episodes
        await self.capability_worker.speak(
            f"Pulling up the latest from {selected_name}."
        )

        episodes, podcast_data = self.get_podcast_episodes(
            selected["id"], api_key
        )
        if not episodes:
            await self.capability_worker.speak(
                "That podcast doesn't have any episodes right now."
            )
            return "another"

        podcast_info = {
            "title": podcast_data.get("title", ""),
            "title_original": podcast_data.get("title", ""),
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
            await self.capability_worker.speak(
                "Which podcast are you looking for?"
            )
            podcast_name = await self.capability_worker.user_response()
            if not podcast_name:
                return "another"

        # Filler before API call
        await self.capability_worker.speak(
            f"Searching for {podcast_name}."
        )

        podcasts = self.search_podcasts(podcast_name, api_key)
        if not podcasts:
            await self.capability_worker.speak(
                f"Couldn't find a podcast called {podcast_name}. "
                "Try something else?"
            )
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

        # Filler before fetching episodes
        await self.capability_worker.speak(
            f"Pulling up episodes from {selected_name}."
        )

        episodes, podcast_data = self.get_podcast_episodes(
            selected_podcast["id"], api_key
        )
        if not episodes:
            await self.capability_worker.speak(
                "No episodes available for that podcast."
            )
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
            await self.capability_worker.speak(
                "Which podcast is that from?"
            )
            podcast_name = await self.capability_worker.user_response()
            if not podcast_name:
                return "another"

        # Build a descriptive filler
        filler_parts = [podcast_name]
        if guest:
            filler_parts.append(f"with {guest}")
        if topic:
            filler_parts.append(f"about {topic}")
        filler_text = " ".join(filler_parts)

        await self.capability_worker.speak(
            f"Searching for {filler_text}."
        )

        # --- Step 1: Resolve podcast → ID ---
        podcasts = self.search_podcasts(podcast_name, api_key)
        podcast_id = None

        if podcasts:
            podcast_id = podcasts[0]["id"]
            self._log(
                f"[Episode] Resolved podcast: "
                f"{self._podcast_title(podcasts[0])} (id={podcast_id})"
            )

        # --- Step 2: Search episodes scoped to that podcast ---
        ep_query_parts = [p for p in [guest, topic] if p]
        ep_query = (
            " ".join(ep_query_parts) if ep_query_parts else podcast_name
        )

        self._log(
            f"[Episode] Query: '{ep_query}', podcast_id: {podcast_id}"
        )

        results = self.search_episodes(ep_query, api_key, podcast_id)

        if not results and podcast_id and guest:
            self._log(
                f"[Episode] Fallback: searching '{guest}' in podcast"
            )
            results = self.search_episodes(guest, api_key, podcast_id)

        if not results:
            await self.capability_worker.speak(
                "Couldn't find that exact episode. "
                "Let me show you the latest from that podcast."
            )
            return await self._handle_podcast(
                {"podcast": podcast_name}, state
            )

        # --- Step 3: Single result → play directly, multiple → ask ---
        if len(results) == 1:
            self._log("[Episode] Single match — playing directly")
            await self.play_episode(results[0], state)
            return "played"

        top = results[:3]
        ep_options = []
        for ep in top:
            ep_title = ep.get(
                "title_original", ep.get("title", "Unknown")
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
                    "Listen Notes API key is not set. "
                    "Please add it in Settings under API Keys."
                )
                return

            self._log("[Run] API key loaded, starting session")

            state = {
                "results": [],
                "current_episode": None,
                "api_key": api_key,
            }

            # --- Music mode for entire session (Audius v1 pattern) ---
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
                    if trigger_text and trigger_text.strip():
                        user_input = trigger_text
                    else:
                        await self.capability_worker.speak(
                            "What do you want to listen to?"
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
                if user_input.lower().strip() in EXIT_WORDS:
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

                elif intent == "play_random":
                    result = await self._handle_random(state)

                elif intent == "play_podcast":
                    result = await self._handle_podcast(intent_data, state)

                elif intent == "play_episode":
                    result = await self._handle_episode(intent_data, state)

                else:
                    await self.capability_worker.speak(
                        "I didn't catch that. You can ask for a podcast, "
                        "a specific episode, something random, "
                        "or say stop to exit."
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
            await self.capability_worker.speak("Something went wrong.")
        finally:
            self._log("[Run] Cleaning up, exiting")
            await self.capability_worker.send_data_over_websocket(
                "music-mode", {"mode": "off"}
            )
            self.worker.music_mode_event.clear()
            self.worker.music_mode_stop_event.clear()
            await self.worker.session_tasks.sleep(0.2)
            self.capability_worker.resume_normal_flow()
