import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CONFIG
# =============================================================================

# Get a Personal Access Token from: https://github.com/settings/tokens
# Scopes needed: repo, notifications, read:user
# For testing, paste your token here. Before submitting PR, revert to placeholder.
GITHUB_TOKEN = "REPLACE_WITH_YOUR_GITHUB_TOKEN"

GITHUB_API_BASE = "https://api.github.com"

PREFS_FILE = "github_voice_manager_prefs.json"

EXIT_WORDS = [
    "done", "exit", "stop", "quit", "bye", "goodbye",
    "nothing else", "all good", "nope", "no thanks",
    "i'm good", "im good", "that's it", "thats it",
    "go to sleep", "never mind", "cancel",
]

FILLER_LINES = [
    "One sec, checking GitHub.",
    "Let me pull that up.",
    "Hang on, fetching that from GitHub.",
    "Give me a moment.",
]


# =============================================================================
# GITHUB API HELPERS
# =============================================================================

def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_get(endpoint: str, params: dict = None, timeout: int = 10) -> Optional[Any]:
    """Make a GET request to the GitHub API. Returns parsed JSON or None."""
    try:
        resp = requests.get(
            f"{GITHUB_API_BASE}{endpoint}",
            headers=_gh_headers(),
            params=params or {},
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def fetch_notifications(all_notifs: bool = False) -> Optional[List[Dict]]:
    params = {"all": "true"} if all_notifs else {}
    return _gh_get("/notifications", params=params)


def fetch_user_prs(username: str) -> Optional[List[Dict]]:
    """Fetch open PRs authored by the user across all repos."""
    query = f"is:open is:pr author:{username}"
    data = _gh_get("/search/issues", params={"q": query, "per_page": "10"})
    if data and "items" in data:
        return data["items"]
    return None


def fetch_repo_issues(repo: str, state: str = "open") -> Optional[List[Dict]]:
    """Fetch issues for a given repo (owner/repo format)."""
    return _gh_get(f"/repos/{repo}/issues", params={"state": state, "per_page": "10"})


def fetch_repo_prs(repo: str, state: str = "open") -> Optional[List[Dict]]:
    """Fetch pull requests for a given repo."""
    return _gh_get(f"/repos/{repo}/pulls", params={"state": state, "per_page": "10"})


def fetch_user_info() -> Optional[Dict]:
    """Fetch authenticated user info."""
    return _gh_get("/user")


def fetch_user_repos(sort: str = "pushed") -> Optional[List[Dict]]:
    """Fetch the user's repos sorted by recent activity."""
    return _gh_get("/user/repos", params={"sort": sort, "per_page": "10", "affiliation": "owner,collaborator"})


def mark_notifications_read() -> bool:
    """Mark all notifications as read."""
    try:
        resp = requests.put(
            f"{GITHUB_API_BASE}/notifications",
            headers=_gh_headers(),
            json={"last_read_at": datetime.now(timezone.utc).isoformat()},
            timeout=10,
        )
        return resp.status_code in (202, 205)
    except Exception:
        return False


def star_repo(repo: str) -> bool:
    """Star a repository."""
    try:
        headers = _gh_headers()
        headers["Content-Length"] = "0"
        resp = requests.put(
            f"{GITHUB_API_BASE}/user/starred/{repo}",
            headers=headers,
            timeout=10,
        )
        return resp.status_code in (204, 304)
    except Exception:
        return False


def unstar_repo(repo: str) -> bool:
    """Unstar a repository."""
    try:
        resp = requests.delete(
            f"{GITHUB_API_BASE}/user/starred/{repo}",
            headers=_gh_headers(),
            timeout=10,
        )
        return resp.status_code == 204
    except Exception:
        return False


def check_star(repo: str) -> Optional[bool]:
    """Check if user has starred a repo. Returns True/False or None on error."""
    try:
        resp = requests.get(
            f"{GITHUB_API_BASE}/user/starred/{repo}",
            headers=_gh_headers(),
            timeout=10,
        )
        if resp.status_code == 204:
            return True
        if resp.status_code == 404:
            return False
        return None
    except Exception:
        return None


def create_issue(repo: str, title: str, body: str = "") -> Optional[Dict]:
    """Create an issue on a repo. Returns the created issue data or None."""
    try:
        payload = {"title": title}
        if body:
            payload["body"] = body
        resp = requests.post(
            f"{GITHUB_API_BASE}/repos/{repo}/issues",
            headers=_gh_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code == 201:
            return resp.json()
        return None
    except Exception:
        return None


def _time_ago(iso_str: str) -> str:
    """Convert ISO timestamp to human-friendly relative time."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        minutes = int(diff.total_seconds() / 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = hours // 24
        return f"{days} day{'s' if days != 1 else ''} ago"
    except Exception:
        return "recently"


# =============================================================================
# CAPABILITY CLASS
# =============================================================================

class GitHubVoiceManagerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    history: list = []
    username: str = ""
    default_repo: str = ""

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.history = []
        self.username = ""
        self.default_repo = ""
        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # LOGGING
    # -------------------------------------------------------------------------

    def log(self, msg: str):
        self.worker.editor_logging_handler.info(f"[GitHubManager] {msg}")

    def log_err(self, msg: str):
        self.worker.editor_logging_handler.error(f"[GitHubManager] {msg}")

    # -------------------------------------------------------------------------
    # FILLER SPEECH
    # -------------------------------------------------------------------------

    async def filler(self):
        import random
        await self.capability_worker.speak(random.choice(FILLER_LINES))

    # -------------------------------------------------------------------------
    # PERSISTENCE — remember username & default repo across sessions
    # -------------------------------------------------------------------------

    async def load_prefs(self):
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                prefs = json.loads(raw)
                self.username = prefs.get("username", "")
                self.default_repo = prefs.get("default_repo", "")
        except Exception as e:
            self.log_err(f"Error loading prefs: {e}")

    async def save_prefs(self):
        try:
            prefs = {"username": self.username, "default_repo": self.default_repo}
            await self.capability_worker.delete_file(PREFS_FILE, False)
            await self.capability_worker.write_file(PREFS_FILE, json.dumps(prefs), False)
        except Exception as e:
            self.log_err(f"Error saving prefs: {e}")

    # -------------------------------------------------------------------------
    # SETUP — fetch username from API or prefs
    # -------------------------------------------------------------------------

    async def ensure_username(self) -> bool:
        if self.username:
            return True
        await self.filler()
        user_info = await asyncio.to_thread(fetch_user_info)
        if user_info and user_info.get("login"):
            self.username = user_info["login"]
            await self.save_prefs()
            return True
        await self.capability_worker.speak(
            "I couldn't connect to GitHub. Please check that the token is configured correctly."
        )
        return False

    # -------------------------------------------------------------------------
    # INTENT CLASSIFICATION
    # -------------------------------------------------------------------------

    def classify_intent(self, user_input: str) -> dict:
        prompt = (
            "Classify this GitHub-related voice command. Return ONLY valid JSON.\n"
            "Possible intents: notifications, my_prs, repo_issues, repo_prs, "
            "repos, mark_read, summary, star, unstar, create_issue, help, unknown\n"
            "If a repo name is mentioned, include it in 'repo' field (owner/repo format).\n"
            "If an issue title is mentioned, include it in 'title' field.\n"
            "If an issue description is mentioned, include it in 'body' field.\n"
            '{"intent": "...", "repo": "...", "title": "...", "body": "...", "details": "..."}\n\n'
            f"User: {user_input}"
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            return {"intent": "unknown"}

    # -------------------------------------------------------------------------
    # TRIGGER CONTEXT — read what the user said to trigger this ability
    # -------------------------------------------------------------------------

    def get_trigger_context(self) -> str:
        try:
            full_history = self.capability_worker.get_full_message_history()
            if full_history:
                recent = [
                    m.get("content", "") for m in full_history[-3:]
                    if m.get("role") == "user"
                ]
                return " ".join(recent)
        except Exception:
            pass
        return ""

    # -------------------------------------------------------------------------
    # HANDLERS
    # -------------------------------------------------------------------------

    async def handle_notifications(self):
        await self.filler()
        notifs = await asyncio.to_thread(fetch_notifications)
        if notifs is None:
            await self.capability_worker.speak("I couldn't fetch your notifications right now.")
            return

        if len(notifs) == 0:
            await self.capability_worker.speak("You're all clear — no unread notifications.")
            return

        count = len(notifs)
        await self.capability_worker.speak(
            f"You have {count} unread notification{'s' if count != 1 else ''}."
        )

        # Summarize top 5
        summaries = []
        for n in notifs[:5]:
            repo = n.get("repository", {}).get("full_name", "unknown repo")
            reason = n.get("reason", "update")
            title = n.get("subject", {}).get("title", "untitled")
            summaries.append(f"{reason} on {repo}: {title}")

        summary_text = ". ".join(summaries)
        response = self.capability_worker.text_to_text_response(
            f"Summarize these GitHub notifications in 2-3 short spoken sentences. "
            f"Be conversational and brief:\n{summary_text}",
            system_prompt="You are a concise voice assistant for GitHub. Keep it under 3 sentences.",
        )
        await self.capability_worker.speak(response)

        if count > 0:
            await self.capability_worker.speak("Want me to mark them all as read?")
            user_input = await self.capability_worker.user_response()
            if user_input and any(w in user_input.lower() for w in ["yes", "yeah", "sure", "yep", "do it"]):
                success = await asyncio.to_thread(mark_notifications_read)
                if success:
                    await self.capability_worker.speak("Done, all marked as read.")
                else:
                    await self.capability_worker.speak("Hmm, couldn't mark them as read. Try again later.")

    async def handle_my_prs(self):
        if not await self.ensure_username():
            return
        await self.filler()
        prs = await asyncio.to_thread(fetch_user_prs, self.username)
        if prs is None:
            await self.capability_worker.speak("Couldn't fetch your pull requests right now.")
            return

        if len(prs) == 0:
            await self.capability_worker.speak("You don't have any open pull requests.")
            return

        count = len(prs)
        summaries = []
        for pr in prs[:5]:
            repo = pr.get("repository_url", "").split("/repos/")[-1] if "repository_url" in pr else "unknown"
            title = pr.get("title", "untitled")
            created = _time_ago(pr.get("created_at", ""))
            summaries.append(f"{title} on {repo}, opened {created}")

        summary_text = ". ".join(summaries)
        response = self.capability_worker.text_to_text_response(
            f"You have {count} open PR{'s' if count != 1 else ''}. "
            f"Summarize these in 2-3 short spoken sentences:\n{summary_text}",
            system_prompt="You are a concise voice assistant for GitHub. Keep it brief and conversational.",
        )
        await self.capability_worker.speak(response)

    async def handle_repo_issues(self, repo: str = ""):
        if not repo:
            repo = self.default_repo
        if not repo:
            answer = await self.capability_worker.run_io_loop(
                "Which repo? Give me the owner slash repo name."
            )
            if answer and "/" in answer:
                repo = answer.strip()
            else:
                # Use LLM to extract repo name from messy voice input
                extracted = self.capability_worker.text_to_text_response(
                    f"Extract the GitHub repository name in owner/repo format from this voice input. "
                    f"Return ONLY the owner/repo string, nothing else:\n{answer}"
                )
                repo = extracted.strip()

        if not repo or "/" not in repo:
            await self.capability_worker.speak("I didn't catch a valid repo name. Try again.")
            return

        await self.filler()
        issues = await asyncio.to_thread(fetch_repo_issues, repo)
        if issues is None:
            await self.capability_worker.speak(f"Couldn't fetch issues for {repo}. Check the repo name.")
            return

        # Filter out PRs (GitHub API returns PRs as issues too)
        issues = [i for i in issues if "pull_request" not in i]

        if len(issues) == 0:
            await self.capability_worker.speak(f"No open issues on {repo}. Nice work!")
            return

        count = len(issues)
        summaries = []
        for issue in issues[:5]:
            title = issue.get("title", "untitled")
            num = issue.get("number", "")
            created = _time_ago(issue.get("created_at", ""))
            summaries.append(f"Issue {num}: {title}, opened {created}")

        summary_text = ". ".join(summaries)
        response = self.capability_worker.text_to_text_response(
            f"{repo} has {count} open issue{'s' if count != 1 else ''}. "
            f"Summarize the top ones in 2-3 short spoken sentences:\n{summary_text}",
            system_prompt="You are a concise voice assistant for GitHub. Be brief.",
        )
        await self.capability_worker.speak(response)

        # Remember this repo for follow-ups
        self.default_repo = repo
        await self.save_prefs()

    async def handle_repo_prs(self, repo: str = ""):
        if not repo:
            repo = self.default_repo
        if not repo:
            answer = await self.capability_worker.run_io_loop(
                "Which repo? Give me the owner slash repo name."
            )
            if answer:
                extracted = self.capability_worker.text_to_text_response(
                    f"Extract the GitHub repository name in owner/repo format from this voice input. "
                    f"Return ONLY the owner/repo string, nothing else:\n{answer}"
                )
                repo = extracted.strip()

        if not repo or "/" not in repo:
            await self.capability_worker.speak("I didn't catch a valid repo name. Try again.")
            return

        await self.filler()
        prs = await asyncio.to_thread(fetch_repo_prs, repo)
        if prs is None:
            await self.capability_worker.speak(f"Couldn't fetch PRs for {repo}.")
            return

        if len(prs) == 0:
            await self.capability_worker.speak(f"No open pull requests on {repo}.")
            return

        count = len(prs)
        summaries = []
        for pr in prs[:5]:
            title = pr.get("title", "untitled")
            num = pr.get("number", "")
            user = pr.get("user", {}).get("login", "someone")
            created = _time_ago(pr.get("created_at", ""))
            summaries.append(f"PR {num} by {user}: {title}, opened {created}")

        summary_text = ". ".join(summaries)
        response = self.capability_worker.text_to_text_response(
            f"{repo} has {count} open PR{'s' if count != 1 else ''}. "
            f"Summarize in 2-3 short spoken sentences:\n{summary_text}",
            system_prompt="You are a concise voice assistant for GitHub. Be brief.",
        )
        await self.capability_worker.speak(response)

        self.default_repo = repo
        await self.save_prefs()

    async def handle_repos(self):
        if not await self.ensure_username():
            return
        await self.filler()
        repos = await asyncio.to_thread(fetch_user_repos)
        if repos is None:
            await self.capability_worker.speak("Couldn't fetch your repos right now.")
            return

        if len(repos) == 0:
            await self.capability_worker.speak("You don't have any repos.")
            return

        summaries = []
        for r in repos[:5]:
            name = r.get("full_name", "")
            desc = r.get("description", "no description")
            stars = r.get("stargazers_count", 0)
            pushed = _time_ago(r.get("pushed_at", ""))
            summaries.append(f"{name} with {stars} stars, last active {pushed}")

        summary_text = ". ".join(summaries)
        response = self.capability_worker.text_to_text_response(
            f"Here are your most recently active repos. Summarize in 2-3 spoken sentences:\n{summary_text}",
            system_prompt="You are a concise voice assistant for GitHub. Be brief and conversational.",
        )
        await self.capability_worker.speak(response)

    async def handle_summary(self):
        """Quick overview: notifications + open PRs."""
        if not await self.ensure_username():
            return
        await self.filler()

        notifs = await asyncio.to_thread(fetch_notifications)
        prs = await asyncio.to_thread(fetch_user_prs, self.username)

        notif_count = len(notifs) if notifs else 0
        pr_count = len(prs) if prs else 0

        response = self.capability_worker.text_to_text_response(
            f"Give a quick GitHub status update in 2 sentences. "
            f"The user has {notif_count} unread notifications and {pr_count} open pull requests.",
            system_prompt="You are a concise voice assistant. Be conversational and brief.",
        )
        await self.capability_worker.speak(response)

    async def handle_help(self):
        await self.capability_worker.speak(
            "I can check your GitHub notifications, list your open pull requests, "
            "show issues or PRs on a repo, list your recent repos, give you a quick summary, "
            "star or unstar a repo, or create an issue by voice. "
            "What would you like?"
        )

    # -------------------------------------------------------------------------
    # STAR / UNSTAR
    # -------------------------------------------------------------------------

    async def handle_star(self, repo: str = ""):
        if not repo:
            repo = self.default_repo
        if not repo:
            answer = await self.capability_worker.run_io_loop(
                "Which repo do you want to star? Give me the owner slash repo name."
            )
            if answer:
                extracted = self.capability_worker.text_to_text_response(
                    f"Extract the GitHub repository name in owner/repo format from this voice input. "
                    f"Return ONLY the owner/repo string, nothing else:\n{answer}"
                )
                repo = extracted.strip()

        if not repo or "/" not in repo:
            await self.capability_worker.speak("I didn't catch a valid repo name.")
            return

        # Check if already starred
        await self.filler()
        is_starred = await asyncio.to_thread(check_star, repo)

        if is_starred is True:
            await self.capability_worker.speak(f"You've already starred {repo}.")
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Star {repo}?"
        )
        if not confirmed:
            await self.capability_worker.speak("Okay, skipped.")
            return

        success = await asyncio.to_thread(star_repo, repo)
        if success:
            await self.capability_worker.speak(f"Done! {repo} is now starred.")
        else:
            await self.capability_worker.speak(f"Couldn't star {repo}. Check the repo name.")

    async def handle_unstar(self, repo: str = ""):
        if not repo:
            repo = self.default_repo
        if not repo:
            answer = await self.capability_worker.run_io_loop(
                "Which repo do you want to unstar?"
            )
            if answer:
                extracted = self.capability_worker.text_to_text_response(
                    f"Extract the GitHub repository name in owner/repo format from this voice input. "
                    f"Return ONLY the owner/repo string, nothing else:\n{answer}"
                )
                repo = extracted.strip()

        if not repo or "/" not in repo:
            await self.capability_worker.speak("I didn't catch a valid repo name.")
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Unstar {repo}?"
        )
        if not confirmed:
            await self.capability_worker.speak("Okay, keeping it starred.")
            return

        await self.filler()
        success = await asyncio.to_thread(unstar_repo, repo)
        if success:
            await self.capability_worker.speak(f"Done. {repo} is unstarred.")
        else:
            await self.capability_worker.speak(f"Couldn't unstar {repo}.")

    # -------------------------------------------------------------------------
    # CREATE ISSUE
    # -------------------------------------------------------------------------

    async def handle_create_issue(self, repo: str = "", title: str = "", body: str = ""):
        # Step 1: Get repo
        if not repo:
            repo = self.default_repo
        if not repo:
            answer = await self.capability_worker.run_io_loop(
                "Which repo should I create the issue on?"
            )
            if answer:
                extracted = self.capability_worker.text_to_text_response(
                    f"Extract the GitHub repository name in owner/repo format from this voice input. "
                    f"Return ONLY the owner/repo string, nothing else:\n{answer}"
                )
                repo = extracted.strip()

        if not repo or "/" not in repo:
            await self.capability_worker.speak("I didn't catch a valid repo name.")
            return

        # Step 2: Get title
        if not title:
            title_input = await self.capability_worker.run_io_loop(
                "What should the issue title be?"
            )
            if not title_input or title_input.strip() == "":
                await self.capability_worker.speak("No title given. Cancelling.")
                return
            # Clean up voice transcription into a proper title
            title = self.capability_worker.text_to_text_response(
                f"Clean up this voice transcription into a concise GitHub issue title. "
                f"Return ONLY the cleaned title, nothing else:\n{title_input}"
            ).strip()

        # Step 3: Ask for optional description
        if not body:
            wants_body = await self.capability_worker.run_confirmation_loop(
                "Want to add a description?"
            )
            if wants_body:
                body_input = await self.capability_worker.run_io_loop(
                    "Go ahead, describe the issue."
                )
                if body_input and body_input.strip():
                    body = self.capability_worker.text_to_text_response(
                        f"Clean up this voice transcription into a clear GitHub issue description. "
                        f"Return ONLY the cleaned description, nothing else:\n{body_input}"
                    ).strip()

        # Step 4: Confirm before creating
        confirm_msg = f"Create issue on {repo} titled '{title}'?"
        if body:
            confirm_msg += " With a description included?"
        confirmed = await self.capability_worker.run_confirmation_loop(confirm_msg)

        if not confirmed:
            await self.capability_worker.speak("Okay, cancelled.")
            return

        # Step 5: Create it
        await self.capability_worker.speak("Creating the issue now.")
        result = await asyncio.to_thread(create_issue, repo, title, body)

        if result:
            number = result.get("number", "")
            await self.capability_worker.speak(
                f"Done! Issue {number} created on {repo}: {title}."
            )
            self.default_repo = repo
            await self.save_prefs()
        else:
            await self.capability_worker.speak(
                f"Couldn't create the issue on {repo}. Check the repo name and permissions."
            )

    # -------------------------------------------------------------------------
    # MAIN RUN LOOP
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            # Load saved preferences
            await self.load_prefs()

            # Read trigger context to determine quick vs full mode
            trigger_context = self.get_trigger_context()
            intent = self.classify_intent(trigger_context) if trigger_context else {"intent": "unknown"}

            self.log(f"Trigger intent: {json.dumps(intent)}")

            # Quick mode — handle the trigger intent directly
            if intent.get("intent") not in ("unknown", "help"):
                await self._route_intent(intent)
                await self.capability_worker.speak("Anything else on GitHub?")
            else:
                # Full mode — greet and enter loop
                if self.username:
                    await self.capability_worker.speak(
                        f"Hey {self.username}. What do you need from GitHub?"
                    )
                else:
                    await self.capability_worker.speak(
                        "GitHub Voice Manager here. What do you need?"
                    )

            # Conversation loop
            idle_count = 0
            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or user_input.strip() == "":
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak("I'll sign off. Talk to you later.")
                        break
                    await self.capability_worker.speak("Still here if you need anything.")
                    continue

                idle_count = 0
                lower = user_input.lower().strip()

                # Check for exit
                if any(word in lower for word in EXIT_WORDS):
                    await self.capability_worker.speak("Got it. Talk later.")
                    break

                # Classify and route
                intent = self.classify_intent(user_input)
                self.log(f"Loop intent: {json.dumps(intent)}")
                await self._route_intent(intent)

                await self.capability_worker.speak("What else?")

        except Exception as e:
            self.log_err(f"Unexpected error: {e}")
            await self.capability_worker.speak(
                "Something went wrong on my end. Let's try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    async def _route_intent(self, intent: dict):
        action = intent.get("intent", "unknown")
        repo = intent.get("repo", "")

        if action == "notifications":
            await self.handle_notifications()
        elif action == "my_prs":
            await self.handle_my_prs()
        elif action == "repo_issues":
            await self.handle_repo_issues(repo)
        elif action == "repo_prs":
            await self.handle_repo_prs(repo)
        elif action == "repos":
            await self.handle_repos()
        elif action == "mark_read":
            await self.handle_notifications()
        elif action == "summary":
            await self.handle_summary()
        elif action == "star":
            await self.handle_star(repo)
        elif action == "unstar":
            await self.handle_unstar(repo)
        elif action == "create_issue":
            await self.handle_create_issue(
                repo=repo,
                title=intent.get("title", ""),
                body=intent.get("body", ""),
            )
        elif action == "help":
            await self.handle_help()
        else:
            # Fallback — let LLM handle conversationally
            response = self.capability_worker.text_to_text_response(
                f"The user said: '{intent.get('details', '')}'. "
                f"This doesn't match a GitHub action. Politely say you can help with "
                f"notifications, pull requests, issues, or repos, and ask what they'd like.",
                system_prompt="You are a concise GitHub voice assistant. One sentence max.",
            )
            await self.capability_worker.speak(response)