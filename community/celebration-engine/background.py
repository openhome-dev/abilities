import json
from datetime import datetime
from time import time

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CELEBRATION ENGINE
# A background daemon that detects wins and positive moments from
# conversation, then surfaces them at the right time.
#
# Most AI abilities only activate on problems. This one notices
# when things go RIGHT.
#
# Pattern: Background poll → analyze conversation → detect wins →
#          store silently → celebrate at the right moment
# =============================================================================

WINS_FILE = "celebration_engine_wins.json"

# Positive signal keywords and phrases
WIN_SIGNALS = [
    "i got it", "we did it", "i got the job", "i passed", "i won",
    "i made it", "it worked", "we got it", "promotion", "accepted",
    "i graduated", "they said yes", "deal closed", "signed the contract",
    "i finished", "finally done", "nailed it", "crushed it",
    "great news", "amazing news", "best day", "so happy",
    "can't believe it", "so excited", "so proud", "i'm thrilled",
]

# How often to check conversation history (seconds)
POLL_INTERVAL = 30.0

# Minimum messages between celebrations (avoid being annoying)
MIN_MESSAGES_BETWEEN = 15

DETECT_WIN_PROMPT = (
    "Analyze these recent conversation messages. Is the user expressing "
    "genuine excitement, happiness, or celebrating an achievement or win? "
    "Look for: job offers, promotions, completing something difficult, "
    "good news, personal milestones, or expressions of joy.\n\n"
    "Messages:\n{messages}\n\n"
    "Return ONLY valid JSON:\n"
    '{"is_win": true/false, "summary": "brief description of the win"}\n'
    "If no win detected, return: {\"is_win\": false, \"summary\": \"\"}"
)

CELEBRATE_PROMPT = (
    "The user just had a positive moment: {summary}\n"
    "Generate a SHORT, warm, genuine celebration response (1 sentence max). "
    "Be natural and enthusiastic but not over-the-top. Match the energy level "
    "of the achievement. Don't be cheesy or use too many exclamation marks.\n"
    "Return ONLY the celebration message."
)


class CelebrationEngineBackground(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    async def background_loop(self):
        self.worker.editor_logging_handler.info(
            "%s: Celebration Engine started" % time()
        )

        last_message_count = 0
        messages_since_last_celebration = 0
        # User messages with a win signal waiting for analysis. Kept across
        # polls so a win during the celebration cooldown is deferred, not lost.
        pending_signal_messages = []
        today = datetime.now().strftime("%Y-%m-%d")
        today_wins = []

        while True:
            try:
                # Reset the daily win list when the date rolls over
                now_day = datetime.now().strftime("%Y-%m-%d")
                if now_day != today:
                    today = now_day
                    today_wins = []

                # Get conversation history
                history = self.capability_worker.get_full_message_history()

                if not history:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                current_count = len(history)

                # Only analyze new messages
                if current_count <= last_message_count:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                new_messages = history[last_message_count:]
                last_message_count = current_count
                messages_since_last_celebration += len(new_messages)

                # Extract user messages only
                user_messages = [
                    m.get("content", "")
                    for m in new_messages
                    if m.get("role") == "user" and m.get("content")
                ]

                if user_messages:
                    # Quick keyword scan first (cheap)
                    combined = " ".join(user_messages).lower()
                    if any(signal in combined for signal in WIN_SIGNALS):
                        pending_signal_messages.extend(user_messages)
                        # Only the most recent few matter for analysis
                        pending_signal_messages = pending_signal_messages[-5:]

                if not pending_signal_messages:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                # Defer LLM analysis until the celebration cooldown has passed
                # (the pending messages are kept, so the win is not dropped)
                if messages_since_last_celebration < MIN_MESSAGES_BETWEEN:
                    self.worker.editor_logging_handler.info(
                        "[CelebrationEngine] Win signal detected, deferring until cooldown passes"
                    )
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                messages_text = "\n".join(
                    f"- {m}" for m in pending_signal_messages
                )
                pending_signal_messages = []

                try:
                    raw = self.capability_worker.text_to_text_response(
                        DETECT_WIN_PROMPT.format(messages=messages_text)
                    )
                    clean = raw.replace("```json", "").replace("```", "").strip()
                    result = json.loads(clean)
                except Exception as e:
                    self.worker.editor_logging_handler.error(
                        f"[CelebrationEngine] Parse error: {e}"
                    )
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                if not result.get("is_win", False):
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                summary = result.get("summary", "something positive")
                self.worker.editor_logging_handler.info(
                    f"[CelebrationEngine] Win detected: {summary}"
                )

                # Generate celebration
                try:
                    celebration = self.capability_worker.text_to_text_response(
                        CELEBRATE_PROMPT.format(summary=summary)
                    )
                    celebration = celebration.strip().strip('"').strip("'")
                except Exception:
                    celebration = "Hey — that sounds like great news!"

                # Interrupt and celebrate
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(celebration)

                messages_since_last_celebration = 0

                # Log the win
                win_entry = {
                    "time": datetime.now().strftime("%H:%M"),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "summary": summary,
                }
                today_wins.append(win_entry)
                await self._save_wins(today_wins)

            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[CelebrationEngine] Loop error: {e}"
                )

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    async def _save_wins(self, wins):
        """Persist today's wins (delete + write for JSON)."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                WINS_FILE, False
            )
            if exists:
                # Read existing, merge with today
                raw = await self.capability_worker.read_file(WINS_FILE, False)
                all_wins = json.loads(raw)
            else:
                all_wins = []

            # Add new wins that aren't already logged. Dedup on the full
            # entry (date + time + summary) so distinct wins that happen to
            # get the same summary text are still kept.
            existing_keys = {
                (w.get("date", ""), w.get("time", ""), w.get("summary", ""))
                for w in all_wins
            }
            for win in wins:
                key = (win.get("date", ""), win.get("time", ""), win.get("summary", ""))
                if key not in existing_keys:
                    all_wins.append(win)
                    existing_keys.add(key)

            # Keep last 100 wins
            all_wins = all_wins[-100:]

            if exists:
                await self.capability_worker.delete_file(WINS_FILE, False)
            await self.capability_worker.write_file(
                WINS_FILE, json.dumps(all_wins), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[CelebrationEngine] Save error: {e}"
            )

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.background_loop())
