import re
import json
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# ==========================================
# SUPABASE CONFIG
# ==========================================
SUPABASE_URL = "https://baygwvfczfwxltolxzzp.supabase.co"
# REPLACED FOR PR COMPLIANCE:
SUPABASE_KEY = "YOUR_SUPABASE_ANON_KEY_HERE"

TABLE_NAME = "patients"
REST_URL = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

PKT = timezone(timedelta(hours=5))

# Global Exit and Back Words
EXIT_WORDS = ("exit", "stop", "quit", "cancel", "never mind", "nevermind", "goodbye", "bye")


class CarexpertVoiceDeskCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run_session())

    def _is_exit(self, text: str) -> bool:
        low = (text or "").lower().strip()
        return any(w in low for w in EXIT_WORDS)

    # ==========================================
    # STEP 0: MAIN SESSION LOOP (The Gatekeeper)
    # ==========================================
    async def run_session(self):
        try:
            while True:
                await self.capability_worker.speak(
                    "Welcome to CareXpert! Are you at the reception to add a patient, "
                    "or opening the doctor dashboard?"
                )
                baseline = await self.capability_worker.user_response()
                role = ""

                while not role:
                    # UPDATED FOR OPENHOME COMPLIANCE
                    await self.worker.session_tasks.sleep(0.4)
                    ans = await self.capability_worker.user_response()
                    if not ans:
                        continue

                    if self._is_exit(ans):
                        await self.capability_worker.speak("Okay, exiting. Have a great day!")
                        return  # Exits the whole loop and capability

                    if ans.strip() and ans.strip() != baseline:
                        low = ans.lower()
                        if any(w in low for w in ["doctor", "dashboard", "desk", "physician"]):
                            role = "doctor"
                        elif any(w in low for w in ["add", "patient", "new", "regist", "reception", "counter"]):
                            role = "counter"
                        else:
                            baseline = ans.strip()
                            await self.capability_worker.speak("Please say 'add a patient' or 'doctor dashboard'.")

                # Route to appropriate loop
                if role == "doctor":
                    exit_requested = await self.run_doctor_dashboard()
                    if exit_requested:
                        return
                elif role == "counter":
                    exit_requested = await self.run_token_counter()
                    if exit_requested:
                        return

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Session error: {e}")
            try:
                await self.capability_worker.speak("Something went wrong. Please try again.")
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # ==========================================
    # STEP 1: DOCTOR DASHBOARD MENU
    # ==========================================
    async def run_doctor_dashboard(self):
        """Returns True if user says EXIT, False if user says BACK to return to Main Menu."""
        while True:
            await self.capability_worker.speak(
                "Doctor dashboard open. Say prescription, queue, next patient, completed today, "
                "history, skip, wait time, follow ups, or go back."
            )
            baseline = await self.capability_worker.user_response()
            action = ""

            while not action:
                await self.worker.session_tasks.sleep(0.4)
                ans = await self.capability_worker.user_response()
                if not ans:
                    continue

                if self._is_exit(ans):
                    await self.capability_worker.speak("Okay, exiting. Have a great day!")
                    return True  # Bubble up the exit

                if ans.strip() and ans.strip() != baseline:
                    low = ans.lower()
                    if any(w in low for w in ["back", "main menu", "go back", "return"]):
                        await self.capability_worker.speak("Returning to main menu.")
                        return False  # Return to Main Session Loop

                    if any(w in low for w in ["call next", "next patient", "call the next"]):
                        action = "call_next"
                    elif any(w in low for w in ["queue", "how many", "waiting count", "position"]):
                        action = "queue"
                    elif any(w in low for w in ["completed today", "my patients today", "patients today"]):
                        action = "completed_today"
                    elif any(w in low for w in ["follow up", "follow ups"]):
                        action = "todays_followups"
                    elif any(w in low for w in ["history", "past visit", "previous visit"]):
                        action = "history"
                    elif any(w in low for w in ["skip", "not available", "no show"]):
                        action = "skip"
                    elif any(w in low for w in ["average wait", "wait time"]):
                        action = "avg_wait"
                    elif any(w in low for w in ["prescri", "assign", "medicine", "update"]):
                        action = "assign_rx"
                    else:
                        baseline = ans.strip()
                        await self.capability_worker.speak(
                            "Please choose an action like 'assign prescription', 'check queue', or 'go back'."
                        )

            # Execute the selected doctor action
            exit_requested = False
            if action == "assign_rx":
                exit_requested = await self.run_doctor_flow()
            elif action == "queue":
                exit_requested = await self.run_queue_status()
            elif action == "call_next":
                exit_requested = await self.run_call_next()
            elif action == "completed_today":
                exit_requested = await self.run_completed_today()
            elif action == "history":
                exit_requested = await self.run_patient_history()
            elif action == "skip":
                exit_requested = await self.run_skip_patient()
            elif action == "avg_wait":
                exit_requested = await self.run_average_wait_time()
            elif action == "todays_followups":
                exit_requested = await self.run_todays_followups()

            # If any of the features returned True (user said exit mid-flow), kill the dashboard.
            if exit_requested:
                return True

    # ==========================================

    async def run_token_counter(self):
        try:
            await self.capability_worker.speak("Please tell me the patient's name, age, and gender.")
            baseline = await self.capability_worker.user_response()
            details = ""
            while not details:
                await self.worker.session_tasks.sleep(0.4)
                ans = await self.capability_worker.user_response()
                if not ans:
                    continue
                if self._is_exit(ans):
                    await self.capability_worker.speak("Okay, exiting. Have a great day!")
                    return True
                if ans.strip() and ans.strip() != baseline:
                    details = ans.strip()

            prompt = (
                "Extract name, age, and gender from the following text. "
                "Return ONLY a valid JSON object: "
                '{"name": "...", "age": 0, "gender": "..."}. '
                f"Text: '{details}'"
            )
            raw_response = self.capability_worker.text_to_text_response(prompt)
            cleaned_json = re.sub(r"^```(?:json)?|```$", "", (raw_response or "").strip())

            name, age, gender = "Unknown", 25, "Male"
            try:
                parsed_data = json.loads(cleaned_json)
                if isinstance(parsed_data, dict):
                    name = str(parsed_data.get("name", "Unknown"))
                    raw_age = parsed_data.get("age", 25)
                    age = int(raw_age) if str(raw_age).isdigit() else self._clean_age(str(raw_age))
                    gender = self._clean_gender(str(parsed_data.get("gender", "Male")))
            except Exception:
                age = self._clean_age(details)
                gender = self._clean_gender(details)

            await self.capability_worker.speak("Is this Emergency or OPD?")
            baseline_vt = details
            visit_type = ""
            while not visit_type:
                await self.worker.session_tasks.sleep(0.4)
                ans = await self.capability_worker.user_response()
                if not ans:
                    continue
                if self._is_exit(ans):
                    await self.capability_worker.speak("Okay, exiting.")
                    return True
                if ans.strip() and ans.strip() != baseline_vt:
                    low_ans = ans.lower()
                    if "emerg" in low_ans:
                        visit_type = "Emergency"
                    elif "opd" in low_ans or "o p d" in low_ans:
                        visit_type = "OPD"
                    else:
                        baseline_vt = ans.strip()
                        await self.capability_worker.speak("Please say Emergency or OPD.")

            severity = "normal"
            if visit_type == "Emergency":
                await self.capability_worker.speak("Is this a critical emergency or a normal emergency?")
                baseline_sev = visit_type
                severity_answer = ""
                while not severity_answer:
                    await self.worker.session_tasks.sleep(0.4)
                    ans = await self.capability_worker.user_response()
                    if not ans:
                        continue
                    if self._is_exit(ans):
                        await self.capability_worker.speak("Okay, exiting.")
                        return True
                    if ans.strip() and ans.strip() != baseline_sev:
                        low_ans = ans.lower()
                        if "critic" in low_ans:
                            severity_answer = "critical"
                        elif "normal" in low_ans:
                            severity_answer = "normal"
                        else:
                            baseline_sev = ans.strip()
                            await self.capability_worker.speak("Please say critical or normal.")
                severity = severity_answer

            token = await asyncio.to_thread(self._generate_token, visit_type)
            payload = {
                "token_number": token,
                "patient_name": name,
                "age": age,
                "gender": gender,
                "visit_type": visit_type,
                "prescription": "None",
                "status": "Waiting",
                "date": datetime.now(PKT).strftime("%Y-%m-%d"),
                "severity": severity,
            }

            resp = await asyncio.to_thread(
                requests.post, REST_URL, headers={**SUPABASE_HEADERS, "Prefer": "return=representation"}, json=payload, timeout=10
            )
            if resp.status_code == 429:
                await self.worker.session_tasks.sleep(1.5)
                resp = await asyncio.to_thread(
                    requests.post, REST_URL, headers={**SUPABASE_HEADERS, "Prefer": "return=representation"}, json=payload, timeout=10
                )

            if resp.status_code == 201:
                await self.capability_worker.speak(f"Registration completed. Token {token} has been generated for {name}.")
            else:
                self.worker.editor_logging_handler.error(f"INSERT failed: status={resp.status_code}")
                await self.capability_worker.speak("Sorry, something went wrong while saving the token.")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Token counter error: {e}")
            await self.capability_worker.speak("Sorry, an error occurred while registering.")

        return False

    # ==========================================
    async def run_doctor_flow(self):
        try:
            await self.capability_worker.speak("Please tell me the token number.")
            baseline = await self.capability_worker.user_response()
            token_id = ""
            while not token_id:
                await self.worker.session_tasks.sleep(0.4)
                ans = await self.capability_worker.user_response()
                if not ans:
                    continue
                if self._is_exit(ans):
                    await self.capability_worker.speak("Okay, exiting.")
                    return True
                if ans.strip() and ans.strip() != baseline:
                    token_id = self._extract_token(ans)
                    if not token_id:
                        baseline = ans.strip()
                        await self.capability_worker.speak("I didn't catch the token number. Please repeat.")

            resp = await asyncio.to_thread(
                requests.get, REST_URL, headers=SUPABASE_HEADERS, params={"select": "*"}, timeout=10
            )
            tokens = resp.json() if resp.status_code == 200 else []
            if not isinstance(tokens, list):
                tokens = []

            record = next(
                (r for r in tokens if isinstance(r, dict) and str(r.get("token_number", "")).replace("-", "").strip().upper() == token_id.upper()),
                None,
            )
            if not record:
                await self.capability_worker.speak(f"No patient found with token {token_id}.")
                return False

            existing_rx = record.get("prescription", "")
            if existing_rx and existing_rx.strip().lower() != "none":
                await self.capability_worker.speak(
                    f"Token {token_id} has a prescription: {existing_rx}. Tell me the new medicines if you want to update it, or say 'no' to keep it."
                )
                medicines = ""
                baseline_med = await self.capability_worker.user_response()
                while not medicines:
                    await self.worker.session_tasks.sleep(0.4)
                    ans = await self.capability_worker.user_response()
                    if not ans:
                        continue
                    if self._is_exit(ans):
                        await self.capability_worker.speak("Okay, exiting.")
                        return True
                    if ans.strip() and ans.strip() != baseline_med:
                        low_ans = ans.strip().lower()
                        if "no" in low_ans or "keep" in low_ans:
                            await self.capability_worker.speak("Prescription kept unchanged.")
                            return False
                        if low_ans.strip(" .!,") in ("yes", "yeah", "yep", "haan", "ok", "okay", "update", "sure"):
                            baseline_med = ans.strip()
                            await self.capability_worker.speak("Sure, please tell me the actual medicines to save.")
                            continue
                        medicines = ans.strip()
            else:
                await self.capability_worker.speak(f"Patient is {record.get('patient_name', '')}. Please tell me the medicines.")
                medicines = ""
                baseline_med = await self.capability_worker.user_response()
                while not medicines:
                    await self.worker.session_tasks.sleep(0.4)
                    ans = await self.capability_worker.user_response()
                    if not ans:
                        continue
                    if self._is_exit(ans):
                        await self.capability_worker.speak("Okay, exiting.")
                        return True
                    if ans.strip() and ans.strip() != baseline_med:
                        medicines = ans.strip()

            # Immediate Prescription Save
            update_resp = await asyncio.to_thread(
                requests.patch, REST_URL, headers={**SUPABASE_HEADERS, "Prefer": "return=minimal"},
                params={"id": f"eq.{record['id']}"},
                json={"prescription": medicines, "status": "Completed", "completed_at": datetime.now(timezone.utc).isoformat()},
                timeout=10,
            )
            if update_resp.status_code not in (200, 204):
                self.worker.editor_logging_handler.error(f"UPDATE failed: status={update_resp.status_code}")
                await self.capability_worker.speak("Something went wrong while saving the prescription.")
                return False

            await self.capability_worker.speak(f"Medicines successfully saved for token {token_id}.")

            # Follow Up Logic
            await self.capability_worker.speak("Any follow up needed? Say the number of days, or say 'no'.")
            baseline_fu = await self.capability_worker.user_response()
            follow_up_answer = None
            follow_up_date = None

            while follow_up_answer is None:
                await self.worker.session_tasks.sleep(0.4)
                ans = await self.capability_worker.user_response()
                if not ans:
                    continue
                if self._is_exit(ans):
                    await self.capability_worker.speak("Okay, exiting.")
                    return True
                if ans.strip() and ans.strip() != baseline_fu:
                    low_ans = ans.lower()
                    if "no" in low_ans and "day" not in low_ans:
                        follow_up_answer = "None"
                    else:
                        days = self._extract_days(ans)
                        if days:
                            follow_up_date = (datetime.now(PKT) + timedelta(days=days)).strftime("%Y-%m-%d")
                            follow_up_answer = follow_up_date
                        else:
                            baseline_fu = ans.strip()
                            await self.capability_worker.speak("Please say a number of days, like 'follow up in 3 days', or say 'no'.")

            if follow_up_date:
                fu_update = await asyncio.to_thread(
                    requests.patch, REST_URL, headers={**SUPABASE_HEADERS, "Prefer": "return=minimal"},
                    params={"id": f"eq.{record['id']}"}, json={"follow_up_date": follow_up_date}, timeout=10,
                )
                if fu_update.status_code in (200, 204):
                    await self.capability_worker.speak(f"Follow up scheduled for {follow_up_date}.")
                else:
                    await self.capability_worker.speak("Couldn't save the follow up date.")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Doctor flow error: {e}")
            await self.capability_worker.speak("Sorry, an error occurred. Please try again.")

        return False

    # ==========================================

    async def run_queue_status(self):
        try:
            today = datetime.now(PKT).strftime("%Y-%m-%d")
            resp = await asyncio.to_thread(
                requests.get, REST_URL, headers=SUPABASE_HEADERS, params={"select": "*", "date": f"eq.{today}", "status": "eq.Waiting"}, timeout=10
            )
            rows = resp.json() if resp.status_code == 200 else []
            if not isinstance(rows, list):
                rows = []

            total_waiting = len(rows)
            emergency_waiting = len([r for r in rows if str(r.get("visit_type", "")).lower() == "emergency"])
            opd_waiting = total_waiting - emergency_waiting

            if total_waiting == 0:
                await self.capability_worker.speak("No patients are currently waiting. The queue is empty.")
            else:
                await self.capability_worker.speak(f"There are {total_waiting} patients waiting. {emergency_waiting} emergency and {opd_waiting} OPD.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Queue error: {e}")
            await self.capability_worker.speak("Sorry, I couldn't fetch the queue status.")
        return False

    async def run_call_next(self):
        try:
            today = datetime.now(PKT).strftime("%Y-%m-%d")
            resp = await asyncio.to_thread(
                requests.get, REST_URL, headers=SUPABASE_HEADERS, params={"select": "*", "date": f"eq.{today}", "status": "eq.Waiting", "order": "id.asc"}, timeout=10
            )
            rows = resp.json() if resp.status_code == 200 else []
            if not isinstance(rows, list):
                rows = []

            if not rows:
                await self.capability_worker.speak("There are no patients waiting right now.")
                return False

            critical_rows = [r for r in rows if str(r.get("visit_type", "")).lower() == "emergency" and str(r.get("severity", "")).lower() == "critical"]
            normal_emergency_rows = [r for r in rows if str(r.get("visit_type", "")).lower() == "emergency" and str(r.get("severity", "")).lower() != "critical"]

            next_patient = critical_rows[0] if critical_rows else (normal_emergency_rows[0] if normal_emergency_rows else rows[0])

            update_resp = await asyncio.to_thread(
                requests.patch, REST_URL, headers={**SUPABASE_HEADERS, "Prefer": "return=minimal"},
                params={"id": f"eq.{next_patient['id']}"}, json={"status": "In Progress"}, timeout=10
            )
            if update_resp.status_code in (200, 204):
                await self.capability_worker.speak(f"Next patient is {next_patient.get('patient_name', '')}, token {next_patient.get('token_number', '')}. Please call them in.")
            else:
                await self.capability_worker.speak("Found the next patient, but couldn't update their status.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Call next error: {e}")
            await self.capability_worker.speak("Sorry, something went wrong.")
        return False

    async def run_completed_today(self):
        try:
            today = datetime.now(PKT).strftime("%Y-%m-%d")
            resp = await asyncio.to_thread(
                requests.get, REST_URL, headers=SUPABASE_HEADERS, params={"select": "*", "date": f"eq.{today}", "status": "eq.Completed"}, timeout=10
            )
            rows = resp.json() if resp.status_code == 200 else []
            if not isinstance(rows, list):
                rows = []

            if not rows:
                await self.capability_worker.speak("No patients have been completed today yet.")
                return False

            names = [r.get("patient_name", "Unknown") for r in rows]
            names_text = ", ".join(names[:8])
            extra = f", and {len(names) - 8} more" if len(names) > 8 else ""
            await self.capability_worker.speak(f"You have completed {len(rows)} patients today: {names_text}{extra}.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Completed today error: {e}")
            await self.capability_worker.speak("Sorry, I couldn't fetch completed patients.")
        return False

    async def run_patient_history(self):
        try:
            await self.capability_worker.speak("Which patient's history would you like to check?")
            baseline = await self.capability_worker.user_response()
            patient_name = ""
            while not patient_name:
                await self.worker.session_tasks.sleep(0.4)
                ans = await self.capability_worker.user_response()
                if not ans:
                    continue
                if self._is_exit(ans):
                    await self.capability_worker.speak("Okay, exiting.")
                    return True
                if ans.strip() and ans.strip() != baseline:
                    patient_name = ans.strip()

            resp = await asyncio.to_thread(
                requests.get, REST_URL, headers=SUPABASE_HEADERS,
                params={"select": "*", "patient_name": f"ilike.*{patient_name}*", "order": "date.desc"}, timeout=10
            )
            rows = resp.json() if resp.status_code == 200 else []
            if not isinstance(rows, list):
                rows = []

            if not rows:
                await self.capability_worker.speak(f"No visit history found for {patient_name}.")
                return False

            await self.capability_worker.speak(f"Found {len(rows)} visits for {patient_name}.")
            for r in rows[:5]:
                rx = r.get("prescription", "None")
                date = r.get("date", "unknown date")
                if rx and rx.strip().lower() != "none":
                    await self.capability_worker.speak(f"On {date}, prescribed: {rx}.")
                else:
                    await self.capability_worker.speak(f"On {date}, no prescription recorded.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"History error: {e}")
            await self.capability_worker.speak("Sorry, I couldn't fetch history.")
        return False

    async def run_skip_patient(self):
        try:
            await self.capability_worker.speak("Which token should be skipped?")
            baseline = await self.capability_worker.user_response()
            token_id = ""
            while not token_id:
                await self.worker.session_tasks.sleep(0.4)
                ans = await self.capability_worker.user_response()
                if not ans:
                    continue
                if self._is_exit(ans):
                    await self.capability_worker.speak("Okay, exiting.")
                    return True
                if ans.strip() and ans.strip() != baseline:
                    token_id = self._extract_token(ans)
                    if not token_id:
                        baseline = ans.strip()
                        await self.capability_worker.speak("I didn't catch the token number. Please repeat.")

            resp = await asyncio.to_thread(
                requests.get, REST_URL, headers=SUPABASE_HEADERS, params={"select": "*", "status": "eq.Waiting"}, timeout=10
            )
            rows = resp.json() if resp.status_code == 200 else []
            if not isinstance(rows, list):
                rows = []

            record = next((r for r in rows if isinstance(r, dict) and str(r.get("token_number", "")).replace("-", "").strip().upper() == token_id.upper()), None)
            if not record:
                await self.capability_worker.speak(f"No waiting patient found with token {token_id}.")
                return False

            update_resp = await asyncio.to_thread(
                requests.patch, REST_URL, headers={**SUPABASE_HEADERS, "Prefer": "return=minimal"},
                params={"id": f"eq.{record['id']}"}, json={"status": "Skipped"}, timeout=10
            )
            if update_resp.status_code in (200, 204):
                await self.capability_worker.speak(f"Token {token_id} has been marked as skipped.")
            else:
                await self.capability_worker.speak("Something went wrong while skipping.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Skip error: {e}")
            await self.capability_worker.speak("Sorry, an error occurred.")
        return False

    async def run_average_wait_time(self):
        try:
            today = datetime.now(PKT).strftime("%Y-%m-%d")
            resp = await asyncio.to_thread(
                requests.get, REST_URL, headers=SUPABASE_HEADERS, params={"select": "*", "date": f"eq.{today}", "status": "eq.Completed"}, timeout=10
            )
            rows = resp.json() if resp.status_code == 200 else []
            if not isinstance(rows, list):
                rows = []

            durations = []
            for r in rows:
                created, completed = r.get("created_at"), r.get("completed_at")
                if not created or not completed:
                    continue
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    completed_dt = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                    diff_minutes = (completed_dt - created_dt).total_seconds() / 60
                    if diff_minutes >= 0:
                        durations.append(diff_minutes)
                except Exception:
                    continue

            if not durations:
                await self.capability_worker.speak("No completed patient data with timing is available yet.")
                return False

            avg_minutes = round(sum(durations) / len(durations))
            await self.capability_worker.speak(f"Based on {len(durations)} completed patients today, the average wait time was {avg_minutes} minutes.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Wait time error: {e}")
            await self.capability_worker.speak("Sorry, I couldn't calculate the average wait time.")
        return False

    async def run_todays_followups(self):
        try:
            today = datetime.now(PKT).strftime("%Y-%m-%d")
            resp = await asyncio.to_thread(
                requests.get, REST_URL, headers=SUPABASE_HEADERS, params={"select": "*", "follow_up_date": f"eq.{today}"}, timeout=10
            )
            rows = resp.json() if resp.status_code == 200 else []
            if not isinstance(rows, list):
                rows = []

            if not rows:
                await self.capability_worker.speak("No follow ups are scheduled for today.")
                return False

            names = [r.get("patient_name", "Unknown") for r in rows]
            names_text = ", ".join(names[:8])
            await self.capability_worker.speak(f"There are {len(rows)} follow ups scheduled for today: {names_text}.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Follow ups error: {e}")
            await self.capability_worker.speak("Sorry, I couldn't fetch today's follow ups.")
        return False

    # ==========================================
    # PARSING HELPERS
    # ==========================================
    def _clean_age(self, text: str) -> int:
        match = re.search(r"\d+", text)
        if match:
            return int(match.group())
        words_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
        for word, val in words_map.items():
            if word in text.lower():
                return val
        return 25

    def _clean_gender(self, text: str) -> str:
        low = text.lower()
        if any(w in low for w in ["femal", "woman", "girl", "she", "feme"]):
            return "Female"
        if any(w in low for w in ["mal", "man", "boy", "he", "main", "mle", "may"]):
            return "Male"
        return "Male"

    def _extract_token(self, text: str) -> str:
        t = text.lower().strip()
        words_map = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
        for word, digit in words_map.items():
            t = t.replace(word, digit)
        t = t.replace("-", "").replace(" ", "")
        is_emergency = "e" in t or "emerg" in t
        match = re.search(r"\d+", t)
        if not match:
            return ""
        num_str = match.group()
        return f"E{num_str}" if is_emergency else num_str

    def _extract_days(self, text: str):
        low = text.lower()
        match = re.search(r"\d+", low)
        if match:
            return int(match.group())
        words_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "week": 7, "ten": 10}
        for word, val in words_map.items():
            if word in low:
                return val
        return None

    def _generate_token(self, v_type: str) -> str:
        today = datetime.now(PKT).strftime("%Y-%m-%d")
        all_tokens = []
        try:
            resp = requests.get(REST_URL, headers=SUPABASE_HEADERS, params={"select": "*", "date": f"eq.{today}"}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    all_tokens = [t for t in data if isinstance(t, dict)]
        except Exception:
            all_tokens = []

        try:
            if v_type == "Emergency":
                emergency_tokens = [t for t in all_tokens if str(t.get("token_number", "")).upper().startswith("E")]
                return f"E{len(emergency_tokens) + 1}"
            else:
                opd_tokens = [t for t in all_tokens if not str(t.get("token_number", "")).upper().startswith("E")]
                return str(len(opd_tokens) + 1)
        except Exception:
            suffix = datetime.now(PKT).strftime("%H%M")
            return f"E{suffix}" if v_type == "Emergency" else suffix
