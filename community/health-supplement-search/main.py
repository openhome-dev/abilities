import asyncio
import json
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
# One-time setup required: run setup/setup_vectordb.py before first use.
# =============================================================================

CONFIG_FILE = "health_supplement_config.json"

# Top-level constants for keys (empty = read from config at runtime)
JINA_API_KEY = ""
QDRANT_URL = ""
QDRANT_API_KEY = ""
WEAVIATE_URL = ""
WEAVIATE_API_KEY = ""
SERPER_API_KEY = ""

JINA_EMBED_URL = "https://api.jina.ai/v1/embeddings"
JINA_MODEL = "jina-embeddings-v3"
JINA_DIMENSIONS = 1536

SERPER_SEARCH_URL = "https://google.serper.dev/search"

# Distance threshold: results with distance >= this value are considered "no match"
# Cosine distance in Qdrant: 0.0 = identical, 2.0 = opposite
# Weaviate certainty: 1.0 = identical, 0.0 = opposite (converted to distance = 1 - certainty)
DEFAULT_DISTANCE_THRESHOLD = 0.70

MAX_RESULTS = 5
MAX_TURNS = 20
IDLE_REPROMPT = 2
IDLE_EXIT = 3

EXIT_WORDS = {"stop", "exit", "quit", "done", "bye", "goodbye", "no thanks", "cancel"}

DEFAULT_CONFIG = {
    "vector_db_provider": "qdrant",
    "jina_api_key": JINA_API_KEY,
    "qdrant_url": QDRANT_URL,
    "qdrant_api_key": QDRANT_API_KEY,
    "qdrant_collection": "supplements",
    "weaviate_url": WEAVIATE_URL,
    "weaviate_api_key": WEAVIATE_API_KEY,
    "weaviate_class": "Supplement",
    "serper_api_key": SERPER_API_KEY,
    "distance_threshold": DEFAULT_DISTANCE_THRESHOLD,
}


def _strip_llm_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class HealthSupplementSearchCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Runtime config (populated by _load_config)
    _cfg: dict = None
    _last_results: list = None   # last vector DB results for follow-up "tell me more"
    _last_source: str = ""       # "curated" | "web"

    # {{register capability}}

    # -------------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------------

    async def _load_config(self) -> bool:
        """Load config from OpenHome file storage. Returns True if ready to use."""
        try:
            exists = await self.capability_worker.check_if_file_exists(CONFIG_FILE, False)
            if exists:
                raw = await self.capability_worker.read_file(CONFIG_FILE, False)
                loaded = json.loads(raw)
                self._cfg = {**DEFAULT_CONFIG, **loaded}
            else:
                self._cfg = dict(DEFAULT_CONFIG)
        except Exception as exc:
            self._log(f"Config load error: {exc}")
            self._cfg = dict(DEFAULT_CONFIG)

        # Merge top-level constants (let env/hardcoded keys override empty config)
        for key, const in [
            ("jina_api_key", JINA_API_KEY),
            ("qdrant_api_key", QDRANT_API_KEY),
            ("qdrant_url", QDRANT_URL),
            ("weaviate_api_key", WEAVIATE_API_KEY),
            ("weaviate_url", WEAVIATE_URL),
            ("serper_api_key", SERPER_API_KEY),
        ]:
            if const and not self._cfg.get(key):
                self._cfg[key] = const

        provider = self._cfg.get("vector_db_provider", "qdrant")
        jina_ok = bool(self._cfg.get("jina_api_key", "").strip())
        qdrant_ok = bool(self._cfg.get("qdrant_url", "").strip() and self._cfg.get("qdrant_api_key", "").strip())
        weaviate_ok = bool(self._cfg.get("weaviate_url", "").strip() and self._cfg.get("weaviate_api_key", "").strip())

        # Jina is only required for Qdrant — Weaviate embeds internally
        if provider == "qdrant" and not jina_ok:
            return False
        if provider == "qdrant" and not qdrant_ok:
            return False
        if provider == "weaviate" and not weaviate_ok:
            return False
        return True

    async def _save_config(self):
        if await self.capability_worker.check_if_file_exists(CONFIG_FILE, False):
            await self.capability_worker.delete_file(CONFIG_FILE, False)
        await self.capability_worker.write_file(CONFIG_FILE, json.dumps(self._cfg), False)

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def _log(self, msg: str):
        self.worker.editor_logging_handler.info(f"[HealthSupSearch] {msg}")

    def _err(self, msg: str):
        self.worker.editor_logging_handler.error(f"[HealthSupSearch] {msg}")

    # -------------------------------------------------------------------------
    # Embedding
    # -------------------------------------------------------------------------

    async def _embed_query(self, text: str) -> list:
        """Embed a query string via Jina AI. Returns 1536-dim vector or []."""
        key = self._cfg.get("jina_api_key", "").strip()
        if not key:
            self._err("Jina API key missing")
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    JINA_EMBED_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
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
        Unified search entry point. Handles embedding per provider:
        - Weaviate: passes raw text via nearText (Weaviate embeds internally)
        - Qdrant: embeds with Jina first, then passes vector
        Returns list of {payload, score, distance}.
        """
        provider = self._cfg.get("vector_db_provider", "qdrant")
        if provider == "weaviate":
            return await self._weaviate_search(user_query, limit)
        vector = await self._embed_query(user_query)
        if not vector:
            return []
        return await self._qdrant_search(vector, limit)

    # --- Qdrant ---

    async def _qdrant_search(self, query_vector: list, limit: int) -> list:
        url = self._cfg.get("qdrant_url", "").rstrip("/")
        collection = self._cfg.get("qdrant_collection", "supplements")
        key = self._cfg.get("qdrant_api_key", "")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{url}/collections/{collection}/points/search",
                    headers={"api-key": key, "Content-Type": "application/json"},
                    json={"vector": query_vector, "limit": limit, "with_payload": True},
                )
                resp.raise_for_status()
                hits = resp.json().get("result", [])
                return [
                    {
                        "payload": h.get("payload", {}),
                        "score": h.get("score", 0.0),
                        "distance": 1.0 - h.get("score", 0.0),  # Qdrant cosine score → distance
                    }
                    for h in hits
                ]
        except Exception as exc:
            self._err(f"Qdrant search error: {exc}")
            return []

    # --- Weaviate (nearText — embedding handled by Weaviate internally) ---

    async def _weaviate_search(self, query_text: str, limit: int) -> list:
        url = self._cfg.get("weaviate_url", "").rstrip("/")
        key = self._cfg.get("weaviate_api_key", "")
        cls = self._cfg.get("weaviate_class", "Supplement")
        # Escape any quotes in the query to avoid breaking the GraphQL string
        safe_query = query_text.replace('"', "'")
        gql = (
            f'{{ Get {{ {cls}('
            f'nearText: {{concepts: ["{safe_query}"]}}, '
            f'limit: {limit}'
            f') {{ name brand rating description ingredients summary effects image reviews '
            f'_additional {{ certainty distance }} }} }} }}'
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{url}/v1/graphql",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "X-Weaviate-Cluster-Url": url,
                    },
                    json={"query": gql},
                )
                resp.raise_for_status()
                data = resp.json()
                errors = data.get("errors")
                if errors:
                    self._err(f"Weaviate GraphQL errors: {errors}")
                    return []
                hits = data.get("data", {}).get("Get", {}).get(cls, []) or []
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
        """Search Serper for supplement info. Returns [{title, snippet, link}]."""
        key = self._cfg.get("serper_api_key", "").strip()
        if not key:
            return []
        search_q = f"{query} supplement benefits reviews site:examine.com OR site:iherb.com OR site:webmd.com"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    SERPER_SEARCH_URL,
                    headers={"X-API-KEY": key, "Content-Type": "application/json"},
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
        Returns (results, source) where source is 'curated' or 'web'.
        1. Try vector DB — if best distance < threshold, return curated results.
        2. If no good match and serper key is set, fall back to web search.
        3. Otherwise return ([], 'none').
        Weaviate embeds the query internally; Qdrant uses Jina AI.
        """
        threshold = float(self._cfg.get("distance_threshold", DEFAULT_DISTANCE_THRESHOLD))

        db_results = await self._search_supplements(user_query)
        if db_results and db_results[0]["distance"] < threshold:
            self._log(f"Curated match (best distance: {db_results[0]['distance']:.3f})")
            return db_results, "curated"

        best = f"{db_results[0]['distance']:.3f}" if db_results else "N/A"
        self._log(f"No curated match (best distance: {best}), trying Serper")
        web_results = await self._serper_search(user_query)
        if web_results:
            return web_results, "web"

        return [], "none"

    # -------------------------------------------------------------------------
    # LLM summarization
    # -------------------------------------------------------------------------

    def _summarize_curated(self, user_query: str, results: list) -> str:
        """Build voice-friendly summary of curated DB results."""
        products_text = ""
        for i, r in enumerate(results[:3], 1):
            p = r["payload"]
            effects_raw = p.get("effects", "")
            positives = []
            for part in str(effects_raw).split(","):
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
            f"Here are the top matching supplements from a curated database:\n{products_text}\n"
            "Provide a friendly, conversational voice response recommending the most relevant products. "
            "Mention product names, ratings, and key benefits. Keep it to 3-4 sentences maximum. "
            "End with asking if they want more details on any product. "
            "Do not include markdown. This is not medical advice."
        )
        return self.capability_worker.text_to_text_response(prompt)

    def _summarize_web(self, user_query: str, web_results: list) -> str:
        """Build voice-friendly summary of web search results."""
        snippets = ""
        for r in web_results[:4]:
            snippets += f"- {r.get('title', '')}: {r.get('snippet', '')}\n"

        prompt = (
            f"The user asked about: \"{user_query}\"\n\n"
            f"I didn't find this in my curated supplement database, but here is what I found online:\n{snippets}\n"
            "Provide a brief, helpful voice response based on these web results. "
            "Keep it to 2-3 sentences. Be clear that this comes from web results and not a curated product database. "
            "Always remind the user to consult a healthcare provider before taking any supplement. "
            "Do not include markdown or URLs."
        )
        return self.capability_worker.text_to_text_response(prompt)

    def _detail_response(self, product_payload: dict) -> str:
        """Generate a detailed voice response for a single product."""
        p = product_payload
        reviews = p.get("reviews", [])
        review_sample = reviews[0][:120] if reviews else "No reviews available."
        prompt = (
            f"Give a detailed voice summary of this supplement:\n"
            f"Name: {p.get('name', '')}\n"
            f"Brand: {p.get('brand', '')}\n"
            f"Rating: {p.get('rating', 0)}/5\n"
            f"Description: {p.get('description', '')[:300]}\n"
            f"Ingredients: {p.get('ingredients', '')[:200]}\n"
            f"Effects: {p.get('effects', '')[:200]}\n"
            f"Sample review: {review_sample}\n"
            "Keep it to 4 sentences. Friendly and informative. No markdown. "
            "Remind the user this is not medical advice."
        )
        return self.capability_worker.text_to_text_response(prompt)

    # -------------------------------------------------------------------------
    # Intent detection
    # -------------------------------------------------------------------------

    def _wants_exit(self, user_input: str) -> bool:
        lowered = user_input.lower().strip()
        if any(word in lowered for word in EXIT_WORDS):
            return True
        prompt = (
            f"Does this voice input mean the user wants to stop/exit the supplement search?\n"
            f"Input: \"{user_input}\"\n"
            "Reply with only YES or NO."
        )
        result = self.capability_worker.text_to_text_response(prompt).strip().upper()
        return result.startswith("YES")

    def _wants_detail(self, user_input: str, last_results: list) -> dict:
        """Return the matching product payload if user wants details on a specific product, else {}."""
        if not last_results:
            return {}
        detail_triggers = ("more", "detail", "tell me about", "ingredients", "reviews", "what's in")
        lowered = user_input.lower()
        if not any(t in lowered for t in detail_triggers):
            return {}

        product_names = [r["payload"].get("name", "") for r in last_results if "payload" in r]
        names_str = "\n".join(f"{i+1}. {n}" for i, n in enumerate(product_names))
        prompt = (
            f"The user said: \"{user_input}\"\n"
            f"Which of these products are they asking about? Reply with only the number (1-{len(product_names)}) "
            f"or 0 if unclear.\n{names_str}"
        )
        raw = self.capability_worker.text_to_text_response(prompt).strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(last_results):
                return last_results[idx].get("payload", {})
        except ValueError:
            pass
        return {}

    def _wants_rerank(self, user_input: str) -> str:
        """Return 'rating_high', 'rating_low', or '' if no rerank intent detected."""
        lowered = user_input.lower()
        if any(w in lowered for w in ("best rated", "highest rated", "top rated", "best rating")):
            return "rating_high"
        if any(w in lowered for w in ("lowest rated", "worst rated", "cheapest")):
            return "rating_low"
        return ""

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            config_ok = await self._load_config()
            if not config_ok:
                await self.capability_worker.speak(
                    "Health Supplement Search isn't configured yet. "
                    "Please run the setup script and add your API keys to the config file. "
                    "Check the README for instructions."
                )
                self.capability_worker.resume_normal_flow()
                return

            provider = self._cfg.get("vector_db_provider", "qdrant")
            self._log(f"Starting. Provider: {provider}")

            await self.capability_worker.speak(
                "Welcome to Health Supplement Search. "
                "I can help you find supplements for specific health concerns using a curated database "
                "of 100 reviewed products. Note: this is for informational purposes only and not medical advice. "
                "What health concern can I help you with today?"
            )

            self._last_results = []
            self._last_source = ""
            idle_count = 0
            turn = 0

            while turn < MAX_TURNS:
                turn += 1
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= IDLE_EXIT:
                        await self.capability_worker.speak("No response detected. Goodbye!")
                        break
                    if idle_count >= IDLE_REPROMPT:
                        await self.capability_worker.speak(
                            "I'm still here. What supplement or health concern can I help you with?"
                        )
                    continue

                idle_count = 0

                if self._wants_exit(user_input):
                    await self.capability_worker.speak(
                        "Thanks for using Health Supplement Search. Stay healthy!"
                    )
                    break

                # Check for rerank request on previous results
                rerank = self._wants_rerank(user_input)
                if rerank and self._last_results and self._last_source == "curated":
                    sorted_results = sorted(
                        self._last_results,
                        key=lambda r: r["payload"].get("rating", 0),
                        reverse=(rerank == "rating_high"),
                    )
                    label = "highest" if rerank == "rating_high" else "lowest"
                    summary = self._summarize_curated(f"{label} rated {user_input}", sorted_results)
                    await self.capability_worker.speak(summary)
                    self._last_results = sorted_results
                    continue

                # Check for detail request on previous results
                if self._last_results and self._last_source == "curated":
                    detail_payload = self._wants_detail(user_input, self._last_results)
                    if detail_payload:
                        detail = self._detail_response(detail_payload)
                        await self.capability_worker.speak(detail)
                        await self.capability_worker.speak(
                            "Would you like details on another product, or shall we search for something else?"
                        )
                        continue

                # New search
                await self.capability_worker.speak("Let me search for that...")
                results, source = await self._search_with_fallback(user_input)
                self._last_results = results
                self._last_source = source

                if source == "curated":
                    summary = self._summarize_curated(user_input, results)
                    await self.capability_worker.speak(summary)
                elif source == "web":
                    summary = self._summarize_web(user_input, results)
                    await self.capability_worker.speak(summary)
                else:
                    await self.capability_worker.speak(
                        "I couldn't find any supplements matching that concern in my database or online. "
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
        self.worker.session_tasks.create(self.run())
