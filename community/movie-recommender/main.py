import json
import re

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# MOVIE & TV RECOMMENDER
# Recommends movies using the TMDB API. Supports trending, genre search,
# mood-based search, and similar-to queries. Requires a free TMDB API key
# set as TMDB_API_KEY environment variable.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_API_KEY = ""

GENRE_MAP = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Science Fiction",
    10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
}

INTENT_PROMPT = (
    "Classify the user's movie request. Return ONLY valid JSON.\n"
    'Format: {{"intent": "trending|genre|similar|search", '
    '"query": "<movie name or genre/mood>"}}\n'
    "Rules:\n"
    "- 'trending', 'popular', 'what's hot' -> trending\n"
    "- genre/mood words (comedy, scary, romantic, action, funny) -> genre\n"
    "- 'like X', 'similar to X', 'movies like X' -> similar\n"
    "- specific movie name -> search\n"
    "Input: {text}"
)

GENRE_MATCH_PROMPT = (
    "Map this mood or genre description to one of these TMDB genre IDs. "
    "Return ONLY the genre ID number.\n"
    "Genres: 28=Action, 12=Adventure, 16=Animation, 35=Comedy, 80=Crime, "
    "99=Documentary, 18=Drama, 10751=Family, 14=Fantasy, 27=Horror, "
    "9648=Mystery, 10749=Romance, 878=Sci-Fi, 53=Thriller, 10752=War, "
    "37=Western\n"
    "Mood mappings: scary/spooky=27, funny/hilarious=35, romantic/love=10749, "
    "exciting/intense=28, thoughtful/deep=18, adventurous=12, mysterious=9648\n"
    "Input: {text}"
)

MOVIE_VOICE_PROMPT = (
    "Summarize these movie recommendations for voice output. For each movie, "
    "give the title, year, rating out of 10, and a one-sentence description. "
    "Keep it concise and conversational. Do not use bullet points."
)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class SportsscoreCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    api_key: str = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.api_key = TMDB_API_KEY
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info(
                "[MovieRecommender] Ability started"
            )

            if not self.api_key:
                await self.capability_worker.speak(
                    "I need a TMDB API key to recommend movies. "
                    "Please set the TMDB_API_KEY environment variable. "
                    "You can get a free key at themoviedb.org."
                )
                return

            await self.capability_worker.speak(
                "I can recommend movies! Want to see what's trending, "
                "search by genre or mood, or find movies similar to one you like?"
            )

            idle_count = 0

            for _ in range(15):
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Closing the movie recommender. Enjoy your next watch!"
                        )
                        break
                    await self.capability_worker.speak(
                        "I'm listening. What kind of movie are you looking for?"
                    )
                    continue

                idle_count = 0

                if any(w in user_input.lower() for w in EXIT_WORDS):
                    await self.capability_worker.speak(
                        "Enjoy your movie! Goodbye."
                    )
                    break

                intent_data = self._classify_intent(user_input)
                intent = intent_data.get("intent", "trending")
                query = intent_data.get("query", "")

                if intent == "trending":
                    movies = self._fetch_trending()
                elif intent == "genre":
                    movies = self._fetch_by_genre(query)
                elif intent == "similar":
                    movies = self._fetch_similar(query)
                else:
                    movies = self._search_movie(query)

                if not movies:
                    await self.capability_worker.speak(
                        "I couldn't find any movies matching that. "
                        "Try a different genre or movie name."
                    )
                else:
                    summary = self._summarize_movies(movies[:3])
                    await self.capability_worker.speak(summary)

                await self.capability_worker.speak(
                    "Want another recommendation? Try a different genre or mood."
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MovieRecommender] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing the movie recommender."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[MovieRecommender] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _classify_intent(self, text: str) -> dict:
        lower = text.lower()

        if any(w in lower for w in ("trending", "popular", "what's hot", "top movies")):
            return {"intent": "trending", "query": ""}

        if any(w in lower for w in ("similar to", "like ", "movies like")):
            return {"intent": "similar", "query": text}

        try:
            raw = self.capability_worker.text_to_text_response(
                INTENT_PROMPT.format(text=text)
            )

            if not raw or not raw.strip():
                raise ValueError("Empty LLM response")

            cleaned = _strip_json_fences(raw)

            if not cleaned:
                raise ValueError("Empty cleaned response")

            return json.loads(cleaned)

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MovieRecommender] Intent parsing error: {e}"
            )
            return {"intent": "search", "query": text}

    def _tmdb_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "accept": "application/json",
        }

    def _fetch_trending(self) -> list:
        try:
            resp = requests.get(
                f"{TMDB_BASE_URL}/trending/movie/week",
                headers=self._tmdb_headers(),
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json().get("results", [])[:5]
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MovieRecommender] Trending fetch error: {e}"
            )
        return []

    def _fetch_by_genre(self, mood_or_genre: str) -> list:
        genre_id = self._resolve_genre(mood_or_genre)
        if not genre_id:
            return []
        try:
            resp = requests.get(
                f"{TMDB_BASE_URL}/discover/movie",
                headers=self._tmdb_headers(),
                params={
                    "with_genres": genre_id,
                    "sort_by": "popularity.desc",
                    "page": 1,
                },
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json().get("results", [])[:5]
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MovieRecommender] Genre fetch error: {e}"
            )
        return []

    def _fetch_similar(self, query: str) -> list:
        movie_name = re.sub(
            r"(?i)(similar to|like|movies like)\s*", "", query
        ).strip()
        movie_id = self._search_movie_id(movie_name)
        if not movie_id:
            return []
        try:
            resp = requests.get(
                f"{TMDB_BASE_URL}/movie/{movie_id}/similar",
                headers=self._tmdb_headers(),
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json().get("results", [])[:5]
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MovieRecommender] Similar fetch error: {e}"
            )
        return []

    def _search_movie(self, query: str) -> list:
        try:
            resp = requests.get(
                f"{TMDB_BASE_URL}/search/movie",
                headers=self._tmdb_headers(),
                params={"query": query},
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json().get("results", [])[:5]
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MovieRecommender] Search error: {e}"
            )
        return []

    def _search_movie_id(self, name: str) -> int:
        try:
            resp = requests.get(
                f"{TMDB_BASE_URL}/search/movie",
                headers=self._tmdb_headers(),
                params={"query": name},
                timeout=5,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    return results[0].get("id")
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MovieRecommender] Movie ID search error: {e}"
            )
        return None

    def _resolve_genre(self, text: str) -> str:
        lower = text.lower()
        keyword_map = {
            "action": 28, "adventure": 12, "animation": 16, "comedy": 35,
            "funny": 35, "crime": 80, "documentary": 99, "drama": 18,
            "family": 10751, "fantasy": 14, "horror": 27, "scary": 27,
            "mystery": 9648, "romance": 10749, "romantic": 10749,
            "sci-fi": 878, "science fiction": 878, "thriller": 53,
            "war": 10752, "western": 37,
        }
        for keyword, gid in keyword_map.items():
            if keyword in lower:
                return str(gid)
        try:
            result = self.capability_worker.text_to_text_response(
                GENRE_MATCH_PROMPT.format(text=text)
            )
            genre_id = re.search(r"\d+", result.strip())
            if genre_id:
                return genre_id.group()
        except Exception:
            pass
        return ""

    def _summarize_movies(self, movies: list) -> str:
        movie_data = []
        for m in movies:
            movie_data.append({
                "title": m.get("title", "Unknown"),
                "year": (m.get("release_date", "") or "")[:4],
                "rating": m.get("vote_average", 0),
                "overview": m.get("overview", "")[:200],
            })
        data_text = json.dumps(movie_data, indent=2)
        try:
            response = self.capability_worker.text_to_text_response(
                f"Movies:\n{data_text}",
                system_prompt=MOVIE_VOICE_PROMPT,
            )
            return response
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MovieRecommender] Summary error: {e}"
            )
            parts = []
            for m in movie_data:
                parts.append(
                    f"{m['title']} from {m['year']}, rated {m['rating']} out of 10"
                )
            return "Here are some recommendations: " + ". ".join(parts) + "."
