import json
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "sleep_quality_tracker_data"

WEEKLY_SUMMARY_PROMPT = (
    "You are giving {name} their weekly sleep summary in a warm, conversational tone. "
    "Data from the last 7 nights: {data}. "
    "Cover: average hours, average quality, best night, and one standout pattern if visible. "
    "End with one encouraging sentence. Max 4 sentences. Plain text only."
)


class SleepQualityTrackerBackgroundCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.background_daemon_mode = background_daemon_mode
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.watch_loop())

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SleepTrackerBG] Load error: {e!r}")
        return {}

    def _save_data(self, data: dict):
        try:
            result = self.capability_worker.create_key(STORAGE_KEY, data)
            if not result.get("success"):
                self.capability_worker.update_key(STORAGE_KEY, data)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SleepTrackerBG] Save error: {e!r}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _current_hour(self) -> int:
        return datetime.now().hour

    def _already_logged_today(self, data: dict) -> bool:
        today = self._today_str()
        return any(e.get("date") == today for e in data.get("sleep_log", []))

    def _evening_habits_logged_today(self, data: dict) -> bool:
        today = self._today_str()
        for e in data.get("sleep_log", []):
            if e.get("date") == today and e.get("evening_habits"):
                return True
        return False

    def _is_sunday(self) -> bool:
        return datetime.now().weekday() == 6

    def _weekly_summary_sent_this_week(self, data: dict) -> bool:
        last_sent = data.get("weekly_summary_last_sent")
        if not last_sent:
            return False
        last_dt = datetime.strptime(last_sent, "%Y-%m-%d")
        return (datetime.now() - last_dt).days < 7

    def _get_week_log(self, data: dict) -> list:
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        return [e for e in data.get("sleep_log", []) if e.get("date", "") >= cutoff]

    def _has_enough_data(self, data: dict) -> bool:
        return len(data.get("sleep_log", [])) >= 3

    # ------------------------------------------------------------------
    # Daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        self.capability_worker.resume_normal_flow()
        self.worker.editor_logging_handler.info("[SleepTrackerBG] Daemon started")

        while True:
            try:
                await self.worker.session_tasks.sleep(900.0)

                data = self._load_data()

                if not data.get("setup_complete"):
                    continue

                name = data.get("user_name", "")
                hour = self._current_hour()

                # Morning nudge: 7–8 AM, sleep not yet logged
                if 7 <= hour < 8 and not self._already_logged_today(data):
                    self.worker.editor_logging_handler.info("[SleepTrackerBG] Morning nudge")
                    await self.capability_worker.send_interrupt_signal()
                    await self.capability_worker.speak(
                        f"Morning{', ' + name if name else ''}! "
                        f"Ready for your sleep check-in? Just say 'how did I sleep'."
                    )

                # Evening habit nudge: 9–10 PM, habits not yet logged
                elif 21 <= hour < 22 and not self._evening_habits_logged_today(data):
                    self.worker.editor_logging_handler.info("[SleepTrackerBG] Evening nudge")
                    await self.capability_worker.send_interrupt_signal()
                    await self.capability_worker.speak(
                        f"Evening{', ' + name if name else ''}! "
                        f"Want to log your habits before bed? "
                        f"Say 'evening habits' and it takes under a minute."
                    )

                # Weekly summary: Sunday 8–9 AM, not yet sent this week
                elif (
                    self._is_sunday()
                    and 8 <= hour < 9
                    and not self._weekly_summary_sent_this_week(data)
                    and self._has_enough_data(data)
                ):
                    self.worker.editor_logging_handler.info("[SleepTrackerBG] Weekly summary")
                    week_log = self._get_week_log(data)
                    if week_log:
                        summary = self.capability_worker.text_to_text_response(
                            WEEKLY_SUMMARY_PROMPT.format(
                                name=name or "friend",
                                data=json.dumps(week_log, indent=2),
                            )
                        )
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(summary)
                        data["weekly_summary_last_sent"] = self._today_str()
                        self._save_data(data)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[SleepTrackerBG] Loop error: {e!r}")
                await self.worker.session_tasks.sleep(300.0)
