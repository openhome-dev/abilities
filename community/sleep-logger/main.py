import json
import re
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# SLEEP LOGGER
# Tracks sleep data across sessions with voice logging and LLM analysis.
# Users log bedtime, wake time, quality, and notes. Provides weekly summaries
# and trend analysis correlating notes with sleep quality.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

SLEEP_LOG_FILE = "sleep_log.json"

LOG_KEYWORDS = {"log", "slept", "sleep", "went to bed", "woke up", "record"}
SUMMARY_KEYWORDS = {"summary", "average", "this week", "how did i sleep", "stats"}
TREND_KEYWORDS = {"trend", "pattern", "correlation", "analysis", "insight"}

CLASSIFY_PROMPT = (
    "Classify this sleep tracker request. Return ONLY one of: "
    "log, summary, trends, exit, unknown\n"
    "Rules:\n"
    "- 'I slept', 'log sleep', 'went to bed', 'woke up' -> log\n"
    "- 'summary', 'average', 'this week', 'how am I sleeping' -> summary\n"
    "- 'trends', 'patterns', 'correlation', 'insights' -> trends\n"
    "- 'stop', 'done', 'bye' -> exit\n"
    "Input: {text}"
)

EXTRACT_SLEEP_PROMPT = (
    "Extract sleep data from the user's input. Return ONLY valid JSON "
    "with no markdown fences.\n"
    'Format: {{"bedtime": "<HH:MM in 24h>", "waketime": "<HH:MM in 24h>", '
    '"quality": <1-5 or null>, "notes": "<any notes>"}}\n'
    "If not mentioned, set to null.\n"
    "Examples:\n"
    '"I slept from 11 PM to 7 AM, quality 4, exercised yesterday" -> '
    '{{"bedtime": "23:00", "waketime": "07:00", "quality": 4, "notes": "exercised yesterday"}}\n'
    '"Went to bed at midnight, woke at 6:30" -> '
    '{{"bedtime": "00:00", "waketime": "06:30", "quality": null, "notes": ""}}\n'
)

SUMMARY_PROMPT = (
    "You are a sleep analyst. Given the user's sleep log entries from the "
    "past 7 days, provide a brief spoken summary including: average hours, "
    "average quality, best night, worst night. Keep it to 2-3 sentences. "
    "Today's date is {today}."
)

TRENDS_PROMPT = (
    "You are a sleep analyst. Analyze these sleep log entries for patterns. "
    "Look for correlations between notes (exercise, caffeine, stress, etc.) "
    "and sleep quality/duration. Provide 2-3 actionable insights in a "
    "conversational tone for voice. Today's date is {today}."
)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class SleepLoggerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.sleep_log = []
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info(
                "[SleepLogger] Ability started"
            )

            self.sleep_log = await self._load_log()

            if not self.sleep_log:
                await self.capability_worker.speak(
                    "Welcome to Sleep Logger! I'll help you track your sleep. "
                    "Tell me about last night, like 'I slept from 11 PM to 7 AM, "
                    "quality 4 out of 5'. Or say summary to review your data."
                )
            else:
                count = len(self.sleep_log)
                await self.capability_worker.speak(
                    f"Welcome back to Sleep Logger! You have {count} "
                    f"entr{'y' if count == 1 else 'ies'}. "
                    "Want to log last night's sleep, see a summary, or check trends?"
                )

            idle_count = 0

            for _ in range(15):
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Closing Sleep Logger. Sweet dreams!"
                        )
                        break
                    await self.capability_worker.speak(
                        "I'm listening. Log your sleep or ask for a summary."
                    )
                    continue

                idle_count = 0

                if any(w in user_input.lower() for w in EXIT_WORDS):
                    await self.capability_worker.speak(
                        "Sweet dreams! See you next time."
                    )
                    break

                intent = self._classify_intent(user_input)

                if intent == "log":
                    await self._handle_log(user_input)
                elif intent == "summary":
                    await self._handle_summary()
                elif intent == "trends":
                    await self._handle_trends()
                elif intent == "exit":
                    await self.capability_worker.speak(
                        "Sweet dreams! See you next time."
                    )
                    break
                else:
                    await self.capability_worker.speak(
                        "I can log your sleep, show a summary, or analyze trends. "
                        "What would you like?"
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SleepLogger] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing Sleep Logger."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[SleepLogger] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _classify_intent(self, text: str) -> str:
        lower = text.lower()

        if any(w in lower for w in EXIT_WORDS):
            return "exit"
        if any(w in lower for w in TREND_KEYWORDS):
            return "trends"
        if any(w in lower for w in SUMMARY_KEYWORDS):
            return "summary"
        if any(w in lower for w in LOG_KEYWORDS):
            return "log"

        try:
            result = self.capability_worker.text_to_text_response(
                CLASSIFY_PROMPT.format(text=text)
            )
            intent = result.strip().lower().rstrip(".")
            if intent in ("log", "summary", "trends", "exit"):
                return intent
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SleepLogger] Classification error: {e}"
            )

        return "unknown"

    async def _handle_log(self, user_input: str):
        try:
            raw = self.capability_worker.text_to_text_response(
                f"User said: {user_input}",
                system_prompt=EXTRACT_SLEEP_PROMPT,
            )
            data = json.loads(_strip_json_fences(raw))
        except (json.JSONDecodeError, Exception) as e:
            self.worker.editor_logging_handler.error(
                f"[SleepLogger] Extraction error: {e}"
            )
            data = {}

        bedtime = data.get("bedtime")
        waketime = data.get("waketime")
        quality = data.get("quality")
        notes = data.get("notes", "")

        if not bedtime or not waketime:
            time_input = await self.capability_worker.run_io_loop(
                "What time did you go to bed and wake up?"
            )
            if not time_input or any(
                w in time_input.lower() for w in EXIT_WORDS
            ):
                return
            try:
                raw2 = self.capability_worker.text_to_text_response(
                    f"User said: {time_input}",
                    system_prompt=EXTRACT_SLEEP_PROMPT,
                )
                data2 = json.loads(_strip_json_fences(raw2))
                bedtime = data2.get("bedtime") or bedtime
                waketime = data2.get("waketime") or waketime
            except (json.JSONDecodeError, Exception):
                pass

        if not bedtime or not waketime:
            await self.capability_worker.speak(
                "I couldn't understand the times. Try something like "
                "'11 PM to 7 AM'."
            )
            return

        if quality is None:
            quality_input = await self.capability_worker.run_io_loop(
                "How was your sleep quality? Rate it 1 to 5."
            )
            if quality_input:
                match = re.search(r"[1-5]", quality_input)
                if match:
                    quality = int(match.group())

        hours = self._calculate_hours(bedtime, waketime)
        today = datetime.now().strftime("%Y-%m-%d")

        existing_idx = None
        for i, entry in enumerate(self.sleep_log):
            if entry.get("date") == today:
                existing_idx = i
                break

        entry = {
            "date": today,
            "bedtime": bedtime,
            "waketime": waketime,
            "hours": hours,
            "quality": quality,
            "notes": notes,
        }

        if existing_idx is not None:
            self.sleep_log[existing_idx] = entry
            await self._save_log()
            await self.capability_worker.speak(
                f"Updated today's entry: {hours:.1f} hours, "
                f"quality {quality or 'not rated'}."
            )
        else:
            self.sleep_log.append(entry)
            await self._save_log()
            await self.capability_worker.speak(
                f"Logged! {hours:.1f} hours of sleep, "
                f"quality {quality or 'not rated'}. "
                "Anything else?"
            )

    async def _handle_summary(self):
        if not self.sleep_log:
            await self.capability_worker.speak(
                "No sleep data yet. Log your first night to get started."
            )
            return

        recent = self.sleep_log[-7:]
        today = datetime.now().strftime("%Y-%m-%d")
        log_text = json.dumps(recent, indent=2)

        try:
            response = self.capability_worker.text_to_text_response(
                f"Sleep log entries:\n{log_text}",
                system_prompt=SUMMARY_PROMPT.format(today=today),
            )
            await self.capability_worker.speak(response)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SleepLogger] Summary error: {e}"
            )
            hours_list = [e.get("hours", 0) for e in recent if e.get("hours")]
            if hours_list:
                avg = sum(hours_list) / len(hours_list)
                await self.capability_worker.speak(
                    f"Over your last {len(recent)} entries, "
                    f"you averaged {avg:.1f} hours of sleep."
                )
            else:
                await self.capability_worker.speak(
                    "I had trouble generating a summary."
                )

    async def _handle_trends(self):
        if len(self.sleep_log) < 3:
            await self.capability_worker.speak(
                "I need at least 3 entries to analyze trends. "
                "Keep logging and check back soon!"
            )
            return

        today = datetime.now().strftime("%Y-%m-%d")
        log_text = json.dumps(self.sleep_log[-14:], indent=2)

        try:
            response = self.capability_worker.text_to_text_response(
                f"Sleep log entries:\n{log_text}",
                system_prompt=TRENDS_PROMPT.format(today=today),
            )
            await self.capability_worker.speak(response)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SleepLogger] Trends error: {e}"
            )
            await self.capability_worker.speak(
                "I had trouble analyzing your trends. Try again later."
            )

    def _calculate_hours(self, bedtime: str, waketime: str) -> float:
        try:
            bed_h, bed_m = map(int, bedtime.split(":"))
            wake_h, wake_m = map(int, waketime.split(":"))
            bed_minutes = bed_h * 60 + bed_m
            wake_minutes = wake_h * 60 + wake_m
            if wake_minutes <= bed_minutes:
                wake_minutes += 24 * 60
            return (wake_minutes - bed_minutes) / 60
        except (ValueError, TypeError):
            return 0.0

    async def _load_log(self) -> list:
        exists = await self.capability_worker.check_if_file_exists(
            SLEEP_LOG_FILE, False
        )
        if exists:
            try:
                raw = await self.capability_worker.read_file(SLEEP_LOG_FILE, False)
                data = json.loads(raw)
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, Exception) as e:
                self.worker.editor_logging_handler.error(
                    f"[SleepLogger] Corrupt file, resetting: {e}"
                )
                await self.capability_worker.delete_file(SLEEP_LOG_FILE, False)
        return []

    async def _save_log(self):
        if await self.capability_worker.check_if_file_exists(
            SLEEP_LOG_FILE, False
        ):
            await self.capability_worker.delete_file(SLEEP_LOG_FILE, False)
        await self.capability_worker.write_file(
            SLEEP_LOG_FILE, json.dumps(self.sleep_log), False
        )
