import json
import re
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

DATA_FILE = "conflict_detector.json"

HOTWORDS = {
    "conflict detector", "my conflicts", "any conflicts", "check my conflicts",
    "conflicting plans", "schedule conflicts", "scheduling conflict",
    "what have i committed to", "my commitments", "what commitments do i have",
    "check my schedule", "what's on my plate", "what do i have coming up",
    "add a commitment", "log a commitment",
    "clear my commitments", "wipe my conflicts", "clear conflicts",
    "clear all conflicts", "clear all commitments", "clear all my",
    "dismiss this conflict", "ignore this conflict",
}

_EXIT_PATTERN = re.compile(
    r'\b(stop|exit|quit|done|cancel|bye|goodbye|never\s*mind|no\s*thanks|'
    r"that'?s\s*all|nothing|nah)\b",
    re.IGNORECASE,
)


def _empty_data() -> dict:
    return {
        "commitments": [],
        "conflicts": [],
        "meta": {"last_processed_length": 0},
    }


def _new_commitment(text: str, c_type: str, people: list, date_hint: str,
                    date_resolved: str, time_hint: str) -> dict:
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "id": str(int(datetime.now().timestamp() * 1000)),
        "text": text,
        "type": c_type,
        "people": people,
        "date_hint": date_hint,
        "date_resolved": date_resolved,
        "time_hint": time_hint,
        "duration_hint": "",
        "captured_at": now_str,
        "status": "active",
    }


def _resolve_date(date_hint: str) -> str:
    today = datetime.now()
    h = date_hint.lower().strip()
    if not h:
        return ""
    if "today" in h or "tonight" in h or "this evening" in h:
        return today.strftime("%Y-%m-%d")
    if "tomorrow" in h:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
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
    m = re.search(r'in\s+(\d+)\s+days?', h)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
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


def _relative_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        days = (dt.date() - datetime.now().date()).days
        if days == 0:
            return "today"
        if days == 1:
            return "tomorrow"
        if days < 0:
            return f"{abs(days)} {'day' if abs(days) == 1 else 'days'} ago"
        if days < 7:
            return dt.strftime("%A")
        return dt.strftime("%B %d")
    except Exception:
        return date_str


class ConflictDetectorCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Hotword matching
    # ------------------------------------------------------------------

    def does_match(self, text: str) -> bool:
        t = text.lower().strip()
        return any(hw in t for hw in HOTWORDS)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        if not text or not text.strip():
            return True
        stripped = text.strip().rstrip(".,!?").strip().lower()
        if stripped == "no":
            return True
        return bool(_EXIT_PATTERN.search(text))

    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        if any(kw in t for kw in ("clear", "wipe")) and any(
            kw in t for kw in ("commitment", "conflict", "schedule", "all")
        ):
            return "CLEAR"
        if any(kw in t for kw in ("dismiss", "ignore this", "not a conflict", "false alarm")):
            return "DISMISS"
        if any(kw in t for kw in ("add a commitment", "log a commitment", "add commitment")):
            return "ADD"
        if any(kw in t for kw in (
            "any conflicts", "my conflicts", "show conflicts", "what conflicts",
            "clashing", "conflicting plans", "schedule conflict", "scheduling conflict",
        )):
            return "CONFLICTS"
        return "LIST"

    def _strip_json_fences(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        return raw

    def _find_commitment_by_index(self, idx: int, commitments: list) -> dict | None:
        active = [c for c in commitments if c.get("status") == "active"]
        active_sorted = sorted(active, key=lambda c: c.get("date_resolved", ""))
        if 0 <= idx < len(active_sorted):
            return active_sorted[idx]
        return None

    def _find_conflict_by_index(self, idx: int, conflicts: list) -> dict | None:
        open_conflicts = [cf for cf in conflicts if cf.get("status") == "open"]
        if 0 <= idx < len(open_conflicts):
            return open_conflicts[idx]
        return None

    def _get_commitment_by_id(self, c_id: str, data: dict) -> dict | None:
        for c in data.get("commitments", []):
            if c.get("id") == c_id:
                return c
        return None

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

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_list(self):
        data = await self._load_data()
        active = [c for c in data.get("commitments", []) if c.get("status") == "active"]
        if not active:
            await self.capability_worker.speak(
                "No upcoming commitments tracked yet — just talk naturally "
                "and I'll pick up anything you plan or commit to."
            )
            return

        active_sorted = sorted(active, key=lambda c: c.get("date_resolved", ""))
        top = active_sorted[:8]
        open_conflicts = [cf for cf in data.get("conflicts", []) if cf.get("status") == "open"]

        parts = []
        for i, c in enumerate(top):
            when = _relative_date(c["date_resolved"]) if c.get("date_resolved") else c.get("date_hint", "")
            time_clause = f" at {c['time_hint']}" if c.get("time_hint") else ""
            parts.append(f"{i + 1}. {c['text']} — {when}{time_clause}")

        suffix = f" and {len(active) - 8} more" if len(active) > 8 else ""
        conflict_clause = (
            f" {len(open_conflicts)} "
            f"{'conflict' if len(open_conflicts) == 1 else 'conflicts'} detected."
            if open_conflicts else ""
        )

        await self.capability_worker.speak(
            f"You have {len(active)} upcoming "
            f"{'commitment' if len(active) == 1 else 'commitments'}{suffix}."
            f"{conflict_clause} "
            + ". ".join(parts) + "."
        )

        await self.capability_worker.speak(
            "Say a number for details, say conflicts to review clashes, or stop."
            if open_conflicts else
            "Say a number for details, or stop."
        )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        r = reply.lower()
        if any(kw in r for kw in ("conflict", "clash", "overlap")):
            await self._handle_conflicts()
            return

        num_match = re.search(r'\b(\d+)\b', reply)
        if num_match:
            idx = int(num_match.group(1)) - 1
            c = self._find_commitment_by_index(idx, data.get("commitments", []))
            if c:
                people_clause = (
                    f" with {', '.join(c['people'])}" if c.get("people") else ""
                )
                time_clause = f" at {c['time_hint']}" if c.get("time_hint") else ""
                dur_clause = f", takes {c['duration_hint']}" if c.get("duration_hint") else ""
                when = _relative_date(c["date_resolved"]) if c.get("date_resolved") else c.get("date_hint", "")
                await self.capability_worker.speak(
                    f"{c['text']}{people_clause} — {when}{time_clause}{dur_clause}."
                )
                await self.capability_worker.speak(
                    "Say another number for details, say conflicts, or stop."
                    if open_conflicts else
                    "Say another number for details, or stop."
                )
                follow = await self.capability_worker.user_response()
                if not self._is_exit(follow):
                    if any(kw in follow.lower() for kw in ("conflict", "clash", "overlap")):
                        await self._handle_conflicts()
                    else:
                        num_m = re.search(r'\b(\d+)\b', follow)
                        if num_m:
                            idx2 = int(num_m.group(1)) - 1
                            c2 = self._find_commitment_by_index(idx2, data.get("commitments", []))
                            if c2:
                                p2 = f" with {', '.join(c2['people'])}" if c2.get("people") else ""
                                t2 = f" at {c2['time_hint']}" if c2.get("time_hint") else ""
                                d2 = f", takes {c2['duration_hint']}" if c2.get("duration_hint") else ""
                                w2 = _relative_date(c2["date_resolved"]) if c2.get("date_resolved") else c2.get("date_hint", "")
                                await self.capability_worker.speak(
                                    f"{c2['text']}{p2} — {w2}{t2}{d2}."
                                )

    async def _handle_conflicts(self):
        data = await self._load_data()
        open_conflicts = [cf for cf in data.get("conflicts", []) if cf.get("status") == "open"]
        if not open_conflicts:
            await self.capability_worker.speak("No conflicts detected — your schedule looks clean.")
            return

        parts = []
        for i, cf in enumerate(open_conflicts[:5]):
            c_a = self._get_commitment_by_id(cf.get("commitment_a_id", ""), data)
            c_b = self._get_commitment_by_id(cf.get("commitment_b_id", ""), data)
            label_a = c_a["text"] if c_a else "a previous commitment"
            label_b = c_b["text"] if c_b else "a previous commitment"
            severity_tag = " (hard conflict)" if cf.get("severity") == "hard" else ""
            parts.append(
                f"{i + 1}. {label_a} vs {label_b}{severity_tag} — {cf['reason']}"
            )

        if not parts:
            await self.capability_worker.speak("No conflicts detected — your schedule looks clean.")
            return

        more_clause = " Showing the first 5." if len(open_conflicts) > 5 else ""
        await self.capability_worker.speak(
            f"You have {len(open_conflicts)} "
            f"{'conflict' if len(open_conflicts) == 1 else 'conflicts'}.{more_clause} "
            + ". ".join(parts) + "."
        )

        await self.capability_worker.speak(
            "Say a number to dismiss one, say all clear to dismiss them all, or stop."
        )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        r = reply.lower()
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        if "all" in r and any(kw in r for kw in ("clear", "done", "dismiss", "resolved")):
            confirmed = await self.capability_worker.run_confirmation_loop(
                f"Dismiss all {len(open_conflicts)} conflicts?"
            )
            if confirmed:
                for cf in open_conflicts:
                    cf["status"] = "dismissed"
                    cf["dismissed_at"] = now_str
                await self._save_data(data)
                await self.capability_worker.speak("Done — all conflicts dismissed.")
            return

        num_match = re.search(r'\b(\d+)\b', reply)
        if num_match:
            idx = int(num_match.group(1)) - 1
            cf = self._find_conflict_by_index(idx, data.get("conflicts", []))
            if cf:
                cf["status"] = "dismissed"
                cf["dismissed_at"] = now_str
                await self._save_data(data)
                remaining = len([c for c in data.get("conflicts", []) if c.get("status") == "open"])
                if remaining:
                    await self.capability_worker.speak(
                        f"Dismissed. {remaining} "
                        f"{'conflict' if remaining == 1 else 'conflicts'} still open — "
                        "say 'conflict detector' to review the rest."
                    )
                else:
                    await self.capability_worker.speak("Dismissed — no more conflicts.")

    def _quick_conflict_hint(self, new_c: dict, data: dict) -> str | None:
        new_date = new_c.get("date_resolved", "")
        if not new_date:
            return None
        try:
            new_dt = datetime.strptime(new_date, "%Y-%m-%d").date()
        except ValueError:
            return None
        adjacent_dates = [
            (new_dt + timedelta(days=d)).strftime("%Y-%m-%d") for d in (-1, 1)
        ]
        same_day = [
            c for c in data.get("commitments", [])
            if c.get("status") == "active"
            and c.get("id") != new_c.get("id")
            and c.get("date_resolved") == new_date
        ]
        if new_c.get("type") == "travel":
            adjacent = [
                c for c in data.get("commitments", [])
                if c.get("status") == "active"
                and c.get("date_resolved") in adjacent_dates
            ]
        else:
            adjacent = [
                c for c in data.get("commitments", [])
                if c.get("status") == "active"
                and c.get("type") == "travel"
                and c.get("date_resolved") in adjacent_dates
            ]
        candidates = same_day + adjacent
        if not candidates:
            return None
        return ", ".join(c["text"] for c in candidates[:2])

    async def _handle_add(self, trigger_text: str):
        await self.capability_worker.speak("What's the commitment?")
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return
        commitment_text = reply.strip()[:120]

        await self.capability_worker.speak("When is it?")
        date_reply = await self.capability_worker.user_response()
        if self._is_exit(date_reply):
            return
        date_hint = date_reply.strip()
        date_resolved = _resolve_date(date_hint)

        if not date_resolved:
            await self.capability_worker.speak(
                "I couldn't work out that date — try something like 'Friday' or 'next Monday'."
            )
            return

        await self.capability_worker.speak("Any specific time?")
        time_reply = await self.capability_worker.user_response()
        time_hint = (
            "" if self._is_exit(time_reply) or "no" in time_reply.lower()
            else time_reply.strip()[:30]
        )

        data = await self._load_data()
        new_c = _new_commitment(
            commitment_text, "task", [], date_hint, date_resolved, time_hint
        )
        data["commitments"].append(new_c)
        data.setdefault("meta", {})
        await self._save_data(data)
        when = _relative_date(date_resolved)
        hint = self._quick_conflict_hint(new_c, data)
        if hint:
            await self.capability_worker.speak(
                f"Saved — {commitment_text} on {when}. "
                f"Heads up: you also have {hint} around that time — "
                "say 'conflict detector' to review."
            )
        else:
            await self.capability_worker.speak(
                f"Saved — {commitment_text} on {when}."
            )

    async def _handle_dismiss(self):
        data = await self._load_data()
        open_conflicts = [cf for cf in data.get("conflicts", []) if cf.get("status") == "open"]
        if not open_conflicts:
            await self.capability_worker.speak("No open conflicts to dismiss.")
            return

        if len(open_conflicts) == 1:
            cf = open_conflicts[0]
            c_a = self._get_commitment_by_id(cf.get("commitment_a_id", ""), data)
            c_b = self._get_commitment_by_id(cf.get("commitment_b_id", ""), data)
            label_a = c_a["text"] if c_a else "a previous commitment"
            label_b = c_b["text"] if c_b else "a previous commitment"
            confirmed = await self.capability_worker.run_confirmation_loop(
                f"Dismiss: {label_a} vs {label_b}?"
            )
            if confirmed:
                cf["status"] = "dismissed"
                cf["dismissed_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                await self._save_data(data)
                await self.capability_worker.speak("Dismissed.")
            return

        await self._handle_conflicts()

    async def _handle_clear(self):
        data = await self._load_data()
        active_count = len([c for c in data.get("commitments", []) if c.get("status") == "active"])
        open_conflict_count = len([cf for cf in data.get("conflicts", []) if cf.get("status") == "open"])
        if active_count == 0 and open_conflict_count == 0:
            await self.capability_worker.speak("Nothing to clear — no active commitments on file.")
            return

        if active_count == 0:
            prompt = (
                f"Clear {open_conflict_count} open "
                f"{'conflict' if open_conflict_count == 1 else 'conflicts'}?"
            )
        else:
            prompt = (
                f"Clear all {active_count} "
                f"{'commitment' if active_count == 1 else 'commitments'} and conflicts?"
            )
        confirmed = await self.capability_worker.run_confirmation_loop(prompt)
        if confirmed:
            data["commitments"] = []
            data["conflicts"] = []
            await self._save_data(data)
            await self.capability_worker.speak("Done — everything cleared.")
        else:
            await self.capability_worker.speak("Keeping everything.")

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger_text = await self.capability_worker.wait_for_complete_transcription()
            if not trigger_text or not isinstance(trigger_text, str):
                trigger_text = ""

            intent = self._classify_intent(trigger_text)
            self.worker.editor_logging_handler.info(
                f"[ConflictDetector] Intent: {intent} | Trigger: {trigger_text[:80]}"
            )

            if intent == "LIST":
                await self._handle_list()
            elif intent == "CONFLICTS":
                await self._handle_conflicts()
            elif intent == "ADD":
                await self._handle_add(trigger_text)
            elif intent == "DISMISS":
                await self._handle_dismiss()
            elif intent == "CLEAR":
                await self._handle_clear()
            else:
                await self.capability_worker.speak(
                    "I can show your upcoming commitments, flag any conflicts, "
                    "or add something manually. What would you like?"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ConflictDetector] Skill error: {e}")
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Try asking again in a moment."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())
