import json
import re
from datetime import datetime
from typing import Optional

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CURIOSITY QUEUE — Background Daemon
# Starts automatically on session connect. Passively monitors conversation
# history every 15s and captures moments when the user voices genuine curiosity:
# "I wonder how X works", "I don't know why Y", "I should look that up".
# Captured topics are stored in curiosity_queue.json for the interactive
# skill to list, explain, and manage.
#
# NOTE: MatchingCapability uses Pydantic — no arbitrary self.* attributes.
# All mutable state lives in a local `s` dict passed between helpers.
# =============================================================================

QUEUE_FILE = "curiosity_queue.json"
POLL_INTERVAL = 15.0
SAVE_EVERY_N_POLLS = 20       # re-sync settings every ~5 minutes
MAX_LLM_CALLS_PER_POLL = 3   # rate-limit Phase 2 LLM calls per cycle (UX-7)
STARTUP_NOTIFY_MIN = 3        # min pending items to announce on connect (UX-1)
DAILY_BRIEF_MIN = 3           # min pending items to trigger daily briefing (UX-10)
MAX_PERSONALITY_INJECTIONS = 3  # cap personality prompt injections per session (UX-2)

# ── Phase 1: Fast keyword filter (no LLM) ───────────────────────────────────
CURIOSITY_TRIGGERS = [
    "i wonder", "i was wondering", "i've always wondered", "ive always wondered",
    "always wondered", "i don't know how", "i dont know how",
    "i don't know why", "i dont know why", "i don't know what", "i dont know what",
    "no idea how", "no idea why", "no idea what",
    "how does", "how do", "why does", "why do", "why is", "why are",
    "what exactly is", "what exactly are", "what exactly does",
    "i'm curious", "im curious", "i'm not sure how", "im not sure how",
    "not sure how", "not sure why", "should look that up", "should google",
    "need to look up", "i forget how", "forgot how", "never understood",
    "interesting how", "funny how", "weird how", "strange how",
]

# ── BUG-3 fix: phrases that match triggers but are NOT curiosity ─────────────
# These are checked BEFORE Phase 1 to avoid LLM calls on conversational speech.
SKIP_PHRASES = [
    "how do you", "how are you", "how can you", "how should you",
    "how do i", "how should i", "how can i", "how will i",
    "why are you", "why do you", "why don't you", "why cant you", "why can't you",
    "why would you", "why did you", "why does it matter",
    "what do you", "what should i", "what can you", "what will you",
    "can you", "could you", "would you", "will you", "shall we",
]


def _new_state() -> dict:
    """Return fresh mutable state dict — lives as a local var, never on self."""
    return {
        "last_processed_index": 0,
        "polls_since_save": 0,
        "instant_explain_enabled": False,
        "startup_notified": False,       # UX-1: only announce once per session
        "last_brief_date": "",           # UX-10: track daily briefing
        "briefed_today": False,          # UX-10: only brief once per day
        "personality_injected_count": 0,  # UX-2: cap personality injections
    }


def _empty_queue_data() -> dict:
    """Return the default empty queue structure."""
    return {
        "queue": [],
        "history": [],
        "settings": {
            "instant_explain": False,
            "last_brief_date": "",       # UX-10: persists across reconnects
        },
        "stats": {"total_captured": 0, "total_answered": 0},
        "meta": {"last_processed_length": 0},  # BUG-5: persists pointer
    }


class CuriosityQueueBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def _load_queue(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(QUEUE_FILE, False)
            if not exists:
                return _empty_queue_data()
            raw = await self.capability_worker.read_file(QUEUE_FILE, False)
            if not raw or not raw.strip():
                return _empty_queue_data()
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[CuriosityQueue] Load error: {e}"
            )
            return _empty_queue_data()

    async def _save_queue(self, data: dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(QUEUE_FILE, False)
            if exists:
                await self.capability_worker.delete_file(QUEUE_FILE, False)
            await self.capability_worker.write_file(
                QUEUE_FILE, json.dumps(data, indent=2), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[CuriosityQueue] Save error: {e}"
            )

    async def _restore_from_file(self, s: dict) -> dict:
        """
        Load persisted queue and seed state from settings.
        BUG-5: restores last_processed_index from meta to avoid re-processing
        old messages on reconnect.
        """
        data = await self._load_queue()
        settings = data.get("settings", {})
        meta = data.get("meta", {})

        s["instant_explain_enabled"] = settings.get("instant_explain", False)
        s["last_brief_date"] = settings.get("last_brief_date", "")
        # BUG-5: restore pointer so old messages aren't re-evaluated
        s["last_processed_index"] = meta.get("last_processed_length", 0)

        pending_count = len([i for i in data.get("queue", []) if not i.get("answered")])
        self.worker.editor_logging_handler.info(
            f"[CuriosityQueue] Restored — {pending_count} pending, "
            f"pointer at {s['last_processed_index']}"
        )
        return data

    # ------------------------------------------------------------------
    # Detection helpers (sync — no await, called inside async watch_loop)
    # ------------------------------------------------------------------

    def _skip_phrase_filter(self, text: str) -> bool:
        """
        BUG-3: Return True if the text is a conversational question directed
        at the assistant, not genuine intellectual curiosity.
        These are checked BEFORE Phase 1 to avoid unnecessary LLM calls.
        """
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in SKIP_PHRASES)

    def _phase1_fast_filter(self, text: str) -> bool:
        """Quick keyword scan — returns True if any curiosity trigger word found."""
        text_lower = text.lower()
        return any(trigger in text_lower for trigger in CURIOSITY_TRIGGERS)

    def _strip_json_fences(self, raw: str) -> str:
        """Remove markdown code fences from LLM response."""
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        return raw

    def _phase2_llm_extract(self, text: str) -> Optional[dict]:
        """
        LLM-based curiosity classifier and topic extractor.
        Called ONLY after skip-phrase and Phase 1 filters pass.
        Returns parsed dict {capture, topic, category} or None on failure.
        """
        prompt = (
            f"The user said: '{text}'\n\n"
            "Does this express genuine curiosity or wonder the user wants to explore?\n\n"
            "YES examples:\n"
            "- 'I wonder how neural networks actually learn'\n"
            "- 'I've always wondered why the sky is blue'\n"
            "- 'I don't know why inflation causes interest rates to rise'\n"
            "- 'I should look up how vaccines work'\n"
            "- 'Funny how time seems to slow down when you're scared'\n\n"
            "NO examples:\n"
            "- 'What's the weather today' (direct command to assistant)\n"
            "- 'Can you play some music' (request to assistant)\n"
            "- 'What time is it?' (practical question, not intellectual)\n"
            "- 'How do I turn this off?' (practical task question)\n"
            "- 'yes', 'okay', 'thanks', 'I don't know' alone (filler)\n\n"
            "Rules:\n"
            "1. If directing a question or request AT the assistant — NO.\n"
            "2. If expressing personal wonder, confusion, or intellectual curiosity — YES.\n"
            "3. Short practical questions ('what time is it') — NO.\n"
            "4. Must have a meaningful topic that could be explained — if none, NO.\n\n"
            "Return ONLY valid JSON, no markdown fences:\n"
            '{"capture": true, "topic": "concise description of what they wonder about", '
            '"category": "how"|"why"|"what"|"other"}\n'
            'OR: {"capture": false, "topic": "", "category": "other"}'
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            cleaned = self._strip_json_fences(raw)
            result = json.loads(cleaned)
            if not result.get("capture"):
                return None
            topic = result.get("topic", "").strip()[:200]
            if not topic:
                return None
            result["topic"] = topic
            return result
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[CuriosityQueue] LLM extract error: {e}"
            )
            return None

    def _is_duplicate(self, topic: str, data: dict) -> bool:
        """
        Word-overlap dedup.
        BUG-4: Checks both unanswered queue items (60% threshold) AND
        recent history items (50% threshold) to prevent re-capturing
        recently-answered curiosities.
        """
        words_new = set(re.findall(r'\b[a-z]+\b', topic.lower()))
        if not words_new:
            return False

        # Check unanswered queue — strict 60% threshold
        for item in data.get("queue", []):
            if item.get("answered"):
                continue
            words_existing = set(re.findall(r'\b[a-z]+\b', item.get("topic", "").lower()))
            if not words_existing:
                continue
            overlap = len(words_new & words_existing) / max(len(words_new), len(words_existing))
            if overlap >= 0.60:
                self.worker.editor_logging_handler.info(
                    f"[CuriosityQueue] Duplicate (queue, {int(overlap*100)}%): {topic}"
                )
                return True

        # BUG-4: Also check last 20 history items — looser 50% threshold
        for item in data.get("history", [])[-20:]:
            words_h = set(re.findall(r'\b[a-z]+\b', item.get("topic", "").lower()))
            if not words_h:
                continue
            overlap = len(words_new & words_h) / max(len(words_new), len(words_h))
            if overlap >= 0.50:
                self.worker.editor_logging_handler.info(
                    f"[CuriosityQueue] Duplicate (history, {int(overlap*100)}%): {topic}"
                )
                return True

        return False

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    async def _add_to_queue(self, text: str, topic: str, category: str, data: dict) -> dict:
        """Append a new curiosity entry and enforce queue/history size limits."""
        entry = {
            "id": str(int(datetime.now().timestamp() * 1000)),
            "topic": topic,
            "raw": text[:500],
            "captured_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "answered_at": None,  # BUG-8: track when answered, not just captured
            "date": datetime.now().strftime("%Y-%m-%d"),
            "answered": False,
            "answer": None,
            "category": category,
        }
        data["queue"].append(entry)
        data["stats"]["total_captured"] = data["stats"].get("total_captured", 0) + 1

        # Queue cap: 50 items — archive oldest answered first, then oldest overall
        if len(data["queue"]) > 50:
            answered = [i for i in data["queue"] if i.get("answered")]
            oldest = min(
                answered if answered else data["queue"],
                key=lambda x: x.get("captured_at", "")
            )
            data["queue"].remove(oldest)
            data.setdefault("history", []).append(oldest)
            self.worker.editor_logging_handler.info(
                f"[CuriosityQueue] Queue overflow — archived: {oldest.get('topic', '')}"
            )

        # History cap: 100 items
        if len(data.get("history", [])) > 100:
            data["history"] = data["history"][-100:]

        return data

    # ------------------------------------------------------------------
    # Main watch loop — ALL mutable state in local `s` dict
    # ------------------------------------------------------------------

    async def watch_loop(self):
        s = _new_state()

        self.worker.editor_logging_handler.info(
            "[CuriosityQueue] daemon started — monitoring for curiosity moments (15s interval)"
        )

        data = await self._restore_from_file(s)

        # UX-1: Startup notification — tell user about pending curiosities once
        pending_on_start = [i for i in data.get("queue", []) if not i.get("answered")]
        if len(pending_on_start) >= STARTUP_NOTIFY_MIN and not s["startup_notified"]:
            count = len(pending_on_start)
            await self.capability_worker.send_interrupt_signal()
            await self.capability_worker.speak(
                f"By the way — you have {count} "
                f"{'curiosity' if count == 1 else 'curiosities'} waiting in your queue. "
                "Say 'curiosity queue' whenever you're ready to explore."
            )
            s["startup_notified"] = True

        while True:
            try:
                history = self.capability_worker.get_full_message_history()
                history = history or []
                current_length = len(history)

                # BUG-5: First-run guard only needed when pointer wasn't restored
                if s["last_processed_index"] == 0 and current_length > 10:
                    s["last_processed_index"] = current_length - 10
                    self.worker.editor_logging_handler.info(
                        f"[CuriosityQueue] First poll: skipping to index {s['last_processed_index']}"
                    )

                # Shrinkage guard: history was trimmed by the platform
                if s["last_processed_index"] > current_length:
                    self.worker.editor_logging_handler.info(
                        "[CuriosityQueue] History shrunk, resetting pointer"
                    )
                    s["last_processed_index"] = max(0, current_length - 3)

                new_msgs = history[s["last_processed_index"]:]
                s["last_processed_index"] = current_length

                llm_calls_this_poll = 0  # UX-7: rate-limit LLM calls

                for msg in new_msgs:
                    if msg.get("role") != "user":
                        continue
                    text = msg.get("content", "")
                    if not isinstance(text, str):
                        continue
                    text = text.strip()

                    # Skip short utterances — too noisy for curiosity detection
                    if not text or len(text.split()) < 5:
                        continue

                    # BUG-3: Skip conversational questions directed at the assistant
                    if self._skip_phrase_filter(text):
                        continue

                    # Phase 1: fast keyword filter (no LLM cost)
                    if not self._phase1_fast_filter(text):
                        continue

                    # UX-7: Rate-limit — max 3 LLM calls per poll cycle
                    if llm_calls_this_poll >= MAX_LLM_CALLS_PER_POLL:
                        self.worker.editor_logging_handler.info(
                            "[CuriosityQueue] LLM rate limit reached for this poll"
                        )
                        break

                    # Phase 2: LLM extraction — only runs if Phase 1 passes
                    result = self._phase2_llm_extract(text)
                    llm_calls_this_poll += 1

                    if result is None:
                        continue

                    topic = result["topic"]
                    category = result["category"]

                    # Load fresh data for accurate dedup check
                    data = await self._load_queue()

                    if self._is_duplicate(topic, data):
                        continue

                    # Capture it
                    data = await self._add_to_queue(text, topic, category, data)

                    # BUG-5: persist pointer in meta before saving
                    data.setdefault("meta", {})["last_processed_length"] = s["last_processed_index"]
                    await self._save_queue(data)
                    s["polls_since_save"] = 0

                    # Re-sync setting from saved data
                    s["instant_explain_enabled"] = data["settings"].get("instant_explain", False)

                    self.worker.editor_logging_handler.info(
                        f"[CuriosityQueue] Captured [{category}]: {topic}"
                    )

                    # UX-2: Inject into agent personality (capped per session)
                    if s["personality_injected_count"] < MAX_PERSONALITY_INJECTIONS:
                        try:
                            self.capability_worker.update_personality_agent_prompt(
                                f"[Curiosity noted]: {topic}"
                            )
                            s["personality_injected_count"] += 1
                        except Exception:
                            pass

                    # Instant explain: notify only — never await user_response() in daemon
                    if s["instant_explain_enabled"]:
                        # UX-9: Better notification copy
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(
                            f"Curious about {topic}? Noted — "
                            "say 'explain my curiosity' anytime and I'll break it down."
                        )

                # UX-10: Daily briefing — on first poll of a new day with pending items
                today = datetime.now().strftime("%Y-%m-%d")
                if today != s["last_brief_date"] and not s["briefed_today"]:
                    data_fresh = await self._load_queue()
                    pending = [i for i in data_fresh.get("queue", []) if not i.get("answered")]
                    if len(pending) >= DAILY_BRIEF_MIN:
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(
                            f"New day! You have {len(pending)} "
                            f"{'curiosity' if len(pending) == 1 else 'curiosities'} "
                            "waiting to explore. Say 'curiosity queue' whenever you're ready."
                        )
                    # Update both in-memory and persisted last_brief_date
                    data_fresh["settings"]["last_brief_date"] = today
                    await self._save_queue(data_fresh)
                    s["last_brief_date"] = today
                    s["briefed_today"] = True

            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[CuriosityQueue] Loop error: {e}"
                )

            # Periodic settings re-sync (picks up toggles made by main.py)
            s["polls_since_save"] += 1
            if s["polls_since_save"] >= SAVE_EVERY_N_POLLS:
                try:
                    fresh = await self._load_queue()
                    settings = fresh.get("settings", {})
                    s["instant_explain_enabled"] = settings.get("instant_explain", False)
                    s["last_brief_date"] = settings.get("last_brief_date", s["last_brief_date"])
                    # BUG-5: also persist pointer on periodic sync
                    fresh.setdefault("meta", {})["last_processed_length"] = s["last_processed_index"]
                    await self._save_queue(fresh)
                    s["polls_since_save"] = 0
                except Exception:
                    pass

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.editor_logging_handler.info(
            "[CuriosityQueue] background.py call() — launching watch_loop"
        )
        self.worker.session_tasks.create(self.watch_loop())
