import json
import os
import time
import asyncio
from typing import Any, Dict, List, Optional

import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# =============================================================================
# Constants
# =============================================================================

PREFS_FILE = "gdrive_manager_prefs.json"

DRIVE_BASE_URL = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
REDIRECT_URI = "http://localhost:1"

# Map MIME types to spoken labels
MIME_LABELS = {
    "application/vnd.google-apps.document": "Doc",
    "application/vnd.google-apps.spreadsheet": "Sheet",
    "application/vnd.google-apps.presentation": "Slides",
    "application/vnd.google-apps.folder": "Folder",
    "application/pdf": "PDF",
    "text/plain": "text file",
}

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye",
    "never mind", "no thanks", "i'm good", "nope",
}


class GDriveVoiceManager(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    prefs: Dict[str, Any] = {}

    # =========================================================================
    # Registration
    # =========================================================================

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

    # =========================================================================
    # Entry Point
    # =========================================================================

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.prefs = {}
        self.worker.session_tasks.create(self.run())

    # =========================================================================
    # Main P0 Flow
    # =========================================================================

    async def run(self):
        try:
            self.prefs = await self.load_prefs()

            # -----------------------------------------------------------------
            # OAuth gate — first-run or expired refresh token
            # -----------------------------------------------------------------
            if not self.prefs.get("refresh_token"):
                await self.capability_worker.speak(
                    "I need to connect to your Google Drive first. "
                    "I'll walk you through the setup."
                )
                success = await self.run_oauth_setup_flow()
                if not success:
                    await self.capability_worker.speak(
                        "Setup didn't complete. We can try again next time."
                    )
                    self.capability_worker.resume_normal_flow()
                    return
                # Reload prefs after successful OAuth
                self.prefs = await self.load_prefs()

            # -----------------------------------------------------------------
            # Bump usage counter
            # -----------------------------------------------------------------
            self.prefs["times_used"] = self.prefs.get("times_used", 0) + 1
            await self.save_prefs()

            # -----------------------------------------------------------------
            # Early exit — user said "Drive, never mind" or similar
            # -----------------------------------------------------------------
            trigger_context = self.get_trigger_context()
            if trigger_context and self._is_exit(trigger_context):
                self.capability_worker.resume_normal_flow()
                return

            # -----------------------------------------------------------------
            # Classify trigger context
            # -----------------------------------------------------------------
            classification = self.classify_trigger_context(trigger_context)
            mode = classification.get("mode", "")
            search_query = classification.get("search_query")

            # -----------------------------------------------------------------
            # Route: Find Files (P0 — name search)
            # -----------------------------------------------------------------
            if mode == "find" and search_query:
                await self._run_find(search_query)
                self.capability_worker.resume_normal_flow()
                return

            # -----------------------------------------------------------------
            # Route: Known but unimplemented modes
            # -----------------------------------------------------------------
            if mode in {"whats_new", "read_doc", "quick_save", "folder_browse"}:
                await self.capability_worker.speak(
                    "That feature is coming soon. "
                    "Right now I can search your Drive by file name. "
                    "What should I look for?"
                )
                user_input = await self.capability_worker.user_response()
                if user_input and not self._is_exit(user_input):
                    await self._run_find(user_input)
                self.capability_worker.resume_normal_flow()
                return

            # -----------------------------------------------------------------
            # Route: Find without extracted query
            # -----------------------------------------------------------------
            if mode == "find" and not search_query:
                await self.capability_worker.speak(
                    "What file should I search for?"
                )
                user_input = await self.capability_worker.user_response()
                if user_input and not self._is_exit(user_input):
                    await self._run_find(user_input)
                self.capability_worker.resume_normal_flow()
                return

            # -----------------------------------------------------------------
            # Route: Generic trigger / fallback
            # -----------------------------------------------------------------
            await self.capability_worker.speak(
                "I can search your Google Drive by file name. "
                "What would you like me to find?"
            )
            user_input = await self.capability_worker.user_response()
            if user_input and not self._is_exit(user_input):
                await self._run_find(user_input)
            self.capability_worker.resume_normal_flow()

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[GDrive] Unhandled error in run(): {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Let me hand you back."
            )
            self.capability_worker.resume_normal_flow()

    # =========================================================================
    # Find Files — P0 Core
    # =========================================================================

    async def _run_find(self, query: str):
        """Execute the find-files flow: search, process, speak results."""
        if not query.strip():
            await self.capability_worker.speak(
                "I need a file name to search for."
            )
            return
        await self.capability_worker.speak("Searching your Drive.")

        resp = await self.search_files_by_name(query)

        if resp is None:
            await self.capability_worker.speak(
                "I couldn't reach Google Drive right now."
            )
            return

        if resp.status_code != 200:
            self.worker.editor_logging_handler.error(
                f"[GDrive] Search returned {resp.status_code}: "
                f"{resp.text[:300]}"
            )
            await self.capability_worker.speak(
                "Something went wrong while searching your Drive."
            )
            return

        data = resp.json()
        files = data.get("files", [])

        if not files:
            await self.capability_worker.speak(
                "I didn't find anything matching that in your Drive. "
                "Try different keywords."
            )
            return

        await self.handle_search_results(files, query)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _is_exit(self, text: str) -> bool:
        """Check if user input matches an exit phrase."""
        lower = text.lower().strip()
        return any(word in lower for word in EXIT_WORDS)

    def _mime_label(self, mime_type: str) -> str:
        """Convert a MIME type string to a spoken label."""
        return MIME_LABELS.get(mime_type, "file")

    def _log(self, msg: str):
        """Shortcut for info logging."""
        self.worker.editor_logging_handler.info(f"[GDrive] {msg}")

    def _log_err(self, msg: str):
        """Shortcut for error logging."""
        self.worker.editor_logging_handler.error(f"[GDrive] {msg}")

    # =========================================================================
    # Persistence
    # =========================================================================

    async def load_prefs(self) -> Dict[str, Any]:
        """
        Load persistent preferences from gdrive_manager_prefs.json.

        - check_if_file_exists before reading
        - Parse JSON safely
        - Return {} if file missing or corrupt
        - Log corruption and delete bad file
        """

        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )

            if not exists:
                self._log("Prefs file not found. Using empty prefs.")
                return {}

            raw = await self.capability_worker.read_file(
                PREFS_FILE, False
            )

            if not raw:
                self._log("Prefs file empty. Resetting.")
                await self.capability_worker.delete_file(
                    PREFS_FILE, False
                )
                return {}

            try:
                data = json.loads(raw)

                if not isinstance(data, dict):
                    raise ValueError("Prefs JSON is not an object.")

                return data

            except (json.JSONDecodeError, ValueError) as parse_err:
                self._log_err(
                    f"Prefs file corrupt. Resetting. Error: {parse_err}"
                )
                await self.capability_worker.delete_file(
                    PREFS_FILE, False
                )
                return {}

        except Exception as e:
            self._log_err(f"Failed to load prefs: {e}")
            return {}

    async def save_prefs(self):
        """
        Persist self.prefs using delete-then-write pattern.

        - Delete file if it exists
        - Write json.dumps(self.prefs)
        - temp=False (persistent)
        """

        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )

            if exists:
                await self.capability_worker.delete_file(
                    PREFS_FILE, False
                )

            serialized = json.dumps(self.prefs)

            await self.capability_worker.write_file(
                PREFS_FILE,
                serialized,
                False  # temp=False → persistent
            )

            self._log("Prefs saved successfully.")

        except Exception as e:
            self._log_err(f"Failed to save prefs: {e}")

    # =========================================================================
    # OAuth Setup Flow
    # =========================================================================

    async def run_oauth_setup_flow(self) -> bool:
        """Guide user through Google OAuth setup via voice."""
        try:
            # ---------------------------------------------------------
            # Step 1: Walk through Google Cloud Console setup
            # ---------------------------------------------------------
            await self.capability_worker.speak(
                "To connect Google Drive, you'll need to create "
                "credentials in the Google Cloud Console. "
                "I'll walk you through it."
            )
            await self.capability_worker.speak(
                "Step one. Go to console dot cloud dot google dot com. "
                "Create a new project or pick an existing one."
            )
            await self.capability_worker.speak(
                "Step two. In the navigation menu on your left, go to APIs and Services, "
                "then Library. Search for Google Drive API and enable it."
            )
            await self.capability_worker.speak(
                "Step three. Go to APIs and Services, then Credentials. "
                "Click Create Credentials and choose OAuth client ID."
            )
            await self.capability_worker.speak(
                "If it asks you to configure a consent screen, "
                "choose External, fill in the app name, add your email, "
                "and save."
            )

            await self.capability_worker.speak(
                "Then click on the nagivation menu again, then APIs and Services, "
                "then OAuth Consent Screen. Click Audience, then click Add Users "
                "at the bottom. Then add your email as a test user."
            )

            await self.capability_worker.speak(
                "Step four. Create the OAuth client. Choose Desktop App "
                "as the type. Name it whatever you like. "
                "Then copy the Client ID and Client Secret."
            )

            # ---------------------------------------------------------
            # Step 2: Collect Client ID
            # ---------------------------------------------------------
            await self.capability_worker.speak(
                "When you have your Client ID, paste it here."
            )

            client_id = await self.capability_worker.wait_for_complete_transcription()

            if not client_id or not client_id.strip():
                await self.capability_worker.speak(
                    "I didn't receive a Client ID."
                )
                return False

            client_id = client_id.strip()

            if ".apps.googleusercontent.com" not in client_id:
                await self.capability_worker.speak(
                    "That doesn't look like a valid Client ID. "
                    "It should end with dot apps dot googleusercontent dot com."
                )
                return False

            # ---------------------------------------------------------
            # Step 3: Collect Client Secret
            # ---------------------------------------------------------
            await self.capability_worker.speak(
                "Got it. Now paste your Client Secret."
            )

            client_secret = await self.capability_worker.user_response()

            if not client_secret or not client_secret.strip():
                await self.capability_worker.speak(
                    "I didn't receive a Client Secret."
                )
                return False

            client_secret = client_secret.strip()

            self.prefs["client_id"] = client_id
            self.prefs["client_secret"] = client_secret
            self.prefs["redirect_uri"] = REDIRECT_URI

            # ---------------------------------------------------------
            # Step 4: Build and present consent URL
            # ---------------------------------------------------------
            consent_url = (
                f"{OAUTH_AUTH_URL}"
                f"?client_id={client_id}"
                f"&redirect_uri={REDIRECT_URI}"
                f"&response_type=code"
                f"&scope={DRIVE_SCOPE}"
                f"&access_type=offline"
                f"&prompt=consent"
            )

            # Send URL over websocket so the user can click it
            await self.capability_worker.speak(
                f"Click this link to authorize access: {consent_url}"
            )
            self._log(f"Consent URL: {consent_url}")

            await self.capability_worker.speak(
                "Now I need you to authorize access. "
                "I've sent an authorization link. Open it in your browser "
                "and sign in with your Google account."
            )
            await self.capability_worker.speak(
                "After you approve, the browser will try to redirect "
                "and show an error page. That's expected. "
                "Look at the URL bar. Copy everything after code equals, "
                "up to the ampersand symbol. Then paste that code here."
            )

            # ---------------------------------------------------------
            # Step 5: Collect Authorization Code
            # ---------------------------------------------------------
            auth_code = await self.capability_worker.user_response()

            if not auth_code or not auth_code.strip():
                await self.capability_worker.speak(
                    "I didn't receive an authorization code."
                )
                return False

            auth_code = auth_code.strip()

            # ---------------------------------------------------------
            # Step 6: Exchange code for tokens
            # ---------------------------------------------------------
            await self.capability_worker.speak(
                "Got it. Exchanging that code for access tokens."
            )

            token_data = await self._exchange_code_for_tokens(auth_code)

            if not token_data:
                await self.capability_worker.speak(
                    "The token exchange failed. Double-check your "
                    "Client ID and Secret, and make sure the code "
                    "was copied correctly. We can try again next time."
                )
                return False

            # ---------------------------------------------------------
            # Step 7: Validate tokens
            # ---------------------------------------------------------
            refresh_token = token_data.get("refresh_token")
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in")

            if not refresh_token:
                await self.capability_worker.speak(
                    "Google didn't return a refresh token. "
                    "This usually means you've authorized before. "
                    "Go to your Google account settings, "
                    "revoke access for this app, then try setup again."
                )
                return False

            if not access_token or not expires_in:
                await self.capability_worker.speak(
                    "Got an incomplete response from Google. "
                    "Let's try again next time."
                )
                return False

            self.prefs["refresh_token"] = refresh_token
            self.prefs["access_token"] = access_token


            # Handle refresh token rotation — Google may return a new one
            if "refresh_token" in token_data:
                self.prefs["refresh_token"] = token_data["refresh_token"]

            # ---------------------------------------------------------
            # Step 8: Validate connection
            # ---------------------------------------------------------
            email = await self._validate_connection()

            if not email:
                await self.capability_worker.speak(
                    "I got tokens but couldn't verify the connection. "
                    "Let's try again next time."
                )
                return False

            self.prefs["user_email"] = email
            await self.save_prefs()

            await self.capability_worker.speak(
                f"Connected! I can see your Drive, {email}."
            )
            return True

        except Exception as e:
            self._log_err(f"OAuth setup error: {e}")
            return False

    async def _exchange_code_for_tokens(self, auth_code: str) -> Optional[Dict]:
        try:
            # Sanitize: URL-decode, strip whitespace, remove trailing params

            # Sanitize pasted auth code
            auth_code = auth_code.strip()

            if "code=" in auth_code:
                auth_code = auth_code.split("code=")[-1]

            auth_code = auth_code.split("&")[0].strip()

            payload = {
                "client_id": self.prefs.get("client_id"),
                "client_secret": self.prefs.get("client_secret"),
                "code": auth_code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
            }

            response = await asyncio.to_thread(
                requests.post,
                OAUTH_TOKEN_URL,
                data=payload,
                timeout=10,
            )

            if response.status_code != 200:
                self._log_err(
                    f"OAuth exchange failed: {response.status_code} "
                    f"{response.text[:300]}"
                )
                return None

            return response.json()

        except Exception as e:
            self._log_err(f"_exchange_code_for_tokens error: {e}")
            return None

    async def _validate_connection(self) -> Optional[str]:
        try:
            resp = await self.drive_request(
                "GET",
                "/about",
                params={"fields": "user"},
            )

            if not resp or resp.status_code != 200:
                return None

            data = resp.json()
            user = data.get("user", {})
            return user.get("emailAddress")

        except Exception as e:
            self._log_err(f"_validate_connection error: {e}")
            return None

    # =========================================================================
    # Token Management
    # =========================================================================

    async def refresh_access_token(self) -> bool:
        """
        Refresh the access token using the stored refresh_token.

        - POST to OAUTH_TOKEN_URL with grant_type=refresh_token
        - Update self.prefs['access_token']
        - Update self.prefs['token_expires_at'] = now + expires_in - 60
        - Save prefs
        - Return True on success, False on failure
        - Wrap requests.post in asyncio.to_thread
        - If refresh fails with 'invalid_grant', log and return False
        """

        try:
            refresh_token = self.prefs.get("refresh_token")
            client_id = self.prefs.get("client_id")
            client_secret = self.prefs.get("client_secret")

            if not refresh_token or not client_id or not client_secret:
                self._log_err("Missing credentials required for token refresh.")
                return False

            payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }

            response = await asyncio.to_thread(
                requests.post,
                OAUTH_TOKEN_URL,
                data=payload,
                timeout=10,
            )

            if response.status_code != 200:
                try:
                    error_data = response.json()
                except Exception:
                    error_data = {}

                if error_data.get("error") == "invalid_grant":
                    self._log_err("Refresh token invalid (invalid_grant).")
                else:
                    self._log_err(
                        f"Token refresh failed: {response.status_code} "
                        f"{response.text[:300]}"
                    )
                return False

            token_data = response.json()

            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in")

            if not access_token or not expires_in:
                self._log_err("Malformed token refresh response.")
                return False

            # Update prefs
            self.prefs["access_token"] = access_token
            self.prefs["token_expires_at"] = time.time() + int(expires_in) - 60

            await self.save_prefs()

            self._log("Access token refreshed successfully.")
            return True

        except Exception as e:
            self._log_err(f"refresh_access_token error: {e}")
            return False

    def _token_expired(self) -> bool:
        """Check if access token is expired or within 60s of expiry."""
        return time.time() >= self.prefs.get("token_expires_at", 0)

    # =========================================================================
    # Drive API Wrapper
    # =========================================================================

    async def drive_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers_extra: Optional[Dict[str, str]] = None,
        data: Optional[bytes] = None,
        upload: bool = False,
    ) -> Optional[requests.Response]:
        """
        Central Drive API request wrapper.

        1. Check token expiry → refresh if needed
        2. Build URL:
           - upload=True  → DRIVE_UPLOAD_URL + path
           - upload=False → DRIVE_BASE_URL + path
        3. Set Authorization header from self.prefs['access_token']
        4. Merge any headers_extra
        5. Execute via asyncio.to_thread(requests.request, ...)
        6. If 401 → refresh token once → retry once
        7. Return response object, or None if refresh failed

        - timeout=10 on all requests
        - No speaking inside this method
        - Log errors via _log_err
        """

        try:
            # -------------------------------------------------------------
            # Ensure we have a refresh token
            # -------------------------------------------------------------
            if not self.prefs.get("refresh_token"):
                self._log_err("No refresh_token available.")
                return None

            # -------------------------------------------------------------
            # Refresh if expired
            # -------------------------------------------------------------
            if self._token_expired():
                refreshed = await self.refresh_access_token()
                if not refreshed:
                    self._log_err("Token refresh failed before request.")
                    return None

            access_token = self.prefs.get("access_token")
            if not access_token:
                self._log_err("No access_token present.")
                return None

            # -------------------------------------------------------------
            # Build URL
            # -------------------------------------------------------------
            base = DRIVE_UPLOAD_URL if upload else DRIVE_BASE_URL

            if not path.startswith("/"):
                path = "/" + path

            url = base + path

            # -------------------------------------------------------------
            # Build headers
            # -------------------------------------------------------------
            headers = {
                "Authorization": f"Bearer {access_token}",
            }

            if headers_extra:
                headers.update(headers_extra)

            # -------------------------------------------------------------
            # Execute request (wrapped)
            # -------------------------------------------------------------
            response = await asyncio.to_thread(
                requests.request,
                method,
                url,
                params=params,
                headers=headers,
                data=data,
                timeout=10,
            )

            # -------------------------------------------------------------
            # Retry once on 401
            # -------------------------------------------------------------
            if response.status_code == 401:
                self._log("Received 401. Attempting token refresh.")

                refreshed = await self.refresh_access_token()
                if not refreshed:
                    self._log_err("Token refresh failed after 401.")
                    return None

                access_token = self.prefs.get("access_token")
                headers["Authorization"] = f"Bearer {access_token}"

                response = await asyncio.to_thread(
                    requests.request,
                    method,
                    url,
                    params=params,
                    headers=headers,
                    data=data,
                    timeout=10,
                )

            return response

        except Exception as e:
            self._log_err(f"drive_request error: {e}")
            return None

    # =========================================================================
    # Search (P0 — Name Only)
    # =========================================================================

    async def search_files_by_name(self, query: str) -> Optional[requests.Response]:
        """
        Build and execute a Drive name search.

        Query construction:
        - name contains '{query}' AND trashed = false
        - AND mimeType != 'application/vnd.google-apps.folder'

        Request params:
        - fields: files(id,name,mimeType,modifiedTime)
        - pageSize: 8
        - orderBy: modifiedTime desc

        Returns the raw response object from drive_request().
        """

        q = (query or "").strip()
        if not q:
            self._log_err("search_files_by_name called with empty query.")
            return None

        # Drive query strings are wrapped in single quotes. Escape any single quotes
        # in user input to avoid breaking the query.
        safe_q = q.replace("'", "\\'")

        drive_q = (
            f"trashed = false and "
            f"mimeType != 'application/vnd.google-apps.folder' and "
            f"name contains '{safe_q}'"
        )

        params = {
            "q": drive_q,
            "fields": "files(id,name,mimeType,modifiedTime)",
            "pageSize": 8,
            "orderBy": "modifiedTime desc",
        }

        return await self.drive_request("GET", "/files", params=params)

    # TODO: Normalize modifiedTime in P2
    async def handle_search_results(self, files: List[Dict], query: str):
        """
        Process and speak search results.

        1. Limit to first 5 files
        2. Map MIME types to spoken labels via _mime_label()
        3. Cache files in self.prefs['recent_results'] (for future follow-ups)
        4. Save prefs
        5. Use text_to_text_response to generate natural spoken output
           - Pass file list as context
           - System prompt: concise voice output, no bullets
        6. Speak the LLM response
        """

        try:
            top_files = files[:5]

            # Build structured context for LLM
            summarized = []
            for f in top_files:
                summarized.append({
                    "name": f.get("name"),
                    "type": self._mime_label(f.get("mimeType", "")),
                    "modifiedTime": f.get("modifiedTime"),
                    "id": f.get("id"),
                })

            # Cache for future follow-ups (P0 forward-compat)
            self.prefs["recent_results"] = summarized
            await self.save_prefs()

            system_prompt = (
                "You are a Google Drive voice assistant.\n"
                "Respond with concise, natural speech.\n"
                "No bullet points. No numbering.\n"
                "Short sentences. Voice-friendly.\n"
                "Mention file type naturally.\n"
            )

            user_prompt = (
                f"The user searched for: '{query}'.\n"
                f"Here are the top matching files:\n"
                f"{json.dumps(summarized)}\n\n"
                "Generate a brief spoken response."
            )

            response_text = self.capability_worker.text_to_text_response(
                user_prompt,
                system_prompt=system_prompt,
            )

            if not response_text:
                raise ValueError("Empty LLM response for search results.")

            # Strip accidental markdown fences (rare but defensive)
            cleaned = response_text.replace("```", "").strip()

            await self.capability_worker.speak(cleaned)

        except Exception as e:
            self._log_err(f"handle_search_results error: {e}")
            await self.capability_worker.speak(
                "I found some files, but had trouble describing them."
            )

    # =========================================================================
    # Trigger Classification
    # =========================================================================

    def get_trigger_context(self) -> str:
        """
        Extract recent user messages from agent_memory.full_message_history.

        - Get last 3-5 user-role messages
        - Join into a single string (oldest → newest)
        - Return empty string if no history
        - Never raise
        """

        try:
            history = self.worker.agent_memory.full_message_history
            if not history or not isinstance(history, list):
                return ""

            # Collect user-role messages
            user_messages = []

            for msg in history:
                if not isinstance(msg, dict):
                    continue

                role = msg.get("role")
                content = msg.get("content")

                if role == "user" and isinstance(content, str):
                    user_messages.append(content.strip())

            if not user_messages:
                return ""

            # Take last 5 user messages
            recent = user_messages[-5:]

            # Join oldest → newest for context clarity
            return "\n".join(recent)

        except Exception as e:
            self._log_err(f"get_trigger_context error: {e}")
            return ""

    def classify_trigger_context(self, text: str) -> Dict[str, Any]:
        """
        Use LLM to classify trigger into a mode.

        - Call capability_worker.text_to_text_response (synchronous)
        - Prompt for JSON: {mode, search_query}
        - Strip markdown fences safely
        - Return parsed dict
        - On parse failure: return {"mode": "find", "search_query": None}
        - Modes: find | whats_new | read_doc | quick_save | folder_browse
        """

        if not text or not text.strip():
            return {"mode": "find", "search_query": None}

        system_prompt = (
            "You are a classifier for a Google Drive voice assistant.\n"
            "Return ONLY valid JSON. No markdown. No explanation.\n\n"
            "Schema:\n"
            "{\n"
            '  "mode": "find | whats_new | read_doc | quick_save | folder_browse",\n'
            '  "search_query": string or null\n'
            "}\n\n"
            "Rules:\n"
            "- If user wants to search for a file, mode = find.\n"
            "- If asking what’s new or recent files, mode = whats_new.\n"
            "- If asking to open or read a document, mode = read_doc.\n"
            "- If asking to save something quickly, mode = quick_save.\n"
            "- If asking to browse folders, mode = folder_browse.\n"
            "- If unsure, default to mode = find.\n"
            "- Extract a clean search_query when possible.\n"
        )

        try:
            raw_response = self.capability_worker.text_to_text_response(
                text,
                system_prompt=system_prompt,
            )

            if not raw_response:
                raise ValueError("Empty LLM response")

            cleaned = raw_response.strip()

            # Safe markdown fence stripping
            cleaned = cleaned.replace("```json", "")
            cleaned = cleaned.replace("```", "")
            cleaned = cleaned.strip()

            parsed = json.loads(cleaned)

            if not isinstance(parsed, dict):
                raise ValueError("Parsed response is not a dict")

            mode = parsed.get("mode", "find")
            search_query = parsed.get("search_query")

            allowed_modes = {
                "find",
                "whats_new",
                "read_doc",
                "quick_save",
                "folder_browse",
            }

            if mode not in allowed_modes:
                mode = "find"

            if search_query is not None and not isinstance(search_query, str):
                search_query = None

            return {
                "mode": mode,
                "search_query": search_query,
            }

        except Exception as e:
            self._log_err(f"Classification failed: {e}")
            return {"mode": "find", "search_query": None}
