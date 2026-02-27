import json
import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# =============================================================================
# Constants (Customize Per Ability)
# =============================================================================

ABILITY_NAMESPACE = "ring"

EXIT_WORDS = {
    "stop", "exit", "quit", "cancel", "bye",
    "never mind", "no thanks", "i'm done", "im done",
}

OAUTH_URL = "https://oauth.ring.com/oauth/token"
API_BASE = "https://api.ring.com/clients_api"
CLIENT_ID = "ring_official_android"
USER_AGENT = "OpenHome-Ring/1.0"
TOKENS_FILE = "ring_tokens.json"

# =============================================================================
# Generic OpenHome Ability Template
# =============================================================================

class RingSecurityAbility(MatchingCapability):
    """
    Ring Security OpenHome Ability (V1).
    Supports authentication, device listing, device health,
    recent activity summaries, and last ring queries.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # =========================================================================
    # Registration
    # =========================================================================

    # {{register capability}}

    # =========================================================================
    # Entry Point
    # =========================================================================

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        """
        Main ability lifecycle entry point.

        High-level flow:
        1. Load stored tokens.
        2. Authenticate or refresh.
        3. Cache Ring devices for this session.
        4. Process initial trigger command (if present).
        5. Enter conversation loop.
        6. Exit cleanly with resume_normal_flow().
        """

        try:
            self._log("Starting Ring ability session.")

            # ---------------------------------------------------------------------
            # Initialize Session State
            # ---------------------------------------------------------------------
            self.devices = {}
            self.name_map = {}
            self.doorbells = []
            self.cameras = []
            self.pending_action = None
            self.refresh_token = None
            self.access_token = None

            # ---------------------------------------------------------------------
            # 1️⃣ Load Tokens
            # ---------------------------------------------------------------------
            self._log("Loading stored tokens.")
            await self._load_tokens()

            # ---------------------------------------------------------------------
            # 2️⃣ Authenticate (Eager)
            # ---------------------------------------------------------------------
            self._log("Authenticating or refreshing token.")
            auth_success = await self._authenticate_or_refresh()

            if not auth_success:
                await self.capability_worker.speak(
                    "Authentication failed. Please try again later."
                )
                self._log_err("Authentication failed during session startup.")
                self.capability_worker.resume_normal_flow()
                return

            # ---------------------------------------------------------------------
            # 3️⃣ Cache Devices
            # ---------------------------------------------------------------------
            self._log("Caching Ring devices for session.")
            cache_success = await self._cache_devices()

            if not cache_success:
                await self.capability_worker.speak(
                    "Ring's servers aren't responding right now. Please try again later."
                )
                self._log_err("Device cache failed. Exiting session.")
                self.capability_worker.resume_normal_flow()
                return

            # ---------------------------------------------------------------------
            # 4️⃣ Handle Trigger Context (Initial Command)
            # ---------------------------------------------------------------------
            trigger_context = self._get_trigger_context()

            if trigger_context:
                stripped = self._strip_activation_phrase(trigger_context)

                if self._is_exit(stripped):
                    self._log("Exit detected in trigger context.")
                    self.capability_worker.resume_normal_flow()
                    return

                classification = self._classify(stripped)
                await self._dispatch(classification)

            # ---------------------------------------------------------------------
            # 5️⃣ Enter Conversation Loop
            # ---------------------------------------------------------------------
            await self._conversation_loop(
                skip_greeting=bool(trigger_context)
            )

            # ---------------------------------------------------------------------
            # 6️⃣ Clean Exit
            # ---------------------------------------------------------------------
            self._log("Session completed normally.")
            self.capability_worker.resume_normal_flow()
            return

        except Exception as e:
            self._log_err(f"Unhandled run() exception: {e}")

            try:
                await self.capability_worker.speak(
                    "Something went wrong. Handing you back."
                )
            except Exception:
                pass

            self.capability_worker.resume_normal_flow()

    # =========================================================================
    # Unified Conversation Loop
    # =========================================================================

    async def _conversation_loop(self, skip_greeting: bool = False):
        """
        Unified multi-turn conversation loop.

        Responsibilities:
        - Handle pending multi-turn state (2FA, clarification, etc.)
        - Collect user input via user_response()
        - Detect deterministic exit words
        - Classify and dispatch intents
        - Enforce idle timeout and max turns
        """

        max_turns = 20
        turn_count = 0
        idle_count = 0

        # ---------------------------------------------------------------------
        # Optional Initial Prompt
        # ---------------------------------------------------------------------
        if not skip_greeting:
            await self.capability_worker.speak(
                "How can I help with your Ring devices?"
            )

        # ---------------------------------------------------------------------
        # Main Loop
        # ---------------------------------------------------------------------
        while turn_count < max_turns:

            # -------------------------------------------------------------
            # 1️⃣ Pending State Check
            # -------------------------------------------------------------
            if self.pending_action:
                user_input = await self.capability_worker.user_response()

                if user_input and self._is_exit(user_input):
                    await self.capability_worker.speak(
                        "Okay, cancelling that request."
                    )
                    self.pending_action = None
                    continue

                await self._handle_pending(user_input)
                turn_count += 1
                continue

            # -------------------------------------------------------------
            # 2️⃣ Collect User Input
            # -------------------------------------------------------------
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                idle_count += 1
                if idle_count >= 2:
                    break
                continue

            idle_count = 0

            # -------------------------------------------------------------
            # 3️⃣ Deterministic Exit
            # -------------------------------------------------------------
            if self._is_exit(user_input):
                break

            # -------------------------------------------------------------
            # 4️⃣ Strip Activation Phrase
            # -------------------------------------------------------------
            cleaned = self._strip_activation_phrase(user_input)

            # -------------------------------------------------------------
            # 5️⃣ Classify Intent
            # -------------------------------------------------------------
            classification = self._classify(cleaned)

            # -------------------------------------------------------------
            # 6️⃣ Dispatch
            # -------------------------------------------------------------
            await self._dispatch(classification)

            turn_count += 1

        # ---------------------------------------------------------------------
        # Exit Prompt (if normal loop end)
        # ---------------------------------------------------------------------
        await self.capability_worker.speak(
            "Let me know if you need anything else."
        )

    # =========================================================================
    # Central Dispatcher
    # =========================================================================

    async def _dispatch(self, classification: dict):
        """
        Route classified intent to appropriate handler.

        Responsibilities:
        - Validate intent
        - Resolve device when required
        - Handle ambiguity
        - Route to correct handler
        """

        intent = classification.get("intent")
        device_hint = classification.get("device_hint")

        # -----------------------------------------------------------------
        # Intent: List Devices
        # -----------------------------------------------------------------
        if intent == "list_devices":
            await self._handle_list_devices()
            return

        # -----------------------------------------------------------------
        # Intent: Help
        # -----------------------------------------------------------------
        if intent == "help":
            await self._handle_help()
            return

        # -----------------------------------------------------------------
        # Intents Requiring Device
        # -----------------------------------------------------------------
        if intent in {"device_status", "check_activity", "last_ring"}:

            device_id = await self._resolve_device(device_hint, intent)

            if device_id is None:
                # Resolution function already spoke clarification or error
                return

            if intent == "device_status":
                await self._handle_device_status(device_id)
                return

            if intent == "check_activity":
                await self._handle_check_activity(device_id)
                return

            if intent == "last_ring":
                await self._handle_last_ring(device_id)
                return

        # -----------------------------------------------------------------
        # Unknown / Fallback
        # -----------------------------------------------------------------
        await self.capability_worker.speak(
            "I can list your Ring devices, check battery and WiFi health, "
            "tell you about recent activity, or find when your doorbell last rang."
        )

    async def _cache_devices(self) -> bool:
        """
        Fetch devices and build lookup maps.
        """
        data = await self._ring_request_with_retry("ring_devices")

        if not data or not isinstance(data, dict):
            self._log_err("Failed to fetch devices.")
            return False

        try:
            devices = []

            for key in ("doorbots", "authorized_doorbots", "stickup_cams"):
                devices.extend(data.get(key, []))

            self.devices = {}
            self.name_map = {}
            self.doorbells = []
            self.cameras = []

            for device in devices:
                device_id = str(device.get("id"))
                name = device.get("description", "Unknown device")
                lower = name.lower()

                self.devices[device_id] = device
                self.name_map[lower] = device_id

                if device.get("kind") == "doorbot":
                    self.doorbells.append(device_id)
                else:
                    self.cameras.append(device_id)

            self._log(f"Cached {len(self.devices)} devices.")
            return True

        except Exception as e:
            self._log_err(f"Device cache error: {e}")
            return False

    async def _handle_help(self):
        await self.capability_worker.speak(
            "I can list your Ring devices, check battery and WiFi health, "
            "summarize recent activity, or tell you when your doorbell last rang. "
            "What would you like?"
        )

    # =========================================================================
    # LLM Intent Classifier
    # =========================================================================

    def _classify(self, text: str) -> dict[str, Any]:
        """
        Central intent classifier using synchronous LLM call.
        MUST strip markdown fences before parsing JSON.
        """

        system_prompt = (
            "You classify commands for a Ring security assistant.\n"
            "Return ONLY valid JSON. No markdown.\n\n"
            "Schema:\n"
            "{\n"
            '  "intent": "list_devices | device_status | check_activity | last_ring | help | unknown",\n'
            '  "device_hint": string or null\n'
            "}\n\n"
            "Rules:\n"
            "- device_status: battery or WiFi health\n"
            "- check_activity: motion or activity summary\n"
            "- last_ring: last doorbell ring\n"
            "- list_devices: list all devices\n"
            "- help: ask what assistant can do\n"
            "- If unsure, return unknown.\n"
        )

        try:
            raw = self.capability_worker.text_to_text_response(
                text,
                system_prompt=system_prompt,
            )

            cleaned = raw.replace("```json", "").replace("```", "").strip()

            parsed = json.loads(cleaned)

            if not isinstance(parsed, dict):
                raise ValueError("Invalid classifier output")

            return parsed

        except Exception as e:
            self._log_err(f"Classification failed: {e}")
            return {"intent": "unknown", "device_hint": None}

    # =========================================================================
    # Utilities
    # =========================================================================

    def _get_trigger_context(self) -> str:
        try:
            history = self.worker.agent_memory.full_message_history
            if not history:
                return ""

            # Design decision: use most recent user message only
            # (developers may extend to last 3-5 if desired)
            for msg in reversed(history):
                if msg.get("role") == "user":
                    return msg.get("content", "")
            return ""

        except Exception:
            return ""

    def _is_exit(self, text: str) -> bool:
        if not text:
            return False
        normalized = text.lower().strip()
        normalized = re.sub(r"[^\w\s']", " ", normalized)
        normalized = " ".join(normalized.split())
        return normalized in EXIT_WORDS

    def _strip_activation_phrase(self, text: str) -> str:
        if not text:
            return text
        lowered = text.lower()
        for hotword in getattr(self, "matching_hotwords", []):
            hw = hotword.lower()
            if lowered.startswith(hw):
                return text[len(hotword):].strip(" .,")
        return text

    def _format_relative_time(self, iso_string: str) -> str:
        try:
            if iso_string.endswith("Z"):
                iso_string = iso_string.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_string)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            seconds = int(delta.total_seconds())
            if seconds < 60:
                return "just now"
            minutes = seconds // 60
            if minutes < 60:
                return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
            hours = minutes // 60
            if hours < 24:
                return f"{hours} hour{'s' if hours != 1 else ''} ago"
            days = hours // 24
            if days == 1:
                return "Yesterday"
            if days < 7:
                return f"{days} days ago"
            if days < 30:
                weeks = days // 7
                return f"{weeks} week{'s' if weeks != 1 else ''} ago"
            if days < 365:
                months = days // 30
                return f"{months} month{'s' if months != 1 else ''} ago"
            years = days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"
        except Exception:
            # Absolute date fallback
            try:
                dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
                return dt.strftime("on %B %d, %Y")
            except Exception:
                return iso_string

    def _log(self, msg: str):
        self.worker.editor_logging_handler.info(
            f"[{ABILITY_NAMESPACE}] {msg}"
        )

    def _log_err(self, msg: str):
        self.worker.editor_logging_handler.error(
            f"[{ABILITY_NAMESPACE}] {msg}"
        )

    async def _resolve_device(self, device_hint: str | None, intent: str) -> str | None:
        """
        Resolve a device hint to a device_id.

        Behavior:
        - Exact match → return device_id
        - Partial single match → return device_id
        - Multiple matches → set pending_action and return None
        - No match → speak available devices and return None
        """

        # -----------------------------------------------------------------
        # No Hint Provided
        # -----------------------------------------------------------------
        if not device_hint:
            if len(self.devices) == 1:
                # Only one device — implicit resolution
                return next(iter(self.devices.keys()))

            await self.capability_worker.speak(
                "Which device are you asking about?"
            )

            self.pending_action = {
                "type": "clarify_device",
                "intent": intent,
                "candidates": list(self.devices.keys())
            }

            return None

        normalized = device_hint.lower().strip()

        # -----------------------------------------------------------------
        # Exact Match
        # -----------------------------------------------------------------
        if normalized in self.name_map:
            return self.name_map[normalized]

        # -----------------------------------------------------------------
        # Partial Match
        # -----------------------------------------------------------------
        matches = []

        for name, device_id in self.name_map.items():
            if normalized in name:
                matches.append(device_id)

        if len(matches) == 1:
            return matches[0]

        # -----------------------------------------------------------------
        # Ambiguous Match
        # -----------------------------------------------------------------
        if len(matches) > 1:
            device_names = [
                self.devices[d]["description"]
                for d in matches
            ]

            await self.capability_worker.speak(
                "I found multiple devices: "
                + ", ".join(device_names)
                + ". Which one did you mean?"
            )

            self.pending_action = {
                "type": "clarify_device",
                "intent": intent,
                "candidates": matches
            }

            return None

        # -----------------------------------------------------------------
        # No Match Found
        # -----------------------------------------------------------------
        available_names = [
            d.get("description", "Unknown device")
            for d in self.devices.values()
        ]

        await self.capability_worker.speak(
            "I couldn't find that device. You have: "
            + ", ".join(available_names)
            + "."
        )

        return None

    async def _handle_pending(self, user_input: str | None):
        """
        Handle multi-turn pending state flows.

        Currently supports:
        - Device clarification
        """

        if not self.pending_action:
            return

        pending_type = self.pending_action.get("type")

        # -----------------------------------------------------------------
        # Device Clarification Flow
        # -----------------------------------------------------------------
        if pending_type == "clarify_device":

            candidates = self.pending_action.get("candidates", [])
            intent = self.pending_action.get("intent")

            if not user_input:
                await self.capability_worker.speak(
                    "Please tell me which device you meant."
                )
                return

            normalized = user_input.lower().strip()

            # -------------------------------------------------------------
            # Try Exact Match Among Candidates
            # -------------------------------------------------------------
            for device_id in candidates:
                device_name = (
                    self.devices.get(device_id, {})
                    .get("description", "")
                    .lower()
                )
                if normalized == device_name:
                    self.pending_action = None
                    await self._route_device_intent(intent, device_id)
                    return

            # -------------------------------------------------------------
            # Try Partial Match Among Candidates
            # -------------------------------------------------------------
            matches = []

            for device_id in candidates:
                device_name = (
                    self.devices.get(device_id, {})
                    .get("description", "")
                    .lower()
                )
                if normalized and normalized in device_name:
                    matches.append(device_id)

            if len(matches) == 1:
                self.pending_action = None
                await self._route_device_intent(intent, matches[0])
                return

            # -------------------------------------------------------------
            # Still Ambiguous
            # -------------------------------------------------------------
            if len(matches) > 1:
                device_names = [
                    self.devices[d]["description"]
                    for d in matches
                ]

                await self.capability_worker.speak(
                    "I still found multiple matches: "
                    + ", ".join(device_names)
                    + ". Please be more specific."
                )

                # Narrow candidates
                self.pending_action["candidates"] = matches
                return

            # -------------------------------------------------------------
            # No Match
            # -------------------------------------------------------------
            device_names = [
                self.devices[d]["description"]
                for d in candidates
            ]

            await self.capability_worker.speak(
                "I couldn't match that to a device. You can choose from: "
                + ", ".join(device_names)
                + "."
            )

            return

    async def _route_device_intent(self, intent: str, device_id: str):
        """
        Route a resolved device_id to the correct handler
        based on stored intent.
        """

        if intent == "device_status":
            await self._handle_device_status(device_id)
            return

        if intent == "check_activity":
            await self._handle_check_activity(device_id)
            return

        if intent == "last_ring":
            await self._handle_last_ring(device_id)
            return

        # Fallback safety
        await self.capability_worker.speak(
            "Something went wrong routing your request."
        )

    async def _load_tokens(self):
        """
        Load stored refresh/access tokens from file storage.
        Never raises fatal errors.
        """

        self.refresh_token = None
        self.access_token = None

        try:
            exists = await self.capability_worker.check_if_file_exists(
                TOKENS_FILE, False
            )

            if not exists:
                return

            raw = await self.capability_worker.read_file(
                TOKENS_FILE, False
            )

            if not raw:
                return

            data = json.loads(raw)

            self.refresh_token = data.get("refresh_token")
            self.access_token = data.get("access_token")

            self._log("Tokens loaded from storage.")

        except Exception as e:
            self._log_err(f"Token load failed (non-fatal): {e}")

    async def _save_tokens(self, refresh_token: str, access_token: str):
        """
        Persist refresh token using delete-then-write pattern.
        """

        try:
            exists = await self.capability_worker.check_if_file_exists(
                TOKENS_FILE, False
            )

            if exists:
                await self.capability_worker.delete_file(
                    TOKENS_FILE, False
                )

            payload = {
                "refresh_token": refresh_token,
                "access_token": access_token,
                "last_refresh": datetime.now(timezone.utc).isoformat()
            }

            await self.capability_worker.write_file(
                TOKENS_FILE,
                json.dumps(payload),
                False
            )

            self._log("Tokens persisted successfully.")

        except Exception as e:
            self._log_err(f"Token save failed: {e}")

    async def _authenticate_or_refresh(self) -> bool:
        """
        Ensure a valid access token exists.
        """

        # Try refresh if refresh token exists
        if self.refresh_token:
            self._log("Attempting token refresh.")
            success = await self._refresh_token(self.refresh_token)
            if success:
                return True

            self._log("Refresh failed. Proceeding to full auth.")

        # No token or refresh failed → full auth
        return await self._full_auth_flow()

    async def _refresh_token(self, refresh_token: str) -> bool:
        """
        Attempt OAuth refresh.
        """

        try:
            response = await asyncio.to_thread(
                requests.post,
                OAUTH_URL,
                data={
                    "client_id": CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )

            if response.status_code != 200:
                self._log_err(
                    f"Refresh failed with status {response.status_code}"
                )
                return False

            data = response.json()

            new_refresh = data.get("refresh_token")
            new_access = data.get("access_token")

            if not new_refresh or not new_access:
                self._log_err("Refresh response missing tokens.")
                return False

            self.refresh_token = new_refresh
            self.access_token = new_access

            await self._save_tokens(new_refresh, new_access)

            self._log("Token refresh successful.")
            return True

        except Exception as e:
            self._log_err(f"Refresh exception: {e}")
            return False

    async def _full_auth_flow(self) -> bool:
        """
        Perform full OAuth authentication via typed credentials.
        """

        try:
            await self.capability_worker.speak(
                "To connect your Ring account, please type your Ring email into the chat."
            )

            email = await self.capability_worker.user_response()

            if not email:
                return False

            confirmed = await self.capability_worker.run_confirmation_loop(
                f"I got {email}. Is that correct?"
            )

            if not confirmed:
                return False

            await self.capability_worker.speak(
                "Please type your Ring password into the chat. "
                "Note that your password will be visible in the chat. "
                "It will not be stored or logged by this ability."
            )

            password = await self.capability_worker.user_response()

            if not password:
                return False

            response = await asyncio.to_thread(
                requests.post,
                OAUTH_URL,
                data={
                    "client_id": CLIENT_ID,
                    "grant_type": "password",
                    "username": email,
                    "password": password,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )

            # 2FA required
            if response.status_code == 412:
                await self.capability_worker.speak(
                    "Please type your two-factor authentication code into the chat."
                )

                code = await self.capability_worker.user_response()

                if not code:
                    await self.capability_worker.speak(
                        "No code received. Authentication cancelled."
                    )
                    return False

                response = await asyncio.to_thread(
                    requests.post,
                    OAUTH_URL,
                    data={
                        "client_id": CLIENT_ID,
                        "grant_type": "password",
                        "username": email,
                        "password": password,
                    },
                    headers={
                        "User-Agent": USER_AGENT,
                        "2fa-support": "true",
                        "2fa-code": code,
                    },
                    timeout=10,
                )

                # ---------------------------------------------------------
                # Single Retry for Incorrect 2FA Code
                # ---------------------------------------------------------
                if response.status_code != 200:
                    await self.capability_worker.speak(
                        "That code didn't work. Please type your two-factor authentication code again."
                    )

                    retry_code = await self.capability_worker.user_response()

                    if not retry_code:
                        await self.capability_worker.speak(
                            "No code received. Authentication cancelled."
                        )
                        return False

                    response = await asyncio.to_thread(
                        requests.post,
                        OAUTH_URL,
                        data={
                            "client_id": CLIENT_ID,
                            "grant_type": "password",
                            "username": email,
                            "password": password,
                        },
                        headers={
                            "User-Agent": USER_AGENT,
                            "2fa-support": "true",
                            "2fa-code": retry_code,
                        },
                        timeout=10,
                    )

            if response.status_code != 200:
                self._log_err(
                    f"Full auth failed with status {response.status_code}"
                )
                await self.capability_worker.speak(
                    "Authentication failed. Please check your credentials."
                )
                return False

            data = response.json()

            refresh_token = data.get("refresh_token")
            access_token = data.get("access_token")

            if not refresh_token or not access_token:
                self._log_err("Full auth response missing tokens.")
                return False

            self.refresh_token = refresh_token
            self.access_token = access_token

            await self._save_tokens(refresh_token, access_token)

            await self.capability_worker.speak(
                "Your Ring account is now connected."
            )

            return True

        except Exception as e:
            self._log_err(f"Full auth exception: {e}")
            await self.capability_worker.speak(
                "Authentication failed due to a network error."
            )
            return False

    async def _ring_request_with_retry(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict | None = None,
    ) -> dict | None:
        """
        Make a Ring API request with a single refresh retry on 401.

        Behavior:
        - Perform request
        - If 401 → attempt token refresh
        - Retry once
        - If still failing → speak reconnect message and return None
        - Never triggers full auth
        """

        if not self.access_token:
            self._log_err("No access token available for API request.")
            return None

        url = f"{API_BASE}/{endpoint}"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": USER_AGENT,
        }

        self._log(f"Calling Ring API: {method} {endpoint}")

        async def _perform_request():
            if method.upper() == "GET":
                return await asyncio.to_thread(
                    requests.get,
                    url,
                    headers=headers,
                    timeout=10,
                )
            elif method.upper() == "POST":
                return await asyncio.to_thread(
                    requests.post,
                    url,
                    headers=headers,
                    json=data,
                    timeout=10,
                )
            else:
                raise ValueError("Unsupported HTTP method")

        try:
            response = await _perform_request()

            # ---------------------------------------------------------
            # If Unauthorized → Attempt Refresh
            # ---------------------------------------------------------
            if response.status_code == 401:
                self._log("401 received. Attempting token refresh.")

                refresh_success = await self._refresh_token(
                    self.refresh_token
                )

                if not refresh_success:
                    self._log_err("Token refresh failed after 401.")
                    await self.capability_worker.speak(
                        "I need to reconnect to Ring. Please start a new session."
                    )
                    return None

                # Update header with new token
                headers["Authorization"] = (
                    f"Bearer {self.access_token}"
                )

                # Retry once
                response = await _perform_request()

                if response.status_code == 401:
                    self._log_err("Second 401 after refresh.")
                    await self.capability_worker.speak(
                        "I need to reconnect to Ring. Please start a new session."
                    )
                    return None

            # ---------------------------------------------------------
            # Non-200 Errors
            # ---------------------------------------------------------
            if response.status_code != 200:
                self._log_err(
                    f"API error {response.status_code} on {endpoint}"
                )
                return None

            # ---------------------------------------------------------
            # Parse JSON
            # ---------------------------------------------------------
            try:
                return response.json()
            except Exception as parse_err:
                self._log_err(
                    f"JSON parse error on {endpoint}: {parse_err}"
                )
                return None

        except Exception as e:
            self._log_err(f"API request exception on {endpoint}: {e}")
            await self.capability_worker.speak(
                "Ring's servers aren't responding right now."
            )
            return None

    async def _handle_device_status(self, device_id: str):
        """
        Retrieve and speak battery and WiFi health for a device.
        """

        device = self.devices.get(device_id)

        if not device:
            self._log_err(f"Device {device_id} not found in cache.")
            await self.capability_worker.speak(
                "That device may be offline."
            )
            return

        device_name = device.get("description", "Your device")

        endpoint = f"doorbots/{device_id}/health"

        data = await self._ring_request_with_retry(endpoint)

        if not data:
            # Error already logged or spoken by wrapper
            return

        try:
            # Health fields are nested under device_health
            health = data.get("device_health", {})

            battery = health.get("battery_percentage")
            rssi = health.get("latest_signal_strength")

            # ---------------------------------------------------------
            # Battery Speech
            # ---------------------------------------------------------
            if battery is not None:
                battery_text = (
                    f"{device_name} battery is at {battery} percent."
                )
            else:
                battery_text = (
                    f"I couldn't determine the battery level for {device_name}."
                )

            # ---------------------------------------------------------
            # WiFi Signal Mapping
            # ---------------------------------------------------------
            signal_text = ""

            if isinstance(rssi, (int, float)):
                signal_label = self._rssi_to_label(rssi)
                signal_text = f" WiFi signal is {signal_label.lower()}."
            else:
                signal_text = ""

            await self.capability_worker.speak(
                battery_text + signal_text
            )

        except Exception as e:
            self._log_err(f"Device status parse error: {e}")
            await self.capability_worker.speak(
                "I couldn't retrieve the device status."
            )

    def _rssi_to_label(self, rssi: float) -> str:
        """
        Convert RSSI value to qualitative label.
        """

        if rssi >= -50:
            return "Excellent"
        if rssi >= -60:
            return "Good"
        if rssi >= -70:
            return "Fair"
        if rssi >= -80:
            return "Weak"
        return "Very weak"

    async def _handle_list_devices(self):
        """
        Speak a summary of available Ring devices.
        """

        try:
            if not self.devices:
                self._log("No devices found in cache.")
                await self.capability_worker.speak(
                    "I couldn't find any Ring devices on your account."
                )
                return

            device_names = [
                d.get("description", "Unknown device")
                for d in self.devices.values()
            ]

            count = len(device_names)

            if count == 1:
                await self.capability_worker.speak(
                    f"You have one Ring device: {device_names[0]}."
                )
                return

            # Join naturally: A, B, and C
            if count == 2:
                joined = f"{device_names[0]} and {device_names[1]}"
            else:
                joined = ", ".join(device_names[:-1]) + f", and {device_names[-1]}"

            await self.capability_worker.speak(
                f"You have {count} Ring devices: {joined}."
            )

        except Exception as e:
            self._log_err(f"List devices error: {e}")
            await self.capability_worker.speak(
                "I couldn't retrieve your device list."
            )

    async def _handle_check_activity(self, device_id: str):
        """
        Summarize recent activity for a device.
        Includes motion events and doorbell rings.
        """

        device = self.devices.get(device_id)

        if not device:
            self._log_err(f"Device {device_id} not found in cache.")
            await self.capability_worker.speak(
                "That device may be offline."
            )
            return

        device_name = device.get("description", "That device")

        endpoint = f"doorbots/{device_id}/history?limit=10"

        data = await self._ring_request_with_retry(endpoint)

        if not data:
            return  # wrapper already logged/spoke error

        try:
            # Ring history returns a list
            if not isinstance(data, list):
                self._log_err("Unexpected history response format.")
                await self.capability_worker.speak(
                    "I couldn't retrieve recent activity."
                )
                return

            if not data:
                await self.capability_worker.speak(
                    f"No recent activity at {device_name}."
                )
                return

            motion_count = 0
            ring_count = 0
            most_recent_time = None

            for event in data:
                kind = event.get("kind")
                created_at = event.get("created_at")

                if kind == "motion":
                    motion_count += 1
                elif kind == "ding":
                    ring_count += 1

                # Track most recent timestamp explicitly
                if created_at:
                    if not most_recent_time or created_at > most_recent_time:
                        most_recent_time = created_at

            if motion_count == 0 and ring_count == 0:
                await self.capability_worker.speak(
                    f"No recent activity at {device_name}."
                )
                return

            # Build summary sentence
            parts = []

            if motion_count:
                parts.append(
                    f"{motion_count} motion event"
                    + ("s" if motion_count != 1 else "")
                )

            if ring_count:
                parts.append(
                    f"{ring_count} ring"
                    + ("s" if ring_count != 1 else "")
                )

            summary = " and ".join(parts)
            total_events = motion_count + ring_count
            verb = "was" if total_events == 1 else "were"

            if most_recent_time:
                relative = self._format_relative_time(most_recent_time)
                await self.capability_worker.speak(
                    f"There {verb} {summary}. The most recent was {relative}."
                )
            else:
                await self.capability_worker.speak(
                    f"There {verb} {summary}."
                )

        except Exception as e:
            self._log_err(f"Activity parsing error: {e}")
            await self.capability_worker.speak(
                "I couldn't retrieve recent activity."
            )

    async def _handle_last_ring(self, device_id: str):
        """
        Report when the doorbell last rang for a device.
        """

        device = self.devices.get(device_id)

        if not device:
            self._log_err(f"Device {device_id} not found in cache.")
            await self.capability_worker.speak(
                "That device may be offline."
            )
            return

        device_name = device.get("description", "That device")

        endpoint = f"doorbots/{device_id}/history?limit=10"

        data = await self._ring_request_with_retry(endpoint)

        if not data:
            return  # wrapper already handled logging/speaking

        try:
            if not isinstance(data, list):
                self._log_err("Unexpected history response format.")
                await self.capability_worker.speak(
                    "I couldn't retrieve ring history."
                )
                return

            # Filter for doorbell rings
            ring_events = [
                event for event in data
                if event.get("kind") == "ding"
            ]

            if not ring_events:
                await self.capability_worker.speak(
                    f"There haven't been any recent rings at {device_name}."
                )
                return

            # Explicitly sort by created_at (ISO-safe lexicographic sort)
            ring_events.sort(
                key=lambda e: e.get("created_at", ""),
                reverse=True,
            )

            most_recent = ring_events[0]
            created_at = most_recent.get("created_at")

            if not created_at:
                await self.capability_worker.speak(
                    f"There was a recent ring at {device_name}, but I couldn't determine when."
                )
                return

            relative = self._format_relative_time(created_at)

            await self.capability_worker.speak(
                f"The last ring at {device_name} was {relative}."
            )

        except Exception as e:
            self._log_err(f"Last ring parsing error: {e}")
            await self.capability_worker.speak(
                "I couldn't retrieve the last ring information."
            )
