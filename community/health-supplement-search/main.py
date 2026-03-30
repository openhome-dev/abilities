import asyncio
import re

import httpx

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# HEALTH SUPPLEMENT SEARCH
# Voice-driven semantic search over 100 curated health supplement products.
# Weaviate: uses built-in Snowflake Arctic embeddings (no Jina key needed).
# Qdrant:   uses Jina AI embeddings (free tier, requires JINA_API_KEY).
# Falls back to Serper web search when a product is not found in the local DB.
#
# SETUP: Fill in your keys below, then upload to OpenHome.
# Setup script: github.com/megz2020/abilities/tree/feat/health-supplement-search-setup
# =============================================================================

# -----------------------------------------------------------------------------
# CONFIGURATION — fill in before uploading
# -----------------------------------------------------------------------------

# Vector DB provider: "weaviate" or "qdrant"
VECTOR_DB_PROVIDER = "weaviate"

# Weaviate — embeddings are built-in (no Jina key needed)
WEAVIATE_URL = ""  # e.g. "https://xxx.weaviate.cloud"
WEAVIATE_API_KEY = ""
WEAVIATE_CLASS = "Supplement"

# Qdrant — requires Jina for embeddings
QDRANT_URL = ""  # e.g. "https://xxx.qdrant.io:6333"
QDRANT_API_KEY = ""
QDRANT_COLLECTION = "supplements"
JINA_API_KEY = ""  # only needed for Qdrant

# Serper web fallback (optional — leave empty to disable)
SERPER_API_KEY = ""  # free key at serper.dev (2,500 searches/month)

# Similarity threshold — compared against normalised distance (lower = better match).
# Weaviate cosine distance = 2 * (1 - certainty), so 0.80 ≈ certainty 0.60.
# Qdrant distance = 1 - cosine_score.
DISTANCE_THRESHOLD = 0.85

# -----------------------------------------------------------------------------

JINA_EMBED_URL = "https://api.jina.ai/v1/embeddings"
JINA_MODEL = "jina-embeddings-v3"
JINA_DIMENSIONS = 1024

SERPER_SEARCH_URL = "https://google.serper.dev/search"

MAX_RESULTS = 5
MAX_DISPLAY = 3
MAX_TURNS = 20
IDLE_REPROMPT = 2
IDLE_EXIT = 3
HTTP_TIMEOUT = 15
SUMMARY_TRUNCATE = 150
DESCRIPTION_TRUNCATE = 300
FIELD_TRUNCATE = 200
GUESS_MAX_LEN = 60


_ORDINAL_TO_IDX = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}

_HEALTH_KEYWORDS = {
    "supplement",
    "vitamin",
    "mineral",
    "herb",
    "herbal",
    "capsule",
    "tablet",
    "pill",
    "pain",
    "joint",
    "sleep",
    "energy",
    "immune",
    "anxiety",
    "stress",
    "inflammation",
    "digestion",
    "gut",
    "heart",
    "brain",
    "memory",
    "focus",
    "mood",
    "skin",
    "hair",
    "weight",
    "muscle",
    "bone",
    "liver",
    "kidney",
    "blood",
    "sugar",
    "pressure",
    "cholesterol",
    "fatigue",
    "cold",
    "flu",
    "allergy",
    "hormone",
    "thyroid",
    "iron",
    "calcium",
    "magnesium",
    "zinc",
    "omega",
    "probiotic",
    "prebiotic",
    "antioxidant",
    "collagen",
    "protein",
    "fiber",
    "detox",
    "cleanse",
    "health",
    "wellness",
    "remedy",
    "natural",
    "organic",
    "extract",
    "dose",
    "deficiency",
    "boost",
    "support",
    "headache",
    "migraine",
    "nausea",
    "insomnia",
    "depression",
    "acne",
    "eczema",
    "arthritis",
    "osteoporosis",
    "menopause",
    "testosterone",
    "estrogen",
    "libido",
    "cramp",
    "cramps",
    "swelling",
    "infection",
    "immunity",
    "stamina",
    "recover",
    "recovery",
    "healing",
    "aging",
    "antifungal",
    "antibacterial",
}

_DETAIL_TRIGGERS = (
    "detail",
    "tell me about",
    "tell me more",
    "more about",
    "ingredients",
    "reviews",
    "what's in",
    "what's it got",
    "yes",
    "yep",
    "yeah",
    "sure",
    "give me",
    "show me",
    "that one",
    "the first",
    "the second",
    "the third",
    "number",
    "about it",
    "about that",
    "first one",
    "second one",
    "third one",
    "go with",
    "pick that",
    "let's go with",
    "what about",
)


def _strip_llm_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text))
    return re.sub(r"\s+", " ", text).strip()


class HealthSupplementSearchCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    _last_results: list = None
    _last_source: str = ""
    _trigger_text: str = ""
    _just_showed_detail: bool = False

    # {{register capability}}

    # -------------------------------------------------------------------------
    # Config & logging
    # -------------------------------------------------------------------------

    def _config_ok(self) -> bool:
        if VECTOR_DB_PROVIDER == "weaviate":
            return bool(WEAVIATE_URL.strip() and WEAVIATE_API_KEY.strip())
        if VECTOR_DB_PROVIDER == "qdrant":
            return bool(
                QDRANT_URL.strip() and QDRANT_API_KEY.strip() and JINA_API_KEY.strip()
            )
        return False

    def _log(self, msg: str):
        try:
            self.worker.editor_logging_handler.info(f"[HealthSupSearch] {msg}")
        except Exception:
            pass

    def _err(self, msg: str):
        try:
            self.worker.editor_logging_handler.error(f"[HealthSupSearch] {msg}")
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Embedding (Qdrant only)
    # -------------------------------------------------------------------------

    async def _embed_query(self, text: str) -> list:
        if not JINA_API_KEY.strip():
            self._err("Jina API key missing")
            return []
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    JINA_EMBED_URL,
                    headers={
                        "Authorization": f"Bearer {JINA_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": JINA_MODEL,
                        "input": [text],
                        "dimensions": JINA_DIMENSIONS,
                    },
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]
        except Exception as exc:
            self._err(f"Jina embed error: {exc}")
            return []

    # -------------------------------------------------------------------------
    # Vector DB search
    # -------------------------------------------------------------------------

    async def _search_supplements(
        self, user_query: str, limit: int = MAX_RESULTS
    ) -> list:
        if VECTOR_DB_PROVIDER == "weaviate":
            return await self._weaviate_search(user_query, limit)
        vector = await self._embed_query(user_query)
        if not vector:
            return []
        return await self._qdrant_search(vector, limit)

    async def _qdrant_search(self, query_vector: list, limit: int) -> list:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{QDRANT_URL.rstrip('/')}/collections/{QDRANT_COLLECTION}/points/search",
                    headers={
                        "api-key": QDRANT_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={"vector": query_vector, "limit": limit, "with_payload": True},
                )
                resp.raise_for_status()
                hits = resp.json().get("result", [])
                return [
                    {
                        "payload": h.get("payload", {}),
                        "score": h.get("score", 0.0),
                        "distance": 1.0 - h.get("score", 0.0),
                    }
                    for h in hits
                ]
        except Exception as exc:
            self._err(f"Qdrant search error: {exc}")
            return []

    async def _weaviate_search(self, query_text: str, limit: int) -> list:
        safe_query = query_text.replace('"', "'")
        gql = (
            f"{{ Get {{ {WEAVIATE_CLASS}("
            f'nearText: {{concepts: ["{safe_query}"]}}, '
            f"limit: {limit}"
            f") {{ name brand rating description ingredients summary effects image reviews "
            f"_additional {{ certainty distance }} }} }} }}"
        )
        try:
            url = WEAVIATE_URL.rstrip("/")
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{url}/v1/graphql",
                    headers={
                        "Authorization": f"Bearer {WEAVIATE_API_KEY}",
                        "Content-Type": "application/json",
                        "X-Weaviate-Cluster-Url": url,
                    },
                    json={"query": gql},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("errors"):
                    self._err(f"Weaviate GraphQL errors: {data['errors']}")
                    return []
                hits = data.get("data", {}).get("Get", {}).get(WEAVIATE_CLASS, []) or []
                results = []
                for h in hits:
                    additional = h.get("_additional", {}) or {}
                    certainty = float(additional.get("certainty") or 0.0)
                    distance = float(additional.get("distance") or (1.0 - certainty))
                    payload = {k: v for k, v in h.items() if k != "_additional"}
                    results.append(
                        {"payload": payload, "score": certainty, "distance": distance}
                    )
                return results
        except Exception as exc:
            self._err(f"Weaviate search error: {exc}")
            return []

    # -------------------------------------------------------------------------
    # Serper web fallback
    # -------------------------------------------------------------------------

    async def _serper_search(self, query: str) -> list:
        if not SERPER_API_KEY.strip():
            return []
        search_q = f"{query} supplement benefits reviews site:examine.com OR site:iherb.com OR site:webmd.com"
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    SERPER_SEARCH_URL,
                    headers={
                        "X-API-KEY": SERPER_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={"q": search_q, "num": 5},
                )
                resp.raise_for_status()
                organic = resp.json().get("organic", [])
                return [
                    {
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                        "link": r.get("link", ""),
                    }
                    for r in organic
                ]
        except Exception as exc:
            self._err(f"Serper search error: {exc}")
            return []

    async def _search_with_fallback(self, user_query: str) -> tuple:
        db_results = await self._search_supplements(user_query)
        if db_results and db_results[0]["distance"] < DISTANCE_THRESHOLD:
            self._log(f"Curated match (distance: {db_results[0]['distance']:.3f})")
            return db_results, "curated"

        best = f"{db_results[0]['distance']:.3f}" if db_results else "N/A"
        self._log(f"No curated match (distance: {best}), trying Serper")
        web_results = await self._serper_search(user_query)
        if web_results:
            return web_results, "web"

        return [], "none"

    # -------------------------------------------------------------------------
    # LLM summarization
    # -------------------------------------------------------------------------

    async def _summarize_curated(self, user_query: str, results: list) -> str:
        products_text = ""
        for i, r in enumerate(results[:MAX_DISPLAY], 1):
            p = r["payload"]
            positives = []
            for part in str(p.get("effects", "")).split(","):
                part = part.strip().strip("[]'\"")
                if part.startswith("POSITIVE on "):
                    positives.append(part.replace("POSITIVE on ", "").replace("_", " "))
            effects_str = (
                ", ".join(positives[:MAX_DISPLAY]) if positives else "general wellness"
            )
            products_text += (
                f"{i}. {p.get('name', 'Unknown')} by {p.get('brand', 'Unknown')} "
                f"(rating: {p.get('rating', 0)}/5). "
                f"Key benefits: {effects_str}. "
                f"Summary: {p.get('summary', '')[:SUMMARY_TRUNCATE]}\n"
            )
        prompt = (
            f'The user asked: "{user_query}"\n\n'
            f"Top matching supplements from a curated database:\n{products_text}\n"
            "Give a SHORT voice response under 40 words. Mention the top 1-2 product names and ratings. "
            "Only mention benefits explicitly listed above — do NOT infer or add any. "
            "End with 'Want details on any of these?' "
            "Plain spoken English only. No lists, no formatting. Not medical advice."
        )
        return await asyncio.to_thread(
            self.capability_worker.text_to_text_response, prompt
        )

    async def _summarize_web(self, user_query: str, web_results: list) -> str:
        snippets = "".join(
            f"- {r.get('title', '')}: {r.get('snippet', '')}\n" for r in web_results[:4]
        )
        prompt = (
            f'The user asked about: "{user_query}"\n\n'
            f"Not found in curated database. Web results:\n{snippets}\n"
            "Give a SHORT voice response under 30 words. Mention this is from web results, not a curated database. "
            "Remind them to consult a healthcare provider. "
            "Plain spoken English only. No lists, no formatting, no URLs."
        )
        return await asyncio.to_thread(
            self.capability_worker.text_to_text_response, prompt
        )

    async def _detail_response(self, product_payload: dict) -> str:
        p = product_payload
        reviews = p.get("reviews", [])
        review_sample = (
            _strip_html(reviews[0])[:SUMMARY_TRUNCATE]
            if isinstance(reviews, list) and reviews
            else "No reviews available."
        )
        prompt = (
            f"Give a detailed voice summary of this supplement:\n"
            f"Name: {p.get('name', '')}\n"
            f"Brand: {p.get('brand', '')}\n"
            f"Rating: {p.get('rating', 0)}/5\n"
            f"Description: {p.get('description', '')[:DESCRIPTION_TRUNCATE]}\n"
            f"Ingredients: {p.get('ingredients', '')[:FIELD_TRUNCATE]}\n"
            f"Effects: {p.get('effects', '')[:FIELD_TRUNCATE]}\n"
            f"Sample review: {review_sample}\n"
            "Keep it under 40 words. Friendly, informative. "
            "Plain spoken English only. No lists, no formatting. Not medical advice."
        )
        return await asyncio.to_thread(
            self.capability_worker.text_to_text_response, prompt
        )

    # -------------------------------------------------------------------------
    # Intent detection
    # -------------------------------------------------------------------------

    def _wants_exit(self, user_input: str) -> bool:
        result = (
            self.capability_worker.text_to_text_response(
                f"Does this input mean the user wants to stop, leave, or say goodbye? "
                f"YES examples: 'bye', 'thanks', 'im done', 'all set', 'i am good', "
                f"'that is all', 'nothing else', 'ok thanks', 'cheers', 'sounds good thanks'. "
                f"NO examples: 'joint pain', 'headache relief', 'no I need something for sleep', "
                f"'tell me more about the first one'. "
                f"If the sentence contains a health question or supplement request, reply NO. "
                f'Input: "{user_input}"\nReply YES or NO only.'
            )
            .strip()
            .upper()
        )
        return result.startswith("YES")

    def _is_health_query(self, user_input: str) -> bool | None:
        """
        True  — valid health/supplement search request.
        None  — too short to judge (1–2 words); caller should ask for clarification.
        False — clearly off-topic.
        """
        stripped = user_input.strip().rstrip(".,!?")
        word_count = len(stripped.split())
        lowered = stripped.lower()
        has_keyword = any(kw in lowered for kw in _HEALTH_KEYWORDS)

        if word_count <= 2:
            return None if has_keyword else False

        # Always use LLM for longer inputs: STT can garble health words beyond
        # keyword recognition (e.g. "join te pin" for "joint pain").
        if has_keyword:
            prompt = (
                f"Does this input contain a meaningful health or supplement question, "
                f"even if the wording is imperfect or garbled by voice recognition?\n"
                f'Input: "{user_input}"\nReply YES or NO only.'
            )
        else:
            prompt = (
                f"Is this a question or request about health, wellness, or dietary supplements? "
                f"The input may be garbled by voice recognition — judge the likely intent.\n"
                f'Input: "{user_input}"\nReply YES or NO only.'
            )
        result = self.capability_worker.text_to_text_response(prompt).strip().upper()
        return result.startswith("YES")

    def _normalize_query(self, user_input: str) -> str:
        """
        Extract a clean health search phrase from raw (possibly garbled) STT input.
        e.g. "I need something for joint bean" -> "joint pain supplements"
        Returns the original input if normalization fails.
        """
        raw = self.capability_worker.text_to_text_response(
            f"Extract the core health or supplement search phrase from this voice input. "
            f"Fix any garbled words to their most likely health-related meaning. "
            f"Examples: 'I need something for joint bean' -> 'joint pain', "
            f"'search for something for headache' -> 'headache relief', "
            f"'find supplements for sleep iz shoes' -> 'sleep issues'. "
            f"Reply with ONLY the 2-5 word search phrase, nothing else.\n"
            f'Input: "{user_input}"'
        ).strip()
        cleaned = raw.strip("'\".")
        if not cleaned or len(cleaned) > GUESS_MAX_LEN:
            return user_input
        self._log(f"Normalized query: '{user_input[:GUESS_MAX_LEN]}' -> '{cleaned}'")
        return cleaned

    def _guess_health_intent(self, user_input: str) -> str:
        """
        Return the most likely health phrase the user meant (e.g. 'joint pain'),
        or an empty string if no health intent can be detected.
        Used to offer a clarification prompt when input is ambiguous or garbled.
        """
        raw = self.capability_worker.text_to_text_response(
            f"This voice input may be garbled by speech recognition. "
            f"If it seems like the user was trying to ask about a health concern or supplement, "
            f"reply with only the most likely 2-4 word health phrase they meant. "
            f"Examples: 'join te pin' -> 'joint pain', 'sleep iz shoes' -> 'sleep issues', "
            f"'some senga for gently being' -> 'joint pain'. "
            f"If you cannot detect any health intent, reply with exactly: NONE\n"
            f'Input: "{user_input}"'
        ).strip()
        if not raw or raw.upper() == "NONE" or len(raw) > GUESS_MAX_LEN:
            return ""
        return raw

    def _wants_detail(self, user_input: str, last_results: list) -> dict:
        if not last_results:
            return {}
        if not any(t in user_input.lower() for t in _DETAIL_TRIGGERS):
            return {}
        product_names = [
            r["payload"].get("name", "") for r in last_results if "payload" in r
        ]
        if not product_names:
            return {}
        names_str = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(product_names))
        raw = _strip_llm_fences(
            self.capability_worker.text_to_text_response(
                f'The user said: "{user_input}"\n'
                f"Which product are they asking about? Reply with only the number (1-{len(product_names)}) or 0.\n{names_str}"
            )
        )
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(last_results):
                return last_results[idx].get("payload", {})
        except ValueError:
            pass
        for word, idx in _ORDINAL_TO_IDX.items():
            if word in raw.lower() and idx < len(last_results):
                return last_results[idx].get("payload", {})
        return {}

    def _wants_rerank(self, user_input: str) -> str:
        result = (
            self.capability_worker.text_to_text_response(
                f"The user said: '{user_input}'. Are they asking to sort or rank results "
                f"by rating, popularity, or reviews? "
                f"Examples: 'best rated' = RATING_HIGH, 'most popular' = RATING_HIGH, "
                f"'which has the best reviews' = RATING_HIGH, 'lowest rated' = RATING_LOW.\n"
                f"Reply ONLY with: RATING_HIGH, RATING_LOW, or NO."
            )
            .strip()
            .upper()
        )
        if "RATING_HIGH" in result:
            return "rating_high"
        if "RATING_LOW" in result:
            return "rating_low"
        return ""

    # -------------------------------------------------------------------------
    # Main session loop
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            if not self._config_ok():
                await self.capability_worker.speak(
                    "Supplement Search isn't set up yet. "
                    "Add your API keys and re-upload the ability."
                )
                self.capability_worker.resume_normal_flow()
                return

            self._log(f"Starting. Provider: {VECTOR_DB_PROVIDER}")

            # Pre-fill first turn if the trigger phrase already contains a query.
            pending_input = None
            if self._trigger_text and len(self._trigger_text.split()) > 2:
                pending_input = self._trigger_text

            pending_guess = None
            confirmed_search = False

            await self.capability_worker.speak(
                "Supplement search is ready. Just a heads up, "
                "this is informational, not medical advice."
            )
            if pending_input:
                await self.capability_worker.speak("Searching now.")
            else:
                await self.capability_worker.speak(
                    "What health concern can I help with?"
                )

            idle_count = 0
            turn = 0

            while turn < MAX_TURNS:
                turn += 1

                if pending_input is not None:
                    user_input = pending_input
                    pending_input = None
                else:
                    user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= IDLE_EXIT:
                        await self.capability_worker.speak(
                            "I haven't heard anything in a while. Talk to you later."
                        )
                        break
                    if idle_count >= IDLE_REPROMPT:
                        user_input = await self.capability_worker.run_io_loop(
                            "Still here. What supplement or health concern can I help with?"
                        )
                        if user_input and user_input.strip():
                            idle_count = 0
                    continue

                idle_count = 0

                # Skip exit check while awaiting guess confirmation — affirmatives like
                # "yes" must confirm the guess, not exit the session.
                if not pending_guess and self._wants_exit(user_input):
                    await self.capability_worker.speak(
                        "Thanks for using Supplement Search. Stay healthy!"
                    )
                    break

                if pending_guess:
                    # User already spoke — use that as the answer
                    lowered_ui = user_input.lower().strip()
                    is_yes = any(
                        w in lowered_ui
                        for w in (
                            "yes", "yep", "yeah", "yup", "sure",
                            "ok", "okay", "correct", "right",
                            "absolutely", "go ahead", "do it",
                            "sounds good", "for sure", "that's right",
                            "exactly", "please", "uh huh", "you got it",
                        )
                    )
                    if is_yes:
                        pending_input = pending_guess
                        pending_guess = None
                        confirmed_search = True
                        continue
                    # Not a yes — check if it's a new health query
                    if self._is_health_query(user_input):
                        pending_guess = None
                        pending_input = user_input
                        confirmed_search = True
                        continue
                    pending_guess = None

                rerank = self._wants_rerank(user_input)
                if rerank and self._last_results and self._last_source == "curated":
                    sorted_results = sorted(
                        self._last_results,
                        key=lambda r: r["payload"].get("rating", 0),
                        reverse=(rerank == "rating_high"),
                    )
                    label = "highest" if rerank == "rating_high" else "lowest"
                    await self.capability_worker.speak(
                        await self._summarize_curated(
                            f"{label} rated {user_input}", sorted_results
                        )
                    )
                    self._last_results = sorted_results
                    continue

                if (
                    self._last_results
                    and self._last_source == "curated"
                    and not self._just_showed_detail
                ):
                    detail_payload = self._wants_detail(user_input, self._last_results)
                    if detail_payload:
                        self._just_showed_detail = True
                        await self.capability_worker.speak(
                            await self._detail_response(detail_payload)
                        )
                        await self.capability_worker.speak(
                            "Want details on another, or search for something else?"
                        )
                        continue
                    if any(t in user_input.lower() for t in _DETAIL_TRIGGERS):
                        count = min(len(self._last_results), MAX_DISPLAY)
                        ordinals = ["first", "second", "third"][:count]
                        options = ", ".join(ordinals[:-1]) + f", or {ordinals[-1]}" if count > 1 else ordinals[0]
                        await self.capability_worker.speak(
                            f"Which one? Say the {options}."
                        )
                        continue

                self._just_showed_detail = False

                if confirmed_search:
                    confirmed_search = False
                else:
                    health_check = self._is_health_query(user_input)
                    if health_check is None:
                        guess = self._guess_health_intent(user_input)
                        if guess:
                            pending_guess = guess
                            await self.capability_worker.speak(
                                f"Did you mean {guess}? Or tell me "
                                f"more about what you need."
                            )
                        else:
                            await self.capability_worker.speak(
                                "Can you tell me a bit more about what you're looking for?"
                            )
                        continue
                    if not health_check:
                        self._log(
                            f"Off-topic input rejected: {user_input[:GUESS_MAX_LEN]}"
                        )
                        guess = self._guess_health_intent(user_input)
                        if guess:
                            pending_guess = guess
                            await self.capability_worker.speak(
                                f"I didn't quite catch that. Did you mean {guess}? "
                                f"Or just tell me what you're looking for."
                            )
                        else:
                            pending_guess = None
                            await self.capability_worker.speak(
                                "I'm focused on health and supplement questions. "
                                "What health concern can I search for?"
                            )
                        continue

                search_query = self._normalize_query(user_input)
                await self.capability_worker.speak("Searching now.")
                results, source = await self._search_with_fallback(search_query)
                self._last_results = results
                self._last_source = source

                if source == "curated":
                    await self.capability_worker.speak(
                        await self._summarize_curated(search_query, results)
                    )
                elif source == "web":
                    await self.capability_worker.speak(
                        await self._summarize_web(search_query, results)
                    )
                else:
                    await self.capability_worker.speak(
                        "Nothing came up for that one. "
                        "Try rephrasing or a different health topic."
                    )

        except Exception as exc:
            self._err(f"Fatal run error: {exc}")
            await self.capability_worker.speak(
                "Sorry, something went wrong. Please try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self._last_results = []
        self._last_source = ""
        self._trigger_text = ""
        self._just_showed_detail = False
        try:
            if worker.transcription and worker.transcription.strip():
                self._trigger_text = worker.transcription.strip()
        except Exception:
            pass
        if not self._trigger_text:
            try:
                if worker.last_transcription and worker.last_transcription.strip():
                    self._trigger_text = worker.last_transcription.strip()
            except Exception:
                pass
        self.worker.session_tasks.create(self.run())
