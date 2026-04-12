import json
import re
import time
import random
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CONVERSATION INSIGHTS COACH — Background Daemon
# Starts automatically on session connect. Passively monitors conversation
# history every 20s and analyzes HOW the user communicates: filler words,
# hedging language, question ratio, vocabulary diversity, and utterance length.
# Results are persisted to insights_stats.json for the interactive skill to read.
#
# NOTE: MatchingCapability uses Pydantic — no arbitrary self.* attributes.
# All mutable state lives in a local `s` dict passed between helpers.
# =============================================================================

# ── Filler word detection ────────────────────────────────────────────────────
MULTI_WORD_FILLERS = [
    "you know", "i mean", "sort of", "kind of",
    "at the end of the day", "to be honest", "to be fair",
    "basically like",
]

SINGLE_WORD_FILLERS = {
    "um", "uh", "uhh", "umm", "erm", "hmm", "hm",
    "basically", "literally", "actually", "right",
    "anyway", "anyways", "whatever",
}

LIKE_NON_FILLER_PATTERNS = [
    re.compile(r'\b(i|you|we|they|he|she|it|who|that|which)\s+like\b', re.IGNORECASE),
    re.compile(r'\b(look|looks|sound|sounds|feel|feels|seem|seems|taste|tastes)s?\s+like\b', re.IGNORECASE),
    re.compile(r'\b(would|do|don\'t|dont|did|didn\'t|didnt|will|can|could|should|might)\s+like\b', re.IGNORECASE),
    re.compile(r'^like\b', re.IGNORECASE),
]

# ── Hedging language ─────────────────────────────────────────────────────────
MULTI_WORD_HEDGES = [
    "i think", "i guess", "i suppose", "i feel like",
    "kind of", "sort of", "not sure", "i'm not sure",
    "might be", "could be", "i believe",
]

SINGLE_WORD_HEDGES = {
    "maybe", "perhaps", "probably", "possibly",
    "apparently", "seemingly",
}

# ── Question-starting words ──────────────────────────────────────────────────
QUESTION_STARTERS = {"who", "what", "when", "where", "why", "how", "is", "are",
                     "was", "were", "will", "would", "can", "could", "should",
                     "do", "does", "did", "have", "has", "had"}

# ── Nudge messages pool ─────────────────────────────────────────────────────
NUDGE_MESSAGES = [
    "Quick tip — try pausing for a beat instead of filling the gap. You're doing great!",
    "Heads up — noticed a few filler words there. A confident pause works just as well.",
    "Small note — you used some filler words just now. No worries, just something to be aware of.",
    "Just a gentle nudge — watch those fillers. Your ideas are strong, let them stand on their own!",
    "Nice thought! Tip: try replacing filler words with a brief pause. Sounds more polished.",
]

STATS_FILE = "insights_stats.json"
POLL_INTERVAL = 20.0
SAVE_EVERY_N_POLLS = 30
NUDGE_COOLDOWN_SECS = 120
MAX_UNIQUE_WORDS = 5000


def _new_state() -> dict:
    """Return a fresh mutable state dict (lives as a local var, never on self)."""
    return {
        "total_utterances": 0,
        "total_words": 0,
        "unique_words": set(),
        "filler_counts": {},
        "hedging_counts": {},
        "question_count": 0,
        "statement_count": 0,
        "utterance_lengths": [],
        "new_vocab_words": set(),
        "repeat_count": 0,
        "last_processed_index": 0,
        "polls_since_save": 0,
        "session_date": datetime.now().strftime("%Y-%m-%d"),
        "goal": None,
        "nudge_enabled": False,
        "prev_vocab": set(),
        "nudge_pending": False,
        "nudge_trigger_word": "",
        "nudge_trigger_count": 0,
        "last_nudge_time": 0.0,
    }


def _empty_stats() -> dict:
    return {
        "current_session": {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_utterances": 0,
            "total_words": 0,
            "unique_word_count": 0,
            "filler_counts": {},
            "hedging_counts": {},
            "question_count": 0,
            "statement_count": 0,
            "avg_utterance_length": 0.0,
            "new_vocab_words": [],
            "repeat_count": 0,
        },
        "daily_history": [],
        "settings": {
            "nudge_enabled": False,
            "filler_goal": None,
        },
    }


class ConversationInsightsBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Filler & hedge detection — pure Python, no LLM, no self-state
    # ------------------------------------------------------------------

    def _is_like_filler(self, text, match_start):
        for pattern in LIKE_NON_FILLER_PATTERNS:
            window = text[max(0, match_start - 25):match_start + 10]
            if pattern.search(window):
                return False
        return True

    def _count_fillers(self, text):
        counts = {}
        lower = text.lower()
        masked = lower

        for phrase in MULTI_WORD_FILLERS:
            n = masked.count(phrase)
            if n:
                counts[phrase] = n
                masked = masked.replace(phrase, " _F_ ")

        like_count = 0
        for m in re.finditer(r'\blike\b', masked):
            if self._is_like_filler(masked, m.start()):
                like_count += 1
        if like_count:
            counts["like"] = like_count
            masked = re.sub(r'\blike\b', '_F_', masked)

        for word in re.findall(r'\b\w+\b', masked):
            if word in SINGLE_WORD_FILLERS:
                counts[word] = counts.get(word, 0) + 1

        return counts

    def _count_hedges(self, text):
        counts = {}
        lower = text.lower()
        masked = lower

        for phrase in MULTI_WORD_HEDGES:
            n = masked.count(phrase)
            if n:
                counts[phrase] = n
                masked = masked.replace(phrase, " _H_ ")

        for word in re.findall(r'\b\w+\b', masked):
            if word in SINGLE_WORD_HEDGES:
                counts[word] = counts.get(word, 0) + 1

        return counts

    def _count_questions(self, text):
        count = 0
        segments = text.split("?")
        count += max(0, len(segments) - 1)
        if count == 0:
            first_word = text.strip().split()[0].lower().rstrip(".,!") if text.strip() else ""
            if first_word in QUESTION_STARTERS:
                count = 1
        return count

    def _detect_repeats(self, text):
        matches = re.findall(r'\b(\w+)(?:\s+\1)+\b', text.lower())
        return len(matches)

    # ------------------------------------------------------------------
    # Utterance analysis — mutates the state dict `s`
    # ------------------------------------------------------------------

    def _analyze_utterance(self, text, s):
        text_clean = re.sub(r'\s+', ' ', text).strip()
        if not text_clean:
            return

        words = [w for w in re.findall(r"\b[a-zA-Z']+\b", text_clean.lower()) if len(w) > 1]
        word_count = len(words)

        if word_count < 3:
            s["total_utterances"] += 1
            return

        s["total_utterances"] += 1
        s["total_words"] += word_count

        for w in words:
            if len(s["unique_words"]) < MAX_UNIQUE_WORDS:
                s["unique_words"].add(w)
            if w not in s["prev_vocab"] and w not in s["new_vocab_words"]:
                s["new_vocab_words"].add(w)

        s["utterance_lengths"].append(word_count)

        q_count = self._count_questions(text_clean)
        s["question_count"] += q_count
        if q_count == 0:
            s["statement_count"] += 1

        fillers = self._count_fillers(text_clean)
        for k, v in fillers.items():
            s["filler_counts"][k] = s["filler_counts"].get(k, 0) + v

        hedges = self._count_hedges(text_clean)
        for k, v in hedges.items():
            s["hedging_counts"][k] = s["hedging_counts"].get(k, 0) + v

        s["repeat_count"] += self._detect_repeats(text_clean)

        total_fillers_this = sum(fillers.values())
        if total_fillers_this >= 3:
            s["nudge_pending"] = True
            s["nudge_trigger_word"] = max(fillers, key=fillers.get)
            s["nudge_trigger_count"] = fillers[s["nudge_trigger_word"]]

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def _load_stats(self):
        try:
            exists = await self.capability_worker.check_if_file_exists(STATS_FILE, False)
            if not exists:
                return _empty_stats()
            raw = await self.capability_worker.read_file(STATS_FILE, False)
            if not raw or not raw.strip():
                return _empty_stats()
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[InsightsCoach] Load error: {e}")
            return _empty_stats()

    async def _save_stats(self, data):
        try:
            exists = await self.capability_worker.check_if_file_exists(STATS_FILE, False)
            if exists:
                await self.capability_worker.delete_file(STATS_FILE, False)
            await self.capability_worker.write_file(
                STATS_FILE, json.dumps(data, indent=2), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[InsightsCoach] Save error: {e}")

    # ------------------------------------------------------------------
    # Snapshot builders — read from state dict `s`
    # ------------------------------------------------------------------

    def _build_session_snapshot(self, s):
        lengths = s["utterance_lengths"]
        avg_len = round(sum(lengths) / len(lengths), 1) if lengths else 0.0
        return {
            "date": s["session_date"],
            "total_utterances": s["total_utterances"],
            "total_words": s["total_words"],
            "unique_word_count": len(s["unique_words"]),
            "filler_counts": dict(s["filler_counts"]),
            "hedging_counts": dict(s["hedging_counts"]),
            "question_count": s["question_count"],
            "statement_count": s["statement_count"],
            "avg_utterance_length": avg_len,
            "new_vocab_words": list(s["new_vocab_words"])[:20],
            "repeat_count": s["repeat_count"],
        }

    def _build_history_entry(self, s):
        total_fillers = sum(s["filler_counts"].values())
        total_hedges = sum(s["hedging_counts"].values())
        tw = s["total_words"]
        tu = s["total_utterances"]
        lengths = s["utterance_lengths"]
        vocab_diversity = round(len(s["unique_words"]) / tw, 3) if tw > 0 else 0.0
        filler_rate = round(total_fillers / tw, 4) if tw > 0 else 0.0
        question_ratio = round(s["question_count"] / tu, 3) if tu > 0 else 0.0
        avg_len = round(sum(lengths) / len(lengths), 1) if lengths else 0.0
        top_fillers = sorted(s["filler_counts"], key=s["filler_counts"].get, reverse=True)[:3]
        return {
            "date": s["session_date"],
            "total_utterances": tu,
            "total_words": tw,
            "vocabulary_diversity": vocab_diversity,
            "filler_rate": filler_rate,
            "total_fillers": total_fillers,
            "total_hedges": total_hedges,
            "question_ratio": question_ratio,
            "avg_utterance_length": avg_len,
            "top_fillers": top_fillers,
            "new_vocab_count": len(s["new_vocab_words"]),
        }

    # ------------------------------------------------------------------
    # Checkpoint
    # ------------------------------------------------------------------

    async def _save_checkpoint(self, data, s):
        today = datetime.now().strftime("%Y-%m-%d")

        if s["session_date"] and today != s["session_date"]:
            entry = self._build_history_entry(s)
            history = data.get("daily_history", [])
            history = [h for h in history if h.get("date") != s["session_date"]]
            history.append(entry)
            if len(history) > 30:
                history = history[-30:]
            data["daily_history"] = history

            s["prev_vocab"].update(s["unique_words"])
            # Reset counters for new day
            for k in ("total_utterances", "total_words", "question_count",
                      "statement_count", "repeat_count"):
                s[k] = 0
            s["unique_words"] = set()
            s["filler_counts"] = {}
            s["hedging_counts"] = {}
            s["utterance_lengths"] = []
            s["new_vocab_words"] = set()
            s["session_date"] = today

            self.worker.editor_logging_handler.info(
                f"[InsightsCoach] Day rollover → archived {entry['date']}"
            )

        data["current_session"] = self._build_session_snapshot(s)
        await self._save_stats(data)

        self.worker.editor_logging_handler.info(
            f"[InsightsCoach] Checkpoint saved — "
            f"{s['total_utterances']} utterances, "
            f"{sum(s['filler_counts'].values())} fillers"
        )

    # ------------------------------------------------------------------
    # Restore state on reconnect
    # ------------------------------------------------------------------

    async def _restore_from_file(self, s):
        data = await self._load_stats()
        today = datetime.now().strftime("%Y-%m-%d")
        session = data.get("current_session", {})

        if session.get("date") == today:
            s["total_utterances"] = session.get("total_utterances", 0)
            s["total_words"] = session.get("total_words", 0)
            s["filler_counts"] = session.get("filler_counts", {})
            s["hedging_counts"] = session.get("hedging_counts", {})
            s["question_count"] = session.get("question_count", 0)
            s["statement_count"] = session.get("statement_count", 0)
            s["repeat_count"] = session.get("repeat_count", 0)
            s["new_vocab_words"] = set(session.get("new_vocab_words", []))
            self.worker.editor_logging_handler.info(
                f"[InsightsCoach] Resumed today's session — "
                f"{s['total_utterances']} utterances already tracked"
            )
        else:
            if session.get("date") and session.get("total_utterances", 0) > 0:
                tw = max(session.get("total_words", 1), 1)
                tu = max(session.get("total_utterances", 1), 1)
                fc = session.get("filler_counts", {})
                hc = session.get("hedging_counts", {})
                entry = {
                    "date": session["date"],
                    "total_utterances": session.get("total_utterances", 0),
                    "total_words": session.get("total_words", 0),
                    "vocabulary_diversity": round(session.get("unique_word_count", 0) / tw, 3),
                    "filler_rate": round(sum(fc.values()) / tw, 4),
                    "total_fillers": sum(fc.values()),
                    "total_hedges": sum(hc.values()),
                    "question_ratio": round(session.get("question_count", 0) / tu, 3),
                    "avg_utterance_length": session.get("avg_utterance_length", 0.0),
                    "top_fillers": sorted(fc, key=lambda k: fc[k], reverse=True)[:3],
                    "new_vocab_count": len(session.get("new_vocab_words", [])),
                }
                history = data.get("daily_history", [])
                history = [h for h in history if h.get("date") != session["date"]]
                history.append(entry)
                if len(history) > 30:
                    history = history[-30:]
                data["daily_history"] = history
                await self._save_stats(data)
                self.worker.editor_logging_handler.info(
                    f"[InsightsCoach] New day — archived {session['date']}"
                )

        settings = data.get("settings", {})
        s["goal"] = settings.get("filler_goal")
        s["nudge_enabled"] = settings.get("nudge_enabled", False)
        s["session_date"] = today
        return data

    # ------------------------------------------------------------------
    # Watch loop — ALL mutable state in local dict `s`
    # ------------------------------------------------------------------

    async def watch_loop(self):
        s = _new_state()

        self.worker.editor_logging_handler.info(
            "[InsightsCoach] daemon started — monitoring communication (20s interval)"
        )

        await self._restore_from_file(s)

        while True:
            try:
                history = self.capability_worker.get_full_message_history()
                history = history or []
                current_length = len(history)

                if s["last_processed_index"] == 0 and current_length > 10:
                    s["last_processed_index"] = current_length - 10
                    self.worker.editor_logging_handler.info(
                        f"[InsightsCoach] First poll: skip to index {s['last_processed_index']}"
                    )

                if s["last_processed_index"] > current_length:
                    self.worker.editor_logging_handler.info(
                        "[InsightsCoach] History shrunk, resetting pointer"
                    )
                    s["last_processed_index"] = max(0, current_length - 3)

                new_messages = history[s["last_processed_index"]:]
                s["last_processed_index"] = current_length

                new_count = 0
                for msg in new_messages:
                    if msg.get("role") != "user":
                        continue
                    text = msg.get("content", "")
                    if not isinstance(text, str):
                        continue
                    text = text.strip()
                    if not text or len(text) < 5:
                        continue
                    self._analyze_utterance(text, s)
                    new_count += 1

                if new_count:
                    tf = sum(s["filler_counts"].values())
                    self.worker.editor_logging_handler.info(
                        f"[InsightsCoach] +{new_count} utterances — "
                        f"{tf} fillers, {len(s['unique_words'])} unique words"
                    )

                s["polls_since_save"] += 1
                if s["polls_since_save"] >= SAVE_EVERY_N_POLLS or new_count:
                    fresh = await self._load_stats()
                    settings = fresh.get("settings", {})
                    s["nudge_enabled"] = settings.get("nudge_enabled", False)
                    s["goal"] = settings.get("filler_goal")
                    fresh["settings"] = settings
                    await self._save_checkpoint(fresh, s)
                    if s["polls_since_save"] >= SAVE_EVERY_N_POLLS:
                        s["polls_since_save"] = 0

                if s["nudge_pending"] and s["nudge_enabled"]:
                    now = time.time()
                    if now - s["last_nudge_time"] >= NUDGE_COOLDOWN_SECS:
                        msg_text = random.choice(NUDGE_MESSAGES)
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(msg_text)
                        s["last_nudge_time"] = now
                        self.worker.editor_logging_handler.info(
                            f"[InsightsCoach] Nudge sent — "
                            f"'{s['nudge_trigger_word']}' x{s['nudge_trigger_count']}"
                        )
                s["nudge_pending"] = False

            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[InsightsCoach] Loop error: {e}"
                )

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.editor_logging_handler.info(
            "[InsightsCoach] background.py call() — launching watch_loop"
        )
        self.worker.session_tasks.create(self.watch_loop())
