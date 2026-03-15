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

# Similarity threshold: Weaviate uses certainty (0–1), Qdrant uses cosine score.
# Both are normalised to distance = 1 - score before comparison.
# Qdrant distances may differ slightly — tune between 0.60 and 0.65 if needed.
DISTANCE_THRESHOLD = 0.70

# -----------------------------------------------------------------------------

JINA_EMBED_URL = "https://api.jina.ai/v1/embeddings"
JINA_MODEL = "jina-embeddings-v3"
JINA_DIMENSIONS = 1024

SERPER_SEARCH_URL = "https://google.serper.dev/search"

MAX_RESULTS = 5
MAX_TURNS = 20
IDLE_REPROMPT = 2
IDLE_EXIT = 3

EXIT_WORDS = {
    "stop",
    "exit",
    "quit",
    "done",
    "bye",
    "goodbye",
    "cancel",
    "no thanks",
    "no thank you",
    "that's all",
    "that's it",
    "never mind",
    "nevermind",
    "all done",
    "i'm done",
    "im done",
    "thank you",
    "thanks",
    "cheers",
    "great thanks",
    "ok thanks",
    "okay thanks",
}

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
    "more",
    "detail",
    "tell me about",
    "ingredients",
    "reviews",
    "what's in",
    "yes",
    "yep",
    "yeah",
    "sure",
    "ok",
    "okay",
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
            async with httpx.AsyncClient(timeout=15) as client:
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
            async with httpx.AsyncClient(timeout=15) as client:
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
            async with httpx.AsyncClient(timeout=15) as client:
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
            async with httpx.AsyncClient(timeout=15) as client:
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
        for i, r in enumerate(results[:3], 1):
            p = r["payload"]
            positives = []
            for part in str(p.get("effects", "")).split(","):
                part = part.strip().strip("[]'\"")
                if part.startswith("POSITIVE on "):
                    positives.append(part.replace("POSITIVE on ", "").replace("_", " "))
            effects_str = ", ".join(positives[:3]) if positives else "general wellness"
            products_text += (
                f"{i}. {p.get('name', 'Unknown')} by {p.get('brand', 'Unknown')} "
                f"(rating: {p.get('rating', 0)}/5). "
                f"Key benefits: {effects_str}. "
                f"Summary: {p.get('summary', '')[:150]}\n"
            )
        prompt = (
            f'The user asked: "{user_query}"\n\n'
            f"Top matching supplements from a curated database:\n{products_text}\n"
            "Give a friendly, conversational voice response recommending the most relevant products. "
            "Mention product names, ratings, and key benefits listed above. "
            "IMPORTANT: Only mention benefits explicitly stated in the data above — do NOT infer, "
            "add, or speculate about any benefits not listed. Keep it to 3-4 sentences. "
            "End by asking if they want more details on any product. No markdown. Not medical advice."
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
            "Give a brief, helpful 2-3 sentence voice response. Make clear this is from web results, "
            "not a curated product database. Remind the user to consult a healthcare provider. "
            "No markdown or URLs."
        )
        return await asyncio.to_thread(
            self.capability_worker.text_to_text_response, prompt
        )

    async def _detail_response(self, product_payload: dict) -> str:
        p = product_payload
        reviews = p.get("reviews", [])
        review_sample = (
            _strip_html(reviews[0])[:150]
            if isinstance(reviews, list) and reviews
            else "No reviews available."
        )
        prompt = (
            f"Give a detailed voice summary of this supplement:\n"
            f"Name: {p.get('name', '')}\n"
            f"Brand: {p.get('brand', '')}\n"
            f"Rating: {p.get('rating', 0)}/5\n"
            f"Description: {p.get('description', '')[:300]}\n"
            f"Ingredients: {p.get('ingredients', '')[:200]}\n"
            f"Effects: {p.get('effects', '')[:200]}\n"
            f"Sample review: {review_sample}\n"
            "4 sentences max. Friendly, informative. No markdown. Not medical advice."
        )
        return await asyncio.to_thread(
            self.capability_worker.text_to_text_response, prompt
        )

    # -------------------------------------------------------------------------
    # Intent detection
    # -------------------------------------------------------------------------

    def _wants_exit(self, user_input: str) -> bool:
        lowered = user_input.lower().strip()
        word_count = len(lowered.split())
        # Short inputs: substring match is safe; exit words won't appear accidentally.
        if word_count <= 5:
            if any(phrase in lowered for phrase in EXIT_WORDS):
                return True
            # LLM catches STT garbles of farewell phrases.
            result = (
                self.capability_worker.text_to_text_response(
                    f"Does this mean the user wants to stop or say goodbye?\n"
                    f'Input: "{user_input}"\nReply YES or NO only.'
                )
                .strip()
                .upper()
            )
            return result.startswith("YES")
        # Longer inputs: exit words can appear inside unrelated sentences; use LLM only.
        result = (
            self.capability_worker.text_to_text_response(
                f"Does this input primarily mean the user wants to stop or say goodbye? "
                f"Ignore incidental words like 'thanks' if the sentence has other content.\n"
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

    def _guess_health_intent(self, user_input: str) -> str:
        """
        Return the most likely health phrase the user meant (e.g. 'joint pain'),
        or an empty string if no health intent can be detected.
        Used to offer a clarification prompt when input is ambiguous or garbled.
        """
        raw = self.capability_worker.text_to_text_response(
            f"This voice input may be garbled by speech recognition. "
            f"If it seems like the user was trying to ask about a health concern or supplement, "
            f"reply with only the most likely 2-4 word health phrase they meant "
            f"(e.g. 'joint pain', 'sleep issues', 'headache relief'). "
            f"If you cannot detect any health intent, reply with exactly: NONE\n"
            f'Input: "{user_input}"'
        ).strip()
        if not raw or raw.upper() == "NONE" or len(raw) > 60:
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
        lowered = user_input.lower()
        if any(w in lowered for w in ("best rated", "highest rated", "top rated")):
            return "rating_high"
        if any(w in lowered for w in ("lowest rated", "worst rated")):
            return "rating_low"
        return ""

    # -------------------------------------------------------------------------
    # Main session loop
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            if not self._config_ok():
                await self.capability_worker.speak(
                    "Health Supplement Search isn't configured yet. "
                    "Please fill in your API keys in main.py and re-upload. "
                    "Check the README for setup instructions."
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

            if pending_input:
                await self.capability_worker.speak(
                    "Welcome to Health Supplement Search. This is informational only — not medical advice. "
                    "Let me search for that..."
                )
            else:
                await self.capability_worker.speak(
                    "Welcome to Health Supplement Search. "
                    "I can help you find supplements for specific health concerns using a curated database "
                    "of 100 reviewed products. This is informational only — not medical advice. "
                    "What health concern can I help you with today?"
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
                            "No response detected. Goodbye!"
                        )
                        break
                    if idle_count >= IDLE_REPROMPT:
                        user_input = await self.capability_worker.run_io_loop(
                            "I'm still here. What supplement or health concern can I help you with?"
                        )
                        if user_input and user_input.strip():
                            idle_count = 0
                    continue

                idle_count = 0

                # Skip exit check while awaiting guess confirmation — affirmatives like
                # "yes" must confirm the guess, not exit the session.
                if not pending_guess and self._wants_exit(user_input):
                    await self.capability_worker.speak(
                        "Thanks for using Health Supplement Search. Stay healthy!"
                    )
                    break

                if pending_guess:
                    lowered_ui = user_input.lower().strip()
                    if any(
                        w in lowered_ui
                        for w in (
                            "yes",
                            "yep",
                            "yeah",
                            "sure",
                            "ok",
                            "okay",
                            "correct",
                            "right",
                        )
                    ):
                        pending_input = pending_guess
                        pending_guess = None
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
                            "Would you like details on another product, or search for something else?"
                        )
                        continue
                    if any(t in user_input.lower() for t in _DETAIL_TRIGGERS):
                        await self.capability_worker.speak(
                            "Which product would you like more details on? "
                            "Say the first, second, or third."
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
                                f"Did you mean {guess}? Say yes to search for that, "
                                f"or tell me more about what you need."
                            )
                        else:
                            await self.capability_worker.speak(
                                "Can you tell me more? What health concern are you looking for supplements for?"
                            )
                        continue
                    if not health_check:
                        self._log(f"Off-topic input rejected: {user_input[:60]}")
                        guess = self._guess_health_intent(user_input)
                        if guess:
                            pending_guess = guess
                            await self.capability_worker.speak(
                                f"I didn't quite catch that. Did you mean something like {guess}? "
                                f"Or tell me what health concern you're looking for."
                            )
                        else:
                            pending_guess = None
                            await self.capability_worker.speak(
                                "I can only help with health and supplement questions. "
                                "What health concern can I search supplements for?"
                            )
                        continue

                await self.capability_worker.speak("Let me search for that...")
                results, source = await self._search_with_fallback(user_input)
                self._last_results = results
                self._last_source = source

                if source == "curated":
                    await self.capability_worker.speak(
                        await self._summarize_curated(user_input, results)
                    )
                elif source == "web":
                    await self.capability_worker.speak(
                        await self._summarize_web(user_input, results)
                    )
                else:
                    await self.capability_worker.speak(
                        "I couldn't find supplements matching that concern in my database or online. "
                        "Could you rephrase, or try a different health topic?"
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
