import asyncio
import re

import httpx

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# HEALTH SUPPLEMENT SEARCH
# Voice-driven semantic search over 100 curated health supplement products.
# Weaviate: uses built-in Snowflake Arctic embeddings (no Jina needed).
# Qdrant: uses Jina AI embeddings (free tier).
# Falls back to Serper web search when the supplement is not in the local DB.
#
# SETUP: Fill in your keys below, then upload to OpenHome.
# Run the setup script first: github.com/megz2020/abilities/tree/feat/health-supplement-search-setup
# =============================================================================

# -----------------------------------------------------------------------------
# CONFIGURATION — fill in before uploading
# -----------------------------------------------------------------------------

# Choose your vector DB provider: "weaviate" or "qdrant"
VECTOR_DB_PROVIDER = "weaviate"

# Weaviate (provider = "weaviate") — no Jina key needed, embeddings are built-in
WEAVIATE_URL = ""        # e.g. "https://xxx.weaviate.cloud"
WEAVIATE_API_KEY = ""
WEAVIATE_CLASS = "Supplement"

# Qdrant (provider = "qdrant") — requires Jina for embeddings
QDRANT_URL = ""          # e.g. "https://xxx.qdrant.io:6333"
QDRANT_API_KEY = ""
QDRANT_COLLECTION = "supplements"
JINA_API_KEY = ""        # only needed for Qdrant

# Serper web fallback (optional — leave empty to disable)
SERPER_API_KEY = ""      # get a free key at serper.dev (2,500/month free)

# How similar a result must be to count as a match.
# Weaviate returns "certainty" (higher = more similar). Threshold applies as distance = 1 - certainty.
# Qdrant returns cosine score; distance = 1 - score. Both use the same threshold but are not
# identical scales — if using Qdrant, you may need to tune this value (try 0.60-0.65).
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
    "stop", "exit", "quit", "done", "bye", "goodbye", "cancel",
    "no thanks", "no thank you", "that's all", "that's it",
    "never mind", "nevermind", "all done", "i'm done", "im done",
    "thank you", "thanks", "cheers", "great thanks", "ok thanks", "okay thanks",
}

_ORDINAL_TO_IDX = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}

# Keywords that signal a health/supplement query — used to reject off-topic input
_HEALTH_KEYWORDS = {
    "supplement", "vitamin", "mineral", "herb", "herbal", "capsule", "tablet", "pill",
    "pain", "joint", "sleep", "energy", "immune", "anxiety", "stress", "inflammation",
    "digestion", "gut", "heart", "brain", "memory", "focus", "mood", "skin", "hair",
    "weight", "muscle", "bone", "liver", "kidney", "blood", "sugar", "pressure",
    "cholesterol", "fatigue", "cold", "flu", "allergy", "hormone", "thyroid", "iron",
    "calcium", "magnesium", "zinc", "omega", "probiotic", "prebiotic", "antioxidant",
    "collagen", "protein", "fiber", "detox", "cleanse", "health", "wellness", "remedy",
    "natural", "organic", "extract", "dose", "deficiency", "boost", "support",
}

# Triggers that indicate the user wants detail on a previously shown product
_DETAIL_TRIGGERS = (
    "more", "detail", "tell me about", "ingredients", "reviews", "what's in",
    "yes", "give me", "show me", "that one", "the first", "the second", "the third",
    "number", "about it", "about that", "first one", "second one", "third one",
)


def _strip_llm_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", str(text))
    return re.sub(r"\s+", " ", text).strip()


class HealthSupplementSearchCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    _last_results: list = None   # last vector DB results for follow-up "tell me more"
    _last_source: str = ""       # "curated" | "web"

    # {{register capability}}

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def _config_ok(self) -> bool:
        if VECTOR_DB_PROVIDER == "weaviate":
            return bool(WEAVIATE_URL.strip() and WEAVIATE_API_KEY.strip())
        if VECTOR_DB_PROVIDER == "qdrant":
            return bool(QDRANT_URL.strip() and QDRANT_API_KEY.strip() and JINA_API_KEY.strip())
        return False

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

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
    # Embedding (Qdrant path only)
    # -------------------------------------------------------------------------

    async def _embed_query(self, text: str) -> list:
        if not JINA_API_KEY.strip():
            self._err("Jina API key missing")
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    JINA_EMBED_URL,
                    headers={"Authorization": f"Bearer {JINA_API_KEY}", "Content-Type": "application/json"},
                    json={"model": JINA_MODEL, "input": [text], "dimensions": JINA_DIMENSIONS},
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]
        except Exception as exc:
            self._err(f"Jina embed error: {exc}")
            return []

    # -------------------------------------------------------------------------
    # Vector DB — abstract interface
    # -------------------------------------------------------------------------

    async def _search_supplements(self, user_query: str, limit: int = MAX_RESULTS) -> list:
        """
        Unified search. Handles embedding per provider:
        - Weaviate: raw text via nearText (Weaviate embeds internally, no Jina needed)
        - Qdrant: embeds with Jina first, then passes vector
        Returns list of {payload, score, distance}.
        """
        if VECTOR_DB_PROVIDER == "weaviate":
            return await self._weaviate_search(user_query, limit)
        vector = await self._embed_query(user_query)
        if not vector:
            return []
        return await self._qdrant_search(vector, limit)

    # --- Qdrant ---

    async def _qdrant_search(self, query_vector: list, limit: int) -> list:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{QDRANT_URL.rstrip('/')}/collections/{QDRANT_COLLECTION}/points/search",
                    headers={"api-key": QDRANT_API_KEY, "Content-Type": "application/json"},
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

    # --- Weaviate (nearText — embedding handled by Weaviate internally) ---

    async def _weaviate_search(self, query_text: str, limit: int) -> list:
        safe_query = query_text.replace('"', "'")
        gql = (
            f'{{ Get {{ {WEAVIATE_CLASS}('
            f'nearText: {{concepts: ["{safe_query}"]}}, '
            f'limit: {limit}'
            f') {{ name brand rating description ingredients summary effects image reviews '
            f'_additional {{ certainty distance }} }} }} }}'
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
                    results.append({"payload": payload, "score": certainty, "distance": distance})
                return results
        except Exception as exc:
            self._err(f"Weaviate search error: {exc}")
            return []

    # -------------------------------------------------------------------------
    # Serper fallback
    # -------------------------------------------------------------------------

    async def _serper_search(self, query: str) -> list:
        if not SERPER_API_KEY.strip():
            return []
        search_q = f"{query} supplement benefits reviews site:examine.com OR site:iherb.com OR site:webmd.com"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    SERPER_SEARCH_URL,
                    headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                    json={"q": search_q, "num": 5},
                )
                resp.raise_for_status()
                organic = resp.json().get("organic", [])
                return [
                    {"title": r.get("title", ""), "snippet": r.get("snippet", ""), "link": r.get("link", "")}
                    for r in organic
                ]
        except Exception as exc:
            self._err(f"Serper search error: {exc}")
            return []

    # -------------------------------------------------------------------------
    # Search with fallback logic
    # -------------------------------------------------------------------------

    async def _search_with_fallback(self, user_query: str) -> tuple:
        """
        1. Vector DB search — return curated results if best distance < threshold.
        2. If no good match and Serper key is set — fall back to web search.
        3. Otherwise return ([], 'none').
        """
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
            f"The user asked: \"{user_query}\"\n\n"
            f"Top matching supplements from a curated database:\n{products_text}\n"
            "Give a friendly, conversational voice response recommending the most relevant products. "
            "Mention product names, ratings, and key benefits listed above. "
            "IMPORTANT: Only mention benefits explicitly stated in the data above — do NOT infer, "
            "add, or speculate about any benefits not listed. Keep it to 3-4 sentences. "
            "End by asking if they want more details on any product. No markdown. Not medical advice."
        )
        return await asyncio.to_thread(self.capability_worker.text_to_text_response, prompt)

    async def _summarize_web(self, user_query: str, web_results: list) -> str:
        snippets = "".join(
            f"- {r.get('title', '')}: {r.get('snippet', '')}\n" for r in web_results[:4]
        )
        prompt = (
            f"The user asked about: \"{user_query}\"\n\n"
            f"Not found in curated database. Web results:\n{snippets}\n"
            "Give a brief, helpful 2-3 sentence voice response. Make clear this is from web results, "
            "not a curated product database. Remind the user to consult a healthcare provider. "
            "No markdown or URLs."
        )
        return await asyncio.to_thread(self.capability_worker.text_to_text_response, prompt)

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
        return await asyncio.to_thread(self.capability_worker.text_to_text_response, prompt)

    # -------------------------------------------------------------------------
    # Intent detection
    # -------------------------------------------------------------------------

    def _wants_exit(self, user_input: str) -> bool:
        lowered = user_input.lower().strip()
        if any(phrase in lowered for phrase in EXIT_WORDS):
            return True
        # Short inputs (≤5 words) that passed keyword check — ask LLM once.
        # Catches STT garbles like "Thank you, Snowby" when user said "goodbye".
        if len(user_input.split()) <= 5:
            result = self.capability_worker.text_to_text_response(
                f"Does this mean the user wants to stop or say goodbye?\n"
                f"Input: \"{user_input}\"\nReply YES or NO only."
            ).strip().upper()
            return result.startswith("YES")
        return False

    def _is_health_query(self, user_input: str) -> bool:
        """Return True if the input looks like a health or supplement question."""
        lowered = user_input.lower()
        if any(kw in lowered for kw in _HEALTH_KEYWORDS):
            return True
        # LLM fallback for any input that didn't match keywords
        result = self.capability_worker.text_to_text_response(
            f"Is this a question about health, wellness, or dietary supplements?\n"
            f"Input: \"{user_input}\"\nReply YES or NO only."
        ).strip().upper()
        return result.startswith("YES")

    def _wants_detail(self, user_input: str, last_results: list) -> dict:
        if not last_results:
            return {}
        if not any(t in user_input.lower() for t in _DETAIL_TRIGGERS):
            return {}
        # Guard: only curated results have payload keys
        product_names = [r["payload"].get("name", "") for r in last_results if "payload" in r]
        if not product_names:
            return {}
        names_str = "\n".join(f"{i+1}. {n}" for i, n in enumerate(product_names))
        raw = _strip_llm_fences(self.capability_worker.text_to_text_response(
            f"The user said: \"{user_input}\"\n"
            f"Which product are they asking about? Reply with only the number (1-{len(product_names)}) or 0.\n{names_str}"
        ))
        # Try numeric first, then ordinal words ("first", "second", etc.)
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
    # Main loop
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

            # If the trigger phrase already contains a specific query (e.g. "find supplements
            # for joint pain"), use it as the first turn instead of asking again.
            pending_input = None
            if self._trigger_text and len(self._trigger_text.split()) > 2:
                pending_input = self._trigger_text

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
                        await self.capability_worker.speak("No response detected. Goodbye!")
                        break
                    if idle_count >= IDLE_REPROMPT:
                        user_input = await self.capability_worker.run_io_loop(
                            "I'm still here. What supplement or health concern can I help you with?"
                        )
                        if user_input and user_input.strip():
                            idle_count = 0
                    continue

                idle_count = 0

                if self._wants_exit(user_input):
                    await self.capability_worker.speak("Thanks for using Health Supplement Search. Stay healthy!")
                    break

                # Check rerank before detail — rerank must happen first so that a subsequent
                # detail request can reference the newly ordered list.
                rerank = self._wants_rerank(user_input)
                if rerank and self._last_results and self._last_source == "curated":
                    sorted_results = sorted(
                        self._last_results,
                        key=lambda r: r["payload"].get("rating", 0),
                        reverse=(rerank == "rating_high"),
                    )
                    label = "highest" if rerank == "rating_high" else "lowest"
                    await self.capability_worker.speak(
                        await self._summarize_curated(f"{label} rated {user_input}", sorted_results)
                    )
                    self._last_results = sorted_results
                    continue

                # Detail request on previous results (only valid for curated results)
                if self._last_results and self._last_source == "curated" and not self._just_showed_detail:
                    detail_payload = self._wants_detail(user_input, self._last_results)
                    if detail_payload:
                        self._just_showed_detail = True
                        await self.capability_worker.speak(await self._detail_response(detail_payload))
                        await self.capability_worker.speak(
                            "Would you like details on another product, or search for something else?"
                        )
                        continue
                    # Detail intent detected but couldn't resolve which product — ask to clarify
                    if any(t in user_input.lower() for t in _DETAIL_TRIGGERS):
                        await self.capability_worker.speak(
                            "Which product would you like more details on? "
                            "Say the first, second, or third."
                        )
                        continue

                self._just_showed_detail = False

                # Off-topic guard — only search if the input is health/supplement related
                if not self._is_health_query(user_input):
                    self._log(f"Off-topic input rejected: {user_input[:60]}")
                    await self.capability_worker.speak(
                        "I can only help with health and supplement questions. "
                        "What health concern can I search supplements for?"
                    )
                    continue

                # New search
                await self.capability_worker.speak("Let me search for that...")
                results, source = await self._search_with_fallback(user_input)
                self._last_results = results
                self._last_source = source

                if source == "curated":
                    await self.capability_worker.speak(await self._summarize_curated(user_input, results))
                elif source == "web":
                    await self.capability_worker.speak(await self._summarize_web(user_input, results))
                else:
                    await self.capability_worker.speak(
                        "I couldn't find supplements matching that concern in my database or online. "
                        "Could you rephrase, or try a different health topic?"
                    )

        except Exception as exc:
            self._err(f"Fatal run error: {exc}")
            await self.capability_worker.speak("Sorry, something went wrong. Please try again later.")
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        # Initialize per-session state to avoid leaking across ability invocations
        self._last_results = []
        self._last_source = ""
        self._trigger_text = ""
        self._just_showed_detail = False
        # Extract the trigger phrase to pre-fill the first search turn if it contains a query
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
