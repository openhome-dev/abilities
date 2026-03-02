import json
from datetime import datetime
from time import time
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class AlarmCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    # -----------------------------
    # alarms.json safe read/write
    # -----------------------------
    async def _reset_alarms_file(self, reason: str = "") -> None:
        filename = "alarms.json"
        try:
            if reason:
                self.worker.editor_logging_handler.warning(
                    f"{time()}: alarms.json reset. Reason: {reason}"
                )
            if await self.capability_worker.check_if_file_exists(filename, False):
                await self.capability_worker.delete_file(filename, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"{time()}: Failed to reset alarms.json: {e}"
            )

    async def _read_alarms(self):
        filename = "alarms.json"

        if not await self.capability_worker.check_if_file_exists(filename, False):
            return []

        raw = await self.capability_worker.read_file(filename, False)
        if not (raw or "").strip():
            return []

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed

            await self._reset_alarms_file("JSON is valid but not a list")
            return []
        except Exception as e:
            await self._reset_alarms_file(f"Corrupted JSON: {e}")
            return []

    async def _write_alarms(self, alarms):
        filename = "alarms.json"
        if not isinstance(alarms, list):
            alarms = []

        payload = json.dumps(alarms, ensure_ascii=False, indent=2)

        # If write_file appends, we MUST delete first to avoid: [old][new]
        await self._reset_alarms_file("Pre-write delete to avoid append-concat")

        try:
            await self.capability_worker.write_file(filename, payload, False)

            # quick verify
            verify_raw = await self.capability_worker.read_file(filename, False)
            verify_parsed = json.loads(verify_raw)
            if not isinstance(verify_parsed, list):
                await self._reset_alarms_file("Post-write verification failed (not list)")
                await self.capability_worker.write_file(filename, "[]", False)

        except Exception as e:
            await self._reset_alarms_file(f"Write failed: {e}")
            try:
                await self.capability_worker.write_file(filename, "[]", False)
            except Exception:
                pass

    # -----------------------------
    # LLM prompt
    # -----------------------------
    def _build_system_prompt(self, now, tz_name):
        return f"""
You are an alarm time parser.

Current datetime (authoritative): {now.isoformat()}
Timezone (authoritative): {tz_name}

Task:
Convert the user request into a future datetime.

Rules:
- If the user requests deleting alarms (e.g., "delete all alarms", "remove all alarms", "clear alarms"),
  respond with EXACTLY:
  DELETE_ALL_ALARMS
- If day/date is missing, ask:
  QUESTION:at what day ?
- If user says something like "26 February" then it automatically means you can know the day and year will be current year
- Prefer to use the same year of current date, unless the user tells about a different year.
- If the user text clearly contains a day + month (including spelled numbers), then we never allow “QUESTION:at what day ?”
Instead, if anything is missing, only allow time questions.
- If date and month is present no need to ask about what day.
- If time is missing, ask exactly:
  QUESTION:at what time ?
- If hour/minute unclear, ask exactly:
  QUESTION:at what hour and minute ?
- If "after X hours/minutes" is given, treat it as relative to current datetime.
- "tomorrow" means next day in given timezone.
- "next Friday" means next occurrence (if today is Friday, use next week).
- You can only give three type of responses:
  * DELETE_ALL_ALARMS
  * QUESTION: (anything related to setting alarm)
  * Valid JSON response of alarm
- Output MUST be either:
  - DELETE_ALL_ALARMS
  - one QUESTION:... line (exactly as specified above), OR
  - valid JSON only (no extra text).
- If User's first message is "Set an alarm for 11:07AM Thursday, 26 February" then it means you have all the info no need to ask further question just return in valid json
Return JSON only when complete:
{{
  "target_iso": "ISO8601 datetime with timezone offset",
  "human_time": "Friendly readable time",
  "timezone": "{tz_name}"
}}
"""

    async def first_setup(self):
        try:
            user_text = await self.capability_worker.wait_for_complete_transcription()
            original_request = user_text

            # Fast-path: if user literally says it, reset without LLM
            t0 = (user_text or "").strip().lower()
            if "delete all alarms" in t0:
                await self._reset_alarms_file("User requested delete all alarms")
                # leave a clean empty list behind
                try:
                    await self.capability_worker.write_file("alarms.json", "[]", False)
                except Exception:
                    pass
                await self.capability_worker.speak("All alarms deleted.")
                return

            tz_name = self.capability_worker.get_timezone()
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = ZoneInfo("UTC")

            now = datetime.now(tz=tz)
            system_prompt = self._build_system_prompt(now, tz_name)
            history = []

            for _ in range(6):
                llm_response = self.capability_worker.text_to_text_response(
                    user_text,
                    history,
                    system_prompt,
                )
                self.worker.editor_logging_handler.info(user_text)
                self.worker.editor_logging_handler.info(system_prompt)
                self.worker.editor_logging_handler.info(llm_response)
                history.append({"role": "user", "content": user_text})

                if isinstance(llm_response, str):
                    if llm_response.strip() == "DELETE_ALL_ALARMS":
                        await self._reset_alarms_file("LLM delete all alarms")
                        try:
                            await self.capability_worker.write_file("alarms.json", "[]", False)
                        except Exception:
                            pass
                        await self.capability_worker.speak("All alarms deleted.")
                        return

                    if llm_response.startswith("QUESTION:"):
                        history.append({"role": "assistant", "content": llm_response})
                        question = llm_response.split("QUESTION:", 1)[1].strip()
                        user_text = await self.capability_worker.run_io_loop(question)
                        continue

                # not a question -> should be JSON
                try:
                    parsed = json.loads(llm_response)
                except Exception:
                    await self.capability_worker.speak("I couldn't understand the time. Try again.")
                    return

                if not parsed.get("target_iso"):
                    await self.capability_worker.speak("I couldn't understand the time. Try again.")
                    return

                alarm = {
                    "id": f"alarm_{int(time() * 1000)}",
                    "created_at_epoch": int(time()),
                    "timezone": parsed.get("timezone", tz_name),
                    "target_iso": parsed["target_iso"],
                    "human_time": parsed.get("human_time", parsed["target_iso"]),
                    "source_text": original_request,
                    "status": "scheduled",
                }

                alarms = await self._read_alarms()
                alarms.append(alarm)
                await self._write_alarms(alarms)

                await self.capability_worker.speak(f"Alarm set for {alarm['human_time']}.")
                return

            await self.capability_worker.speak("Too many questions. Please try setting the alarm again.")

        except Exception:
            pass
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker):
        try:
            worker.editor_logging_handler.info("Alarm Capability")
            self.worker = worker
            self.capability_worker = CapabilityWorker(self)
            self.worker.session_tasks.create(self.first_setup())
        except Exception as e:
            self.worker.editor_logging_handler.warning(e)
