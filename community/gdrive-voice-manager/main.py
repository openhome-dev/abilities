import json
import os
import time
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import re

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
    "stop",
    "exit",
    "quit",
    "done",
    "i'm done",
    "im done",
    "cancel",
    "bye",
    "never mind",
    "no thanks",
    "i'm good",
    "im good",
    "nope",
}

TUTORIAL_EXIT_WORDS = {
    "stop",
    "exit",
    "quit",
    "cancel",
    "bye",
    "never mind",
}

HELP_WORDS = {
    "can't",
    "cannot",
    "dont",
    "don't",
    "where",
    "help",
    "confused",
    "stuck",
    "not sure",
    "what",
    "how",
}


class GDriveVoiceManager(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    prefs: Dict[str, Any] = {}

    # =========================================================================
    # Registration
    # =========================================================================

    #{{register capability}}

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
                    "Before I can access your Drive, I need to connect via OAuth."
                )

                skip_walkthrough = await self.capability_worker.run_confirmation_loop(
                    "Do you already have a Client ID and Client Secret ready?"
                )

                success = await self.run_oauth_setup_flow(
                    skip_walkthrough=skip_walkthrough
                )
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
            # Unified conversation loop
            # -----------------------------------------------------------------
            await self._conversation_loop(trigger_context)

            self.capability_worker.resume_normal_flow()
            return

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[GDrive] Unhandled error in run(): {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Let me hand you back."
            )
            self.capability_worker.resume_normal_flow()

    # =========================================================================
    # Central Dispatcher (P1)
    # =========================================================================

    async def dispatch(self, classification: Dict[str, Any]):
        """
        Route classified command to correct handler.

        Handles missing required fields gracefully by prompting user.
        Does NOT call resume_normal_flow().
        """

        mode = classification.get("mode", "name_search")
        search_query = classification.get("search_query")
        file_reference = classification.get("file_reference")
        folder_name = classification.get("folder_name")
        note_content = classification.get("note_content")
        classification.get("file_type", "any")

        # ----------------------------
        # NAME SEARCH (default)
        # ----------------------------
        if mode == "name_search":
            if not search_query:
                await self.capability_worker.speak(
                    "What file title should I search for?"
                )
                return

            await self._run_find(search_query, classification)
            return

        # ----------------------------
        # CONTENT SEARCH
        # ----------------------------
        if mode == "content_search":
            if not search_query:
                await self.capability_worker.speak(
                    "What phrase should I search for inside documents?"
                )
                return

            await self._run_find(search_query, classification)
            return

        # ----------------------------
        # WHAT'S NEW
        # ----------------------------
        if mode == "whats_new":
            await self._run_whats_new()
            return

        # ----------------------------
        # READ DOC
        # ----------------------------
        if mode == "read_doc":
            if not file_reference:
                await self.capability_worker.speak(
                    "What file should I read?"
                )
                return

            await self._run_read_doc(file_reference)
            return

        # ----------------------------
        # QUICK SAVE
        # ----------------------------
        if mode == "quick_save":
            if not note_content:
                await self.capability_worker.speak(
                    "What would you like me to save?"
                )
                return

            await self._run_quick_save(note_content)
            return

        # ----------------------------
        # FOLDER BROWSE
        # ----------------------------
        if mode == "folder_browse":
            if not folder_name:
                await self.capability_worker.speak(
                    "Which folder would you like to browse?"
                )
                return

            await self._run_folder_browse(folder_name)
            return

        # ----------------------------
        # SET NOTES FOLDER (P2)
        # ----------------------------
        if mode == "set_notes_folder":
            if not folder_name:
                await self.capability_worker.speak(
                    "Which folder should I use for saving notes?"
                )
                return

            await self._run_set_notes_folder(folder_name)
            return

        # ----------------------------
        # EXPAND DOC
        # ----------------------------
        if mode == "expand_doc":
            await self._run_expand_doc()
            return

        # ----------------------------
        # Fallback
        # ----------------------------
        await self.capability_worker.speak(
            "I can search, read documents, list recent files, "
            "save notes, or browse folders. What would you like to do?"
        )

    # =========================================================================
    # Unified Conversation Loop
    # =========================================================================

    async def _conversation_loop(self, trigger_context: str = ""):
        """
        Single conversation loop that handles all turns uniformly.

        Turn 0: classify and dispatch the trigger context (if any).
        Turn 1+: listen → resolve-from-recent shortcut → classify → dispatch.

        - Idle counter: 2 consecutive silent turns → exit
        - Exit words → exit
        - Hard cap of 20 turns
        """

        max_turns = 20
        turn_count = 0
        idle_count = 0

        # ---------------------------------------------------------
        # Turn 0: handle the trigger that activated the ability
        # ---------------------------------------------------------
        if trigger_context and trigger_context.strip():
            classification = self.classify_trigger_context(trigger_context)
            await self.dispatch(classification)
            turn_count += 1

        # ---------------------------------------------------------
        # Subsequent turns: listen → route
        # ---------------------------------------------------------
        while turn_count < max_turns:
            user_input = await self.capability_worker.user_response()

            # Silence handling
            if not user_input or not user_input.strip():
                idle_count += 1
                if idle_count >= 2:
                    break
                continue

            idle_count = 0

            # Exit handling
            if self._is_exit(user_input):
                break

            # ---------------------------------------------------------
            # Deterministic shortcut: expand currently open document
            # (belt-and-suspenders for "go deeper" style requests)
            # ---------------------------------------------------------
            lower_input = user_input.lower().strip()
            if (
                self.prefs.get("_session_current_doc_id")
                and any(phrase in lower_input for phrase in [
                    "go deeper",
                    "more detail",
                    "expand",
                    "more about this",
                ])
            ):
                await self._run_expand_doc()
                turn_count += 1
                continue

            # ---------------------------------------------------------
            # Deterministic shortcut: resolve from recent results
            # (handles "the second one", partial name matches, etc.)
            # ---------------------------------------------------------
            match = self._resolve_from_recent(user_input)
            if match:
                await self._run_read_doc(match.get("name"))
                turn_count += 1
                continue

            # ---------------------------------------------------------
            # Classify and dispatch
            # ---------------------------------------------------------
            classification = self.classify_trigger_context(user_input)
            await self.dispatch(classification)

            turn_count += 1

        # Graceful exit
        await self.capability_worker.speak("Let me know if you need anything else.")

    # =========================================================================
    # Expand Doc — extracted from old "go deeper" logic
    # =========================================================================

    async def _run_expand_doc(self):
        """
        Provide a more detailed explanation of the currently active document.

        Relies on session state:
        - _session_current_doc_id
        - _session_current_doc_name
        - _session_current_doc_mime

        If no document is active, tells the user.
        """

        file_id = self.prefs.get("_session_current_doc_id")
        name = self.prefs.get("_session_current_doc_name", "this document")
        mime = self.prefs.get("_session_current_doc_mime")

        if not file_id:
            await self.capability_worker.speak(
                "I don't have a document open right now. "
                "Try searching for a file first, then ask me to go deeper."
            )
            return

        resp = await self._export_file_content(file_id, mime)

        if not resp or resp.status_code != 200:
            await self.capability_worker.speak(
                "I couldn't retrieve that document for a deeper read."
            )
            return

        content = resp.text or ""

        words = content.split()
        if len(words) > 3000:
            content = " ".join(words[:3000])

        if not content.strip():
            await self.capability_worker.speak(
                "That document appears to be empty."
            )
            return

        prompt = (
            f"Provide a more detailed explanation of the following document.\n\n"
            f"Document title: {name}\n\n"
            f"{content}"
        )

        await self.capability_worker.speak(
            f"I'm preparing a deeper summary of {name} for you."
        )

        deeper = self.capability_worker.text_to_text_response(
            prompt,
            system_prompt="Provide a deeper explanation. Conversational. No bullet points.",
        )

        if deeper:
            await self.capability_worker.speak(deeper.strip())
        else:
            await self.capability_worker.speak(
                "I wasn't able to generate a deeper summary."
            )

    # =========================================================================
    # Relative Timestamp Utility (P1)
    # =========================================================================

    def _format_relative_time(self, iso_string: str) -> str:
        """
        Convert ISO 8601 timestamp (Drive modifiedTime) into
        natural spoken relative time.

        Behavior:
        - < 60 seconds → "just now"
        - < 60 minutes → "X minutes ago"
        - < 24 hours → "X hours ago"
        - 1 day → "Yesterday"
        - < 7 days → "X days ago"
        - < 30 days → "X weeks ago"
        - < 365 days → "X months ago"
        - ≥ 365 days → "X years ago"

        If relative-time calculation fails but the timestamp
        can still be parsed, returns an absolute date in the
        format: "on February 12, 2026".

        If parsing completely fails, returns the original string.
        """

        if not iso_string or not isinstance(iso_string, str):
            return iso_string

        try:
            # Handle trailing Z (UTC)
            if iso_string.endswith("Z"):
                iso_string = iso_string.replace("Z", "+00:00")

            dt = datetime.fromisoformat(iso_string)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            delta = now - dt

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
            # Fallback to date-only readable format if possible
            try:
                dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
                return dt.strftime("on %B %d, %Y")
            except Exception:
                return iso_string

    # =========================================================================
    # Find Files — P0 Core
    # =========================================================================

    async def _run_find(self, query: str, classification: Optional[Dict[str, Any]] = None):
        """Enhanced find: supports MIME filtering + name/content search + LLM-formatted output."""
        if not query.strip():
            await self.capability_worker.speak(
                "I need a file name to search for."
            )
            return

        mode = classification.get("mode") if classification else "name_search"

        if mode == "content_search":
            await self.capability_worker.speak(
                f"Searching inside documents for {query}."
            )
        else:
            await self.capability_worker.speak(
                f"Searching file titles for {query}."
            )

        # -------------------------------------------------------------
        # Determine file_type (default any)
        # -------------------------------------------------------------
        file_type = "any"
        if classification:
            file_type = classification.get("file_type", "any")

        mime_map = {
            "doc": "application/vnd.google-apps.document",
            "sheet": "application/vnd.google-apps.spreadsheet",
            "slides": "application/vnd.google-apps.presentation",
            "pdf": "application/pdf",
        }

        # -------------------------------------------------------------
        # Build Drive query
        # -------------------------------------------------------------
        safe_query = (query or "").strip().replace("'", "\\'")
        if mode == "content_search":
            search_clause = f"fullText contains '{safe_query}'"
        else:
            search_clause = f"name contains '{safe_query}'"

        q_parts = ["trashed = false", search_clause]

        if file_type in mime_map:
            q_parts.append(f"mimeType = '{mime_map[file_type]}'")
        else:
            # Avoid folders polluting results unless explicitly searching for folders
            q_parts.append("mimeType != 'application/vnd.google-apps.folder'")

        drive_query = " and ".join(q_parts)

        resp = await self.drive_request(
            "GET",
            "/files",
            params={
                "q": drive_query,
                "fields": "files(id,name,mimeType,modifiedTime)",
                "pageSize": 8,
                "orderBy": "modifiedTime desc",
            },
        )

        if resp is None:
            await self.capability_worker.speak(
                "I couldn't reach Google Drive right now."
            )
            return

        if resp.status_code != 200:
            self._log_err(f"Find failed: {resp.status_code} {resp.text[:200]}")
            await self.capability_worker.speak(
                "Something went wrong while searching your Drive."
            )
            return

        data = resp.json()
        files = data.get("files", [])

        if not files:
            await self.capability_worker.speak(
                f"I couldn't find any files matching {query}."
            )
            return

        # Let the existing LLM formatter speak naturally + cache summarized results.
        await self.handle_search_results(files, query)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _is_exit(self, text: str) -> bool:
        if not text:
            return False

        normalized = text.lower().strip()

        # Collapse punctuation to spaces
        normalized = re.sub(r"[^\w\s']", " ", normalized)
        normalized = " ".join(normalized.split())

        return normalized in EXIT_WORDS

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
        - Write json.dumps(filtered prefs without _session_ keys)
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

            # Strip session-only keys before persisting
            to_persist = {
                k: v for k, v in self.prefs.items()
                if not k.startswith("_session_")
            }

            serialized = json.dumps(to_persist)

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

    async def run_oauth_setup_flow(self, skip_walkthrough: bool = False) -> bool:
        """
        Guide user through Google OAuth setup.

        If skip_walkthrough is True, collect Client ID/Secret directly.
        Otherwise, run full Google Cloud Console walkthrough.
        """
        try:
            # ---------------------------------------------------------
            # Step 1: Walk through Google Cloud Console setup
            # ---------------------------------------------------------
            if not skip_walkthrough:
                await self.capability_worker.speak(
                    "To connect Google Drive, you'll need to create "
                    "credentials in the Google Cloud Console."
                )
                await self.capability_worker.speak(
                    "I'll walk you through it."
                )
                await self.capability_worker.speak(
                    "Step one. Go to console dot cloud dot google dot com."
                )
                await self.capability_worker.speak(
                    "Create a new project or pick an existing one."
                )
                await self.capability_worker.speak(
                    "If you're creating a new project, make sure you click on the project "
                    "to select it after creating it."
                )
                await self.capability_worker.speak(
                    "Tell me when that's done."
                )
                while True:
                    user_input = (await self.capability_worker.user_response() or "").lower().strip()

                    # --- Exit handling ---
                    if any(word in user_input for word in TUTORIAL_EXIT_WORDS):
                        await self.capability_worker.speak(
                            "No problem. We can finish setup later."
                        )
                        return False

                    # --- Help handling ---
                    if any(word in user_input for word in HELP_WORDS):
                        await self.capability_worker.speak(
                            "No worries. Look at the project picker at the top of the page "
                            "If you're not seeing it, double check that you're at console "
                            "dot google cloud dot com and you're signed in"
                        )
                        await self.capability_worker.speak(
                            "Tell me when you're ready to continue."
                        )
                        continue

                    # --- Default: treat as confirmation ---
                    break
                await self.capability_worker.speak(
                    "Step two. In the navigation menu on your left, "
                    "go to APIs and Services, then Library."
                )
                await self.capability_worker.speak(
                    "Search for Google Drive API and enable it."
                )
                await self.capability_worker.speak(
                    "Tell me when that's done."
                )
                while True:
                    user_input = (await self.capability_worker.user_response() or "").lower().strip()

                    # --- Exit handling ---
                    if any(word in user_input for word in TUTORIAL_EXIT_WORDS):
                        await self.capability_worker.speak(
                            "No problem. We can finish setup later."
                        )
                        return False

                    # --- Help handling ---
                    if any(word in user_input for word in HELP_WORDS):
                        await self.capability_worker.speak(
                            "No worries. Look at the left navigation menu. "
                            "If you're not seeing it, try expanding the menu icon in the top left."
                        )
                        await self.capability_worker.speak(
                            "Tell me when you're ready to continue."
                        )
                        continue

                    # --- Default: treat as confirmation ---
                    break
                await self.capability_worker.speak(
                    "Step three. Go to APIs and Services, then Credentials. "
                    "Click Create Credentials and choose OAuth client ID."
                )
                await self.capability_worker.speak(
                    "If it asks you to configure a consent screen, "
                    "choose External."
                )
                await self.capability_worker.speak(
                    "Fill in the app name and add your email."
                )
                await self.capability_worker.speak(
                    "Then click save."
                )
                await self.capability_worker.speak(
                    "Tell me when that's done."
                )
                while True:
                    user_input = (await self.capability_worker.user_response() or "").lower().strip()

                    # --- Exit handling ---
                    if any(word in user_input for word in TUTORIAL_EXIT_WORDS):
                        await self.capability_worker.speak(
                            "No problem. We can finish setup later."
                        )
                        return False

                    # --- Help handling ---
                    if any(word in user_input for word in HELP_WORDS):
                        await self.capability_worker.speak(
                            "No worries. Look at the left navigation menu. "
                            "If you're not seeing it, try expanding the menu icon in the top left."
                        )
                        await self.capability_worker.speak(
                            "Tell me when you're ready to continue."
                        )
                        continue

                    # --- Default: treat as confirmation ---
                    break
                await self.capability_worker.speak(
                    "Open the navigation menu again."
                )
                await self.capability_worker.speak(
                    "Go to APIs and Services, then OAuth Consent Screen."
                )
                await self.capability_worker.speak(
                    "Click Audience, then click Add Users at the bottom."
                )
                await self.capability_worker.speak(
                    "Add your email as a test user."
                )
                await self.capability_worker.speak(
                    "Tell me when that's done."
                )
                while True:
                    user_input = (await self.capability_worker.user_response() or "").lower().strip()

                    # --- Exit handling ---
                    if any(word in user_input for word in TUTORIAL_EXIT_WORDS):
                        await self.capability_worker.speak(
                            "No problem. We can finish setup later."
                        )
                        return False

                    # --- Help handling ---
                    if any(word in user_input for word in HELP_WORDS):
                        await self.capability_worker.speak(
                            "No worries. Look at the left navigation menu. "
                            "If you're not seeing it, try expanding the menu icon in the top left."
                        )
                        await self.capability_worker.speak(
                            "If you can't find the Audience button, look below the button"
                            "that expands the navigation menu"
                        )
                        await self.capability_worker.speak(
                            "Tell me when you're ready to continue."
                        )
                        continue

                    # --- Default: treat as confirmation ---
                    break
                await self.capability_worker.speak(
                    "Step four. Click on clients on the left side of your screen. Then click "
                    "create client at the top. Choose Desktop App as the type."
                )
                await self.capability_worker.speak(
                    "Name it whatever you like."
                )
                await self.capability_worker.speak(
                    "Then copy the Client ID and Client Secret."
                )
            else:
                await self.capability_worker.speak(
                    "Great. Let's connect your existing credentials."
                )

            # ---------------------------------------------------------
            # Step 2: Collect Client ID
            # ---------------------------------------------------------
            await self.capability_worker.speak(
                "When you have your Client ID, paste it here."
            )

            client_id = await self.capability_worker.user_response()

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
                "Now I need you to authorize access."
            )
            await self.capability_worker.speak(
                "I've sent an authorization link."
            )
            await self.capability_worker.speak(
                "Open it in your browser and sign in with your Google account."
            )
            await self.capability_worker.speak(
                "After you approve, the browser will try to redirect "
                "and show an error page."
            )
            await self.capability_worker.speak(
                "That's expected."
            )
            await self.capability_worker.speak(
                "Look at the URL bar."
            )
            await self.capability_worker.speak(
                "Copy everything after code equals."
            )
            await self.capability_worker.speak(
                "Stop at the ampersand symbol."
            )
            await self.capability_worker.speak(
                "Then paste that code here."
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
            self.prefs["token_expires_at"] = time.time() + int(expires_in) - 60

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

    async def _invalidate_tokens(self):
        """
        Clear stored OAuth tokens when refresh_token is invalid.
        Forces full OAuth re-auth next run.
        """
        self._log("Invalidating stored OAuth tokens.")

        self.prefs.pop("access_token", None)
        self.prefs.pop("refresh_token", None)
        self.prefs.pop("token_expires_at", None)

        await self.save_prefs()

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

                error_code = error_data.get("error")

                if error_code in ("invalid_grant", "invalid_client"):
                    self._log_err(f"Refresh failed ({error_code}). Invalidating tokens.")

                    # Clear stored tokens so OAuth gate triggers
                    await self._invalidate_tokens()

                    return False

                # Non-invalid_grant/non-invalid_client error
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

                    await self.capability_worker.speak(
                        "Your Google authorization has expired. "
                        "I'll need to reconnect your Drive."
                    )

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

            # -------------------------------------------------------------
            # Ensure uploadType=multipart for upload endpoint
            # -------------------------------------------------------------
            if upload:
                if params is None:
                    params = {}
                else:
                    # Avoid mutating original caller dict
                    params = dict(params)

                # Only set if not already provided explicitly
                if "uploadType" not in params:
                    params["uploadType"] = "multipart"

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

                    await self.capability_worker.speak(
                        "Your Google authorization has expired. "
                        "I'll need to reconnect your Drive."
                    )

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

            # -------------------------------------------------------------
            # Conservative 403 handling (AFTER 401 logic)
            # -------------------------------------------------------------
            if response.status_code == 403:
                try:
                    error_payload = response.json().get("error", {})
                    message = error_payload.get("message", "").lower()
                except Exception:
                    message = ""

                # Only invalidate if clearly an authentication scope issue
                if "authentication scopes" in message:
                    self._log_err(
                        "403 due to insufficient authentication scopes."
                    )

                    await self._invalidate_tokens()

                    await self.capability_worker.speak(
                        "Your Google authorization is no longer valid. "
                        "I'll need to reconnect your Drive."
                    )

                    return None

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
                rel = None
                mt = f.get("modifiedTime")
                if isinstance(mt, str) and mt.strip():
                    rel = self._format_relative_time(mt)
                summarized.append({
                    "name": f.get("name"),
                    "mimeType": f.get("mimeType"),
                    "type": self._mime_label(f.get("mimeType", "")),
                    "modified": rel,
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
    # Read Doc — P1
    # =========================================================================

    def _resolve_from_recent(self, user_input: str) -> Optional[Dict]:
        """
        Resolve a file selection from cached recent_results.

        Priority:
        1. Exact name match
        2. Partial name match
        3. Ordinal reference
        """

        files = self.prefs.get("recent_results", [])
        if not files or not user_input:
            return None

        # Guard: only treat short utterances as file selections.
        # Longer commands (e.g., "save a note to drive...") should be classified normally.
        if len(user_input.split()) > 6:
            return None

        ref = user_input.strip().lower()

        # Exact match
        for f in files:
            if (f.get("name") or "").lower() == ref:
                return f

        # Partial match
        for f in files:
            name_lower = (f.get("name") or "").lower()
            if ref and ref in name_lower:
                return f

        # Ordinal match
        ordinal_map = {
            "first": 0,
            "second": 1,
            "third": 2,
            "fourth": 3,
            "fifth": 4,
            "1": 0,
            "2": 1,
            "3": 2,
            "4": 3,
            "5": 4,
        }

        for word, idx in ordinal_map.items():
            if word in ref and idx < len(files):
                return files[idx]

        return None

    # =========================================================================
    # Shared Export Helper
    # =========================================================================

    async def _export_file_content(self, file_id: str, mime: str):
        """Export file content using correct MIME branching."""

        if mime == "application/vnd.google-apps.document":
            return await self.drive_request(
                "GET", f"/files/{file_id}/export",
                params={"mimeType": "text/plain"}
            )

        if mime == "application/vnd.google-apps.spreadsheet":
            return await self.drive_request(
                "GET", f"/files/{file_id}/export",
                params={"mimeType": "text/csv"}
            )

        if mime == "application/vnd.google-apps.presentation":
            return await self.drive_request(
                "GET", f"/files/{file_id}/export",
                params={"mimeType": "text/plain"}
            )

        # Fallback for non-Google files
        return await self.drive_request(
            "GET", f"/files/{file_id}", params={"alt": "media"}
        )

    async def _run_read_doc(self, file_reference: str):
        """
        Read and summarize a document.

        Resolution priority:
        1. Exact name match in recent_results
        2. Ordinal reference (first, second, 1, 2...)
        3. Fallback: search by name
        """

        if not file_reference or not file_reference.strip():
            await self.capability_worker.speak(
                "What file should I read?"
            )
            return

        target = self._resolve_from_recent(file_reference)

        # -------------------------------------------------------------
        # 3. Fallback search by name
        # -------------------------------------------------------------
        if not target:
            await self.capability_worker.speak(
                "Searching file titles for that document."
            )
            safe_ref = (file_reference or "").strip().replace("'", "\\'")
            resp = await self.drive_request(
                "GET",
                "/files",
                params={
                    "q": (
                        f"name contains '{safe_ref}' and trashed = false"
                    ),
                    "pageSize": 1,
                    "fields": "files(id,name,mimeType,modifiedTime)",
                },
            )

            if resp and resp.status_code == 200:
                data = resp.json()
                matches = data.get("files", [])
                if matches:
                    target = matches[0]

        if not target:
            await self.capability_worker.speak(
                "I couldn't find that file."
            )
            return

        file_id = target.get("id")
        mime = target.get("mimeType", "")
        name = target.get("name", "Untitled")

        await self.capability_worker.speak(f"Reading {name}.")

        if mime == "application/pdf":
            await self.capability_worker.speak(
                "I can't read PDF files aloud yet."
            )
            return

        resp = await self._export_file_content(file_id, mime)

        if resp is None:
            await self.capability_worker.speak(
                "I couldn't access that file."
            )
            return

        if resp.status_code != 200:
            self._log_err(
                f"Read export failed: {resp.status_code} {resp.text[:200]}"
            )
            await self.capability_worker.speak(
                "That file may be too large or restricted."
            )
            return

        # -------------------------------------------------------------
        # Content-Length guard (prevent large exports / memory spikes)
        # -------------------------------------------------------------
        try:
            content_length = int(resp.headers.get("Content-Length", "0"))
        except Exception:
            content_length = 0

        # Guard at ~8MB (Drive export hard limit is 10MB)
        if content_length and content_length > 8 * 1024 * 1024:
            self._log_err(
                f"Read aborted: file too large ({content_length} bytes)"
            )
            await self.capability_worker.speak(
                "That document is too large for me to read aloud."
            )
            return

        content = resp.text

        if not content or not content.strip():
            await self.capability_worker.speak(
                "That file appears to be empty."
            )
            return

        # -------------------------------------------------------------
        # Truncate to ~3000 words
        # -------------------------------------------------------------
        words = content.split()
        if len(words) > 3000:
            content = " ".join(words[:3000])

        # Store session pointer only (not persisted)
        self.prefs["_session_current_doc_id"] = file_id
        self.prefs["_session_current_doc_name"] = name
        self.prefs["_session_current_doc_mime"] = mime

        # -------------------------------------------------------------
        # Summarize via LLM for voice
        # -------------------------------------------------------------
        system_prompt = (
            "You summarize documents for spoken output.\n"
            "3 to 5 sentences. Conversational. No bullet points."
        )

        try:
            prompt_text = (
                "Summarize this document for voice output. "
                "Be concise, 3 to 5 sentences. Focus on key points and conclusions.\n\n"
                f"Document title: {name}\n"
                "Content:\n"
                f"{content}"
            )

            summary = self.capability_worker.text_to_text_response(
                prompt_text,
                system_prompt=system_prompt,
            )

            if summary:
                await self.capability_worker.speak(summary.strip())
                await self.capability_worker.speak(
                    "Want me to go deeper into this, or would you "
                    "like me to read another file? If you'd "
                    "like me to read another file, just say the file's name."
                )
            else:
                await self.capability_worker.speak(
                    "I couldn't summarize that document."
                )

        except Exception as e:
            self._log_err(f"Summarization failed: {e}")
            await self.capability_worker.speak(
                "Something went wrong while summarizing the document."
            )

    # =========================================================================
    # Folder Browse — P1
    # =========================================================================

    async def _run_folder_browse(self, folder_name: str):
        """
        Browse contents of a folder.

        Resolution priority:
        1. Exact folder name match (API)
        2. Partial name match
        3. Clarify if multiple
        """
        # TODO: when multiple folders are found and the user is prompted to clarify, there's no logic to capture their response and continue. The method just returns after speaking the options. The user's answer goes nowhere — it'll fall back to the main flow or follow-up loop (which doesn't exist yet). This is fine for now since the follow-up loop (step 10) will handle re-classification of the user's response, but worth flagging so it doesn't get forgotten. Once the follow-up loop is in place, the user saying "the first one" or "Marketing 2025" after disambiguation should re-enter the dispatcher and resolve correctly.

        if not folder_name or not folder_name.strip():
            await self.capability_worker.speak(
                "Which folder would you like to browse?"
            )
            return

        safe_name = folder_name.strip().replace("'", "\\'")

        # -------------------------------------------------------------
        # 1. Find matching folders
        # -------------------------------------------------------------
        resp = await self.drive_request(
            "GET",
            "/files",
            params={
                "q": (
                    "mimeType = 'application/vnd.google-apps.folder' "
                    f"and name contains '{safe_name}' "
                    "and trashed = false"
                ),
                "fields": "files(id,name,modifiedTime)",
                "pageSize": 5,
            },
        )

        if resp is None:
            await self.capability_worker.speak(
                "I couldn't reach Google Drive."
            )
            return

        if resp.status_code != 200:
            self._log_err(
                f"Folder search failed: {resp.status_code} {resp.text[:200]}"
            )
            await self.capability_worker.speak(
                "Something went wrong while looking for that folder."
            )
            return

        data = resp.json()
        folders = data.get("files", [])

        if not folders:
            await self.capability_worker.speak(
                f"I couldn't find a folder named {folder_name}."
            )
            return

        if len(folders) > 1:
            names = ", ".join(f.get("name", "") for f in folders[:3])
            await self.capability_worker.speak(
                f"I found multiple folders: {names}. Which one did you mean?"
            )
            return

        folder = folders[0]
        folder_id = folder.get("id")
        folder_display_name = folder.get("name", "that folder")

        await self.capability_worker.speak(
            f"Here are the contents of {folder_display_name}."
        )

        # -------------------------------------------------------------
        # 2. List folder contents
        # -------------------------------------------------------------
        resp = await self.drive_request(
            "GET",
            "/files",
            params={
                "q": (
                    f"'{folder_id}' in parents "
                    "and trashed = false"
                ),
                "orderBy": "modifiedTime desc",
                "pageSize": 10,
                "fields": "files(id,name,mimeType,modifiedTime)",
            },
        )

        if resp is None:
            await self.capability_worker.speak(
                "I couldn't retrieve that folder's contents."
            )
            return

        if resp.status_code != 200:
            self._log_err(
                f"Folder list failed: {resp.status_code} {resp.text[:200]}"
            )
            await self.capability_worker.speak(
                "Something went wrong while listing that folder."
            )
            return

        data = resp.json()
        files = data.get("files", [])

        if not files:
            await self.capability_worker.speak(
                "That folder is empty."
            )
            return

        # Deterministic folder listing (no LLM)
        top_files = files[:5]

        # Cache for follow-up selection
        summarized = []
        for f in top_files:
            summarized.append({
                "name": f.get("name"),
                "mimeType": f.get("mimeType"),
                "type": self._mime_label(f.get("mimeType", "")),
                "id": f.get("id"),
            })
        self.prefs["recent_results"] = summarized
        await self.save_prefs()

        descriptions = []
        for f in top_files:
            name = f.get("name", "Untitled")
            mime = f.get("mimeType", "")
            file_type = self._mime_label(mime)

            modified = None
            mt = f.get("modifiedTime")
            if isinstance(mt, str) and mt.strip():
                modified = self._format_relative_time(mt)

            if modified:
                descriptions.append(
                    f"{file_type} titled \"{name}\" modified {modified}"
                )
            else:
                descriptions.append(
                    f"{file_type} titled \"{name}\""
                )

        if descriptions:
            joined = ". ".join(descriptions) + "."
            await self.capability_worker.speak(
                f"In {folder_display_name}, I see: {joined}"
            )

    # =========================================================================
    # Set Notes Folder — P2
    # =========================================================================

    async def _run_set_notes_folder(self, folder_name: str):
        """
        Configure a folder where Quick Save will create documents.

        - Searches for matching Drive folders
        - Stores folder ID in prefs
        - Used by Quick Save
        """

        if not folder_name or not folder_name.strip():
            await self.capability_worker.speak(
                "Which folder would you like me to use for notes?"
            )
            return

        safe_name = folder_name.strip().replace("'", "\\'")

        resp = await self.drive_request(
            "GET",
            "/files",
            params={
                "q": (
                    "mimeType = 'application/vnd.google-apps.folder' "
                    f"and name contains '{safe_name}' "
                    "and trashed = false"
                ),
                "fields": "files(id,name)",
                "pageSize": 5,
            },
        )

        if not resp or resp.status_code != 200:
            await self.capability_worker.speak(
                "I couldn't find that folder."
            )
            return

        data = resp.json()
        folders = data.get("files", [])

        if not folders:
            await self.capability_worker.speak(
                f"I couldn't find a folder named {folder_name}."
            )
            return

        # Pick first match (deterministic)
        folder = folders[0]

        self.prefs["notes_folder_id"] = folder.get("id")
        self.prefs["notes_folder_name"] = folder.get("name")
        await self.save_prefs()

        await self.capability_worker.speak(
            f"Got it. I'll save future notes to {folder.get('name')}."
        )

    # =========================================================================
    # Quick Save — P1
    # =========================================================================

    async def _run_quick_save(self, note_content: str):
        """
        Save a quick note to Drive as a text file.

        Steps:
        1. Use LLM to extract title + cleaned body.
        2. Build multipart upload payload.
        3. POST to /files (upload endpoint).
        4. Confirm to user.
        """

        if not note_content or not note_content.strip():
            await self.capability_worker.speak(
                "What would you like me to save?"
            )
            return

        # -------------------------------------------------------------
        # 1. Extract title + body via LLM
        # -------------------------------------------------------------
        system_prompt = (
            "You extract structured note data.\n"
            "Return ONLY valid JSON. No markdown.\n\n"
            "Schema:\n"
            "{\n"
            '  "title": string (3-8 words),\n'
            '  "body": string (cleaned full note text)\n'
            "}"
        )

        try:
            raw = self.capability_worker.text_to_text_response(
                note_content,
                system_prompt=system_prompt,
            )

            cleaned = (
                raw.replace("```json", "")
                .replace("```", "")
                .strip()
            )

            parsed = json.loads(cleaned)

            title = parsed.get("title")
            body = parsed.get("body")

            if not title or not body:
                raise ValueError("Missing title/body in LLM output")

        except Exception as e:
            self._log_err(f"Quick Save LLM parse failed: {e}")
            # Fallback: simple title from first few words
            words = note_content.strip().split()
            title = " ".join(words[:6]) or "Quick Note"
            body = note_content.strip()

        # Sanitize filename
        safe_title = title.strip().replace("/", "-")

        # -------------------------------------------------------------
        # 2. Build multipart payload
        # -------------------------------------------------------------
        metadata = {
            "name": safe_title,
            "mimeType": "application/vnd.google-apps.document",
        }

        notes_folder_id = self.prefs.get("notes_folder_id")
        if notes_folder_id:
            metadata["parents"] = [notes_folder_id]

        boundary = "-------314159265358979323846"

        multipart_body = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\n"
            "Content-Type: text/plain\r\n\r\n"
            f"{body}\r\n"
            f"--{boundary}--"
        ).encode("utf-8")

        headers_extra = {
            "Content-Type": f"multipart/related; boundary={boundary}"
        }

        # -------------------------------------------------------------
        # 3. Upload
        # -------------------------------------------------------------
        resp = await self.drive_request(
            "POST",
            "/files",
            headers_extra=headers_extra,
            data=multipart_body,
            upload=True,
        )

        if resp is None:
            await self.capability_worker.speak(
                "I couldn't reach Google Drive to save that note."
            )
            return

        if resp.status_code not in (200, 201):
            self._log_err(
                f"Quick Save failed: {resp.status_code} {resp.text[:200]}"
            )
            await self.capability_worker.speak(
                "Something went wrong while saving your note."
            )
            return

        await self.capability_worker.speak(
            f"Saved '{safe_title}' to your Drive."
        )

    # =========================================================================
    # What's New Mode (P1)
    # =========================================================================

    async def _run_whats_new(self):
        """
        List the 5 most recently modified non-folder files.

        - Excludes trashed files
        - Excludes folders
        - Orders by modifiedTime desc
        - Uses relative timestamps
        - Routes through handle_search_results() for natural voice formatting
        """

        await self.capability_worker.speak("I'm pulling up your most recently updated files.")

        resp = await self.drive_request(
            "GET",
            "/files",
            params={
                "q": (
                    "trashed = false and "
                    "mimeType != 'application/vnd.google-apps.folder'"
                ),
                "orderBy": "modifiedTime desc",
                "pageSize": 5,
                "fields": "files(id,name,mimeType,modifiedTime)",
            },
        )

        if resp is None:
            await self.capability_worker.speak(
                "I couldn't reach Google Drive right now."
            )
            return

        if resp.status_code != 200:
            self._log_err(
                f"What's New failed: {resp.status_code} {resp.text[:200]}"
            )
            await self.capability_worker.speak(
                "Something went wrong while checking your recent files."
            )
            return

        data = resp.json()
        files = data.get("files", [])

        if not files:
            await self.capability_worker.speak(
                "You don't have any recent files."
            )
            return

        # Route through LLM formatter for natural output + caching
        await self.handle_search_results(files, "recent files")

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

            # Use only most recent user message
            return user_messages[-1]

        except Exception as e:
            self._log_err(f"get_trigger_context error: {e}")
            return ""

    def classify_trigger_context(self, text: str) -> Dict[str, Any]:
        """
        Classify Google Drive voice command.

        Returns:
        {
          "mode": str,
          "search_query": str | None,
          "file_reference": str | None,
          "folder_name": str | None,
          "note_content": str | None,
          "file_type": str
        }

        file_type ∈ {"doc","sheet","slides","pdf","any"}
        """

        if not text or not text.strip():
            return {
                "mode": "name_search",
                "search_query": None,
                "file_reference": None,
                "folder_name": None,
                "note_content": None,
                "file_type": "any",
            }

        text = self._strip_activation_phrase(text)

        session_context = ""

        system_prompt = (
            "You classify voice commands for a Google Drive assistant.\n"
            "Return ONLY valid JSON. No markdown fences. No explanation.\n\n"
            "Schema:\n"
            "{\n"
            '  "mode": "name_search | content_search | whats_new | read_doc | quick_save | folder_browse | set_notes_folder | expand_doc",\n'
            '  "search_query": string or null,\n'
            '  "file_reference": string or null,\n'
            '  "folder_name": string or null,\n'
            '  "note_content": string or null,\n'
            '  "file_type": "doc | sheet | slides | pdf | any"\n'
            "}\n\n"
            "Rules:\n"
            "- If user wants to search for files by title, mode = name_search.\n"
            "- If user says search inside, search content, or refers to what's inside documents, mode = content_search.\n"
            "- If asking what's new or recent files, mode = whats_new.\n"
            "- If asking to read/open a file, mode = read_doc.\n"
            "- If asking to save a note, mode = quick_save.\n"
            "- If asking about folder contents, mode = folder_browse.\n"
            "- If asking to set or change the notes folder, mode = set_notes_folder.\n"
            "- If asking for more detail, to go deeper, or to expand on a document, mode = expand_doc.\n"
            "- Extract a clean search_query for searches.\n"
            "- Extract file_reference for read_doc.\n"
            "- Extract folder_name for folder browsing.\n"
            "- Extract note_content for quick saves.\n"
            "- Detect file_type from words like spreadsheet, sheet, slides, presentation, doc, document, pdf.\n"
            "- If no file type specified, use 'any'.\n"
            "- If unsure about mode, default to name_search.\n"
            + ("\n" + session_context if session_context else "")
        )

        try:
            raw_response = self.capability_worker.text_to_text_response(
                text,
                system_prompt=system_prompt,
            )

            if not raw_response:
                raise ValueError("Empty LLM response")

            cleaned = (
                raw_response.replace("```json", "")
                .replace("```", "")
                .strip()
            )

            parsed = json.loads(cleaned)

            if not isinstance(parsed, dict):
                raise ValueError("Parsed response is not a dict")

            allowed_modes = {
                "name_search",
                "content_search",
                "whats_new",
                "read_doc",
                "quick_save",
                "folder_browse",
                "set_notes_folder",
                "expand_doc",
            }

            allowed_types = {"doc", "sheet", "slides", "pdf", "any"}

            mode = parsed.get("mode", "name_search")
            if mode not in allowed_modes:
                mode = "name_search"

            file_type = parsed.get("file_type", "any")
            if file_type not in allowed_types:
                file_type = "any"

            def safe_str(val):
                return val if isinstance(val, str) and val.strip() else None

            return {
                "mode": mode,
                "search_query": safe_str(parsed.get("search_query")),
                "file_reference": safe_str(parsed.get("file_reference")),
                "folder_name": safe_str(parsed.get("folder_name")),
                "note_content": safe_str(parsed.get("note_content")),
                "file_type": file_type,
            }

        except Exception as e:
            self._log_err(f"Classification failed: {e}")
            return {
                "mode": "name_search",
                "search_query": None,
                "file_reference": None,
                "folder_name": None,
                "note_content": None,
                "file_type": "any",
            }

    def _strip_activation_phrase(self, text: str) -> str:
        if not text:
            return text

        lowered = text.lower()

        for hotword in self.matching_hotwords:
            hw = hotword.lower()
            if lowered.startswith(hw):
                # remove only first occurrence at start
                return text[len(hotword):].strip(" .,")

        return text
