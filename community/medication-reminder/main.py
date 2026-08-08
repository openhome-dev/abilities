import asyncio
import json
import re
import uuid
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "medication_reminder_data"
FDA_URL = "https://api.fda.gov/drug/label.json"
FDA_TIMEOUT = 8

HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

HOTWORDS = {
    "medication", "medicine", "pill", "pills", "dose", "doses",
    "took it", "took my", "took them", "i took", "i didn't take",
    "remind me to take", "set a reminder", "my prescription",
    "med reminder", "add a medication", "remove medication",
    "refill", "how many pills", "what is my medication",
    "medication schedule", "did i take", "adherence",
}

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "that's all"}

DEFAULT_TIMES = {
    "morning": "08:00",
    "afternoon": "13:00",
    "evening": "18:00",
    "night": "21:00",
    "bedtime": "21:00",
    "noon": "12:00",
    "twice a day": ["08:00", "20:00"],
    "twice daily": ["08:00", "20:00"],
    "three times a day": ["08:00", "14:00", "20:00"],
    "three times daily": ["08:00", "14:00", "20:00"],
    "once a day": ["08:00"],
    "once daily": ["08:00"],
}

INTENT_PROMPT = """Classify into exactly one intent:
SETUP    - adding or changing a medication schedule
TAKEN    - confirming a dose was taken
SNOOZE   - asking to be reminded again later
SKIP     - intentionally skipping a dose
STATUS   - asking what medications are due or taken today
REPORT   - asking about adherence/consistency over time
INFO     - asking what a medication is for or its side effects
REFILL   - updating supply / tablet count
REMOVE   - removing a medication from the schedule
EXIT     - done, stop, quit, goodbye

Return ONLY the label. Input: {text}"""

SETUP_PROMPT = (
    "Extract all medications from this text and return a JSON array. "
    "Each item must have: name (string), dose (string or empty), "
    "times (array of HH:MM strings in 24-hour format), "
    "instructions (string — food/timing note or empty string). "
    "Use these default times if not specified: once daily=08:00, "
    "twice daily=[08:00,20:00], three times daily=[08:00,14:00,20:00], "
    "morning=08:00, night=21:00, bedtime=21:00. "
    "Reply ONLY with valid JSON array, no extra text. Text: '{text}'"
)

SNOOZE_MINUTES_PROMPT = (
    "Extract the snooze duration in minutes from: '{text}'. "
    "Reply with just the number. If unclear, reply 30."
)

MED_NAME_PROMPT = (
    "From this text: '{text}', identify which medication the user is referring to. "
    "Their medications are: {med_names}. "
    "Reply with just the medication name exactly as listed. "
    "If unclear and there is only one pending, pick it."
)

FDA_SUMMARY_PROMPT = (
    "Summarise this official FDA drug-label information in 2 spoken sentences. "
    "Only state what is in the text — do not add facts. "
    "Plain English, no markdown. Info: {info}"
)

REPORT_PROMPT = (
    "Write a 2-sentence spoken adherence summary for a voice assistant. "
    "Data: {data}. "
    "Sentence 1: overall adherence percentage and doses taken vs expected. "
    "Sentence 2: which medication had the most missed doses if any, or praise if perfect. "
    "No markdown. Plain English."
)


def _empty_data() -> dict:
    return {
        "medications": [],
        "dose_log": [],
        "pending_alerts": [],
    }


def _med_id() -> str:
    return f"med_{uuid.uuid4().hex[:8]}"


class MedicationReminderCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        t = text.lower().strip()
        return any(hw in t for hw in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    def _now(self) -> datetime:
        """Naive wall-clock time in the user's timezone (falls back to server local)."""
        try:
            return datetime.now(ZoneInfo(self.capability_worker.get_timezone())).replace(tzinfo=None)
        except Exception:
            return datetime.now()

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
            return _empty_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[MedReminder] Load error: {e!r}")
            return _empty_data()

    def _save_data(self, data: dict):
        data = self._prune_log(data)
        try:
            self.capability_worker.create_key(STORAGE_KEY, data)
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, data)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[MedReminder] Save error: {e!r}")

    def _prune_log(self, data: dict) -> dict:
        cutoff = (self._now() - timedelta(days=30)).strftime("%Y-%m-%d")
        data["dose_log"] = [
            e for e in data.get("dose_log", []) if e.get("date", "") >= cutoff
        ]
        return data

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _classify_intent(self, text: str) -> str:
        raw = self.capability_worker.text_to_text_response(INTENT_PROMPT.format(text=text))
        result = raw.strip().upper().split()[0]
        valid = {"SETUP", "TAKEN", "SNOOZE", "SKIP", "STATUS", "REPORT", "INFO", "REFILL", "REMOVE", "EXIT"}
        return result if result in valid else "STATUS"

    def _parse_medications(self, text: str) -> list:
        raw = self.capability_worker.text_to_text_response(SETUP_PROMPT.format(text=text))
        try:
            raw = raw.strip()
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[MedReminder] Parse meds error: {e!r}")
        return []

    def _resolve_med_name(self, text: str, med_names: list) -> str:
        if len(med_names) == 1:
            return med_names[0]
        raw = self.capability_worker.text_to_text_response(
            MED_NAME_PROMPT.format(text=text, med_names=", ".join(med_names))
        ).strip()
        for name in med_names:
            if name.lower() in raw.lower():
                return name
        return med_names[0]

    def _snooze_minutes(self, text: str) -> int:
        raw = self.capability_worker.text_to_text_response(
            SNOOZE_MINUTES_PROMPT.format(text=text)
        ).strip()
        try:
            return max(5, min(int(raw), 120))
        except (ValueError, TypeError):
            return 30

    def _fetch_drug_info(self, med_name: str) -> str:
        try:
            resp = requests.get(
                FDA_URL,
                params={"search": f'openfda.generic_name:"{med_name.lower()}"', "limit": 1},
                timeout=FDA_TIMEOUT,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    usage = results[0].get("indications_and_usage", [""])
                    if usage and usage[0]:
                        return usage[0][:600]
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[MedReminder] FDA fetch error: {e!r}")
        return ""

    # ------------------------------------------------------------------
    # Active medication helpers
    # ------------------------------------------------------------------

    def _active_meds(self, data: dict) -> list:
        return [m for m in data.get("medications", []) if m.get("active", True)]

    def _find_med_by_name(self, name: str, data: dict) -> dict:
        name_l = name.lower()
        for m in self._active_meds(data):
            if m["name"].lower() in name_l or name_l in m["name"].lower():
                return m
        return {}

    def _pending_med_names(self, data: dict) -> list:
        pending = data.get("pending_alerts", [])
        med_ids = {p["med_id"] for p in pending}
        return [m["name"] for m in data.get("medications", []) if m["id"] in med_ids]

    # ------------------------------------------------------------------
    # Dose log helpers
    # ------------------------------------------------------------------

    def _log_dose(self, data: dict, med_id: str, scheduled_time: str, status: str):
        now = self._now()
        today = now.strftime("%Y-%m-%d")
        entry = {
            "med_id": med_id,
            "date": today,
            "scheduled_time": scheduled_time,
            "status": status,
            "logged_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        data.setdefault("dose_log", []).append(entry)
        data["pending_alerts"] = [
            p for p in data.get("pending_alerts", [])
            if not (p["med_id"] == med_id and p.get("date") == today
                    and p.get("scheduled_time") == scheduled_time)
        ]
        if status == "taken":
            for m in data.get("medications", []):
                if m["id"] == med_id and m.get("supply_count") and m["supply_count"] > 0:
                    m["supply_count"] -= 1
                    break

    def _todays_log(self, data: dict) -> list:
        today = self._now().strftime("%Y-%m-%d")
        return [e for e in data.get("dose_log", []) if e.get("date") == today]

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_setup(self, trigger: str, data: dict):
        parsed = self._parse_medications(trigger)
        if not parsed:
            await self.capability_worker.speak(
                "I didn't catch any medication details. "
                "Try saying something like: add metformin 500mg twice a day with meals."
            )
            return

        for med in parsed:
            name = med.get("name", "").strip()
            dose = med.get("dose", "").strip()
            times = med.get("times", [])
            instructions = med.get("instructions", "").strip()

            if not name:
                continue
            times = [t for t in times if isinstance(t, str) and HHMM_RE.match(t.strip())]
            if not times:
                times = ["08:00"]

            existing = self._find_med_by_name(name, data)
            if existing:
                existing["dose"] = dose or existing.get("dose", "")
                existing["times"] = times
                existing["instructions"] = instructions
                existing["active"] = True
            else:
                data["medications"].append({
                    "id": _med_id(),
                    "name": name,
                    "dose": dose,
                    "times": times,
                    "instructions": instructions,
                    "active": True,
                    "supply_count": 0,
                    "supply_doses_per_day": len(times),
                    "supply_start_date": "",
                    "supply_start_count": 0,
                })

        meds = self._active_meds(data)
        if not meds:
            await self.capability_worker.speak("I couldn't save any medications. Please try again.")
            return

        summary_parts = []
        for m in meds[-len(parsed):]:
            time_strs = [self._fmt_time(t) for t in m["times"]]
            time_str = " and ".join(time_strs)
            part = f"{m['name']}"
            if m["dose"]:
                part += f" {m['dose']}"
            part += f" at {time_str}"
            if m["instructions"]:
                part += f" — {m['instructions']}"
            summary_parts.append(part)

        await self.capability_worker.speak(
            "Got it. I'll remind you to take " + "; ".join(summary_parts) + "."
        )

        want_supply = await self.capability_worker.run_confirmation_loop(
            "Would you like to track your supply so I can remind you when to refill?"
        )
        if want_supply:
            for m in meds[-len(parsed):]:
                await self.capability_worker.speak(
                    f"How many {m['name']} tablets or doses do you currently have?"
                )
                reply = await self.capability_worker.user_response()
                if reply:
                    try:
                        count = int("".join(c for c in reply if c.isdigit()))
                        m["supply_count"] = count
                        m["supply_start_count"] = count
                        m["supply_doses_per_day"] = len(m["times"])
                        m["supply_start_date"] = self._now().strftime("%Y-%m-%d")
                        await self.capability_worker.speak(
                            f"Got it — {count} {m['name']} on hand. "
                            f"I'll alert you when you're running low."
                        )
                    except (ValueError, TypeError):
                        pass

        self._save_data(data)

    async def _handle_taken(self, text: str, data: dict):
        pending_names = self._pending_med_names(data)
        active_names = [m["name"] for m in self._active_meds(data)]
        candidates = pending_names if pending_names else active_names

        if not candidates:
            await self.capability_worker.speak(
                "No medications are currently scheduled. Say 'add a medication' to get started."
            )
            return

        med_name = self._resolve_med_name(text, candidates)
        med = self._find_med_by_name(med_name, data)
        if not med:
            await self.capability_worker.speak(f"I couldn't find {med_name} in your schedule.")
            return

        pending = [
            p for p in data.get("pending_alerts", [])
            if p["med_id"] == med["id"]
        ]
        scheduled_time = pending[0]["scheduled_time"] if pending else (med["times"][0] if med["times"] else "")

        self._log_dose(data, med["id"], scheduled_time, "taken")
        self._save_data(data)

        streak = self._streak(data, med["id"])
        msg = f"Logged — {med['name']} marked as taken."
        if streak >= 5:
            msg += f" You're on a {streak}-day streak. Keep it up."
        await self.capability_worker.speak(msg)

    async def _handle_snooze(self, text: str, data: dict):
        pending_names = self._pending_med_names(data)
        if not pending_names:
            await self.capability_worker.speak("No pending reminders to snooze right now.")
            return

        med_name = self._resolve_med_name(text, pending_names)
        med = self._find_med_by_name(med_name, data)
        if not med:
            await self.capability_worker.speak("I couldn't find that medication.")
            return

        minutes = self._snooze_minutes(text)
        snooze_until = (self._now() + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")

        for p in data.get("pending_alerts", []):
            if p["med_id"] == med["id"]:
                p["snoozed_until"] = snooze_until
                p["re_alerted"] = False

        self._save_data(data)
        await self.capability_worker.speak(
            f"I'll remind you about {med['name']} again in {minutes} minutes."
        )

    async def _handle_skip(self, text: str, data: dict):
        pending_names = self._pending_med_names(data)
        active_names = [m["name"] for m in self._active_meds(data)]
        candidates = pending_names if pending_names else active_names

        if not candidates:
            await self.capability_worker.speak("No medications found in your schedule.")
            return

        med_name = self._resolve_med_name(text, candidates)
        med = self._find_med_by_name(med_name, data)
        if not med:
            await self.capability_worker.speak(f"Couldn't find {med_name} in your schedule.")
            return

        pending = [p for p in data.get("pending_alerts", []) if p["med_id"] == med["id"]]
        scheduled_time = pending[0]["scheduled_time"] if pending else (med["times"][0] if med["times"] else "")
        self._log_dose(data, med["id"], scheduled_time, "skipped")
        self._save_data(data)
        await self.capability_worker.speak(f"Noted — {med['name']} skipped for this dose.")

    async def _handle_status(self, data: dict):
        meds = self._active_meds(data)
        if not meds:
            await self.capability_worker.speak(
                "You have no medications set up yet. Say 'add a medication' to get started."
            )
            return

        today_log = {(e["med_id"], e["scheduled_time"]): e["status"] for e in self._todays_log(data)}
        now_hhmm = self._now().strftime("%H:%M")

        taken_parts = []
        due_parts = []
        upcoming_parts = []

        for m in meds:
            for t in m["times"]:
                key = (m["id"], t)
                status = today_log.get(key)
                label = f"{m['name']}"
                if m["dose"]:
                    label += f" {m['dose']}"
                time_label = self._fmt_time(t)

                if status == "taken":
                    taken_parts.append(f"{label} at {time_label}")
                elif status == "skipped":
                    pass
                elif t <= now_hhmm:
                    due_parts.append(f"{label} at {time_label}")
                else:
                    upcoming_parts.append(f"{label} at {time_label}")

        parts = []
        if taken_parts:
            parts.append("Taken today: " + ", ".join(taken_parts) + ".")
        if due_parts:
            parts.append("Overdue: " + ", ".join(due_parts) + " — please take these now.")
        if upcoming_parts:
            parts.append("Coming up: " + ", ".join(upcoming_parts) + ".")
        if not parts:
            parts.append("All medications are up to date for today.")

        await self.capability_worker.speak(" ".join(parts))

    async def _handle_report(self, data: dict):
        meds = self._active_meds(data)
        if not meds:
            await self.capability_worker.speak("No medications are set up to report on.")
            return

        cutoff = (self._now() - timedelta(days=7)).strftime("%Y-%m-%d")
        recent = [e for e in data.get("dose_log", []) if e.get("date", "") >= cutoff]

        total_taken = sum(1 for e in recent if e["status"] == "taken")
        total_missed = sum(1 for e in recent if e["status"] == "missed")
        total_expected = total_taken + total_missed + sum(1 for e in recent if e["status"] == "skipped")

        if total_expected == 0:
            await self.capability_worker.speak(
                "No dose history in the last 7 days. Make sure to acknowledge reminders when they fire."
            )
            return

        pct = int((total_taken / total_expected) * 100) if total_expected else 0

        missed_by_med = {}
        for e in recent:
            if e["status"] == "missed":
                missed_by_med[e["med_id"]] = missed_by_med.get(e["med_id"], 0) + 1

        worst_id = max(missed_by_med, key=missed_by_med.get) if missed_by_med else None
        worst_name = next((m["name"] for m in meds if m["id"] == worst_id), "") if worst_id else ""

        report_data = {
            "taken": total_taken,
            "expected": total_expected,
            "pct": pct,
            "worst_med": worst_name,
            "worst_missed": missed_by_med.get(worst_id, 0) if worst_id else 0,
        }
        summary = self.capability_worker.text_to_text_response(
            REPORT_PROMPT.format(data=report_data)
        )
        await self.capability_worker.speak(summary)

    async def _handle_info(self, text: str, data: dict):
        med_names = [m["name"] for m in self._active_meds(data)]
        if med_names:
            med_name = self._resolve_med_name(text, med_names)
        else:
            med_name = text.strip()

        fda_info = await asyncio.to_thread(self._fetch_drug_info, med_name)
        if fda_info:
            summary = self.capability_worker.text_to_text_response(
                FDA_SUMMARY_PROMPT.format(info=fda_info[:500])
            )
            await self.capability_worker.speak(summary)
        else:
            await self.capability_worker.speak(
                f"I couldn't find official information on {med_name}. "
                f"Please check with your pharmacist or doctor for details about it."
            )

    async def _handle_refill(self, text: str, data: dict):
        med_names = [m["name"] for m in self._active_meds(data)]
        if not med_names:
            await self.capability_worker.speak("No medications in your schedule to refill.")
            return

        med_name = self._resolve_med_name(text, med_names)
        med = self._find_med_by_name(med_name, data)
        if not med:
            await self.capability_worker.speak(f"Couldn't find {med_name} in your schedule.")
            return

        digits = "".join(c for c in text if c.isdigit())
        if digits:
            count = int(digits)
        else:
            await self.capability_worker.speak(f"How many {med_name} do you have now?")
            reply = await self.capability_worker.user_response()
            digits = "".join(c for c in (reply or "") if c.isdigit())
            count = int(digits) if digits else 0

        if count > 0:
            med["supply_count"] = count
            med["supply_start_count"] = count
            med["supply_doses_per_day"] = len(med["times"]) or 1
            med["supply_start_date"] = self._now().strftime("%Y-%m-%d")
            self._save_data(data)
            days = count // (med["supply_doses_per_day"] or 1)
            await self.capability_worker.speak(
                f"Updated. You have {count} {med_name} — that's about {days} days' worth. "
                f"I'll remind you when you're running low."
            )
        else:
            await self.capability_worker.speak("I couldn't catch the count. Please try again.")

    async def _handle_remove(self, text: str, data: dict):
        med_names = [m["name"] for m in self._active_meds(data)]
        if not med_names:
            await self.capability_worker.speak("No medications to remove.")
            return

        med_name = self._resolve_med_name(text, med_names)
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Are you sure you want to remove {med_name} from your schedule?"
        )
        if confirmed:
            for m in data.get("medications", []):
                if m["name"].lower() == med_name.lower():
                    m["active"] = False
            self._save_data(data)
            await self.capability_worker.speak(f"{med_name} removed from your schedule.")
        else:
            await self.capability_worker.speak("No changes made.")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _fmt_time(self, hhmm: str) -> str:
        try:
            dt = datetime.strptime(hhmm, "%H:%M")
            return dt.strftime("%-I:%M %p").replace(":00 ", " ").lower()
        except ValueError:
            return hhmm

    def _streak(self, data: dict, med_id: str) -> int:
        today = self._now().date()
        streak = 0
        for i in range(30):
            day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            day_entries = [
                e for e in data.get("dose_log", [])
                if e["med_id"] == med_id and e["date"] == day
            ]
            if any(e["status"] == "taken" for e in day_entries):
                streak += 1
            elif i > 0:
                break
        return streak

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[MedReminder] Trigger: {trigger!r}")

            data = self._load_data()
            intent = self._classify_intent(trigger or "")
            self.worker.editor_logging_handler.info(f"[MedReminder] Intent: {intent}")

            if intent == "EXIT" or (trigger and any(w in trigger.lower() for w in EXIT_WORDS)):
                await self.capability_worker.speak("Sure, take care.")
                return

            await self._dispatch(intent, trigger or "", data)

            await self.capability_worker.speak(
                "Anything else? You can check your schedule, log a dose, or say done."
            )

            while True:
                reply = await self.capability_worker.user_response()
                if not reply or any(w in reply.lower() for w in EXIT_WORDS):
                    break

                data = self._load_data()
                intent = self._classify_intent(reply)
                self.worker.editor_logging_handler.info(f"[MedReminder] Intent: {intent}")

                if intent == "EXIT":
                    break

                await self._dispatch(intent, reply, data)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[MedReminder] Error: {e!r}")
            await self.capability_worker.speak("Something went wrong. Please try again.")
        finally:
            self.capability_worker.resume_normal_flow()

    async def _dispatch(self, intent: str, text: str, data: dict):
        if intent == "SETUP":
            await self._handle_setup(text, data)
        elif intent == "TAKEN":
            await self._handle_taken(text, data)
        elif intent == "SNOOZE":
            await self._handle_snooze(text, data)
        elif intent == "SKIP":
            await self._handle_skip(text, data)
        elif intent == "STATUS":
            await self._handle_status(data)
        elif intent == "REPORT":
            await self._handle_report(data)
        elif intent == "INFO":
            await self._handle_info(text, data)
        elif intent == "REFILL":
            await self._handle_refill(text, data)
        elif intent == "REMOVE":
            await self._handle_remove(text, data)
