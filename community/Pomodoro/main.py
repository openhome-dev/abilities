import json
import os
import time
import re
import asyncio
from datetime import datetime
from typing import ClassVar, Optional, Dict

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class PomodoroFocusTimer(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    PREFS_FILENAME: ClassVar[str] = "pomodoro_prefs.json"
    HISTORY_FILENAME: ClassVar[str] = "pomodoro_history.json"
    PERSIST: ClassVar[bool] = False

    EXIT_WORDS: ClassVar[set] = {
        "stop", "exit", "quit", "done", "cancel",
        "bye", "goodbye", "leave", "finish", "end"
    }

    # how frequently (seconds) we attempt to listen for mid-session commands
    LISTEN_CHUNK_SECONDS: ClassVar[int] = 5

    # Small mapping for common spoken number words -> ints
    WORD_NUMBERS: ClassVar[Dict[str, int]] = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50
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

    # --- PERSISTENCE HELPERS ---
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
        # Trim to last 90 days
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

    # --- INTENT CLASSIFICATION ---
    def classify_trigger_intent(self, trigger_context: str) -> dict:
        # Check if user wants stats
        stats_keywords = [
            "stats", "productive", "how many", "sessions",
            "history", "completed"
        ]
        if any(kw in trigger_context.lower() for kw in stats_keywords):
            return {"mode": "stats", "query": trigger_context}

        # Otherwise it's a focus session
        # Parse custom duration if specified
        prompt = (
            f"Parse this focus session request: '{trigger_context}'\n"
            "Return ONLY valid JSON. No markdown fences.\n"
            "{\n"
            '  "focus_minutes": <int, default 25>,\n'
            '  "label": <string or null>\n'
            "}\n"
            "If the user didn't specify a value, use the default."
        )

        response = self.capability_worker.text_to_text_response(prompt).strip()
        # Remove markdown fences if present
        response = response.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(response)
            return {
                "mode": "focus",
                "focus_minutes": parsed.get("focus_minutes", 25),
                "label": parsed.get("label")
            }
        except Exception:
            return {
                "mode": "focus",
                "focus_minutes": 25,
                "label": None
            }

    # --- STATS MODE ---
    async def show_stats(self, query: str):
        history = await self.get_history()

        if not history:
            await self.capability_worker.speak(
                "You haven't completed any focus sessions yet. "
                "Say start to begin your first one!"
            )
            return

        # Generate stats summary with LLM
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

        # Offer to start a session
        await self.worker.session_tasks.sleep(0.2)
        start_response = await self.capability_worker.run_io_loop(
            "Want to start a focus session?"
        )

        if start_response and self.is_yes_response(start_response):
            intent = {"mode": "focus", "focus_minutes": 25, "label": None}
            await self.run_focus_cycle(intent)

    # --- FOCUS CYCLE ---
    async def run_focus_cycle(self, intent: dict):
        prefs = await self.get_preferences()

        # Ask about cycles
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

        # Ask about session configuration
        await self.worker.session_tasks.sleep(0.1)
        config_response = await self.capability_worker.run_io_loop(
            "Would you like the default Pomodoro or customize? "
            "Say 'default' for 25 minute focus, 5 minute short break, "
            "15 minute long break. Say 'customize' to set your own values. "
            "Or tell me just minutes to directly start that session."
        )

        if not config_response:
            # Use defaults
            pass
        elif "customize" in config_response.lower():
            # Custom configuration
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
            # User might have said a number directly
            try:
                direct_mins = int(''.join(filter(str.isdigit, config_response)))
                prefs["focus_minutes"] = direct_mins
            except Exception:
                pass

        # Save preferences
        await self.save_preferences(prefs)

        # Start the cycle
        session_count = 0
        sessions_per_cycle = prefs["sessions_per_cycle"]

        while True:
            session_count += 1

            # Run focus session
            completed = await self.run_focus_session(
                prefs["focus_minutes"],
                session_count,
                sessions_per_cycle,
                prefs.get("halfway_checkin", True)
            )

            if completed:
                # Log the session
                await self.log_session(
                    prefs["focus_minutes"],
                    True,
                    session_count,
                    intent.get("label")
                )

                # Determine break type
                if session_count % sessions_per_cycle == 0:
                    # Long break
                    await self.capability_worker.speak(
                        f"Excellent! You completed {sessions_per_cycle} sessions. "
                        f"Time for a {prefs['long_break_minutes']} minute long break."
                    )
                    # run break returns True if completed normally, 'skipped' if skipped early
                    break_result = await self.run_break(
                        prefs["long_break_minutes"],
                        is_long_break=True
                    )

                    # Ask if they want to continue
                    await self.worker.session_tasks.sleep(0.2)
                    continue_resp = await self.capability_worker.run_io_loop(
                        "You completed a full cycle! Want to keep going?"
                    )

                    if not continue_resp or not self.is_yes_response(continue_resp):
                        break
                else:
                    # Short break
                    await self.capability_worker.speak(
                        f"Nice work! Session {session_count} complete. "
                        f"Time for a {prefs['short_break_minutes']} minute break."
                    )
                    break_result = await self.run_break(
                        prefs["short_break_minutes"],
                        is_long_break=False
                    )

                    # Ask if they want to continue
                    await self.worker.session_tasks.sleep(0.2)
                    continue_resp = await self.capability_worker.run_io_loop(
                        "Ready for another session? Say start or done."
                    )

                    if not continue_resp or self.is_exit(continue_resp):
                        break
                    if not self.is_yes_response(continue_resp) and "start" not in continue_resp.lower():
                        break
            else:
                # User stopped early
                break

        # Session summary
        await self.speak_session_summary(session_count)

    # --- MID-SESSION COMMAND HANDLING HELPERS ---
    def _word_to_num(self, word: str) -> Optional[int]:
        if not word:
            return None
        word = word.lower().strip()
        # direct match
        if word in self.WORD_NUMBERS:
            return self.WORD_NUMBERS[word]
        # handle combined words like "twenty five"
        parts = re.split(r"[\s-]+", word)
        total = 0
        any_found = False
        for p in parts:
            if p in self.WORD_NUMBERS:
                total += self.WORD_NUMBERS[p]
                any_found = True
            else:
                # try numeric form
                try:
                    total += int(p)
                    any_found = True
                except Exception:
                    pass
        if any_found:
            return total
        return None

    def _parse_add_minutes(self, text: str) -> Optional[int]:
        """
        Tries to parse "add 5 minutes", "add five minutes", "add 2", "add two" etc.
        Returns integer minutes or None.
        """
        if not text:
            return None

        t = text.lower()

        # first try digits: "add 5 minutes" or "add 5"
        m = re.search(r"(\d+)\s*(?:min(?:ute)?s?)?", t)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass

        # try word numbers: "add five minutes"
        m2 = re.search(r"(?:add|extend|plus)?\s*([a-z\s-]+)\s*(?:min(?:ute)?s?)", t)
        if m2:
            wordnum = m2.group(1).strip()
            val = self._word_to_num(wordnum)
            if val is not None:
                return val

        # fallback: look for "add <word>" without "minutes"
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
                await self.capability_worker.speak(f"{mins} minutes and {secs} seconds remaining.")
            else:
                await self.capability_worker.speak(f"{mins} minutes remaining.")
        else:
            await self.capability_worker.speak(f"{secs} seconds remaining.")

    async def _confirm_and_cancel_session(self, session_start_time: float, session_number: int, label: Optional[str]):
        # Ask for confirmation
        await self.capability_worker.speak("Do you want to cancel the session? Say yes to confirm.")
        confirm = await self.capability_worker.run_io_loop("Confirm cancel?")
        if confirm and self.is_yes_response(confirm):
            # log partial session
            elapsed = time.time() - session_start_time
            elapsed_minutes = max(0, int(elapsed // 60))
            await self.log_session(elapsed_minutes, False, session_number, label)
            await self.capability_worker.speak("Session cancelled.")
            return True
        else:
            await self.capability_worker.speak("Continuing session.")
            return False

    async def _handle_mid_session_command(self, text: str, context: str, session_start_time: float, end_time: float, session_number: int, label: Optional[str], halfway_checkin_flag_container: dict):
        """
        Handle commands and return a dict with possible keys:
        - action: "none" | "stop" | "extend" | "time" | "skip_break" | "skip_checkins"
        - added_seconds: int (if extend)
        - new_end_time: float (if extend)
        """
        if not text:
            return {"action": "none"}

        t = text.lower().strip()

        # Exit / stop / cancel
        if any(w in t for w in ["stop", "cancel", "done", "quit", "end"]):
            cancelled = await self._confirm_and_cancel_session(session_start_time, session_number, label)
            if cancelled:
                return {"action": "stop"}
            else:
                return {"action": "none"}

        # How much time left?
        if any(phrase in t for phrase in ["how much time", "time left", "remaining", "what's left", "how much is left"]):
            remaining = max(0, end_time - time.time())
            await self._speak_remaining(remaining)
            return {"action": "time"}

        # Add / extend minutes
        add = self._parse_add_minutes(t)
        if add is not None:
            added_seconds = int(add * 60)
            new_end_time = end_time + added_seconds
            # Speak confirmation
            if add == 1:
                await self.capability_worker.speak("Adding 1 minute.")
            else:
                await self.capability_worker.speak(f"Adding {add} minutes.")
            return {"action": "extend", "added_seconds": added_seconds, "new_end_time": new_end_time}

        # Skip break (only meaningful during break)
        if context == "break" and any(word in t for word in ["skip break", "skip"]):
            await self.capability_worker.speak("Skipping break.")
            return {"action": "skip_break"}

        # Skip halfway check-ins
        if "skip check" in t or "skip check-ins" in t or "skip checkins" in t:
            # mutate container (since booleans are passed by value)
            halfway_checkin_flag_container["halfway_checkin"] = False
            await self.capability_worker.speak("Halfway check-ins turned off.")
            return {"action": "skip_checkins"}

        # Unrecognized -> speak a short help
        await self.capability_worker.speak(
            "I heard that. You can ask how much time is left, say 'add 5 minutes', or say stop to cancel."
        )
        return {"action": "none"}

    # --- FOCUS / BREAK WITH IN-SESSION LISTENING ---
    async def run_focus_session(
        self,
        duration_minutes: int,
        session_number: int,
        total_sessions: int,
        halfway_checkin: bool
    ) -> bool:
        # Announce start
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

        # Run timer with mid-session command support
        duration_seconds = duration_minutes * 60
        start_time = time.time()
        end_time = start_time + duration_seconds

        halfway_announced = False
        # container for toggling halfway_checkin through commands
        halfway_container = {"halfway_checkin": halfway_checkin}

        while True:
            remaining = end_time - time.time()
            if remaining <= 0:
                # Session complete
                return True

            # Halfway check-in (use container value for updatable flag)
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
                halfway_announced = True  # Don't repeat

            # Wait for either user input or chunk expiry
            chunk = min(self.LISTEN_CHUNK_SECONDS, max(0.5, remaining))
            user_input = None
            try:
                # run_io_loop will wait for input; we timeout if none within chunk seconds
                user_input = await asyncio.wait_for(
                    self.capability_worker.run_io_loop(""), timeout=chunk
                )
            except asyncio.TimeoutError:
                user_input = None
            except asyncio.CancelledError:
                # If cancelled externally, continue loop safely
                user_input = None
            except Exception:
                # swallow other exceptions to avoid killing timer; continue
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
                    # User confirmed stop -> return False (caller treats as stopped early)
                    return False
                elif action == "extend":
                    added = result.get("added_seconds", 0)
                    end_time = result.get("new_end_time", end_time + added)
                    # adjust duration_seconds for potential halfway calculation
                    duration_seconds = end_time - start_time
                    # continue the loop (will reflect new end_time)
                    continue
                elif action in ("time", "none", "skip_checkins"):
                    # already handled inside handler; continue loop
                    continue

            # no user input this chunk -> loop again (time continues)
            # small sleep for safety to yield control (but we've already waited via wait_for)
            await asyncio.sleep(0)

    async def run_break(self, duration_minutes: int, is_long_break: bool):
        duration_seconds = duration_minutes * 60
        start_time = time.time()
        end_time = start_time + duration_seconds

        while True:
            remaining = end_time - time.time()
            if remaining <= 0:
                # Break complete
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
                    # End break early
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
                    # If user cancels during break, speak summary and exit break
                    await self.capability_worker.speak("Cancelling and exiting.")
                    return True

            await asyncio.sleep(0)

    async def speak_session_summary(self, session_count: int):
        history = await self.get_history()

        # Get today's sessions
        today = datetime.now().strftime("%Y-%m-%d")
        today_sessions = [s for s in history if s["date"] == today]
        total_minutes = sum(s["duration_minutes"] for s in today_sessions)

        # Get weekly sessions
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

    # --- HELPER METHODS ---
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

    # --- MAIN ENTRY POINT ---
    async def run_main(self):
        try:
            # Say "Pomodoro"
            await self.capability_worker.speak("Pomodoro.")
            await self.worker.session_tasks.sleep(0.5)

            # Wait for user to choose: stats or start session
            choice = await self.capability_worker.run_io_loop(
                "Say my stats or start a focus session."
            )

            # If there is no user response (silent / empty), do not say goodbye — just return.
            if not choice:
                return

            # If user explicitly said an exit word, say goodbye and exit.
            if self.is_exit(choice):
                await self.capability_worker.speak("Goodbye.")
                return

            # Classify intent
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
