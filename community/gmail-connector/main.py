import base64
import json
import re
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

CONTACTS_FILE = "gmail_contacts.json"

EMAIL_SYSTEM = (
    "You are an intelligent voice email assistant running on OpenHome. "
    "The user is speaking — all your output will be read aloud. "
    "Keep responses concise and natural for speech, under 2 sentences and 25 words. "
    "Never use markdown, bullet points, numbered lists, emojis, URLs, or raw email addresses. "
    "When drafting emails, be professional yet conversational."
)

# Shared ordinal/positional word-to-number map for voice input
_ORDINAL_MAP = {
    "first": 1, "1st": 1, "one": 1,
    "second": 2, "2nd": 2, "two": 2,
    "third": 3, "3rd": 3, "three": 3,
    "fourth": 4, "4th": 4, "four": 4,
    "fifth": 5, "5th": 5, "five": 5,
    "sixth": 6, "6th": 6, "six": 6,
    "seventh": 7, "7th": 7, "seven": 7,
    "eighth": 8, "8th": 8, "eight": 8,
    "ninth": 9, "9th": 9, "nine": 9,
    "tenth": 10, "10th": 10, "ten": 10,
    "top": 1,
}

_ORDINAL_MAP_ZERO = {k: v - 1 for k, v in _ORDINAL_MAP.items()}


#  Low-level Gmail helpers
def _build_gmail_service(token: str):
    creds = Credentials(token=token)
    return build("gmail", "v1", credentials=creds)


def _make_message(to: str, subject: str, body: str) -> dict:
    msg = MIMEMultipart()
    msg["to"] = to
    msg["subject"] = subject.title()
    msg.attach(MIMEText(body, "plain"))
    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}


def _make_reply(to: str, subject: str, body: str,
                thread_id: str, message_id_header: str) -> dict:
    msg = MIMEMultipart()
    msg["to"] = to
    msg["subject"] = subject.title() if subject.startswith("Re:") else f"Re: {subject}"
    msg["In-Reply-To"] = message_id_header
    msg["References"] = message_id_header
    msg.attach(MIMEText(body, "plain"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw, "threadId": thread_id}


def _get_header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_body(msg: dict) -> str:
    payload = msg.get("payload", {})
    def _extract(part):
        if part.get("mimeType", "") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            result = _extract(sub)
            if result:
                return result
        return ""
    return _extract(payload).strip()


def _sender_display(msg: dict) -> tuple:
    """Returns (display_name, email_address) from a Gmail message dict."""
    headers = msg.get("payload", {}).get("headers", [])
    sender = _get_header(headers, "From")
    m = re.search(r"<([^>]+)>", sender)
    email = m.group(1) if m else sender
    name = re.sub(r"<[^>]+>", "", sender).strip().strip('"') or sender
    return name, email


def _clean_subject(subject: str) -> str:
    """Strip GitHub/CI noise from subject lines before speaking them."""
    subject = re.sub(r"\[openhome[^\]]*\]", "", subject)
    subject = re.sub(r"\(PR #\d+\)", "", subject)
    subject = re.sub(r"#\d+", "", subject)
    subject = re.sub(r"\s{2,}", " ", subject)
    return subject.strip() or "no subject"


def _list_messages(service, query: str, max_results: int = 500) -> list:
    messages, page_token = [], None
    while len(messages) < max_results:
        kwargs = {
            "userId": "me",
            "q": query,
            "maxResults": min(500, max_results - len(messages)),
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.users().messages().list(**kwargs).execute()
        messages.extend(result.get("messages", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return messages


def _get_message(service, msg_id: str) -> dict:
    return service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()


def _send_message(service, message: dict) -> dict:
    return service.users().messages().send(userId="me", body=message).execute()


def _modify_labels(service, msg_id: str,
                   add_labels: list = None, remove_labels: list = None) -> dict:
    return service.users().messages().modify(
        userId="me", id=msg_id,
        body={"addLabelIds": add_labels or [], "removeLabelIds": remove_labels or []}
    ).execute()


def _mark_read(service, msg_id: str) -> None:
    try:
        _modify_labels(service, msg_id, remove_labels=["UNREAD"])
    except Exception:
        pass


#  Capability class
class GmailCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    # LLM shorthand
    def _llm(self, prompt: str, history: list = None) -> str:
        return self.capability_worker.text_to_text_response(
            prompt,
            history=history or [],
            system_prompt=EMAIL_SYSTEM,
        ).strip()

    # Voice helpers

    async def _speak(self, text: str) -> None:
        await self.capability_worker.speak(text)

    async def _ask(self, question: str) -> str:
        await self.capability_worker.speak(question)
        return (await self.capability_worker.user_response()).strip()

    # KV upsert helper

    def _upsert_key(self, key: str, value) -> None:
        try:
            existing = self.capability_worker.get_single_key(key)
            if existing is not None:
                self.capability_worker.update_key(key, value)
            else:
                self.capability_worker.create_key(key, value)
        except Exception:
            try:
                self.capability_worker.create_key(key, value)
            except Exception:
                pass

    # Persistent contact memory
    async def _load_contacts(self) -> dict:
        try:
            if await self.capability_worker.check_if_file_exists(CONTACTS_FILE, False):
                raw = await self.capability_worker.read_file(CONTACTS_FILE, False)
                return json.loads(raw)
        except Exception:
            pass
        return {}

    async def _save_contacts(self, contacts: dict) -> None:
        try:
            if await self.capability_worker.check_if_file_exists(CONTACTS_FILE, False):
                await self.capability_worker.delete_file(CONTACTS_FILE, False)
            await self.capability_worker.write_file(
                CONTACTS_FILE, json.dumps(contacts), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Contact save error: {e}")

    async def _remember_contact(self, email: str, name: str = "") -> None:
        # Strip trailing punctuation from name before storing
        name = name.strip().rstrip(".,!?;:") if name else ""
        
        # Reject LLM "NONE" values that slipped through
        if name.upper() in ("NONE", "NONE.", "", "N/A", "NA", "UNKNOWN", "NULL", "-"):
            name = ""

        contacts = await self._load_contacts()
        local = email.split("@")[0].lower()
        entry = {"email": email, "name": name or local}
        contacts[local] = entry
        if name:
            name_key = re.sub(r"\s+", "_", name.lower().strip())
            contacts[name_key] = entry
        await self._save_contacts(contacts)

    async def _lookup_contact(self, raw_name: str) -> Optional[str]:
        contacts = await self._load_contacts()
        if not contacts:
            return None
        summary = "\n".join([
            f"{k}: {v['email']} ({v.get('name', '')})"
            for k, v in contacts.items()
        ])
        result = self._llm(
            f"The user wants to contact: \"{raw_name}\"\n"
            f"Known contacts:\n{summary}\n\n"
            "Fuzzy-match by name or local email part.\n"
            "Reply with ONLY the email address, or NONE."
        )
        if result.upper() == "NONE" or "@" not in result:
            return None
        return result.strip()

    # Email context (KV session memory)
    def _store_email_context(self, emails: list) -> None:
        context = []
        for msg in emails:
            headers = msg.get("payload", {}).get("headers", [])
            name, sender_email = _sender_display(msg)
            context.append({
                "id": msg.get("id"),
                "threadId": msg.get("threadId"),
                "sender_name": name,
                "sender_email": sender_email,
                "subject": _clean_subject(_get_header(headers, "Subject") or "no subject"),
                "message_id_header": _get_header(headers, "Message-ID"),
            })
        self._upsert_key("recent_emails_context", context)
        debug_lines = [
            f"  [{i+1}] id={e['id']} | from={e['sender_name']} | subject={e['subject']}"
            for i, e in enumerate(context)
        ]
        
    def _resolve_from_context(self, hint: str, service) -> Optional[dict]:
        """Fast-path: match against KV-stored email list before hitting Gmail API."""
        try:
            context = self.capability_worker.get_single_key("recent_emails_context")
            if not context or not isinstance(context, list):
                self.worker.editor_logging_handler.info(
                    f"KV[recent_emails_context] is empty or missing — hint='{hint}'"
                )
                return None
            self.worker.editor_logging_handler.info(
                f"KV[recent_emails_context] resolving '{hint}' against "
                f"{len(context)} entries: "
                + ", ".join(f"{e.get('sender_name','?')}:{e.get('subject','?')[:30]}" for e in context)
            )
        except Exception:
            return None

        hint_lower = hint.lower()

        # "last" / "bottom" → last item in context
        if re.search(r'\b(last|bottom)\b', hint_lower) and context:
            try:
                return _get_message(service, context[-1]["id"])
            except Exception:
                pass

        num_m = re.search(r'\b(?:no\.?|number|#)\s*(\d+)\b', hint_lower)
        if num_m:
            idx = int(num_m.group(1)) - 1
            if 0 <= idx < len(context):
                try:
                    return _get_message(service, context[idx]["id"])
                except Exception:
                    pass

        for word, num in _ORDINAL_MAP.items():
            if re.search(r'\b' + word + r'\b', hint_lower):
                idx = num - 1
                if 0 <= idx < len(context):
                    try:
                        return _get_message(service, context[idx]["id"])
                    except Exception:
                        pass
                break

        summary = "\n".join([
            f"{i+1}. From: {e['sender_name']} <{e['sender_email']}>, Subject: {e['subject']}"
            for i, e in enumerate(context)
        ])
        result = self._llm(
            f"The user said: \"{hint}\"\n"
            f"Recently listed emails:\n{summary}\n\n"
            "Does this refer to one of these emails?\n"
            "Match by ordinal, name, or subject keyword.\n"
            "Reply with ONLY the 1-based index, or NONE."
        )
        if result.upper() == "NONE":
            return None
        nums = re.findall(r"\d+", result)
        if nums:
            idx = int(nums[0]) - 1
            if 0 <= idx < len(context):
                try:
                    return _get_message(service, context[idx]["id"])
                except Exception as e:
                    self.worker.editor_logging_handler.error(f"Context fetch error: {e}")
        return None

    # Email resolution
    async def _resolve_email(self, service, hint: str = "") -> Optional[dict]:
        """Resolve a natural-language description to a Gmail message."""
        if not hint:
            hint = await self._ask(
                "Which email? Say the sender, subject, or a keyword."
            )

        ctx = self._resolve_from_context(hint, service)
        if ctx:
            self.worker.editor_logging_handler.info("Resolved from KV context.")
            return ctx

        query = self._llm(
            f"The user described an email: \"{hint}\"\n"
            "Convert to a precise Gmail search query.\n"
            "Rules:\n"
            "- Use subject:\"exact phrase\" (with quotes) for subject keywords\n"
            "- Use from:name for sender names\n"
            "- Combine with AND if both sender and subject are mentioned\n"
            "- Do NOT include in:inbox — added automatically\n"
            "- Do NOT use broad single-word queries that could match unrelated emails\n"
            "Examples:\n"
            "  'Eid holidays email'         → subject:\"Eid holidays\"\n"
            "  'email from Ahmed'           → from:Ahmed\n"
            "  'PR review email from danial'→ from:danial subject:\"PR\"\n"
            "  'invoice email'              → subject:\"invoice\"\n"
            "Reply with ONLY the query string."
        )
        # Always restrict to inbox so sent/reply threads don't appear
        query = f"in:inbox {query}".strip()
        self.worker.editor_logging_handler.info(f"Gmail primary query: '{query}'")
        messages = _list_messages(service, query, max_results=5)

        if not messages:
            # Loose fallback: quoted keywords only (no operators that could misfire)
            loose_kw = self._llm(
                f"The user described: \"{hint}\"\n"
                "Extract the 1-2 most distinctive keywords (no operators, no stop words).\n"
                "Wrap multi-word phrases in double quotes.\n"
                "Examples: 'Eid holidays email' → \"Eid holidays\"  |  'email from ahmed' → ahmed\n"
                "Reply with ONLY the keyword(s)."
            )
            loose_query = f"in:inbox {loose_kw}".strip()
            self.worker.editor_logging_handler.info(f"Gmail loose query: '{loose_query}'")
            messages = _list_messages(service, loose_query, max_results=5)

        if not messages:
            # Final fallback: drop in:inbox restriction — email may have been read/replied
            # and lost its INBOX label, but still exists in All Mail
            all_mail_query = re.sub(r'\bin:inbox\s*', '', query).strip()
            if all_mail_query:
                self.worker.editor_logging_handler.info(
                    f"Gmail all-mail fallback query: '{all_mail_query}'"
                )
                messages = _list_messages(service, all_mail_query, max_results=5)

        if not messages:
            hint = await self._ask(
                "Couldn't find that. Be more specific — "
                "sender name, their email, or the subject?"
            )
            query2 = self._llm(
                f"The user described an email: \"{hint}\"\n"
                "Convert to a Gmail search query. Reply with ONLY the query."
            )
            messages = _list_messages(service, query2, max_results=5)
            if not messages:
                await self._speak("Still couldn't find any matching emails.")
                return None

        if len(messages) == 1:
            return _get_message(service, messages[0]["id"])

        candidates = [_get_message(service, m["id"]) for m in messages[:5]]
        self._store_email_context(candidates)

        preselect = self._llm(
            f"The user said: \"{hint}\"\n"
            f"Search returned {len(candidates)} results.\n"
            "If they specified an ordinal or precise subject keyword → give 1-based index.\n"
            "If only a sender name with no other detail → NONE.\n"
            "Reply with ONLY the index or NONE."
        )
        nums = re.findall(r"\d+", preselect)
        if nums:
            idx = max(0, min(int(nums[0]) - 1, len(candidates) - 1))
            return candidates[idx]

        preamble = f"I found {len(candidates)} matching emails."

        shown = candidates[:3]
        options = ". ".join([
            f"Number {i+1}, from {_sender_display(c)[0]}, "
            f"about {_clean_subject(_get_header(c.get('payload', {}).get('headers', []), 'Subject') or 'no subject')}"
            for i, c in enumerate(shown)
        ])
        await self._speak(f"{preamble} {options}.")
        pick_raw = await self._ask(f"Which one? Say a number, 1 to {len(shown)}.")

        pick_lower = pick_raw.lower()
        direct_idx = None
        if re.search(r'\b(last|bottom)\b', pick_lower):
            direct_idx = len(candidates) - 1
        else:
            for word, i in _ORDINAL_MAP_ZERO.items():
                if re.search(r'\b' + word + r'\b', pick_lower):
                    direct_idx = i
                    break
        if direct_idx is None:
            num_m2 = re.search(r'\b(?:no\.?|number|#)?\s*(\d+)\b', pick_lower)
            if num_m2:
                direct_idx = int(num_m2.group(1)) - 1
        if direct_idx is not None and 0 <= direct_idx < len(candidates):
            return candidates[direct_idx]

        pick_result = self._llm(
            f"The user said: \"{pick_raw}\". There are {len(candidates)} options.\n"
            "Reply with ONLY the integer of the chosen option."
        )
        nums2 = re.findall(r"\d+", pick_result)
        idx = max(0, min(int(nums2[0]) - 1 if nums2 else 0, len(candidates) - 1))
        return candidates[idx]

    # Text cleaning
    def _clean_for_speech(self, text: str) -> str:
        if not text:
            return ""
        text = (text.replace("&amp;", "and").replace("&lt;", "less than")
                .replace("&gt;", "greater than").replace("&nbsp;", " ")
                .replace("&quot;", '"').replace("&#39;", "'").replace("&apos;", "'"))
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"https?://\S+|www\.\S+", "", text)
        text = re.sub(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
                      "an email address", text)
        text = re.sub(r"—\s*Reply to this email directly.*", "", text, flags=re.DOTALL)
        text = re.sub(r"You are receiving this because.*", "", text, flags=re.DOTALL)
        text = re.sub(r"^[\-=_]{3,}\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"#{1,6}\s+", "", text)
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
        text = re.sub(r"\[openhome[^\]]*\]|\(PR #\d+\)|#\d+", "", text)
        text = re.sub(r"\([^)]{0,40}\)", "", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _summarize_for_speech(self, body: str) -> str:
        if len(body) <= 150:
            return body
        return self._llm(
            "Summarize this email in 2-3 concise spoken sentences, under 40 words total. "
            "Natural and conversational — it will be read aloud. "
            "No markdown, no URLs, no email addresses, no emojis, no lists.\n\n"
            f"{body[:3000]}"
        )

    def _spell_email_for_speech(self, email: str) -> str:
        if "@" not in email:
            return email
        local, domain = email.split("@", 1)
        common = {
            "gmail.com": "gmail dot com", "yahoo.com": "yahoo dot com",
            "outlook.com": "outlook dot com", "hotmail.com": "hotmail dot com",
            "icloud.com": "icloud dot com", "me.com": "me dot com",
        }
        punct = {".": "dot", "-": "dash", "_": "underscore", "+": "plus"}
        def spell(part):
            return " ".join(punct.get(ch, ch) for ch in part)
        return f"{spell(local)} at {common.get(domain.lower(), spell(domain))}"

    def _extract_email_with_llm(self, raw_text: str) -> Optional[str]:
        cleaned = raw_text.strip().rstrip(".,!?;:")
        direct = re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", cleaned)
        if direct:
            candidate = direct.group(0).rstrip(".,!?;:")
            if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", candidate):
                return candidate
        result = self._llm(
            "Voice transcription of someone saying an email address. "
            "'at' means '@', 'dot' means '.'. Reconstruct the email.\n"
            "Reply with ONLY the email, or NONE.\n\n"
            f"Transcription: \"{cleaned}\""
        ).lower().rstrip(".,!?;:")
        if result == "none" or "@" not in result:
            return None
        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", result):
            return result
        return None

    # Shared: read a message aloud
    async def _read_full_message(self, service, msg: dict) -> None:
        headers = msg.get("payload", {}).get("headers", [])
        name, _ = _sender_display(msg)
        subject = _clean_subject(_get_header(headers, "Subject") or "no subject")
        date = _get_header(headers, "Date")
        body = self._clean_for_speech(_decode_body(msg))

        # Build one combined speech: Subject → From → Body → Received time
        parts = [f"{subject}, from {name}."]
        parts.append(
            self._summarize_for_speech(body) if body
            else "The email body appears to be empty."
        )
        if date:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date)
                day = dt.day
                hour = dt.hour % 12 or 12
                minute = dt.minute
                am_pm = "in the morning" if dt.hour < 12 else (
                    "in the afternoon" if dt.hour < 17 else "in the evening"
                )
                if minute == 0:
                    time_str = f"{hour} o'clock"
                elif minute < 10:
                    time_str = f"{hour} oh {minute}"
                else:
                    time_str = f"{hour} {minute}"
                parts.append(
                    f"Received {dt.strftime('%A')} {dt.strftime('%B')} {day} at {time_str} {am_pm}."
                )
            except Exception:
                pass

        await self._speak(" ".join(parts))
        _mark_read(service, msg["id"])
        self._store_email_context([msg])

    # Shared: handle post-read reply decision
    async def _handle_post_read_reply(self, service, msg: dict) -> None:
        """After reading an email aloud, ask user what to do and handle reply/archive."""
        post_raw = await self._ask("Want to reply, archive, or move on?")
        decision = self._llm(
            f"The user said: \"{post_raw}\"\n"
            "Classify AND extract in one step. Reply with ONLY valid JSON:\n"
            '{"action": "SEND|REPLY|ARCHIVE|NO", "content": "extracted reply text or null"}\n'
            "SEND = they stated reply content directly (e.g. 'got it', 'yeah I'll be there', 'sounds good').\n"
            "REPLY = said yes/sure but gave NO specific content.\n"
            "ARCHIVE = wants to archive/trash/delete.\n"
            "NO = declined (no, nah, done, skip, move on, I'm good).\n"
            "For SEND, extract the reply content stripping filler like 'yes'/'sure'."
        ).strip()

        try:
            parsed = json.loads(re.sub(r"```(?:json)?|```", "", decision).strip())
        except Exception:
            parsed = {"action": "NO", "content": None}

        action = parsed.get("action", "NO").upper()
        content = parsed.get("content")

        if action == "SEND" and content:
            headers_t = msg.get("payload", {}).get("headers", [])
            _, reply_to = _sender_display(msg)
            subj_t = _clean_subject(_get_header(headers_t, "Subject") or "no subject")
            msg_id_t = _get_header(headers_t, "Message-ID")
            thread_t = msg.get("threadId", "")
            try:
                _send_message(service, _make_reply(reply_to, subj_t, content, thread_t, msg_id_t))
                await self._speak("Reply sent.")
                await self._remember_contact(reply_to)
            except Exception as e:
                await self._speak("Something went wrong sending the reply.")
                self.worker.editor_logging_handler.error(f"Reply error: {e}")
        elif action == "REPLY":
            await self._flow_reply(service, raw_utterance=post_raw, msg=msg)
        elif action == "ARCHIVE":
            try:
                _modify_labels(service, msg["id"], remove_labels=["INBOX"])
                await self._speak("Archived.")
            except Exception:
                await self._speak("Couldn't archive that one.")

    #  Flow: Compose / Send
    async def _flow_compose(self, service, raw_utterance: str = "") -> None:
        pre = {}
        if raw_utterance:
            raw = self._llm(
                f"The user said: \"{raw_utterance}\"\n"
                "Extract email fields already mentioned. Reply with ONLY valid JSON:\n"
                '{"to": "email or null", "subject": "subject or null", "body": "body or null"}'
            )
            try:
                pre = json.loads(re.sub(r"```(?:json)?|```", "", raw).strip())
            except Exception:
                pre = {}

        def clean(v):
            return None if not v or str(v).lower().strip() in ("null", "none", "") else v

        to_address = clean(pre.get("to"))
        subject    = clean(pre.get("subject"))
        body       = clean(pre.get("body"))

        # ── Collect missing fields — batch into one question when possible ──
        missing = []
        if not to_address:
            missing.append("recipient")
        if not subject:
            missing.append("subject")
        if not body:
            missing.append("body")

        if len(missing) >= 2:
            field_labels = {
                "recipient": "who it's to",
                "subject": "the subject",
                "body": "what you want to say",
            }
            parts = [field_labels[f] for f in missing]
            if len(parts) == 2:
                question = f"I need {parts[0]} and {parts[1]}."
            else:
                question = f"I need {', '.join(parts[:-1])}, and {parts[-1]}."
            combined = await self._ask(question)
            extracted = self._llm(
                f"The user said: \"{combined}\"\n"
                "Extract email fields mentioned. Reply with ONLY valid JSON:\n"
                '{"to": "email or name or null", "subject": "subject or null", "body": "body or null"}'
            )
            try:
                parsed = json.loads(re.sub(r"```(?:json)?|```", "", extracted).strip())
            except Exception:
                parsed = {}
            if not to_address:
                to_address = clean(parsed.get("to"))
            if not subject:
                subject = clean(parsed.get("subject"))
            if not body:
                body = clean(parsed.get("body"))

        # ── Recipient ──
        if not to_address:
            raw_to = await self._ask("Who should I send this to?")
            to_address = await self._lookup_contact(raw_to)
            if not to_address:
                direct = re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw_to)
                if direct:
                    candidate = direct.group(0).rstrip(".,!?;:")
                    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", candidate):
                        to_address = candidate
                if not to_address:
                    to_address = self._extract_email_with_llm(raw_to)
            if not to_address:
                await self._speak("Couldn't recognize that email address. Please try again.")
                return
        else:
            # Resolve name to email if needed
            if "@" not in to_address:
                resolved = await self._lookup_contact(to_address)
                if resolved:
                    to_address = resolved
                else:
                    extracted_addr = self._extract_email_with_llm(to_address)
                    if extracted_addr:
                        to_address = extracted_addr
                    else:
                        raw_to = await self._ask(f"What's the email address for {to_address}?")
                        to_address = self._extract_email_with_llm(raw_to)
                        if not to_address:
                            await self._speak("Couldn't recognize that email address.")
                            return

        # ── Subject ──
        if not subject:
            subject = (await self._ask("What's the subject?")).strip().rstrip(".,!?;:")

        # ── Body ──
        if not body:
            body = (await self._ask("What would you like to say?")).strip()

        # ── Grammar-fix only: keep user's exact words, fix spelling/caps/grammar ──
        final_body = self._llm(
            f"Fix ONLY grammar, spelling, and capitalization in this text.\n"
            f"Do NOT rewrite, expand, or change the meaning. Keep it as close "
            f"to the original as possible. Output must be same length or shorter.\n\n"
            f"Original: \"{body}\"\n\n"
            "Reply with ONLY the corrected text."
        )
        self.worker.editor_logging_handler.info(
            f"Compose grammar fix: '{body}' → '{final_body}'"
        )

        try:
            _send_message(service, _make_message(to_address, subject, final_body))
            await self._speak("Done! Email sent.")
            # Save contact using the name from the original extraction (no extra LLM call)
            raw_name = clean(pre.get("to", "")) or ""
            if raw_name and "@" not in raw_name:
                await self._remember_contact(to_address, raw_name)
            else:
                await self._remember_contact(to_address)
        except HttpError as e:
            await self._speak("Something went wrong sending the email. Try again in a moment.")
            self.worker.editor_logging_handler.error(f"Send error: {e.reason}")

    #  Flow: Reply
    async def _flow_reply(self, service, raw_utterance: str = "",
                          msg: dict = None) -> None:
        prefilled_intent = ""

        if msg is not None:
            # Pre-resolved from list/read flow — extract inline reply content if any
            if raw_utterance:
                extracted = self._llm(
                    f"The user said: \"{raw_utterance}\"\n"
                    "Did they also state what they want to say in the reply?\n"
                    "Examples:\n"
                    "  'reply to danial thank you' → 'thank you'\n"
                    "  'reply to the invoice email saying payment sent' → 'payment sent'\n"
                    "  'reply to the invoice email' → NONE\n"
                    "  'yes' / 'reply' / 'reply to it' → NONE\n"
                    "Reply with the reply content only, or NONE."
                )
                if extracted.upper() != "NONE" and extracted:
                    prefilled_intent = extracted
        else:
            # Single LLM call: specificity + search hint + reply content in one shot
            parse_result = self._llm(
                f"The user said: \"{raw_utterance}\"\n"
                "Analyze this reply request. Reply with ONLY valid JSON:\n"
                '{"specific": true/false, "search_hint": "identifier or null", "reply_content": "content or null"}\n'
                "specific: true if they named a sender, subject, or described a particular email. "
                "false if vague like 'reply to email', 'reply to a mail', 'reply'.\n"
                "search_hint: the part identifying WHICH email, stripped of reply verb, filler words, and reply content. "
                "Examples: 'reply to Ahmed saying thanks' → 'Ahmed', 'get back to the invoice email' → 'invoice', "
                "'hit Sarah back that I'll be there' → 'Sarah'. null if vague.\n"
                "reply_content: what they want to say in the reply, or null if not stated. "
                "Examples: 'reply to Ahmed saying thanks' → 'thanks', 'reply to the invoice email' → null."
            ).strip()

            try:
                parsed = json.loads(re.sub(r"```(?:json)?|```", "", parse_result).strip())
            except Exception:
                parsed = {"specific": False, "search_hint": None, "reply_content": None}

            is_specific = parsed.get("specific", False)
            search_hint = parsed.get("search_hint") or ""
            reply_content = parsed.get("reply_content")

            self.worker.editor_logging_handler.info(
                f"Reply parse: '{raw_utterance}' → specific={is_specific}, "
                f"hint='{search_hint}', content='{reply_content}'"
            )

            if reply_content:
                prefilled_intent = reply_content

            if not is_specific:
                hint = await self._ask(
                    "Which email? You can say a name or subject."
                )
                raw_utterance = hint
                search_hint = hint

            # Try KV context first
            msg = self._resolve_from_context(search_hint or raw_utterance, service)
            if msg:
                self.worker.editor_logging_handler.info("Reply: resolved from KV context.")
            else:
                if not search_hint:
                    search_hint = raw_utterance
                msg = await self._resolve_email(service, hint=search_hint)

        if not msg:
            return

        headers = msg.get("payload", {}).get("headers", [])
        name, reply_to = _sender_display(msg)
        subject = _clean_subject(_get_header(headers, "Subject") or "no subject")
        msg_id = _get_header(headers, "Message-ID")
        thread = msg.get("threadId", "")
        original_body = self._clean_for_speech(_decode_body(msg))[:2000]

        # ── Collect reply intent ──
        while True:
            if prefilled_intent:
                intent_raw = prefilled_intent
                prefilled_intent = ""
            else:
                intent_raw = await self._ask(
                    f"Replying to {name}. What would you like to say?"
                )

            if not intent_raw.strip():
                await self._speak("Didn't catch that. What would you like to say?")
                continue
            break

        # ── Grammar-fix only: keep user's exact words, fix spelling/caps/grammar ──
        final_body = self._llm(
            f"Fix ONLY grammar, spelling, and capitalization in this text.\n"
            f"Do NOT rewrite, expand, or change the meaning. Keep it as close "
            f"to the original as possible.\n\n"
            f"Original: \"{intent_raw}\"\n\n"
            "Reply with ONLY the corrected text."
        )
        self.worker.editor_logging_handler.info(
            f"Reply grammar fix: '{intent_raw}' → '{final_body}'"
        )

        try:
            _send_message(service, _make_reply(reply_to, subject, final_body, thread, msg_id))
            await self._speak("Reply sent.")
            await self._remember_contact(reply_to, name)
        except HttpError as e:
            await self._speak("Something went wrong sending the reply.")
            self.worker.editor_logging_handler.error(f"Reply error: {e.reason}")

    #  Flow: Read Email
    async def _flow_read(self, service, raw_utterance: str = "") -> None:
        # LLM decides if the request targets a specific email or is a vague "read my email"
        specificity = self._llm(
            f"The user said: \"{raw_utterance}\"\n"
            "Does this mention a SPECIFIC email to read?\n"
            "SPECIFIC means they named a sender, subject keyword, or described a particular email.\n"
            "  Examples: 'read the email from Ahmed', 'open that invoice email', 'what did Sarah say'\n"
            "VAGUE means they just want to see their emails in general with no particular target.\n"
            "  Examples: 'read my email', 'check my inbox', 'pull up my mail', 'what's in my inbox',\n"
            "  'go through my emails', 'lemme see my messages', 'any new stuff'\n"
            "Reply with exactly one word: SPECIFIC or VAGUE."
        ).strip().upper()
        is_specific = "SPECIFIC" in specificity

        if not is_specific:
            unread_msgs = _list_messages(service, "is:unread in:inbox", max_results=5)
            if not unread_msgs:
                await self._speak("You have no unread emails.")
                return
            candidates = [_get_message(service, m["id"]) for m in unread_msgs]
            self._store_email_context(candidates)
            lines = []
            for i, m in enumerate(candidates, 1):
                hdrs = m.get("payload", {}).get("headers", [])
                subj = _clean_subject(_get_header(hdrs, "Subject") or "no subject")
                name, _ = _sender_display(m)
                lines.append(f"Number {i}, {subj}, from {name}.")
            await self._speak(
                f"You have {len(candidates)} unread emails. " + " ".join(lines)
            )
            pick_raw = await self._ask(f"Which one? Say a number, 1 to {len(candidates)}.")

            p_lower = pick_raw.lower()
            msg = None

            # "last" / "bottom" → last item
            if re.search(r'\b(last|bottom)\b', p_lower):
                msg = candidates[-1]

            if not msg:
                num_m = re.search(r'\b(?:no\.?|number|#)?\s*(\d+)\b', p_lower)
                if num_m:
                    idx = int(num_m.group(1)) - 1
                    if 0 <= idx < len(candidates):
                        msg = candidates[idx]
            if not msg:
                for word, num in _ORDINAL_MAP.items():
                    if re.search(r'\b' + word + r'\b', p_lower):
                        idx = num - 1
                        if 0 <= idx < len(candidates):
                            msg = candidates[idx]
                        break
            if not msg:
                # LLM fallback: match by sender name or subject keyword
                summary = "\n".join([
                    f"{i+1}. From: {_sender_display(c)[0]}, "
                    f"Subject: {_clean_subject(_get_header(c.get('payload',{}).get('headers',[]), 'Subject') or 'no subject')}"
                    for i, c in enumerate(candidates)
                ])
                pick_result = self._llm(
                    f"The user said: \"{pick_raw}\"\nEmails:\n{summary}\n"
                    "Which one? Reply with ONLY the 1-based index or NONE."
                )
                nums = re.findall(r"\d+", pick_result)
                if nums:
                    idx = max(0, min(int(nums[0]) - 1, len(candidates) - 1))
                    msg = candidates[idx]
            if not msg:
                await self._speak("Couldn't identify which email. Please try again.")
                return
        else:
            msg = await self._resolve_email(service, hint=raw_utterance)
            if not msg:
                return


        await self._read_full_message(service, msg)
        await self._handle_post_read_reply(service, msg)

    #  Flow: List Emails
    async def _flow_list(self, service, raw_utterance: str = "") -> None:
        # ── Timezone — try get_timezone(), fall back to IP geolocation ──
        user_tz_str = ""
        try:
            user_tz_str = self.capability_worker.get_timezone() or ""
        except Exception:
            pass

        if not user_tz_str:
            try:
                ip = self.worker.user_socket.client.host
                resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        user_tz_str = data.get("timezone", "")
            except Exception:
                pass

        try:
            now = datetime.now(ZoneInfo(user_tz_str)) if user_tz_str else datetime.now(timezone.utc)
        except Exception:
            now = datetime.now(timezone.utc)

        self.worker.editor_logging_handler.info(
            f"List emails: local time {now.strftime('%Y-%m-%d %H:%M %Z')} (tz={user_tz_str or 'UTC fallback'})"
        )

        # ── Intent classification — explicit examples so LLM doesn't misfire ──
        intent = self._llm(
            f"The user said: \"{raw_utterance}\"\n\n"
            "Classify which emails they want. Reply with ONLY one word from this list:\n\n"
            "today       — 'today', 'today's emails', 'emails today', 'this morning', 'tonight', 'what came in today'\n"
            "yesterday   — 'yesterday', 'yesterday's emails', 'last night'\n"
            "unread      — 'unread', 'new emails', 'what did I miss', 'haven't checked', 'anything I missed', 'anything new'\n"
            "recent      — 'recent', 'latest', 'last few', 'show me emails' (no time/filter)\n"
            "from_sender — 'from X', 'emails from X', 'X's emails'\n"
            "specific_date — a named date like 'March 5th', 'last Monday', 'on the 10th'\n"
            "unknown     — completely unclear\n\n"
            "Reply with ONE word only: today, yesterday, unread, recent, from_sender, specific_date, or unknown."
        ).lower().strip()

        self.worker.editor_logging_handler.info(f"List email intent: '{intent}' for utterance: '{raw_utterance}'")

        if intent == "unknown":
            choice = await self._ask(
                "Which emails? Like today's, unread, or from someone specific?"
            )
            intent = self._llm(
                f"The user said: \"{choice}\"\n"
                "Classify: today, yesterday, unread, recent, from_sender, specific_date\n"
                "Reply with ONE word."
            ).lower().strip()
            raw_utterance = choice

        # ── Build query ──
        today_str     = now.strftime("%Y/%m/%d")
        yesterday_str = (now - timedelta(days=1)).strftime("%Y/%m/%d")
        tomorrow_str  = (now + timedelta(days=1)).strftime("%Y/%m/%d")

        if intent == "today":
            # after: is inclusive of the date, before: is exclusive
            # Adding in:inbox avoids sent/spam/trash polluting results
            query = f"in:inbox after:{today_str} before:{tomorrow_str}"
            label = "today's"
            max_fetch = 25

        elif intent == "yesterday":
            query = f"in:inbox after:{yesterday_str} before:{today_str}"
            label = "yesterday's"
            max_fetch = 25

        elif intent == "unread":
            query = "is:unread in:inbox"
            label = "unread"
            max_fetch = 50

        elif intent == "from_sender":
            sender_hint = self._llm(
                f"The user said: \"{raw_utterance}\"\n"
                "Extract the sender name or email. Reply with ONLY that, or NONE."
            ).strip()
            if not sender_hint or sender_hint.upper() == "NONE":
                sender_hint = await self._ask("Emails from who?")
            query = f"from:{sender_hint}"
            label = f"emails from {sender_hint}"
            max_fetch = 20

        elif intent == "specific_date":
            query = self._llm(
                f"Today is {now.strftime('%Y-%m-%d')}. The user said: \"{raw_utterance}\"\n"
                "Convert to Gmail query using after: and before: operators.\n"
                "Format: in:inbox after:YYYY/MM/DD before:YYYY/MM/DD\n"
                "Examples:\n"
                "  'March 5th'   → in:inbox after:2026/03/05 before:2026/03/06\n"
                "  'last Monday' → in:inbox after:2026/03/16 before:2026/03/17\n"
                "Reply with ONLY the query string."
            ).strip()
            label = "emails from that date"
            max_fetch = 20

        else:  # recent
            query = "in:inbox"
            label = "recent"
            max_fetch = 5

        self.worker.editor_logging_handler.info(f"Gmail list query: '{query}' max_fetch={max_fetch}")

        messages = _list_messages(service, query, max_results=max_fetch)

        # ── Friendly empty state per intent ──
        if not messages:
            empty_msg = {
                "today":         "You have no emails in your inbox today.",
                "yesterday":     "You have no emails from yesterday.",
                "unread":        "You have no unread emails.",
                "from_sender":   f"No emails found from {sender_hint if intent == 'from_sender' else 'that person'}.",
                "specific_date": "No emails found for that date.",
            }.get(intent, "No emails found.")
            await self._speak(empty_msg)
            return

        count = len(messages)
        my_email = ""
        try:
            my_email = service.users().getProfile(userId="me").execute().get("emailAddress", "").lower()
        except Exception:
            pass

        BATCH = 5
        offset = 0
        all_shown: list = []

        def _pick_from_shown(utterance: str) -> Optional[dict]:
            if not all_shown:
                return None
            u_lower = utterance.lower()

            # "last" / "bottom" → last shown item
            if re.search(r'\b(last|bottom)\b', u_lower):
                return all_shown[-1]

            # Fast path 1: "no 2", "number 3", "#4", plain digits
            num_m = re.search(r'\b(?:no\.?|number|#)?\s*(\d+)\b', u_lower)
            if num_m:
                idx = int(num_m.group(1)) - 1
                if 0 <= idx < len(all_shown):
                    return all_shown[idx]

            # Fast path 2: ordinal words ("second", "third", …)
            for word, num in _ORDINAL_MAP.items():
                if re.search(r'\b' + word + r'\b', u_lower):
                    idx = num - 1
                    if 0 <= idx < len(all_shown):
                        return all_shown[idx]
                    break

            # Fallback: LLM matches by name / subject keyword
            summary = "\n".join([
                f"{i+1}. From: {_sender_display(m)[0]}, "
                f"Subject: {_clean_subject(_get_header(m.get('payload', {}).get('headers', []), 'Subject') or 'no subject')}"
                for i, m in enumerate(all_shown)
            ])
            pick = self._llm(
                f"The user said: \"{utterance}\"\n"
                f"Emails:\n{summary}\n"
                "Which one? Match by name or subject keyword.\n"
                "Reply with ONLY the 1-based index or NONE."
            )
            nums = re.findall(r"\d+", pick)
            if nums:
                idx = max(0, min(int(nums[0]) - 1, len(all_shown) - 1))
                return all_shown[idx]
            return None

        while True:
            batch_meta = messages[offset:offset + BATCH]
            if not batch_meta:
                await self._speak("That's all the emails.")
                break

            full_batch = [_get_message(service, m["id"]) for m in batch_meta]
            all_shown.extend(full_batch)
            self._store_email_context(all_shown)

            if offset == 0:
                await self._speak(
                    f"You have {count} {label} {'email' if count == 1 else 'emails'}. "
                    f"Here {'is' if len(full_batch) == 1 else 'are'} the first {len(full_batch)}."
                )
            else:
                await self._speak(f"Emails {offset + 1} to {offset + len(full_batch)}.")

            # Build all subjects into one speech string (faster, more natural)
            lines = []
            for i, m in enumerate(full_batch, offset + 1):
                headers = m.get("payload", {}).get("headers", [])
                subj = _clean_subject(_get_header(headers, "Subject") or "no subject")
                sender = _get_header(headers, "From") or ""
                addr_m = re.search(r"<([^>]+)>", sender)
                sender_addr = addr_m.group(1).lower() if addr_m else sender.lower()
                display = "you" if (my_email and sender_addr == my_email) else \
                          (re.sub(r"<[^>]+>", "", sender).strip().strip('"') or sender)
                lines.append(f"Number {i}, {subj}, from {display}.")
            await self._speak(" ".join(lines))

            has_more = (offset + BATCH) < count
            more_hint = ", show more" if has_more else ""
            follow_up_raw = await self._ask(
                f"Want to read one, reply{more_hint}, or are you all set?"
            )

            follow_up_intent = self._llm(
                f"The user said: \"{follow_up_raw}\"\n"
                "READ: open/read an email in full\n"
                "REPLY: reply to a specific email\n"
                "MARK_READ: mark one or all as read\n"
                "COMPOSE: write a new email\n"
                "MORE: show more / next page\n"
                "DONE: done, stop, nothing\n"
                "Reply with ONE word."
            ).upper()

            if follow_up_intent == "MORE":
                if has_more:
                    offset += BATCH
                    continue
                await self._speak("No more emails to show.")
                break

            elif follow_up_intent == "READ":
                target = _pick_from_shown(follow_up_raw)
                if not target:
                    pick_raw = await self._ask(
                        f"Which one? Say a number, 1 to {len(all_shown)}."
                    )
                    target = _pick_from_shown(pick_raw)
                    if not target:
                        target = self._resolve_from_context(pick_raw, service)
                if target:
                    await self._read_full_message(service, target)
                    await self._handle_post_read_reply(service, target)
                break

            elif follow_up_intent == "REPLY":
                target = _pick_from_shown(follow_up_raw)
                await self._flow_reply(service, follow_up_raw, msg=target)
                break

            elif follow_up_intent == "MARK_READ":
                scope = self._llm(
                    f"The user said: \"{follow_up_raw}\"\n"
                    f"There are {len(all_shown)} emails shown.\n"
                    "Mark ALL or a specific one? Reply ALL or a 1-based number."
                ).upper()
                if scope == "ALL":
                    for m in all_shown:
                        _mark_read(service, m["id"])
                    await self._speak(f"Marked all {len(all_shown)} as read.")
                else:
                    nums = re.findall(r"\d+", scope)
                    idx = max(0, min(int(nums[0]) - 1, len(all_shown) - 1)) if nums else 0
                    _mark_read(service, all_shown[idx]["id"])
                    await self._speak("Marked as read.")
                break

            elif follow_up_intent == "COMPOSE":
                await self._flow_compose(service, follow_up_raw)
                break

            else:  # DONE
                break

    #  Entry point
    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        first_msg = await self.capability_worker.wait_for_complete_transcription()

        token = self.capability_worker.get_token("google")
        if not token:
            await self._speak(
                "Your Google account isn't linked yet. "
                "Head to Settings, then Linked Accounts to connect it."
            )
            self.capability_worker.resume_normal_flow()
            return
 
        try:
            service = _build_gmail_service(token)
            self.worker.editor_logging_handler.info("Gmail service ready.")
        except Exception as e:
            await self._speak("Couldn't connect to Gmail. Try again in a moment.")
            self.worker.editor_logging_handler.error(f"Gmail service build error: {e}")
            self.capability_worker.resume_normal_flow()
            return

        context_prefix = ""
        try:
            history = self.capability_worker.get_full_message_history()
            if history:
                recent = [m for m in history[-6:] if isinstance(m.get("content"), str)]
                if recent:
                    context_prefix = "Recent conversation:\n" + "\n".join([
                        f"{m.get('role', '')}: {m['content'][:120]}" for m in recent
                    ]) + "\n\n"
        except Exception:
            pass

        # LLM-based intent classification — no hardcoded keyword gates
        intent = self._llm(
            f"{context_prefix}"
            f"Classify this Gmail intent: '{first_msg}'.\n"
            "COMPOSE — user wants to send, write, shoot, or fire off a new email\n"
            "REPLY   — user wants to reply, respond, get back to, answer, or hit someone back\n"
            "READ    — user wants to read, open, hear, or know what an email says\n"
            "LIST    — user wants to list, show, check, see what came in, or know about unread/new emails\n"
            "UNKNOWN — not related to email, too vague to tell, or just filler like 'okay', 'hey', 'hmm'\n"
            "Reply with exactly one word: COMPOSE, REPLY, READ, LIST, or UNKNOWN."
        ).upper()

        routing_msg = first_msg

        if intent == "UNKNOWN":
            await self._speak("Gmail ready. What would you like to do?")
            while True:
                intent_raw = (await self.capability_worker.user_response()).strip()
                routing_msg = intent_raw
                intent = self._llm(
                    f"Classify this Gmail intent: '{intent_raw}'.\n"
                    "COMPOSE — send / shoot / write / fire off a new email to someone\n"
                    "REPLY   — reply / respond / get back to / answer / hit back\n"
                    "READ    — read / open / what does X say / read it to me\n"
                    "LIST    — list / show / check / anything new / what came in / any unread\n"
                    "UNKNOWN — unclear, unrelated, or just a filler word like 'okay', 'yes', 'hmm'\n"
                    "Reply with exactly one word: COMPOSE, REPLY, READ, LIST, or UNKNOWN."
                ).upper()
                if intent != "UNKNOWN":
                    break
                await self._speak(
                    "Sorry, I didn't catch that. "
                    "You can send, reply, read, or check your emails."
                )

        try:
            if intent == "COMPOSE":
                await self._flow_compose(service, routing_msg)
            elif intent == "REPLY":
                await self._flow_reply(service, routing_msg)
            elif intent == "LIST":
                await self._flow_list(service, routing_msg)
            elif intent == "READ":
                await self._flow_read(service, routing_msg)
            else:
                await self._speak(
                    "Not sure what you'd like to do. "
                    "You can compose, reply, read, or list emails."
                )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Gmail unhandled error: {e}")
            await self._speak("Something went wrong. Please try again.")
        finally:
            self.capability_worker.resume_normal_flow()
