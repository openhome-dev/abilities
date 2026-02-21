import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CONFIG (in production use environment variables or secrets)
# =============================================================================

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

CLIENT_ID = "YOUR_CLIENT_ID"
TENANT_ID = "consumers"
REFRESH_TOKEN = "YOUR_REFRESH_TOKEN"

EXIT_WORDS = [
    "done",
    "exit",
    "stop",
    "quit",
    "bye",
    "goodbye",
    "nothing else",
    "all good",
    "nope",
    "no thanks",
    "i'm good",
    "im good",
    "that's it",
    "thats it",
    "that's all",
    "thats all",
    "go to sleep",
]

CONFIRM_YES_PHRASES = [
    "yes",
    "yeah",
    "yep",
    "sure",
    "okay",
    "ok",
    "correct",
    "right",
    "do it",
    "go ahead",
    "sounds good",
    "that's right",
    "thats right",
    "please",
    "read it",
    "send it",
    "read the full",
    "hear it",
]

CONFIRM_NO_PHRASES = [
    "no",
    "nope",
    "never mind",
    "nevermind",
    "cancel",
    "forget it",
    "don't",
    "dont",
    "skip",
    "not now",
    "pass",
    "next",
]

MAX_UNREAD_FETCH = 15
MAX_SUMMARY_INPUT = 15
MAX_SEARCH_RESULTS = 5
MAX_TRIAGE_BATCH = 10

PREFS_FILE = "outlook_connector_prefs.json"
CACHE_FILE = "outlook_connector_cache.json"

# Static message for all API/connection errors
OUTLOOK_ERROR_SPEAK = (
    "I'm having trouble connecting to Outlook right now. Try again in a minute."
)

# =============================================================================
# LLM PROMPTS
# =============================================================================

TRIGGER_INTENT_PROMPT = (
    "You are the Outlook Connector, a voice-only assistant that manages the "
    "user's Outlook / Microsoft 365 email.\n"
    "You are classifying the user's email-related request.\n\n"
    "Given the user's recent messages, return ONLY a JSON object:\n"
    "{{\n"
    '  "intent": one of ["summary", "read_specific", "reply", "compose", '
    '"search", "triage", "mark_read", "archive", "unknown"],\n'
    '  "mode": "quick" or "full",\n'
    '  "details": {{\n'
    '    "sender_name": null,\n'
    '    "subject_keywords": null,\n'
    '    "recipient": null,\n'
    '    "body_content": null,\n'
    '    "date_range": null,\n'
    '    "email_address": null,\n'
    '    "count_only": false\n'
    "  }}\n"
    "}}\n\n"
    "Rules:\n"
    '- "summary" = user wants overview of inbox. Mode: quick if asking a count, '
    'full if asking to "go through" or "catch me up". When the user asks ONLY '
    'for the number of unread emails (e.g. "how many unread", "do I have any '
    'new email"), set details.count_only to true and mode to quick.\n'
    '- "read_specific" = user wants to hear a specific email. Mode: quick. '
    'IMPORTANT: Questions like "did [Name] message me", "did [Name] email me", '
    '"did Cursor message me", "any email from [Name]" are read_specific — set '
    'sender_name to the name or company (e.g. "Cursor", "Cursor Team", "Sarah") '
    "so we can match from the inbox list by display name.\n"
    '- "reply" = user wants to reply to an email. Mode: quick\n'
    '- "compose" = user wants to write a new email. Mode: quick\n'
    '- "search" = user wants to find an email (e.g. by keyword or date). Use '
    'for "find emails about X" or "emails from last week". For "did [Name] '
    'message me" use read_specific instead. Mode: quick\n'
    '- "triage" = user wants to go through emails one by one. Mode: full\n'
    '- "mark_read" / "archive" = user wants to manage a specific email. '
    "Mode: quick\n"
    '- If the request is vague like just "email" or "check email", default to '
    "summary with mode: full\n\n"
    "Examples:\n"
    '"What did Sarah say?" -> {{"intent": "read_specific", "details": '
    '{{"sender_name": "Sarah"}}}}\n'
    '"Reply to that one" -> {{"intent": "reply", "details": {{}}}}\n'
    '"Send an email to Mike" -> {{"intent": "compose", "details": '
    '{{"recipient": "Mike"}}}}\n'
    '"Email Mike about the API spec and tell him I\'ll have it Friday" -> '
    '{{"intent": "compose", "details": {{"recipient": "Mike", '
    '"subject_keywords": "API spec", "body_content": "tell him I\'ll have it '
    'Friday"}}}}\n'
    '"Find the email about the budget" -> {{"intent": "search", "details": '
    '{{"subject_keywords": "budget"}}}}\n'
    '"Mark it as read" -> {{"intent": "mark_read", "details": {{}}}}\n'
    '"Archive that" -> {{"intent": "archive", "details": {{}}}}\n'
    '"Go through my inbox" -> {{"intent": "triage", "details": {{}}}}\n\n'
    "User's recent messages:\n"
    "{trigger_context}\n"
)

COMPOSE_EXTRACT_PROMPT = (
    "You are the Outlook Connector. The user wants to send an email. Extract "
    "whatever info is available from their message. Return ONLY valid JSON, "
    "no markdown:\n"
    "{{\n"
    '  "recipient": "name or email or null",\n'
    '  "subject": "subject line or null",\n'
    '  "body": "message content or null"\n'
    "}}\n"
    "If the user gave everything in one sentence, extract all three fields. "
    "If only partial info, fill what you can and leave the rest as null.\n\n"
    "User said or context:\n"
    "{user_input}\n"
)

SEARCH_EXTRACT_PROMPT = (
    "You are the Outlook Connector. Extract search parameters from the user's "
    "email search request. Return ONLY valid JSON, no markdown:\n"
    "{{\n"
    '  "sender": "sender name or email address or null",\n'
    '  "keywords": "search keywords for subject or body or null",\n'
    '  "date_range": "today|yesterday|this week|last week|last month|null"\n'
    "}}\n"
    "Use date_range only if the user mentioned a time range. Examples: "
    '"this week" -> "this week", "last month" -> "last month", '
    '"yesterday" -> "yesterday", "today" -> "today".\n\n'
    "User said:\n"
    "{user_input}\n"
)

TRIAGE_SUMMARY_PROMPT = (
    "You are the Outlook Connector. Give a 1-sentence spoken summary of this "
    "email for triage. Lead with who and what; mention the main point if clear "
    "from the preview. Keep it short and natural for voice.\n\n"
    "From: {from_name}\n"
    "Subject: {subject}\n"
    "Preview: {preview}\n"
)

SUMMARY_PROMPT = (
    "You are the Outlook Connector, a voice-only assistant that manages the "
    "user's Outlook / Microsoft 365 email.\n\n"
    "Summarize these emails in 2-3 spoken sentences. Lead with the most "
    "important or urgent ones. Keep it short.\n"
    "Do NOT read every email. Summarize. The user can ask for details on "
    "specific ones.\n"
    "Do NOT end with a question or offer — just the summary.\n\n"
    "Example voice output:\n"
    '"You have 7 unread emails. Two look important — Sarah sent the Q3 deck '
    "and flagged two issues, and Mike is asking about the API spec. The rest "
    'are newsletters and notifications."\n\n'
    "Emails:\n"
    "{emails}\n"
)

EMAIL_SUMMARY_PROMPT = (
    "You are the Outlook Connector, a voice-only assistant that manages the "
    "user's Outlook / Microsoft 365 email.\n"
    "Summarize this email body in 1-2 spoken sentences. Only the actual "
    "message content — ignore signatures, reply chains, and disclaimers.\n"
    "Format for voice — say 'at' for @, 'dot' for periods in emails, and "
    "natural dates like 'Tuesday at 3 PM'. Say 'there's a link' instead of "
    "reading URLs.\n\n"
    "From: {sender}\n"
    "Subject: {subject}\n"
    "Body:\n"
    "{body}\n"
)

DRAFT_REPLY_PROMPT = (
    "You are the Outlook Connector, a voice-only assistant that manages the "
    "user's Outlook / Microsoft 365 email.\n"
    "Rewrite this into a complete, sendable email reply. The user is replying "
    "to: {replying_to}.\n\n"
    "User said:\n"
    '"{user_input}"\n\n'
    "Rules:\n"
    "- Write the FULL reply body. Use the recipient's name in the greeting "
    '(e.g. "Hi Sarah,") since you know who they are.\n'
    '- Use a simple sign-off like "Thanks," or "Best," only — never use '
    "placeholders like [Your Name], [My Name], [Recipient's Name], [Name], "
    "or [Anything in brackets].\n"
    "- Keep it concise and natural. Output only the email body text, ready "
    "to send.\n"
)

DRAFT_COMPOSE_PROMPT = (
    "You are the Outlook Connector, a voice-only assistant that composes and "
    "manages the user's Outlook / Microsoft 365 email.\n"
    "Turn this spoken request into a clean email that sounds natural when "
    "read aloud.\n\n"
    "If the user says something casual like:\n"
    '- "tell him yeah I\'ll get it done by Friday no worries"\n\n'
    "You should turn it into something like:\n"
    "- \"Hi Mike, I'll have the API spec ready by Friday. Let me know if you "
    'need anything before then."\n\n'
    "Turn this spoken request into a complete, sendable email body. Use the "
    "actual recipient and subject below.\n\n"
    "Recipient: {recipient}\n"
    "Subject: {subject}\n\n"
    "User said:\n"
    '"{body}"\n\n'
    "Rules:\n"
    "- Write the FULL email body. Use the recipient's name in the greeting "
    '(e.g. "Hi Mike,").\n'
    '- Use a simple sign-off like "Thanks," or "Best," only — never use '
    "placeholders like [Your Name], [My Name], [Recipient's Name], [Name], "
    "or [Anything in brackets].\n"
    "- Output only the email body text, ready to send. No placeholders.\n"
)

# =============================================================================
# MAIN CLASS
# =============================================================================


class OutlookConnectorCapability(MatchingCapability):

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Session state
    emails: List[Dict] = []
    current_email: Optional[Dict] = None
    history: List = []
    pending_reply: Optional[Dict] = None
    pending_compose: Optional[Dict] = None
    archive_folder_id: Optional[str] = None
    mode: str = "quick"
    idle_count: int = 0
    prefs: Dict = {}
    in_triage: bool = False
    triage_index: int = 0
    _just_gave_summary: bool = False  # "yes" after summary → start triage
    _triage_just_sent_reply: bool = (
        False  # after "Sent." in triage, advance to next email
    )
    _just_finished_read: bool = (
        False  # after "Want to reply, archive, or read?" → same reply/archive/read handlers
    )

    # =========================================================================
    # REGISTRATION
    # =========================================================================

    #{{register capability}}

    # =========================================================================
    # ENTRY POINT
    # =========================================================================

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.reset_session_state()
        self.worker.session_tasks.create(self.run())

    def reset_session_state(self):
        self.emails = []
        self.current_email = None
        self.history = []
        self.pending_reply = None
        self.pending_compose = None
        self.archive_folder_id = None
        self.mode = "quick"
        self.idle_count = 0
        self.in_triage = False
        self.triage_index = 0
        self._just_gave_summary = False
        self._triage_just_sent_reply = False
        self._just_finished_read = False

    def log(self, msg):
        self.worker.editor_logging_handler.info(f"[Outlook] {msg}")

    def log_err(self, msg):
        self.worker.editor_logging_handler.error(f"[Outlook] {msg}")

    # =========================================================================
    # MAIN RUN
    # =========================================================================

    async def run(self):
        try:
            await self.capability_worker.speak("One sec, checking your inbox.")

            initial_history_len = 0
            try:
                history = self.worker.agent_memory.full_message_history
                initial_history_len = len(history) if history else 0
            except Exception:
                pass

            self.prefs = await self.load_preferences()
            try:
                self.emails, err = self.outlook_list_unread(MAX_UNREAD_FETCH)
                if err:
                    self.log_err(f"Outlook fetch failed: {err}")
                    await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                    self.capability_worker.resume_normal_flow()
                    return
            except Exception as e:
                self.log_err(f"Outlook fetch failed: {e}")
                await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                self.capability_worker.resume_normal_flow()
                return

            await self.save_json(CACHE_FILE, {"emails": self.emails}, temp=True)

            trigger_context = None
            for _ in range(6):
                await self.worker.session_tasks.sleep(0.5)
                try:
                    current = self.worker.agent_memory.full_message_history
                    current_len = len(current) if current else 0
                    if current_len > initial_history_len:
                        trigger_context = self.get_trigger_context()
                        break
                except Exception:
                    pass
            if trigger_context is None:
                trigger_context = self.get_trigger_context()

            intent_data = self.classify_trigger_intent(trigger_context)
            self.mode = intent_data.get("mode", "quick")

            if self.mode == "quick":
                await self.handle_quick_intent(intent_data)
                if self._just_finished_read:
                    await self._quick_after_read_then_exit()
                else:
                    await self.capability_worker.speak(
                        "Let me know if you need anything else about your email."
                    )
                    await self.brief_follow_up_window()
                return

            if self.mode == "full":
                await self.handle_full_mode(intent_data)
                await self.session_loop()
                return

        except Exception as e:
            self.log_err(str(e))
            await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
            self.capability_worker.resume_normal_flow()
        finally:
            self.capability_worker.resume_normal_flow()

    def fetch_emails(self):
        """Get unread emails from Microsoft Graph API.
        Sets self.emails; returns (True, None) or (False, error_message)."""
        self.emails, err = self.outlook_list_unread(MAX_UNREAD_FETCH)
        return (err is None, err)

    # =========================================================================
    # TRIGGER CONTEXT
    # =========================================================================

    def get_trigger_context(self):
        recent: List[str] = []
        trigger = ""

        try:
            history = self.worker.agent_memory.full_message_history
            for msg in reversed(history):
                if hasattr(msg, "role") and "user" in str(msg.role).lower():
                    content = str(msg.content).strip()
                    if not content:
                        continue
                    recent.append(content)
                    if not trigger:
                        trigger = content
                    if len(recent) >= 5:
                        break
        except Exception:
            pass

        recent_text = "\n".join(reversed(recent)) if recent else trigger
        return {"trigger": trigger, "trigger_context": recent_text}

    def classify_trigger_intent(self, trigger_context: dict) -> Dict:
        """Classify trigger intent and mode from context."""
        raw_trigger = trigger_context.get("trigger", "")
        raw_recent = trigger_context.get("trigger_context", raw_trigger)
        trigger = (
            " ".join(str(x) for x in raw_trigger)
            if isinstance(raw_trigger, list)
            else str(raw_trigger or "")
        )
        recent_text = (
            " ".join(str(x) for x in raw_recent)
            if isinstance(raw_recent, list)
            else str(raw_recent or "")
        )

        if not trigger.strip():
            return {"intent": "summary", "mode": "full", "details": {}}

        # Vague triggers ("email", "inbox", etc.) → summary, full mode
        lower_stripped = trigger.strip().lower().rstrip(".!?")
        if lower_stripped in ("outlook", "email", "emails", "inbox"):
            return {"intent": "summary", "mode": "full", "details": {}}

        full_triggers = [
            "check my email",
            "triage",
            "go through my email",
            "go through my emails",
            "go through my inbox",
            "catch me up on email",
            "read me my emails",
        ]
        if any(ft in trigger.lower() for ft in full_triggers):
            lower = trigger.lower()
            # Triage = walk through one by one (brief: "let's go through my inbox", "triage my email")
            is_triage = "triage" in lower or "go through" in lower
            return {
                "intent": "triage" if is_triage else "summary",
                "mode": "full",
                "details": {},
            }

        prompt = TRIGGER_INTENT_PROMPT.format(trigger_context=recent_text)
        default = {"intent": "summary", "mode": "quick", "details": {}}

        try:
            response = self.capability_worker.text_to_text_response(prompt)
            clean = (response or "").replace("```json", "").replace("```", "").strip()
            start, end = clean.find("{"), clean.rfind("}")
            if start != -1 and end > start:
                clean = clean[start : end + 1]
            result = json.loads(clean)
            if isinstance(result, dict):
                return result
        except Exception as e:
            self.log_err(f"Trigger classification error: {e}")

        lower = (trigger or "").lower()
        if "how many" in lower and (
            "unread" in lower or "email" in lower or "mail" in lower
        ):
            return {
                "intent": "summary",
                "mode": "quick",
                "details": {"count_only": True},
            }
        if "do i have" in lower and ("email" in lower or "mail" in lower):
            return {
                "intent": "summary",
                "mode": "quick",
                "details": {"count_only": True},
            }
        if "any new" in lower and ("email" in lower or "mail" in lower):
            return {
                "intent": "summary",
                "mode": "quick",
                "details": {"count_only": True},
            }
        if any(w in lower for w in ["send", "write", "compose", "email to"]):
            return {"intent": "compose", "mode": "quick", "details": {}}
        if any(w in lower for w in ["reply", "respond"]):
            return {"intent": "reply", "mode": "quick", "details": {}}
        if any(w in lower for w in ["archive"]):
            return {"intent": "archive", "mode": "quick", "details": {}}
        if any(w in lower for w in ["search", "find"]):
            return {"intent": "search", "mode": "quick", "details": {}}
        return default

    # =========================================================================
    # QUICK MODE
    # =========================================================================

    async def handle_quick_intent(self, intent_data: Dict):
        intent = intent_data.get("intent", "summary")
        await self.route_intent(intent, intent_data.get("details", {}))

    async def _quick_after_read_then_exit(self):
        """After read in quick mode: handle one reply/archive/read (same handlers), then say Done and exit."""
        while True:
            user = await self.user_response_with_timeout(15)
            if not user:
                await self.capability_worker.speak("Done.")
                return
            if any(word in user.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak("Done.")
                return

            if self.pending_reply:
                await self.handle_pending_reply(user)
                if not self.pending_reply:
                    await self.capability_worker.speak("Done.")
                    return
                continue

            if self._just_finished_read:
                self._just_finished_read = False
                lowered = user.lower()
                if "reply" in lowered:
                    reply_body = self._extract_reply_body_from_triage_action(user)
                    if reply_body:
                        self.pending_reply = {
                            "email_id": self.current_email["id"],
                            "waiting_for": "body",
                            "draft": None,
                        }
                        await self.handle_pending_reply(reply_body)
                    else:
                        await self.start_reply({})
                    if not self.pending_reply:
                        await self.capability_worker.speak("Done.")
                        return
                    continue
                if "archive" in lowered:
                    await self.handle_archive()
                    await self.capability_worker.speak("Done.")
                    return
                if "read" in lowered:
                    await self._read_full_current_email()
                    await self.capability_worker.speak("Done.")
                    return
                # unexpected: treat as done and exit
                await self.capability_worker.speak("Done.")
                return

            await self.capability_worker.speak("Done.")
            return

    async def brief_follow_up_window(self):
        user = await self.user_response_with_timeout(5)
        if user:
            intent_data = self.classify_trigger_intent(
                {"trigger": user, "trigger_context": user}
            )
            await self.route_intent(
                intent_data["intent"], intent_data.get("details", {})
            )
        self.capability_worker.resume_normal_flow()

    # =========================================================================
    # FULL MODE
    # =========================================================================

    async def handle_full_mode(self, intent_data: Dict):
        intent = intent_data.get("intent", "summary")
        await self.route_intent(intent, intent_data.get("details", {}))

    async def session_loop(self):
        while True:
            user = await self.user_response_with_timeout(15)

            if not user:
                self.idle_count += 1
                if self.idle_count >= 2:
                    await self.capability_worker.speak("Alright, closing your inbox.")
                    self.capability_worker.resume_normal_flow()
                    return
                continue

            self.idle_count = 0

            if any(word in user.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak("Done.")
                self.capability_worker.resume_normal_flow()
                return

            # After "Want me to go through them?" — only start triage on clear yes; no/cancel or trigger-like = don't
            if self._just_gave_summary:
                if self._is_confirm_no_or_cancel(user):
                    self._just_gave_summary = False
                    await self.capability_worker.speak("Okay.")
                    continue
                if self._looks_like_trigger(user):
                    self._just_gave_summary = False
                elif self._is_confirm_yes(user):
                    self._just_gave_summary = False
                    await self.handle_triage()
                    continue

            if self.pending_reply:
                await self.handle_pending_reply(user)
                if self.in_triage and not self.pending_reply:
                    if self._triage_just_sent_reply:
                        self._triage_just_sent_reply = False
                        self.triage_index += 1
                    await self.handle_triage()
                continue

            if self.pending_compose:
                await self.handle_pending_compose(user)
                continue

            # After read: same reply/archive/read flow as triage (one path: extract body when present, same handlers)
            if self._just_finished_read:
                self._just_finished_read = False
                lowered = user.lower()
                if "reply" in lowered:
                    reply_body = self._extract_reply_body_from_triage_action(user)
                    if reply_body:
                        self.pending_reply = {
                            "email_id": self.current_email["id"],
                            "waiting_for": "body",
                            "draft": None,
                        }
                        await self.handle_pending_reply(reply_body)
                    else:
                        await self.start_reply({})
                    continue
                if "archive" in lowered:
                    await self.handle_archive()
                    continue
                if "read" in lowered:
                    await self._read_full_current_email()
                    continue
                # anything else: fall through to classify (e.g. "read the one from Sarah")

            intent_data = self.classify_user_intent(
                {"trigger": user, "trigger_context": user}
            )
            await self.route_intent(
                intent_data["intent"], intent_data.get("details", {})
            )

    classify_user_intent = classify_trigger_intent  # alias for session_loop

    async def user_response_with_timeout(self, timeout):
        try:
            return await asyncio.wait_for(
                self.capability_worker.user_response(), timeout=timeout
            )
        except Exception:
            return None

    # =========================================================================
    # ROUTER
    # =========================================================================

    async def route_intent(self, intent: str, details: Dict):
        if intent == "summary":
            if details.get("count_only"):
                await self.handle_count()
            else:
                await self.handle_summary()
        elif intent == "read_specific":
            await self.handle_read(details)
        elif intent == "reply":
            await self.start_reply(details)
        elif intent == "compose":
            await self.start_compose(details)
        elif intent == "search":
            await self.handle_search(details)
        elif intent == "mark_read":
            await self.handle_mark_read()
        elif intent == "archive":
            await self.handle_archive()
        elif intent == "triage":
            await self.handle_triage()
        else:
            await self.handle_summary()

    # =========================================================================
    # COUNT (quick: just the number, no full summary)
    # =========================================================================

    async def handle_count(self):
        n = len(self.emails)
        if n == 0:
            await self.capability_worker.speak(
                "Your inbox is clear — no unread emails."
            )
        elif n == 1:
            await self.capability_worker.speak("You have 1 unread email.")
        else:
            await self.capability_worker.speak(f"You have {n} unread emails.")

    # =========================================================================
    # SUMMARY
    # =========================================================================

    async def handle_summary(self):
        if not self.emails:
            await self.capability_worker.speak(
                "Your inbox is clear — no unread emails."
            )
            return

        # Summarize all fetched emails so spoken count matches count-only path (len(self.emails))
        max_summary = min(len(self.emails), MAX_UNREAD_FETCH)
        prompt = SUMMARY_PROMPT.format(emails=json.dumps(self.emails[:max_summary]))

        summary = self.capability_worker.text_to_text_response(prompt)
        to_speak = ((summary or "").strip() + " Want me to go through them?").strip()
        await self.capability_worker.speak(
            to_speak or "You have unread emails. Want me to go through them?"
        )
        self._just_gave_summary = True  # "yes" in session_loop starts triage

    speak_summary = handle_summary  # alias

    # =========================================================================
    # READ
    # =========================================================================

    async def handle_read(self, details: Dict):
        if not self.emails:
            await self.capability_worker.speak(
                "Your inbox is clear — no unread emails."
            )
            return

        email = self._select_email_for_details(details)
        if (
            details.get("sender_name") or details.get("subject_keywords")
        ) and email is None:
            await self.capability_worker.speak(
                "I don't see any recent emails from that person. Can you give me more details?"
            )
            return
        if email is None:
            email = self.emails[0]
        self.current_email = email

        await self.capability_worker.speak("One sec.")
        try:
            full_html, err = self.outlook_get_message(email["id"])
            if err:
                await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                return
            if not full_html:
                await self.capability_worker.speak(
                    "I couldn't load that email from Outlook."
                )
                return
        except Exception as e:
            self.log_err(f"Get message failed: {e}")
            await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
            return

        body_text = self.strip_html(full_html)
        sender_name = (
            email.get("from", {}).get("emailAddress", {}).get("name") or "The sender"
        )
        subject = email.get("subject", "something without a subject")

        spoken = self.capability_worker.text_to_text_response(
            EMAIL_SUMMARY_PROMPT.format(
                sender=sender_name, subject=subject, body=body_text[:2000]
            )
        )
        await self.capability_worker.speak(
            f"{sender_name} emailed about {subject}. {spoken}"
        )

        if len(body_text) > 600:
            await self.capability_worker.speak(
                "Want me to read the full email? Say yes to hear it, or no to continue."
            )
            follow_up = await self.user_response_with_timeout(10)
            if self._is_confirm_yes(follow_up):
                await self.capability_worker.speak(body_text[:3000])

        await self.capability_worker.speak("Want to reply, archive, or read?")
        self._just_finished_read = True

    async def _read_full_current_email(self) -> bool:
        """Fetch full body for current_email, strip HTML, speak up to 3000 chars.
        Returns True if spoken, False on error."""
        if not self.current_email:
            return False
        try:
            full_html, err = self.outlook_get_message(self.current_email["id"])
            if err or not full_html:
                await self.capability_worker.speak(
                    OUTLOOK_ERROR_SPEAK if err else "I couldn't load that email."
                )
                return False
            body_text = self.strip_html(full_html)
            await self.capability_worker.speak(body_text[:3000])
            return True
        except Exception as e:
            self.log_err(f"Read full email failed: {e}")
            await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
            return False

    # =========================================================================
    # REPLY (STATEFUL)
    # =========================================================================

    async def start_reply(self, details: Optional[Dict] = None):
        details = details or {}
        if (
            not self.current_email
            and self.emails
            and (details.get("sender_name") or details.get("subject_keywords"))
        ):
            email = self._select_email_for_details(details)
            if email:
                self.current_email = email

        if not self.current_email:
            self.pending_reply = {
                "email_id": None,
                "waiting_for": "which_email",
                "draft": None,
            }
            await self.capability_worker.speak("Which email should I reply to?")
            return

        self.pending_reply = {
            "email_id": self.current_email["id"],
            "waiting_for": "body",
            "draft": None,
        }
        await self.capability_worker.speak("What do you want to say?")

    async def handle_pending_reply(self, user_input: str):
        lowered = user_input.lower()

        # Allow cancellation at any point (exit words or explicit cancel phrases)
        if any(
            phrase in lowered
            for phrase in ["cancel", "never mind", "nevermind", "forget it"]
        ) or any(phrase in lowered for phrase in EXIT_WORDS):
            self.pending_reply = None
            await self.capability_worker.speak("Okay, not replying.")
            return

        if self.pending_reply["waiting_for"] == "which_email":
            email = self._select_email_for_details(
                {
                    "sender_name": user_input.strip(),
                    "subject_keywords": user_input.strip(),
                }
            )
            if not email and self.emails:
                q = user_input.strip().lower()
                for e in self.emails:
                    from_name = (
                        e.get("from", {}).get("emailAddress", {}).get("name") or ""
                    ).lower()
                    subj = (e.get("subject") or "").lower()
                    if q in from_name or q in subj:
                        email = e
                        break
            if email:
                self.current_email = email
                self.pending_reply["email_id"] = email["id"]
                self.pending_reply["waiting_for"] = "body"
                await self.capability_worker.speak("What do you want to say?")
                return
            await self.capability_worker.speak(
                "I couldn't find that email. Which email should I reply to?"
            )
            return

        if self.pending_reply["waiting_for"] == "body":
            # Don't draft when user said only "Reply" or something too short (would produce generic reply)
            stripped = user_input.strip()
            if (
                not stripped
                or len(stripped) < 4
                or stripped.lower().rstrip(".,") in ("reply", "reply,")
            ):
                await self.capability_worker.speak("What do you want to say?")
                return
            replying_to = "the sender"
            if self.current_email:
                from_obj = self.current_email.get("from") or {}
                replying_to = (
                    from_obj.get("emailAddress", {}).get("name")
                    or from_obj.get("emailAddress", {}).get("address")
                    or replying_to
                )
            draft = self.capability_worker.text_to_text_response(
                DRAFT_REPLY_PROMPT.format(
                    user_input=user_input,
                    replying_to=replying_to,
                )
            )

            self.pending_reply["draft"] = draft
            self.pending_reply["waiting_for"] = "confirm"

            await self.capability_worker.speak(
                f"Here's what I'll send: {draft}. Should I send it?"
            )
            return

        if self.pending_reply["waiting_for"] == "confirm":
            if self._is_confirm_yes(user_input):
                await self.capability_worker.speak("Sending.")
                try:
                    _, err = self.outlook_send_reply(
                        self.pending_reply["email_id"], self.pending_reply["draft"]
                    )
                    if err:
                        await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                        self.pending_reply = None
                        return
                except Exception as e:
                    self.log_err(f"Send reply failed: {e}")
                    await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                    self.pending_reply = None
                    return
                await self.capability_worker.speak("Sent.")
                if self.in_triage:
                    self._triage_just_sent_reply = True
                self.pending_reply = None
                return

            # "No, say X instead" or "could you say X" → re-draft with new content immediately
            new_body = self._extract_revision_from_confirm(user_input)
            if new_body:
                replying_to = "the sender"
                if self.current_email:
                    from_obj = self.current_email.get("from") or {}
                    replying_to = (
                        from_obj.get("emailAddress", {}).get("name")
                        or from_obj.get("emailAddress", {}).get("address")
                        or replying_to
                    )
                draft = self.capability_worker.text_to_text_response(
                    DRAFT_REPLY_PROMPT.format(
                        user_input=new_body,
                        replying_to=replying_to,
                    )
                )
                self.pending_reply["draft"] = draft
                await self.capability_worker.speak(
                    f"Here's what I'll send: {draft}. Should I send it?"
                )
                return

            await self.capability_worker.speak(
                "Want to change anything, or should I skip it?"
            )
            self.pending_reply["waiting_for"] = "post_confirm"
            return

        if self.pending_reply["waiting_for"] == "post_confirm":
            if "change" in lowered or "edit" in lowered:
                self.pending_reply["waiting_for"] = "body"
                await self.capability_worker.speak("What should I say instead?")
                return

            self.pending_reply = None
            await self.capability_worker.speak("Okay, skipping the reply.")

    # =========================================================================
    # COMPOSE (STATEFUL)
    # =========================================================================

    async def start_compose(self, details: Dict):
        recipient = details.get("recipient")
        subject = details.get("subject_keywords")
        body = details.get("body_content")

        if not recipient:
            try:
                raw = self.capability_worker.text_to_text_response(
                    COMPOSE_EXTRACT_PROMPT.format(user_input=json.dumps(details))
                )
                clean = (raw or "").replace("```json", "").replace("```", "").strip()
                start, end = clean.find("{"), clean.rfind("}")
                if start != -1 and end > start:
                    clean = clean[start : end + 1]
                extracted = json.loads(clean)
                if isinstance(extracted, dict):
                    recipient = recipient or extracted.get("recipient")
                    subject = subject or extracted.get("subject")
                    body = body or extracted.get("body")
            except (json.JSONDecodeError, Exception):
                pass

        # Resolve name to email if needed; if we can't, ask for their email first
        if recipient and "@" not in recipient:
            resolved = self._resolve_recipient_address(recipient)
            if resolved:
                recipient = resolved
            else:
                self.pending_compose = {
                    "recipient": recipient,
                    "subject": subject,
                    "body": body,
                    "draft": None,
                    "waiting_for": "recipient_email",
                }
                name = recipient.strip()
                await self.capability_worker.speak(
                    f"I don't have an email address for {name}. What's their email?"
                )
                return

        if recipient and body:
            subject_for_email = subject or "Quick email"
            draft = self.capability_worker.text_to_text_response(
                DRAFT_COMPOSE_PROMPT.format(
                    recipient=recipient,
                    subject=subject_for_email,
                    body=body,
                )
            )
            self.pending_compose = {
                "recipient": recipient,
                "subject": subject_for_email,
                "body": body,
                "draft": draft,
                "waiting_for": "confirm",
            }
            recipient_spoken = (
                self.format_email_for_speech(recipient)
                if "@" in recipient
                else recipient
            )
            await self.capability_worker.speak(
                f"To {recipient_spoken}, subject: {subject_for_email}. "
                f"Here's what I'll send: {draft}. Should I send it?"
            )
            return

        self.pending_compose = {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "draft": None,
            "waiting_for": (
                "recipient" if not recipient else "subject" if not subject else "body"
            ),
        }

        if not recipient:
            await self.capability_worker.speak("Who should I send it to?")
        elif not subject:
            await self.capability_worker.speak("What's the subject?")
        else:
            await self.capability_worker.speak("What do you want to say?")

    async def handle_pending_compose(self, user_input: str):
        lowered = user_input.lower()

        if (
            "cancel" in lowered
            or "never mind" in lowered
            or "nevermind" in lowered
            or any(phrase in lowered for phrase in EXIT_WORDS)
        ):
            self.pending_compose = None
            await self.capability_worker.speak("Okay, cancelling the email.")
            return

        if self.pending_compose["waiting_for"] == "recipient":
            extracted_recipient = None
            extracted_subject = None
            extracted_body = None
            if "," in user_input or len(user_input.split()) > 3:
                try:
                    raw = self.capability_worker.text_to_text_response(
                        COMPOSE_EXTRACT_PROMPT.format(user_input=user_input)
                    )
                    clean = (
                        (raw or "").replace("```json", "").replace("```", "").strip()
                    )
                    start, end = clean.find("{"), clean.rfind("}")
                    if start != -1 and end > start:
                        clean = clean[start : end + 1]
                    ex = json.loads(clean)
                    if isinstance(ex, dict):
                        extracted_recipient = ex.get("recipient")
                        extracted_subject = ex.get("subject")
                        extracted_body = ex.get("body")
                except (json.JSONDecodeError, Exception):
                    pass

            recipient_val = extracted_recipient or user_input.strip()
            if extracted_subject:
                self.pending_compose["subject"] = extracted_subject
            if extracted_body:
                self.pending_compose["body"] = extracted_body
            resolved = self._resolve_recipient_address(recipient_val)
            if resolved:
                self.pending_compose["recipient"] = resolved
                if self.pending_compose.get("subject") and self.pending_compose.get(
                    "body"
                ):
                    draft = self.capability_worker.text_to_text_response(
                        DRAFT_COMPOSE_PROMPT.format(
                            recipient=self.pending_compose["recipient"],
                            subject=self.pending_compose["subject"],
                            body=self.pending_compose["body"],
                        )
                    )
                    self.pending_compose["draft"] = draft
                    self.pending_compose["waiting_for"] = "confirm"
                    recipient_spoken = (
                        self.format_email_for_speech(resolved)
                        if "@" in resolved
                        else resolved
                    )
                    await self.capability_worker.speak(
                        f"To {recipient_spoken}, subject: {self.pending_compose['subject']}. "
                        f"Here's what I'll send: {draft}. Should I send it?"
                    )
                    return
                if not self.pending_compose.get("subject"):
                    self.pending_compose["waiting_for"] = "subject"
                    await self.capability_worker.speak("What's the subject?")
                else:
                    self.pending_compose["waiting_for"] = "body"
                    await self.capability_worker.speak("What do you want to say?")
                return
            self.pending_compose["waiting_for"] = "recipient_email"
            name = recipient_val
            await self.capability_worker.speak(f"What's {name}'s email address?")
            return

        if self.pending_compose["waiting_for"] == "recipient_email":
            self.pending_compose["recipient"] = user_input.strip()
            if self.pending_compose.get("subject") and self.pending_compose.get("body"):
                draft = self.capability_worker.text_to_text_response(
                    DRAFT_COMPOSE_PROMPT.format(
                        recipient=self.pending_compose["recipient"],
                        subject=self.pending_compose["subject"],
                        body=self.pending_compose["body"],
                    )
                )
                self.pending_compose["draft"] = draft
                self.pending_compose["waiting_for"] = "confirm"
                recip = self.pending_compose["recipient"]
                recipient_spoken = (
                    self.format_email_for_speech(recip) if "@" in recip else recip
                )
                await self.capability_worker.speak(
                    f"To {recipient_spoken}, subject: {self.pending_compose['subject']}. "
                    f"Here's what I'll send: {draft}. Should I send it?"
                )
                return
            if not self.pending_compose.get("subject"):
                self.pending_compose["waiting_for"] = "subject"
                await self.capability_worker.speak("What's the subject?")
            else:
                self.pending_compose["waiting_for"] = "body"
                await self.capability_worker.speak("What do you want to say?")
            return

        if self.pending_compose["waiting_for"] == "subject":
            subject_normalized = " ".join(user_input.strip().split()) or "Quick email"
            self.pending_compose["subject"] = subject_normalized
            if self.pending_compose.get("editing_subject_only"):
                self.pending_compose.pop("editing_subject_only", None)
                draft = self.capability_worker.text_to_text_response(
                    DRAFT_COMPOSE_PROMPT.format(
                        recipient=self.pending_compose["recipient"],
                        subject=subject_normalized,
                        body=self.pending_compose["body"],
                    )
                )
                self.pending_compose["draft"] = draft
                self.pending_compose["waiting_for"] = "confirm"
                recipient = self.pending_compose["recipient"]
                recipient_spoken = (
                    self.format_email_for_speech(recipient)
                    if "@" in recipient
                    else recipient
                )
                await self.capability_worker.speak(
                    f"To {recipient_spoken}, subject: {subject_normalized}. "
                    f"Here's what I'll send: {draft}. Should I send it?"
                )
                return
            self.pending_compose["waiting_for"] = "body"
            await self.capability_worker.speak("What do you want to say?")
            return

        if self.pending_compose["waiting_for"] == "body":
            self.pending_compose["body"] = user_input

            draft = self.capability_worker.text_to_text_response(
                DRAFT_COMPOSE_PROMPT.format(
                    recipient=self.pending_compose["recipient"],
                    subject=self.pending_compose["subject"],
                    body=user_input,
                )
            )

            self.pending_compose["draft"] = draft
            self.pending_compose["waiting_for"] = "confirm"

            recipient = self.pending_compose["recipient"]
            recipient_spoken = (
                self.format_email_for_speech(recipient)
                if "@" in recipient
                else recipient
            )
            await self.capability_worker.speak(
                f"To {recipient_spoken}, subject: {self.pending_compose['subject']}. "
                f"Here's what I'll send: {draft}. Should I send it?"
            )
            return

        if self.pending_compose["waiting_for"] == "confirm":
            if self._is_confirm_yes(user_input):
                await self.capability_worker.speak("Sending.")
                try:
                    _, err = self.outlook_send_new(
                        self.pending_compose["recipient"],
                        self.pending_compose["subject"],
                        self.pending_compose["draft"],
                    )
                    if err:
                        await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                        self.pending_compose = None
                        return
                except Exception as e:
                    self.log_err(f"Send email failed: {e}")
                    await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                    self.pending_compose = None
                    return
                await self.capability_worker.speak("Sent.")
                self.pending_compose = None
                return

            await self.capability_worker.speak(
                "Want to change anything, or cancel the email?"
            )
            self.pending_compose["waiting_for"] = "post_confirm"
            return

        if self.pending_compose["waiting_for"] == "post_confirm":
            if "subject" in lowered and ("change" in lowered or "edit" in lowered):
                self.pending_compose["waiting_for"] = "subject"
                self.pending_compose["editing_subject_only"] = True
                await self.capability_worker.speak("What's the subject?")
                return
            if "change" in lowered or "edit" in lowered:
                self.pending_compose["waiting_for"] = "body"
                await self.capability_worker.speak("What do you want to say?")
                return

            self.pending_compose = None
            await self.capability_worker.speak("Okay, cancelling the email.")

    # =========================================================================
    # SEARCH
    # =========================================================================

    async def handle_search(self, details: Dict):
        search_input = json.dumps(details) if details else ""
        try:
            raw = self.capability_worker.text_to_text_response(
                SEARCH_EXTRACT_PROMPT.format(
                    user_input=search_input or "search my email"
                )
            )
            clean = (raw or "").replace("```json", "").replace("```", "").strip()
            start, end = clean.find("{"), clean.rfind("}")
            if start != -1 and end > start:
                clean = clean[start : end + 1]
            params = json.loads(clean)
            if isinstance(params, dict):
                sender = (
                    params.get("sender")
                    or details.get("email_address")
                    or details.get("sender_name")
                )
                keywords = (
                    params.get("keywords")
                    or details.get("subject_keywords")
                    or details.get("body_content")
                )
                date_range = params.get("date_range") or details.get("date_range")
            else:
                sender = details.get("email_address") or details.get("sender_name")
                keywords = details.get("subject_keywords") or details.get(
                    "body_content"
                )
                date_range = details.get("date_range")
        except (json.JSONDecodeError, Exception):
            sender = details.get("email_address") or details.get("sender_name")
            keywords = details.get("subject_keywords") or details.get("body_content")
            date_range = details.get("date_range")

        # If user gave a name (no @), match by display name from already-fetched
        # inbox — Graph API filters by address only
        if sender and "@" not in sender.strip():
            results_from_inbox = self._emails_matching_sender_name(sender.strip())
            if results_from_inbox:
                name = (
                    results_from_inbox[0]
                    .get("from", {})
                    .get("emailAddress", {})
                    .get("name", "them")
                )
                await self.capability_worker.speak(
                    f"I found {len(results_from_inbox)} from {name}. "
                    "Want me to read the most recent?"
                )
                follow_up = await self.user_response_with_timeout(10)
                if self._is_confirm_yes(follow_up):
                    self.emails = results_from_inbox
                    self.current_email = results_from_inbox[0]
                    await self.handle_read({})
                return
            # Fall through to API search

        results: List[Dict] = []
        await self.capability_worker.speak("One sec, searching your email.")
        try:
            if sender and "@" in sender and date_range:
                results, err = self.outlook_search_by_sender_and_date(
                    sender, date_range, MAX_SEARCH_RESULTS
                )
            elif sender and "@" in sender:
                results, err = self.outlook_search_by_sender(sender, MAX_SEARCH_RESULTS)
            elif sender and "@" not in sender:
                # Name only: Graph filters by address, so use keyword search
                results, err = self.outlook_search(sender, MAX_SEARCH_RESULTS)
            elif date_range:
                results, err = self.outlook_search_by_date_range(
                    date_range, MAX_SEARCH_RESULTS
                )
            elif keywords:
                results, err = self.outlook_search(keywords, MAX_SEARCH_RESULTS)
            else:
                err = None

            if err:
                await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                return
        except Exception as e:
            self.log_err(f"Search failed: {e}")
            await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
            return

        if not results:
            await self.capability_worker.speak("I didn't find anything.")
            return

        most_recent = results[0]
        from_name = (
            most_recent.get("from", {}).get("emailAddress", {}).get("name", "someone")
        )
        subject = most_recent.get("subject", "something")
        received = most_recent.get("receivedDateTime")
        when_spoken = (
            self.format_datetime_for_speech(received) if received else "recently"
        )

        await self.capability_worker.speak(
            f"I found {len(results)} email{'s' if len(results) != 1 else ''} matching that. "
            f"The most recent is from {from_name} on {when_spoken} about {subject}. "
            "Want me to read it?"
        )

        follow_up = await self.user_response_with_timeout(10)
        if self._is_confirm_yes(follow_up):
            self.emails = results
            self.current_email = most_recent
            await self.handle_read({})

    # =========================================================================
    # MARK READ
    # =========================================================================

    async def handle_mark_read(self):
        if not self.current_email:
            await self.capability_worker.speak("Which email should I mark as read?")
            return
        email_id = self.current_email.get("id")
        if not email_id:
            await self.capability_worker.speak(
                "I don't have a reference to that email."
            )
            return
        await self.capability_worker.speak("Marking it as read.")
        try:
            _, err = self.outlook_mark_read(email_id)
            if err:
                await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                return
        except Exception as e:
            self.log_err(f"Mark read failed: {e}")
            await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
            return
        await self.capability_worker.speak("Marked as read.")

    # =========================================================================
    # ARCHIVE
    # =========================================================================

    async def handle_archive(self):
        if not self.current_email:
            await self.capability_worker.speak("Which email should I archive?")
            return
        email_id = self.current_email.get("id")
        if not email_id:
            await self.capability_worker.speak(
                "I don't have a reference to that email."
            )
            return

        if not self.archive_folder_id:
            try:
                self.archive_folder_id, err = self.outlook_get_folder_id()
                if err:
                    await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                    return
                if not self.archive_folder_id:
                    await self.capability_worker.speak(
                        "I couldn't find your Archive folder. The email is still in your inbox."
                    )
                    return
            except Exception as e:
                self.log_err(f"Get archive folder failed: {e}")
                await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                return

        await self.capability_worker.speak("Archiving that email.")
        try:
            # Mark read before move; after move the message is in Archive and /me/messages/{id} can 404
            _, mark_err = self.outlook_mark_read(email_id)
            if mark_err:
                self.log_err(f"Mark read before archive failed: {mark_err}")
            _, err = self.outlook_archive(email_id, self.archive_folder_id)
            if err:
                await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
                return
        except Exception as e:
            self.log_err(f"Archive failed: {e}")
            await self.capability_worker.speak(OUTLOOK_ERROR_SPEAK)
            return
        await self.capability_worker.speak("Archived.")

    # =========================================================================
    # TRIAGE
    # =========================================================================

    async def handle_triage(self):
        if not self.emails:
            await self.capability_worker.speak("You don't have any emails to triage.")
            return

        if not self.in_triage:
            self.in_triage = True
            self.triage_index = 0
            await self.capability_worker.speak("Let's go through them.")

        max_index = min(len(self.emails), MAX_TRIAGE_BATCH)

        while self.triage_index < max_index:
            email = self.emails[self.triage_index]
            self.current_email = email

            from_name = (
                email.get("from", {}).get("emailAddress", {}).get("name", "Someone")
            )
            subject = email.get("subject", "an email")
            preview = (email.get("bodyPreview") or "").strip()[:300]
            one_sentence = self.capability_worker.text_to_text_response(
                TRIAGE_SUMMARY_PROMPT.format(
                    from_name=from_name,
                    subject=subject,
                    preview=preview or "(no preview)",
                )
            )
            one_sentence = (one_sentence or f"{from_name} sent {subject}.").strip()

            prefix = "First one — " if self.triage_index == 0 else "Next — "
            await self.capability_worker.speak(
                f"{prefix}{one_sentence} Reply, skip, mark as read, or archive?"
            )

            action = await self.user_response_with_timeout(15)
            if not action:
                self.triage_index += 1
                continue

            lowered = action.lower()

            if (
                any(word in lowered for word in EXIT_WORDS)
                or "that's enough" in lowered
            ):
                await self.capability_worker.speak("Okay, stopping triage.")
                self.in_triage = False
                return

            if "reply" in lowered:
                reply_body = self._extract_reply_body_from_triage_action(action)
                if reply_body:
                    self.pending_reply = {
                        "email_id": self.current_email["id"],
                        "waiting_for": "body",
                        "draft": None,
                    }
                    await self.handle_pending_reply(reply_body)
                else:
                    await self.start_reply()
                return
            if "archive" in lowered:
                await self.handle_archive()
            if "mark" in lowered or ("read" in lowered and "reply" not in lowered):
                await self.handle_mark_read()

            self.triage_index += 1

        self.in_triage = False
        await self.capability_worker.speak(
            "That's all the emails in this triage batch."
        )

    # =========================================================================
    # GRAPH API
    # =========================================================================

    def refresh_access_token(self) -> tuple:
        """Returns (access_token, error_message). error_message is None on success."""
        url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
        payload = {
            "client_id": CLIENT_ID,
            "refresh_token": REFRESH_TOKEN,
            "grant_type": "refresh_token",
            "scope": (
                "https://graph.microsoft.com/Mail.Read "
                "https://graph.microsoft.com/Mail.ReadWrite "
                "https://graph.microsoft.com/Mail.Send"
            ),
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return (data.get("access_token"), None)
            self.log_err(
                f"Token refresh failed: {response.status_code} {response.text}"
            )
            return (None, "I need you to reconnect your Outlook account.")
        except requests.Timeout:
            self.log_err("Token refresh timeout")
            return (None, "I couldn't reach Outlook. Check your connection.")
        except Exception as e:
            self.log_err(f"Token refresh error: {e}")
            return (
                None,
                "I'm having trouble connecting to Outlook right now. Try again in a minute.",
            )

    def graph_request(self, method, endpoint, body=None) -> tuple:
        """Returns (data, error_message). error_message is None on success."""
        access_token, err = self.refresh_access_token()
        if err:
            return (None, err)
        if not access_token:
            return (None, "I need you to reconnect your Outlook account.")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        url = f"{GRAPH_BASE_URL}/me{endpoint}"

        try:
            if method == "GET":
                r = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                r = requests.post(url, headers=headers, json=body, timeout=10)
            elif method == "PATCH":
                r = requests.patch(url, headers=headers, json=body, timeout=10)
            else:
                return (None, None)

            if r.status_code in [200, 201, 202]:
                return (r.json() if r.text else {}, None)

            self.log_err(f"Graph API error {r.status_code}: {r.text}")
            if r.status_code == 401:
                return (None, "I need you to reconnect your Outlook account.")
            if r.status_code == 403:
                return (
                    None,
                    "I don't have permission to access your email. Check that the right permissions are enabled.",
                )
            if r.status_code == 429:
                return (None, "Microsoft is rate limiting me. Try again in a minute.")
            return (
                None,
                "I'm having trouble connecting to Outlook right now. Try again in a minute.",
            )
        except requests.Timeout:
            self.log_err("Graph API request timeout")
            return (None, "I couldn't reach Outlook. Check your connection.")
        except Exception as e:
            self.log_err(f"Graph API request failed: {e}")
            return (
                None,
                "I'm having trouble connecting to Outlook right now. Try again in a minute.",
            )

    def outlook_list_unread(self, limit: int) -> tuple:
        """Returns (list of emails, error_message). error_message is None on success.
        Uses Inbox folder so unread count matches Outlook's Inbox."""
        data, err = self.graph_request(
            "GET",
            f"/mailFolders/inbox/messages?$filter=isRead eq false&$top={limit}"
            f"&$orderby=receivedDateTime desc"
            f"&$select=id,subject,from,receivedDateTime,bodyPreview,isRead",
        )
        if err:
            return ([], err)
        return (data.get("value", []) if data else [], None)

    def outlook_get_message(self, message_id: str) -> tuple:
        """Returns (body_content, error_message). error_message is None on success."""
        data, err = self.graph_request("GET", f"/messages/{message_id}")
        if err:
            return ("", err)
        return (data.get("body", {}).get("content", "") if data else "", None)

    def outlook_reply(self, message_id: str, text: str) -> tuple:
        """Returns (None, error_message). error_message is None on success."""
        _, err = self.graph_request(
            "POST", f"/messages/{message_id}/reply", {"comment": text}
        )
        return (None, err)

    def outlook_send_reply(self, message_id: str, text: str) -> tuple:
        """Returns (None, error_message). error_message is None on success."""
        return self.outlook_reply(message_id, text)

    def outlook_send_new(self, to: str, subject: str, body: str) -> tuple:
        """Returns (None, error_message). error_message is None on success."""
        _, err = self.graph_request(
            "POST",
            "/sendMail",
            {
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                }
            },
        )
        return (None, err)

    def outlook_mark_read(self, message_id: str) -> tuple:
        """Returns (None, error_message). error_message is None on success."""
        _, err = self.graph_request(
            "PATCH", f"/messages/{message_id}", {"isRead": True}
        )
        return (None, err)

    def outlook_get_archive_folder_id(self) -> tuple:
        """Returns (folder_id or None, error_message). error_message is None on success.
        Uses well-known folder name 'archive' so it works regardless of locale."""
        data, err = self.graph_request("GET", "/mailFolders/archive")
        if err:
            return (None, err)
        if data and data.get("id"):
            return (data["id"], None)
        return (None, None)

    def outlook_get_folder_id(self) -> tuple:
        """Returns (archive_folder_id or None, error_message)."""
        return self.outlook_get_archive_folder_id()

    def outlook_archive(self, message_id: str, folder_id: str) -> tuple:
        """Returns (None, error_message). error_message is None on success."""
        _, err = self.graph_request(
            "POST", f"/messages/{message_id}/move", {"destinationId": folder_id}
        )
        return (None, err)

    def outlook_search(self, query: str, limit: int) -> tuple:
        """Returns (list of messages, error_message)."""
        data, err = self.graph_request(
            "GET", f'/messages?$search="{query}"&$top={limit}'
        )
        if err:
            return ([], err)
        return (data.get("value", []) if data else [], None)

    def outlook_search_by_sender(self, sender: str, limit: int) -> tuple:
        """Returns (list of messages, error_message)."""
        sender_value = sender.strip()
        data, err = self.graph_request(
            "GET",
            f"/messages?$filter=from/emailAddress/address eq '{sender_value}'"
            f"&$top={limit}&$orderby=receivedDateTime desc",
        )
        if err:
            return ([], err)
        return (data.get("value", []) if data else [], None)

    def outlook_search_by_date_range(self, date_range: str, limit: int) -> tuple:
        """Returns (list of messages, error_message)."""
        start_iso = self._date_range_to_start_iso(date_range)
        if not start_iso:
            return ([], None)
        data, err = self.graph_request(
            "GET",
            f"/messages?$filter=receivedDateTime ge {start_iso}"
            f"&$top={limit}&$orderby=receivedDateTime desc",
        )
        if err:
            return ([], err)
        return (data.get("value", []) if data else [], None)

    def outlook_search_by_sender_and_date(
        self, sender: str, date_range: str, limit: int
    ) -> tuple:
        """Returns (list of messages, error_message)."""
        start_iso = self._date_range_to_start_iso(date_range)
        if not start_iso:
            return self.outlook_search_by_sender(sender, limit)
        sender_value = sender.strip()
        data, err = self.graph_request(
            "GET",
            f"/messages?$filter=from/emailAddress/address eq '{sender_value}' "
            f"and receivedDateTime ge {start_iso}"
            f"&$top={limit}&$orderby=receivedDateTime desc",
        )
        if err:
            return ([], err)
        return (data.get("value", []) if data else [], None)

    # =========================================================================
    # UTILITIES
    # =========================================================================

    @staticmethod
    def _extract_reply_body_from_triage_action(action: str) -> Optional[str]:
        """From e.g. 'Reply — tell her X', 'Reply saying thank you', 'Could you reply saying X' return the body text.
        Same parsing for triage and after-read so reply flow is identical."""
        if not action or not action.strip():
            return None
        lower = action.lower().strip()
        # "could you reply saying X" / "can you reply saying X"
        for prefix in (
            "could you reply saying ",
            "can you reply saying ",
            "reply saying ",
            "reply with ",
        ):
            if lower.startswith(prefix):
                rest = action[len(prefix) :].strip()
                return rest if rest else None
        # "Reply — X", "Reply, X", "Reply X"
        for prefix in ("reply — ", "reply—", "reply, ", "reply , ", "reply "):
            if lower.startswith(prefix):
                rest = action[len(prefix) :].strip()
                return rest if rest else None
        if lower.startswith("reply"):
            rest = action[5:].strip().lstrip("—,-:")
            return rest if rest else None
        return None

    def _extract_revision_from_confirm(self, user_input: str) -> Optional[str]:
        """If user said 'no, say X instead' or 'could you say X', return X for re-drafting; else None."""
        if not user_input or len(user_input.strip()) < 5:
            return None
        lower = user_input.strip().lower()
        if self._is_confirm_no_or_cancel(user_input) and len(lower) < 15:
            return None
        prefixes = (
            "no, ",
            "nope, ",
            "no. ",
            "could you say ",
            "can you say ",
            "change it to say ",
            "change it to ",
            "say ",
            "instead say ",
        )
        text = user_input.strip()
        while True:
            before = text
            for prefix in prefixes:
                if text.lower().startswith(prefix):
                    text = text[len(prefix) :].strip()
                    break
            if text == before:
                break
        if text.lower().endswith(" instead"):
            text = text[: -len(" instead")].strip()
        if text and len(text) >= 3:
            return text
        return None

    def _looks_like_trigger(self, text: Optional[str]) -> bool:
        """True if the input looks like an initial email/inbox trigger, not a yes/no to a follow-up."""
        if not text or not text.strip():
            return False
        lower = text.lower().strip().rstrip(".!?")
        if lower in ("outlook", "email", "emails", "inbox"):
            return True
        trigger_phrases = [
            "check my email",
            "triage",
            "go through my email",
            "catch me up on email",
            "read me my emails",
            "check email",
            "check my mail",
        ]
        return any(phrase in lower for phrase in trigger_phrases)

    def _is_confirm_yes(self, text: Optional[str]) -> bool:
        """True if the user's response sounds like a yes/confirm (send it, read it, etc.)."""
        if not text or not text.strip():
            return False
        lower = text.lower().strip()
        return any(phrase in lower for phrase in CONFIRM_YES_PHRASES)

    def _is_confirm_no_or_cancel(self, text: Optional[str]) -> bool:
        """True if the user is declining, cancelling, or exiting this step."""
        if not text or not text.strip():
            return True
        lower = text.lower().strip()
        if any(phrase in lower for phrase in CONFIRM_NO_PHRASES):
            return True
        if any(phrase in lower for phrase in EXIT_WORDS):
            return True
        return False

    def strip_html(self, html: str) -> str:
        text = re.sub(r"<[^>]+>", "", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def clean_email_body_for_speech(self, html: str) -> str:
        """
        Strip HTML, signatures, reply chains and raw URLs to make the body
        friendlier to speak aloud.
        """
        text = self.strip_html(html)

        lines = text.splitlines()
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            lower = stripped.lower()
            if (
                lower.startswith("from:")
                or lower.startswith("sent:")
                or lower.startswith("to:")
            ):
                break
            if stripped.startswith("On ") and "wrote:" in stripped:
                break
            cleaned_lines.append(stripped)

        text = " ".join(cleaned_lines)

        sig_index = text.find("--")
        if sig_index != -1:
            text = text[:sig_index]

        text = re.sub(r"https?://\S+", " there's a link ", text)
        # Speak email addresses as "name at domain dot com"
        text = re.sub(
            r"\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
            lambda m: self.format_email_for_speech(m.group(0)),
            text,
        )
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def format_email_for_speech(self, email_address: str) -> str:
        """
        Convert an email address into a spoken-friendly format.
        "chris@openhome.com" -> "chris at openhome dot com"
        """
        return email_address.replace("@", " at ").replace(".", " dot ")

    def format_datetime_for_speech(self, iso_string: str) -> str:
        """
        Convert an ISO 8601 datetime string into a simple spoken format,
        like "Tuesday at 3 PM".
        """
        try:
            dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
            hour_12 = dt.hour % 12 or 12  # 0 -> 12 for noon/midnight
            return dt.strftime("%A at ") + str(hour_12) + dt.strftime(" %p")
        except Exception:
            return "recently"

    def _date_range_to_start_iso(self, date_range: str) -> Optional[str]:
        """
        Interpret date range phrases into an ISO start date for Graph $filter.
        Supports: "today", "yesterday", "this week", "last week", "last month".
        """
        if not date_range:
            return None

        now = datetime.utcnow()
        lowered = date_range.lower().strip()

        if "today" in lowered:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif "yesterday" in lowered:
            start = (now - timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif "this week" in lowered:
            start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif "last week" in lowered:
            start = (now - timedelta(days=now.weekday() + 7)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif "last month" in lowered:
            month = now.month - 1 or 12
            year = now.year - 1 if now.month == 1 else now.year
            start = datetime(year, month, 1, 0, 0, 0, 0)
        else:
            return None

        return start.isoformat() + "Z"

    def _emails_matching_sender_name(self, name_query: str) -> List[Dict]:
        if not name_query or not self.emails:
            return []
        lower_q = name_query.lower()
        return [
            e
            for e in self.emails
            if lower_q
            in ((e.get("from", {}).get("emailAddress", {}).get("name") or "").lower())
        ]

    def _select_email_for_details(self, details: Dict) -> Optional[Dict]:
        """
        Try to choose a specific email from self.emails based on LLM-extracted details.
        Matches by sender display name (e.g. "cursor" matches "Cursor Team") or subject keywords.
        """
        if not details or not self.emails:
            return None

        sender_name = (details.get("sender_name") or "").lower()
        subject_keywords = (details.get("subject_keywords") or "").lower()

        for email in self.emails:
            from_obj = email.get("from", {}).get("emailAddress", {})
            name = (from_obj.get("name") or "").lower()
            subject = (email.get("subject") or "").lower()

            if sender_name and sender_name in name:
                return email
            if subject_keywords and subject_keywords in subject:
                return email

        return None

    def _resolve_recipient_address(self, name_or_email: str) -> Optional[str]:
        """
        Resolve a spoken recipient (name or email) to an email address.
        - If it already looks like an email, return as-is.
        - Otherwise, try to match against recent emails' from/to names.
        """
        candidate = name_or_email.strip()
        if "@" in candidate:
            return candidate

        lowered = candidate.lower()

        for email in self.emails:
            from_obj = email.get("from", {}).get("emailAddress", {})
            from_name = (from_obj.get("name") or "").lower()
            from_addr = from_obj.get("address")
            if lowered and lowered in from_name and from_addr:
                return from_addr

            for recip in email.get("toRecipients") or []:
                r_name = (recip.get("emailAddress", {}).get("name") or "").lower()
                r_addr = recip.get("emailAddress", {}).get("address")
                if lowered and lowered in r_name and r_addr:
                    return r_addr

        return None

    async def load_preferences(self) -> Dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )
            if not exists:
                return {
                    "max_emails_in_summary": MAX_UNREAD_FETCH,
                    "triage_order": "newest_first",
                }

            raw = await self.capability_worker.read_file(PREFS_FILE, False)
            return json.loads(raw)
        except Exception:
            return {
                "max_emails_in_summary": MAX_UNREAD_FETCH,
                "triage_order": "newest_first",
            }

    async def load_json(self, filename: str, temp: bool = False) -> Dict:
        """Check exists + read JSON."""
        try:
            if not await self.capability_worker.check_if_file_exists(filename, temp):
                return {}
            raw = await self.capability_worker.read_file(filename, temp)
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    async def save_json(self, filename: str, data: Dict, temp: bool = False):
        """Save JSON (delete then write)."""
        try:
            if await self.capability_worker.check_if_file_exists(filename, temp):
                await self.capability_worker.delete_file(filename, temp)
            await self.capability_worker.write_file(filename, json.dumps(data), temp)
        except Exception:
            self.log_err(f"Failed to persist {filename}")
