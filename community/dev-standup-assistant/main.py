import json
import re
from datetime import datetime, timedelta, timezone

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "end"}

DATA_FILE = "dev_standup_db.json"     # persistent store
LATEST_FILE = "latest_standup.md"     # latest recap export


def is_exit(text: str) -> bool:
    if not text:
        return False

    t = text.strip().lower()

    # Remove punctuation, collapse spaces
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    if not t:
        return False

    # Exact match
    if t in EXIT_WORDS:
        return True

    # First token match (e.g., "done please", "stop now")
    first = t.split(" ", 1)[0]
    if first in EXIT_WORDS:
        return True

    # Common phrase patterns
    if "i am done" in t or "i'm done" in t or "please stop" in t:
        return True

    return False


def clean_json_fences(s: str) -> str:
    if not s:
        return ""
    return s.replace("```json", "").replace("```", "").strip()


def today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def yesterday_key() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


class DevStandupAssistantCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    # ---------------------------
    # Storage helpers
    # ---------------------------
    async def load_db(self) -> dict:
        cw = self.capability_worker
        try:
            if not await cw.check_if_file_exists(DATA_FILE, False):
                return {"days": {}}
            raw = await cw.read_file(DATA_FILE, False)
            return json.loads(raw) if raw else {"days": {}}
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Failed to load DB: {e}")
            return {"days": {}}

    async def save_db(self, db: dict) -> None:
        cw = self.capability_worker
        try:
            if await cw.check_if_file_exists(DATA_FILE, False):
                await cw.delete_file(DATA_FILE, False)
            await cw.write_file(DATA_FILE, json.dumps(db), False)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Failed to save DB: {e}")

    async def save_latest_md(self, md: str) -> None:
        cw = self.capability_worker
        try:
            if await cw.check_if_file_exists(LATEST_FILE, False):
                await cw.delete_file(LATEST_FILE, False)
            await cw.write_file(LATEST_FILE, md, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Failed to save latest MD: {e}")

    def ensure_day(self, db: dict, day_key: str) -> dict:
        db.setdefault("days", {})
        if day_key not in db["days"]:
            db["days"][day_key] = {
                "raw_text": "",
                "updates": [],   # list of {"ts_utc":..., "text":...}
                "summary": "",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        return db["days"][day_key]

    # ---------------------------
    # LLM helpers
    # ---------------------------
    def llm_make_summary(self, day_key: str, raw_text: str, updates: list) -> str:
        update_block = "\n".join([f"- {u.get('text','')}" for u in (updates or []) if u.get("text")])
        prompt = (
            "You are a developer standup assistant.\n"
            "Write a meeting-ready standup recap in 2–4 sentences.\n"
            "Keep it spoken-friendly. Mention blockers briefly if present.\n"
            "Do not invent anything not in the input.\n\n"
            f"Date: {day_key}\n"
            f"Standup (raw):\n{raw_text}\n\n"
            f"Additional updates:\n{update_block if update_block else '(none)'}"
        )
        return self.capability_worker.text_to_text_response(prompt)

    def llm_detect_missing_followup(self, raw_text: str) -> str:
        """
        Returns ONE short follow-up question tailored to what's missing.
        Examples: blockers missing, next steps missing, unclear scope.
        """
        prompt = (
            "You are a standup assistant.\n"
            "Given the user's raw standup message, decide ONE helpful follow-up question to ask.\n"
            "Goals:\n"
            "- If blockers aren't mentioned, ask about blockers.\n"
            "- If next steps aren't mentioned, ask what they plan next.\n"
            "- If it's vague, ask for one concrete detail.\n"
            "Return ONLY the question, no extra text.\n\n"
            f"Raw standup:\n{raw_text}"
        )
        q = self.capability_worker.text_to_text_response(prompt).strip()
        return q if q else "Anything else you want to add?"

    def llm_answer_query(self, day_key: str, day_obj: dict, user_question: str) -> str:
        """
        Answers user question using stored raw_text + updates.
        This is the core 'LLM retrieval' behavior (no rigid schema).
        """
        raw_text = day_obj.get("raw_text", "")
        updates = day_obj.get("updates", [])
        update_block = "\n".join([f"- {u.get('text','')}" for u in (updates or []) if u.get("text")])

        prompt = (
            "You are a developer standup assistant.\n"
            "Answer the user's question using ONLY the provided standup notes for that day.\n"
            "If the info isn't present, say you don't have it.\n"
            "Keep the answer short and spoken-friendly.\n\n"
            f"Date: {day_key}\n"
            f"Standup (raw):\n{raw_text}\n\n"
            f"Additional updates:\n{update_block if update_block else '(none)'}\n\n"
            f"User question: {user_question}"
        )
        return self.capability_worker.text_to_text_response(prompt)

    def llm_route_intent(self, user_input: str) -> dict:
        """
        Intent routing with minimal structure.
        """
        prompt = (
            "Classify the user's request for a developer standup assistant.\n"
            "Return ONLY valid JSON.\n"
            'Schema: {"intent":"...", "text":""}\n'
            "Allowed intents:\n"
            '- "new_standup"\n'
            '- "update_today"\n'
            '- "read_today"\n'
            '- "read_yesterday"\n'
            '- "recap_today"\n'
            '- "recap_yesterday"\n'
            '- "ask_today"\n'
            '- "ask_yesterday"\n'
            '- "clear_today"\n'
            '- "help"\n'
            '- "unknown"\n'
            "Rules:\n"
            "- If user is asking a specific question about today's content (blockers/projects/plan), use ask_today.\n"
            "- If user says update today / add to today, use update_today with text field.\n"
            "Examples:\n"
            '- "new standup" -> {"intent":"new_standup","text":""}\n'
            '- "update today: fixed staging, waiting on QA" -> {"intent":"update_today","text":"fixed staging, waiting on QA"}\n'
            '- "read today" -> {"intent":"read_today","text":""}\n'
            '- "recap today" -> {"intent":"recap_today","text":""}\n'
            '- "what are my blockers today" -> {"intent":"ask_today","text":"what are my blockers today"}\n'
            '- "what did I say about payments today" -> {"intent":"ask_today","text":"what did I say about payments today"}\n'
            '- "clear today" -> {"intent":"clear_today","text":""}\n\n'
            f"User: {user_input}"
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        cleaned = clean_json_fences(raw)
        try:
            obj = json.loads(cleaned)
            return {"intent": (obj.get("intent") or "unknown").strip(), "text": (obj.get("text") or "").strip()}
        except Exception:
            return {"intent": "unknown", "text": ""}

    # ---------------------------
    # Actions
    # ---------------------------
    async def do_new_standup(self, db: dict) -> dict:
        cw = self.capability_worker
        day_key = today_key()
        day = self.ensure_day(db, day_key)

        await cw.speak("Okay — tell me your standup in one go.")
        raw_text = await cw.user_response()
        if is_exit(raw_text):
            return db

        day["raw_text"] = raw_text.strip()
        day["updates"] = []
        day["updated_at_utc"] = datetime.now(timezone.utc).isoformat()

        # Tailored follow-up
        follow_q = self.llm_detect_missing_followup(day["raw_text"])
        await cw.speak(follow_q)
        more = await cw.user_response()
        if more and not is_exit(more) and more.strip().lower() not in {"no", "nope", "nothing", "that's all"}:
            day["updates"].append({"ts_utc": datetime.now(timezone.utc).isoformat(), "text": more.strip()})
            day["updated_at_utc"] = datetime.now(timezone.utc).isoformat()

        # Create summary + export
        day["summary"] = self.llm_make_summary(day_key, day["raw_text"], day["updates"])
        await self.save_db(db)

        md = f"*Standup — {day_key}*\n\n{day['summary']}\n"
        await self.save_latest_md(md)

        await cw.speak("Saved. If you want, say read today, recap today, or ask me something like blockers or a project.")
        return db

    async def do_update_today(self, db: dict, text: str) -> dict:
        cw = self.capability_worker
        day_key = today_key()
        day = self.ensure_day(db, day_key)

        if not text:
            await cw.speak("What do you want to add to today?")
            text = await cw.user_response()
            if is_exit(text):
                return db

        day["updates"].append({"ts_utc": datetime.now(timezone.utc).isoformat(), "text": text.strip()})
        day["updated_at_utc"] = datetime.now(timezone.utc).isoformat()

        # Refresh summary after update
        if day.get("raw_text"):
            day["summary"] = self.llm_make_summary(day_key, day["raw_text"], day["updates"])

        await self.save_db(db)
        await cw.speak("Got it — updated today’s standup.")
        return db

    async def do_read_day(self, db: dict, day_key: str) -> None:
        cw = self.capability_worker
        day = db.get("days", {}).get(day_key)
        if not day or (not day.get("raw_text") and not day.get("updates")):
            await cw.speak("I don’t have anything saved for that day yet.")
            return

        # Natural read-back: speak summary if we have it; else speak raw in a compact way
        if day.get("summary"):
            await cw.speak(f"Here’s what you saved for {day_key}.")
            await cw.speak(day["summary"])
            return

        # Fallback
        await cw.speak(f"Here’s what you saved for {day_key}.")
        await cw.speak(day.get("raw_text", ""))

    async def do_recap_day(self, db: dict, day_key: str) -> None:
        cw = self.capability_worker
        day = db.get("days", {}).get(day_key)
        if not day or (not day.get("raw_text") and not day.get("updates")):
            await cw.speak("I don’t have anything saved for that day yet.")
            return

        # Ensure summary exists
        if not day.get("summary") and day.get("raw_text"):
            day["summary"] = self.llm_make_summary(day_key, day["raw_text"], day.get("updates", []))
            await self.save_db(db)

        await cw.speak(day.get("summary") or "I have notes saved, but I couldn’t generate a recap right now.")

    async def do_ask_day(self, db: dict, day_key: str, question: str) -> None:
        cw = self.capability_worker
        day = db.get("days", {}).get(day_key)
        if not day or (not day.get("raw_text") and not day.get("updates")):
            await cw.speak("I don’t have anything saved for that day yet.")
            return

        answer = self.llm_answer_query(day_key, day, question)
        await cw.speak(answer)

    async def do_clear_today(self, db: dict) -> dict:
        cw = self.capability_worker
        dk = today_key()
        if dk not in db.get("days", {}):
            await cw.speak("Nothing to clear for today.")
            return db

        confirmed = await cw.run_confirmation_loop("Clear today’s saved standup?")
        if not confirmed:
            await cw.speak("Okay, keeping it.")
            return db

        db["days"].pop(dk, None)
        await self.save_db(db)
        await cw.speak("Cleared today’s standup.")
        return db

    async def help(self) -> None:
        await self.capability_worker.speak(
            "Try: new standup, update today, read today, recap today, or ask: what are my blockers today."
        )

    # ---------------------------
    # Main loop
    # ---------------------------
    async def run(self):
        cw = self.capability_worker
        db = await self.load_db()

        await cw.speak("Standup assistant ready. Say new standup, read today, recap today, or update today.")
        while True:
            user = await cw.user_response()
            if is_exit(user):
                break

            route = self.llm_route_intent(user)
            intent = route.get("intent", "unknown")
            text = route.get("text", "")

            if intent == "new_standup":
                db = await self.do_new_standup(db)
            elif intent == "update_today":
                db = await self.do_update_today(db, text)
            elif intent == "read_today":
                await self.do_read_day(db, today_key())
            elif intent == "read_yesterday":
                await self.do_read_day(db, yesterday_key())
            elif intent == "recap_today":
                await self.do_recap_day(db, today_key())
            elif intent == "recap_yesterday":
                await self.do_recap_day(db, yesterday_key())
            elif intent == "ask_today":
                q = text or user
                await self.do_ask_day(db, today_key(), q)
            elif intent == "ask_yesterday":
                q = text or user
                await self.do_ask_day(db, yesterday_key(), q)
            elif intent == "clear_today":
                db = await self.do_clear_today(db)
            elif intent == "help":
                await self.help()
            else:
                await cw.speak("Try: new standup, read today, recap today, update today, or help.")

            await cw.speak("What next?")

        await cw.speak("Alright, exiting standup.")
        cw.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())