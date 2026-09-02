import json
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "sleep_quality_tracker_data"

HOTWORDS = [
    "how did i sleep", "sleep check", "log my sleep", "sleep report",
    "sleep tracker", "sleep quality", "sleep log", "i slept",
    "morning check-in", "sleep patterns", "sleep insights", "sleep score",
    "tips for tonight", "help me sleep", "sleep better", "sleep summary",
    "sleep tracker", "track my sleep", "bedtime check",
]

EXIT_WORDS = {"stop", "done", "exit", "quit", "bye", "nothing", "cancel", "no thanks"}

ANALYSIS_PROMPT = (
    "You are analysing {name}'s personal sleep data from the last {n} nights. "
    "Data (JSON): {data}. "
    "Identify the top 1-2 correlations between their evening habits and sleep quality. "
    "Speak directly to {name} in a warm, conversational tone. "
    "Only state patterns supported by 3 or more data points. "
    "If data is still too thin for a pattern, be honest and encouraging. "
    "Never give generic sleep advice — only findings from this person's actual data. "
    "Maximum 3 sentences. Plain text only."
)

TONIGHT_TIP_PROMPT = (
    "Based on {name}'s sleep data: {data}. "
    "Give ONE specific, personalised tip for tonight based on their worst-performing habit correlations. "
    "If fewer than 5 nights logged, give one evidence-based general tip and note it gets personal over time. "
    "Warm, direct, one sentence. Plain text only."
)


class SleepQualityTrackerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        t = text.lower()
        return any(hw in t for hw in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SleepTracker] Load error: {e!r}")
        return {}

    def _save_data(self, data: dict):
        try:
            result = self.capability_worker.create_key(STORAGE_KEY, data)
            if not result.get("success"):
                self.capability_worker.update_key(STORAGE_KEY, data)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SleepTracker] Save error: {e!r}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        tokens = set(text.lower().strip().split())
        return bool(tokens & EXIT_WORDS)

    def _extract_hours(self, text: str) -> float:
        raw = self.capability_worker.text_to_text_response(
            f"Extract the number of sleep hours from this text. "
            f"Return ONLY a decimal number (e.g. 7.5). "
            f"If a bedtime and wake time are given, calculate the duration. "
            f"If unclear, return 7. Text: \"{text}\""
        )
        try:
            hours = float(raw.strip().split()[0])
            return round(max(1.0, min(hours, 24.0)), 1)
        except Exception:
            return 7.0

    def _extract_rating(self, text: str) -> int:
        raw = self.capability_worker.text_to_text_response(
            f"Extract a sleep quality rating from 1 to 10 from this text. "
            f"If the person uses words like 'great' or 'amazing' use 9, 'good' use 7, "
            f"'okay' or 'alright' use 6, 'bad' or 'rough' use 4, 'terrible' use 2. "
            f"Return ONLY a single integer. Text: \"{text}\""
        )
        try:
            rating = int(raw.strip().split()[0])
            return max(1, min(rating, 10))
        except Exception:
            return 5

    def _extract_yes_no(self, text: str) -> bool:
        t = text.lower()
        return any(w in t for w in ("yes", "yeah", "yep", "yup", "sure", "did", "had", "true"))

    def _extract_stress(self, text: str) -> int:
        raw = self.capability_worker.text_to_text_response(
            f"Extract a stress level from 1 to 5 from this text. "
            f"'calm' or 'relaxed' = 1, 'a little' = 2, 'moderate' = 3, 'stressed' = 4, 'very stressed' = 5. "
            f"Return ONLY a single integer. Text: \"{text}\""
        )
        try:
            level = int(raw.strip().split()[0])
            return max(1, min(level, 5))
        except Exception:
            return 3

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _get_recent_log(self, data: dict, days: int = 14) -> list:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return [e for e in data.get("sleep_log", []) if e.get("date", "") >= cutoff]

    def _sleep_debt(self, data: dict) -> float:
        goal = data.get("sleep_goal_hours", 8)
        week_log = self._get_recent_log(data, days=7)
        if not week_log:
            return 0.0
        actual = sum(e.get("hours", 0) for e in week_log)
        target = goal * len(week_log)
        return round(max(0.0, target - actual), 1)

    def _already_logged_today(self, data: dict) -> bool:
        today = self._today_str()
        return any(e.get("date") == today for e in data.get("sleep_log", []))

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def _load_user_name(self) -> str:
        for filename in ("user_profile.md", "user_summary.md"):
            try:
                content = await self.capability_worker.read_file(
                    filename, in_ability_directory=False
                )
                if content:
                    name = self.capability_worker.text_to_text_response(
                        f"Extract the person's first name from this profile text. "
                        f"Return only the name, or UNKNOWN if not found.\n{content}"
                    ).strip()
                    if name and name != "UNKNOWN":
                        return name
            except Exception:
                pass
        return ""

    async def _handle_setup(self, data: dict) -> dict:
        name = await self._load_user_name()
        if not name:
            await self.capability_worker.speak(
                "Hi! I'm your sleep tracker. I'll learn your sleep patterns over time "
                "and give you personalised insights — not generic advice, but findings "
                "from your own data. What's your name?"
            )
            name_reply = await self.capability_worker.user_response()
            if not name_reply:
                await self.capability_worker.speak("Come back whenever you're ready. Sleep well!")
                return data
            name = name_reply.strip().split()[0].capitalize()

        await self.capability_worker.speak(
            f"How many hours of sleep do you aim for each night, {name}?"
            if name else
            "How many hours of sleep do you aim for each night?"
        )
        goal_reply = await self.capability_worker.user_response()
        goal = self._extract_hours(goal_reply or "8")

        data.update({
            "user_name": name,
            "sleep_goal_hours": goal,
            "setup_complete": True,
            "sleep_log": [],
            "weekly_summary_last_sent": None,
        })
        self._save_data(data)

        await self.capability_worker.speak(
            f"Perfect. I'll aim to help you hit {goal:.0f} hours a night. "
            f"Each morning, just say 'how did I sleep' and I'll log it. "
            f"After a week I'll start spotting patterns in your data. Let's go."
        )
        return data

    # ------------------------------------------------------------------
    # Morning check-in
    # ------------------------------------------------------------------

    async def _handle_morning_checkin(self, data: dict):
        name = data.get("user_name", "")

        if self._already_logged_today(data):
            await self.capability_worker.speak(
                f"You've already logged sleep for today, {name}. "
                f"Ask for your sleep report or tonight's tip if you'd like."
            )
            return

        await self.capability_worker.speak(
            f"Morning{', ' + name if name else ''}! How'd you sleep?"
        )
        sleep_reply = await self.capability_worker.user_response()
        if not sleep_reply or self._is_exit(sleep_reply):
            await self.capability_worker.speak("No worries — log it whenever you're ready.")
            return

        hours = self._extract_hours(sleep_reply)
        quality = self._extract_rating(sleep_reply)
        notes = self.capability_worker.text_to_text_response(
            f"Extract any sleep note or comment from this text (e.g. 'woke up in the night', "
            f"'vivid dreams', 'felt groggy'). Return the note as a short phrase, "
            f"or NONE if nothing noteworthy was mentioned. Text: \"{sleep_reply}\""
        ).strip()
        if notes.upper() == "NONE":
            notes = ""

        # If hours could not be extracted from the natural reply, ask once
        if hours == 7.0 and "7" not in sleep_reply and "seven" not in sleep_reply.lower():
            await self.capability_worker.speak("How many hours roughly?")
            hours_reply = await self.capability_worker.user_response()
            if hours_reply and not self._is_exit(hours_reply):
                hours = self._extract_hours(hours_reply)

        entry = {
            "date": self._today_str(),
            "hours": hours,
            "quality": quality,
            "notes": notes,
            "evening_habits": {},
        }
        data.setdefault("sleep_log", []).append(entry)
        self._save_data(data)
        self.worker.editor_logging_handler.info(
            f"[SleepTracker] Logged: {hours}h, quality {quality}/10"
        )

        insight = self._generate_morning_insight(data, hours, quality)
        await self.capability_worker.speak(insight)

    def _generate_morning_insight(self, data: dict, hours: float, quality: int) -> str:
        log = data.get("sleep_log", [])
        n = len(log)
        name = data.get("user_name", "")
        goal = data.get("sleep_goal_hours", 8)
        debt = self._sleep_debt(data)

        if n < 3:
            msg = f"Logged — {n} night{'s' if n != 1 else ''} tracked so far."
            if hours < goal - 0.5:
                msg += f" You're {goal - hours:.1f} hours short of your {goal:.0f}-hour goal tonight."
            return msg

        recent = self._get_recent_log(data, days=7)
        avg_quality = sum(e["quality"] for e in recent) / len(recent) if recent else quality
        avg_hours = sum(e["hours"] for e in recent) / len(recent) if recent else hours

        parts = [f"Logged — {hours:.1f} hours, {quality}/10."]
        if quality >= avg_quality + 1.5:
            parts.append("That's one of your better nights this week.")
        elif quality <= avg_quality - 1.5:
            parts.append(f"Rougher than your usual {avg_quality:.1f} average this week.")

        if debt > 1:
            parts.append(f"You're {debt:.1f} hours in sleep debt against your {goal:.0f}-hour goal this week.")
        elif debt == 0:
            parts.append(f"You're on track with your {goal:.0f}-hour goal this week.")

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Evening habits
    # ------------------------------------------------------------------

    async def _handle_evening_habits(self, data: dict):
        log = data.get("sleep_log", [])
        today = self._today_str()

        today_entry = next((e for e in log if e.get("date") == today), None)
        if today_entry is None:
            today_entry = {"date": today, "hours": 0, "quality": 0, "notes": "", "evening_habits": {}}
            log.append(today_entry)

        name = data.get("user_name", "")
        await self.capability_worker.speak(
            f"Quick habit check{', ' + name if name else ''}. Caffeine after 3pm today?"
        )
        r1 = await self.capability_worker.user_response()
        if r1 and not self._is_exit(r1):
            today_entry["evening_habits"]["caffeine_after_3pm"] = self._extract_yes_no(r1)

        await self.capability_worker.speak("Any exercise today?")
        r2 = await self.capability_worker.user_response()
        if r2 and not self._is_exit(r2):
            today_entry["evening_habits"]["exercise"] = self._extract_yes_no(r2)

        await self.capability_worker.speak("How stressed are you feeling tonight — calm, a little, moderate, stressed, or very stressed?")
        r3 = await self.capability_worker.user_response()
        if r3 and not self._is_exit(r3):
            today_entry["evening_habits"]["stress_level"] = self._extract_stress(r3)

        await self.capability_worker.speak("Screen time in the last hour before bed?")
        r4 = await self.capability_worker.user_response()
        if r4 and not self._is_exit(r4):
            today_entry["evening_habits"]["screen_time_before_bed"] = self._extract_yes_no(r4)

        data["sleep_log"] = log
        self._save_data(data)
        await self.capability_worker.speak(
            "Logged. I'll compare this with how you sleep tonight. Sleep well!"
        )

    # ------------------------------------------------------------------
    # Report / pattern insight
    # ------------------------------------------------------------------

    async def _handle_report(self, data: dict):
        log = data.get("sleep_log", [])
        name = data.get("user_name", "")

        if len(log) < 2:
            await self.capability_worker.speak(
                f"Not enough data yet{', ' + name if name else ''}. "
                f"Log a few more mornings and I'll start building your sleep picture."
            )
            return

        recent = self._get_recent_log(data, days=14)
        n = len(recent)
        avg_hours = sum(e["hours"] for e in recent) / n
        avg_quality = sum(e["quality"] for e in recent) / n
        best = max(recent, key=lambda e: e["quality"])
        worst = min(recent, key=lambda e: e["quality"])
        debt = self._sleep_debt(data)
        goal = data.get("sleep_goal_hours", 8)

        summary = (
            f"Here's your sleep picture for the last {n} night{'s' if n != 1 else ''}, {name}. "
            f"Average {avg_hours:.1f} hours, quality {avg_quality:.1f} out of 10. "
            f"Best night: {best['date']} — {best['hours']}h, rated {best['quality']}. "
            f"Worst night: {worst['date']} — {worst['hours']}h, rated {worst['quality']}. "
        )

        if debt > 0:
            summary += f"You're {debt:.1f} hours in sleep debt against your {goal:.0f}-hour goal this week. "
        else:
            summary += f"You're on track with your {goal:.0f}-hour goal this week. "

        await self.capability_worker.speak(summary)

        if n >= 5:
            pattern = self.capability_worker.text_to_text_response(
                ANALYSIS_PROMPT.format(
                    name=name,
                    n=n,
                    data=json.dumps(recent, indent=2),
                )
            )
            await self.capability_worker.speak(pattern)

    # ------------------------------------------------------------------
    # Tonight's tip
    # ------------------------------------------------------------------

    async def _handle_tonight_tip(self, data: dict):
        name = data.get("user_name", "")
        log = data.get("sleep_log", [])
        recent = self._get_recent_log(data, days=14)

        tip = self.capability_worker.text_to_text_response(
            TONIGHT_TIP_PROMPT.format(
                name=name or "friend",
                data=json.dumps(recent, indent=2) if recent else "[]",
            )
        )
        await self.capability_worker.speak(tip)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def _handle_history(self, data: dict):
        log = data.get("sleep_log", [])
        name = data.get("user_name", "")

        if not log:
            await self.capability_worker.speak(
                f"No sleep entries yet{', ' + name if name else ''}. "
                f"Say 'how did I sleep' each morning to start building your history."
            )
            return

        recent = log[-5:]
        lines = []
        for e in reversed(recent):
            lines.append(
                f"{e['date']}: {e['hours']}h, quality {e['quality']}/10"
                + (f" — {e['notes']}" if e.get("notes") else "")
            )
        await self.capability_worker.speak(
            f"Your last {len(recent)} nights, {name}: " + ". ".join(lines) + "."
        )

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ("report", "pattern", "insight", "summary", "trend", "picture")):
            return "REPORT"
        if any(w in t for w in ("tip", "tonight", "help me sleep", "better sleep", "wind down")):
            return "TONIGHT_TIP"
        if any(w in t for w in ("evening", "before bed", "habit", "log my habit")):
            return "EVENING_HABITS"
        if any(w in t for w in ("history", "last night", "last week", "entries")):
            return "HISTORY"
        return "MORNING_CHECKIN"

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[SleepTracker] Trigger: {trigger!r}")

            data = self._load_data()

            if not data.get("setup_complete"):
                data = await self._handle_setup(data)
                return

            intent = self._classify_intent(trigger or "")
            self.worker.editor_logging_handler.info(f"[SleepTracker] Intent: {intent}")

            if intent == "MORNING_CHECKIN":
                await self._handle_morning_checkin(data)
            elif intent == "REPORT":
                await self._handle_report(data)
            elif intent == "TONIGHT_TIP":
                await self._handle_tonight_tip(data)
            elif intent == "EVENING_HABITS":
                await self._handle_evening_habits(data)
            elif intent == "HISTORY":
                await self._handle_history(data)

            while True:
                reply = await self.capability_worker.user_response()
                if reply is None:
                    break
                reply_clean = reply.strip()
                if not reply_clean:
                    break
                if trigger and reply_clean.lower() == trigger.strip().lower():
                    continue
                if self._is_exit(reply_clean):
                    break
                data = self._load_data()
                intent = self._classify_intent(reply_clean)
                self.worker.editor_logging_handler.info(f"[SleepTracker] Follow-up intent: {intent}")
                if intent == "MORNING_CHECKIN":
                    await self._handle_morning_checkin(data)
                elif intent == "REPORT":
                    await self._handle_report(data)
                elif intent == "TONIGHT_TIP":
                    await self._handle_tonight_tip(data)
                elif intent == "EVENING_HABITS":
                    await self._handle_evening_habits(data)
                elif intent == "HISTORY":
                    await self._handle_history(data)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SleepTracker] Error: {e!r}")
            await self.capability_worker.speak("Something went wrong. Try again in a moment.")
        finally:
            self.capability_worker.resume_normal_flow()
