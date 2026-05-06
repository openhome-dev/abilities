import json
import re
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

DATA_FILE = "conflict_detector.json"
POLL_INTERVAL = 15.0
SAVE_EVERY_N_POLLS = 20
MAX_LLM_CALLS_PER_POLL = 3
MAX_COMMITMENTS = 200
EXPIRY_AFTER_DAYS = 1
CONFLICT_WINDOW_DAYS = 14

SKIP_PHRASES = [
    "can you", "could you", "would you", "will you",
    "hypothetically", "if i were", "let's say", "what if",
    "imagine if", "pretend", "just say",
    "what do you think", "do you think",
]


def _new_state() -> dict:
    return {
        "last_processed_index": 0,
        "polls_since_save": 0,
        "startup_notified": False,
        "current_day": "",
    }


def _empty_data() -> dict:
    return {
        "commitments": [],
        "conflicts": [],
        "meta": {"last_processed_length": 0},
    }


def _new_commitment(text: str, c_type: str, people: list, date_hint: str,
                    date_resolved: str, time_hint: str, duration_hint: str) -> dict:
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "id": str(int(datetime.now().timestamp() * 1000)),
        "text": text,
        "type": c_type,
        "people": people,
        "date_hint": date_hint,
        "date_resolved": date_resolved,
        "time_hint": time_hint,
        "duration_hint": duration_hint,
        "captured_at": now_str,
        "status": "active",
    }


def _new_conflict(id_a: str, id_b: str, reason: str, severity: str) -> dict:
    return {
        "id": f"cf_{int(datetime.now().timestamp() * 1000)}",
        "commitment_a_id": id_a,
        "commitment_b_id": id_b,
        "reason": reason,
        "severity": severity,
        "detected_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "alerted": False,
        "status": "open",
    }


def _resolve_date(date_hint: str) -> str:
    today = datetime.now()
    h = date_hint.lower().strip()
    if not h:
        return ""
    if "today" in h:
        return today.strftime("%Y-%m-%d")
    if "tomorrow" in h:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if "tonight" in h or "this evening" in h:
        return today.strftime("%Y-%m-%d")
    if "after the weekend" in h or "after weekend" in h:
        days = (0 - today.weekday()) % 7 or 7
        return (today + timedelta(days=days)).strftime("%Y-%m-%d")
    if "weekend" in h:
        days = (5 - today.weekday()) % 7 or 7
        return (today + timedelta(days=days)).strftime("%Y-%m-%d")
    if "next week" in h:
        return (today + timedelta(days=7)).strftime("%Y-%m-%d")
    if "this week" in h:
        return (today + timedelta(days=3)).strftime("%Y-%m-%d")
    if "next month" in h:
        return (today + timedelta(days=30)).strftime("%Y-%m-%d")
    day_offsets = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    for day_name, target_weekday in day_offsets.items():
        if day_name in h:
            days = (target_weekday - today.weekday()) % 7 or 7
            return (today + timedelta(days=days)).strftime("%Y-%m-%d")
    # "in X days"
    m = re.search(r'in\s+(\d+)\s+days?', h)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    # "May 10", "10th May", etc.
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    for month_name, month_num in month_names.items():
        if month_name in h:
            day_m = re.search(r'(\d{1,2})', h)
            if day_m:
                try:
                    year = today.year
                    dt = datetime(year, month_num, int(day_m.group(1)))
                    if dt.date() < today.date():
                        dt = datetime(year + 1, month_num, int(day_m.group(1)))
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass
    return ""


class ConflictDetectorBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def _load_data(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(DATA_FILE, False)
            if not exists:
                return _empty_data()
            raw = await self.capability_worker.read_file(DATA_FILE, False)
            if not raw or not raw.strip():
                return _empty_data()
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ConflictDetector] Load error: {e}")
            return _empty_data()

    async def _save_data(self, data: dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(DATA_FILE, False)
            if exists:
                await self.capability_worker.delete_file(DATA_FILE, False)
            await self.capability_worker.write_file(
                DATA_FILE, json.dumps(data, indent=2), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ConflictDetector] Save error: {e}")

    async def _restore_from_file(self, s: dict) -> dict:
        data = await self._load_data()
        s["last_processed_index"] = data.get("meta", {}).get("last_processed_length", 0)
        return data

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _skip_phrase_filter(self, text: str) -> bool:
        t = text.lower()
        return any(phrase in t for phrase in SKIP_PHRASES)

    def _phase1_fast_filter(self, text: str) -> bool:
        return len(text.split()) >= 4

    def _strip_json_fences(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        return raw

    def _phase2_llm_extract(self, text: str) -> list:
        prompt = (
            f"The user said: '{text}'\n\n"
            "Extract any concrete plans or commitments the user is personally making.\n\n"
            "Look for:\n"
            "- Scheduled events: meetings, calls, appointments with a date\n"
            "- Travel: flights, drives, trips\n"
            "- Deadlines: tasks to complete by a specific date\n"
            "- Social plans: lunch, dinner, events with a date\n\n"
            "For each commitment found, extract:\n"
            "1. text: brief description of the commitment (max 80 chars)\n"
            "2. type: one of meeting / call / travel / task / social / deadline\n"
            "3. people: list of people involved (first names only, empty list if none)\n"
            "4. date_hint: the date/time reference exactly as spoken (e.g. 'Friday', 'next Monday')\n"
            "5. time_hint: specific time if mentioned, else empty string\n"
            "6. duration_hint: how long it takes if mentioned, else empty string\n\n"
            "Rules:\n"
            "- Only capture commitments the user is MAKING (I'll, I'm, I have, I need to, I promised)\n"
            "- Skip things others are doing that don't involve the user\n"
            "- Skip vague plans with no time reference ('I should call him sometime')\n"
            "- Skip maybes and hypotheticals ('I might go', 'maybe I'll')\n"
            "- Skip past events already completed\n\n"
            "Return ONLY valid JSON, no markdown:\n"
            "{\"commitments\": [{\"text\": \"call Marcus\", \"type\": \"call\", "
            "\"people\": [\"Marcus\"], \"date_hint\": \"Friday\", "
            "\"time_hint\": \"\", \"duration_hint\": \"\"}]}\n"
            "OR if no commitments: {\"commitments\": []}"
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            cleaned = self._strip_json_fences(raw)
            parsed = json.loads(cleaned)
            commitments = parsed.get("commitments", [])
            return commitments if isinstance(commitments, list) else []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ConflictDetector] Extract error: {e}")
            return []

    def _is_duplicate_commitment(self, text: str, date_resolved: str, data: dict) -> bool:
        words_new = set(re.findall(r'\b[a-z]+\b', text.lower()))
        if not words_new:
            return False
        for c in data.get("commitments", []):
            if c.get("status") != "active":
                continue
            if c.get("date_resolved", "") != date_resolved:
                continue
            words_ex = set(re.findall(r'\b[a-z]+\b', c.get("text", "").lower()))
            if words_ex:
                # Subset check: shorter phrase fully contained in longer is a duplicate
                if words_new.issubset(words_ex) or words_ex.issubset(words_new):
                    return True
                overlap = len(words_new & words_ex) / max(len(words_new), len(words_ex), 1)
                if overlap >= 0.70:
                    return True
        return False

    def _conflict_pair_exists(self, id_a: str, id_b: str, data: dict) -> bool:
        for cf in data.get("conflicts", []):
            if cf.get("status") == "dismissed":
                continue
            pair = {cf.get("commitment_a_id"), cf.get("commitment_b_id")}
            if pair == {id_a, id_b}:
                return True
        return False

    def _run_conflict_check(self, new_c: dict, data: dict) -> list:
        new_date = new_c.get("date_resolved", "")
        if not new_date:
            return []

        today = datetime.now().date()
        try:
            new_dt = datetime.strptime(new_date, "%Y-%m-%d").date()
            if new_dt < today:
                return []
        except ValueError:
            return []

        cutoff = (today + timedelta(days=CONFLICT_WINDOW_DAYS)).strftime("%Y-%m-%d")
        candidates = [
            c for c in data.get("commitments", [])
            if c.get("status") == "active"
            and c.get("id") != new_c.get("id")
            and c.get("date_resolved", "") == new_date
            and c.get("date_resolved", "") <= cutoff
        ]

        # Adjacent-date check relative to the commitment's own date (not today)
        adjacent_dates = [
            (new_dt + timedelta(days=d)).strftime("%Y-%m-%d")
            for d in (-1, 1)
        ]
        if new_c.get("type") == "travel":
            # Travel commitment: check ALL adjacent-day items — any could be blocked
            adjacent_candidates = [
                c for c in data.get("commitments", [])
                if c.get("status") == "active"
                and c.get("id") != new_c.get("id")
                and c.get("date_resolved", "") in adjacent_dates
                and c not in candidates
            ]
        else:
            # Non-travel commitment: check only travel on adjacent days
            adjacent_candidates = [
                c for c in data.get("commitments", [])
                if c.get("status") == "active"
                and c.get("id") != new_c.get("id")
                and c.get("type") == "travel"
                and c.get("date_resolved", "") in adjacent_dates
                and c not in candidates
            ]
        candidates = candidates + adjacent_candidates

        if not candidates:
            return []

        new_conflicts = []
        for candidate in candidates:
            if self._conflict_pair_exists(new_c["id"], candidate["id"], data):
                continue
            conflict = self._llm_check_conflict(new_c, candidate)
            if conflict:
                new_conflicts.append((candidate, conflict["reason"], conflict["severity"]))

        return new_conflicts

    def _llm_check_conflict(self, c_a: dict, c_b: dict) -> dict | None:
        time_a = f" at {c_a['time_hint']}" if c_a.get("time_hint") else ""
        time_b = f" at {c_b['time_hint']}" if c_b.get("time_hint") else ""
        dur_a = f" (takes {c_a['duration_hint']})" if c_a.get("duration_hint") else ""
        dur_b = f" (takes {c_b['duration_hint']})" if c_b.get("duration_hint") else ""

        same_day = c_a["date_resolved"] == c_b["date_resolved"]
        adjacent_note = (
            "" if same_day else
            "Note: these are on adjacent days. Treat overnight travel the night before "
            "any other commitment as a SOFT conflict — flag it even if technically possible.\n\n"
        )
        prompt = (
            f"Do these two commitments conflict with each other?\n\n"
            f"Commitment A: \"{c_a['text']}\""
            f" on {c_a['date_resolved']}{time_a}{dur_a}\n"
            f"Commitment B: \"{c_b['text']}\""
            f" on {c_b['date_resolved']}{time_b}{dur_b}\n\n"
            f"{adjacent_note}"
            "A conflict exists if:\n"
            "- They overlap in time and require being in two places\n"
            "- One is travel that runs into or through the other's time window\n"
            "- Overnight or evening travel the day before creates risk for next-day commitments\n"
            "- A deadline is incompatible with being away or in transit\n\n"
            "Return ONLY valid JSON:\n"
            "{\"conflicts\": true, \"reason\": \"one sentence explanation\", "
            "\"severity\": \"hard or soft\"}\n"
            "OR {\"conflicts\": false}"
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            cleaned = self._strip_json_fences(raw)
            result = json.loads(cleaned)
            if result.get("conflicts"):
                return {
                    "reason": result.get("reason", "These commitments may clash."),
                    "severity": result.get("severity", "soft"),
                }
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ConflictDetector] Conflict check error: {e}")
            return None

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def _expire_stale_commitments(self, data: dict) -> dict:
        today = datetime.now().date()
        cutoff = today - timedelta(days=EXPIRY_AFTER_DAYS)
        for c in data.get("commitments", []):
            if c.get("status") != "active":
                continue
            date_str = c.get("date_resolved", "")
            if not date_str:
                continue
            try:
                if datetime.strptime(date_str, "%Y-%m-%d").date() < cutoff:
                    c["status"] = "expired"
            except ValueError:
                pass
        return data

    # ------------------------------------------------------------------
    # Main daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        s = _new_state()
        self.worker.editor_logging_handler.info("[ConflictDetector] daemon started")
        cached_data = await self._restore_from_file(s)
        self.capability_worker.resume_normal_flow()

        # Startup: alert on any open unalerted conflicts from previous sessions
        try:
            unalerted = [
                cf for cf in cached_data.get("conflicts", [])
                if cf.get("status") == "open" and not cf.get("alerted")
            ]
            if unalerted and not s["startup_notified"]:
                count = len(unalerted)
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(
                    f"Just so you know — {count} schedule "
                    f"{'conflict was' if count == 1 else 'conflicts were'} "
                    "detected from your recent plans. Say 'conflict detector' to review."
                )
                s["startup_notified"] = True
        except Exception:
            pass

        while True:
            try:
                history = self.capability_worker.get_full_message_history()
                history = history or []
                current_length = len(history)

                if s["last_processed_index"] == 0 and current_length > 10:
                    s["last_processed_index"] = current_length - 10
                if s["last_processed_index"] > current_length:
                    s["last_processed_index"] = max(0, current_length - 3)

                new_msgs = history[s["last_processed_index"]:]
                s["last_processed_index"] = current_length

                llm_calls_this_poll = 0
                for msg in new_msgs:
                    if msg.get("role") != "user":
                        continue
                    text = msg.get("content", "")
                    if not isinstance(text, str):
                        continue
                    text = text.strip()

                    if self._skip_phrase_filter(text):
                        continue
                    if not self._phase1_fast_filter(text):
                        continue
                    if llm_calls_this_poll >= MAX_LLM_CALLS_PER_POLL:
                        break

                    extracted = self._phase2_llm_extract(text)
                    llm_calls_this_poll += 1
                    if not extracted:
                        self.worker.editor_logging_handler.info(
                            f"[ConflictDetector] No commitments extracted: {text[:60]}"
                        )
                        continue

                    data = await self._load_data()
                    changed = False
                    pending_alerts = []

                    for c_data in extracted:
                        raw_text = c_data.get("text", "").strip()[:120]
                        c_type = c_data.get("type", "task")
                        people = [p.strip() for p in c_data.get("people", []) if p.strip()][:5]
                        date_hint = c_data.get("date_hint", "").strip()
                        time_hint = c_data.get("time_hint", "").strip()
                        duration_hint = c_data.get("duration_hint", "").strip()

                        if not raw_text or not date_hint:
                            self.worker.editor_logging_handler.info(
                                f"[ConflictDetector] Skipped (no date): {raw_text[:60]}"
                            )
                            continue

                        date_resolved = _resolve_date(date_hint)
                        if not date_resolved:
                            continue

                        if self._is_duplicate_commitment(raw_text, date_resolved, data):
                            continue

                        if len(data.get("commitments", [])) >= MAX_COMMITMENTS:
                            expired = [c for c in data["commitments"] if c.get("status") == "expired"]
                            pool = expired or [c for c in data["commitments"] if c.get("status") == "active"]
                            if pool:
                                oldest = min(pool, key=lambda c: c.get("captured_at", ""))
                                data["commitments"].remove(oldest)

                        new_c = _new_commitment(
                            raw_text, c_type, people, date_hint,
                            date_resolved, time_hint, duration_hint
                        )
                        data["commitments"].append(new_c)
                        changed = True

                        self.worker.editor_logging_handler.info(
                            f"[ConflictDetector] Captured: {raw_text[:60]} on {date_resolved}"
                        )

                        new_conflicts = self._run_conflict_check(new_c, data)
                        for other_c, reason, severity in new_conflicts:
                            cf = _new_conflict(new_c["id"], other_c["id"], reason, severity)
                            data["conflicts"].append(cf)
                            self.worker.editor_logging_handler.info(
                                f"[ConflictDetector] Conflict: {new_c['text'][:40]} "
                                f"vs {other_c['text'][:40]}"
                            )
                            cf["alerted"] = True
                            pending_alerts.append((new_c["text"], other_c["text"], reason))

                    if changed:
                        data.setdefault("meta", {})["last_processed_length"] = s["last_processed_index"]
                        await self._save_data(data)
                        s["polls_since_save"] = 0

                    for alert_a, alert_b, alert_reason in pending_alerts:
                        try:
                            await self.capability_worker.send_interrupt_signal()
                            await self.capability_worker.speak(
                                f"Heads up — you said you'd {alert_a} "
                                f"but you also mentioned {alert_b}. "
                                f"{alert_reason}. Say 'conflict detector' to review."
                            )
                        except Exception as e:
                            self.worker.editor_logging_handler.error(
                                f"[ConflictDetector] Alert error: {e}"
                            )

                # Daily maintenance
                today_str = datetime.now().strftime("%Y-%m-%d")
                if today_str != s["current_day"]:
                    s["current_day"] = today_str
                    data = await self._load_data()
                    data = self._expire_stale_commitments(data)
                    data.setdefault("meta", {})["last_processed_length"] = s["last_processed_index"]
                    await self._save_data(data)
                    s["polls_since_save"] = 0

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[ConflictDetector] Loop error: {e}")

            s["polls_since_save"] += 1
            if s["polls_since_save"] >= SAVE_EVERY_N_POLLS:
                try:
                    fresh = await self._load_data()
                    fresh.setdefault("meta", {})["last_processed_length"] = s["last_processed_index"]
                    await self._save_data(fresh)
                    s["polls_since_save"] = 0
                except Exception:
                    pass

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.background_daemon_mode = background_daemon_mode
        self.worker.session_tasks.create(self.watch_loop())
