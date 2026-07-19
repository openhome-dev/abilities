import asyncio
import datetime
import difflib
import json
import random
import re
from typing import Any, Optional

import httpx

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# ============================================================================
# Constants
# ============================================================================

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_API_KEY_NAME = "tmdb_api_key"

RECOMMEND_COUNT = 3
MAX_TMDB_PAGES = 20
HISTORY_TURNS = 8
MAX_IDLE_TURNS = 5

GENRE_IDS = {
    "action": 28, "adventure": 12, "animation": 16, "animated": 16,
    "comedy": 35, "funny": 35, "crime": 80, "documentary": 99,
    "drama": 18, "family": 10751, "fantasy": 14, "horror": 27,
    "scary": 27, "spooky": 27, "mystery": 9648, "romance": 10749,
    "romantic": 10749, "science fiction": 878, "sci-fi": 878,
    "sci fi": 878, "sf": 878, "thriller": 53, "war": 10752, "western": 37,
}
GENRE_LIST = ", ".join(sorted(set(GENRE_IDS.keys())))

# Bare phrases that should trigger the welcome message, not a search.
BARE_TRIGGERS = {
    "", "movie", "movies", "movie recommender", "movie recommendation",
    "movies player", "play a movie", "play movies", "find me a movie",
    "find a movie", "show me a movie", "tell me a movie", "give me a movie",
    "i want a movie", "i want to watch", "what should i watch",
    "open movie recommender", "open movies", "start movies",
    "movie please", "movies please", "recommend a movie",
    "recommend me a movie", "suggest a movie", "hey movies", "hey movie",
}

# Bare decline phrases — after a continue prompt ("Anything else?", "What's next?"),
# saying just "no" / "nope" / "nah" means the user is done. Treat as exit.
BARE_DECLINES = {
    "no", "nope", "nah", "no thanks", "no thank you", "not really",
    "im fine", "i am fine", "im ok", "i am ok", "im alright",
    "i am alright", "not now",
}

# Phrases that DO exit the session (exact match — fastest path).
EXIT_PHRASES = {
    "goodbye", "bye", "bye bye", "see you", "quit", "exit",
    "im done", "i am done", "thats all", "that is all", "that is enough",
    "nothing", "nothing else", "cancel", "leave", "im good", "i am good",
    "nevermind", "never mind", "shut it down", "close",
}

# Single tokens that, in a SHORT utterance, signal exit intent regardless of
# surrounding intro words like "ok", "alright", "yeah", "thanks".
EXIT_TOKENS = {
    "goodbye", "bye", "quit", "exit", "cancel", "leave", "nevermind",
}

# Multi-word exit phrases to look for as substrings in short utterances.
EXIT_SUBSTRINGS = (
    "im done", "i am done", "thats all", "that is all",
    "thats enough", "that is enough", "shut it down", "shut down",
    "never mind", "thats it", "that is it", "im good", "i am good",
    "im finished", "i am finished", "were done", "we are done",
)


def looks_like_exit(cleaned: str) -> bool:
    """Pre-LLM exit detector — catches common variants without a model call.
    The LLM router is still the authority for ambiguous cases."""
    if not cleaned:
        return False
    if cleaned in EXIT_PHRASES:
        return True
    words = cleaned.split()
    # Only short utterances; long ones may genuinely be search queries that
    # happen to contain an exit word ("don't quit yet, find me a thriller").
    if len(words) > 6:
        return False
    if set(words) & EXIT_TOKENS:
        return True
    return any(sub in cleaned for sub in EXIT_SUBSTRINGS)

# Tokens stripped before fuzzy title matching.
TITLE_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "on", "in", "for", "with",
    "is", "it", "that", "this", "tell", "me", "about", "details", "detail",
    "movie", "movies", "film", "one", "stop", "wait", "actually", "no",
    "okay", "ok", "please", "what", "how", "when", "was", "did", "does",
    "has", "will", "released", "release", "releasing", "out", "yet",
    "already", "future", "come", "coming",
}

LEADING_FILLER = re.compile(
    r"^(?:stop|wait|actually|no|okay|ok|hey|um|uh|so|please)[,.\s]+",
    re.IGNORECASE,
)

# ============================================================================
# Voice copy
# ============================================================================

WELCOME = (
    "Hey! What movie are you in the mood for? "
    "Tell me a genre, a movie you like, or just say trending."
)

FILLERS = {
    "recommend": [
        "Got it, finding a few that fit.",
        "On it — let me check.",
        "Sure, looking through some options.",
        "Cool, let me see what's good.",
    ],
    "trending": [
        "Let me see what's trending right now.",
        "Checking what people are watching.",
        "On it — pulling up what's hot.",
    ],
    "best": [
        "Let me grab some of the top-rated picks.",
        "Looking up the highest-rated ones.",
        "On it — pulling the best of the best.",
    ],
    "like": [
        "Good pick — let me find some similar ones.",
        "Cool, looking for movies with that vibe.",
        "Got it, finding some in the same vein.",
    ],
    "details": [
        "Sure, let me tell you more about it.",
        "Alright, here's the rundown.",
        "Got it — let me share what I know.",
    ],
    "release": [
        "Let me check on that.",
        "Looking that up now.",
        "One sec, checking the release.",
    ],
    "rating": [
        "Let me check the rating.",
        "One sec, looking that up.",
    ],
    "watch": [
        "Let me see where it's streaming.",
        "Checking where you can watch it.",
    ],
    "more": [
        "Sure, more on the way.",
        "Got it, pulling a few more.",
        "On it — here's what else I've got.",
    ],
}

CONTINUE_PROMPTS_RICH = [
    "Want to hear more about one, see more picks, or try a different vibe?",
    "Tell me which one to dig into, ask for more, or name another genre.",
    "Curious about one of these, want more, or want to change direction?",
]

# Used only on the SECOND open-ended turn — keeps the conversation
# alive without sounding like a checkout clerk. From turn 3 onward,
# the loop listens silently (no prompt).
CONTINUE_PROMPTS_SHORT = [
    "Want to know more about one, or try a different genre?",
    "Tell me which one, or ask for more.",
    "Pick one to hear about, or change direction.",
]

EXIT_MESSAGES = [
    "Enjoy your movie — catch you later.",
    "Have a good one. Talk soon.",
    "Hope you find a good one. Take care.",
    "Alright, enjoy the show.",
]

CLARIFY_PROMPTS = [
    "What kind of movie are you in the mood for? You can name a genre, "
    "a movie you like, or just say trending.",
    "Tell me a bit more — what genre or vibe are you after?",
    "What sort of movie? Action, comedy, sci-fi, horror, or something "
    "specific you've got in mind?",
    "Got it. Any particular genre, mood, or movie you'd want something like?",
]

IDLE_WARNING = "Still around if you want another movie."

# ============================================================================
# Prompts
# ============================================================================

INTENT_PROMPT = """You are an intent classifier for a voice movie recommender.
The user is speaking — expect filler, mispronunciations, fragments.
Return ONLY a single line of JSON. No markdown fences.

INTENTS:
- recommend: user asks for movies by genre, mood, or general request.
  args: {{"query": str, "genres": [str], "year": str, "sort": "popular|trending|best"}}
- like: user names a movie and wants similar.
  args: {{"title": str}}
- details: user picks one option or asks about a specific movie by name.
  args: {{"movie_ref": str (ordinal, pronoun, or title)}}
- release: user asks when a movie comes out or was released.
  args: {{"movie_ref": str}}
- rating: user asks for a movie's rating or score.
  args: {{"movie_ref": str}}
- watch: user asks where to watch / stream a movie.
  args: {{"movie_ref": str}}
- more: user asks for more like these or more picks. args: {{}}
- summaries: user asks what current options are about, or to summarize. args: {{}}
- ask: user's request is VAGUE — no specific genre, mood, title, year, or movie
  reference. Use this whenever the input is essentially "find me a movie" or
  "play something" without anything actionable. The assistant will then ask a
  follow-up question instead of running a junk search.
  Examples that route to ask: "play a movie", "find me a movie", "looking for
  a movie", "looking for a movie to watch", "what should I watch", "tell me a
  movie", "I want to watch something", "find me something to watch",
  "recommend a movie" (with no genre/title).
  args: {{}}
- exit: user wants to END the movie recommender session. Recognize this BROADLY.
  Any standalone request to stop, quit, leave, or refuse further movies is exit.
  Examples that ARE exit:
    "goodbye", "bye", "bye for now", "alright bye", "ok I'm done",
    "yeah I'm good thanks", "that's all thanks", "that's enough", "nevermind",
    "thanks bye", "shut it down", "close it", "I am finished", "we're done here",
    "stop", "stop now", "stop please", "okay stop", "alright stop", "just stop",
    "I don't want any movie", "don't want a movie", "I don't want to watch",
    "no more movies", "no movie", "I'm not interested", "forget it".
  Do NOT classify as exit:
    - "stop, I want X" — that is recommend with query "X".
    - "no thanks, find something else" — that is recommend, not exit.
    - "stop the second one" / "stop that movie" — these reference a movie; route
      to details or watch as appropriate.
  args: {{}}

TMDB genres available: {genres}

EXAMPLES:
User: "comedy" -> {{"intent":"recommend","args":{{"query":"comedy","genres":["comedy"],"year":"","sort":"popular"}}}}
User: "sci-fi movies in 2020" -> {{"intent":"recommend","args":{{"query":"sci-fi movies in 2020","genres":["sci-fi"],"year":"2020","sort":"popular"}}}}
User: "trending movies" -> {{"intent":"recommend","args":{{"query":"","genres":[],"year":"","sort":"trending"}}}}
User: "best movies of all time" -> {{"intent":"recommend","args":{{"query":"","genres":[],"year":"","sort":"best"}}}}
User: "movies like Inception" -> {{"intent":"like","args":{{"title":"Inception"}}}}
User: "tell me about The Dark Knight" -> {{"intent":"details","args":{{"movie_ref":"The Dark Knight"}}}}
User: "the second one" -> {{"intent":"details","args":{{"movie_ref":"second"}}}}
User: "is it out yet" -> {{"intent":"release","args":{{"movie_ref":"it"}}}}
User: "what's that rated" -> {{"intent":"rating","args":{{"movie_ref":"that"}}}}
User: "where can I watch it" -> {{"intent":"watch","args":{{"movie_ref":"it"}}}}
User: "more" -> {{"intent":"more","args":{{}}}}
User: "what are these about" -> {{"intent":"summaries","args":{{}}}}
User: "play a movie" -> {{"intent":"ask","args":{{}}}}
User: "looking for a movie to watch" -> {{"intent":"ask","args":{{}}}}
User: "find me something" -> {{"intent":"ask","args":{{}}}}
User: "what should I watch" -> {{"intent":"ask","args":{{}}}}
User: "recommend a movie" -> {{"intent":"ask","args":{{}}}}
User: "goodbye" -> {{"intent":"exit","args":{{}}}}
User: "alright bye for now" -> {{"intent":"exit","args":{{}}}}
User: "ok I'm done thanks" -> {{"intent":"exit","args":{{}}}}
User: "yeah that's all thanks" -> {{"intent":"exit","args":{{}}}}
User: "nevermind close it" -> {{"intent":"exit","args":{{}}}}
User: "stop" -> {{"intent":"exit","args":{{}}}}
User: "okay stop" -> {{"intent":"exit","args":{{}}}}
User: "stop now" -> {{"intent":"exit","args":{{}}}}
User: "I don't want any movie" -> {{"intent":"exit","args":{{}}}}
User: "no more movies" -> {{"intent":"exit","args":{{}}}}

RULES:
- JSON only. No markdown, no explanation.
- Standalone "stop" / "stop now" / "okay stop" / "don't want any movie" = exit.
- "stop, I want comedy" is recommend with query "comedy", not exit.
- For pronouns ("it", "that") in release/rating/watch/details, use that pronoun
  as movie_ref — the handler will resolve it against the focused movie.

CURRENT OPTIONS:
{options}

FOCUSED MOVIE: {focused}

RECENT CONVERSATION:
{history}

User said: "{text}"

JSON:"""

ERROR_PROMPT = """Summarize this error into one short, friendly spoken sentence
for a voice user. No technical details, no URLs, no internal info.
Plain conversational English. Under fifteen words.

Error: {error}"""

# ============================================================================
# Pure helpers
# ============================================================================

def normalize(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def clean_voice(text: str) -> str:
    cleaned = re.sub(r"(?:https?://|www\.)\S+", "", text or "")
    cleaned = re.sub(r"`{1,3}|\*{1,2}|#{1,6}", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def strip_json_fences(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract_year(text: str) -> str:
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text or "")
    if not m:
        return ""
    y = int(m.group(1))
    return str(y) if 1900 <= y <= 2099 else ""


def strip_year(text: str) -> str:
    c = re.sub(
        r"\b(?:from|in|released in|year)\s+(?:19\d{2}|20\d{2})\b",
        " ",
        text or "",
        flags=re.I,
    )
    c = re.sub(r"\b(?:19\d{2}|20\d{2})\b", " ", c)
    return re.sub(r"\s+", " ", c).strip()


def first_sentence(text: str) -> str:
    s = re.split(r"(?<=[.!?])\s+", (text or "").strip(), maxsplit=1)[0]
    if not s:
        return ""
    return s if s.endswith((".", "!", "?")) else s + "."


def short_summary(text: str, max_words: int = 22) -> str:
    words = first_sentence(text).split()
    if not words:
        return ""
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


def release_year(movie: dict) -> str:
    d = movie.get("release_date") or ""
    return d[:4] if len(d) >= 4 else ""


def spoken_date(date_text: str) -> str:
    try:
        d = datetime.datetime.strptime(date_text or "", "%Y-%m-%d").date()
        return f"{d.strftime('%B')} {d.day}, {d.year}"
    except ValueError:
        return date_text or "an unknown date"


def format_history(history: list[dict]) -> str:
    if not history:
        return "(none)"
    rows = history[-HISTORY_TURNS:]
    return "\n".join(
        f"{row.get('role', 'user')}: {row.get('content', '')}" for row in rows
    )


# ============================================================================
# Capability class
# ============================================================================

class MovieRecommenderCapability(MatchingCapability):
    """Voice-first movie recommender — podcast-style flow."""

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    api_key: str = ""
    api_auth_failed: bool = False
    history: list = None
    current_movies: list = None
    shown_movies: list = None
    seen_titles: dict = None
    focused_movie: dict = None
    last_search: dict = None
    last_total_pages: int = 1
    cursor: int = 0
    shown_ids: set = None
    continue_count: int = 0
    last_continue: str = ""
    idle_warned: bool = False

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # ------------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------------

    def _log(self, msg: str):
        try:
            self.worker.editor_logging_handler.info(f"[MovieV4] {msg}")
        except Exception:
            pass

    def _err(self, msg: str):
        try:
            self.worker.editor_logging_handler.error(f"[MovieV4] {msg}")
        except Exception:
            pass

    # ------------------------------------------------------------------------
    # Speech helpers
    # ------------------------------------------------------------------------

    async def _speak(self, text: str):
        text = clean_voice(text)
        if text:
            self._add_history("assistant", text)
            await self.capability_worker.speak(text)

    async def _ask(self, prompt: str) -> str:
        """Speak a prompt and listen for the user's reply. Use this only when
        speaking a question right before listening — it is the SDK's combined
        speak+listen call."""
        prompt = clean_voice(prompt)
        if prompt:
            self._add_history("assistant", prompt)
            self.last_continue = prompt
        return await self.capability_worker.run_io_loop(prompt)

    async def _listen(self) -> str:
        """Listen for the next user utterance without speaking anything first.
        This is the documented SDK pattern for "listen only" — calling
        `run_io_loop("")` instead can drain buffered STT and yield multiple
        transcriptions stitched together."""
        return await self.capability_worker.user_response()

    def _add_history(self, role: str, content: str):
        if content:
            self.history.append({"role": role, "content": content})
            self.history = self.history[-HISTORY_TURNS:]

    # ------------------------------------------------------------------------
    # LLM passes
    # ------------------------------------------------------------------------

    async def _llm_call(self, prompt: str) -> str:
        try:
            raw = await asyncio.to_thread(
                self.capability_worker.text_to_text_response, prompt
            )
            return raw or ""
        except Exception as exc:
            self._err(f"LLM call failed: {exc}")
            return ""

    async def _summarize_error(self, exc: Exception) -> str:
        try:
            raw = await self._llm_call(ERROR_PROMPT.format(error=str(exc)))
            cleaned = clean_voice(raw)
            return cleaned or "Something went wrong."
        except Exception:
            return "Something went wrong."

    # ------------------------------------------------------------------------
    # API key + TMDB
    # ------------------------------------------------------------------------

    def _api_key(self) -> str:
        try:
            v = self.capability_worker.get_api_keys(TMDB_API_KEY_NAME)
            return v.strip() if isinstance(v, str) else ""
        except Exception as exc:
            self._err(f"API key lookup failed: {exc}")
            return ""

    async def _tmdb_get(self, path: str, params: Optional[dict] = None) -> dict:
        try:
            request_params = dict(params or {})
            request_params["api_key"] = self.api_key
            request_params.setdefault("language", "en-US")
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"{TMDB_BASE_URL}{path}",
                    headers={"accept": "application/json"},
                    params=request_params,
                )
            if resp.status_code == 401:
                self.api_auth_failed = True
                await self._speak(
                    "TMDB rejected the API key. Check it in OpenHome settings "
                    "under tmdb api key."
                )
                return {}
            if resp.status_code == 403:
                self.api_auth_failed = True
                await self._speak(
                    "TMDB would not authorize this API key. "
                    "Check your TMDB account permissions."
                )
                return {}
            if resp.status_code != 200:
                self._err(f"TMDB error {resp.status_code}: {resp.text[:200]}")
                return {}
            return resp.json()
        except Exception as exc:
            self._err(f"TMDB request failed: {exc}")
            return {}

    def _clean_movies(self, movies: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        seen: set = set()
        for m in movies:
            mid = m.get("id")
            title = m.get("title") or m.get("name")
            if not mid or not title or mid in seen:
                continue
            m["title"] = title
            cleaned.append(m)
            seen.add(mid)
        return cleaned

    def _page(self, page: Any) -> int:
        try:
            return max(1, min(int(page), MAX_TMDB_PAGES))
        except (TypeError, ValueError):
            return 1

    def _genre_ids(self, values: list[str]) -> list[str]:
        matched: list[str] = []
        for v in values or []:
            low = (v or "").lower()
            words = set(normalize(v).split())
            for name, gid in GENRE_IDS.items():
                is_phrase = " " in name or "-" in name
                if (is_phrase and name in low) or (not is_phrase and name in words):
                    s = str(gid)
                    if s not in matched:
                        matched.append(s)
        return matched

    async def _discover(self, args: dict, page: int = 1) -> dict:
        """Run the right TMDB discovery query for the given args."""
        sort = args.get("sort", "popular") or "popular"
        if sort == "trending":
            return await self._tmdb_get("/trending/movie/week", {"page": page})

        query = args.get("query", "") or ""
        year = args.get("year", "") or extract_year(query)
        genres = self._genre_ids((args.get("genres") or []) + [query])

        params: dict = {"page": page, "include_adult": "false"}

        if sort == "best":
            params["sort_by"] = "vote_average.desc"
            params["vote_count.gte"] = 1000
            if year:
                params["primary_release_year"] = year
            if genres:
                params["with_genres"] = ",".join(genres)
            return await self._tmdb_get("/discover/movie", params)

        if genres:
            params["with_genres"] = ",".join(genres)
            params["sort_by"] = "popularity.desc"
            params["vote_count.gte"] = 80
            if year:
                params["primary_release_year"] = year
            qwords = normalize(query).split()
            if "new" in qwords or "latest" in qwords or "recent" in qwords:
                params["sort_by"] = "primary_release_date.desc"
                params["vote_count.gte"] = 20
            return await self._tmdb_get("/discover/movie", params)

        # No genre — fall back to a search query
        search_params: dict = {"query": strip_year(query) or query, "page": page}
        if year:
            search_params["year"] = year
        return await self._tmdb_get("/search/movie", search_params)

    async def _search_movie(self, title: str) -> Optional[dict]:
        title = clean_voice(title)
        if not title:
            return None
        params: dict = {"query": strip_year(title) or title, "page": 1}
        y = extract_year(title)
        if y:
            params["year"] = y
        data = await self._tmdb_get("/search/movie", params)
        results = self._clean_movies(data.get("results", []) if data else [])
        return results[0] if results else None

    async def _similar_or_recommended(self, movie_id: int, page: int = 1) -> list[dict]:
        for endpoint in ("recommendations", "similar"):
            data = await self._tmdb_get(f"/movie/{movie_id}/{endpoint}", {"page": page})
            results = self._clean_movies(data.get("results", []) if data else [])
            if results:
                return results
        return []

    async def _movie_details(self, movie_id: int) -> dict:
        return await self._tmdb_get(f"/movie/{movie_id}", {}) or {}

    async def _watch_providers(self, movie_id: int) -> list[str]:
        """Return streaming providers (US region) for a movie."""
        data = await self._tmdb_get(f"/movie/{movie_id}/watch/providers", {})
        results = data.get("results", {}) if data else {}
        region = results.get("US", {})
        providers: list[str] = []
        for kind in ("flatrate", "free", "ads"):
            for p in region.get(kind, []) or []:
                name = p.get("provider_name")
                if name and name not in providers:
                    providers.append(name)
        return providers

    # ------------------------------------------------------------------------
    # Movie ref resolution
    # ------------------------------------------------------------------------

    def _looks_like_title(self, text: str) -> bool:
        cleaned = LEADING_FILLER.sub("", text or "")
        tokens = [
            t for t in normalize(cleaned).split()
            if len(t) >= 4 and t not in TITLE_STOPWORDS
        ]
        return bool(tokens)

    def _resolve_movie_ref(self, text: str) -> Optional[dict]:
        """Resolve a textual reference to a movie in session state."""
        if not text:
            return None
        text = LEADING_FILLER.sub("", text)
        cleaned = normalize(text)

        # Pronouns → focused
        if cleaned in {"it", "that", "this", "that one", "this one"}:
            return self.focused_movie or (
                self.shown_movies[0] if self.shown_movies else None
            )

        # Ordinals
        ordinals = {
            "first": 0, "1": 0, "one": 0,
            "second": 1, "2": 1, "two": 1,
            "third": 2, "3": 2, "three": 2,
            "fourth": 3, "4": 3, "four": 3,
            "fifth": 4, "5": 4, "five": 4,
        }
        options = self.shown_movies or self.current_movies
        for word, idx in ordinals.items():
            if re.search(rf"\b{word}\b", cleaned) and idx < len(options):
                return options[idx]

        # Substring / fuzzy across pools
        cleaned = " ".join(t for t in cleaned.split() if t not in TITLE_STOPWORDS)
        if not cleaned:
            return None
        pools = [
            self.shown_movies,
            self.current_movies,
            list(self.seen_titles.values()),
        ]
        for pool in pools:
            for movie in pool:
                title = normalize(movie.get("title") or "")
                if title and (title in cleaned or cleaned in title):
                    return movie
            m = self._fuzzy_movie(cleaned, pool)
            if m:
                return m
        return None

    def _fuzzy_movie(self, cleaned: str, movies: list[dict]) -> Optional[dict]:
        user_tokens = [
            t for t in cleaned.split()
            if len(t) >= 4 and t not in TITLE_STOPWORDS
        ]
        if not user_tokens:
            return None
        best = None
        best_score = 0.0
        for movie in movies:
            title = normalize(movie.get("title") or "")
            title_tokens = [t for t in title.split() if len(t) >= 3]
            if not title_tokens:
                continue
            token_matches = sum(
                1 for ut in user_tokens
                if any(ut in tt or tt in ut for tt in title_tokens)
                or any(
                    difflib.SequenceMatcher(None, ut, tt).ratio() >= 0.9
                    for tt in title_tokens
                )
            )
            need = 2 if len(user_tokens) >= 2 else 1
            if token_matches < need:
                continue
            phrase = difflib.SequenceMatcher(None, cleaned, title).ratio()
            if phrase < 0.45 and token_matches < len(user_tokens):
                continue
            score = phrase
            for ut in user_tokens:
                for tt in title_tokens:
                    score = max(score, difflib.SequenceMatcher(None, ut, tt).ratio())
            if score > best_score:
                best_score = score
                best = movie
        return best if best_score >= 0.85 else None

    async def _resolve_or_search(self, ref: str, search_first: bool = False) -> Optional[dict]:
        """Resolve a movie ref. If `search_first`, hit TMDB before session pools
        — better when the user says a full title not in current options."""
        ref = clean_voice(ref or "")
        if not ref:
            return None

        if normalize(ref) in {"it", "that", "this", "that one", "this one"}:
            return self.focused_movie or (
                self.shown_movies[0] if self.shown_movies else None
            )

        if search_first and self._looks_like_title(ref):
            m = await self._search_movie(ref)
            if m:
                return m

        m = self._resolve_movie_ref(ref)
        if m:
            return m

        if self._looks_like_title(ref):
            return await self._search_movie(ref)
        return None

    # ------------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------------

    def _reset_results(self, action: str, args: dict, movies: list[dict]):
        self.current_movies = []
        self.shown_movies = []
        self.shown_ids = set()
        self.cursor = 0
        self._append_movies(movies)
        self.last_search = {
            "action": action,
            "args": dict(args),
            "page": self._page(args.get("page") or 1),
        }

    def _append_movies(self, movies: list[dict]):
        existing_ids = {m.get("id") for m in self.current_movies if m.get("id")}
        existing_titles = {
            normalize(m.get("title") or "") for m in self.current_movies
        }
        for m in movies:
            title = m.get("title") or m.get("name")
            if not title:
                continue
            m["title"] = title
            mid = m.get("id")
            nt = normalize(title)
            if (mid and mid not in existing_ids) or nt not in existing_titles:
                self.current_movies.append(m)
                if mid:
                    existing_ids.add(mid)
                existing_titles.add(nt)
            self.seen_titles[nt] = m

    def _next_unshown(self, count: int) -> list[dict]:
        picks: list[dict] = []
        while self.cursor < len(self.current_movies) and len(picks) < count:
            m = self.current_movies[self.cursor]
            self.cursor += 1
            mid = m.get("id")
            if mid and mid in self.shown_ids:
                continue
            if mid:
                self.shown_ids.add(mid)
            picks.append(m)
        self.shown_movies = picks
        return picks

    def _total_pages(self, data: Optional[dict]) -> int:
        if not data:
            return 1
        try:
            return min(int(data.get("total_pages") or 1), MAX_TMDB_PAGES)
        except (TypeError, ValueError):
            return 1

    # ------------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------------

    async def classify_intent(self, text: str) -> dict:
        options_str = "(none)"
        if self.shown_movies or self.current_movies:
            opts = self.shown_movies or self.current_movies[:5]
            options_str = "\n".join(
                f"{i+1}. {m.get('title')}" for i, m in enumerate(opts)
            )
        focused_str = (
            self.focused_movie.get("title") if self.focused_movie else "(none)"
        )
        prompt = INTENT_PROMPT.format(
            genres=GENRE_LIST,
            options=options_str,
            focused=focused_str,
            history=format_history(self.history),
            text=text,
        )
        raw = await self._llm_call(prompt)
        try:
            data = json.loads(strip_json_fences(raw))
            self._log(f"Intent raw: {raw[:200]}")
            return data
        except Exception as exc:
            self._err(f"Intent parse failed: {exc} (raw: {raw[:200]})")
            return {"intent": "recommend", "args": {"query": text}}

    # ------------------------------------------------------------------------
    # Voice presentation
    # ------------------------------------------------------------------------

    async def _speak_recommendations(self, movies: list[dict], lead: str = ""):
        if not movies:
            await self._speak("I didn't find any. Want to try a different vibe?")
            return
        parts: list[str] = []
        if lead:
            parts.append(lead)
        for movie in movies[:RECOMMEND_COUNT]:
            title = movie.get("title", "Unknown")
            year = release_year(movie)
            rating = float(movie.get("vote_average") or 0)
            if year and rating:
                parts.append(f"{title} from {year}, rated {rating:.1f}.")
            elif year:
                parts.append(f"{title} from {year}.")
            else:
                parts.append(f"{title}.")
        await self._speak(" ".join(parts))

    async def _speak_detail(self, movie: dict):
        title = movie.get("title", "Unknown title")
        rating = float(movie.get("vote_average") or 0)
        year = release_year(movie)
        overview = first_sentence(movie.get("overview") or "")
        bits: list[str] = [title]
        if year:
            bits.append(f"from {year}")
        if rating:
            bits.append(f"rated {rating:.1f}")
        head = ", ".join(bits) + "."
        line = head if not overview else f"{head} {overview}"
        await self._speak(line)

    # ------------------------------------------------------------------------
    # Continue prompts
    # ------------------------------------------------------------------------

    def _next_continue_prompt(self) -> str:
        """Pick a continue prompt that gets shorter and then silent over turns:
            turn 1 → full rich prompt with all options
            turn 2 → short directional prompt
            turn 3+ → "" (caller listens silently — no nagging)
        """
        self.continue_count += 1
        if self.continue_count == 1:
            pool = CONTINUE_PROMPTS_RICH
        elif self.continue_count == 2:
            pool = CONTINUE_PROMPTS_SHORT
        else:
            return ""
        choices = [p for p in pool if p != self.last_continue]
        return random.choice(choices or pool)

    # ------------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------------

    async def _handle_recommend(self, args: dict) -> str:
        sort = args.get("sort", "popular") or "popular"
        filler_key = (
            "trending" if sort == "trending"
            else "best" if sort == "best"
            else "recommend"
        )
        await self._speak(random.choice(FILLERS[filler_key]))

        data = await self._discover(args, page=1)
        movies = self._clean_movies(data.get("results", []) if data else [])
        self.last_total_pages = self._total_pages(data)

        if not movies:
            # Skip the misleading "couldn't find anything" if TMDB itself
            # told the user the API key was rejected.
            if not self.api_auth_failed:
                await self._speak(
                    "I couldn't find anything that fits. Want to try a different genre or year?"
                )
            return "another"

        self._reset_results("recommend", {**args, "page": 1}, movies)
        self.focused_movie = None
        picks = self._next_unshown(RECOMMEND_COUNT)

        lead_map = {
            "trending": "Here's what's trending right now.",
            "best": "Here are some of the top-rated picks.",
            "popular": "Here are a few that fit.",
        }
        lead = lead_map.get(sort, "Here are a few that fit.")
        await self._speak_recommendations(picks, lead=lead)
        return "shown"

    async def _handle_like(self, args: dict) -> str:
        title = args.get("title") or ""
        if not title and self.focused_movie:
            title = self.focused_movie.get("title", "")
        if not title:
            await self._speak("Which movie should I find similar picks for?")
            return "another"

        await self._speak(random.choice(FILLERS["like"]))

        base = await self._search_movie(title)
        if not base:
            await self._speak(f"I couldn't find {title}. Want to try a different title?")
            return "another"

        results = await self._similar_or_recommended(base.get("id"))
        if not results:
            await self._speak(
                f"I couldn't find anything quite like {base.get('title')}. "
                f"Want to try a genre instead?"
            )
            return "another"

        self._append_movies([base])
        self.focused_movie = base
        self._reset_results(
            "like", {"title": base.get("title"), "page": 1}, results
        )
        picks = self._next_unshown(RECOMMEND_COUNT)
        await self._speak_recommendations(
            picks, lead=f"Movies like {base.get('title')}:"
        )
        return "shown"

    async def _handle_details(self, args: dict) -> str:
        ref = args.get("movie_ref") or ""
        movie = await self._resolve_or_search(ref)
        if not movie:
            await self._speak(
                "Which one would you like to know more about? "
                "You can say the title or say the second one."
            )
            return "another"

        await self._speak(random.choice(FILLERS["details"]))

        # Enrich with full TMDB details
        mid = movie.get("id")
        if mid:
            full = await self._movie_details(mid)
            if full:
                full["title"] = full.get("title") or movie.get("title")
                movie = full

        self.focused_movie = movie
        self._append_movies([movie])
        await self._speak_detail(movie)
        return "answered"

    async def _handle_release(self, args: dict) -> str:
        ref = args.get("movie_ref") or ""
        movie = await self._resolve_or_search(ref, search_first=True)
        if not movie:
            await self._speak("Which movie's release are you asking about?")
            return "another"

        await self._speak(random.choice(FILLERS["release"]))
        self.focused_movie = movie
        self._append_movies([movie])

        title = movie.get("title") or "That movie"
        rd = movie.get("release_date") or ""
        if not rd:
            await self._speak(f"{title}'s release date is not listed.")
            return "answered_quiet"
        try:
            day = datetime.datetime.strptime(rd, "%Y-%m-%d").date()
        except ValueError:
            await self._speak(f"{title}'s listed release date is {rd}.")
            return "answered_quiet"

        today = datetime.date.today()
        if day <= today:
            line = f"{title} was released on {spoken_date(rd)}."
        else:
            delta_days = (day - today).days
            if delta_days <= 14:
                line = (
                    f"{title} comes out on {spoken_date(rd)}, "
                    f"about {delta_days} days from now."
                )
            elif delta_days <= 90:
                weeks = max(1, delta_days // 7)
                line = (
                    f"{title} comes out on {spoken_date(rd)}, "
                    f"about {weeks} weeks from now."
                )
            else:
                line = f"{title} is scheduled for {spoken_date(rd)}."
        await self._speak(line)
        return "answered_quiet"

    async def _handle_rating(self, args: dict) -> str:
        ref = args.get("movie_ref") or ""
        movie = await self._resolve_or_search(ref, search_first=True)
        if not movie:
            await self._speak("Which movie's rating are you asking about?")
            return "another"

        await self._speak(random.choice(FILLERS["rating"]))
        self.focused_movie = movie
        self._append_movies([movie])

        title = movie.get("title") or "That movie"
        rating = float(movie.get("vote_average") or 0)
        year = release_year(movie)
        if rating:
            qualitative = (
                "excellent" if rating >= 8 else
                "solid" if rating >= 7 else
                "decent" if rating >= 6 else
                "mixed" if rating >= 5 else
                "rough"
            )
            line = f"{title} is rated {rating:.1f} out of ten — {qualitative}."
            if year:
                line += f" Released in {year}."
        else:
            line = f"{title} does not have a rating listed."
        await self._speak(line)
        return "answered_quiet"

    async def _handle_watch(self, args: dict) -> str:
        ref = args.get("movie_ref") or ""
        movie = await self._resolve_or_search(ref, search_first=True)
        if not movie:
            await self._speak("Which movie are you trying to watch?")
            return "another"

        await self._speak(random.choice(FILLERS["watch"]))
        self.focused_movie = movie
        self._append_movies([movie])

        title = movie.get("title") or "That movie"
        try:
            providers = await self._watch_providers(movie.get("id"))
        except Exception as exc:
            self._err(f"Watch providers failed: {exc}")
            providers = []

        if not providers:
            await self._speak(
                f"I couldn't find any streaming info for {title}."
            )
            return "answered_quiet"

        if len(providers) == 1:
            line = f"{title} is on {providers[0]}."
        elif len(providers) == 2:
            line = f"{title} is on {providers[0]} and {providers[1]}."
        else:
            line = (
                f"{title} is on {', '.join(providers[:-1])}, "
                f"and {providers[-1]}."
            )
        await self._speak(line)
        return "answered_quiet"

    async def _handle_more(self) -> str:
        if not self.last_search:
            await self._speak(
                "What genre or movie should I use for more recommendations?"
            )
            return "another"

        await self._speak(random.choice(FILLERS["more"]))

        picks: list[dict] = []
        while len(picks) < RECOMMEND_COUNT:
            picks.extend(self._next_unshown(RECOMMEND_COUNT - len(picks)))
            if (
                len(picks) >= RECOMMEND_COUNT
                or self.last_search["page"] >= self.last_total_pages
            ):
                break
            self.last_search["page"] += 1
            more = await self._fetch_more_page(self.last_search["page"])
            if not more:
                break
            self._append_movies(more)

        if not picks:
            await self._speak(
                "I'm out of fresh picks for that vibe. Want to try a new genre?"
            )
            return "another"

        await self._speak_recommendations(picks, lead="Here are a few more.")
        return "shown"

    async def _fetch_more_page(self, page: int) -> list[dict]:
        action = self.last_search.get("action")
        args = dict(self.last_search.get("args") or {})
        args["page"] = page

        if action == "like":
            base = await self._search_movie(args.get("title") or "")
            if not base:
                return []
            return await self._similar_or_recommended(base.get("id"), page)

        # Default: recommend / search
        data = await self._discover(args, page=page)
        self.last_total_pages = self._total_pages(data)
        return self._clean_movies(data.get("results", []) if data else [])

    async def _handle_ask(self) -> str:
        """User input was too vague to act on (e.g. 'play a movie',
        'looking for a movie'). Speak a clarifying question and listen for
        a real request next turn."""
        prompt = random.choice(CLARIFY_PROMPTS)
        await self._speak(prompt)
        return "another"

    async def _handle_summaries(self) -> str:
        opts = (
            self.shown_movies or self.current_movies[:RECOMMEND_COUNT]
        )[:RECOMMEND_COUNT]
        if not opts:
            await self._speak(
                "Search for some movies first, then I can summarize the picks."
            )
            return "another"
        lines: list[str] = []
        for m in opts:
            title = m.get("title") or "Unknown"
            ov = short_summary(m.get("overview") or "")
            if ov:
                lines.append(f"{title}: {ov}")
            else:
                lines.append(f"{title} does not have a summary listed.")
        await self._speak(" ".join(lines))
        return "answered"

    # ------------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------------

    async def run(self):
        try:
            # Initialize Pydantic-tracked fields
            self.api_auth_failed = False
            self.history = []
            self.current_movies = []
            self.shown_movies = []
            self.seen_titles = {}
            self.focused_movie = None
            self.last_search = {}
            self.last_total_pages = 1
            self.cursor = 0
            self.shown_ids = set()
            self.continue_count = 0
            self.last_continue = ""
            self.idle_warned = False

            self._log("Ability started")

            self.api_key = self._api_key()
            if not self.api_key:
                await self._speak(
                    "I need your TMDB API key before I can recommend movies. "
                    "Add it in OpenHome settings under tmdb api key."
                )
                return

            # Read trigger transcription
            trigger = (
                await self.capability_worker.wait_for_complete_transcription() or ""
            ).strip()
            self._log(f"Trigger: {trigger!r}")

            # If trigger is substantive, skip welcome and use it directly.
            # Otherwise speak welcome and wait for the real first input.
            stripped = normalize(trigger)
            if trigger and stripped not in BARE_TRIGGERS:
                user_input = trigger
            else:
                await self._speak(WELCOME)
                user_input = await self._listen()

            first_turn = True
            idle_count = 0

            while True:
                # Idle handling
                if not user_input or not user_input.strip():
                    idle_count += 1
                    if self.idle_warned:
                        break
                    if idle_count >= MAX_IDLE_TURNS:
                        self.idle_warned = True
                        user_input = await self._ask(IDLE_WARNING)
                    else:
                        user_input = await self._listen()
                    continue

                idle_count = 0
                self.idle_warned = False
                cleaned = normalize(user_input)

                # Pre-LLM guards
                if first_turn and looks_like_exit(cleaned):
                    self._log(f"First-turn exit ignored: {user_input!r}")
                    user_input = await self._listen()
                    continue

                if looks_like_exit(cleaned):
                    await self._speak(random.choice(EXIT_MESSAGES))
                    break

                # Bare "no" / "nope" / "no thanks" answered to a continue
                # prompt = user is done. Only treat as exit AFTER a successful
                # turn (continue_count > 0) so we don't accidentally bail on
                # a "no" reply to a clarifying question.
                if cleaned in BARE_DECLINES and self.continue_count > 0:
                    self._log(f"Bare decline after continue prompt: {user_input!r}")
                    await self._speak(random.choice(EXIT_MESSAGES))
                    break

                first_turn = False
                self._add_history("user", user_input)

                # Classify
                intent_data = await self.classify_intent(user_input)
                intent = (intent_data.get("intent") or "").lower()
                args = (
                    intent_data.get("args")
                    if isinstance(intent_data.get("args"), dict)
                    else {}
                )
                self._log(f"Intent: {intent} args={args}")

                # Route
                if intent == "exit":
                    await self._speak(random.choice(EXIT_MESSAGES))
                    break

                try:
                    if intent == "recommend":
                        result = await self._handle_recommend(args)
                    elif intent == "like":
                        result = await self._handle_like(args)
                    elif intent == "details":
                        result = await self._handle_details(args)
                    elif intent == "release":
                        result = await self._handle_release(args)
                    elif intent == "rating":
                        result = await self._handle_rating(args)
                    elif intent == "watch":
                        result = await self._handle_watch(args)
                    elif intent == "more":
                        result = await self._handle_more()
                    elif intent == "summaries":
                        result = await self._handle_summaries()
                    elif intent == "ask":
                        result = await self._handle_ask()
                    else:
                        # Unknown intent → treat as recommend with raw text
                        result = await self._handle_recommend({"query": user_input})
                except Exception as exc:
                    self._err(f"Handler error: {exc}")
                    spoken = await self._summarize_error(exc)
                    await self._speak(spoken)
                    result = "another"

                if self.api_auth_failed:
                    break

                # After-action routing
                if result in ("shown", "answered"):
                    # Open-ended turns (recommendations, details) — invite
                    # next move on turns 1-2, then taper to silent listening
                    # so it doesn't feel like a checkout clerk.
                    prompt = self._next_continue_prompt()
                    if prompt:
                        user_input = await self._ask(prompt)
                    else:
                        user_input = await self._listen()
                elif result == "answered_quiet":
                    # Factual one-shot (release / rating / watch) — listen
                    # silently so back-to-back fact queries feel natural.
                    user_input = await self._listen()
                elif result == "exit":
                    await self._speak(random.choice(EXIT_MESSAGES))
                    break
                else:  # "another" or anything else
                    user_input = await self._listen()

        except Exception as exc:
            self._err(f"Unhandled error: {exc}")
            try:
                spoken = await self._summarize_error(exc)
                await self._speak(spoken)
            except Exception:
                pass
        finally:
            self._log("Ability ended")
            try:
                self.capability_worker.resume_normal_flow()
            except Exception:
                pass
