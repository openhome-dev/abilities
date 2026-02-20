import asyncio
import json
import os
import re
import time
from datetime import datetime
from typing import ClassVar, Dict, Optional

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class PomodoroFocusTimerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    PREFS_FILENAME: ClassVar[str] = "pomodoro_prefs.json"
    HISTORY_FILENAME: ClassVar[str] = "pomodoro_history.json"
    PERSIST: ClassVar[bool] = False

    EXIT_WORDS: ClassVar[set] = {
        "stop", "exit", "quit", "done", "cancel",
        "bye", "goodbye", "leave", "finish", "end"
    }

    LISTEN_CHUNK_SECONDS: ClassVar[int] = 5

    WORD_NUMBERS: ClassVar[Dict[str, int]] = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
        "forty": 40, "fifty": 50
    }

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"]
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_main())

    async def get_preferences(self) -> dict:
        if await self.capability_worker.check_if_file_exists(
            self.PREFS_FILENAME, self.PERSIST
        ):
            raw = await self.capability_worker.read_file(
                self.PREFS_FILENAME, self.PERSIST
            )
            try:
                return json.loads(raw)
            except Exception:
                return self.get_default_preferences()
        return self.get_default_preferences()

    def get_default_preferences(self) -> dict:
        return {
            "focus_minutes": 25,
            "short_break_minutes": 5,
            "long_break_minutes": 15,
            "sessions_per_cycle": 4,
            "halfway_checkin": True
        }

    async def save_preferences(self, prefs: dict):
        if await self.capability_worker.check_if_file_exists(
            self.PREFS_FILENAME, self.PERSIST
        ):
            await self.capability_worker.delete_file(
                self.PREFS_FILENAME, self.PERSIST
            )
        await self.capability_worker.write_file(
            self.PREFS_FILENAME, json.dumps(prefs), self.PERSIST
        )

    async def get_history(self) -> list:
        if await self.capability_worker.check_if_file_exists(
            self.HISTORY_FILENAME, self.PERSIST
        ):
            raw = await self.capability_worker.read_file(
                self.HISTORY_FILENAME, self.PERSIST
            )
            try:
                return json.loads(raw)
            except Exception:
                return []
        return []

    async def save_history(self, history: list):
        cutoff_date = datetime.now().timestamp() - (90 * 24 * 60 * 60)
        history = [
            s for s in history
            if datetime.fromisoformat(s["started_at"]).timestamp() > cutoff_date
        ]

        if await self.capability_worker.check_if_file_exists(
            self.HISTORY_FILENAME, self.PERSIST
        ):
            await self.capability_worker.delete_file(
                self.HISTORY_FILENAME, self.PERSIST
            )
        await self.capability_worker.write_file(
            self.HISTORY_FILENAME, json.dumps(history), self.PERSIST
        )

    async def log_session(
        self,
        duration_minutes: int,
        completed: bool,
        session_number: int,
        label: Optional[str] = None
    ):
        history = await self.get_history()
        now = datetime.now()
        session_id = f"sess_{int(time.time())}"

        session = {
            "id": session_id,
            "date": now.strftime("%Y-%m-%d"),
            "started_at": now.isoformat(),
            "ended_at": now.isoformat(),
            "duration_minutes": duration_minutes,
            "label": label,
            "completed": completed,
            "session_number": session_number
        }

        history.append(session)
        await self.save_history(history)

    async def show_stats(self, query: str):
        history = await self.get_history()

        if not history:
            await self.capability_worker.speak(
                "You haven't completed any focus sessions yet. "
                "Say start to begin your first one!"
            )
            return

        today = datetime.now().strftime("%Y-%m-%d")
        prompt = (
            "You are a productivity assistant summarizing the user's focus "
            "session history. Given their session log and query, generate "
            "a brief, encouraging spoken summary. Keep it to 2-3 sentences. "
            "Include specific numbers. Be warm, not robotic.\n\n"
            f"Today's date: {today}\n"
            f"Session history: {json.dumps(history)}\n"
            f"User asked: {query}"
        )

        summary = self.capability_worker.text_to_text_response(prompt).strip()
        await self.capability_worker.speak(summary)

        await self.worker.session_tasks.sleep(0.2)
        start_response = await self.capability_worker.run_io_loop(
            "Want to start a focus session?"
        )

        if start_response and self.is_yes_response(start_response):
            intent = {"mode": "focus", "focus_minutes": 25, "label": None}
            await self.run_focus_cycle(intent)

    async def run_focus_cycle(self, intent: dict):
        prefs = await self.get_preferences()

        await self.worker.session_tasks.sleep(0.1)
        cycle_response = await self.capability_worker.run_io_loop(
            "How many cycles do you want? Default is 4 cycles. "
            "Say yes to keep it or no to customize it."
        )

        if cycle_response and self.is_no_response(cycle_response):
            custom_cycle = await self.capability_worker.run_io_loop(
                "How many cycles?"
            )
            if custom_cycle:
                try:
                    cycles = int(''.join(filter(str.isdigit, custom_cycle)))
                    prefs["sessions_per_cycle"] = cycles
                except Exception:
                    prefs["sessions_per_cycle"] = 4
        else:
            prefs["sessions_per_cycle"] = 4

        await self.worker.session_tasks.sleep(0.1)
        config_response = await self.capability_worker.run_io_loop(
            "Would you like the default Pomodoro or customize? "
            "Say 'default' for 25 minute focus, 5 minute short break, "
            "15 minute long break. Say 'customize' to set your own values. "
            "Or tell me just minutes to directly start that session."
        )

        if not config_response:
            pass
        elif "customize" in config_response.lower():
            await self.worker.session_tasks.sleep(0.1)
            focus_resp = await self.capability_worker.run_io_loop(
                "How many minutes for focus sessions?"
            )
            if focus_resp:
                try:
                    prefs["focus_minutes"] = int(
                        ''.join(filter(str.isdigit, focus_resp))
                    )
                except Exception:
                    pass

            await self.worker.session_tasks.sleep(0.1)
            short_resp = await self.capability_worker.run_io_loop(
                "How many minutes for short breaks?"
            )
            if short_resp:
                try:
                    prefs["short_break_minutes"] = int(
                        ''.join(filter(str.isdigit, short_resp))
                    )
                except Exception:
                    pass

            if prefs["sessions_per_cycle"] > 1:
                await self.worker.session_tasks.sleep(0.1)
                long_resp = await self.capability_worker.run_io_loop(
                    "How many minutes for long breaks?"
                )
                if long_resp:
                    try:
                        prefs["long_break_minutes"] = int(
                            ''.join(filter(str.isdigit, long_resp))
                        )
                    except Exception:
                        pass

        elif "default" not in config_response.lower():
            try:
                direct_mins = int(''.join(filter(str.isdigit, config_response)))
                prefs["focus_minutes"] = direct_mins
            except Exception:
                pass

        await self.save_preferences(prefs)

        session_count = 0
        sessions_per_cycle = prefs["sessions_per_cycle"]

        while True:
            session_count += 1

            completed = await self.run_focus_session(
                prefs["focus_minutes"],
                session_count,
                sessions_per_cycle,
                prefs.get("halfway_checkin", True)
            )

            if completed:
                await self.log_session(
                    prefs["focus_minutes"],
                    True,
                    session_count,
                    intent.get("label")
                )

                if session_count % sessions_per_cycle == 0:
                    await self.capability_worker.speak(
                        f"Excellent! You completed {sessions_per_cycle} sessions. "
                        f"Time for a {prefs['long_break_minutes']} minute long break."
                    )
                    await self.run_break(
                        prefs["long_break_minutes"],
                        is_long_break=True
                    )

                    await self.worker.session_tasks.sleep(0.2)
                    continue_resp = await self.capability_worker.run_io_loop(
                        "You completed a full cycle! Want to keep going?"
                    )

                    if not continue_resp or not self.is_yes_response(continue_resp):
                        break
                else:
                    await self.capability_worker.speak(
                        f"Nice work! Session {session_count} complete. "
                        f"Time for a {prefs['short_break_minutes']} minute break."
                    )
                    await self.run_break(
                        prefs["short_break_minutes"],
                        is_long_break=False
                    )

                    await self.worker.session_tasks.sleep(0.2)
                    continue_resp = await self.capability_worker.run_io_loop(
                        "Ready for another session? Say start or done."
                    )

                    if not continue_resp or self.is_exit(continue_resp):
                        await self.capability_worker.speak("Goodbye.")
                        break
                    if (
                        not self.is_yes_response(continue_resp)
                        and "start" not in continue_resp.lower()
                    ):
                        break
            else:
                break

        await self.speak_session_summary(session_count)

    def _word_to_num(self, word: str) -> Optional[int]:
        if not word:
            return None
        word = word.lower().strip()
        if word in self.WORD_NUMBERS:
            return self.WORD_NUMBERS[word]
        parts = re.split(r"[\s-]+", word)
        total = 0
        any_found = False
        for p in parts:
            if p in self.WORD_NUMBERS:
                total += self.WORD_NUMBERS[p]
                any_found = True
            else:
                try:
                    total += int(p)
                    any_found = True
                except Exception:
                    pass
        if any_found:
            return total
        return None

    def _parse_add_minutes(self, text: str) -> Optional[int]:
        if not text:
            return None
        t = text.lower()
        m = re.search(r"(\d+)\s*(?:min(?:ute)?s?)?", t)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
        m2 = re.search(r"(?:add|extend|plus)?\s*([a-z\s-]+)\s*(?:min(?:ute)?s?)", t)
        if m2:
            wordnum = m2.group(1).strip()
            val = self._word_to_num(wordnum)
            if val is not None:
                return val
        m3 = re.search(r"(?:add|extend|plus)\s+([a-z-]+)", t)
        if m3:
            wordnum = m3.group(1).strip()
            val = self._word_to_num(wordnum)
            if val is not None:
                return val
        return None

    async def _speak_remaining(self, remaining_seconds: float):
        if remaining_seconds <= 0:
            await self.capability_worker.speak("No time remaining.")
            return
        mins = int(remaining_seconds // 60)
        secs = int(remaining_seconds % 60)
        if mins > 0:
            if secs > 0:
                await self.capability_worker.speak(
                    f"{mins} minutes and {secs} seconds remaining."
                )
            else:
                await self.capability_worker.speak(f"{mins} minutes remaining.")
        else:
            await self.capability_worker.speak(f"{secs} seconds remaining.")

    async def _confirm_and_cancel_session(
        self,
        session_start_time: float,
        session_number: int,
        label: Optional[str]
    ):
        await self.capability_worker.speak(
            "Do you want to cancel the session? Say yes to confirm."
        )
        confirm = await self.capability_worker.run_io_loop("Confirm cancel?")
        if confirm and self.is_yes_response(confirm):
            elapsed = time.time() - session_start_time
            elapsed_minutes = max(0, int(elapsed // 60))
            await self.log_session(elapsed_minutes, False, session_number, label)
            await self.capability_worker.speak("Session cancelled.")
            return True
        await self.capability_worker.speak("Continuing session.")
        return False

    async def _handle_mid_session_command(
        self,
        text: str,
        context: str,
        session_start_time: float,
        end_time: float,
        session_number: int,
        label: Optional[str],
        halfway_checkin_flag_container: dict
    ):
        if not text:
            return {"action": "none"}

        t = text.lower().strip()

        if any(w in t for w in ["stop", "cancel", "done", "quit", "end"]):
            cancelled = await self._confirm_and_cancel_session(
                session_start_time, session_number, label
            )
            if cancelled:
                return {"action": "stop"}
            return {"action": "none"}

        if any(
            phrase in t
            for phrase in [
                "how much time", "time left", "remaining",
                "what's left", "how much is left"
            ]
        ):
            remaining = max(0, end_time - time.time())
            await self._speak_remaining(remaining)
            return {"action": "time"}

        if context == "break" and "skip" in t:
            return {"action": "skip_break"}

        add = self._parse_add_minutes(t)
        if add is not None:
            added_seconds = int(add * 60)
            new_end_time = end_time + added_seconds
            if add == 1:
                await self.capability_worker.speak("Adding 1 minute.")
            else:
                await self.capability_worker.speak(f"Adding {add} minutes.")
            return {
                "action": "extend",
                "added_seconds": added_seconds,
                "new_end_time": new_end_time
            }

        return {"action": "none"}

    async def run_focus_session(
        self,
        duration_minutes: int,
        session_number: int,
        total_sessions: int,
        halfway_checkin: bool
    ) -> bool:
        if session_number == 1:
            await self.capability_worker.speak(
                f"Starting a {duration_minutes} minute focus session. "
                "I'll stay quiet until it's time for a break. Let's go!"
            )
        elif session_number == total_sessions:
            await self.capability_worker.speak(
                f"Last session in this cycle. {duration_minutes} minutes, "
                "then you've earned a long break."
            )
        else:
            await self.capability_worker.speak(
                f"Focus session {session_number}. {duration_minutes} minutes. "
                "You've got this."
            )

        duration_seconds = duration_minutes * 60
        start_time = time.time()
        end_time = start_time + duration_seconds
        halfway_announced = False

        halfway_container = {"halfway_checkin": halfway_checkin}

        while True:
            remaining = end_time - time.time()
            if remaining <= 0:
                return True

            if (
                halfway_container["halfway_checkin"]
                and session_number == 1
                and (not halfway_announced)
                and (time.time() - start_time) >= (duration_seconds / 2)
            ):
                mins_left = int(max(0, (end_time - time.time()) // 60))
                await self.capability_worker.speak(
                    f"Halfway there. {mins_left} minutes left. Keep going."
                )
                halfway_announced = True

            chunk = min(self.LISTEN_CHUNK_SECONDS, max(0.5, remaining))
            user_input = None
            try:
                user_input = await asyncio.wait_for(
                    self.capability_worker.run_io_loop(""), timeout=chunk
                )
            except asyncio.TimeoutError:
                user_input = None
            except asyncio.CancelledError:
                user_input = None
            except Exception:
                user_input = None

            if user_input:
                result = await self._handle_mid_session_command(
                    user_input,
                    context="focus",
                    session_start_time=start_time,
                    end_time=end_time,
                    session_number=session_number,
                    label=None,
                    halfway_checkin_flag_container=halfway_container
                )
                action = result.get("action", "none")
                if action == "stop":
                    return False
                elif action == "extend":
                    added = result.get("added_seconds", 0)
                    end_time = result.get("new_end_time", end_time + added)
                    duration_seconds = end_time - start_time
                    continue
                elif action in ("time", "none", "skip_checkins"):
                    continue

            await asyncio.sleep(0)

    async def run_break(self, duration_minutes: int, is_long_break: bool):
        duration_seconds = duration_minutes * 60
        start_time = time.time()
        end_time = start_time + duration_seconds

        while True:
            remaining = end_time - time.time()
            if remaining <= 0:
                if is_long_break:
                    await self.capability_worker.speak("Long break done!")
                else:
                    await self.capability_worker.speak("Break's over!")
                return True

            chunk = min(self.LISTEN_CHUNK_SECONDS, max(0.5, remaining))
            user_input = None
            try:
                user_input = await asyncio.wait_for(
                    self.capability_worker.run_io_loop(""), timeout=chunk
                )
            except asyncio.TimeoutError:
                user_input = None
            except asyncio.CancelledError:
                user_input = None
            except Exception:
                user_input = None

            if user_input:
                result = await self._handle_mid_session_command(
                    user_input,
                    context="break",
                    session_start_time=start_time,
                    end_time=end_time,
                    session_number=0,
                    label=None,
                    halfway_checkin_flag_container={"halfway_checkin": False}
                )
                action = result.get("action", "none")
                if action == "skip_break":
                    if is_long_break:
                        await self.capability_worker.speak("Long break skipped.")
                    else:
                        await self.capability_worker.speak("Short break skipped.")
                    return True
                elif action == "extend":
                    added = result.get("added_seconds", 0)
                    end_time = result.get("new_end_time", end_time + added)
                    continue
                elif action == "time":
                    continue
                elif action == "stop":
                    await self.capability_worker.speak("Cancelling and exiting.")
                    return True

            await asyncio.sleep(0)

    async def speak_session_summary(self, session_count: int):
        history = await self.get_history()

        today = datetime.now().strftime("%Y-%m-%d")
        today_sessions = [s for s in history if s["date"] == today]
        total_minutes = sum(s["duration_minutes"] for s in today_sessions)

        week_ago = datetime.now().timestamp() - (7 * 24 * 60 * 60)
        weekly_sessions = [
            s for s in history
            if datetime.fromisoformat(s["started_at"]).timestamp() > week_ago
        ]

        await self.capability_worker.speak(
            f"Great session! You completed {session_count} focus sessions today "
            f"for a total of {total_minutes} minutes of focused work. "
            f"That brings your weekly total to {len(weekly_sessions)} sessions. "
            "Nice work!"
        )

    def is_yes_response(self, text: str) -> bool:
        text_lower = text.lower().strip()
        yes_words = {
            "yes", "yeah", "yep", "sure", "okay",
            "ok", "yup", "correct", "right", "start"
        }
        return any(word in text_lower for word in yes_words)

    def is_no_response(self, text: str) -> bool:
        text_lower = text.lower().strip()
        no_words = {"no", "nope", "nah", "not", "customize"}
        return any(word in text_lower for word in no_words)

    def is_exit(self, text: str) -> bool:
        return any(word in text.lower() for word in self.EXIT_WORDS)

    async def run_main(self):
        try:
            await self.capability_worker.speak("Pomodoro.")
            await self.worker.session_tasks.sleep(0.5)

            choice = await self.capability_worker.run_io_loop(
                "Say my stats or start a focus session."
            )

            if not choice:
                await self.capability_worker.speak("Didn't catch that. Goodbye.")
                return

            # Check for exit words FIRST (like Weather ability)
            if self.is_exit(choice):
                await self.capability_worker.speak("Goodbye.")
                return

            if "stats" in choice.lower() or "stat" in choice.lower():
                await self.show_stats(choice)
            elif (
                "start" in choice.lower()
                or "focus" in choice.lower()
                or "session" in choice.lower()
            ):
                intent = {
                    "mode": "focus",
                    "focus_minutes": 25,
                    "label": None
                }
                await self.run_focus_cycle(intent)
            else:
                await self.capability_worker.speak(
                    "I didn't understand. Say stats or start."
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Pomodoro error: {e}")
            await self.capability_worker.speak("Something went wrong.")
        finally:
            self.capability_worker.resume_normal_flow()
