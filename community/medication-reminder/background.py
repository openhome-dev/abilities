from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "medication_reminder_data"

POLL_INTERVAL = 60.0      # seconds
STARTUP_GRACE = 90        # seconds — skip alerts on cold start
RE_ALERT_MINUTES = 10     # re-alert if no ack after 10 min
MISSED_MINUTES = 30       # mark as missed after 30 min with no ack
REFILL_ALERT_DAYS = 7     # alert when supply drops below this many days


def _empty_data() -> dict:
    return {
        "medications": [],
        "dose_log": [],
        "pending_alerts": [],
    }


def _parse_dt(s: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return datetime.now()


class MedicationReminderBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    _refill_alerted_today: set = set()   # med_ids alerted for refill today
    _last_refill_alert_date: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

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
            self.worker.editor_logging_handler.error(f"[MedReminderBG] Load error: {e!r}")
            return _empty_data()

    def _save_data(self, data: dict):
        try:
            self.capability_worker.create_key(STORAGE_KEY, data)
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, data)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[MedReminderBG] Save error: {e!r}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        """Naive wall-clock time in the user's timezone (falls back to server local)."""
        try:
            return datetime.now(ZoneInfo(self.capability_worker.get_timezone())).replace(tzinfo=None)
        except Exception:
            return datetime.now()

    def _active_meds(self, data: dict) -> list:
        return [m for m in data.get("medications", []) if m.get("active", True)]

    def _is_logged_today(self, data: dict, med_id: str, scheduled_time: str) -> bool:
        today = self._now().strftime("%Y-%m-%d")
        return any(
            e["med_id"] == med_id
            and e.get("date") == today
            and e.get("scheduled_time") == scheduled_time
            and e.get("status") in ("taken", "skipped")
            for e in data.get("dose_log", [])
        )

    def _get_pending(self, data: dict, med_id: str, scheduled_time: str) -> dict:
        today = self._now().strftime("%Y-%m-%d")
        for p in data.get("pending_alerts", []):
            if (p["med_id"] == med_id
                    and p.get("date") == today
                    and p.get("scheduled_time") == scheduled_time):
                return p
        return {}

    def _streak(self, data: dict, med_id: str) -> int:
        today = self._now().date()
        streak = 0
        for i in range(1, 30):
            day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            day_entries = [
                e for e in data.get("dose_log", [])
                if e["med_id"] == med_id and e["date"] == day
            ]
            if any(e["status"] == "taken" for e in day_entries):
                streak += 1
            else:
                break
        return streak

    def _reminder_text(self, med: dict, data: dict) -> str:
        name = med["name"]
        dose = med.get("dose", "")
        instructions = med.get("instructions", "")
        label = f"{name} {dose}".strip()
        streak = self._streak(data, med["id"])

        msg = f"Time for your {label}."
        if instructions:
            msg += f" Remember to {instructions}."
        if streak >= 5:
            msg += f" You've kept up {streak} days in a row — great work."
        msg += " Say 'took it', 'remind me in 30 minutes', or 'skipping this one'."
        return msg

    def _mark_missed(self, data: dict, med_id: str, scheduled_time: str):
        now = self._now()
        today = now.strftime("%Y-%m-%d")
        data.setdefault("dose_log", []).append({
            "med_id": med_id,
            "date": today,
            "scheduled_time": scheduled_time,
            "status": "missed",
            "logged_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        data["pending_alerts"] = [
            p for p in data.get("pending_alerts", [])
            if not (p["med_id"] == med_id
                    and p.get("date") == today
                    and p.get("scheduled_time") == scheduled_time)
        ]

    # ------------------------------------------------------------------
    # Daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        self.capability_worker.resume_normal_flow()
        self.worker.editor_logging_handler.info("[MedReminderBG] Daemon started")

        started_at = datetime.now().timestamp()

        while True:
            try:
                now = self._now()
                today = now.strftime("%Y-%m-%d")
                current_hhmm = now.strftime("%H:%M")
                data = self._load_data()
                daemon_age = datetime.now().timestamp() - started_at
                changed = False

                # Reset daily refill alert tracker
                if self._last_refill_alert_date != today:
                    self._refill_alerted_today = set()
                    self._last_refill_alert_date = today

                if daemon_age <= STARTUP_GRACE:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                meds = self._active_meds(data)

                # 1. Fire new reminders
                for med in meds:
                    for sched_time in med.get("times", []):
                        if current_hhmm != sched_time:
                            continue
                        if self._is_logged_today(data, med["id"], sched_time):
                            continue
                        if self._get_pending(data, med["id"], sched_time):
                            continue

                        data.setdefault("pending_alerts", []).append({
                            "med_id": med["id"],
                            "date": today,
                            "scheduled_time": sched_time,
                            "alerted_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
                            "snoozed_until": None,
                            "re_alerted": False,
                        })
                        changed = True

                        msg = self._reminder_text(med, data)
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(msg)
                        self.worker.editor_logging_handler.info(
                            f"[MedReminderBG] Reminder fired: {med['name']} at {sched_time}"
                        )

                # 2. Re-alert for unacknowledged doses, then mark missed
                for p in list(data.get("pending_alerts", [])):
                    if p.get("snoozed_until"):
                        continue
                    alerted_at = _parse_dt(p.get("alerted_at", ""))
                    minutes_since = (now - alerted_at).total_seconds() / 60

                    if minutes_since >= MISSED_MINUTES:
                        # Mark missed even if it was already re-alerted.
                        self._mark_missed(data, p["med_id"], p["scheduled_time"])
                        changed = True
                        med = next((m for m in meds if m["id"] == p["med_id"]), None)
                        if med:
                            self.worker.editor_logging_handler.info(
                                f"[MedReminderBG] Marked missed: {med['name']} at {p['scheduled_time']}"
                            )
                    elif minutes_since >= RE_ALERT_MINUTES and not p.get("re_alerted"):
                        p["re_alerted"] = True
                        changed = True
                        med = next((m for m in meds if m["id"] == p["med_id"]), None)
                        if med:
                            name = med["name"]
                            dose = med.get("dose", "")
                            label = f"{name} {dose}".strip()
                            await self.capability_worker.send_interrupt_signal()
                            await self.capability_worker.speak(
                                f"Just a follow-up — did you take your {label}? "
                                f"Say 'took it' or 'skipping this one'."
                            )
                            self.worker.editor_logging_handler.info(
                                f"[MedReminderBG] Re-alert fired: {med['name']}"
                            )

                # 3. Re-fire snoozed reminders
                for p in data.get("pending_alerts", []):
                    snoozed_until = p.get("snoozed_until")
                    if not snoozed_until:
                        continue
                    snooze_dt = _parse_dt(snoozed_until)
                    if now < snooze_dt:
                        continue

                    p["snoozed_until"] = None
                    p["re_alerted"] = False
                    p["alerted_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                    changed = True

                    med = next((m for m in meds if m["id"] == p["med_id"]), None)
                    if med:
                        msg = self._reminder_text(med, data)
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(msg)
                        self.worker.editor_logging_handler.info(
                            f"[MedReminderBG] Snooze re-fired: {med['name']}"
                        )

                # 4. Refill countdown alerts
                for med in meds:
                    supply = med.get("supply_count", 0)
                    doses_per_day = med.get("supply_doses_per_day", 1) or 1
                    if supply <= 0:
                        continue
                    if med["id"] in self._refill_alerted_today:
                        continue
                    days_left = supply / doses_per_day
                    if days_left <= REFILL_ALERT_DAYS:
                        self._refill_alerted_today.add(med["id"])
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(
                            f"Heads up — you have about {int(days_left)} day"
                            f"{'s' if int(days_left) != 1 else ''} of {med['name']} left. "
                            f"Say 'I just refilled my {med['name'].lower()}' when you pick it up."
                        )
                        self.worker.editor_logging_handler.info(
                            f"[MedReminderBG] Refill alert: {med['name']} ({int(days_left)} days left)"
                        )

                if changed:
                    self._save_data(data)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[MedReminderBG] Loop error: {e!r}")

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.background_daemon_mode = background_daemon_mode
        # Per-instance refill-alert state (avoid sharing the class-level default).
        self._refill_alerted_today = set()
        self._last_refill_alert_date = ""
        self.worker.session_tasks.create(self.watch_loop())
