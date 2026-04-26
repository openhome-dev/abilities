import json
import re
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# DECISION JOURNAL — Background Daemon
# Auto-starts on session connect. Polls conversation history every 15 seconds.
# Detects when the user makes or deliberates on significant decisions and
# silently captures them to decision_journal.json. Also handles stale-outcome
# nudges (14-day follow-up on high-significance decisions without outcomes)
# and daily briefings when pending-outcome decisions exist.
# =============================================================================

JOURNAL_FILE = "decision_journal.json"
POLL_INTERVAL = 15.0
SAVE_EVERY_N_POLLS = 20
MAX_LLM_CALLS_PER_POLL = 3
STARTUP_NOTIFY_MIN = 2        # min pending-outcome decisions to announce at startup
STALE_OUTCOME_DAYS = 14       # days before nudging about an outstanding outcome
DAILY_BRIEF_MIN = 2           # min pending-outcome decisions to trigger daily brief
MAX_PERSONALITY_INJECTIONS = 3

DECISION_TRIGGERS = [
    # Committed decisions
    "i decided", "i've decided", "i have decided",
    "i made a decision", "i've made my decision", "i made my decision",
    "i'm going with", "i'll go with", "going with",
    "i chose", "i've chosen", "i picked", "i've picked",
    "i made up my mind", "made my choice",
    "going ahead with", "i'm going ahead",
    "i went with", "i settled on", "i landed on",
    "i committed to",
    # Active deliberation
    "i'm torn between", "torn between",
    "can't decide between", "can't choose between",
    "going back and forth", "back and forth on",
    "weighing", "on the fence about",
    "i don't know whether to", "not sure whether to",
    "i'm leaning towards", "leaning toward",
]

SKIP_PHRASES = [
    # Direct requests to agent — not personal decisions
    "should i", "what should i", "what do you think i should",
    "would you decide", "help me decide", "can you decide",
    "do you think i should", "what would you do",
    # Hypothetical / indirect
    "if i had to decide", "hypothetically",
    "let's say i decided", "what if i decided",
    # Third-party — not about the user
    "he decided", "she decided", "they decided",
    "he chose", "she chose", "they chose",
]


def _new_state() -> dict:
    """Return fresh mutable state dict — lives as a local var, never on self."""
    return {
        "last_processed_index": 0,
        "polls_since_save": 0,
        "notify_on_capture": False,
        "startup_notified": False,
        "last_brief_date": "",
        "briefed_today": False,
        "nudge_checked_today": False,
        "personality_injected_count": 0,
    }


def _empty_journal_data() -> dict:
    """Single shared factory — used in all three _load_journal paths."""
    return {
        "decisions": [],
        "history": [],
        "settings": {
            "notify_on_capture": False,
            "last_brief_date": "",
            "last_nudge_date": "",
        },
        "stats": {"total_captured": 0, "total_with_outcomes": 0},
        "meta": {"last_processed_length": 0},
    }


class DecisionJournalBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    #{{register capability}}

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def _load_journal(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(JOURNAL_FILE, False)
            if not exists:
                return _empty_journal_data()
            raw = await self.capability_worker.read_file(JOURNAL_FILE, False)
            if not raw or not raw.strip():
                return _empty_journal_data()
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[DecisionJournal] Load error: {e}")
            return _empty_journal_data()

    async def _save_journal(self, data: dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(JOURNAL_FILE, False)
            if exists:
                await self.capability_worker.delete_file(JOURNAL_FILE, False)
            await self.capability_worker.write_file(
                JOURNAL_FILE, json.dumps(data, indent=2), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[DecisionJournal] Save error: {e}")

    async def _restore_from_file(self, s: dict) -> dict:
        """Restore persisted state into s on session reconnect."""
        data = await self._load_journal()
        settings = data.get("settings", {})
        meta = data.get("meta", {})
        s["notify_on_capture"] = settings.get("notify_on_capture", False)
        s["last_brief_date"] = settings.get("last_brief_date", "")
        s["last_processed_index"] = meta.get("last_processed_length", 0)
        return data

    # ------------------------------------------------------------------
    # Detection helpers (sync)
    # ------------------------------------------------------------------

    def _skip_phrase_filter(self, text: str) -> bool:
        """Returns True if text contains a skip phrase — abort before Phase 1."""
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in SKIP_PHRASES)

    def _phase1_fast_filter(self, text: str) -> bool:
        """Returns True if any decision trigger keyword is present."""
        text_lower = text.lower()
        return any(trigger in text_lower for trigger in DECISION_TRIGGERS)

    def _strip_json_fences(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        return raw

    def _phase2_llm_extract(self, text: str) -> dict | None:
        """Phase 2: LLM extraction. Sync — text_to_text_response is sync."""
        prompt = (
            f"The user said: '{text}'\n\n"
            "Does this express a genuine, significant personal decision made BY the user?\n\n"
            "YES:\n"
            '  "I decided to quit my job"\n'
            '  "I\'m going with the Toyota over the Honda"\n'
            '  "I\'ve made up my mind — I\'m moving to Austin"\n'
            '  "I\'m torn between two job offers"\n'
            '  "I committed to starting therapy"\n\n'
            "NO:\n"
            '  "I\'m going to grab coffee" (trivial — not significant)\n'
            '  "Should I take the job?" (asking the agent — not a decision)\n'
            '  "He decided to leave" (third party — not the user)\n'
            '  "I\'ll check my email" (trivial daily task)\n\n'
            "Rule: Only significant personal decisions by THIS user — career, financial, health, "
            "relationship, personal. Trivial daily choices → significance: low → capture: false.\n\n"
            "Return ONLY valid JSON, no markdown:\n"
            '{"capture": true, "summary": "concise max 150 chars", '
            '"decision_type": "made" or "deliberating", '
            '"category": "career" or "financial" or "health" or "relationship" or "personal" or "other", '
            '"alternatives": ["option A", "option B"], '
            '"significance": "medium" or "high"}\n'
            'OR: {"capture": false}'
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            cleaned = self._strip_json_fences(raw)
            parsed = json.loads(cleaned)
            if not parsed.get("capture"):
                return None
            summary = parsed.get("summary", "").strip()[:150]
            if not summary:
                return None
            return {
                "summary": summary,
                "decision_type": parsed.get("decision_type", "made"),
                "category": parsed.get("category", "other"),
                "alternatives": parsed.get("alternatives", []),
                "significance": parsed.get("significance", "medium"),
            }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[DecisionJournal] Phase 2 parse error: {e}")
            return None

    def _is_duplicate(self, summary: str, data: dict) -> bool:
        """60% word-overlap dedup vs all decisions + 50% vs last 20 history items."""
        words_new = set(re.findall(r'\b[a-z]+\b', summary.lower()))
        if not words_new:
            return False

        for item in data.get("decisions", []):
            words_ex = set(re.findall(r'\b[a-z]+\b', item.get("summary", "").lower()))
            if words_ex:
                overlap = len(words_new & words_ex) / max(len(words_new), len(words_ex), 1)
                if overlap >= 0.60:
                    return True

        for item in data.get("history", [])[-20:]:
            words_h = set(re.findall(r'\b[a-z]+\b', item.get("summary", "").lower()))
            if words_h:
                overlap = len(words_new & words_h) / max(len(words_new), len(words_h), 1)
                if overlap >= 0.50:
                    return True

        return False

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    async def _add_to_decisions(
        self, text: str, summary: str, decision_type: str,
        category: str, alternatives: list, significance: str, data: dict
    ) -> dict:
        entry = {
            "id": str(int(datetime.now().timestamp() * 1000)),
            "summary": summary,
            "raw": text[:500],
            "decision_type": decision_type,
            "category": category,
            "alternatives": alternatives,
            "significance": significance,
            "captured_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "outcome": None,
            "outcome_at": None,
            "outcome_sentiment": None,
            "reflection": None,
            "status": "pending_outcome",
        }
        data["decisions"].append(entry)
        data["stats"]["total_captured"] = data["stats"].get("total_captured", 0) + 1

        # Overflow: max 50 items — archive oldest outcome_recorded first, then oldest
        if len(data["decisions"]) > 50:
            resolved = [d for d in data["decisions"] if d.get("status") == "outcome_recorded"]
            oldest = min(
                resolved if resolved else data["decisions"],
                key=lambda x: x.get("captured_at", "")
            )
            data["decisions"].remove(oldest)
            data.setdefault("history", []).append(oldest)

        # History cap
        if len(data.get("history", [])) > 100:
            data["history"] = data["history"][-100:]

        return data

    # ------------------------------------------------------------------
    # Main daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        s = _new_state()
        self.worker.editor_logging_handler.info("[DecisionJournal] daemon started")
        cached_data = await self._restore_from_file(s)

        # Startup notification: pending-outcome decisions
        pending_outcome = [
            d for d in cached_data.get("decisions", [])
            if d.get("status") == "pending_outcome"
        ]
        if len(pending_outcome) >= STARTUP_NOTIFY_MIN and not s["startup_notified"]:
            count = len(pending_outcome)
            await self.capability_worker.send_interrupt_signal()
            await self.capability_worker.speak(
                f"Just so you know — you have {count} "
                f"{'decision' if count == 1 else 'decisions'} waiting for outcomes. "
                "Say 'decision journal' anytime to update them."
            )
            s["startup_notified"] = True

        while True:
            try:
                history = self.capability_worker.get_full_message_history()
                history = history or []
                current_length = len(history)

                # First-run guard: skip old messages on first session
                if s["last_processed_index"] == 0 and current_length > 10:
                    s["last_processed_index"] = current_length - 10

                # Shrinkage guard: history was trimmed
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
                    if len(text.split()) < 5:
                        continue

                    if self._skip_phrase_filter(text):
                        continue
                    if not self._phase1_fast_filter(text):
                        continue
                    if llm_calls_this_poll >= MAX_LLM_CALLS_PER_POLL:
                        break

                    result = self._phase2_llm_extract(text)
                    llm_calls_this_poll += 1
                    if result is None:
                        continue

                    data = await self._load_journal()
                    if self._is_duplicate(result["summary"], data):
                        self.worker.editor_logging_handler.info(
                            f"[DecisionJournal] Duplicate skipped: {result['summary']}"
                        )
                        continue

                    data = await self._add_to_decisions(
                        text, result["summary"], result["decision_type"],
                        result["category"], result["alternatives"], result["significance"], data
                    )

                    # Persist pointer
                    data.setdefault("meta", {})["last_processed_length"] = s["last_processed_index"]
                    await self._save_journal(data)
                    s["polls_since_save"] = 0

                    self.worker.editor_logging_handler.info(
                        f"[DecisionJournal] Captured [{result['category']}/{result['significance']}]: "
                        f"{result['summary']}"
                    )

                    # Personality injection (cap at MAX_PERSONALITY_INJECTIONS)
                    if s["personality_injected_count"] < MAX_PERSONALITY_INJECTIONS:
                        self.capability_worker.update_personality_agent_prompt(
                            f"[Decision noted]: {result['summary']}"
                        )
                        s["personality_injected_count"] += 1

                    # Real-time notification (if enabled)
                    if s["notify_on_capture"]:
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(
                            f"Just noted a decision: {result['summary']}. "
                            "Say 'decision journal' anytime to reflect on it."
                        )

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[DecisionJournal] Loop error: {e}")

            # ------------------------------------------------------------------
            # Stale-outcome nudge (once per day — HIGH significance, 14+ days old)
            # ------------------------------------------------------------------
            today = datetime.now().strftime("%Y-%m-%d")
            if not s["nudge_checked_today"]:
                try:
                    stale_cutoff = (
                        datetime.now() - timedelta(days=STALE_OUTCOME_DAYS)
                    ).strftime("%Y-%m-%d")
                    data_fresh = await self._load_journal()
                    stale = [
                        d for d in data_fresh.get("decisions", [])
                        if d.get("status") == "pending_outcome"
                        and d.get("significance") == "high"
                        and d.get("date", "") <= stale_cutoff
                    ]
                    last_nudge = data_fresh["settings"].get("last_nudge_date", "")
                    if stale and last_nudge != today:
                        oldest = min(stale, key=lambda x: x.get("date", ""))
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(
                            f"It's been a while — over {STALE_OUTCOME_DAYS} days ago you decided "
                            f"to {oldest['summary']}. How's that going? "
                            "Say 'decision journal' to update it."
                        )
                        data_fresh["settings"]["last_nudge_date"] = today
                        await self._save_journal(data_fresh)
                    s["nudge_checked_today"] = True
                except Exception as e:
                    self.worker.editor_logging_handler.error(
                        f"[DecisionJournal] Stale nudge error: {e}"
                    )

            # ------------------------------------------------------------------
            # Daily briefing (new day + enough pending-outcome decisions)
            # ------------------------------------------------------------------
            if today != s["last_brief_date"] and not s["briefed_today"]:
                try:
                    data_fresh = await self._load_journal()
                    pending = [
                        d for d in data_fresh.get("decisions", [])
                        if d.get("status") == "pending_outcome"
                    ]
                    if len(pending) >= DAILY_BRIEF_MIN:
                        count = len(pending)
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(
                            f"New day! You have {count} "
                            f"{'decision' if count == 1 else 'decisions'} without outcomes recorded. "
                            "Say 'decision journal' whenever you're ready to reflect."
                        )
                    data_fresh["settings"]["last_brief_date"] = today
                    await self._save_journal(data_fresh)
                    s["last_brief_date"] = today
                    s["briefed_today"] = True
                except Exception as e:
                    self.worker.editor_logging_handler.error(
                        f"[DecisionJournal] Daily brief error: {e}"
                    )

            # ------------------------------------------------------------------
            # Periodic settings re-sync (~5 minutes)
            # ------------------------------------------------------------------
            s["polls_since_save"] += 1
            if s["polls_since_save"] >= SAVE_EVERY_N_POLLS:
                try:
                    fresh = await self._load_journal()
                    s["notify_on_capture"] = fresh["settings"].get("notify_on_capture", False)
                    s["last_brief_date"] = fresh["settings"].get(
                        "last_brief_date", s["last_brief_date"]
                    )
                    fresh.setdefault("meta", {})["last_processed_length"] = s["last_processed_index"]
                    await self._save_journal(fresh)
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
