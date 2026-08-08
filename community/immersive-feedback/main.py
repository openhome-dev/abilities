import asyncio
import json

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# IMMERSIVE FEEDBACK (Skill)
# Entry point after a provider visit: find the user's recent booked jobs,
# collect a 1-5 satisfaction rating plus an optional comment by voice, and
# POST it to the ranking backend so personalized provider scores improve.
#
# Flow: load booked jobs -> pick one -> rating -> optional comment ->
# confirm -> POST + persist -> resume_normal_flow().
#
# Shared-state contract (abilities cannot chain, they share files):
#   immersive_requests.json = {"requests": [
#       {"id", "category", "description",
#        "status": "open"|"booked"|"rated",
#        "booked_provider" (set by the provider skill),
#        "feedback": {"rating", "comment"} (set here)} ]}
# =============================================================================

BACKEND_URL = ""                                   # optional hardcoded fallback URL
BACKEND_URL_KEY = "immersive_backend_url"          # Settings -> API Keys: your deployed backend URL
API_KEY_NAME = "immersive_api_key"                 # optional, Settings -> API Keys
REQUEST_TIMEOUT = 10
REQUESTS_FILE = "immersive_requests.json"

EXIT_WORDS = {"stop", "exit", "quit", "cancel", "goodbye", "bye", "never mind", "nevermind"}
SKIP_WORDS = {"skip", "no", "nothing", "nope", "that's it", "thats it", "all good"}

DEMO_JOB = {
    "id": "demo-1",
    "category": "plumbing",
    "description": "leaking pipe under the kitchen sink",
    "status": "booked",
    "booked_provider": "Rapid Plumbing Co",
}

RATING_PROMPT = (
    "You classify one voice reply from a user rating a home service provider. "
    "Reply with EXACTLY one token:\n"
    "RATING:<n> where n is 1 to 5 if they gave a score (map words: terrible/awful=1, "
    "bad/poor=2, okay/fine/average=3, good/great=4, excellent/amazing/perfect=5, "
    "'four stars'=4, and so on).\n"
    "EXIT if they want to stop or rate later.\n"
    "OTHER for anything else.\n"
    "Output only the token."
)

ORDINALS = ("first", "second", "third", "fourth", "fifth")

# Spoken lines — fork the persona by editing these, never the logic below.
LINE_CHECKING = "One sec, checking your recent jobs."
LINE_NO_JOBS = "I don't see any booked jobs to rate yet. Say check my quotes to book a provider first."
LINE_LATER = "Okay, we can do the rating later."
LINE_ASK_RATING = "How was {provider} for the {category} job, on a scale of one to five?"
LINE_ASK_COMMENT = "Got it. Anything to add for other homeowners, or say skip?"
LINE_RATING_RETRY = "Just a number from one to five works. How would you rate it?"
LINE_STILL_THERE = "Still there? Give a rating from one to five, or say stop."
LINE_SAVED_FOR_LATER = "No problem, you can rate the job anytime. Say rate my service when you're ready."
LINE_SUBMITTING = "Submitting your feedback now."
LINE_NOT_SUBMITTED = "Okay, I won't submit that. Say rate my service anytime to try again."
LINE_THANKS = "Thanks, your {rating} star rating for {provider} is in. It'll sharpen your future provider matches."
LINE_WHICH_JOB = "Sorry, which job was that?"
LINE_ERROR = "Sorry, something went wrong saving your feedback. Please try again."


class ImmersiveFeedbackCapability(MatchingCapability):
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
        self.worker.editor_logging_handler.info(f"[ImmersiveFeedback] {message}")

    @staticmethod
    def _matches_any_word(text: str, words) -> bool:
        # Short ambiguous words ("no", "stop") only match as a whole word (so
        # "yeah, stop" still matches but "no" inside "noisy" or "stop"
        # inside "stopped" does not false-trigger). Distinctive multi-word
        # phrases ("that's it") still match anywhere in the reply.
        lower = (text or "").lower().strip().rstrip(".!?")
        if not lower:
            return False
        tokens = set(lower.split())
        return any((word in lower if " " in word else word in tokens) for word in words)

    def _is_exit(self, text: str) -> bool:
        return self._matches_any_word(text, EXIT_WORDS)

    def log_error(self, message: str):
        self.worker.editor_logging_handler.error(f"[ImmersiveFeedback] {message}")

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

    # ---------------------------------------------------------- job loading
    async def load_rateable_jobs(self, api_key: str | None) -> list[dict]:
        data = await asyncio.to_thread(self.api_get, "/requests?status=booked", api_key)
        if data and data.get("requests"):
            return data["requests"]

        if await self.capability_worker.check_if_file_exists(REQUESTS_FILE, False):
            try:
                raw = await self.capability_worker.read_file(REQUESTS_FILE, False)
                stored = json.loads(raw).get("requests", [])
                booked = [r for r in stored if r.get("status") == "booked"]
                if booked:
                    self.log(f"Loaded {len(booked)} booked job(s) from file")
                    return booked
            except Exception as error:
                self.log_error(f"Bad {REQUESTS_FILE}: {error!r}")

        self.log("No backend or stored jobs; using demo job")
        return [DEMO_JOB]

    async def save_feedback(self, job: dict, rating: int, comment: str):
        """Mark the job rated in the shared file so it isn't offered again."""
        stored = {"requests": []}
        try:
            if await self.capability_worker.check_if_file_exists(REQUESTS_FILE, False):
                raw = await self.capability_worker.read_file(REQUESTS_FILE, False)
                stored = json.loads(raw)
        except Exception as error:
            self.log_error(f"Could not read {REQUESTS_FILE}: {error!r}")

        feedback = {"rating": rating, "comment": comment}
        found = False
        for entry in stored.get("requests", []):
            if entry.get("id") == job["id"]:
                entry["status"] = "rated"
                entry["feedback"] = feedback
                found = True
        if not found:
            stored.setdefault("requests", []).append(
                {**job, "status": "rated", "feedback": feedback}
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

    # ------------------------------------------------------------- parsing
    def classify_rating(self, user_input: str) -> int | None:
        """Return 1-5, -1 for EXIT, or None if unparseable."""
        token = (
            self.capability_worker.text_to_text_response(
                user_input, system_prompt=RATING_PROMPT
            )
            or "OTHER"
        ).strip().upper()
        self.log(f"Rating token: {token} for input: {user_input!r}")
        if token == "EXIT":
            return -1
        if token.startswith("RATING:"):
            try:
                rating = int(token.split(":", 1)[1])
            except (IndexError, ValueError):
                return None
            if 1 <= rating <= 5:
                return rating
        return None

    # ----------------------------------------------------------- job choice
    async def choose_job(self, jobs: list[dict]) -> dict | None:
        if len(jobs) == 1:
            return jobs[0]

        labels = ", ".join(
            f"{j.get('booked_provider', 'a provider')} for {j['category']}" for j in jobs
        )
        await self.capability_worker.speak(
            f"You have {len(jobs)} finished jobs: {labels}. Which one?"
        )
        for _ in range(2):
            reply = await self.capability_worker.user_response()
            if not reply:
                continue
            lowered = reply.lower()
            if self._is_exit(reply):
                return None
            for i, job in enumerate(jobs):
                if (
                    job["category"].lower() in lowered
                    or job.get("booked_provider", "").lower() in lowered
                    or (i < len(ORDINALS) and ORDINALS[i] in lowered)
                ):
                    return job
            await self.capability_worker.speak(LINE_WHICH_JOB)
        return jobs[0]

    # --------------------------------------------------------------- main
    async def run(self):
        try:
            api_key = self.capability_worker.get_api_keys(API_KEY_NAME)

            # Filler before a potentially slow lookup — never leave dead air.
            await self.capability_worker.speak(LINE_CHECKING)
            jobs = await self.load_rateable_jobs(api_key)
            if not jobs:
                await self.capability_worker.speak(LINE_NO_JOBS)
                return

            job = await self.choose_job(jobs)
            if job is None:
                await self.capability_worker.speak(LINE_LATER)
                return

            provider = job.get("booked_provider", "the provider")
            await self.capability_worker.speak(
                LINE_ASK_RATING.format(provider=provider, category=job["category"])
            )

            rating = None
            empty_replies = 0
            while rating is None:
                user_input = await self.capability_worker.user_response()
                if not user_input or not user_input.strip():
                    empty_replies += 1
                    if empty_replies == 2:
                        await self.capability_worker.speak(LINE_STILL_THERE)
                    elif empty_replies >= 3:
                        await self.capability_worker.speak(LINE_SAVED_FOR_LATER)
                        return
                    continue
                empty_replies = 0
                if self._is_exit(user_input):
                    await self.capability_worker.speak(LINE_SAVED_FOR_LATER)
                    return
                rating = self.classify_rating(user_input)
                if rating == -1:
                    await self.capability_worker.speak(LINE_SAVED_FOR_LATER)
                    return
                if rating is None:
                    await self.capability_worker.speak(LINE_RATING_RETRY)

            await self.capability_worker.speak(LINE_ASK_COMMENT)
            comment_reply = await self.capability_worker.user_response()
            comment = ""
            if comment_reply and comment_reply.strip():
                if not self._matches_any_word(comment_reply, SKIP_WORDS | EXIT_WORDS):
                    comment = comment_reply.strip()

            # run_confirmation_loop appends its own yes/no instruction.
            confirmed = await self.capability_worker.run_confirmation_loop(
                f"Submit {rating} stars for {provider}?"
            )
            if not confirmed:
                await self.capability_worker.speak(LINE_NOT_SUBMITTED)
                return

            await self.capability_worker.speak(LINE_SUBMITTING)
            posted = await asyncio.to_thread(
                self.api_post,
                "/feedback",
                {
                    "request_id": job["id"],
                    "provider": provider,
                    "rating": rating,
                    "comment": comment,
                },
                api_key,
            )
            if not posted:
                self.log("Backend feedback POST failed or unavailable; saving locally")
            await self.save_feedback(job, rating, comment)

            await self.capability_worker.speak(
                LINE_THANKS.format(rating=rating, provider=provider)
            )
        except Exception as error:
            self.log_error(f"Unhandled error: {error!r}")
            try:
                await self.capability_worker.speak(LINE_ERROR)
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()
