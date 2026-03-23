import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

API_KEY = "YOUR_LISTEN_NOTES_API_KEY"  # YOUR KEY from https://www.listennotes.com/api/dashboard/#apps
BASE_URL = "https://listen-api.listennotes.com/api/v2"

EXIT_WORDS = {"stop", "pause", "exit", "quit", "cancel"}
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
            await self.capability_worker.speak(f"Error streaming audio: {e}")
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
                "What would you like to listen to? "
                "You can search for an episode, a podcast, or say surprise me."
            )

            while True:
                user_input = await self.capability_worker.user_response()
                if not user_input:
                    continue

                text = user_input.lower()

                # ---------------- EXIT ----------------
                if self._wants(text, EXIT_WORDS):
                    await self.capability_worker.speak("Stopping playback.")
                    break

                # ---------------- RANDOM ----------------
                if self._wants(text, SURPRISE_WORDS):
                    ep = self.random_episode()
                    await self.play_episode(ep, state)
                    continue

                # ---------------- WHAT'S PLAYING ----------------
                if self._wants(text, WHATS_PLAYING_WORDS):
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
                if "podcast" in text:

                    await self.capability_worker.speak("What podcast are you looking for?")
                    query = await self.capability_worker.user_response()
                    if not query:
                        continue

                    podcasts = self.search_podcasts(query)

                    if not podcasts:
                        await self.capability_worker.speak("No podcasts found.")
                        continue

                    for i, p in enumerate(podcasts[:3], start=1):
                        await self.capability_worker.speak(
                            f"{i}. {p['title_original']} by {p['publisher_original']}."
                        )

                    await self.capability_worker.speak(
                        "Choose 1, 2, or 3."
                    )

                    choice = await self.capability_worker.user_response()
                    if not choice:
                        continue

                    index_map = {"1": 0, "2": 1, "3": 2,
                                 "first": 0, "second": 1, "third": 2}

                    selected_index = None
                    for key, value in index_map.items():
                        if key in choice.lower():
                            selected_index = value
                            break

                    if selected_index is None or selected_index >= len(podcasts):
                        continue

                    selected_podcast = podcasts[selected_index]

                    episodes = self.get_podcast_episodes(selected_podcast["id"])
                    if not episodes:
                        await self.capability_worker.speak("No episodes found.")
                        continue

                    latest_five = episodes[:5]

                    await self.capability_worker.speak(
                        f"Here are the latest five episodes of {selected_podcast['title']}:"
                    )

                    for i, ep in enumerate(latest_five, start=1):
                        await self.capability_worker.speak(
                            f"{i}. {ep['title']}."
                        )

                    await self.capability_worker.speak(
                        "Choose 1, 2, 3, 4, or 5."
                    )

                    ep_choice = await self.capability_worker.user_response()
                    if not ep_choice:
                        continue

                    ep_index_map = {
                        "1": 0, "2": 1, "3": 2, "4": 3, "5": 4,
                        "first": 0, "second": 1, "third": 2,
                        "fourth": 3, "fifth": 4
                    }

                    selected_ep_index = None
                    for key, value in ep_index_map.items():
                        if key in ep_choice.lower():
                            selected_ep_index = value
                            break

                    if selected_ep_index is None or selected_ep_index >= len(latest_five):
                        continue

                    await self.play_episode(latest_five[selected_ep_index], state)
                    continue

                # ---------------- EPISODE SEARCH FLOW ----------------
                if self._wants(text, SEARCH_WORDS):

                    results = self.search_episodes(user_input)

                    if not results:
                        await self.capability_worker.speak(
                            "I couldn't find any episodes for that."
                        )
                        continue

                    state["results"] = results

                    await self.capability_worker.speak("Here are a few options:")

                    for i, ep in enumerate(results[:3], start=1):
                        audio_sec = ep.get("audio_length_sec")
                        if audio_sec:
                            minutes = int(audio_sec // 60)
                            duration = f"{minutes} minutes"
                        else:
                            duration = "unknown duration"

                        await self.capability_worker.speak(
                            f"{i}. {ep['title']} "
                            f"from {ep['podcast']['title']}, {duration}."
                        )

                    await self.capability_worker.speak(
                        "Choose 1, 2, or 3."
                    )

                    choice = await self.capability_worker.user_response()
                    if not choice:
                        continue

                    for key, index in {"1": 0, "2": 1, "3": 2,
                                       "first": 0, "second": 1, "third": 2}.items():
                        if key in choice.lower():
                            if index < len(results):
                                await self.play_episode(results[index], state)
                            break

                    continue

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PodcastPlayer] Error: {e}")
            await self.capability_worker.speak(
                "Something went wrong while playing the podcast."
            )

        self.capability_worker.resume_normal_flow()
