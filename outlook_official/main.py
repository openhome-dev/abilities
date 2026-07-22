import json
import re
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# CONFIG
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
CONTACTS_FILE = "outlook_contacts.json"


EMAIL_SYSTEM = (
    "You are an intelligent voice email assistant running on OpenHome. "
    "The user is speaking — all your output will be read aloud. "
    "Keep responses concise and natural for speech, under 2 sentences and 25 words. "
    "Never use markdown, bullet points, numbered lists, emojis, URLs, or raw email addresses. "
    "When drafting emails, be professional yet conversational."
)

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



def _graph_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _graph_get(token: str, endpoint: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{GRAPH_BASE_URL}{endpoint}",
        headers=_graph_headers(token),
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _graph_post(token: str, endpoint: str, body: dict = None) -> dict:
    resp = requests.post(
        f"{GRAPH_BASE_URL}{endpoint}",
        headers=_graph_headers(token),
        json=body or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _graph_patch(token: str, endpoint: str, body: dict = None) -> dict:
    resp = requests.patch(
        f"{GRAPH_BASE_URL}{endpoint}",
        headers=_graph_headers(token),
        json=body or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}



# -- Mail operations --
def _list_messages(token: str, query: str = None, top: int = 10,
                   folder: str = "inbox", filter_str: str = None) -> list:
    params = {
        "$top": top,
        "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,body",
    }
    if query:
        # $search can't be combined with $orderby in Graph API
        # Use /me/messages (not folder-scoped) for search — more reliable
        params["$search"] = f'"{query}"'
        endpoint = "/me/messages"
    elif filter_str:
        params["$filter"] = filter_str
        params["$orderby"] = "receivedDateTime desc"
        endpoint = f"/me/mailFolders/{folder}/messages"
    else:
        params["$orderby"] = "receivedDateTime desc"
        endpoint = f"/me/mailFolders/{folder}/messages"
    data = _graph_get(token, endpoint, params)
    return data.get("value", [])


def _get_message(token: str, msg_id: str) -> dict:
    return _graph_get(
        token, f"/me/messages/{msg_id}",
        {"$select": "id,subject,from,toRecipients,receivedDateTime,isRead,body,bodyPreview,conversationId"},
    )


def _normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def _is_outlook_mailbox(email: Optional[str]) -> bool:
    email_lower = _normalize_email(email)
    return email_lower.endswith("@outlook.com") or email_lower.endswith("@hotmail.com") or email_lower.endswith("@live.com")


def _graph_recipient(email: str) -> dict:
    return {"emailAddress": {"address": email}}


def _get_sender_email(token: str) -> str:
    """Resolve the best sender identity for outbound Outlook mail.

    Prefer the mailbox's primary Outlook-family alias if one exists.
    This avoids falling back to a Gmail sign-in alias when the account
    actually has an Outlook/Hotmail/Live mailbox address.
    """
    account_data = _graph_get(token, "/me", {
        "$select": "mail,userPrincipalName,proxyAddresses"
    })

    # proxyAddresses contains aliases like "SMTP:user@outlook.com", "smtp:user@gmail.com"
    proxy = account_data.get("proxyAddresses") or []
    primary_outlook = []
    other_outlook = []
    primary_other = []
    other_candidates = []

    for addr in proxy:
        clean = addr.replace("SMTP:", "").replace("smtp:", "").strip()
        if not clean:
            continue
        is_primary = addr.startswith("SMTP:")
        is_outlook = _is_outlook_mailbox(clean)

        if is_primary and is_outlook:
            primary_outlook.append(clean)
        elif is_outlook:
            other_outlook.append(clean)
        elif is_primary:
            primary_other.append(clean)
        else:
            other_candidates.append(clean)

    account_mail = account_data.get("mail", "").strip()
    account_upn = account_data.get("userPrincipalName", "").strip()

    candidates = []
    candidates.extend(primary_outlook)
    candidates.extend(other_outlook)
    if _is_outlook_mailbox(account_mail):
        candidates.append(account_mail)
    if _is_outlook_mailbox(account_upn):
        candidates.append(account_upn)
    candidates.extend(primary_other)
    candidates.extend(other_candidates)
    candidates.extend([account_mail, account_upn])

    seen = set()
    for candidate in candidates:
        normalized = _normalize_email(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            return candidate.strip()
    return ""


def _apply_sender_identity(token: str, draft_id: str, sender_email: str = None) -> None:
    if not sender_email:
        return
    sender = _graph_recipient(sender_email)
    _graph_patch(
        token,
        f"/me/messages/{draft_id}",
        {"from": sender, "replyTo": [sender]},
    )


def _send_message(token: str, to: str, subject: str, body: str,
                  sender_email: str = None) -> dict:
    draft = _graph_post(token, "/me/messages", {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [_graph_recipient(to)],
    })
    draft_id = draft.get("id")
    if not draft_id:
        raise Exception("Microsoft Graph did not return a draft id for the new email.")
    _apply_sender_identity(token, draft_id, sender_email)
    _graph_post(token, f"/me/messages/{draft_id}/send")
    return {}


def _send_reply(token: str, msg_id: str, body: str,
                sender_email: str = None) -> dict:
    draft = _graph_post(token, f"/me/messages/{msg_id}/createReply", {"comment": body})
    draft_id = draft.get("id")
    if not draft_id:
        raise Exception("Microsoft Graph did not return a draft id for the reply.")
    _apply_sender_identity(token, draft_id, sender_email)
    _graph_post(token, f"/me/messages/{draft_id}/send")
    return {}


def _is_send_as_denied(error: Exception) -> bool:
    return "ErrorSendAsDenied" in str(error)



# -- Helpers --
def _sender_display(msg: dict) -> tuple:
    from_obj = msg.get("from", {}).get("emailAddress", {})
    name = from_obj.get("name", "")
    email = from_obj.get("address", "")
    return name or email, email


def _clean_subject(subject: str) -> str:
    subject = re.sub(r"\[openhome[^\]]*\]", "", subject or "")
    subject = re.sub(r"\(PR #\d+\)", "", subject)
    subject = re.sub(r"#\d+", "", subject)
    subject = re.sub(r"\s{2,}", " ", subject)
    return subject.strip() or "no subject"


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>|</?p>|</?div>", "\n", text or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;|&apos;", "'", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _body_text(msg: dict) -> str:
    body = msg.get("body", {})
    content = body.get("content", "")
    if body.get("contentType", "").lower() == "html":
        return _strip_html(content)
    return content.strip()


class OutlookOfficialCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _sender_email: Optional[str] = None

    # Do not change following tag of register capability
    #{{register capability}}

    # -------------------- LLM shorthand --------------------
    def _llm(self, prompt: str, history: list = None) -> str:
        return self.capability_worker.text_to_text_response(
            prompt,
            history=history or [],
            system_prompt=EMAIL_SYSTEM,
        ).strip()

    # -------------------- Voice helpers --------------------
    async def _speak(self, text: str) -> None:
        await self.capability_worker.speak(text)

    async def _ask(self, question: str) -> str:
        await self.capability_worker.speak(question)
        return (await self.capability_worker.user_response()).strip()

    # -------------------- KV upsert helper --------------------
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

    # -------------------- Persistent contact memory --------------------
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
        name = name.strip().rstrip(".,!?;:") if name else ""
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

    # -------------------- Email context (KV session memory) --------------------
    def _store_email_context(self, emails: list) -> None:
        context = []
        for msg in emails:
            name, sender_email = _sender_display(msg)
            context.append({
                "id": msg.get("id"),
                "conversationId": msg.get("conversationId"),
                "sender_name": name,
                "sender_email": sender_email,
                "subject": _clean_subject(msg.get("subject", "")),
            })
        self._upsert_key("recent_emails_context", context)

    def _resolve_from_context(self, hint: str, token: str) -> Optional[dict]:
        try:
            context = self.capability_worker.get_single_key("recent_emails_context")
            if not context or not isinstance(context, list):
                return None
        except Exception:
            return None

        hint_lower = hint.lower()

        if re.search(r'\b(last|bottom)\b', hint_lower) and context:
            try:
                return _get_message(token, context[-1]["id"])
            except Exception:
                pass

        num_m = re.search(r'\b(?:no\.?|number|#)\s*(\d+)\b', hint_lower)
        if num_m:
            idx = int(num_m.group(1)) - 1
            if 0 <= idx < len(context):
                try:
                    return _get_message(token, context[idx]["id"])
                except Exception:
                    pass

        for word, num in _ORDINAL_MAP.items():
            if re.search(r'\b' + word + r'\b', hint_lower):
                idx = num - 1
                if 0 <= idx < len(context):
                    try:
                        return _get_message(token, context[idx]["id"])
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
                    return _get_message(token, context[idx]["id"])
                except Exception as e:
                    self.worker.editor_logging_handler.error(f"Context fetch error: {e}")
        return None

    # -------------------- Email resolution --------------------
    async def _resolve_email(self, token: str, hint: str = "") -> Optional[dict]:
        if not hint:
            hint = await self._ask(
                "Which email? Say the sender, subject, or a keyword."
            )

        ctx = self._resolve_from_context(hint, token)
        if ctx:
            self.worker.editor_logging_handler.info("Resolved from KV context.")
            return ctx

        query = self._llm(
            f"The user described an email: \"{hint}\"\n"
            "Extract the most relevant search keyword or phrase for Microsoft Graph $search.\n"
            "Examples:\n"
            "  'Eid holidays email'         → Eid holidays\n"
            "  'email from Ahmed'           → Ahmed\n"
            "  'PR review email from danial'→ danial PR\n"
            "  'invoice email'              → invoice\n"
            "Reply with ONLY the search term."
        )
        self.worker.editor_logging_handler.info(f"Outlook search query: '{query}'")
        messages = _list_messages(token, query=query, top=5)

        if not messages:
            hint = await self._ask(
                "Couldn't find that one. Try the sender's name or the subject?"
            )
            query2 = self._llm(
                f"The user described an email: \"{hint}\"\n"
                "Extract search keywords. Reply with ONLY the keywords."
            )
            messages = _list_messages(token, query=query2, top=5)
            if not messages:
                await self._speak("Still couldn't find any matching emails.")
                return None

        if len(messages) == 1:
            return messages[0]

        self._store_email_context(messages)

        preselect = self._llm(
            f"The user said: \"{hint}\"\n"
            f"Search returned {len(messages)} results.\n"
            "If they specified an ordinal or precise subject keyword, give 1-based index.\n"
            "If only a sender name with no other detail, reply NONE.\n"
            "Reply with ONLY the index or NONE."
        )
        nums = re.findall(r"\d+", preselect)
        if nums:
            idx = max(0, min(int(nums[0]) - 1, len(messages) - 1))
            return messages[idx]

        shown = messages[:3]
        options = ". ".join([
            f"Number {i+1}, from {_sender_display(c)[0]}, "
            f"about {_clean_subject(c.get('subject', ''))}"
            for i, c in enumerate(shown)
        ])
        await self._speak(f"I found {len(messages)} matching emails. {options}.")
        pick_raw = await self._ask(f"Which one? Say a number, 1 to {len(shown)}.")

        pick_lower = pick_raw.lower()
        direct_idx = None
        if re.search(r'\b(last|bottom)\b', pick_lower):
            direct_idx = len(messages) - 1
        else:
            for word, i in _ORDINAL_MAP_ZERO.items():
                if re.search(r'\b' + word + r'\b', pick_lower):
                    direct_idx = i
                    break
        if direct_idx is None:
            num_m2 = re.search(r'\b(?:no\.?|number|#)?\s*(\d+)\b', pick_lower)
            if num_m2:
                direct_idx = int(num_m2.group(1)) - 1
        if direct_idx is not None and 0 <= direct_idx < len(messages):
            return messages[direct_idx]

        pick_result = self._llm(
            f"The user said: \"{pick_raw}\". There are {len(messages)} options.\n"
            "Reply with ONLY the integer of the chosen option."
        )
        nums2 = re.findall(r"\d+", pick_result)
        idx = max(0, min(int(nums2[0]) - 1 if nums2 else 0, len(messages) - 1))
        return messages[idx]

    # -------------------- Text cleaning --------------------
    def _clean_for_speech(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"https?://\S+|www\.\S+", "", text)
        text = re.sub(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
            "an email address", text,
        )
        text = re.sub(r"—\s*Reply to this email directly.*", "", text, flags=re.DOTALL)
        text = re.sub(r"^[\-=_]{3,}\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"#{1,6}\s+", "", text)
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
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
            "icloud.com": "icloud dot com", "live.com": "live dot com",
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
    async def _read_full_message(self, token: str, msg: dict) -> None:
        name, _ = _sender_display(msg)
        subject = _clean_subject(msg.get("subject", ""))
        body = self._clean_for_speech(_body_text(msg))

        parts = [f"{subject}, from {name}."]
        parts.append(
            self._summarize_for_speech(body) if body
            else "Looks like there's nothing in this one."
        )

        received = msg.get("receivedDateTime", "")
        if received:
            try:
                dt = datetime.fromisoformat(received.replace("Z", "+00:00"))
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
        self._store_email_context([msg])

    # Shared: handle post-read reply decision
    async def _handle_post_read_reply(self, token: str, msg: dict) -> None:
        post_raw = await self._ask("Want to reply or move on?")
        decision = self._llm(
            f"The user said: \"{post_raw}\"\n"
            "Classify AND extract in one step. Reply with ONLY valid JSON:\n"
            '{"action": "SEND|REPLY|NO", "content": "extracted reply text or null"}\n'
            "SEND = they stated reply content directly (e.g. 'got it', 'yeah I'll be there').\n"
            "REPLY = said yes/sure but gave NO specific content.\n"
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
            try:
                content = self._llm(
                    f"Fix ONLY grammar, spelling, and capitalization in this text.\n"
                    f"Do NOT rewrite, expand, or change the meaning. Keep it as close "
                    f"to the original as possible.\n\n"
                    f"Original: \"{content}\"\n\n"
                    "Reply with ONLY the corrected text."
                )
                _send_reply(token, msg["id"], content, sender_email=self._sender_email)
                await self._speak("Reply sent.")
                name, email_addr = _sender_display(msg)
                await self._remember_contact(email_addr, name)
            except Exception as e:
                if _is_send_as_denied(e):
                    await self._speak("Outlook couldn't send from that address. You may need to update your account settings.")
                else:
                    await self._speak("Something went wrong sending the reply.")
                self.worker.editor_logging_handler.error(f"Reply error: {e}")
        elif action == "REPLY":
            await self._flow_reply(token, raw_utterance=post_raw, msg=msg)

    # Flow: List Emails
    async def _flow_list(self, token: str, raw_utterance: str = "") -> None:
        now = datetime.now(timezone.utc)

        intent = self._llm(
            f"The user said: \"{raw_utterance}\"\n\n"
            "Classify which emails they want. Reply with ONLY one word from this list:\n\n"
            "today       — 'today', 'what came in today', 'today's stuff', 'this morning'\n"
            "yesterday   — 'yesterday', 'what'd I get yesterday', 'yesterday's stuff'\n"
            "unread      — 'unread', 'new emails', 'what'd I miss', 'anything new', 'what do I got'\n"
            "recent      — 'recent', 'latest', 'last few', 'pull up my mail', 'lemme see'\n"
            "from_sender — 'from X', 'emails from X', 'anything from X'\n"
            "unknown     — completely unclear\n\n"
            "Reply with ONE word only: today, yesterday, unread, recent, from_sender, or unknown."
        ).lower().strip()

        self.worker.editor_logging_handler.info(
            f"Outlook list intent: '{intent}' for utterance: '{raw_utterance}'"
        )

        if intent == "unknown":
            choice = await self._ask(
                "Which emails? Like today's, unread, or from someone specific?"
            )
            intent = self._llm(
                f"The user said: \"{choice}\"\n"
                "Classify: today, yesterday, unread, recent, from_sender\n"
                "Reply with ONE word."
            ).lower().strip()
            raw_utterance = choice

        sender_hint = ""
        if intent == "today":
            today_str = now.strftime("%Y-%m-%dT00:00:00Z")
            filter_str = f"receivedDateTime ge {today_str}"
            label = "today's"
            messages = _list_messages(token, filter_str=filter_str, top=25)
        elif intent == "yesterday":
            yesterday_start = (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
            today_start = now.strftime("%Y-%m-%dT00:00:00Z")
            filter_str = f"receivedDateTime ge {yesterday_start} and receivedDateTime lt {today_start}"
            label = "yesterday's"
            messages = _list_messages(token, filter_str=filter_str, top=25)
        elif intent == "unread":
            filter_str = "isRead eq false"
            label = "unread"
            messages = _list_messages(token, filter_str=filter_str, top=50)
        elif intent == "from_sender":
            sender_hint = self._llm(
                f"The user said: \"{raw_utterance}\"\n"
                "Extract the sender name or email. Reply with ONLY that, or NONE."
            ).strip()
            if not sender_hint or sender_hint.upper() == "NONE":
                sender_hint = await self._ask("Emails from who?")
            label = f"emails from {sender_hint}"
            messages = _list_messages(token, query=sender_hint, top=20)
        else:  # recent
            label = "recent"
            messages = _list_messages(token, top=5)

        if not messages:
            empty_msg = {
                "today": "You have no emails in your inbox today.",
                "yesterday": "You have no emails from yesterday.",
                "unread": "You have no unread emails.",
                "from_sender": f"No emails found from {sender_hint or 'that person'}.",
            }.get(intent, "No emails found.")
            await self._speak(empty_msg)
            return

        count = len(messages)
        BATCH = 5
        offset = 0
        all_shown: list = []

        def _pick_from_shown(utterance: str) -> Optional[dict]:
            if not all_shown:
                return None
            u_lower = utterance.lower()
            if re.search(r'\b(last|bottom)\b', u_lower):
                return all_shown[-1]
            num_m = re.search(r'\b(?:no\.?|number|#)?\s*(\d+)\b', u_lower)
            if num_m:
                idx = int(num_m.group(1)) - 1
                if 0 <= idx < len(all_shown):
                    return all_shown[idx]
            for word, num in _ORDINAL_MAP.items():
                if re.search(r'\b' + word + r'\b', u_lower):
                    idx = num - 1
                    if 0 <= idx < len(all_shown):
                        return all_shown[idx]
                    break
            summary = "\n".join([
                f"{i+1}. From: {_sender_display(m)[0]}, Subject: {_clean_subject(m.get('subject', ''))}"
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
            batch = messages[offset:offset + BATCH]
            if not batch:
                await self._speak("That's all the emails.")
                break

            all_shown.extend(batch)
            self._store_email_context(all_shown)

            if offset == 0:
                await self._speak(
                    f"You have {count} {label} {'email' if count == 1 else 'emails'}. "
                    f"Here {'is' if len(batch) == 1 else 'are'} the first {len(batch)}."
                )
            else:
                await self._speak(f"Emails {offset + 1} to {offset + len(batch)}.")

            lines = []
            for i, m in enumerate(batch, offset + 1):
                subj = _clean_subject(m.get("subject", ""))
                display, _ = _sender_display(m)
                lines.append(f"Number {i}, {subj}, from {display}.")
            await self._speak(" ".join(lines))

            has_more = (offset + BATCH) < count
            follow_up_raw = await self._ask(
                "Wanna dig into any of these?"
            )

            follow_up_intent = self._llm(
                f"The user said: \"{follow_up_raw}\"\n"
                "READ: open/read an email in full\n"
                "REPLY: reply to a specific email\n"
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
                        target = self._resolve_from_context(pick_raw, token)
                if target:
                    full = _get_message(token, target["id"])
                    await self._read_full_message(token, full)
                    await self._handle_post_read_reply(token, full)
                break

            elif follow_up_intent == "REPLY":
                target = _pick_from_shown(follow_up_raw)
                if target:
                    full = _get_message(token, target["id"])
                    await self._flow_reply(token, follow_up_raw, msg=full)
                else:
                    await self._flow_reply(token, follow_up_raw)
                break

            elif follow_up_intent == "COMPOSE":
                await self._flow_compose(token, follow_up_raw)
                break

            else:  # DONE
                break

    # Flow: Read Email
    async def _flow_read(self, token: str, raw_utterance: str = "") -> None:
        specificity = self._llm(
            f"The user said: \"{raw_utterance}\"\n"
            "Does this mention a SPECIFIC email to read?\n"
            "SPECIFIC means they named a sender, subject keyword, or described a particular email.\n"
            "VAGUE means they just want to see their emails in general.\n"
            "Reply with exactly one word: SPECIFIC or VAGUE."
        ).strip().upper()
        is_specific = "SPECIFIC" in specificity

        if not is_specific:
            unread = _list_messages(token, filter_str="isRead eq false", top=5)
            if not unread:
                await self._speak("You have no unread emails.")
                return

            self._store_email_context(unread)
            lines = []
            for i, m in enumerate(unread, 1):
                subj = _clean_subject(m.get("subject", ""))
                name, _ = _sender_display(m)
                lines.append(f"Number {i}, {subj}, from {name}.")
            await self._speak(
                f"You have {len(unread)} unread emails. " + " ".join(lines)
            )
            pick_raw = await self._ask(f"Which one? Say a number, 1 to {len(unread)}.")

            p_lower = pick_raw.lower()
            msg = None

            if re.search(r'\b(last|bottom)\b', p_lower):
                msg = unread[-1]
            if not msg:
                num_m = re.search(r'\b(?:no\.?|number|#)?\s*(\d+)\b', p_lower)
                if num_m:
                    idx = int(num_m.group(1)) - 1
                    if 0 <= idx < len(unread):
                        msg = unread[idx]
            if not msg:
                for word, num in _ORDINAL_MAP.items():
                    if re.search(r'\b' + word + r'\b', p_lower):
                        idx = num - 1
                        if 0 <= idx < len(unread):
                            msg = unread[idx]
                        break
            if not msg:
                summary = "\n".join([
                    f"{i+1}. From: {_sender_display(c)[0]}, "
                    f"Subject: {_clean_subject(c.get('subject', ''))}"
                    for i, c in enumerate(unread)
                ])
                pick_result = self._llm(
                    f"The user said: \"{pick_raw}\"\nEmails:\n{summary}\n"
                    "Which one? Reply with ONLY the 1-based index or NONE."
                )
                nums = re.findall(r"\d+", pick_result)
                if nums:
                    idx = max(0, min(int(nums[0]) - 1, len(unread) - 1))
                    msg = unread[idx]
            if not msg:
                await self._speak("Couldn't find that one. Try again?")
                return
        else:
            msg = await self._resolve_email(token, hint=raw_utterance)
            if not msg:
                return

        full = _get_message(token, msg["id"])
        await self._read_full_message(token, full)
        await self._handle_post_read_reply(token, full)

    # Flow: Compose / Send
    async def _flow_compose(self, token: str, raw_utterance: str = "") -> None:
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
        subject = clean(pre.get("subject"))
        body = clean(pre.get("body"))

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

        # Recipient
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
                await self._speak("Didn't catch that address. Try again?")
                return
        else:
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
                            await self._speak("Didn't catch that address.")
                            return

        # Subject
        if not subject:
            subject = (await self._ask("What's the subject?")).strip().rstrip(".,!?;:")

        # Body
        if not body:
            body = (await self._ask("What would you like to say?")).strip()

        # Fix grammar, spelling, and capitalization in subject and body
        final_subject = self._llm(
            f"Fix ONLY grammar, spelling, and capitalization in this email subject line.\n"
            f"Use proper title case. Do NOT rewrite or change the meaning.\n\n"
            f"Original: \"{subject}\"\n\n"
            "Reply with ONLY the corrected subject."
        )
        final_body = self._llm(
            f"Fix ONLY grammar, spelling, and capitalization in this text.\n"
            f"Do NOT rewrite, expand, or change the meaning. Keep it as close "
            f"to the original as possible. Output must be same length or shorter.\n\n"
            f"Original: \"{body}\"\n\n"
            "Reply with ONLY the corrected text."
        )
        self.worker.editor_logging_handler.info(
            f"Compose grammar fix: subject '{subject}' → '{final_subject}' | body '{body}' → '{final_body}'"
        )

        try:
            _send_message(token, to_address, final_subject, final_body,
                         sender_email=self._sender_email)
            await self._speak("Done! Email sent.")
            raw_name = clean(pre.get("to", "")) or ""
            if raw_name and "@" not in raw_name:
                await self._remember_contact(to_address, raw_name)
            else:
                await self._remember_contact(to_address)
        except Exception as e:
            if _is_send_as_denied(e):
                await self._speak("Outlook couldn't send from that address. You may need to update your account settings.")
            else:
                await self._speak("Couldn't send that. Give it another shot.")
            self.worker.editor_logging_handler.error(f"Send error: {e}")

    # Flow: Reply
    async def _flow_reply(self, token: str, raw_utterance: str = "",
                          msg: dict = None) -> None:
        prefilled_intent = ""

        if msg is not None:
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
            parse_result = self._llm(
                f"The user said: \"{raw_utterance}\"\n"
                "Analyze this reply request. Reply with ONLY valid JSON:\n"
                '{"specific": true/false, "search_hint": "identifier or null", "reply_content": "content or null"}\n'
                "specific: true if they named a sender, subject, or described a particular email.\n"
                "search_hint: the part identifying WHICH email. null if vague.\n"
                "reply_content: what they want to say in the reply, or null if not stated."
            ).strip()

            try:
                parsed = json.loads(re.sub(r"```(?:json)?|```", "", parse_result).strip())
            except Exception:
                parsed = {"specific": False, "search_hint": None, "reply_content": None}

            is_specific = parsed.get("specific", False)
            search_hint = parsed.get("search_hint") or ""
            reply_content = parsed.get("reply_content")

            if reply_content:
                prefilled_intent = reply_content

            if not is_specific:
                hint = await self._ask(
                    "Which email? You can say a name or subject."
                )
                raw_utterance = hint
                search_hint = hint

            msg = self._resolve_from_context(search_hint or raw_utterance, token)
            if msg:
                self.worker.editor_logging_handler.info("Reply: resolved from KV context.")
            else:
                if not search_hint:
                    search_hint = raw_utterance
                msg = await self._resolve_email(token, hint=search_hint)

        if not msg:
            return

        # Ensure we have full message data
        if "body" not in msg or not msg.get("body"):
            msg = _get_message(token, msg["id"])

        name, reply_to = _sender_display(msg)
        subject = _clean_subject(msg.get("subject", ""))

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

        # Grammar-fix only
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
            _send_reply(token, msg["id"], final_body, sender_email=self._sender_email)
            await self._speak("Reply sent.")
            await self._remember_contact(reply_to, name)
        except Exception as e:
            if _is_send_as_denied(e):
                await self._speak("Outlook couldn't send from that address. You may need to update your account settings.")
            else:
                await self._speak("Something went wrong sending the reply.")
            self.worker.editor_logging_handler.error(f"Reply error: {e}")

    # Entry point
    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        first_msg = await self.capability_worker.wait_for_complete_transcription()

        # Get access token via OpenHome SDK
        try:
            token = self.capability_worker.get_token("microsoft")
            if not token:
                await self._speak(
                    "Your Microsoft account isn't linked yet. "
                    "Connect it in the OpenHome app."
                )
                self.capability_worker.resume_normal_flow()
                return
            self.worker.editor_logging_handler.info("Outlook token retrieved successfully.")
        except Exception as e:
            await self._speak("Can't connect to Outlook. Make sure your Microsoft account is linked.")
            self.worker.editor_logging_handler.error(f"Token retrieval error: {e}")
            self.capability_worker.resume_normal_flow()
            return

        # Resolve the sender identity from the signed-in account record.
        try:
            self._sender_email = _get_sender_email(token)
            self.worker.editor_logging_handler.info(f"Sender email: {self._sender_email}")
        except Exception:
            self._sender_email = None

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

        # Intent classification with keyword fast paths + LLM fallback
        intent = self._classify_intent(first_msg, context_prefix)

        routing_msg = first_msg

        if intent == "UNKNOWN":
            await self._speak("Outlook ready. What would you like to do?")
            while True:
                intent_raw = (await self.capability_worker.user_response()).strip()
                routing_msg = intent_raw
                intent = self._classify_intent(intent_raw)
                if intent not in ("UNKNOWN",):
                    break
                await self._speak(
                    "Didn't get that. What do you need?"
                )

        try:
            await self._route_and_execute(token, intent, routing_msg)

            # Session loop — keep listening for follow-up actions
            while True:
                follow_up = await self._ask(
                    "Anything else?"
                )
                lowered = follow_up.lower().strip()
                if lowered in ("done", "exit", "stop", "quit", "bye", "no",
                               "nope", "nothing", "no thanks", "i'm good",
                               "im good", "that's all", "thats all", "that's it",
                               "thats it", "never mind", "nevermind", "all good",
                               "we're good", "all set", "good for now",
                               "i'm done", "im done", "nah", "wrap up",
                               "later", "peace", "goodbye"):
                    await self._speak("Got it.")
                    break

                intent = self._classify_intent(follow_up)

                if intent == "EXIT":
                    await self._speak("Done.")
                    break

                await self._route_and_execute(token, intent, follow_up)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Outlook unhandled error: {e}")
            await self._speak("Something went wrong. Please try again.")
        finally:
            self.capability_worker.resume_normal_flow()

    def _classify_intent(self, utterance: str, context_prefix: str = "") -> str:
        """Classify intent with keyword fast paths, then LLM fallback."""
        lower = utterance.lower().strip()

        # Keyword fast paths — prevent LLM misclassification
        if any(w in lower for w in ["list", "show", "inbox", "check my email",
                                     "unread", "new email", "new mail",
                                     "what came in", "anything new", "my emails",
                                     "pull up my mail", "what's in my inbox",
                                     "any messages", "what do i got", "lemme see",
                                     "go through my mail", "what'd i miss",
                                     "catch me up", "what i got"]):
            return "LIST"
        if any(w in lower for w in ["read", "open", "what did", "what does",
                                     "hear the", "tell me about", "pull up",
                                     "let me hear", "what's it say",
                                     "what'd they say", "gimme the",
                                     "the one from", "the one about", "play me"]):
            return "READ"
        if any(w in lower for w in ["send", "compose", "write an email",
                                     "email to", "send email", "send a mail",
                                     "shoot an email", "fire off", "draft",
                                     "write to", "message", "hit up",
                                     "drop a line"]):
            return "COMPOSE"
        if any(w in lower for w in ["reply", "respond", "get back to",
                                     "hit them back", "write back", "answer",
                                     "tell them", "say back",
                                     "get back to them"]):
            return "REPLY"
        if lower in ("done", "exit", "stop", "quit", "bye", "no", "nope",
                      "nothing", "no thanks", "i'm good", "im good",
                      "that's all", "thats all", "that's it", "thats it",
                      "never mind", "nevermind", "all good", "we're good",
                      "all set", "good for now", "i'm done", "im done",
                      "nah", "wrap up", "later", "peace", "goodbye"):
            return "EXIT"

        # LLM fallback for ambiguous cases
        return self._llm(
            f"{context_prefix}"
            f"Classify this Outlook email intent: '{utterance}'.\n"
            "COMPOSE — user wants to send, write, or compose a new email\n"
            "REPLY   — user wants to reply, respond, or get back to someone\n"
            "READ    — user wants to read, open, hear, or know what an email says\n"
            "LIST    — user wants to list, show, check, see what came in, or know about unread/new emails\n"
            "EXIT    — done, stop, quit, goodbye, nothing else\n"
            "UNKNOWN — not related to email, too vague to tell\n"
            "Reply with exactly one word: COMPOSE, REPLY, READ, LIST, EXIT, or UNKNOWN."
        ).upper()

    async def _route_and_execute(self, token: str, intent: str, routing_msg: str):
        if intent == "COMPOSE":
            await self._flow_compose(token, routing_msg)
        elif intent == "REPLY":
            await self._flow_reply(token, routing_msg)
        elif intent == "LIST":
            await self._flow_list(token, routing_msg)
        elif intent == "READ":
            await self._flow_read(token, routing_msg)
        else:
            await self._speak(
                "Didn't catch that. What do you need?"
            )
