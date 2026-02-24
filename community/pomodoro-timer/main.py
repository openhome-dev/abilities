import json
import os
import re

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# POMODORO FOCUS TIMER
# A voice-controlled Pomodoro timer that manages focus and break sessions.
# Pattern: Ask duration -> Focus -> Break -> Repeat or Exit
# =============================================================================

DEFAULT_FOCUS_MINUTES = 25
DEFAULT_BREAK_MINUTES = 5
LONG_BREAK_MINUTES = 15
SESSIONS_BEFORE_LONG_BREAK = 4

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave"}

DURATION_PATTERNS = [
    (r"(\d{1,4})\s*(?:min|minute|minutes)", lambda m: int(m.group(1))),
    (r"half\s*(?:an?\s*)?hour", lambda m: 30),
    (r"an?\s*hour", lambda m: 60),
    (r"(\d{1,4}(?:\.\d+)?)\s*(?:hour|hours|hr|hrs)", lambda m: round(float(m.group(1)) * 60)),
    (r"\b(\d{1,4})\b", lambda m: int(m.group(1))),
]


class PomodoroTimerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker) -> None:
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self) -> None:
        try:
            session_count = 0

            await self.capability_worker.speak(
                "How long would you like to focus? I'll default to 25 minutes."
            )
            user_input = await self.capability_worker.user_response()
            focus_minutes = self._parse_minutes(user_input)

            self.worker.editor_logging_handler.info(
                f"[PomodoroTimer] Starting with {focus_minutes}-minute sessions"
            )

            while True:
                session_count += 1

                await self.capability_worker.speak(
                    f"Starting focus session {session_count}. "
                    f"{focus_minutes} minutes on the clock. Good luck."
                )

                await self.worker.session_tasks.sleep(focus_minutes * 60)

                if session_count % SESSIONS_BEFORE_LONG_BREAK == 0:
                    break_minutes = LONG_BREAK_MINUTES
                    await self.capability_worker.speak(
                        f"Focus session complete. You've done {session_count} sessions. "
                        f"Take a longer break, {break_minutes} minutes. "
                        "Say stop to finish, or anything else to keep going."
                    )
                else:
                    break_minutes = DEFAULT_BREAK_MINUTES
                    await self.capability_worker.speak(
                        f"Focus session complete. Take a {break_minutes}-minute break. "
                        "Say stop to finish, or anything else to keep going."
                    )

                user_input = await self.capability_worker.user_response()

                if not user_input:
                    continue

                input_words = set(user_input.lower().split())
                if input_words & EXIT_WORDS:
                    total = session_count * focus_minutes
                    await self.capability_worker.speak(
                        f"Great work. You completed {session_count} "
                        f"focus session{'s' if session_count != 1 else ''}, "
                        f"totaling {total} minutes. See you next time."
                    )
                    break

                await self.capability_worker.speak(
                    f"Enjoy your {break_minutes}-minute break."
                )
                await self.worker.session_tasks.sleep(break_minutes * 60)

                await self.capability_worker.speak(
                    "Break's over. Ready for the next session."
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PomodoroTimer] Unexpected error: {e}"
            )
            try:
                await self.capability_worker.speak(
                    "Something went wrong with the timer. Let me hand you back."
                )
            except Exception:
                pass
        finally:
            self.worker.editor_logging_handler.info(
                "[PomodoroTimer] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _parse_minutes(self, text: str) -> int:
        """Extract a duration in minutes from natural language. Falls back to 25."""
        if not text or len(text) > 200:
            return DEFAULT_FOCUS_MINUTES

        cleaned = text.strip().lower()

        for pattern, extractor in DURATION_PATTERNS:
            match = re.search(pattern, cleaned)
            if match:
                minutes = extractor(match)
                if 1 <= minutes <= 180:
                    return minutes
                return DEFAULT_FOCUS_MINUTES

        return DEFAULT_FOCUS_MINUTES
