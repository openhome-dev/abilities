import asyncio

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# IMMERSIVE QUOTE WATCHER (Background Daemon)
# Auto-starts with the agent session. Polls the Immersive backend for open
# requests that have received provider quotes and announces each one once:
# "You have 3 quotes for the plumbing job. Say check my quotes to compare."
#
# Silent when no backend URL is configured (Settings -> API Keys ->
# immersive_backend_url) or the backend is unreachable — it never breaks the
# conversation, it only adds to it. By design this loop never calls
# resume_normal_flow(); background daemons run for the whole session.
# =============================================================================

BACKEND_URL = ""                                   # optional hardcoded fallback URL
BACKEND_URL_KEY = "immersive_backend_url"          # Settings -> API Keys
API_KEY_NAME = "immersive_api_key"                 # optional
REQUEST_TIMEOUT = 10
POLL_SECONDS = 30.0
STARTUP_GRACE_SECONDS = 20.0

LINE_QUOTES_READY = "Good news, you have {count} quotes for the {category} job. Say check my quotes to compare."


class ImmersiveQuoteWatcherBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False
    api_base: str = None

    # {{register capability}}

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        # Daemons pass `self` (not self.worker) so the SDK can read
        # background_daemon_mode off this capability — the documented
        # convention for background abilities.
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.watch())

    def log(self, message: str):
        self.worker.editor_logging_handler.info(f"[QuoteWatcher] {message}")

    def backend_url(self) -> str:
        try:
            configured = self.capability_worker.get_api_keys(BACKEND_URL_KEY)
        except Exception:
            configured = None
        return ((configured or BACKEND_URL) or "").strip().rstrip("/")

    def fetch_open_requests(self) -> list[dict]:
        """Blocking GET, run via asyncio.to_thread. Empty list on any failure.
        Tries the configured base and base + /api; caches the working one."""
        if self.api_base:
            candidates = [self.api_base]
        else:
            base = self.backend_url()
            if not base:
                return []
            candidates = [base] if base.endswith("/api") else [base, base + "/api"]
        try:
            api_key = self.capability_worker.get_api_keys(API_KEY_NAME)
        except Exception:
            api_key = None
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        for candidate in candidates:
            try:
                response = requests.get(
                    f"{candidate}/requests?status=open", headers=headers, timeout=REQUEST_TIMEOUT
                )
                if response.status_code != 200:
                    continue
                data = response.json()
            except ValueError:
                continue
            except Exception as error:
                self.worker.editor_logging_handler.error(f"[QuoteWatcher] Poll failed: {error!r}")
                continue
            self.api_base = candidate
            return data.get("requests", [])
        return []

    async def watch(self):
        announced: set[str] = set()
        self.log("Watching for new provider quotes")
        # Grace period so the daemon never talks over the session greeting.
        await self.worker.session_tasks.sleep(STARTUP_GRACE_SECONDS)

        while True:
            try:
                open_requests = await asyncio.to_thread(self.fetch_open_requests)
                for req in open_requests:
                    req_id = req.get("id")
                    count = req.get("quote_count", 0)
                    if not req_id or req_id in announced or count < 1:
                        continue
                    announced.add(req_id)
                    self.log(f"Announcing {count} quote(s) for request {req_id}")
                    await self.capability_worker.speak(
                        LINE_QUOTES_READY.format(count=count, category=req.get("category", "home service"))
                    )
            except Exception as error:
                self.worker.editor_logging_handler.error(f"[QuoteWatcher] Loop error: {error!r}")
            await self.worker.session_tasks.sleep(POLL_SECONDS)
