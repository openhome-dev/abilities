import json
import random
import re
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# WORKOUT TRACKER
# A voice-driven exercise tracker that logs workouts, tracks streaks,
# and provides weekly summaries. Data persists across sessions.
#
# Pattern: Greet → Detect Intent (log / stats / history / goals) → Loop → Exit
# =============================================================================

WORKOUTS_FILE = "workout_tracker_log.json"
PREFS_FILE = "workout_tracker_prefs.json"

MAX_TURNS = 20

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "bye", "goodbye",
    "leave", "cancel", "nothing else", "no thanks",
    "i'm good", "im good", "i am good", "nah",
}

LOG_KEYWORDS = {"log", "add", "did", "finished", "completed", "just did", "record", "went"}
STATS_KEYWORDS = {"stats", "statistics", "summary", "progress", "how am i", "streak", "total"}
HISTORY_KEYWORDS = {"history", "past", "previous", "show", "list", "review", "what did"}
GOAL_KEYWORDS = {"goal", "target", "set goal", "change goal"}

FILLER_SAVING = [
    "Got it, logging that workout.",
    "Nice work! Saving that.",
    "Logged! Keep it up.",
]
FILLER_LOADING = [
    "Let me check your stats.",
    "Pulling up your progress.",
    "One sec, crunching the numbers.",
]

PARSE_WORKOUT_PROMPT = (
    "The user described a workout by voice. Extract the following as JSON:\n"
    '- "exercise": the type of exercise (e.g. "pushups", "running", "yoga")\n'
    '- "amount": the number or duration (e.g. "30", "5k", "45 minutes"). Use "" if unclear.\n'
    '- "unit": the unit (e.g. "reps", "miles", "minutes", "km"). Use "" if unclear.\n'
    "Return ONLY valid JSON, nothing else.\n\n"
    "User said: {raw}"
)

INTENT_PROMPT = (
    "Classify this user input into exactly one of: log, stats, history, goal, exit, unknown.\n"
    "Context: this is a voice workout tracker. The user can log exercises, "
    "check stats/streaks, review history, set goals, or exit.\n"
    "Return ONLY one word, nothing else.\n"
    "Input: {text}"
)

WEEKLY_SUMMARY_PROMPT = (
    "Summarize this week's workout data in 2-3 sentences for voice readback. "
    "Mention total workouts, variety, and any notable streaks or patterns. "
    "Be encouraging but honest.\n\n{data}"
)


class WorkoutTrackerCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.workouts = []
        self.prefs = {"goal_per_week": 4, "name": ""}
        self.idle_count = 0
        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            await self._boot()

            turn = 0
            while turn < MAX_TURNS:
                turn += 1
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    self.idle_count += 1
                    if self.idle_count >= 2:
                        await self.capability_worker.speak(
                            "Still here if you need me. Otherwise I'll sign off."
                        )
                        final = await self.capability_worker.user_response()
                        if not final or not final.strip() or any(
                            w in final.lower() for w in EXIT_WORDS
                        ):
                            break
                        self.idle_count = 0
                        user_input = final
                    else:
                        continue

                self.idle_count = 0

                if any(w in user_input.lower() for w in EXIT_WORDS):
                    break

                intent = self._classify_intent(user_input)

                if intent == "log":
                    await self._handle_log(user_input)
                elif intent == "stats":
                    await self._handle_stats()
                elif intent == "history":
                    await self._handle_history()
                elif intent == "goal":
                    await self._handle_goal()
                elif intent == "exit":
                    break
                else:
                    await self.capability_worker.speak(
                        "You can log a workout, check your stats, review history, "
                        "or set a weekly goal. What would you like?"
                    )

            streak = self._calculate_streak()
            if streak > 0:
                await self.capability_worker.speak(
                    f"Keep it up! You're on a {streak}-day streak. See you next time."
                )
            else:
                await self.capability_worker.speak(
                    "Great job tracking your fitness. See you next time!"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[WorkoutTracker] Error: {e}"
            )
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Let me hand you back."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # -------------------------------------------------------------------------
    # Boot & Persistence
    # -------------------------------------------------------------------------

    async def _boot(self):
        """Load saved data or run first-time setup."""
        is_new_user = True

        # Load prefs
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )
            if exists:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                self.prefs = json.loads(raw)
                is_new_user = False
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[WorkoutTracker] Prefs load error: {e}"
            )

        # Load workouts
        try:
            exists = await self.capability_worker.check_if_file_exists(
                WORKOUTS_FILE, False
            )
            if exists:
                raw = await self.capability_worker.read_file(WORKOUTS_FILE, False)
                self.workouts = json.loads(raw)
                is_new_user = False
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[WorkoutTracker] Workouts load error: {e}"
            )

        if is_new_user:
            # First-time onboarding
            await self.capability_worker.speak(
                "Welcome to Workout Tracker! Tell me what you did — "
                "like 'I did 30 pushups' or 'ran 3 miles'."
            )
            await self.capability_worker.speak("What should I call you?")
            name_input = await self.capability_worker.user_response()
            if (
                name_input
                and name_input.strip()
                and len(name_input.strip()) < 30
                and not self._is_decline(name_input)
            ):
                self.prefs["name"] = name_input.strip()
                await self._save_prefs()
                await self.capability_worker.speak(
                    f"Nice to meet you, {self.prefs['name']}! Let's get started."
                )
            else:
                await self.capability_worker.speak(
                    "No problem, we can skip the name. Let's get started."
                )
        else:
            # Returning user
            name = self.prefs.get("name", "")
            week_count = self._count_this_week()
            goal = self.prefs.get("goal_per_week", 4)
            streak = self._calculate_streak()

            greeting = "Welcome back"
            if name:
                greeting += f", {name}"
            greeting += f". You've logged {week_count} workout"
            if week_count != 1:
                greeting += "s"
            greeting += f" this week out of your {goal} goal."
            if streak > 1:
                greeting += f" {streak}-day streak going!"

            await self.capability_worker.speak(greeting)

        await self.capability_worker.speak(
            "Log a workout, check stats, or say done to leave."
        )

    async def _save_workouts(self):
        """Persist workout log (delete + write pattern for JSON)."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                WORKOUTS_FILE, False
            )
            if exists:
                await self.capability_worker.delete_file(WORKOUTS_FILE, False)
            await self.capability_worker.write_file(
                WORKOUTS_FILE, json.dumps(self.workouts), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[WorkoutTracker] Save error: {e}"
            )

    async def _save_prefs(self):
        """Persist user preferences."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )
            if exists:
                await self.capability_worker.delete_file(PREFS_FILE, False)
            await self.capability_worker.write_file(
                PREFS_FILE, json.dumps(self.prefs), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[WorkoutTracker] Prefs save error: {e}"
            )

    # -------------------------------------------------------------------------
    # Intent Detection
    # -------------------------------------------------------------------------

    def _classify_intent(self, text):
        """Keyword-first intent detection with LLM fallback."""
        if not text or not text.strip():
            return "unknown"
        lower = text.lower().strip()

        if any(w in lower for w in EXIT_WORDS):
            return "exit"
        if any(w in lower for w in GOAL_KEYWORDS):
            return "goal"
        if any(w in lower for w in STATS_KEYWORDS):
            return "stats"
        if any(w in lower for w in HISTORY_KEYWORDS):
            return "history"
        if any(w in lower for w in LOG_KEYWORDS):
            return "log"

        # LLM fallback
        try:
            result = self.capability_worker.text_to_text_response(
                INTENT_PROMPT.format(text=text)
            )
            intent = result.strip().lower().rstrip(".")
            if intent in ("log", "stats", "history", "goal", "exit"):
                return intent
        except Exception:
            pass

        # Default: if it sounds like an exercise, treat as log
        exercise_words = {
            "pushup", "pushups", "squat", "squats", "ran", "run", "running",
            "walked", "walk", "yoga", "plank", "planks", "burpee", "burpees",
            "bench", "deadlift", "curl", "curls", "workout", "exercise",
            "swim", "swam", "cycling", "biked", "biking", "hiked", "hiking",
            "stretched", "stretching", "jumped", "jumping", "pull-up", "pullup",
            "situp", "sit-up", "lunge", "lunges", "weights", "lifting",
        }
        if any(w in lower for w in exercise_words):
            return "log"

        return "unknown"

    # -------------------------------------------------------------------------
    # Handlers
    # -------------------------------------------------------------------------

    async def _handle_log(self, user_input):
        """Parse and log a workout from natural language."""
        await self.capability_worker.speak(random.choice(FILLER_SAVING))

        try:
            raw = self.capability_worker.text_to_text_response(
                PARSE_WORKOUT_PROMPT.format(raw=user_input)
            )
            clean = raw.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[WorkoutTracker] Parse error: {e}"
            )
            parsed = {"exercise": user_input.strip(), "amount": "", "unit": ""}

        exercise = parsed.get("exercise", "workout").strip()
        amount = str(parsed.get("amount", "")).strip()
        unit = parsed.get("unit", "").strip()

        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "exercise": exercise,
            "amount": amount,
            "unit": unit,
        }
        self.workouts.append(entry)
        await self._save_workouts()

        # Build confirmation message
        desc = exercise
        if amount:
            desc = f"{amount} {unit} {exercise}" if unit else f"{amount} {exercise}"

        streak = self._calculate_streak()
        msg = f"Logged {desc}!"
        if streak > 1:
            msg += f" That's a {streak}-day streak!"

        week_count = self._count_this_week()
        goal = self.prefs.get("goal_per_week", 4)
        if week_count >= goal:
            msg += " You hit your weekly goal!"
        elif week_count == goal - 1:
            msg += " One more workout to hit your weekly goal!"

        await self.capability_worker.speak(msg)
        await self.capability_worker.speak(
            "Log another, check stats, or say done."
        )

    async def _handle_stats(self):
        """Show workout statistics and streak info."""
        await self.capability_worker.speak(random.choice(FILLER_LOADING))

        if not self.workouts:
            await self.capability_worker.speak(
                "No workouts logged yet. Tell me what you did to get started!"
            )
            return

        week_count = self._count_this_week()
        month_count = self._count_this_month()
        total = len(self.workouts)
        streak = self._calculate_streak()
        goal = self.prefs.get("goal_per_week", 4)

        # Get exercise variety this week
        week_exercises = self._get_week_exercises()
        variety = len(set(e.lower() for e in week_exercises))

        stats_msg = f"This week: {week_count} workouts"
        if variety > 1:
            stats_msg += f" across {variety} different exercises"
        stats_msg += f". Goal: {goal} per week."

        if streak > 0:
            stats_msg += f" Current streak: {streak} days."
        stats_msg += f" This month: {month_count}. All time: {total}."

        await self.capability_worker.speak(stats_msg)

        # LLM-powered weekly summary if enough data
        if week_count >= 2:
            try:
                week_data = json.dumps(
                    [w for w in self.workouts if self._is_this_week(w["date"])],
                    indent=2
                )
                summary = self.capability_worker.text_to_text_response(
                    WEEKLY_SUMMARY_PROMPT.format(data=week_data)
                )
                await self.capability_worker.speak(summary)
            except Exception:
                pass

    async def _handle_history(self):
        """Read back recent workout history."""
        if not self.workouts:
            await self.capability_worker.speak("No workouts logged yet.")
            return

        await self.capability_worker.speak(random.choice(FILLER_LOADING))

        recent = self.workouts[-7:]  # Last 7 entries
        count = len(recent)

        await self.capability_worker.speak(
            f"Here are your last {count} workouts."
        )

        for entry in recent:
            date = entry.get("date", "")
            exercise = entry.get("exercise", "workout")
            amount = entry.get("amount", "")
            unit = entry.get("unit", "")

            # Format date for speech
            try:
                dt = datetime.strptime(date, "%Y-%m-%d")
                today = datetime.now().date()
                if dt.date() == today:
                    date_str = "Today"
                elif dt.date() == today - timedelta(days=1):
                    date_str = "Yesterday"
                else:
                    date_str = dt.strftime("%A, %B %d")
            except Exception:
                date_str = date

            desc = exercise
            if amount:
                desc = f"{amount} {unit} {exercise}" if unit else f"{amount} {exercise}"

            await self.capability_worker.speak(f"{date_str}: {desc}.")

    async def _handle_goal(self):
        """Set or update weekly workout goal."""
        current = self.prefs.get("goal_per_week", 4)
        await self.capability_worker.speak(
            f"Your current goal is {current} workouts per week. "
            "What would you like to change it to?"
        )

        response = await self.capability_worker.user_response()
        if not response or not response.strip():
            await self.capability_worker.speak("I didn't catch that.")
            return

        if any(w in response.lower() for w in EXIT_WORDS):
            return

        # Extract number
        try:
            match = re.search(r"(\d+)", response)
            if match:
                new_goal = int(match.group(1))
                if 1 <= new_goal <= 14:
                    self.prefs["goal_per_week"] = new_goal
                    await self._save_prefs()
                    await self.capability_worker.speak(
                        f"Goal updated to {new_goal} workouts per week. You got this!"
                    )
                else:
                    await self.capability_worker.speak(
                        "Let's keep it between 1 and 14 per week."
                    )
            else:
                await self.capability_worker.speak(
                    "I couldn't get a number from that. Try saying a number like 5."
                )
        except Exception:
            await self.capability_worker.speak(
                "I had trouble with that. Try again later."
            )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _is_decline(self, text):
        """True if a short utterance is a decline ("no", "skip", "no thanks")."""
        normalized = text.lower().strip().strip(".!?,")
        declines = {"no", "skip", "none", "nope"} | EXIT_WORDS
        if normalized in declines:
            return True
        words = [w.strip(".!?,") for w in normalized.split()]
        return len(words) <= 3 and any(w in declines for w in words)

    def _calculate_streak(self):
        """Calculate consecutive days with at least one workout."""
        if not self.workouts:
            return 0

        dates = sorted(set(w["date"] for w in self.workouts), reverse=True)
        today = datetime.now().strftime("%Y-%m-%d")

        # If no workout today, check if yesterday counts
        if dates[0] != today:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            if dates[0] != yesterday:
                return 0

        # Count consecutive days starting from the most recent workout day
        # (today or yesterday), so a streak ending yesterday still counts.
        try:
            check_date = datetime.strptime(dates[0], "%Y-%m-%d").date()
        except ValueError:
            return 0

        streak = 0
        for i in range(len(dates)):
            expected = (check_date - timedelta(days=i)).strftime("%Y-%m-%d")
            if expected in dates:
                streak += 1
            else:
                break

        return streak

    def _count_this_week(self):
        """Count workouts logged in the current calendar week."""
        return len([w for w in self.workouts if self._is_this_week(w["date"])])

    def _count_this_month(self):
        """Count workouts logged in the current month."""
        this_month = datetime.now().strftime("%Y-%m")
        return len([w for w in self.workouts if w["date"].startswith(this_month)])

    def _get_week_exercises(self):
        """Get list of exercises done this week."""
        return [
            w["exercise"]
            for w in self.workouts
            if self._is_this_week(w["date"])
        ]

    def _is_this_week(self, date_str):
        """Check if a date string falls in the current ISO week."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            now = datetime.now()
            return dt.isocalendar()[:2] == now.isocalendar()[:2]
        except Exception:
            return False
