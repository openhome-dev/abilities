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
CONTACTS_FILE = "housemate_contacts.json"
STATUS_MD = "housemate_status.md"

ISLAMABAD_TZ = "Asia/Karachi"
ISLAMABAD_LAT = 33.6844
ISLAMABAD_LON = 73.0479

# Default contacts (also seeded into housemate_contacts.json memory)
DEFAULT_CONTACTS = {
    "dad": "dad@example.com",
    "father": "dad@example.com",
    "papa": "dad@example.com",
    "abu": "dad@example.com",
    "security": "security@example.com",
    "doctor": "doctor@example.com",
    "dr": "doctor@example.com",
}
CONTACTS = dict(DEFAULT_CONTACTS)

# SMTP sender (Gmail app password). Override via Dashboard API keys when set.
SMTP_FALLBACK_EMAIL = ""
SMTP_FALLBACK_PASSWORD = ""
SMTP_FALLBACK_HOST = "smtp.gmail.com"

# Optional companion dashboard base URL (no trailing slash). Empty = disabled.
DASHBOARD_URL = ""

WIKIPEDIA_API_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
ALADHAN_URL = "https://api.aladhan.com/v1/timingsByCity"

WMO_WEATHER = {
    0: "clear",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy",
    51: "light drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "snow",
    80: "rain showers",
    95: "thunderstorms",
}

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
{{"intent":"email|reminder|schedule|doctor|search|time|weather|prayer|brief|sos|contacts|home_help|guardian_walk|help|exit","confidence":0.0}}

Rules:
- sos: emergency / help me / SOS / call security for help (urgent alert emails)
- brief: morning brief / daily brief / brief me
- weather: weather / temperature / mausam
- prayer: prayer times / namaz / salah / zahur / zuhr / dhuhr / asr / maghrib / isha / fajr
- contacts: change contact email / update dad email
- email: send / draft email
- reminder: reminder / timer / alarm
- schedule: remember / list plans in memory
- doctor: doctor appointment
- search: look up facts
- time: current clock time
- home_help: general household help
- guardian_walk: walking home safety
- help: what can you do
- exit: finished

User: {user_input}
"""


class HomeHelperCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _last_user: str = ""
    _contacts: dict = None
    _session_id: str = ""
    _session_start: float = 0.0
    _dash_cycle: int = 0

    # {{register capability}}

    # -------------------- storage helpers --------------------
    async def _reset_json(self, filename: str, reason: str = "") -> None:
        try:
            if reason:
                self.worker.editor_logging_handler.info(
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
            self.worker.editor_logging_handler.info(
                f"{time()}: schedule key sync skipped: {e}"
            )

    async def _ensure_contacts(self) -> dict:
        if isinstance(self._contacts, dict) and self._contacts:
            return self._contacts
        data = await self._read_json(CONTACTS_FILE, None)
        if not isinstance(data, dict) or not data:
            data = dict(DEFAULT_CONTACTS)
            await self._write_json(CONTACTS_FILE, data)
        # Keep aliases in sync with dad/doctor/security
        if data.get("dad"):
            data["father"] = data["dad"]
            data["papa"] = data["dad"]
            data["abu"] = data["dad"]
        if data.get("doctor"):
            data["dr"] = data["doctor"]
        self._contacts = data
        return data

    async def _save_contacts(self, data: dict) -> None:
        if data.get("dad"):
            data["father"] = data["dad"]
            data["papa"] = data["dad"]
            data["abu"] = data["dad"]
        if data.get("doctor"):
            data["dr"] = data["doctor"]
        self._contacts = data
        await self._write_json(CONTACTS_FILE, data)

    def _dash_post(self, event: str, payload: dict) -> None:
        if not DASHBOARD_URL:
            return

        async def _send():
            try:
                import asyncio

                body = dict(payload)
                body.setdefault("session_id", self._session_id)
                body.setdefault("timestamp", time())
                body.setdefault("cycle_id", self._dash_cycle)
                await asyncio.to_thread(
                    requests.post,
                    f"{DASHBOARD_URL}/api/housemate/{event}",
                    json=body,
                    timeout=5,
                )
            except Exception as e:
                self.worker.editor_logging_handler.info(f"[DASH] {event} skip: {e}")

        try:
            self.worker.session_tasks.create(_send())
        except Exception:
            pass

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
        contacts = self._contacts if isinstance(self._contacts, dict) else DEFAULT_CONTACTS
        for name, email in contacts.items():
            if name in lower:
                return email
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
                "sos",
                "emergency",
                "help me now",
                "i need help",
                "call security",
                "alert security",
                "send sos",
                "danger",
            )
        ):
            return "sos"
        if any(
            w in lower
            for w in (
                "daily brief",
                "morning brief",
                "brief me",
                "start my day",
                "briefing",
            )
        ):
            return "brief"
        if any(
            w in lower
            for w in (
                "prayer",
                "namaz",
                "salah",
                "fajr",
                "maghrib",
                "isha",
                "asr",
                "asar",
                "dhuhr",
                "zuhr",
                "zuhar",
                "zahur",
                "zohar",
                "zohur",
                "نماز",
                "ظہر",
                "ظهر",
            )
        ):
            return "prayer"
        if any(
            w in lower
            for w in ("weather", "temperature", "mausam", "forecast", "موسم")
        ):
            return "weather"
        if any(
            w in lower
            for w in (
                "change contact",
                "update contact",
                "change dad",
                "update dad",
                "change security",
                "update security",
                "change doctor email",
                "set contact",
            )
        ):
            return "contacts"
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
                "pakistan time",
                "وقت",
                "time now",
                "tell me the time",
                "tell me current time",
                "time in islamabad",
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
            "weather",
            "prayer",
            "brief",
            "sos",
            "contacts",
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
        await self._ensure_contacts()
        sender, password, _host = self._smtp_creds()
        smtp_ready = bool(sender and password)
        if not smtp_ready:
            await self._speak_plain(
                "Email isn't set up yet. Check the SMTP settings."
            )
            return

        contact = self._resolve_contact(user_input)
        contacts = self._contacts or DEFAULT_CONTACTS
        draft = self.capability_worker.text_to_text_response(
            f"""Extract an email from this multilingual request. Return ONLY JSON:
{{"to_contact":"dad|security|doctor|empty","to":"email or empty","subject":"real short subject not placeholder","body":"message body"}}
Known contacts: dad={contacts.get('dad')}, security={contacts.get('security')}, doctor={contacts.get('doctor')}.
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
        for name, email in (self._contacts or DEFAULT_CONTACTS).items():
            if email == to_addr and name in ("dad", "security", "doctor"):
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
            self._dash_cycle += 1
            self._dash_post(
                "update",
                {
                    "last_action": "email",
                    "last_email_to": contact_name,
                    "last_email_ok": True,
                },
            )
        else:
            await self._speak_plain(
                "Send failed. Check the Gmail app password and try again."
            )

    def _fetch_weather_islamabad(self) -> dict:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": ISLAMABAD_LAT,
                "longitude": ISLAMABAD_LON,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": ISLAMABAD_TZ,
                "forecast_days": 1,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json() or {}
        current = data.get("current") or {}
        daily = data.get("daily") or {}
        code = current.get("weather_code")
        return {
            "temp": current.get("temperature_2m"),
            "wind": current.get("wind_speed_10m"),
            "condition": WMO_WEATHER.get(code, "changing skies"),
            "high": (daily.get("temperature_2m_max") or [None])[0],
            "low": (daily.get("temperature_2m_min") or [None])[0],
            "rain": (daily.get("precipitation_probability_max") or [None])[0],
        }

    def _fetch_prayer_islamabad(self) -> dict:
        resp = requests.get(
            ALADHAN_URL,
            params={"city": "Islamabad", "country": "Pakistan", "method": 1},
            timeout=10,
        )
        if resp.status_code != 200:
            return {}
        timings = ((resp.json() or {}).get("data") or {}).get("timings") or {}
        keep = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")
        out = {}
        for k in keep:
            val = timings.get(k, "")
            out[k] = val.split(" ")[0] if val else ""
        return out

    async def _handle_weather(self, user_input: str) -> None:
        await self._speak_plain("Checking Islamabad weather.")
        try:
            import asyncio

            w = await asyncio.to_thread(self._fetch_weather_islamabad)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"weather error: {e}")
            w = {}
        if not w or w.get("temp") is None:
            await self._speak_plain("I couldn't get the weather right now.")
            return
        rain = w.get("rain")
        rain_bit = f" Rain chance {rain} percent." if rain is not None else ""
        await self._speak_plain(
            f"Islamabad is {w['temp']} degrees and {w['condition']}. "
            f"High {w.get('high')}, low {w.get('low')}.{rain_bit}"
        )
        self._dash_post("update", {"weather": w, "last_action": "weather"})

    def _which_prayer(self, user_input: str) -> str:
        """Return Aladhan key for a specific prayer, or empty for all."""
        lower = (user_input or "").lower()
        mapping = [
            (("fajr", "fajar", "فجر"), "Fajr"),
            (("dhuhr", "zuhr", "zuhar", "zahur", "zohar", "zohur", "zahar", "ظہر", "ظهر"), "Dhuhr"),
            (("asr", "asar", "asar", "عصر"), "Asr"),
            (("maghrib", "magrib", "maghreb", "مغرب"), "Maghrib"),
            (("isha", "esha", "ishaa", "عشاء"), "Isha"),
        ]
        for keys, name in mapping:
            if any(k in lower for k in keys):
                return name
        return ""

    async def _handle_prayer(self, user_input: str) -> None:
        which = self._which_prayer(user_input)
        if which:
            await self._speak_plain(f"Checking {which} time in Islamabad.")
        else:
            await self._speak_plain("Fetching Islamabad prayer times.")
        try:
            import asyncio

            p = await asyncio.to_thread(self._fetch_prayer_islamabad)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"prayer error: {e}")
            p = {}
        if not p:
            await self._speak_plain("I couldn't get prayer times right now.")
            return
        if which and p.get(which):
            await self._speak_plain(
                f"{which} namaz in Islamabad is at {p.get(which)} today."
            )
        else:
            await self._speak_plain(
                f"Islamabad namaz today: Fajr {p.get('Fajr')}, Dhuhr {p.get('Dhuhr')}, "
                f"Asr {p.get('Asr')}, Maghrib {p.get('Maghrib')}, Isha {p.get('Isha')}."
            )
        self._dash_post(
            "update",
            {"prayer": p, "last_action": "prayer", "asked_prayer": which or "all"},
        )

    async def _handle_sos(self, user_input: str) -> None:
        await self._ensure_contacts()
        contacts = self._contacts or DEFAULT_CONTACTS
        now = self._islamabad_now().strftime("%I:%M %p").lstrip("0")
        subject = "HouseMate SOS ALERT"
        body = (
            f"SOS from HouseMate at {now} Islamabad time.\n"
            f"User said: {user_input}\n"
            "Please check on them immediately."
        )
        await self._speak_plain("Sending SOS emails to security and dad now.")
        sent = []
        for name in ("security", "dad"):
            addr = contacts.get(name)
            if not addr:
                continue
            try:
                import asyncio

                ok = await asyncio.to_thread(self._send_smtp, addr, subject, body)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"SOS email {name}: {e}")
                ok = False
            if ok:
                sent.append(name)
        if sent:
            await self._speak_plain(
                f"SOS sent to {', '.join(sent)}. Get to a safe place if you can."
            )
        else:
            await self._speak_plain(
                "SOS email failed. Call emergency services directly."
            )
        self._dash_post(
            "update",
            {"last_action": "sos", "sos_sent_to": sent, "sos_ok": bool(sent)},
        )

    async def _handle_brief(self, user_input: str) -> None:
        await self._ensure_contacts()
        now = self._islamabad_now()
        clock = now.strftime("%I:%M %p").lstrip("0")
        await self._speak_plain("Building your Islamabad brief.")
        try:
            import asyncio

            weather = await asyncio.to_thread(self._fetch_weather_islamabad)
            prayer = await asyncio.to_thread(self._fetch_prayer_islamabad)
        except Exception:
            weather, prayer = {}, {}

        events = await self._read_json(SCHEDULE_FILE, [])
        if not isinstance(events, list):
            events = []
        active_plans = [e for e in events if e.get("status") != "cancelled"][:3]
        reminders = await self._read_json(REMINDERS_FILE, [])
        if not isinstance(reminders, list):
            reminders = []
        active_rems = [r for r in reminders if r.get("status") == "scheduled"][:3]

        parts = [f"It is {clock} in Islamabad."]
        if weather.get("temp") is not None:
            parts.append(
                f"Weather {weather['temp']} degrees, {weather.get('condition', 'okay')}."
            )
        if prayer.get("Dhuhr"):
            parts.append(
                f"Prayers include Dhuhr {prayer.get('Dhuhr')} and Maghrib {prayer.get('Maghrib')}."
            )
        if active_plans:
            plan_bits = "; ".join(
                f"{e.get('title')} at {e.get('human_time') or e.get('when_text')}"
                for e in active_plans
            )
            parts.append(f"In memory: {plan_bits}.")
        else:
            parts.append("No plans saved in memory.")
        if active_rems:
            rem_bits = "; ".join(
                f"{r.get('label')} at {r.get('human_time')}" for r in active_rems
            )
            parts.append(f"Reminders: {rem_bits}.")

        spoken = " ".join(parts)
        await self._speak_plain(spoken)
        await self._write_md(
            STATUS_MD,
            "## HouseMate Daily Brief\n\n"
            + "\n".join(f"- {p}" for p in parts)
            + "\n",
        )
        self._dash_post(
            "update",
            {
                "last_action": "brief",
                "brief": spoken,
                "weather": weather,
                "prayer": prayer,
                "plans": active_plans,
                "reminders": active_rems,
            },
        )

    async def _handle_contacts(self, user_input: str) -> None:
        await self._ensure_contacts()
        parsed = self._strip_json(
            self.capability_worker.text_to_text_response(
                f"""Extract a contact update. Return ONLY JSON:
{{"name":"dad|security|doctor","email":"address or empty"}}
User: {user_input}"""
            )
        ) or {}
        name = (parsed.get("name") or "").strip().lower()
        email = (parsed.get("email") or "").strip()
        if name not in ("dad", "security", "doctor"):
            who = await self._ask("Which contact? dad, security, or doctor?")
            name = "dad"
            for n in ("dad", "security", "doctor"):
                if n in who.lower():
                    name = n
                    break
            email = self._resolve_contact(who) or email
        if not email or "@" not in email:
            email = await self._ask(f"What is the new email for {name}?")
            email = email.replace(" at ", "@").replace(" ", "").strip()
        if "@" not in email:
            await self._speak_plain("That doesn't look like an email address.")
            return
        data = dict(self._contacts or DEFAULT_CONTACTS)
        data[name] = email
        await self._save_contacts(data)
        await self._speak_plain(f"Updated {name} to {email}.")
        self._dash_post("update", {"last_action": "contacts", "contacts": data})

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
        await self._ensure_contacts()
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
            f"Also email the doctor contact at {(self._contacts or DEFAULT_CONTACTS).get('doctor')}?"
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
        await self._speak_plain(
            "I can email contacts, send SOS alerts, set reminders, remember your schedule, "
            "tell Islamabad time, weather, and prayer times, give a daily brief, "
            "update contacts, book a doctor plan, look things up, or start walk-home mode."
        )

    # -------------------- main loop --------------------
    async def run(self):
        try:
            # Seize the mic turn so the main Agent does not answer over HouseMate
            try:
                await self.capability_worker.send_interrupt_signal()
            except Exception:
                pass

            try:
                await self._ensure_contacts()
            except Exception as e:
                self.worker.editor_logging_handler.error(f"contacts init: {e}")
                self._contacts = dict(DEFAULT_CONTACTS)

            self._session_id = f"housemate-{int(time())}"
            self._session_start = time()
            self._dash_cycle = 0
            try:
                self._dash_post(
                    "session_start",
                    {"ability": "housemate", "contacts": self._contacts or {}},
                )
            except Exception:
                pass

            await self._speak_plain(
                "HouseMate ready. Ask weather, zahur namaz, brief, email, or SOS."
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
                        "Yes? Email, SOS, weather, brief, prayer, or reminder?"
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
                elif intent == "sos":
                    await self._handle_sos(user_input)
                elif intent == "reminder":
                    await self._handle_reminder(user_input)
                elif intent == "time":
                    await self._handle_time(user_input)
                elif intent == "weather":
                    await self._handle_weather(user_input)
                elif intent == "prayer":
                    await self._handle_prayer(user_input)
                elif intent == "brief":
                    await self._handle_brief(user_input)
                elif intent == "contacts":
                    await self._handle_contacts(user_input)
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
            try:
                self._dash_post(
                    "session_end",
                    {
                        "duration_seconds": time() - (self._session_start or time()),
                    },
                )
            except Exception:
                pass
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())
