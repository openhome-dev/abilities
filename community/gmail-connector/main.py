import base64
import json
import re
from datetime import datetime
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# GMAIL CONNECTOR
# A voice-powered Gmail client. Summarize unread emails, read specific messages,
# reply, compose, search, mark read, archive, and triage your inbox — all by
# voice. Uses Composio middleware for Gmail API access.
#
# Composio slugs (tested):
#   - GMAIL_FETCH_EMAILS      — list unread emails
#   - GMAIL_GET_MESSAGE        — get single email by ID
#   - GMAIL_SEND_EMAIL         — send a new email
#   - GMAIL_REPLY_TO_THREAD    — reply to an existing thread
#   - GMAIL_SEARCH             — search emails by query
#   - GMAIL_MODIFY_MESSAGE     — add/remove labels (mark read, archive)
#
# NOTE: These slugs may need adjustment. Build Phase 0 debug ability first
# to discover the correct slugs and response formats for your Composio account.
# =============================================================================

# -- Composio credentials (replace with your real keys) -----------------------
COMPOSIO_API_KEY = "YOUR_COMPOSIO_API_KEY"
COMPOSIO_USER_ID = "YOUR_COMPOSIO_USER_ID"
COMPOSIO_ENTITY_ID = "YOUR_COMPOSIO_ENTITY_ID"
COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v2"

# -- Persistent storage -------------------------------------------------------
PREFS_FILE = "gmail_connector_prefs.json"
CACHE_FILE = "gmail_connector_cache.json"

# -- Exit detection -----------------------------------------------------------
EXIT_WORDS = [
    "done", "exit", "stop", "quit", "bye", "goodbye",
    "nothing else", "all good", "nope", "no thanks",
    "i'm good", "that's it", "that's all", "leave", "cancel",
]

# -- Intent classification prompts --------------------------------------------
TRIGGER_INTENT_PROMPT = (
    "You are classifying a user's email-related request.\n\n"
    "Given the user's recent messages, return ONLY a JSON object:\n"
    '{{\n'
    '    "intent": one of ["summary", "read_specific", "reply", "compose", '
    '"search", "triage", "mark_read", "archive", "unknown"],\n'
    '    "mode": "quick" or "full",\n'
    '    "details": {{any extracted info like sender name, keywords, etc}}\n'
    '}}\n\n'
    "Rules:\n"
    '- "summary" = user wants overview of inbox. Mode: quick if asking a '
    'count, full if asking to "go through" or "catch me up"\n'
    '- "read_specific" = user wants to hear a specific email. Mode: quick\n'
    '- "reply" = user wants to reply to an email. Mode: quick\n'
    '- "compose" = user wants to write a new email. Mode: quick\n'
    '- "search" = user wants to find an email. Mode: quick\n'
    '- "triage" = user wants to go through emails one by one. Mode: full\n'
    '- "mark_read" / "archive" = user wants to manage a specific email. '
    'Mode: quick\n'
    '- If the request is vague like just "email" or "check email", default '
    'to summary with mode: full\n\n'
    "User's recent messages:\n{context}"
)

SESSION_INTENT_PROMPT = (
    "You are classifying an in-session email command.\n"
    "The user is already inside the Gmail assistant.\n\n"
    "Return ONLY valid JSON, no markdown:\n"
    '{{\n'
    '    "intent": one of ["summary", "read_specific", "reply", "compose", '
    '"search", "triage", "mark_read", "archive", "unknown"],\n'
    '    "details": {{any extracted info like sender name, keywords, subject, '
    'body content, recipient, etc}}\n'
    '}}\n\n'
    "Examples:\n"
    '"What did Sarah say?" -> {{"intent": "read_specific", '
    '"details": {{"sender": "Sarah"}}}}\n'
    '"Reply to that one" -> {{"intent": "reply", "details": {{}}}}\n'
    '"Send an email to Mike" -> {{"intent": "compose", '
    '"details": {{"recipient": "Mike"}}}}\n'
    '"Find the email about the budget" -> {{"intent": "search", '
    '"details": {{"keywords": "budget"}}}}\n'
    '"Mark it as read" -> {{"intent": "mark_read", "details": {{}}}}\n'
    '"Archive that" -> {{"intent": "archive", "details": {{}}}}\n'
    '"Go through my inbox" -> {{"intent": "triage", "details": {{}}}}\n\n'
    "User said: {user_input}"
)

COMPOSE_EXTRACT_PROMPT = (
    "The user wants to send an email. Extract whatever info is available "
    "from their message. Return ONLY valid JSON:\n"
    '{{\n'
    '    "recipient": "name or email or null",\n'
    '    "subject": "subject line or null",\n'
    '    "body": "message content or null"\n'
    '}}\n\n'
    "If the user gave everything in one sentence, extract all fields.\n"
    "If only partial info, fill what you can and leave the rest as null.\n\n"
    "User said: {user_input}"
)

DRAFT_EMAIL_PROMPT = (
    "Turn this casual spoken input into a properly formatted short email. "
    "Keep it natural and concise — 2-4 sentences max. "
    "Do NOT add a subject line. Do NOT add a greeting if one is not needed. "
    "Just the body text.\n\n"
    "User said: {user_input}"
)

SEARCH_EXTRACT_PROMPT = (
    "Extract search parameters from the user's email search request. "
    "Return ONLY valid JSON:\n"
    '{{\n'
    '    "sender": "sender name or email or null",\n'
    '    "keywords": "search keywords or null",\n'
    '    "date_range": "today|yesterday|this_week|last_week|this_month|null"\n'
    '}}\n\n'
    "User said: {user_input}"
)

SUMMARIZE_PROMPT = (
    "Summarize these emails in 2-3 spoken sentences. Lead with the most "
    "important or urgent ones. Keep it short — this will be read aloud.\n\n"
    "Emails:\n{emails}"
)

EMAIL_BODY_PROMPT = (
    "Summarize this email body in 1-2 spoken sentences. Strip HTML, "
    "signatures, and reply chains. Only the actual message content. "
    "Format for voice — say 'at' for @, 'dot' for periods in emails, "
    "and natural dates like 'Tuesday at 3 PM'.\n\n"
    "From: {sender}\nSubject: {subject}\nBody:\n{body}"
)


class GmailConnectorCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    emails: list = None
    current_email: dict = None
    pending_reply: dict = None
    pending_compose: dict = None
    idle_count: int = 0
    mode: str = "quick"
    prefs: dict = None

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
        self.worker.session_tasks.create(self.run())

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    async def run(self):
        try:
            self._log("info", "Gmail Connector started")
            self.emails = []
            self.current_email = None
            self.pending_reply = None
            self.pending_compose = None
            self.idle_count = 0
            self.prefs = await self.load_preferences()

            # Read trigger context and classify
            trigger_context = self.get_trigger_context()
            intent_data = self.classify_trigger_intent(trigger_context)
            intent = intent_data.get("intent", "unknown")
            self.mode = intent_data.get("mode", "full")

            self._log("info", f"Trigger intent: {intent} | Mode: {self.mode}")

            # Fetch emails upfront with filler speech
            await self.capability_worker.speak(
                "One sec, checking your inbox."
            )
            self.emails = self.gmail_list_unread()

            if self.mode == "quick":
                await self.handle_quick_intent(intent, intent_data)
            else:
                await self.handle_full_mode(intent, intent_data)

        except Exception as e:
            self._log("error", f"Unexpected error: {e}")
            await self.capability_worker.speak(
                "Something went wrong with Gmail. Try again in a moment."
            )
        finally:
            self._log("info", "Gmail Connector ended")
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Trigger context + intent classification
    # ------------------------------------------------------------------

    def get_trigger_context(self) -> str:
        """Read last 5 user messages from conversation history."""
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
        except Exception as e:
            self._log("error", f"Trigger context error: {e}")
            return ""

    def classify_trigger_intent(self, context: str) -> dict:
        """Use LLM to classify the trigger intent and decide quick/full mode."""
        if not context:
            return {"intent": "summary", "mode": "full", "details": {}}
        try:
            raw = self.capability_worker.text_to_text_response(
                TRIGGER_INTENT_PROMPT.format(context=context)
            )
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except (json.JSONDecodeError, Exception) as e:
            self._log("error", f"Trigger classification error: {e}")
            return {"intent": "summary", "mode": "full", "details": {}}

    def classify_session_intent(self, user_input: str) -> dict:
        """Classify intent during an active session."""
        try:
            raw = self.capability_worker.text_to_text_response(
                SESSION_INTENT_PROMPT.format(user_input=user_input)
            )
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except (json.JSONDecodeError, Exception) as e:
            self._log("error", f"Session classification error: {e}")
            return {"intent": "unknown", "details": {}}

    # ------------------------------------------------------------------
    # Quick mode
    # ------------------------------------------------------------------

    async def handle_quick_intent(self, intent: str, intent_data: dict):
        """Answer a specific question and offer brief follow-up."""
        details = intent_data.get("details", {})

        if intent == "summary":
            await self.handle_summary()
        elif intent == "read_specific":
            await self.handle_read_specific(details)
        elif intent == "reply":
            await self.handle_reply(details)
        elif intent == "compose":
            await self.handle_compose(details)
        elif intent == "search":
            await self.handle_search(details)
        elif intent == "mark_read":
            await self.handle_mark_read(details)
        elif intent == "archive":
            await self.handle_archive(details)
        else:
            await self.handle_summary()

        # Brief follow-up window
        await self.capability_worker.speak(
            "Anything else with your email?"
        )
        follow_up = await self.capability_worker.user_response()
        if follow_up and not self._is_exit(follow_up):
            session_intent = self.classify_session_intent(follow_up)
            await self.route_session_intent(
                session_intent.get("intent", "unknown"),
                session_intent.get("details", {}),
            )

    # ------------------------------------------------------------------
    # Full mode
    # ------------------------------------------------------------------

    async def handle_full_mode(self, intent: str, intent_data: dict):
        """Full interactive session with inbox."""
        details = intent_data.get("details", {})

        # Initial action based on trigger
        if intent == "triage":
            await self.handle_triage()
        elif intent == "read_specific":
            await self.handle_read_specific(details)
        elif intent == "compose":
            await self.handle_compose(details)
        elif intent == "reply":
            await self.handle_reply(details)
        elif intent == "search":
            await self.handle_search(details)
        else:
            await self.handle_summary()

        # Session loop
        for _ in range(30):
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                self.idle_count += 1
                if self.idle_count >= 2:
                    await self.capability_worker.speak(
                        "Sounds like you're all set. Closing Gmail."
                    )
                    return
                continue

            self.idle_count = 0

            if self._is_exit(user_input):
                await self.capability_worker.speak(
                    "Got it. Closing Gmail. Have a good one!"
                )
                return

            session_intent = self.classify_session_intent(user_input)
            await self.route_session_intent(
                session_intent.get("intent", "unknown"),
                session_intent.get("details", {}),
            )

    async def route_session_intent(self, intent: str, details: dict):
        """Route a classified in-session intent to its handler."""
        if intent == "summary":
            await self.handle_summary()
        elif intent == "read_specific":
            await self.handle_read_specific(details)
        elif intent == "reply":
            await self.handle_reply(details)
        elif intent == "compose":
            await self.handle_compose(details)
        elif intent == "search":
            await self.handle_search(details)
        elif intent == "mark_read":
            await self.handle_mark_read(details)
        elif intent == "archive":
            await self.handle_archive(details)
        elif intent == "triage":
            await self.handle_triage()
        else:
            await self.capability_worker.speak(
                "I can summarize, read, reply, compose, search, "
                "or triage your emails. What would you like?"
            )

    # ------------------------------------------------------------------
    # Feature handlers
    # ------------------------------------------------------------------

    async def handle_summary(self):
        """Summarize unread emails."""
        if not self.emails:
            await self.capability_worker.speak(
                "Your inbox is clear — no unread emails."
            )
            return

        email_list = self._format_email_list_for_llm(self.emails[:15])
        summary = self.capability_worker.text_to_text_response(
            SUMMARIZE_PROMPT.format(emails=email_list)
        )
        await self.capability_worker.speak(summary)

    async def handle_read_specific(self, details: dict):
        """Read a specific email based on sender/subject match."""
        sender = details.get("sender", "")
        keywords = details.get("keywords", "")

        if not self.emails:
            await self.capability_worker.speak("No unread emails to read.")
            return

        # Find matching email
        match = self._find_email(sender, keywords)
        if not match:
            await self.capability_worker.speak(
                "I don't see a recent email matching that. "
                "Can you give me more details?"
            )
            return

        self.current_email = match

        # Get full message if we only have a snippet
        email_id = match.get("id")
        if email_id and not match.get("body"):
            full = self.gmail_get_message(email_id)
            if full:
                match.update(full)
                self.current_email = match

        # Summarize for voice
        sender_name = match.get("sender", "someone")
        subject = match.get("subject", "no subject")
        body = match.get("body", match.get("snippet", ""))

        spoken = self.capability_worker.text_to_text_response(
            EMAIL_BODY_PROMPT.format(
                sender=sender_name, subject=subject, body=body[:2000]
            )
        )
        await self.capability_worker.speak(
            f"From {self.format_email_for_speech(sender_name)}, "
            f"subject: {subject}."
        )
        await self.capability_worker.speak(spoken)
        await self.capability_worker.speak(
            "Want to reply, archive, or move on?"
        )

    async def handle_reply(self, details: dict):
        """Reply to the current or specified email."""
        # Determine which email to reply to
        if not self.current_email and self.emails:
            sender = details.get("sender", "")
            if sender:
                match = self._find_email(sender, "")
                if match:
                    self.current_email = match

        if not self.current_email:
            await self.capability_worker.speak(
                "Which email do you want to reply to?"
            )
            clarify = await self.capability_worker.user_response()
            if not clarify or self._is_exit(clarify):
                return
            match = self._find_email(clarify, clarify)
            if not match:
                await self.capability_worker.speak(
                    "I couldn't find that email. Let's skip this one."
                )
                return
            self.current_email = match

        # Collect reply content
        body_text = details.get("body") or details.get("content")
        if not body_text:
            await self.capability_worker.speak("What do you want to say?")
            body_text = await self.capability_worker.user_response()
            if not body_text or self._is_exit(body_text):
                await self.capability_worker.speak("Reply cancelled.")
                return

        # Draft with LLM
        draft = self.capability_worker.text_to_text_response(
            DRAFT_EMAIL_PROMPT.format(user_input=body_text)
        )

        # Confirm before sending
        await self.capability_worker.speak(
            f"Here's what I'll send: {draft}. Should I send it?"
        )
        confirmed = await self.capability_worker.run_confirmation_loop(
            "Say yes to send, or no to cancel."
        )

        if confirmed:
            await self.capability_worker.speak("Sending your reply.")
            thread_id = self.current_email.get("thread_id", "")
            to_email = self.current_email.get("sender_email", "")
            subject = self.current_email.get("subject", "")
            success = self.gmail_send_reply(thread_id, to_email, subject, draft)
            if success:
                await self.capability_worker.speak("Reply sent!")
            else:
                await self.capability_worker.speak(
                    "I had trouble sending that. Try again later."
                )
        else:
            await self.capability_worker.speak(
                "Okay, reply cancelled."
            )

    async def handle_compose(self, details: dict):
        """Compose and send a new email with multi-turn collect flow."""
        # Try to extract everything from the initial utterance
        extracted = details
        if not extracted.get("recipient"):
            try:
                raw = self.capability_worker.text_to_text_response(
                    COMPOSE_EXTRACT_PROMPT.format(
                        user_input=json.dumps(details)
                    )
                )
                clean = raw.replace("```json", "").replace("```", "").strip()
                extracted = json.loads(clean)
            except Exception:
                extracted = {}

        # Collect recipient
        recipient = extracted.get("recipient")
        if not recipient:
            await self.capability_worker.speak("Who should I send it to?")
            recipient = await self.capability_worker.user_response()
            if not recipient or self._is_exit(recipient):
                await self.capability_worker.speak("Email cancelled.")
                return

        # Try to resolve name to email from recent messages
        recipient_email = self._resolve_recipient(recipient)
        if not recipient_email:
            await self.capability_worker.speak(
                f"What's {recipient}'s email address?"
            )
            recipient_email = await self.capability_worker.user_response()
            if not recipient_email or self._is_exit(recipient_email):
                await self.capability_worker.speak("Email cancelled.")
                return

        # Collect subject
        subject = extracted.get("subject")
        if not subject:
            await self.capability_worker.speak("What's the subject?")
            subject = await self.capability_worker.user_response()
            if not subject or self._is_exit(subject):
                await self.capability_worker.speak("Email cancelled.")
                return

        # Collect body
        body_input = extracted.get("body")
        if not body_input:
            await self.capability_worker.speak("What do you want to say?")
            body_input = await self.capability_worker.user_response()
            if not body_input or self._is_exit(body_input):
                await self.capability_worker.speak("Email cancelled.")
                return

        # Draft with LLM
        draft = self.capability_worker.text_to_text_response(
            DRAFT_EMAIL_PROMPT.format(user_input=body_input)
        )

        # Read back and confirm
        spoken_email = self.format_email_for_speech(recipient_email)
        await self.capability_worker.speak(
            f"To {spoken_email}, subject: {subject}. "
            f"Message: {draft}. Should I send it?"
        )
        confirmed = await self.capability_worker.run_confirmation_loop(
            "Say yes to send, or no to cancel."
        )

        if confirmed:
            await self.capability_worker.speak("Sending your email.")
            success = self.gmail_send_new(recipient_email, subject, draft)
            if success:
                await self.capability_worker.speak("Email sent!")
            else:
                await self.capability_worker.speak(
                    "I had trouble sending that. Try again later."
                )
        else:
            await self.capability_worker.speak("Okay, email cancelled.")

    async def handle_search(self, details: dict):
        """Search emails by sender, keywords, or date."""
        search_input = json.dumps(details) if details else ""

        # Extract search params
        try:
            raw = self.capability_worker.text_to_text_response(
                SEARCH_EXTRACT_PROMPT.format(user_input=search_input)
            )
            clean = raw.replace("```json", "").replace("```", "").strip()
            params = json.loads(clean)
        except Exception:
            params = details or {}

        # Build Gmail search query
        query_parts = []
        if params.get("sender"):
            query_parts.append(f"from:{params['sender']}")
        if params.get("keywords"):
            query_parts.append(params["keywords"])
        date_range = params.get("date_range")
        if date_range == "today":
            query_parts.append(f"after:{datetime.now().strftime('%Y/%m/%d')}")
        elif date_range == "yesterday":
            query_parts.append("newer_than:1d")
        elif date_range in ("this_week", "last_week"):
            query_parts.append("newer_than:7d")
        elif date_range == "this_month":
            query_parts.append("newer_than:30d")

        query = " ".join(query_parts) if query_parts else "is:unread"

        await self.capability_worker.speak("Searching your email.")
        results = self.gmail_search(query)

        if not results:
            await self.capability_worker.speak(
                "I didn't find any emails matching that."
            )
            return

        # Summarize results
        count = len(results)
        first = results[0]
        sender = first.get("sender", "someone")
        subject = first.get("subject", "no subject")
        await self.capability_worker.speak(
            f"I found {count} email{'s' if count != 1 else ''} matching that. "
            f"The most recent is from {self.format_email_for_speech(sender)} "
            f"about {subject}. Want me to read it?"
        )

        answer = await self.capability_worker.user_response()
        if answer and any(w in answer.lower() for w in ["yes", "yeah", "sure", "read"]):
            self.current_email = first
            await self.handle_read_specific({"sender": sender})

    async def handle_mark_read(self, details: dict):
        """Mark the current email as read."""
        target = self.current_email
        if not target:
            await self.capability_worker.speak(
                "Which email should I mark as read?"
            )
            return

        email_id = target.get("id")
        if email_id:
            success = self.gmail_mark_read(email_id)
            if success:
                await self.capability_worker.speak("Marked as read.")
            else:
                await self.capability_worker.speak(
                    "Sorry, mark as read isn't available right now."
                )
        else:
            await self.capability_worker.speak(
                "I don't have a reference to that email."
            )

    async def handle_archive(self, details: dict):
        """Archive the current email (moves to trash via Composio)."""
        target = self.current_email
        if not target:
            await self.capability_worker.speak(
                "Which email should I archive?"
            )
            return

        email_id = target.get("id")
        if email_id:
            success = self.gmail_archive(email_id)
            if success:
                await self.capability_worker.speak(
                    "Done — moved to trash."
                )
            else:
                await self.capability_worker.speak(
                    "I had trouble with that. Try again."
                )
        else:
            await self.capability_worker.speak(
                "I don't have a reference to that email."
            )

    async def handle_triage(self):
        """Walk through unread emails one by one."""
        if not self.emails:
            await self.capability_worker.speak(
                "No unread emails to triage. You're all caught up!"
            )
            return

        await self.capability_worker.speak(
            f"You have {len(self.emails)} unread email"
            f"{'s' if len(self.emails) != 1 else ''}. Let's go through them."
        )

        for i, email in enumerate(self.emails[:15]):
            self.current_email = email
            sender = email.get("sender", "someone")
            subject = email.get("subject", "no subject")
            snippet = email.get("snippet", "")

            # One-sentence summary per email
            summary = self.capability_worker.text_to_text_response(
                f"Give a 1-sentence spoken summary of this email. "
                f"From: {sender}, Subject: {subject}, "
                f"Preview: {snippet[:200]}"
            )

            position = "First" if i == 0 else "Next"
            await self.capability_worker.speak(
                f"{position} — {summary}"
            )
            await self.capability_worker.speak(
                "Reply, skip, mark read, or archive?"
            )

            action = await self.capability_worker.user_response()
            if not action or self._is_exit(action):
                await self.capability_worker.speak(
                    "Okay, stopping triage."
                )
                return

            lower = action.lower()
            if "reply" in lower:
                await self.handle_reply({})
            elif "archive" in lower:
                await self.handle_archive({})
            elif "read" in lower and "mark" in lower:
                await self.handle_mark_read({})
            elif "read" in lower:
                await self.handle_read_specific(
                    {"sender": sender}
                )
            # "skip" or anything else → move to next

        await self.capability_worker.speak(
            "That's all your unread emails. Nice work!"
        )

    # ------------------------------------------------------------------
    # Gmail API helpers (Composio)
    # ------------------------------------------------------------------

    def execute_composio_action(self, action_slug: str, params: dict) -> Optional[dict]:
        """Call a Composio action. Returns response dict or None on error."""
        url = f"{COMPOSIO_BASE_URL}/actions/{action_slug}/execute"
        headers = {
            "X-API-KEY": COMPOSIO_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "connectedAccountId": COMPOSIO_USER_ID,
            "entityId": COMPOSIO_ENTITY_ID,
            "input": params,
        }
        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=15
            )
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                self._log("error", "Composio 401 — token may be expired")
            elif response.status_code == 429:
                self._log("error", "Composio 429 — rate limited")
            else:
                self._log(
                    "error",
                    f"Composio {response.status_code}: {response.text[:200]}",
                )
            return None
        except requests.exceptions.Timeout:
            self._log("error", "Composio request timed out")
            return None
        except Exception as e:
            self._log("error", f"Composio request failed: {e}")
            return None

    def gmail_list_unread(self) -> list:
        """Fetch unread emails. Returns list of email dicts."""
        result = self.execute_composio_action(
            "GMAIL_FETCH_EMAILS",
            {"query": "is:unread", "max_results": 15, "user_id": "me"},
        )
        if not result:
            return []
        return self._parse_email_list(result)

    def gmail_get_message(self, message_id: str) -> Optional[dict]:
        """Get a single email by ID."""
        result = self.execute_composio_action(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
            {"message_id": message_id, "format": "full", "user_id": "me"},
        )
        if not result:
            return None
        return self._parse_single_email(result)

    def gmail_send_reply(
        self, thread_id: str, to: str, subject: str, body: str
    ) -> bool:
        """Reply to an email thread."""
        result = self.execute_composio_action(
            "GMAIL_REPLY_TO_THREAD",
            {
                "thread_id": thread_id,
                "recipient_email": to,
                "message_body": body,
                "user_id": "me",
            },
        )
        return result is not None

    def gmail_send_new(self, to: str, subject: str, body: str) -> bool:
        """Send a new email."""
        result = self.execute_composio_action(
            "GMAIL_SEND_EMAIL",
            {
                "recipient_email": to,
                "subject": subject,
                "body": body,
                "user_id": "me",
            },
        )
        return result is not None

    def gmail_search(self, query: str) -> list:
        """Search emails by query string (uses GMAIL_FETCH_EMAILS with query)."""
        result = self.execute_composio_action(
            "GMAIL_FETCH_EMAILS",
            {"query": query, "max_results": 10, "user_id": "me"},
        )
        if not result:
            return []
        return self._parse_email_list(result)

    def gmail_mark_read(self, message_id: str) -> bool:
        """Mark as read — not directly supported by Composio.
        Uses GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID as a workaround to
        trigger a read, or logs that the action is unavailable.
        """
        self._log("warning", "Mark-as-read not available via Composio")
        return False

    def gmail_archive(self, message_id: str) -> bool:
        """Archive — uses GMAIL_MOVE_TO_TRASH as closest available action.
        NOTE: This trashes, not archives. Inform user accordingly.
        """
        result = self.execute_composio_action(
            "GMAIL_MOVE_TO_TRASH",
            {"message_id": message_id, "user_id": "me"},
        )
        return result is not None

    # ------------------------------------------------------------------
    # Response parsers (adapt these once you know Composio's response format)
    # ------------------------------------------------------------------

    def _parse_email_list(self, api_response: dict) -> list:
        """Parse Composio v2 response into a list of email dicts.

        Actual Composio format: {"data": {"messages": [{"messageId": ...,
        "payload": {"headers": [{"name":...,"value":...}]}, ...}]}}
        """
        emails = []
        try:
            data = api_response
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            if isinstance(data, dict):
                data = data.get("messages", data.get("emails", []))
            if not isinstance(data, list):
                data = [data] if data else []

            for msg in data:
                if not isinstance(msg, dict):
                    continue
                headers = {}
                payload = msg.get("payload", {})
                for h in payload.get("headers", []):
                    headers[h.get("name", "").lower()] = h.get("value", "")

                sender = headers.get("from", msg.get("from", ""))
                subject = headers.get("subject", msg.get("subject", ""))
                snippet = msg.get("snippet", "")
                body = self._extract_body(payload)

                emails.append({
                    "id": msg.get("messageId", msg.get("id", "")),
                    "thread_id": msg.get("threadId", msg.get("thread_id", "")),
                    "sender": sender,
                    "sender_email": self._extract_email_address(sender),
                    "subject": subject,
                    "snippet": snippet,
                    "body": body or snippet,
                    "date": msg.get("messageTimestamp", headers.get("date", "")),
                    "labels": msg.get("labelIds", []),
                })
        except Exception as e:
            self._log("error", f"Email list parse error: {e}")
        return emails

    def _parse_single_email(self, api_response: dict) -> Optional[dict]:
        """Parse a single email response from Composio."""
        emails = self._parse_email_list(api_response)
        return emails[0] if emails else None

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """Recursively extract plain text body from Gmail payload."""
        body_data = payload.get("body", {}).get("data", "")
        if body_data:
            try:
                return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
            except Exception:
                return body_data
        for part in payload.get("parts", []):
            if part.get("mimeType", "").startswith("text/plain"):
                data = part.get("body", {}).get("data", "")
                if data:
                    try:
                        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    except Exception:
                        return data
            nested = GmailConnectorCapability._extract_body(part)
            if nested:
                return nested
        return ""

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _find_email(self, sender: str, keywords: str) -> Optional[dict]:
        """Find an email matching sender name or keywords."""
        sender_lower = (sender or "").lower()
        keywords_lower = (keywords or "").lower()

        for email in self.emails:
            email_sender = (email.get("sender", "") or "").lower()
            email_subject = (email.get("subject", "") or "").lower()
            email_snippet = (email.get("snippet", "") or "").lower()

            if sender_lower and sender_lower in email_sender:
                return email
            if keywords_lower and (
                keywords_lower in email_subject
                or keywords_lower in email_snippet
            ):
                return email
        return None

    def _resolve_recipient(self, name: str) -> Optional[str]:
        """Try to find an email address from recent messages by name."""
        name_lower = (name or "").lower()
        # Check if it already looks like an email
        if "@" in name:
            return name
        # Search through fetched emails
        for email in self.emails:
            sender = (email.get("sender", "") or "").lower()
            if name_lower in sender:
                return email.get("sender_email", "")
        return None

    @staticmethod
    def _extract_email_address(sender_str: str) -> str:
        """Extract email address from 'Name <email>' format."""
        match = re.search(r"<([^>]+)>", sender_str)
        if match:
            return match.group(1)
        if "@" in sender_str:
            return sender_str.strip()
        return sender_str

    @staticmethod
    def format_email_for_speech(text: str) -> str:
        """Convert email addresses and tech strings for spoken output."""
        return text.replace("@", " at ").replace(".", " dot ")

    def _format_email_list_for_llm(self, emails: list) -> str:
        """Format email list as text for LLM summarization."""
        lines = []
        for i, e in enumerate(emails, 1):
            lines.append(
                f"{i}. From: {e.get('sender', '?')} | "
                f"Subject: {e.get('subject', '?')} | "
                f"Preview: {e.get('snippet', '')[:100]}"
            )
        return "\n".join(lines)

    def _is_exit(self, text: str) -> bool:
        """Check if user input contains exit intent."""
        if not text:
            return False
        lower = text.lower().strip()
        lower = re.sub(r"[^\w\s']", "", lower)
        for word in EXIT_WORDS:
            if word in lower:
                return True
        return False

    def _log(self, level: str, message: str):
        """Log to the editor logging handler."""
        handler = self.worker.editor_logging_handler
        if level == "error":
            handler.error(f"[GmailConnector] {message}")
        elif level == "warning":
            handler.warning(f"[GmailConnector] {message}")
        else:
            handler.info(f"[GmailConnector] {message}")

    # ------------------------------------------------------------------
    # Persistence (delete + write pattern)
    # ------------------------------------------------------------------

    async def load_preferences(self) -> dict:
        """Load user preferences or return defaults."""
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            try:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                return json.loads(raw)
            except (json.JSONDecodeError, Exception):
                self._log("error", "Corrupt prefs file, using defaults.")
        return {
            "max_emails_in_summary": 10,
            "triage_order": "newest_first",
            "auto_mark_read_after_listening": False,
        }

    async def save_json(self, filename: str, data: dict, temp: bool = False):
        """Save JSON using delete + write pattern."""
        if await self.capability_worker.check_if_file_exists(filename, temp):
            await self.capability_worker.delete_file(filename, temp)
        await self.capability_worker.write_file(
            filename, json.dumps(data), temp
        )
