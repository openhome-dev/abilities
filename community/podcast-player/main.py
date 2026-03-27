import json

import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

API_KEY = "YOUR_LISTEN_NOTES_API_KEY"  # YOUR KEY from https://www.listennotes.com/api/dashboard/#apps
BASE_URL = "https://listen-api.listennotes.com/api/v2"

EXIT_WORDS = {
    "stop", "exit", "quit", "cancel",
    "forget it", "never mind", "nevermind", "done",
    "bye", "that's all", "no thanks", "actually", "leave it"
}

PAUSE_WORDS = {"pause", "hold on", "wait"}
SURPRISE_WORDS = {"surprise", "random", "anything"}
SEARCH_WORDS = {"find", "search", "podcast", "listen"}
ELSE_WORDS = {"something else", "another one"}
WHATS_PLAYING_WORDS = {"what's playing", "what is playing", "current"}


class PodcastPlayerCapability(MatchingCapability):
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

    def _headers(self):
        return {"X-ListenAPI-Key": API_KEY}

    def _wants(self, text: str, words: set[str]) -> bool:
        t = text.lower()
        return any(w in t for w in words)
    
    # -------------------------------------------------------------------------
    # API Calls
    # -------------------------------------------------------------------------
   
    async def classify_intent(self, user_input: str) -> dict:
        # Надсилаємо user_input LLM і отримуємо відповідь (можеш інтегрувати OpenAI GPT)
        prompt = f"""
        Classify the user's command into one of the following intents:
        - play_podcast: user wants to play a podcast by name or topic
        - play_episode: user wants to play a specific episode
        - play_random: user wants to play a random episode
        - pause: user wants to pause the playback
        - exit: user wants to stop the ability
        - whats_playing: user asks what is currently playing
        Respond in JSON: {{ "intent": "...", "query": "..." }}
        User said: "{user_input}"
        """
        llm_response = self.capability_worker.text_to_text_response(prompt_text=prompt)
        
        try:
            data = json.loads(llm_response)
            return data
        except Exception:
            # fallback
            return {"intent": "unknown", "query": None}
        
    def search_episodes(self, query: str):
        url = f"{BASE_URL}/search"
        params = {"q": query, "type": "episode", "sort_by_date": 0, "page_size": 5}
        response = requests.get(url, headers=self._headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("results", [])

    def search_podcasts(self, query: str):
        url = f"{BASE_URL}/search"
        params = {"q": query, "type": "podcast", "page_size": 5}
        response = requests.get(url, headers=self._headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("results", [])

    def random_episode(self):
        url = f"{BASE_URL}/just_listen"
        response = requests.get(url, headers=self._headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    
    def get_podcast_episodes(self, podcast_id: str):
        url = f"{BASE_URL}/podcasts/{podcast_id}"
        params = {"sort": "recent_first"}
        response = requests.get(url, headers=self._headers(), params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("episodes", [])
    # -------------------------------------------------------------------------
    # Playback
    # -------------------------------------------------------------------------
    def match_choice(self, user_input: str, options: list[dict], key: str):
        text = user_input.lower()

        for opt in options:
            if opt[key].lower() in text:
                return opt

        return options[0] if options else None
    
    async def play_episode(self, episode: dict, state: dict):
        state["current_episode"] = episode
        title = episode["title"]
        podcast = episode["podcast"]["title_original"]
        audio_url = episode.get("audio")

        if not audio_url:
            await self.capability_worker.speak("No audio URL found for this episode.")
            return

        await self.capability_worker.speak(f"Playing {title} from {podcast}.")

        # --- Streaming long audio ---
        await self.capability_worker.stream_init()
        try:
            with requests.get(audio_url, stream=True, timeout=10) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        await self.capability_worker.send_audio_data_in_stream(chunk)
        except Exception as e:
            await self.capability_worker.speak("Had trouble loading that episode. Want to try a different one?")
        finally:
            await self.capability_worker.stream_end()
    # -------------------------------------------------------------------------
    # Main Flow
    # -------------------------------------------------------------------------
    async def run(self):
        try:
            state = {
                "results": [],
                "current_episode": None
            }

            await self.capability_worker.speak(
                "What do you want to listen to?"
            )

            while True:
                user_input = await self.capability_worker.user_response()
                if not user_input:
                    continue

                result = await self.classify_intent(user_input)
                intent = result.get("intent")
                query = result.get("query")

                # ---------------- EXIT ----------------
                if intent == "exit":
                    await self.capability_worker.speak("Stopping playback.")
                    break
                
                elif intent == "pause":
                    await self.capability_worker.speak("Paused.")
                    continue        
                # ---------------- RANDOM ----------------
                elif intent == "play_random":
                    ep = self.random_episode()
                    await self.play_episode(ep, state)
                    continue

                # ---------------- WHAT'S PLAYING ----------------
                elif intent == "whats_playing":
                    ep = state.get("current_episode")
                    if ep:
                        await self.capability_worker.speak(
                            f"You're listening to {ep['title']} "
                            f"from {ep['podcast']['title_original']}."
                        )
                    else:
                        await self.capability_worker.speak("Nothing is playing right now.")
                    continue

                # ---------------- PODCAST FLOW ----------------
                elif intent == "play_podcast":
                        if not query:
                            await self.capability_worker.speak("Which podcast do you want to listen to?")
                            query = await self.capability_worker.user_response()
                            if not query:
                                continue
                            
                        podcasts = self.search_podcasts(query)

                        if not podcasts:
                            await self.capability_worker.speak(
                                "Couldn't find any podcasts for that — try another search?"
                            )
                            continue

                        # ---- TOP PODCASTS ----
                        top = podcasts[:3]
                        titles = [p["title_original"] for p in top]

                        if len(titles) == 1:
                            spoken_list = titles[0]
                        else:
                            spoken_list = f"{', '.join(titles[:-1])}, and {titles[-1]}"

                        await self.capability_worker.speak(
                            f"I found a few podcasts: {spoken_list}. Which one sounds right?"
                        )

                        choice = await self.capability_worker.user_response()
                        if not choice:
                            continue

                        # ---- MATCH PODCAST ----
                        selected_podcast = self.match_choice(choice, top, "title_original")

                        # ---- GET EPISODES ----
                        episodes = self.get_podcast_episodes(selected_podcast["id"])

                        if not episodes:
                            await self.capability_worker.speak(
                                "That podcast doesn't seem to have any episodes available."
                            )
                            continue

                        latest_five = episodes[:5]
                        ep_titles = [ep["title"] for ep in latest_five]

                        if len(ep_titles) == 1:
                            spoken_eps = ep_titles[0]
                        else:
                            spoken_eps = f"{', '.join(ep_titles[:-1])}, and {ep_titles[-1]}"

                        await self.capability_worker.speak(
                            f"Latest episodes from {selected_podcast['title_original']} include: {spoken_eps}. "
                            "Which one do you want?"
                        )

                        ep_choice = await self.capability_worker.user_response()
                        if not ep_choice:
                            continue

                        # ---- MATCH EPISODE ----
                        selected_episode = self.match_choice(ep_choice, latest_five, "title")

                        await self.play_episode(selected_episode, state)
                        continue
                    
                # ---------------- EPISODE SEARCH FLOW ----------------
                elif intent == "play_episode":

                    results = self.search_episodes(user_input)

                    if not results:
                        await self.capability_worker.speak(
                            "I couldn't find any episodes for that."
                        )
                        continue

                    state["results"] = results

                    await self.capability_worker.speak("Here are a few options:")

                    top = results[:3]

                    titles = []
                    for ep in top:
                        audio_sec = ep.get("audio_length_sec")
                        if audio_sec:
                            minutes = int(audio_sec // 60)
                            duration = f"{minutes} minutes"
                        else:
                            duration = "unknown duration"

                        titles.append(f"{ep['title']} from {ep['podcast']['title']} ({duration})")

                    # ---- Natural sentence ----
                    if len(titles) == 1:
                        spoken = titles[0]
                    else:
                        spoken = f"{', '.join(titles[:-1])}, and {titles[-1]}"

                    await self.capability_worker.speak(
                        f"I found a few episodes: {spoken}. Which one sounds good?"
                    )

                    choice = await self.capability_worker.user_response()
                    if not choice:
                        continue

                    selected_episode = self.match_choice(choice, top, "title")

                    await self.play_episode(selected_episode, state)
                    continue


        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PodcastPlayer] Error: {e}")
            await self.capability_worker.speak(
                "Something went wrong while playing the podcast."
            )

        self.capability_worker.resume_normal_flow()
    