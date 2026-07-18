import json
import re
import base64
import requests
from datetime import datetime, timedelta
from time import time
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# CONSTANTS
# =============================================================================

EXIT_WORDS = {
    "stop",
    "exit",
    "quit",
    "done",
    "cancel",
    "bye",
    "goodbye",
    "leave",
    "that's all",
    "bas",
    "khatam",
    "band karo",
}

REMINDERS_FILE = "guardian_reminders.json"
WALK_FILE = "guardian_walk.json"
PREFS_FILE = "guardian_prefs.json"
SCHEDULE_FILE = "housemate_schedule.json"
SCHEDULE_MD = "housemate_schedule.md"

ISLAMABAD_TZ = "Asia/Karachi"

# Edit these contacts for your household (or leave empty and speak full addresses).
CONTACTS = {
    "dad": "dad@example.com",
    "father": "dad@example.com",
    "papa": "dad@example.com",
    "abu": "dad@example.com",
    "security": "security@example.com",
    "doctor": "doctor@example.com",
    "dr": "doctor@example.com",
}

# Prefer Dashboard API keys: housemate_smtp_email / housemate_smtp_password / housemate_smtp_host
SMTP_FALLBACK_EMAIL = ""
SMTP_FALLBACK_PASSWORD = ""
SMTP_FALLBACK_HOST = "smtp.gmail.com"

WIKIPEDIA_API_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

SYSTEM_HOME = (
    "You are HouseMate, a calm multilingual home assistant for voice. "
    "Always reply in the SAME language the user just used "
    "(English, Urdu, Roman Urdu, Hindi, Arabic, or mixed). "
    "Reply in 1-2 short spoken sentences. No markdown, lists, or symbols. "
    "IMPORTANT: HouseMate CAN send email, set reminders, and remember schedules. "
    "Never say you cannot send email. Never refuse a HouseMate action that already succeeded."
)

INTENT_PROMPT = """Classify the user's home-helper request. Language may be English, Urdu, Roman Urdu, or mixed.
Return ONLY valid JSON, nothing else.
{{"intent":"email|reminder|schedule|doctor|search|time|home_help|guardian_walk|help|exit","confidence":0.0}}

Rules:
- email: send / draft email (also: email, mail, ای میل, send mail)
- reminder: reminder / timer / alarm (یاد دہانی, remind)
- schedule: remember / list / add appointments or plans in memory (schedule, calendar, my plans, what's on, remember that I have)
- doctor: doctor / medical appointment (saved in memory + reminder + optional email)
- search: look up facts / internet
- time: current time / clock / Islamabad / Pakistan time / وقت
- home_help: general household help
- guardian_walk: walking home / safety check-in
- help: what can you do
- exit: finished

User: {user_input}
"""


class HomeHelperCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _last_user: str = ""

    # {{register capability}}

    # -------------------- storage helpers --------------------
    async def _reset_json(self, filename: str, reason: str = "") -> None:
        try:
            if reason:
                self.worker.editor_logging_handler.warning(
                    f"{time()}: reset {filename}. {reason}"
                )
            if await self.capability_worker.check_if_file_exists(filename, False):
                await self.capability_worker.delete_file(filename, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"{time()}: reset failed {filename}: {e}"
            )

    async def _read_json(self, filename: str, default):
        if not await self.capability_worker.check_if_file_exists(filename, False):
            return default
        raw = await self.capability_worker.read_file(filename, False)
        if not (raw or "").strip():
            return default
        try:
            return json.loads(raw)
        except Exception as e:
            await self._reset_json(filename, f"corrupt: {e}")
            return default

    async def _write_json(self, filename: str, data) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        await self._reset_json(filename, "pre-write delete")
        try:
            await self.capability_worker.write_file(filename, payload, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"{time()}: write failed {filename}: {e}"
            )

    async def _write_md(self, filename: str, content: str) -> None:
        """Delete-then-write so Agent memory injection stays current."""
        try:
            if await self.capability_worker.check_if_file_exists(filename, False):
                await self.capability_worker.delete_file(filename, False)
            await self.capability_worker.write_file(filename, content, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"{time()}: md write failed {filename}: {e}"
            )

    async def _sync_schedule_memory(self, events: list) -> None:
        if not isinstance(events, list):
            events = []
        await self._write_json(SCHEDULE_FILE, events)
        lines = ["## HouseMate Schedule Memory", ""]
        if not events:
            lines.append("- No upcoming appointments saved.")
        else:
            for ev in events[:12]:
                title = ev.get("title") or "Plan"
                when = ev.get("human_time") or ev.get("when_text") or "time TBD"
                kind = ev.get("kind") or "plan"
                note = ev.get("note") or ""
                line = f"- [{kind}] {title} — {when}"
                if note:
                    line += f" ({note})"
                lines.append(line)
        lines.append("")
        lines.append(
            "HouseMate stores plans in memory (not Google Calendar). "
            "Use this when the user asks what they have planned."
        )
        await self._write_md(SCHEDULE_MD, "\n".join(lines) + "\n")
        # Key-value mirror for structured reads
        try:
            existing = self.capability_worker.get_single_key("housemate_schedule")
            if existing is not None:
                self.capability_worker.update_key("housemate_schedule", {"events": events})
            else:
                self.capability_worker.create_key("housemate_schedule", {"events": events})
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"{time()}: schedule key sync skipped: {e}"
            )

    def _now_tz(self):
        tz_name = self.capability_worker.get_timezone() or ISLAMABAD_TZ
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo(ISLAMABAD_TZ)
            tz_name = ISLAMABAD_TZ
        return datetime.now(tz=tz), tz_name, tz

    def _islamabad_now(self):
        tz = ZoneInfo(ISLAMABAD_TZ)
        return datetime.now(tz=tz)

    def _strip_json(self, text: str):
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    return None
            return None

    async def _say(self, meaning_en: str, user_input: str = "") -> None:
        """Speak a message in the user's language. Never invent refusals."""
        hint = user_input or self._last_user or ""
        spoken = self.capability_worker.text_to_text_response(
            (
                f"User said: {hint}\n"
                f"Rephrase ONLY this meaning for voice in the user's language. "
                f"Do NOT change the meaning. Do NOT refuse. Do NOT say you cannot send email. "
                f"1 short sentence:\n{meaning_en}"
            ),
            [],
            SYSTEM_HOME,
        )
        text = (spoken or meaning_en).strip()
        # Guard: if the LLM invents a refusal, fall back to the real meaning
        low = text.lower()
        if any(
            bad in low
            for bad in (
                "can't send",
                "cannot send",
                "i'm sorry",
                "i am sorry",
                "unable to send",
                "don't send emails",
                "do not send emails",
            )
        ) and "sent" in meaning_en.lower():
            text = meaning_en
        await self.capability_worker.speak(text)

    async def _speak_plain(self, text: str) -> None:
        """Speak exact text — no LLM rewrite (use for email status)."""
        await self.capability_worker.speak(text)

    async def _ask(self, question_en: str) -> str:
        await self._say(question_en, self._last_user)
        return (await self.capability_worker.user_response() or "").strip()

    def _resolve_contact(self, text: str) -> str:
        lower = (text or "").lower()
        for name, email in CONTACTS.items():
            if name in lower:
                return email
        # spoken "at gmail"
        cleaned = (
            lower.replace(" at ", "@")
            .replace(" dot ", ".")
            .replace(" ", "")
        )
        match = re.search(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", cleaned)
        if match:
            return match.group(0)
        match2 = re.search(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", lower)
        if match2:
            return match2.group(0)
        return ""

    def _route_intent(self, user_input: str) -> str:
        lower = (user_input or "").lower()
        if any(w in lower for w in EXIT_WORDS):
            return "exit"
        if any(
            w in lower
            for w in (
                "walking home",
                "walk home",
                "guardian mode",
                "check in",
                "i'm walking",
            )
        ):
            return "guardian_walk"
        if any(
            w in lower
            for w in (
                "what time",
                "current time",
                "time is it",
                "clock",
                "islamabad",
                "pakistan time",
                "وقت",
                "time now",
                "tell me the time",
                "tell me current time",
            )
        ):
            return "time"
        if any(
            w in lower
            for w in (
                "doctor",
                "appointment",
                "clinic",
                "dentist",
                "physician",
                "ڈاکٹر",
            )
        ):
            return "doctor"
        if any(
            w in lower
            for w in (
                "email",
                "e-mail",
                "send mail",
                "sedn",
                "ای میل",
                "mail bhejo",
                "send an email",
                "send email",
            )
        ):
            return "email"
        if any(
            w in lower
            for w in (
                "remind",
                "reminder",
                "timer",
                "alarm",
                "یاد",
                "yaad",
            )
        ):
            return "reminder"
        if any(
            w in lower
            for w in (
                "calendar",
                "what's on my",
                "my events",
                "my schedule",
                "my plans",
                "what's planned",
                "remember that",
                "save this",
                "add to memory",
                "schedule",
            )
        ):
            return "schedule"
        if any(
            w in lower
            for w in (
                "search",
                "look up",
                "wikipedia",
                "what is",
                "who is",
                "internet",
            )
        ):
            return "search"
        if any(w in lower for w in ("what can you", "help me", "your abilities")):
            return "help"

        raw = self.capability_worker.text_to_text_response(
            INTENT_PROMPT.format(user_input=user_input)
        )
        parsed = self._strip_json(raw) or {}
        intent = (parsed.get("intent") or "home_help").strip().lower()
        allowed = {
            "email",
            "reminder",
            "schedule",
            "doctor",
            "search",
            "time",
            "home_help",
            "guardian_walk",
            "help",
            "exit",
        }
        return intent if intent in allowed else "home_help"

    # -------------------- email --------------------
    def _google_token(self):
        return self.capability_worker.get_token("google")

    def _send_gmail_api(self, token: str, to_addr: str, subject: str, body: str) -> bool:
        raw_msg = (
            f"To: {to_addr}\r\n"
            f"Subject: {subject}\r\n"
            f"Content-Type: text/plain; charset=\"UTF-8\"\r\n"
            f"\r\n"
            f"{body}"
        )
        encoded = base64.urlsafe_b64encode(raw_msg.encode("utf-8")).decode("utf-8")
        resp = requests.post(
            GMAIL_SEND_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"raw": encoded},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            self.worker.editor_logging_handler.error(
                f"gmail send failed: {resp.status_code} {resp.text[:300]}"
            )
            return False
        return True

    def _smtp_creds(self):
        # Dashboard API keys (Settings -> API Keys), then optional empty fallbacks.
        try:
            sender = self.capability_worker.get_api_keys("housemate_smtp_email") or SMTP_FALLBACK_EMAIL
        except Exception:
            sender = SMTP_FALLBACK_EMAIL
        try:
            password = self.capability_worker.get_api_keys("housemate_smtp_password") or SMTP_FALLBACK_PASSWORD
        except Exception:
            password = SMTP_FALLBACK_PASSWORD
        try:
            host = self.capability_worker.get_api_keys("housemate_smtp_host") or SMTP_FALLBACK_HOST
        except Exception:
            host = SMTP_FALLBACK_HOST
        return sender, password, host

    def _send_smtp(self, to_addr: str, subject: str, body: str) -> bool:
        sender, password, host = self._smtp_creds()
        if not sender or not password:
            return False
        self.worker.editor_logging_handler.info(
            f"SMTP send attempt from={sender} to={to_addr} host={host}"
        )
        return bool(
            self.capability_worker.send_email(
                host=host,
                port=465,
                sender_email=sender,
                sender_password=password,
                receiver_email=to_addr,
                cc_emails=[],
                subject=subject,
                body=body,
                attachment_paths=[],
            )
        )

    async def _handle_email(self, user_input: str) -> None:
        sender, password, _host = self._smtp_creds()
        smtp_ready = bool(sender and password)
        if not smtp_ready:
            await self._speak_plain(
                "Email isn't set up yet. Check the SMTP settings."
            )
            return

        contact = self._resolve_contact(user_input)
        draft = self.capability_worker.text_to_text_response(
            f"""Extract an email from this multilingual request. Return ONLY JSON:
{{"to_contact":"dad|security|doctor|empty","to":"email or empty","subject":"real short subject not placeholder","body":"message body"}}
Known contacts: dad={CONTACTS['dad']}, security={CONTACTS['security']}, doctor={CONTACTS['doctor']}.
If the user only asks whether email is possible, leave to/body empty.
User: {user_input}"""
        )
        parsed = self._strip_json(draft) or {}
        to_addr = contact or self._resolve_contact(parsed.get("to_contact") or "") or (
            parsed.get("to") or ""
        ).strip()
        subject = (parsed.get("subject") or "").strip()
        body = (parsed.get("body") or "").strip()
        if subject.lower() in {"short subject", "subject", "message from housemate", "none", "n/a"}:
            subject = ""

        if not to_addr or "@" not in to_addr:
            who = await self._ask(
                "Who should I email? Say dad, security, doctor, or an address."
            )
            to_addr = self._resolve_contact(who) or who.replace(" at ", "@").replace(
                " ", ""
            ).strip()
            # If they said more than a name, use it as the message body
            if who and not body and len(who.split()) > 2:
                body = who
        if not body:
            body = await self._ask("What should the email say?")
        if not subject:
            subject = self.capability_worker.text_to_text_response(
                f"Write a 3-6 word email subject for this body only. No quotes: {body}"
            ).strip().strip('"')
            if subject.lower() in {"short subject", "subject"} or not subject:
                subject = "HouseMate message"

        who_label = to_addr
        contact_name = "them"
        for name, email in CONTACTS.items():
            if email == to_addr:
                who_label = name
                contact_name = name
                break

        ok = await self.capability_worker.run_confirmation_loop(
            f"Send email to {who_label} about {subject}?"
        )
        if not ok:
            await self._speak_plain("Okay, cancelled.")
            return

        await self._speak_plain("Sending now.")
        status = False
        try:
            import asyncio

            status = await asyncio.to_thread(
                self._send_smtp, to_addr, subject, body
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"email send error: {e}")
            status = False

        if status:
            # Plain speak only — LLM was wrongly saying "I can't send email" after success
            await self._speak_plain(
                f"Done. Email sent to {contact_name}."
            )
            self.worker.editor_logging_handler.info(
                f"HouseMate confirmed email success to={to_addr}"
            )
        else:
            await self._speak_plain(
                "Send failed. Check the Gmail app password and try again."
            )

    # -------------------- time (Islamabad) --------------------
    async def _handle_time(self, user_input: str) -> None:
        now = self._islamabad_now()
        spoken = now.strftime("%I:%M %p").lstrip("0")
        date = now.strftime("%A, %B %d, %Y")
        await self._say(
            f"In Islamabad, Pakistan it is {spoken} on {date}.",
            user_input,
        )

    # -------------------- reminders --------------------
    async def _handle_reminder(self, user_input: str) -> None:
        now, tz_name, tz = self._now_tz()
        # Prefer Islamabad if user asks in PK context
        if any(w in user_input.lower() for w in ("islamabad", "pakistan", "pkr")):
            tz_name = ISLAMABAD_TZ
            tz = ZoneInfo(ISLAMABAD_TZ)
            now = datetime.now(tz=tz)

        lower = user_input.lower()

        if any(w in lower for w in ("list", "what reminders", "show reminder")):
            reminders = await self._read_json(REMINDERS_FILE, [])
            active = [r for r in reminders if r.get("status") == "scheduled"]
            if not active:
                await self._say("You have no active reminders.", user_input)
                return
            spoken = "; ".join(
                f"{r.get('label', 'reminder')} at {r.get('human_time', 'unknown')}"
                for r in active[:5]
            )
            await self._say(f"You have {len(active)}. {spoken}.", user_input)
            return

        if any(w in lower for w in ("cancel all", "clear reminder", "delete all reminder")):
            await self._write_json(REMINDERS_FILE, [])
            await self._say("All reminders cleared.", user_input)
            return

        prompt = f"""You are a reminder time parser. Multilingual input is OK.
Current datetime: {now.isoformat()}
Timezone: {tz_name}

Convert the user request into a future reminder.
If time is missing, respond exactly: QUESTION:when should I remind you?
Otherwise return ONLY JSON:
{{"target_iso":"ISO8601 with offset","human_time":"friendly time","label":"short reminder label"}}

User: {user_input}
"""
        history = []
        text = user_input
        for _ in range(4):
            llm = self.capability_worker.text_to_text_response(text, history, prompt)
            history.append({"role": "user", "content": text})
            if isinstance(llm, str) and llm.startswith("QUESTION:"):
                history.append({"role": "assistant", "content": llm})
                q = llm.split("QUESTION:", 1)[1].strip()
                await self._say(q, user_input)
                text = (await self.capability_worker.user_response() or "").strip()
                continue
            parsed = self._strip_json(llm) if isinstance(llm, str) else None
            if not parsed or not parsed.get("target_iso"):
                await self._say(
                    "I couldn't understand that reminder time. Try again.",
                    user_input,
                )
                return
            reminder = {
                "id": f"rem_{int(time() * 1000)}",
                "created_at_epoch": int(time()),
                "timezone": tz_name,
                "target_iso": parsed["target_iso"],
                "human_time": parsed.get("human_time", parsed["target_iso"]),
                "label": parsed.get("label", "Reminder"),
                "status": "scheduled",
                "source_text": user_input,
            }
            reminders = await self._read_json(REMINDERS_FILE, [])
            if not isinstance(reminders, list):
                reminders = []
            reminders.append(reminder)
            await self._write_json(REMINDERS_FILE, reminders)
            await self._say(
                f"Okay. I'll remind you about {reminder['label']} at {reminder['human_time']}.",
                user_input,
            )
            return

        await self._say("Let's try setting that reminder again later.", user_input)

    # -------------------- schedule memory (replaces calendar) --------------------
    async def _add_schedule_event(
        self,
        title: str,
        when_text: str,
        kind: str = "plan",
        note: str = "",
        target_iso: str = "",
        human_time: str = "",
        source_text: str = "",
    ) -> dict:
        events = await self._read_json(SCHEDULE_FILE, [])
        if not isinstance(events, list):
            events = []
        event = {
            "id": f"mem_{int(time() * 1000)}",
            "title": title,
            "kind": kind,
            "when_text": when_text,
            "human_time": human_time or when_text,
            "target_iso": target_iso,
            "note": note,
            "source_text": source_text,
            "created_at_epoch": int(time()),
            "status": "planned",
        }
        events.append(event)
        await self._sync_schedule_memory(events)
        return event

    async def _handle_schedule(self, user_input: str) -> None:
        lower = user_input.lower()
        events = await self._read_json(SCHEDULE_FILE, [])
        if not isinstance(events, list):
            events = []

        if any(w in lower for w in ("clear schedule", "delete all plans", "forget all")):
            await self._sync_schedule_memory([])
            await self._say("I cleared your schedule memory.", user_input)
            return

        wants_list = any(
            w in lower
            for w in (
                "what's on",
                "what is on",
                "list",
                "show",
                "my schedule",
                "my plans",
                "my events",
                "calendar",
                "do i have",
            )
        ) and not any(
            w in lower for w in ("add", "book", "remember that", "save", "schedule a")
        )

        # Default: if asking about plans with no add language, list
        if wants_list or (
            any(w in lower for w in ("calendar", "schedule", "plans", "events"))
            and not any(w in lower for w in ("add", "book", "remember", "save", "create"))
        ):
            active = [e for e in events if e.get("status") != "cancelled"]
            if not active:
                await self._say(
                    "Your schedule memory is empty. Tell me a plan and I'll remember it.",
                    user_input,
                )
                return
            spoken = "; ".join(
                f"{e.get('title', 'plan')} at {e.get('human_time') or e.get('when_text', 'sometime')}"
                for e in active[:6]
            )
            await self._say(
                f"You have {len(active)} in memory. {spoken}.",
                user_input,
            )
            return

        # Add to memory
        now, tz_name, tz = self._now_tz()
        parse_prompt = f"""Extract a plan/appointment to remember. Current: {now.isoformat()}, tz: {tz_name}.
Return ONLY JSON:
{{"title":"short title","when_text":"day/time phrase","human_time":"friendly time","target_iso":"ISO8601 or empty","note":"optional","kind":"plan|meeting|errand|other"}}
If time missing: QUESTION:when is it?
User: {user_input}
"""
        text = user_input
        history = []
        for _ in range(4):
            llm = self.capability_worker.text_to_text_response(text, history, parse_prompt)
            history.append({"role": "user", "content": text})
            if isinstance(llm, str) and llm.startswith("QUESTION:"):
                history.append({"role": "assistant", "content": llm})
                q = llm.split("QUESTION:", 1)[1].strip()
                await self._say(q, user_input)
                text = (await self.capability_worker.user_response() or "").strip()
                continue
            parsed = self._strip_json(llm) if isinstance(llm, str) else None
            if not parsed or not (parsed.get("title") or parsed.get("when_text")):
                await self._say(
                    "I couldn't understand that plan. Try again.",
                    user_input,
                )
                return
            title = (parsed.get("title") or "Plan").strip()
            when_text = (parsed.get("when_text") or "").strip()
            human_time = (parsed.get("human_time") or when_text).strip()
            event = await self._add_schedule_event(
                title=title,
                when_text=when_text,
                kind=(parsed.get("kind") or "plan").strip(),
                note=(parsed.get("note") or "").strip(),
                target_iso=(parsed.get("target_iso") or "").strip(),
                human_time=human_time,
                source_text=user_input,
            )
            # Also set a spoken reminder if we have a parseable time
            if event.get("target_iso"):
                await self._handle_reminder(
                    f"Remind me about {title} at {human_time or when_text}"
                )
            await self._say(
                f"Saved in memory: {title} at {human_time or when_text}.",
                user_input,
            )
            return

        await self._say("Let's try saving that plan again.", user_input)

    # -------------------- doctor booking (memory + reminder + email) --------------------
    async def _handle_doctor(self, user_input: str) -> None:
        details = self.capability_worker.text_to_text_response(
            f"""Extract doctor appointment details. Return ONLY JSON:
{{"doctor":"name or type","reason":"short","when_text":"time phrase from user or empty"}}
User: {user_input}"""
        )
        parsed = self._strip_json(details) or {}
        doctor = (parsed.get("doctor") or "").strip()
        reason = (parsed.get("reason") or "").strip()
        when_text = (parsed.get("when_text") or "").strip()

        if not doctor:
            doctor = await self._ask("Which doctor or clinic?")
        if not when_text:
            when_text = await self._ask("What day and time should I book?")
        if not reason:
            reason = "Appointment"

        title = f"Doctor: {doctor}"
        await self._add_schedule_event(
            title=title,
            when_text=when_text,
            kind="doctor",
            note=reason,
            human_time=when_text,
            source_text=user_input,
        )
        await self._say(
            f"Saved doctor visit with {doctor} in memory.",
            user_input,
        )
        await self._handle_reminder(
            f"Remind me about doctor appointment with {doctor} for {reason} at {when_text}"
        )

        notify = await self.capability_worker.run_confirmation_loop(
            f"Also email the doctor contact at {CONTACTS['doctor']}?"
        )
        if notify:
            await self._handle_email(
                f"Email doctor about appointment with {doctor} for {reason} at {when_text}"
            )

    # -------------------- internet / search --------------------
    def _wikipedia_summary(self, topic: str) -> str:
        formatted = topic.replace(" ", "_")
        try:
            resp = requests.get(
                f"{WIKIPEDIA_API_URL}{formatted}",
                headers={"User-Agent": "HouseMate-OpenHome/1.0"},
                timeout=10,
            )
            if resp.status_code != 200:
                return ""
            summary = (resp.json() or {}).get("extract", "") or ""
            sentences = summary.split(". ")
            short = ". ".join(sentences[:2]).strip()
            if short and not short.endswith("."):
                short += "."
            return short
        except Exception as e:
            self.worker.editor_logging_handler.error(f"wikipedia error: {e}")
            return ""

    async def _handle_search(self, user_input: str) -> None:
        topic = self.capability_worker.text_to_text_response(
            f"Extract the search topic in a few words, no punctuation. User: {user_input}"
        ).strip().strip('"')
        if not topic:
            topic = await self._ask("What should I look up?")

        await self._say(f"Looking up {topic}.", user_input)
        try:
            import asyncio

            summary = await asyncio.to_thread(self._wikipedia_summary, topic)
        except Exception:
            summary = self._wikipedia_summary(topic)

        if summary:
            spoken = self.capability_worker.text_to_text_response(
                f"Rewrite for voice in the user's language:\n{summary}\nUser said: {user_input}",
                [],
                SYSTEM_HOME,
            )
            await self.capability_worker.speak(spoken)
            return

        answer = self.capability_worker.text_to_text_response(
            f"Answer briefly from general knowledge for voice: {user_input}",
            [],
            SYSTEM_HOME,
        )
        await self.capability_worker.speak(answer)

    # -------------------- home Q&A --------------------
    async def _handle_home_help(self, user_input: str) -> None:
        answer = self.capability_worker.text_to_text_response(
            user_input,
            [],
            SYSTEM_HOME
            + " Help with household tasks, troubleshooting, recipes, chores, and everyday life.",
        )
        await self.capability_worker.speak(answer)

    # -------------------- walk-home mode --------------------
    async def _handle_guardian_walk(self, user_input: str) -> None:
        now, tz_name, tz = self._now_tz()
        parse = self.capability_worker.text_to_text_response(
            f"""Parse a walk-home safety check-in. Current: {now.isoformat()}, tz: {tz_name}.
Return ONLY JSON:
{{"minutes":20,"destination":"home","note":"short"}}
If user gave an ETA in minutes use that, else default 20.
User: {user_input}"""
        )
        parsed = self._strip_json(parse) or {}
        minutes = parsed.get("minutes") or 20
        try:
            minutes = int(minutes)
        except Exception:
            minutes = 20
        minutes = max(5, min(minutes, 180))
        destination = parsed.get("destination") or "home"
        due = now + timedelta(minutes=minutes)

        session = {
            "id": f"walk_{int(time() * 1000)}",
            "status": "active",
            "destination": destination,
            "started_at_epoch": int(time()),
            "check_in_iso": due.isoformat(),
            "human_time": due.strftime("%I:%M %p").lstrip("0"),
            "missed_count": 0,
            "timezone": tz_name,
            "note": parsed.get("note") or user_input,
        }
        await self._write_json(WALK_FILE, session)
        await self._say(
            f"Walk-home mode on. I'll check in at {session['human_time']}. "
            "Say check in when you arrive, or help if you need me.",
            user_input,
        )

        while True:
            reply = await self.capability_worker.user_response()
            if not reply:
                continue
            self._last_user = reply
            low = reply.lower()
            if any(w in low for w in EXIT_WORDS):
                await self._say("Leaving walk-home mode.", reply)
                break
            if any(
                w in low
                for w in (
                    "arrived",
                    "i'm home",
                    "i am home",
                    "safe",
                    "check in",
                    "check-in",
                )
            ):
                session["status"] = "completed"
                await self._write_json(WALK_FILE, session)
                await self._say("Glad you're safe. Walk-home mode off.", reply)
                break
            if any(w in low for w in ("help", "emergency", "not safe", "scared")):
                session["status"] = "emergency"
                session["emergency_at_epoch"] = int(time())
                await self._write_json(WALK_FILE, session)
                await self._say(
                    "I'm with you. Move to a lit public place if you can, "
                    "call local emergency services if you're in danger, "
                    "and tell a trusted contact where you are.",
                    reply,
                )
                continue
            tip = self.capability_worker.text_to_text_response(
                f"User in walk-home mode said: {reply}. Give brief calm safety guidance.",
                [],
                SYSTEM_HOME,
            )
            await self.capability_worker.speak(tip)

    async def _handle_help(self, user_input: str = "") -> None:
        await self._say(
            "I can send email to dad, security, or doctor, set reminders, "
            "remember your schedule in memory, tell Islamabad time, "
            "book a doctor visit, look things up, or start walk-home mode.",
            user_input,
        )

    # -------------------- main loop --------------------
    async def run(self):
        try:
            # Greet immediately so the main Agent doesn't steal the turn
            await self._speak_plain(
                "HouseMate ready. I can email dad, security, or doctor, "
                "set reminders, remember your schedule, and tell Islamabad time. "
                "What do you need?"
            )

            idle_empty = 0
            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input:
                    idle_empty += 1
                    if idle_empty >= 2:
                        await self._speak_plain("Okay, call HouseMate anytime.")
                        break
                    await self._speak_plain("Still there? What do you need?")
                    continue

                idle_empty = 0
                self._last_user = user_input
                if user_input.lower().strip() in {
                    "housemate",
                    "hey housemate",
                    "house mate",
                }:
                    await self._speak_plain(
                        "Yes? Email, reminder, schedule, or Islamabad time?"
                    )
                    continue

                intent = self._route_intent(user_input)
                self.worker.editor_logging_handler.info(
                    f"HouseMate intent={intent} input={user_input}"
                )

                if intent == "exit":
                    await self._speak_plain("Okay. I'm here if you need me.")
                    break
                if intent == "help":
                    await self._handle_help(user_input)
                elif intent == "email":
                    await self._handle_email(user_input)
                elif intent == "reminder":
                    await self._handle_reminder(user_input)
                elif intent == "time":
                    await self._handle_time(user_input)
                elif intent == "schedule":
                    await self._handle_schedule(user_input)
                elif intent == "doctor":
                    await self._handle_doctor(user_input)
                elif intent == "search":
                    await self._handle_search(user_input)
                elif intent == "guardian_walk":
                    await self._handle_guardian_walk(user_input)
                else:
                    await self._handle_home_help(user_input)

                await self._speak_plain("Anything else? Or say done.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"HouseMate run error: {e}")
            try:
                await self._speak_plain("Something went wrong. Please try again.")
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())
