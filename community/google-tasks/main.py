import json
import re
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# GOOGLE TASKS
# Voice-powered Google Tasks management using Google Tasks API v1.
# Add tasks, check what's due, mark things done, get daily summaries,
# and switch lists — all by voice. Uses OAuth 2.0 for authentication.
#
# Modes:
#   - add_task       — "Add a task: call the dentist by Friday"
#   - list_tasks     — "What's due today?" / "What's on my list?"
#   - complete_task  — "Mark call the dentist done" / "Complete task 2"
#   - daily_summary  — "Task summary" / "How's my day?"
#   - switch_list    — "Switch to Work list" / "What lists do I have?"
#
# APIs used:
#   - Google Tasks API v1 (https://tasks.googleapis.com)
#   - Google OAuth 2.0 (https://oauth2.googleapis.com)
#   - ip-api.com (timezone auto-detection)
# =============================================================================

PREFS_FILE = "google_tasks_prefs.json"

# -- Google OAuth credentials (replace with your real keys) -------------------
# Get these from: Google Cloud Console → APIs & Services → Credentials
# If left empty, the voice setup will ask for them during first use.
# If pre-filled, the voice setup skips credential collection.
#
# RECOMMENDED: Use the Google OAuth 2.0 Playground to get a refresh token:
#   1. Go to https://developers.google.com/oauthplayground/
#   2. Click the gear icon → check "Use your own OAuth credentials"
#   3. Enter your Client ID and Client Secret
#   4. In Step 1, add scope: https://www.googleapis.com/auth/tasks
#   5. Click "Authorize APIs" → sign in → Allow
#   6. Click "Exchange authorization code for tokens"
#   7. Copy the refresh_token and paste it below
#
# If all three are pre-filled, the ability skips OAuth entirely.
GOOGLE_CLIENT_ID = "YOUR_GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET = "YOUR_GOOGLE_CLIENT_SECRET"
GOOGLE_REFRESH_TOKEN = "YOUR_GOOGLE_REFRESH_TOKEN"

TASKS_BASE_URL = "https://tasks.googleapis.com"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
OAUTH_SCOPE = "https://www.googleapis.com/auth/tasks"
IP_GEO_URL = "http://ip-api.com/json/"

MAX_SPOKEN_TASKS = 5
MAX_SUMMARY_PER_CATEGORY = 3
CACHE_TTL_SECONDS = 300  # 5 minutes

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye",
    "leave", "nothing else", "all good", "nope", "no thanks",
    "i'm good", "that's it", "that's all",
}

TRIGGER_PHRASES = {
    "task", "tasks", "to do", "todo", "add a task", "new task",
    "remind me", "my tasks", "what's due", "task list", "mark done",
    "complete task", "check off", "task summary", "daily tasks",
    "overdue", "switch list", "google tasks",
    "what do i need to do", "finish task",
}

# -- LLM Prompts --------------------------------------------------------------

CLASSIFY_PROMPT = (
    "Classify this voice command for a Google Tasks assistant. "
    "Return ONLY valid JSON. No markdown fences.\n"
    '{{\n'
    '  "mode": "add_task|list_tasks|complete_task|daily_summary|switch_list|noise",\n'
    '  "title": "<task title if adding or completing, else empty string>",\n'
    '  "due_text": "<date reference if mentioned, else empty string>",\n'
    '  "time_range": "<today|this_week|all|overdue if listing, else empty string>",\n'
    '  "task_index": null,\n'
    '  "list_name": "<list name if switching, else empty string>",\n'
    '  "notes": "<any notes mentioned, else empty string>"\n'
    '}}\n\n'
    "Rules:\n"
    '- "add a task call the dentist by Friday" -> add_task, title="call the dentist", due_text="Friday"\n'
    '- "remind me to buy groceries tomorrow" -> add_task, title="buy groceries", due_text="tomorrow"\n'
    '- "new task submit report, note include Q1 numbers" -> add_task, title="submit report", notes="include Q1 numbers"\n'
    '- "what\'s due today" -> list_tasks, time_range="today"\n'
    '- "what\'s on my list" -> list_tasks, time_range="all"\n'
    '- "what\'s due this week" -> list_tasks, time_range="this_week"\n'
    '- "any overdue tasks" -> list_tasks, time_range="overdue"\n'
    '- "mark call the dentist done" -> complete_task, title="call the dentist"\n'
    '- "complete task 2" / "mark the second one done" -> complete_task, task_index=2\n'
    '- "mark the first one done" -> complete_task, task_index=1\n'
    '- "mark the last one done" -> complete_task, task_index=-1\n'
    '- "task summary" / "how\'s my day" -> daily_summary\n'
    '- "switch to work list" -> switch_list, list_name="work"\n'
    '- "what lists do I have" -> switch_list, list_name=""\n'
    "- Strip trigger words from title: remove 'add a task', 'remind me to', 'new task', etc.\n"
    "- If user references a position like 'first', 'second', 'last', set task_index accordingly (1-indexed, -1 for last)\n\n"
    "User's active list: {active_list_name}\n"
    "Recent tasks cached: {has_cache}\n\n"
    "User said: {user_input}"
)

TASK_EXTRACT_PROMPT = (
    "Extract task details from this voice input. "
    "Return ONLY valid JSON. No markdown fences.\n"
    '{{\n'
    '  "title": "<the main task description>",\n'
    '  "due_text": "<date reference or empty string>",\n'
    '  "notes": "<any notes or empty string>",\n'
    '  "priority": "<high|normal or empty string>"\n'
    '}}\n\n'
    "Rules:\n"
    "- Strip trigger words: 'add a task', 'remind me to', 'new task', 'create task', 'I need to'\n"
    "- Extract date references: 'by Friday', 'tomorrow', 'next week', etc.\n"
    "- If user says 'note:' or 'with a note', put remainder in notes\n"
    "- If user says 'high priority' or 'urgent', set priority to 'high'\n\n"
    "User said: {user_input}"
)

DATE_PARSE_PROMPT = (
    "Parse this date reference into RFC 3339 format. "
    "Today is {today} ({day_of_week}). User's timezone: {timezone}.\n\n"
    "Rules:\n"
    '- "today" -> today\'s date\n'
    '- "tomorrow" -> tomorrow\'s date\n'
    '- "Friday" / "by Friday" -> next upcoming Friday (if today IS that day, use NEXT week)\n'
    '- "next week" -> next Monday\n'
    '- "in 3 days" -> today + 3 days\n'
    '- "next month" -> 1st of next month\n'
    '- "end of month" -> last day of current month\n'
    '- "January 15" -> if past, use next year\n\n'
    "Output ONLY the date in format: YYYY-MM-DDT00:00:00.000Z\n"
    "If no date can be parsed, output ONLY: NONE\n\n"
    "Date reference: {date_text}"
)

TASK_RESPONSE_PROMPT = (
    "Generate a natural, concise voice response for this task operation. "
    "Keep it to 1-2 sentences. Be friendly but brief.\n\n"
    "Operation: {operation}\n"
    "Data: {data}\n\n"
    "Generate a spoken response:"
)

SUMMARY_RESPONSE_PROMPT = (
    "Generate a natural voice response for a daily task summary. "
    "Keep it conversational and concise. Skip empty categories.\n\n"
    "Overdue tasks ({overdue_count}): {overdue_titles}\n"
    "Due today ({today_count}): {today_titles}\n"
    "Coming this week ({upcoming_count}): {upcoming_titles}\n"
    "No due date ({undated_count}): {undated_titles}\n\n"
    "Rules:\n"
    "- Max 3 task titles per category\n"
    "- If a category is empty, skip it entirely\n"
    "- If everything is clear, say something like 'You're all caught up!'\n"
    "- Mention overdue tasks first with emphasis\n\n"
    "Generate a spoken response:"
)


# =============================================================================
# CAPABILITY CLASS
# =============================================================================


class GoogleTasksCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    prefs: dict = None
    _recent_results: list = None
    _recent_results_time: float = 0

    # {{register capability}}  # noqa: E265

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.prefs = await self.load_prefs()
            self._recent_results = []
            self._recent_results_time = 0

            # First-run: no refresh_token -> OAuth setup
            if not self.prefs.get("refresh_token"):
                await self.handle_oauth_setup()
                self.prefs = await self.load_prefs()
                if not self.prefs.get("refresh_token"):
                    await self.capability_worker.speak(
                        "Setup wasn't completed. Try again when you're ready."
                    )
                    return

            # Auto-detect timezone if not set
            if self.prefs.get("timezone", "UTC") == "UTC":
                detected_tz = self._detect_timezone()
                if detected_tz and detected_tz != "UTC":
                    self.prefs["timezone"] = detected_tz
                    await self.save_prefs()
                    self._log("info", f"Auto-detected timezone: {detected_tz}")

            # Validate connection by refreshing token
            try:
                await self._ensure_valid_token()
            except Exception:
                await self.capability_worker.speak(
                    "Your Google connection has expired. Let's reconnect."
                )
                await self._handle_reauth()
                if not self.prefs.get("refresh_token"):
                    return

            # Bump usage counter
            self.prefs["times_used"] = self.prefs.get("times_used", 0) + 1
            await self.save_prefs()

            # Get trigger context
            trigger_text = self.get_trigger_context()

            # If trigger text is empty or just trigger phrases, ask user
            if not trigger_text or not trigger_text.strip() or self._is_trigger_leak(trigger_text):
                await self.capability_worker.speak(
                    "What would you like to do with your tasks? "
                    "You can add a task, check what's due, or get a summary."
                )
                trigger_text = await self._get_clean_response()
                if not trigger_text:
                    return

            # Filter STT noise
            if self._is_noise(trigger_text):
                await self.capability_worker.speak(
                    "I didn't catch that. Try saying something like: "
                    "what's due today, or add a task."
                )
                retry = await self._get_clean_response()
                if not retry:
                    return
                trigger_text = retry

            # Classify intent
            raw = self.capability_worker.text_to_text_response(
                CLASSIFY_PROMPT.format(
                    active_list_name=self.prefs.get("active_list_name", "My Tasks"),
                    has_cache="yes" if self._recent_results else "no",
                    user_input=trigger_text,
                )
            )
            parsed = self._parse_json(raw)
            mode = parsed.get("mode", "noise")

            if mode == "noise":
                await self.capability_worker.speak(
                    "I'm not sure what you'd like to do. "
                    "Try: add a task, what's due today, or task summary."
                )
                trigger_text = await self._get_clean_response()
                if not trigger_text:
                    return
                raw = self.capability_worker.text_to_text_response(
                    CLASSIFY_PROMPT.format(
                        active_list_name=self.prefs.get("active_list_name", "My Tasks"),
                        has_cache="yes" if self._recent_results else "no",
                        user_input=trigger_text,
                    )
                )
                parsed = self._parse_json(raw)
                mode = parsed.get("mode", "noise")

            # Route to handler
            await self._dispatch(mode, parsed)

            # Follow-up loop
            while True:
                await self.capability_worker.speak(
                    "Anything else with your tasks? Or say done to exit."
                )
                followup = await self._get_clean_response()
                if not followup or self._is_exit(followup):
                    break
                raw2 = self.capability_worker.text_to_text_response(
                    CLASSIFY_PROMPT.format(
                        active_list_name=self.prefs.get("active_list_name", "My Tasks"),
                        has_cache="yes" if self._recent_results else "no",
                        user_input=followup,
                    )
                )
                parsed2 = self._parse_json(raw2)
                mode2 = parsed2.get("mode", "noise")
                if mode2 == "noise":
                    await self.capability_worker.speak(
                        "I didn't understand that. Try again, or say done to exit."
                    )
                    continue
                await self._dispatch(mode2, parsed2)

        except Exception as e:
            self._log("error", f"Unexpected error: {e}")
            await self.capability_worker.speak(
                "Something went wrong with Google Tasks. Try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    async def _dispatch(self, mode: str, parsed: dict):
        """Route to the appropriate handler."""
        if mode == "add_task":
            await self.handle_add_task(parsed)
        elif mode == "list_tasks":
            await self.handle_list_tasks(parsed)
        elif mode == "complete_task":
            await self.handle_complete_task(parsed)
        elif mode == "daily_summary":
            await self.handle_daily_summary()
        elif mode == "switch_list":
            await self.handle_switch_list(parsed)
        else:
            await self.capability_worker.speak(
                "I'm not sure what to do with that. "
                "Try: add a task, what's due, or task summary."
            )

    # ------------------------------------------------------------------
    # Trigger context
    # ------------------------------------------------------------------

    def get_trigger_context(self) -> str:
        try:
            history = self.worker.agent_memory.full_message_history
            if not history:
                return ""
            user_msgs = []
            for msg in reversed(history):
                try:
                    if isinstance(msg, dict):
                        role = msg.get("role")
                        content = msg.get("content")
                    else:
                        role = msg.role if hasattr(msg, "role") else None
                        content = msg.content if hasattr(msg, "content") else None
                    if role == "user" and content:
                        user_msgs.append(content)
                    if len(user_msgs) >= 5:
                        break
                except Exception:
                    continue
            return "\n".join(reversed(user_msgs))
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # OAuth setup
    # ------------------------------------------------------------------

    async def handle_oauth_setup(self):
        """Guide user through Google Tasks OAuth 2.0 setup."""
        # Use pre-filled constants if available (not placeholders)
        client_id = GOOGLE_CLIENT_ID.strip()
        client_secret = GOOGLE_CLIENT_SECRET.strip()
        has_prefilled = (
            client_id and client_secret
            and not client_id.startswith("YOUR_")
            and not client_secret.startswith("YOUR_")
        )

        if has_prefilled:
            await self.capability_worker.speak(
                "Welcome to Google Tasks! Your credentials are pre-configured. "
                "I just need you to authorize access."
            )
        else:
            await self.capability_worker.speak(
                "Welcome to Google Tasks! Let's get you connected. "
                "You'll need a Google Cloud project with the Tasks API enabled. "
                "Have you already set that up?"
            )
            has_project = await self._ask_yes_no()

            if not has_project:
                await self.capability_worker.speak(
                    "No problem. Here's what to do. "
                    "First, go to console dot cloud dot google dot com "
                    "and create a new project. "
                    "Then go to APIs and Services, Library, and enable the Tasks API. "
                    "Next, set up the OAuth consent screen: "
                    "choose External, add your email as a test user. "
                    "Finally, go to Credentials, create an OAuth client ID, "
                    "choose Desktop app as the application type. "
                    "Copy your Client ID and Client Secret. "
                    "Let me know when you have those ready."
                )
                ready = await self.capability_worker.user_response()
                if not ready or self._is_exit(ready):
                    return

            # Collect Client ID
            await self.capability_worker.speak(
                "What's your Client ID? You can paste it in."
            )
            client_id = await self.capability_worker.user_response()
            if not client_id or self._is_exit(client_id):
                return
            client_id = client_id.strip()

            # Collect Client Secret
            await self.capability_worker.speak(
                "Got it. And the Client Secret?"
            )
            client_secret = await self.capability_worker.user_response()
            if not client_secret or self._is_exit(client_secret):
                return
            client_secret = client_secret.strip()

        self._log("info", f"OAuth setup for client: {client_id[:20]}...")

        # Try device flow first
        device_data = self._request_device_code(client_id)
        if device_data:
            success = await self._complete_device_flow(
                client_id, client_secret, device_data
            )
            if success:
                await self._validate_connection()
                return

        # Device flow failed — fall back to OAuth Playground
        self._log("info", "Device flow unavailable, using OAuth Playground flow")
        await self.capability_worker.speak(
            "I'll walk you through getting a token. "
            "Open your browser and go to "
            "developers dot google dot com slash oauthplayground. "
            "Click the gear icon in the top right and check "
            "Use your own OAuth credentials. "
            "Enter your Client ID and Client Secret. "
            "In Step 1, type this scope: "
            "h t t p s colon slash slash www dot googleapis dot com "
            "slash auth slash tasks. "
            "Click Authorize APIs, sign in, and click Allow. "
            "Then in Step 2, click Exchange authorization code for tokens. "
            "Copy the refresh token and paste it here."
        )

        token_input = await self.capability_worker.user_response()
        if not token_input or self._is_exit(token_input):
            return

        refresh_token = token_input.strip()
        self.prefs["client_id"] = client_id
        self.prefs["client_secret"] = client_secret
        self.prefs["refresh_token"] = refresh_token
        await self.save_prefs()

        # Validate by refreshing
        try:
            await self._ensure_valid_token(force=True)
            self._log("info", "OAuth Playground token exchange successful")
            await self._validate_connection()
        except Exception as e:
            self._log("error", f"Token refresh failed: {e}")
            await self.capability_worker.speak(
                "That token didn't work. Make sure you copied the "
                "refresh token, not the access token. "
                "Double-check and try again later."
            )
            self.prefs["refresh_token"] = ""
            await self.save_prefs()

    async def _complete_device_flow(
        self, client_id: str, client_secret: str, device_data: dict
    ) -> bool:
        """Complete device authorization flow after getting device code."""
        user_code = device_data.get("user_code", "")
        verification_url = device_data.get(
            "verification_url", "https://www.google.com/device"
        )
        device_code = device_data.get("device_code", "")

        spaced_code = " ... ".join(user_code)
        await self.capability_worker.speak(
            f"Open your browser and go to {verification_url}. "
            f"Enter this code: {user_code}. "
            f"That's {spaced_code}. "
            "Sign in with your Google account and click Allow. "
            "Then come back and say done."
        )

        for attempt in range(5):
            resp = await self.capability_worker.user_response()
            if not resp or self._is_exit(resp):
                return False

            token_data = self._exchange_device_code(
                client_id, client_secret, device_code
            )
            if token_data and token_data.get("access_token"):
                self.prefs["client_id"] = client_id
                self.prefs["client_secret"] = client_secret
                self.prefs["access_token"] = token_data.get("access_token", "")
                self.prefs["refresh_token"] = token_data.get("refresh_token", "")
                self.prefs["token_expires_at"] = (
                    time.time() + token_data.get("expires_in", 3600)
                )
                await self.save_prefs()
                self._log("info", "Device flow authorization successful")
                return True
            if attempt < 4:
                await self.capability_worker.speak(
                    "I don't see the approval yet. "
                    "Make sure you've completed all the steps in your browser. "
                    "Say done when ready."
                )
        return False

    async def _validate_connection(self):
        """Validate OAuth by fetching task lists and setting defaults."""
        try:
            lists = await self._fetch_task_lists()
            list_names = [tl.get("title", "Untitled") for tl in lists]
            names_spoken = ", ".join(list_names[:5])

            if lists:
                default_list = lists[0]
                self.prefs["active_list_id"] = default_list.get("id", "@default")
                self.prefs["active_list_name"] = default_list.get("title", "My Tasks")
                self.prefs["cached_lists"] = [
                    {"id": tl.get("id"), "title": tl.get("title")}
                    for tl in lists
                ]
                self.prefs["lists_cached_at"] = time.time()

            await self.save_prefs()

            tasks = await self._fetch_all_tasks(
                self.prefs.get("active_list_id", "@default"),
                {"showCompleted": "false"},
            )
            task_count = len(tasks)

            await self.capability_worker.speak(
                f"You're connected! I can see your lists: {names_spoken}. "
                f"I'll use {self.prefs.get('active_list_name', 'My Tasks')} "
                f"as your active list. "
                f"You have {task_count} incomplete "
                f"{'task' if task_count == 1 else 'tasks'}. "
                "Try saying 'what's due today' or 'add a task'."
            )

        except Exception as e:
            self._log("error", f"Failed to fetch lists after OAuth: {e}")
            await self.capability_worker.speak(
                "Connected, but I had trouble fetching your lists. "
                "Try again in a moment."
            )

    async def _handle_reauth(self):
        """Re-authorize when refresh token has expired."""
        client_id = self.prefs.get("client_id", "")
        client_secret = self.prefs.get("client_secret", "")
        if not client_id or not client_secret:
            await self.capability_worker.speak(
                "I don't have your credentials on file. "
                "Let's set up from scratch."
            )
            await self.handle_oauth_setup()
            return

        # Try device flow first
        device_data = self._request_device_code(client_id)
        if device_data:
            success = await self._complete_device_flow(
                client_id, client_secret, device_data
            )
            if success:
                await self.capability_worker.speak("Reconnected!")
                return

        # Fall back to OAuth Playground
        await self.capability_worker.speak(
            "I need you to get a new refresh token. "
            "Go to developers dot google dot com slash oauthplayground, "
            "use your own credentials in the gear icon, "
            "authorize the Tasks scope, exchange for tokens, "
            "and paste the refresh token here."
        )
        token_input = await self.capability_worker.user_response()
        if not token_input or self._is_exit(token_input):
            return

        self.prefs["refresh_token"] = token_input.strip()
        await self.save_prefs()
        try:
            await self._ensure_valid_token(force=True)
            await self.capability_worker.speak("Reconnected!")
        except Exception:
            await self.capability_worker.speak(
                "That token didn't work. Try again later."
            )
            self.prefs["refresh_token"] = ""
            await self.save_prefs()

    def _request_device_code(self, client_id: str) -> Optional[dict]:
        """Request a device code from Google for the device authorization flow."""
        try:
            resp = requests.post(
                OAUTH_DEVICE_CODE_URL,
                data={
                    "client_id": client_id,
                    "scope": OAUTH_SCOPE,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                self._log(
                    "error",
                    f"Device code request failed: {resp.status_code} "
                    f"{resp.text[:200]}",
                )
                return None
        except Exception as e:
            self._log("error", f"Device code request error: {e}")
            return None

    def _exchange_device_code(
        self, client_id: str, client_secret: str, device_code: str
    ) -> Optional[dict]:
        """Exchange device code for tokens (returns None if still pending)."""
        try:
            resp = requests.post(
                OAUTH_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            data = resp.json()
            error = data.get("error", "")
            if error in ("authorization_pending", "slow_down"):
                return None  # User hasn't approved yet
            self._log("error", f"Device token error: {error}")
            return None
        except Exception as e:
            self._log("error", f"Device token exchange error: {e}")
            return None

    async def _ensure_valid_token(self, force: bool = False):
        """Refresh access token if expired. Call before every API request."""
        expires_at = self.prefs.get("token_expires_at", 0)
        if not force and time.time() < expires_at - 60:
            return  # Still valid

        refresh_token = self.prefs.get("refresh_token")
        if not refresh_token:
            raise Exception("No refresh token available")

        resp = requests.post(
            OAUTH_TOKEN_URL,
            data={
                "client_id": self.prefs.get("client_id", ""),
                "client_secret": self.prefs.get("client_secret", ""),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            self.prefs["access_token"] = data.get("access_token", "")
            self.prefs["token_expires_at"] = time.time() + data.get("expires_in", 3600)
            await self.save_prefs()
        else:
            raise Exception(f"Token refresh failed: {resp.status_code}")

    # ------------------------------------------------------------------
    # Google Tasks API wrapper
    # ------------------------------------------------------------------

    async def _api_request(
        self, method: str, path: str, body: dict = None, params: dict = None
    ) -> Optional[requests.Response]:
        """Make authenticated request to Google Tasks API with 401 retry."""
        await self._ensure_valid_token()
        url = f"{TASKS_BASE_URL}{path}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"
        headers = {
            "Authorization": f"Bearer {self.prefs.get('access_token', '')}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.request(
                method, url, json=body, headers=headers, timeout=10,
            )

            # Auto-retry on 401
            if resp.status_code == 401:
                try:
                    await self._ensure_valid_token(force=True)
                    headers["Authorization"] = f"Bearer {self.prefs.get('access_token', '')}"
                    resp = requests.request(
                        method, url, json=body, headers=headers, timeout=10,
                    )
                except Exception:
                    pass

            return resp
        except requests.exceptions.RequestException as e:
            self._log("error", f"API request failed: {e}")
            return None

    async def _fetch_task_lists(self) -> list:
        """Fetch all task lists."""
        resp = await self._api_request("GET", "/tasks/v1/users/@me/lists")
        if resp and resp.status_code == 200:
            return resp.json().get("items", [])
        return []

    async def _fetch_all_tasks(
        self, list_id: str, params: dict = None
    ) -> list:
        """Fetch all tasks with pagination."""
        all_tasks = []
        page_token = None
        if params is None:
            params = {}
        params["maxResults"] = "100"

        while True:
            req_params = dict(params)
            if page_token:
                req_params["pageToken"] = page_token
            resp = await self._api_request(
                "GET", f"/tasks/v1/lists/{list_id}/tasks", params=req_params,
            )
            if not resp or resp.status_code != 200:
                break
            data = resp.json()
            all_tasks.extend(data.get("items", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return all_tasks

    async def _create_task(
        self, list_id: str, title: str, due: str = None, notes: str = None
    ) -> Optional[dict]:
        """Create a new task."""
        body = {"title": title}
        if due:
            body["due"] = due
        if notes:
            body["notes"] = notes
        resp = await self._api_request(
            "POST", f"/tasks/v1/lists/{list_id}/tasks", body=body,
        )
        if resp and resp.status_code == 200:
            return resp.json()
        return None

    async def _update_task(
        self, list_id: str, task_id: str, body: dict
    ) -> Optional[dict]:
        """Update an existing task (e.g., mark complete)."""
        resp = await self._api_request(
            "PATCH", f"/tasks/v1/lists/{list_id}/tasks/{task_id}", body=body,
        )
        if resp and resp.status_code == 200:
            return resp.json()
        return None

    # ------------------------------------------------------------------
    # Mode handlers
    # ------------------------------------------------------------------

    async def handle_add_task(self, parsed: dict):
        """Add a new task to the active list."""
        title = parsed.get("title", "").strip()
        due_text = parsed.get("due_text", "").strip()
        notes = parsed.get("notes", "").strip()

        # If no title extracted, ask
        if not title:
            await self.capability_worker.speak(
                "What's the task?"
            )
            user_input = await self._get_clean_response()
            if not user_input:
                return
            # Re-extract from full input
            raw = self.capability_worker.text_to_text_response(
                TASK_EXTRACT_PROMPT.format(user_input=user_input)
            )
            extracted = self._parse_json(raw)
            title = extracted.get("title", user_input).strip()
            due_text = extracted.get("due_text", due_text).strip()
            notes = extracted.get("notes", notes).strip()

        # Handle priority in title
        priority = parsed.get("priority", "")
        if not priority:
            raw_p = self.capability_worker.text_to_text_response(
                TASK_EXTRACT_PROMPT.format(user_input=title)
            )
            p_data = self._parse_json(raw_p)
            priority = p_data.get("priority", "")
        if priority and priority.lower() == "high":
            if not title.startswith("!"):
                title = f"! {title}"

        # Parse due date
        due_rfc = None
        if due_text and due_text.lower() != "none":
            due_rfc = self._parse_date(due_text)

        # Create task
        list_id = self.prefs.get("active_list_id", "@default")
        result = await self._create_task(list_id, title, due_rfc, notes or None)

        if result:
            # Invalidate cache
            self._recent_results = []
            # Build response
            due_spoken = ""
            if due_text and due_text.lower() != "none":
                due_spoken = f" due {due_text}"
            response = self.capability_worker.text_to_text_response(
                TASK_RESPONSE_PROMPT.format(
                    operation="task_added",
                    data=f"Added '{title}'{due_spoken} to {self.prefs.get('active_list_name', 'your list')}",
                )
            )
            await self.capability_worker.speak(response)
        else:
            await self.capability_worker.speak(
                "I couldn't add that task. There might be a connection issue."
            )

    async def handle_list_tasks(self, parsed: dict):
        """List tasks from the active list."""
        time_range = parsed.get("time_range", "all").strip().lower()
        list_id = self.prefs.get("active_list_id", "@default")

        # Build date filters
        params = {"showCompleted": "false"}
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        if time_range == "today":
            params["dueMin"] = today_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            params["dueMax"] = today_end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        elif time_range == "this_week":
            days_until_sunday = 6 - today_start.weekday()
            if days_until_sunday <= 0:
                days_until_sunday = 7
            week_end = today_start + timedelta(days=days_until_sunday + 1)
            params["dueMin"] = today_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            params["dueMax"] = week_end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        elif time_range == "overdue":
            params["dueMax"] = today_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # Fetch tasks
        tasks = await self._fetch_all_tasks(list_id, params)

        if not tasks:
            if time_range == "today":
                await self.capability_worker.speak(
                    "You don't have any tasks due today."
                )
            elif time_range == "overdue":
                await self.capability_worker.speak(
                    "No overdue tasks. You're on track!"
                )
            elif time_range == "this_week":
                await self.capability_worker.speak(
                    "Nothing due this week."
                )
            else:
                await self.capability_worker.speak(
                    f"Your {self.prefs.get('active_list_name', '')} list is empty."
                )
            return

        # Cache results for follow-up
        self._recent_results = tasks
        self._recent_results_time = time.time()

        # Build spoken output
        total = len(tasks)
        speak_tasks = tasks[:MAX_SPOKEN_TASKS]

        lines = []
        for i, task in enumerate(speak_tasks, 1):
            title = task.get("title", "Untitled")
            due = task.get("due", "")
            due_str = self._format_due_date(due) if due else ""
            if due_str:
                lines.append(f"{i}. {title}, {due_str}")
            else:
                lines.append(f"{i}. {title}")

        task_list_text = ". ".join(lines)

        if total > MAX_SPOKEN_TASKS:
            prefix = f"You have {total} tasks. Here are the first {MAX_SPOKEN_TASKS}: "
        else:
            prefix = f"You have {total} {'task' if total == 1 else 'tasks'}: "

        await self.capability_worker.speak(prefix + task_list_text)

    async def handle_complete_task(self, parsed: dict):
        """Mark a task as complete."""
        task_index = parsed.get("task_index")
        task_query = parsed.get("title", "").strip()
        list_id = self.prefs.get("active_list_id", "@default")

        target_task = None

        # Try by index from recent cache
        if task_index is not None and self._recent_results:
            try:
                idx = int(task_index)
                if idx == -1:
                    target_task = self._recent_results[-1]
                elif 1 <= idx <= len(self._recent_results):
                    target_task = self._recent_results[idx - 1]
            except (ValueError, IndexError):
                pass

        # Try by name
        if not target_task and task_query:
            # Use cache if fresh
            if self._recent_results and (time.time() - self._recent_results_time < CACHE_TTL_SECONDS):
                tasks = self._recent_results
            else:
                tasks = await self._fetch_all_tasks(list_id, {"showCompleted": "false"})
                self._recent_results = tasks
                self._recent_results_time = time.time()

            matches = self._fuzzy_match_task(task_query, tasks)

            if len(matches) == 1:
                target_task = matches[0]
            elif len(matches) > 1:
                # Disambiguate
                options = []
                for i, m in enumerate(matches[:3], 1):
                    t = m.get("title", "Untitled")
                    d = self._format_due_date(m.get("due", ""))
                    options.append(f"{i}. {t}" + (f", {d}" if d else ""))
                options_text = ". ".join(options)
                await self.capability_worker.speak(
                    f"I found {len(matches)} tasks matching that: {options_text}. "
                    "Which one?"
                )
                choice = await self._get_clean_response()
                if choice:
                    # Try to parse choice as index
                    choice_idx = self._parse_choice_index(choice, len(matches))
                    if choice_idx is not None:
                        target_task = matches[choice_idx]
                    else:
                        # Try fuzzy match again on the choices
                        sub_matches = self._fuzzy_match_task(choice, matches)
                        if sub_matches:
                            target_task = sub_matches[0]
            else:
                await self.capability_worker.speak(
                    f"I couldn't find a task matching '{task_query}'. "
                    "Try saying the exact name, or list your tasks first."
                )
                return

        # If still no task and no query, ask
        if not target_task:
            await self.capability_worker.speak(
                "Which task do you want to complete?"
            )
            user_input = await self._get_clean_response()
            if not user_input:
                return
            tasks = await self._fetch_all_tasks(list_id, {"showCompleted": "false"})
            self._recent_results = tasks
            self._recent_results_time = time.time()
            matches = self._fuzzy_match_task(user_input, tasks)
            if matches:
                target_task = matches[0]
            else:
                await self.capability_worker.speak(
                    "I couldn't find that task. Try listing your tasks first."
                )
                return

        # Mark complete
        task_id = target_task.get("id")
        task_title = target_task.get("title", "Untitled")
        result = await self._update_task(
            list_id, task_id, {"status": "completed"}
        )

        if result:
            # Remove from cache
            self._recent_results = [
                t for t in self._recent_results if t.get("id") != task_id
            ]
            await self.capability_worker.speak(
                f"Done! '{task_title}' is marked complete."
            )
        else:
            await self.capability_worker.speak(
                "I couldn't update that task. There might be a connection issue."
            )

    async def handle_daily_summary(self):
        """Provide a summary of overdue, today, upcoming, and undated tasks."""
        list_id = self.prefs.get("active_list_id", "@default")
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        week_end = today_start + timedelta(days=7)

        # Fetch all incomplete tasks at once (more efficient than 4 calls)
        all_tasks = await self._fetch_all_tasks(
            list_id, {"showCompleted": "false"}
        )

        # Categorize
        overdue = []
        today_tasks = []
        upcoming = []
        undated = []

        for task in all_tasks:
            due_str = task.get("due", "")
            if not due_str:
                undated.append(task)
                continue
            try:
                due_date = datetime.strptime(due_str[:10], "%Y-%m-%d")
                if due_date < today_start:
                    overdue.append(task)
                elif due_date < today_end:
                    today_tasks.append(task)
                elif due_date < week_end:
                    upcoming.append(task)
                else:
                    # Beyond this week — still include in undated-like bucket
                    upcoming.append(task)
            except ValueError:
                undated.append(task)

        # Generate spoken summary
        def titles_str(task_list, max_count):
            names = [t.get("title", "Untitled") for t in task_list[:max_count]]
            return ", ".join(names) if names else "none"

        response = self.capability_worker.text_to_text_response(
            SUMMARY_RESPONSE_PROMPT.format(
                overdue_count=len(overdue),
                overdue_titles=titles_str(overdue, MAX_SUMMARY_PER_CATEGORY),
                today_count=len(today_tasks),
                today_titles=titles_str(today_tasks, MAX_SUMMARY_PER_CATEGORY),
                upcoming_count=len(upcoming),
                upcoming_titles=titles_str(upcoming, MAX_SUMMARY_PER_CATEGORY),
                undated_count=len(undated),
                undated_titles=titles_str(undated, MAX_SUMMARY_PER_CATEGORY),
            )
        )
        await self.capability_worker.speak(response)

        # Cache all tasks for follow-up
        self._recent_results = overdue + today_tasks + upcoming + undated
        self._recent_results_time = time.time()

    async def handle_switch_list(self, parsed: dict):
        """Switch active list or show available lists."""
        list_name = parsed.get("list_name", "").strip()

        # Fetch current lists
        lists = await self._fetch_task_lists()
        if not lists:
            await self.capability_worker.speak(
                "I couldn't fetch your lists. Check your connection."
            )
            return

        # Cache lists
        self.prefs["cached_lists"] = [
            {"id": tl.get("id"), "title": tl.get("title")}
            for tl in lists
        ]
        self.prefs["lists_cached_at"] = time.time()
        await self.save_prefs()

        # If no name specified, just show lists
        if not list_name:
            names = [tl.get("title", "Untitled") for tl in lists]
            current = self.prefs.get("active_list_name", "")
            names_spoken = ", ".join(names)
            await self.capability_worker.speak(
                f"You have {len(lists)} "
                f"{'list' if len(lists) == 1 else 'lists'}: {names_spoken}. "
                f"You're currently on {current}."
            )
            # Ask if they want to switch
            await self.capability_worker.speak(
                "Want to switch to a different list?"
            )
            switch_resp = await self._get_clean_response()
            if not switch_resp or self._is_exit(switch_resp):
                return
            # Check if they said yes vs a list name
            lower = switch_resp.lower().strip()
            if lower in {"yes", "yeah", "yep", "sure", "ok"}:
                await self.capability_worker.speak("Which list?")
                switch_resp = await self._get_clean_response()
                if not switch_resp:
                    return
            list_name = switch_resp

        # Fuzzy match list name
        best_match = None
        best_score = 0
        for tl in lists:
            tl_title = tl.get("title", "")
            score = SequenceMatcher(
                None, list_name.lower(), tl_title.lower()
            ).ratio()
            # Also check substring
            if list_name.lower() in tl_title.lower() or tl_title.lower() in list_name.lower():
                score = max(score, 0.9)
            if score > best_score:
                best_score = score
                best_match = tl

        if best_match and best_score > 0.4:
            self.prefs["active_list_id"] = best_match.get("id", "@default")
            self.prefs["active_list_name"] = best_match.get("title", "My Tasks")
            await self.save_prefs()

            # Count tasks
            tasks = await self._fetch_all_tasks(
                self.prefs["active_list_id"],
                {"showCompleted": "false"},
            )
            # Clear cache on list switch
            self._recent_results = []

            await self.capability_worker.speak(
                f"Switched to your {self.prefs['active_list_name']} list. "
                f"You have {len(tasks)} incomplete "
                f"{'task' if len(tasks) == 1 else 'tasks'}."
            )
        else:
            names = [tl.get("title", "") for tl in lists]
            await self.capability_worker.speak(
                f"I couldn't find a list called '{list_name}'. "
                f"Your lists are: {', '.join(names)}."
            )

    # ------------------------------------------------------------------
    # Fuzzy matching
    # ------------------------------------------------------------------

    def _fuzzy_match_task(self, query: str, tasks: list) -> list:
        """Match spoken query to task titles using substring + difflib + LLM."""
        if not query or not tasks:
            return []

        query_lower = query.lower().strip()
        scored = []

        for task in tasks:
            title = task.get("title", "").lower()
            if not title:
                continue

            # Exact substring match
            if query_lower in title or title in query_lower:
                scored.append((1.0, task))
                continue

            # Fuzzy ratio
            ratio = SequenceMatcher(None, query_lower, title).ratio()
            if ratio > 0.4:
                scored.append((ratio, task))

        scored.sort(key=lambda x: x[0], reverse=True)

        # If best match > 0.7, return just that one
        if scored and scored[0][0] > 0.7:
            return [scored[0][1]]

        # If decent matches, return top 3 for disambiguation
        decent = [t for score, t in scored if score > 0.4]
        if decent:
            return decent[:3]

        # LLM fallback
        if tasks:
            titles = [t.get("title", "") for t in tasks[:20]]
            llm_result = self.capability_worker.text_to_text_response(
                f"The user said '{query}'. Which of these task titles matches best? "
                f"Options: {titles}. "
                "Reply with ONLY the exact matching title, or NONE if no match."
            )
            llm_clean = llm_result.strip().strip("'\"")
            for task in tasks:
                if task.get("title", "").lower() == llm_clean.lower():
                    return [task]

        return []

    def _parse_choice_index(self, choice: str, max_idx: int) -> Optional[int]:
        """Parse user choice like '1', 'first', 'the second one', etc."""
        if not choice:
            return None
        lower = choice.lower().strip()
        ordinals = {
            "first": 0, "1": 0, "one": 0,
            "second": 1, "2": 1, "two": 1,
            "third": 2, "3": 2, "three": 2,
            "last": max_idx - 1,
        }
        for word, idx in ordinals.items():
            if word in lower and 0 <= idx < max_idx:
                return idx
        # Try numeric extraction
        match = re.search(r'(\d+)', lower)
        if match:
            num = int(match.group(1)) - 1  # 1-indexed to 0-indexed
            if 0 <= num < max_idx:
                return num
        return None

    # ------------------------------------------------------------------
    # Date parsing
    # ------------------------------------------------------------------

    def _parse_date(self, date_text: str) -> Optional[str]:
        """Parse a date reference into RFC 3339 format using LLM."""
        if not date_text or date_text.lower() in ("none", ""):
            return None

        now = datetime.utcnow()
        today_str = now.strftime("%Y-%m-%d")
        day_of_week = now.strftime("%A")
        timezone = self.prefs.get("timezone", "UTC")

        result = self.capability_worker.text_to_text_response(
            DATE_PARSE_PROMPT.format(
                today=today_str,
                day_of_week=day_of_week,
                timezone=timezone,
                date_text=date_text,
            )
        )

        cleaned = result.strip()
        if cleaned.upper() == "NONE":
            return None

        # Validate format
        if re.match(r'\d{4}-\d{2}-\d{2}T', cleaned):
            return cleaned

        # Try to extract a date from the response
        match = re.search(r'(\d{4}-\d{2}-\d{2})', cleaned)
        if match:
            return f"{match.group(1)}T00:00:00.000Z"

        return None

    def _format_due_date(self, due_str: str) -> str:
        """Format an RFC 3339 due date into a spoken string."""
        if not due_str:
            return ""
        try:
            due_date = datetime.strptime(due_str[:10], "%Y-%m-%d")
            now = datetime.utcnow()
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            delta = (due_date - today).days

            if delta == 0:
                return "due today"
            elif delta == 1:
                return "due tomorrow"
            elif delta == -1:
                return "was due yesterday"
            elif delta < -1:
                return f"was due {abs(delta)} days ago"
            elif delta <= 7:
                return f"due {due_date.strftime('%A')}"
            else:
                return f"due {due_date.strftime('%B %d')}"
        except ValueError:
            return ""

    # ------------------------------------------------------------------
    # Timezone detection
    # ------------------------------------------------------------------

    def _detect_timezone(self) -> Optional[str]:
        """Auto-detect timezone from IP geolocation."""
        try:
            resp = requests.get(IP_GEO_URL, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return data.get("timezone", "UTC")
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _parse_json(self, raw: str) -> dict:
        """Parse JSON from LLM response, stripping markdown fences."""
        if not raw:
            return {}
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            # Try to find JSON object in the response
            match = re.search(r'\{[^{}]*\}', clean, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except (json.JSONDecodeError, ValueError):
                    pass
            return {}

    def _is_exit(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower().strip()
        lower = re.sub(r"[^\w\s']", "", lower)
        for word in EXIT_WORDS:
            if word in lower:
                return True
        return False

    def _is_noise(self, text: str) -> bool:
        """Detect STT noise: non-English, gibberish, or very short."""
        if not text or len(text.strip()) < 2:
            return True
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        if len(text) > 3 and ascii_chars / len(text) < 0.5:
            return True
        return False

    def _is_trigger_leak(self, text: str) -> bool:
        """Check if response is just the trigger phrase leaking through."""
        if not text:
            return True
        lower = text.lower().strip().rstrip(".")
        return lower in TRIGGER_PHRASES

    async def _get_clean_response(self) -> Optional[str]:
        """Get user response, filtering out trigger leaks and noise."""
        resp = await self.capability_worker.user_response()
        if not resp:
            return None
        if self._is_exit(resp):
            return None
        if self._is_trigger_leak(resp):
            await self.capability_worker.speak(
                "I heard the trigger phrase, not your answer. Please say it again."
            )
            resp = await self.capability_worker.user_response()
            if not resp or self._is_exit(resp) or self._is_trigger_leak(resp):
                return None
        if self._is_noise(resp):
            await self.capability_worker.speak(
                "I didn't catch that clearly. Try again?"
            )
            resp = await self.capability_worker.user_response()
            if not resp or self._is_exit(resp) or self._is_noise(resp):
                return None
        return resp

    async def _ask_yes_no(self, max_retries: int = 2) -> bool:
        """Custom yes/no prompt that won't loop forever."""
        for attempt in range(max_retries + 1):
            resp = await self.capability_worker.user_response()
            if not resp:
                return False
            lower = resp.lower().strip().rstrip(".")
            if lower in {"yes", "yeah", "yep", "yup", "sure", "ok", "okay",
                         "correct", "right", "affirmative", "si"}:
                return True
            if lower in {"no", "nah", "nope", "not really", "negative", "skip"}:
                return False
            if self._is_exit(resp):
                return False
            if attempt < max_retries:
                await self.capability_worker.speak(
                    "Just say yes or no."
                )
        return False

    def _log(self, level: str, message: str):
        handler = self.worker.editor_logging_handler
        if level == "error":
            handler.error(f"[GoogleTasks] {message}")
        elif level == "warning":
            handler.warning(f"[GoogleTasks] {message}")
        else:
            handler.info(f"[GoogleTasks] {message}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def load_prefs(self) -> dict:
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            try:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                return json.loads(raw)
            except (json.JSONDecodeError, Exception):
                self._log("error", "Corrupt prefs file, using defaults.")
        return {
            "client_id": GOOGLE_CLIENT_ID if not GOOGLE_CLIENT_ID.startswith("YOUR_") else "",
            "client_secret": GOOGLE_CLIENT_SECRET if not GOOGLE_CLIENT_SECRET.startswith("YOUR_") else "",
            "refresh_token": GOOGLE_REFRESH_TOKEN if not GOOGLE_REFRESH_TOKEN.startswith("YOUR_") else "",
            "access_token": "",
            "token_expires_at": 0,
            "active_list_id": "@default",
            "active_list_name": "My Tasks",
            "cached_lists": [],
            "lists_cached_at": 0,
            "timezone": "UTC",
            "times_used": 0,
        }

    async def save_prefs(self):
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            await self.capability_worker.delete_file(PREFS_FILE, False)
        await self.capability_worker.write_file(
            PREFS_FILE, json.dumps(self.prefs), False
        )
