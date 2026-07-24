import asyncio
import json

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# IMMERSIVE PROVIDER (Skill)
# Entry point for a user returning to compare and book provider quotes on an
# open home-service request created earlier by the intake skill.
#
# Flow: load open requests -> pick one -> fetch + rank quotes -> spoken
# comparison loop -> confirm -> book -> resume_normal_flow().
#
# Shared-state contract (abilities cannot chain, they share files):
#   immersive_requests.json = {"requests": [
#       {"id", "category", "description", "status": "open"|"booked",
#        "booked_provider" (once booked)} ]}
# =============================================================================

BACKEND_URL = ""                                   # optional hardcoded fallback URL
BACKEND_URL_KEY = "immersive_backend_url"          # Settings -> API Keys: your deployed backend URL
API_KEY_NAME = "immersive_api_key"                 # optional, Settings -> API Keys
REQUEST_TIMEOUT = 10
REQUESTS_FILE = "immersive_requests.json"

EXIT_WORDS = {"stop", "exit", "quit", "cancel", "goodbye", "bye", "never mind", "nevermind"}

# Ranking weights: reproducible scoring belongs in code, not the LLM.
# Quality-first: rating and reliability dominate; price gets a floored score
# (0.5-1.0) so a cheap low-quality provider can never outrank a great one.
WEIGHTS = {"rating": 0.45, "reliability": 0.25, "price": 0.15, "availability": 0.15}

DEMO_REQUEST = {
    "id": "demo-1",
    "category": "plumbing",
    "description": "leaking pipe under the kitchen sink",
    "status": "open",
}

DEMO_QUOTES = [
    {"id": "q1", "provider": "Rapid Plumbing Co", "price": 140, "rating": 4.8,
     "reliability": 0.96, "availability": "today at 5 PM"},
    {"id": "q2", "provider": "HomeFix Solutions", "price": 110, "rating": 4.4,
     "reliability": 0.90, "availability": "tomorrow morning"},
    {"id": "q3", "provider": "BlueWrench Services", "price": 95, "rating": 3.9,
     "reliability": 0.78, "availability": "in two days"},
]

INTENT_PROMPT = (
    "You classify one voice reply from a user comparing provider quotes. "
    "The quotes are numbered 1 to {count}. Reply with EXACTLY one token:\n"
    "SELECT:<n> if they choose quote n to book (e.g. 'book the first one', 'go with Rapid Plumbing').\n"
    "DETAILS:<n> if they ask about quote n (e.g. 'tell me more about the second').\n"
    "REPEAT if they want the comparison again.\n"
    "EXIT if they want to stop or decide later.\n"
    "OTHER for anything else.\n"
    "Provider names in order: {names}. Output only the token."
)

ORDINALS = ("first", "second", "third", "fourth", "fifth")

# Spoken lines — fork the persona by editing these, never the logic below.
LINE_CHECKING = "One sec, checking your open requests."
LINE_NO_REQUESTS = "You have no open service requests right now. Say home help to start one."
LINE_LATER = "Okay, we can compare quotes later."
LINE_NO_QUOTES = "No quotes have come in yet. I'll let you know when providers respond."
LINE_STILL_THERE = "Still there? Say book, details, or stop."
LINE_QUOTES_SAVED = "No problem, your quotes are saved. Say check my quotes anytime."
LINE_BOOKING = "Booking that now."
LINE_NOT_BOOKED = "Okay, not booked. Want details on another quote, or should we stop?"
LINE_HELP = "You can say book the first one, ask for details, or say stop."
LINE_ERROR = "Sorry, something went wrong checking your quotes. Please try again."
LINE_WHICH_REQUEST = "Sorry, which request was that?"


class ImmersiveProviderCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    api_base: str = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.api_base = None
        self.worker.session_tasks.create(self.run())

    # ------------------------------------------------------------------ log
    def log(self, message: str):
        self.worker.editor_logging_handler.info(f"[ImmersiveProvider] {message}")

    def log_error(self, message: str):
        self.worker.editor_logging_handler.error(f"[ImmersiveProvider] {message}")

    def _is_exit(self, text: str) -> bool:
        # Short ambiguous words ("stop", "done") only match as a whole word
        # (so "yeah, stop" still exits but "stopped" in normal conversation
        # does not false-trigger). Distinctive multi-word phrases ("never
        # mind") still match anywhere in the reply.
        lower = (text or "").lower().strip().rstrip(".!?")
        if not lower:
            return False
        tokens = set(lower.split())
        return any((word in lower if " " in word else word in tokens) for word in EXIT_WORDS)

    # ---------------------------------------------------------- backend I/O
    def backend_url(self) -> str:
        """Backend base URL from Settings -> API Keys, else the constant."""
        try:
            configured = self.capability_worker.get_api_keys(BACKEND_URL_KEY)
        except Exception:
            configured = None
        return ((configured or BACKEND_URL) or "").strip().rstrip("/")

    def base_candidates(self) -> list[str]:
        """The configured base plus base + /api (some deploys serve the
        contract under an /api prefix). A detected winner is cached."""
        if self.api_base:
            return [self.api_base]
        base = self.backend_url()
        if not base:
            return []
        return [base] if base.endswith("/api") else [base, base + "/api"]

    def api_get(self, path: str, api_key: str | None):
        """Blocking GET, run via asyncio.to_thread. Returns parsed JSON or None.
        A non-JSON reply (e.g. an SPA catch-all page) moves to the next base."""
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        for base in self.base_candidates():
            try:
                response = requests.get(
                    f"{base}{path}", headers=headers, timeout=REQUEST_TIMEOUT
                )
                if response.status_code != 200:
                    continue
                data = response.json()
            except ValueError:
                continue
            except Exception as error:
                self.log_error(f"GET {base}{path} failed: {error!r}")
                continue
            self.api_base = base
            return data
        return None

    def api_post(self, path: str, payload: dict, api_key: str | None) -> bool:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        for base in self.base_candidates():
            try:
                response = requests.post(
                    f"{base}{path}", json=payload, headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if response.status_code not in (200, 201):
                    continue
                response.json()
            except ValueError:
                continue
            except Exception as error:
                self.log_error(f"POST {base}{path} failed: {error!r}")
                continue
            self.api_base = base
            return True
        return False

    # ------------------------------------------------------- request loading
    async def load_open_requests(self, api_key: str | None) -> list[dict]:
        data = await asyncio.to_thread(self.api_get, "/requests?status=open", api_key)
        if data and data.get("requests"):
            return data["requests"]

        if await self.capability_worker.check_if_file_exists(REQUESTS_FILE, False):
            try:
                raw = await self.capability_worker.read_file(REQUESTS_FILE, False)
                stored = json.loads(raw).get("requests", [])
                open_requests = [r for r in stored if r.get("status") == "open"]
                if open_requests:
                    self.log(f"Loaded {len(open_requests)} open request(s) from file")
                    return open_requests
            except Exception as error:
                self.log_error(f"Bad {REQUESTS_FILE}: {error!r}")

        self.log("No backend or stored requests; using demo request")
        return [DEMO_REQUEST]

    async def save_booking(self, request: dict, quote: dict):
        """Mark the request booked in the shared file so later skills see it."""
        stored = {"requests": []}
        try:
            if await self.capability_worker.check_if_file_exists(REQUESTS_FILE, False):
                raw = await self.capability_worker.read_file(REQUESTS_FILE, False)
                stored = json.loads(raw)
        except Exception as error:
            self.log_error(f"Could not read {REQUESTS_FILE}: {error!r}")

        found = False
        for entry in stored.get("requests", []):
            if entry.get("id") == request["id"]:
                entry["status"] = "booked"
                entry["booked_provider"] = quote["provider"]
                found = True
        if not found:
            stored.setdefault("requests", []).append(
                {**request, "status": "booked", "booked_provider": quote["provider"]}
            )
        # Delete-then-write so a partial write can't corrupt the shared JSON.
        try:
            if await self.capability_worker.check_if_file_exists(REQUESTS_FILE, False):
                self.capability_worker.delete_file(REQUESTS_FILE, False)
        except Exception as error:
            self.log_error(f"Could not delete {REQUESTS_FILE}: {error!r}")
        await self.capability_worker.write_file(
            REQUESTS_FILE, json.dumps(stored, indent=2), False
        )

    # ------------------------------------------------------------- quotes
    async def fetch_quotes(self, request: dict, api_key: str | None) -> list[dict]:
        data = await asyncio.to_thread(
            self.api_get, f"/requests/{request['id']}/quotes", api_key
        )
        if data and data.get("quotes"):
            return data["quotes"]
        self.log("Using demo quotes")
        return DEMO_QUOTES

    def rank_quotes(self, quotes: list[dict]) -> list[dict]:
        prices = [q["price"] for q in quotes]
        low, high = min(prices), max(prices)

        def score(quote: dict) -> float:
            price_norm = 1.0 if high == low else (high - quote["price"]) / (high - low)
            price_score = 0.5 + 0.5 * price_norm
            rating_score = quote.get("rating", 3.0) / 5.0
            reliability = quote.get("reliability", 0.5)
            availability = quote.get("availability", "")
            if "today" in availability:
                availability_score = 1.0
            elif "tomorrow" in availability:
                availability_score = 0.75
            else:
                availability_score = 0.5
            return (
                WEIGHTS["price"] * price_score
                + WEIGHTS["rating"] * rating_score
                + WEIGHTS["reliability"] * reliability
                + WEIGHTS["availability"] * availability_score
            )

        return sorted(quotes, key=score, reverse=True)

    # ------------------------------------------------------------- speech
    def recap(self, ranked: list[dict]) -> str:
        top = ranked[0]
        recap = (
            f"Top pick: {top['provider']} at {top['price']} dollars, "
            f"rated {top['rating']}, available {top['availability']}."
        )
        if len(ranked) > 1:
            runner = ranked[1]
            recap += (
                f" Second is {runner['provider']} at {runner['price']} dollars;"
                " say book the first, hear details, or stop."
            )
        return recap

    def details(self, quote: dict) -> str:
        percent = int(quote.get("reliability", 0) * 100)
        return (
            f"{quote['provider']} charges {quote['price']} dollars and is rated "
            f"{quote['rating']} out of 5. They complete {percent} percent of jobs "
            f"on time and can come {quote['availability']}."
        )

    def classify(self, user_input: str, ranked: list[dict]) -> str:
        names = ", ".join(q["provider"] for q in ranked)
        token = self.capability_worker.text_to_text_response(
            user_input,
            system_prompt=INTENT_PROMPT.format(count=len(ranked), names=names),
        )
        return (token or "OTHER").strip().upper()

    @staticmethod
    def parse_index(token: str, prefix: str, count: int) -> int | None:
        if not token.startswith(prefix):
            return None
        try:
            index = int(token.split(":", 1)[1]) - 1
        except (IndexError, ValueError):
            return None
        return index if 0 <= index < count else None

    # ------------------------------------------------------- request choice
    async def choose_request(self, open_requests: list[dict]) -> dict | None:
        if len(open_requests) == 1:
            return open_requests[0]

        categories = ", ".join(r["category"] for r in open_requests)
        await self.capability_worker.speak(
            f"You have {len(open_requests)} open requests: {categories}. Which one?"
        )
        for _ in range(2):
            reply = await self.capability_worker.user_response()
            if not reply:
                continue
            lowered = reply.lower()
            if self._is_exit(reply):
                return None
            for i, request in enumerate(open_requests):
                if request["category"].lower() in lowered or (
                    i < len(ORDINALS) and ORDINALS[i] in lowered
                ):
                    return request
            await self.capability_worker.speak(LINE_WHICH_REQUEST)
        return open_requests[0]

    # --------------------------------------------------------------- main
    async def run(self):
        try:
            api_key = self.capability_worker.get_api_keys(API_KEY_NAME)

            # Filler before a potentially slow lookup — never leave dead air.
            await self.capability_worker.speak(LINE_CHECKING)
            open_requests = await self.load_open_requests(api_key)
            if not open_requests:
                await self.capability_worker.speak(LINE_NO_REQUESTS)
                return

            request = await self.choose_request(open_requests)
            if request is None:
                await self.capability_worker.speak(LINE_LATER)
                return

            await self.capability_worker.speak(
                f"Checking quotes for your {request['category']} request."
            )
            quotes = await self.fetch_quotes(request, api_key)
            if not quotes:
                await self.capability_worker.speak(LINE_NO_QUOTES)
                return

            ranked = self.rank_quotes(quotes)
            await self.capability_worker.speak(self.recap(ranked))

            empty_replies = 0
            while True:
                user_input = await self.capability_worker.user_response()
                if not user_input or not user_input.strip():
                    empty_replies += 1
                    if empty_replies == 2:
                        await self.capability_worker.speak(LINE_STILL_THERE)
                    elif empty_replies >= 3:
                        await self.capability_worker.speak(LINE_QUOTES_SAVED)
                        return
                    continue
                empty_replies = 0
                if self._is_exit(user_input):
                    await self.capability_worker.speak(LINE_QUOTES_SAVED)
                    return

                token = self.classify(user_input, ranked)
                self.log(f"Intent: {token} for input: {user_input!r}")

                select_index = self.parse_index(token, "SELECT", len(ranked))
                details_index = self.parse_index(token, "DETAILS", len(ranked))

                if select_index is not None:
                    chosen = ranked[select_index]
                    # run_confirmation_loop appends its own yes/no instruction.
                    confirmed = await self.capability_worker.run_confirmation_loop(
                        f"Book {chosen['provider']} for {chosen['price']} dollars, "
                        f"available {chosen['availability']}?"
                    )
                    if confirmed:
                        await self.capability_worker.speak(LINE_BOOKING)
                        booked = await asyncio.to_thread(
                            self.api_post,
                            f"/quotes/{chosen['id']}/accept",
                            {"request_id": request["id"]},
                            api_key,
                        )
                        if not booked:
                            self.log("Backend accept failed or unavailable; saving locally")
                        await self.save_booking(request, chosen)
                        await self.capability_worker.speak(
                            f"Done, {chosen['provider']} is booked, coming {chosen['availability']}. "
                            "You'll get a confirmation shortly."
                        )
                        return
                    await self.capability_worker.speak(LINE_NOT_BOOKED)
                elif details_index is not None:
                    await self.capability_worker.speak(self.details(ranked[details_index]))
                elif token == "REPEAT":
                    await self.capability_worker.speak(self.recap(ranked))
                elif token == "EXIT":
                    await self.capability_worker.speak(LINE_QUOTES_SAVED)
                    return
                else:
                    await self.capability_worker.speak(LINE_HELP)
        except Exception as error:
            self.log_error(f"Unhandled error: {error!r}")
            try:
                await self.capability_worker.speak(LINE_ERROR)
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()
