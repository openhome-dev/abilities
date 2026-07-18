import asyncio

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# IMMERSIVE QUOTE WATCHER — status skill (pairs with background.py, which does
# the always-on polling). Trigger "quote watcher status" to hear what the
# watcher currently sees: open requests and how many quotes each has.
# =============================================================================

BACKEND_URL = ""                                   # optional hardcoded fallback URL
BACKEND_URL_KEY = "immersive_backend_url"          # Settings -> API Keys
API_KEY_NAME = "immersive_api_key"                 # optional
REQUEST_TIMEOUT = 10

LINE_NO_BACKEND = "The quote watcher is idle because no backend is connected yet."
LINE_NO_OPEN = "No open requests right now. The watcher will speak up when new quotes arrive."
LINE_ERROR = "I couldn't reach the quote service just now. I'll keep watching."


class ImmersiveQuoteWatcherCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def backend_url(self) -> str:
        try:
            configured = self.capability_worker.get_api_keys(BACKEND_URL_KEY)
        except Exception:
            configured = None
        return ((configured or BACKEND_URL) or "").strip().rstrip("/")

    def fetch_open_requests(self) -> list[dict] | None:
        base = self.backend_url()
        if not base:
            return None
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
                return response.json().get("requests", [])
            except ValueError:
                continue
            except Exception as error:
                self.worker.editor_logging_handler.error(f"[QuoteWatcher] Status fetch failed: {error!r}")
                continue
        return None

    async def run(self):
        try:
            if not self.backend_url():
                await self.capability_worker.speak(LINE_NO_BACKEND)
                return
            open_requests = await asyncio.to_thread(self.fetch_open_requests)
            if open_requests is None:
                await self.capability_worker.speak(LINE_ERROR)
                return
            if not open_requests:
                await self.capability_worker.speak(LINE_NO_OPEN)
                return
            top = open_requests[0]
            total_quotes = sum(r.get("quote_count", 0) for r in open_requests)
            await self.capability_worker.speak(
                f"Watching {len(open_requests)} open request{'s' if len(open_requests) != 1 else ''} "
                f"with {total_quotes} quotes so far, newest is the {top.get('category', 'home')} job. "
                "Say check my quotes to compare."
            )
        except Exception as error:
            self.worker.editor_logging_handler.error(f"[QuoteWatcher] Status error: {error!r}")
        finally:
            self.capability_worker.resume_normal_flow()
