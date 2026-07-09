import json
import asyncio
import requests
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

TASKS_SYSTEM = (
    "You are a concise voice to-do list assistant running on OpenHome. "
    "The user is speaking — all your output will be read aloud. "
    "Keep every response under 2 sentences and 20 words. "
    "Use plain spoken English. "
    "Never use markdown, bullet points, numbered lists, emojis, or URLs."
)


def _spoken_date(iso_date: str) -> str:
    """Convert ISO date string like '2026-03-27' to spoken form like 'March 27'."""
    try:
        dt = datetime.strptime(iso_date[:10], "%Y-%m-%d")
        return dt.strftime("%B %d").replace(" 0", " ")
    except Exception:
        return iso_date[:10]


# Low-level Tasks helpers
def _build_tasks_service(token: str):
    creds = Credentials(token=token)
    return build("tasks", "v1", credentials=creds)

def _get_all_tasklists(service) -> list:
    """Fetch all task lists for the user."""
    result = service.tasklists().list(maxResults=100).execute()
    return result.get("items", [])

def _get_tasks(service) -> list:
    """Fetch all incomplete tasks from ALL task lists."""
    tasklists = _get_all_tasklists(service)
    all_tasks = []
    for tl in tasklists:
        tl_id = tl["id"]
        tl_title = tl.get("title", "Unknown list")
        result = service.tasks().list(
            tasklist=tl_id,
            showCompleted=False,
            maxResults=20,
        ).execute()
        for task in result.get("items", []):
            task["_tasklist_id"] = tl_id
            task["_tasklist_title"] = tl_title
            all_tasks.append(task)
    return all_tasks

def _add_task(service, title: str, notes: str = None, due: str = None, tasklist_id: str = "@default") -> bool:
    body = {"title": title}
    if notes:
        body["notes"] = notes
    if due:
        body["due"] = due
    service.tasks().insert(tasklist=tasklist_id, body=body).execute()
    return True

def _complete_task(service, task_id: str, tasklist_id: str = "@default") -> bool:
    service.tasks().patch(
        tasklist=tasklist_id,
        task=task_id,
        body={"status": "completed"},
    ).execute()
    return True

def _delete_task(service, task_id: str, tasklist_id: str = "@default") -> bool:
    service.tasks().delete(tasklist=tasklist_id, task=task_id).execute()
    return True

def _update_task(service, task_id: str, new_title: str, tasklist_id: str = "@default") -> bool:
    service.tasks().patch(
        tasklist=tasklist_id,
        task=task_id,
        body={"title": new_title},
    ).execute()
    return True


class GoogleTodoCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    # ── LLM helpers ──────────────────────────────────────────────────

    def _llm(self, prompt: str, history: list = None) -> str:
        return self.capability_worker.text_to_text_response(
            prompt,
            history=history or [],
            system_prompt=TASKS_SYSTEM,
        ).strip()

    def _llm_json(self, prompt: str, fallback: dict = None) -> dict:
        """Call LLM expecting JSON. Returns parsed dict or fallback."""
        raw = self._llm(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except Exception:
            return fallback or {}

    # ── Voice helpers ────────────────────────────────────────────────

    async def _speak(self, text: str) -> None:
        await self.capability_worker.speak(text)

    async def _ask(self, question: str) -> str:
        await self.capability_worker.speak(question)
        return (await self.capability_worker.user_response()).strip()

    # ── Formatting helpers ───────────────────────────────────────────

    @staticmethod
    def _tasks_context(tasks: list) -> str:
        if not tasks:
            return "No tasks"
        return "; ".join(
            f"{i + 1}. {t.get('title', '?')} (list: {t.get('_tasklist_title', 'My Tasks')})"
            for i, t in enumerate(tasks)
        )

    @staticmethod
    def _tasks_summary(tasks: list) -> str:
        if not tasks:
            return "Your list is empty."
        if len(tasks) == 1:
            return f"You have one task: {tasks[0].get('title', 'unnamed')}."
        titles = [t.get("title", "unnamed") for t in tasks]
        joined = ", ".join(titles[:-1]) + f", and {titles[-1]}"
        return f"You have {len(tasks)} tasks: {joined}."

    @staticmethod
    def _tasks_numbered(tasks: list) -> str:
        if not tasks:
            return "Your list is empty."
        return "Here they are: " + ". ".join(
            f"number {i + 1}, {t.get('title', '?')}" for i, t in enumerate(tasks)
        ) + "."

    @staticmethod
    def _task_detail(task: dict) -> str:
        parts = [task.get("title", "unnamed")]
        tl = task.get("_tasklist_title")
        if tl:
            parts.append(f"in list {tl}")
        due = task.get("due")
        if due:
            parts.append(f"due {_spoken_date(due)}")
        notes = task.get("notes", "")
        if notes:
            parts.append(notes[:80])
        return ", ".join(parts)

    # ── Intent classifier (lightweight, one-word) ────────────────────

    def _classify_intent(self, message: str) -> str:
        """Returns one word: ADD, VIEW, COMPLETE, DELETE, UPDATE, EXIT, or UNKNOWN."""
        prompt = (
            f"Classify this intent: '{message}'.\n"
            "Examples:\n"
            "  'add grocery shopping' / 'put birthday on my list' / 'I need to remember something' / 'throw groceries on there' → ADD\n"
            "  'what've I got' / 'read me my list' / 'what's on there' / 'show my tasks' → VIEW\n"
            "  'I finished buy milk' / 'check off grocery' / 'buy milk is done' / 'mark that one done' → COMPLETE\n"
            "  'take holiday off' / 'scratch birthday' / 'lose that one' / 'get rid of it' → DELETE\n"
            "  'call birthday something else' / 'change grocery' / 'rename that one' → UPDATE\n"
            "  'I'm good' / 'all set' / 'we're done' / 'that'll do' / 'nah' / 'no thanks' / 'nothing else' → EXIT\n"
            "  'todo' / 'tasks' / 'task' (just a trigger, no action) → UNKNOWN\n"
            "Reply with exactly one word — ADD, VIEW, COMPLETE, DELETE, UPDATE, EXIT, or UNKNOWN."
        )
        intent = self._llm(prompt).strip().upper()
        valid = {"ADD", "VIEW", "COMPLETE", "DELETE", "UPDATE", "EXIT", "UNKNOWN"}
        return intent if intent in valid else "UNKNOWN"

    # ── Full intent classifier (extracts task_title, etc.) ───────────

    def _classify(self, user_input: str, tasks_context: str) -> dict:
        """Returns dict with: intent, task_title, task_index, new_title."""
        prompt = (
            f"Current tasks: {tasks_context}\n"
            f'User said: "{user_input}"\n'
            "Classify the intent. Return ONLY valid JSON with no markdown fences:\n"
            '{"intent": "add|view|complete|delete|update|exit|unknown", '
            '"task_title": "actual task name or null", '
            '"task_index": null_or_integer_1_based, '
            '"new_title": "new name if renaming or null"}\n'
            "IMPORTANT: Generic words like 'event', 'task', 'todo', 'item', 'entry', 'list' are NOT task titles. "
            "Only set task_title if the user provides a specific, meaningful name for the task. "
            "If the user ONLY says a generic trigger word like 'todo' or 'tasks' with no action verb, "
            "classify as intent=unknown (it's just a capability trigger, not an actionable command). "
            'E.g. "todo" → intent=unknown. "what\'ve I got" → intent=view. '
            '"I wanna add something" → intent=add, task_title=null. '
            '"put birthday on my list" → intent=add, task_title="birthday". '
            '"throw grocery shopping on there" → intent=add, task_title="grocery shopping".'
        )
        return self._llm_json(prompt, {
            "intent": "unknown", "task_title": None,
            "task_index": None, "new_title": None
        })

    # ── Task selection (LLM-powered, single or multi) ────────────────

    def _classify_selection(self, user_input: str, tasks: list) -> dict:
        """LLM classifies task selection. Returns {"type": "specific|skip", "matched": [tasks]}"""
        if not tasks or not user_input.strip():
            return {"type": "skip", "task_indices": [], "matched": []}

        tasks_list = self._tasks_context(tasks)
        prompt = (
            f"Current tasks: {tasks_list}\n"
            f'User said: "{user_input}"\n'
            "The user is selecting tasks. Ignore action words like 'complete', 'mark', 'done', "
            "'finish', 'delete', 'remove', 'rename', 'update'. "
            "Focus on the task name(s) they are referring to.\n"
            "Return ONLY valid JSON with no markdown:\n"
            '{"type": "specific|skip", "task_indices": [1_based_integers]}\n'
            "RULES:\n"
            '- "specific": user named one or more tasks by name, number, or description. '
            "Fill task_indices with ALL matched tasks — one index per task name mentioned. "
            "IMPORTANT: When the user mentions multiple tasks (e.g. 'birthday and holiday'), "
            "you MUST return an index for EACH one. Do not skip any.\n"
            "  - Exact match takes priority over partial.\n"
            "  - Partial matches are allowed: 'birth' matches 'birthday', 'grocery' matches 'grocery shopping'.\n"
            "  - If ambiguous, pick the exact match.\n"
            '- "skip": user wants to cancel/skip (e.g. "skip", "cancel", "never mind", "forget it", '
            '"nah", "I\'m good", "that\'s all", "no", "nothing").\n'
            "  - Also skip if input is just a generic phrase with no task name "
            '(e.g. "todo", "tasks", "complete task", "delete task").\n'
            "task_indices should be empty for skip type."
        )
        result = self._llm_json(prompt, {"type": "skip", "task_indices": []})
        indices = result.get("task_indices", [])
        result["matched"] = [tasks[i - 1] for i in indices if 1 <= i <= len(tasks)]
        return result

    def _match_task(self, user_input: str, tasks: list):
        """LLM matches user input to a single task. Exact match priority."""
        if not tasks or not user_input.strip():
            return None
        tasks_list = self._tasks_context(tasks)
        prompt = (
            f"Current tasks: {tasks_list}\n"
            f'User said: "{user_input}"\n'
            "Which task is the user referring to? Return ONLY valid JSON:\n"
            '{"task_index": 1_based_integer_or_null}\n'
            "STRICT: Exact match takes priority. "
            'If tasks are "eid holidays" and "holiday" and user says "holiday", pick "holiday".\n'
            "Return null if no reasonable match."
        )
        result = self._llm_json(prompt, {"task_index": None})
        idx = result.get("task_index")
        if idx and 1 <= idx <= len(tasks):
            return tasks[idx - 1]
        return None

    # ── Field parsing (LLM-powered) ──────────────────────────────────

    def _parse_field(self, field: str, user_input: str) -> str | None:
        """LLM extracts a field value or detects skip. Returns value or None."""
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = (
            f"Today is {today}.\n"
            f'The user was asked for "{field}" of a task and said: "{user_input}"\n'
            "Return ONLY valid JSON with no markdown:\n"
            f'{{"value": "extracted {field} or null", "skipped": true_or_false}}\n'
            "If the user declined, said no, skip, nothing, none, not needed, "
            "nah, I'm good, forget it, doesn't matter, etc. → skipped=true, value=null.\n"
        )
        if field == "due date":
            prompt += 'If not skipped, value must be RFC 3339 format: "YYYY-MM-DDT00:00:00.000Z".\n'
        if field == "repeat":
            prompt += 'If not skipped, value should be a short pattern like "daily", "weekly", "every Monday", etc.\n'
        result = self._llm_json(prompt, {"value": None, "skipped": True})
        if result.get("skipped"):
            return None
        return result.get("value")

    def _parse_quick_task(self, text: str) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = (
            f"Today is {today}. Parse this task voice input: \"{text}\"\n"
            "Return ONLY valid JSON with no markdown:\n"
            '{"title": "task name or null", "notes": "details or null", '
            '"due": "YYYY-MM-DDT00:00:00.000Z or null", "repeat": "repeat pattern or null"}'
        )
        return self._llm_json(prompt, {"title": text, "notes": None, "due": None, "repeat": None})

    def _classify_add_mode(self, user_input: str) -> str:
        """LLM classifies add mode response. Returns QUICK, STEP, or TASK_NAME."""
        prompt = (
            f'The user was asked "Quick or step by step?" to add a task, and said: "{user_input}"\n'
            "Classify their response. Reply with exactly one word:\n"
            "- QUICK: user wants quick mode (e.g. 'quick', 'fast', 'simple', 'just quick', 'just throw it on')\n"
            "- STEP: user wants step-by-step mode (e.g. 'step by step', 'detailed', 'guided', 'walk me through it')\n"
            "- TASK_NAME: user gave a task name/details instead of choosing a mode "
            "(e.g. 'birthday party', 'buy groceries tomorrow', 'meeting at 3pm')\n"
            "Reply with exactly one word — QUICK, STEP, or TASK_NAME."
        )
        result = self._llm(prompt).strip().upper()
        valid = {"QUICK", "STEP", "TASK_NAME"}
        return result if result in valid else "TASK_NAME"

    # ── List picker ───────────────────────────────────────────────────

    def _classify_list_selection(self, user_input: str, tasklists: list) -> str | None:
        """LLM matches user input to a task list. Returns tasklist id or None."""
        lists_str = "; ".join(
            f"{i + 1}. {tl.get('title', '?')}" for i, tl in enumerate(tasklists)
        )
        prompt = (
            f"Available task lists: {lists_str}\n"
            f'User said: "{user_input}"\n'
            "Which list is the user referring to? Return ONLY valid JSON:\n"
            '{"list_index": 1_based_integer_or_null}\n'
            "Match by name, number, or partial match. Return null if no match."
        )
        result = self._llm_json(prompt, {"list_index": None})
        idx = result.get("list_index")
        if idx and 1 <= idx <= len(tasklists):
            return tasklists[idx - 1]["id"]
        return None

    async def _pick_tasklist(self, service) -> str:
        """Ask user which list to add to if multiple exist. Returns tasklist id."""
        try:
            tasklists = await asyncio.to_thread(_get_all_tasklists, service)
        except Exception:
            return "@default"

        if len(tasklists) <= 1:
            return "@default"

        list_names = ", ".join(tl.get("title", "?") for tl in tasklists)
        resp = await self._ask(f"Which list? You have {list_names}.")
        selected = self._classify_list_selection(resp, tasklists)
        if selected:
            return selected

        # Couldn't match — default
        await self._speak("I'll add it to your default list.")
        return "@default"

    # ── FLOW: Add ────────────────────────────────────────────────────

    async def _do_add(self, service, title: str, notes: str = None, due: str = None, tasklist_id: str = "@default"):
        try:
            await asyncio.to_thread(_add_task, service, title, notes, due, tasklist_id)
            msg = f"Added {title}."
            if due:
                msg += f" Due {_spoken_date(due)}."
            await self._speak(msg)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Add task failed: {e}")
            await self._speak("Couldn't add that. Try again?")

    async def _flow_add_quick(self, service, tasklist_id: str = "@default"):
        resp = await self._ask("What should I call it?")
        parsed = self._parse_quick_task(resp)
        title = parsed.get("title")
        if not title:
            await self._speak("Didn't catch that. Try again.")
            return
        notes_parts = []
        if parsed.get("notes"):
            notes_parts.append(parsed["notes"])
        if parsed.get("repeat"):
            notes_parts.append(f"Repeats: {parsed['repeat']}")
        notes = "\n".join(notes_parts) or None
        await self._do_add(service, title, notes, parsed.get("due"), tasklist_id)

    async def _flow_add_stepbystep(self, service, tasklist_id: str = "@default"):
        title_resp = await self._ask("What's the title?")
        title = self._parse_field("title", title_resp) or title_resp

        detail_resp = await self._ask("Any details?")
        notes_parts = []
        detail = self._parse_field("details", detail_resp)
        if detail:
            notes_parts.append(detail)

        time_resp = await self._ask("When is it due?")
        due = self._parse_field("due date", time_resp)

        repeat_resp = await self._ask("Should it repeat?")
        repeat = self._parse_field("repeat", repeat_resp)
        if repeat:
            notes_parts.append(f"Repeats: {repeat}")

        notes = "\n".join(notes_parts) or None
        await self._do_add(service, title, notes, due, tasklist_id)

    async def _flow_add(self, service, intent_data: dict):
        tasklist_id = await self._pick_tasklist(service)

        title = intent_data.get("task_title")

        if title:
            await self._do_add(service, title, tasklist_id=tasklist_id)
            return

        # No title — ask which mode
        mode = await self._ask("Quick or step by step?")
        mode_type = self._classify_add_mode(mode)

        if mode_type == "STEP":
            await self._flow_add_stepbystep(service, tasklist_id)
        elif mode_type == "QUICK":
            await self._flow_add_quick(service, tasklist_id)
        else:
            # User gave a task name directly
            parsed = self._parse_quick_task(mode)
            task_title = parsed.get("title")
            if task_title:
                notes_parts = []
                if parsed.get("notes"):
                    notes_parts.append(parsed["notes"])
                if parsed.get("repeat"):
                    notes_parts.append(f"Repeats: {parsed['repeat']}")
                notes = "\n".join(notes_parts) or None
                await self._do_add(service, task_title, notes, parsed.get("due"), tasklist_id)
            else:
                await self._flow_add_quick(service, tasklist_id)

    # ── FLOW: View ───────────────────────────────────────────────────

    async def _flow_view(self, service):
        try:
            tasks = await asyncio.to_thread(_get_tasks, service)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Get tasks failed: {e}")
            await self._speak("Couldn't get your list right now.")
            return
        await self._speak(self._tasks_summary(tasks))
        if not tasks:
            return

        # Detail drill-down loop
        prompt = "Want details on any task?"
        while True:
            resp = await self._ask(prompt)
            selection = self._parse_field("task selection", resp)
            if not selection:
                break
            task = self._match_task(resp, tasks)
            if task:
                await self._speak(self._task_detail(task))
            else:
                await self._speak("Couldn't find that one.")
            prompt = "Any other task?"

    # ── FLOW: Complete ───────────────────────────────────────────────

    async def _flow_complete(self, service, intent_data: dict):
        try:
            tasks = await asyncio.to_thread(_get_tasks, service)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Get tasks failed: {e}")
            await self._speak("Couldn't get your tasks.")
            return
        if not tasks:
            await self._speak("You don't have any tasks yet.")
            return

        raw_input = intent_data.get("_raw") or ""
        explicitly_named = False
        matched = []

        # Try matching from the initial command
        sel = self._classify_selection(raw_input, tasks)
        if sel["type"] == "specific" and sel["matched"]:
            matched = sel["matched"]
            explicitly_named = True

        # If no match — ask with retry loop
        if not matched:
            await self._speak(self._tasks_numbered(tasks))
            prompt = "Which one should I mark done?"
            while True:
                resp = await self._ask(prompt)
                sel = self._classify_selection(resp, tasks)
                if sel["type"] == "skip":
                    break
                elif sel["type"] == "specific" and sel["matched"]:
                    matched = sel["matched"]
                    break
                else:
                    prompt = "Couldn't find that one. Try again or never mind."

        if not matched:
            await self._speak("No changes made.")
            return

        # Single task — confirm only if picked from list
        if len(matched) == 1:
            task = matched[0]
            if not explicitly_named:
                confirmed = await self.capability_worker.run_confirmation_loop(
                    f"Mark {task.get('title')} as done?"
                )
                if not confirmed:
                    await self._speak(f"Kept {task.get('title')}.")
                    return
            try:
                await asyncio.to_thread(_complete_task, service, task["id"], task.get("_tasklist_id", "@default"))
                await self._speak(f"Done! {task.get('title')} is off your list.")
            except Exception as e:
                self.worker.editor_logging_handler.error(f"Complete task failed: {e}")
                await self._speak("Something went wrong. Try again?")
            return

        # Multiple tasks — confirm the batch (cap names at 3 for voice)
        task_names = [t.get("title", "?") for t in matched]
        if len(task_names) <= 3:
            names_str = ", ".join(task_names)
        else:
            names_str = ", ".join(task_names[:3]) + f", and {len(task_names) - 3} more"
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Mark {len(matched)} tasks as done: {names_str}?"
        )
        if not confirmed:
            await self._speak("No changes made.")
            return

        done_count = 0
        for task in matched:
            try:
                await asyncio.to_thread(_complete_task, service, task["id"], task.get("_tasklist_id", "@default"))
                done_count += 1
            except Exception as e:
                self.worker.editor_logging_handler.error(f"Complete task failed: {e}")
                await self._speak(f"Couldn't complete {task.get('title')}.")
        await self._speak(f"Done! Completed {done_count} of {len(matched)} tasks.")

    # ── FLOW: Delete (single only, no confirmation) ──────────────────

    async def _flow_delete(self, service, intent_data: dict):
        try:
            tasks = await asyncio.to_thread(_get_tasks, service)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Get tasks failed: {e}")
            await self._speak("Couldn't get your tasks.")
            return
        if not tasks:
            await self._speak("Nothing to delete.")
            return

        raw_input = intent_data.get("_raw") or ""
        task = None

        # Try matching from initial command
        sel = self._classify_selection(raw_input, tasks)
        if sel["type"] == "specific" and sel["matched"]:
            task = sel["matched"][0]

        # If no match — ask with retry loop
        if not task:
            await self._speak(self._tasks_numbered(tasks))
            prompt = "Which one should I delete?"
            while True:
                resp = await self._ask(prompt)
                sel = self._classify_selection(resp, tasks)
                if sel["type"] == "skip":
                    break
                elif sel["type"] == "specific" and sel["matched"]:
                    task = sel["matched"][0]
                    break
                else:
                    prompt = "Couldn't find that one. Try again or never mind."

        if not task:
            await self._speak("No changes made.")
            return

        try:
            await asyncio.to_thread(_delete_task, service, task["id"], task.get("_tasklist_id", "@default"))
            await self._speak(f"Deleted {task.get('title')}.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Delete task failed: {e}")
            await self._speak("Something went wrong. Try again?")

    # ── FLOW: Update (no confirmation) ───────────────────────────────

    async def _flow_update(self, service, intent_data: dict):
        try:
            tasks = await asyncio.to_thread(_get_tasks, service)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Get tasks failed: {e}")
            await self._speak("Couldn't get your tasks.")
            return
        if not tasks:
            await self._speak("Nothing to update.")
            return

        raw_input = intent_data.get("_raw") or ""
        task = None

        # Try matching from initial command
        sel = self._classify_selection(raw_input, tasks)
        if sel["type"] == "specific" and sel["matched"]:
            task = sel["matched"][0]

        # If no match — ask with retry loop
        if not task:
            await self._speak(self._tasks_numbered(tasks))
            prompt = "Which one should I rename?"
            while True:
                resp = await self._ask(prompt)
                sel = self._classify_selection(resp, tasks)
                if sel["type"] == "skip":
                    break
                elif sel["type"] == "specific" and sel["matched"]:
                    task = sel["matched"][0]
                    break
                else:
                    prompt = "Couldn't find that one. Try again or never mind."

        if not task:
            await self._speak("No changes made.")
            return

        new_title = intent_data.get("new_title")
        if not new_title:
            new_title = await self._ask(f"What should I rename {task.get('title')} to?")

        try:
            await asyncio.to_thread(_update_task, service, task["id"], new_title, task.get("_tasklist_id", "@default"))
            await self._speak(f"Renamed to {new_title}.")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Update task failed: {e}")
            await self._speak("Couldn't update that. Try again?")

    # ── Main entry ───────────────────────────────────────────────────

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        first_msg = await self.capability_worker.wait_for_complete_transcription()
        self.worker.editor_logging_handler.info(f"[TODO] First transcription: {first_msg!r}")

        # Google auth check
        token = self.capability_worker.get_token("google")
        if not token:
            await self._speak(
                "Your Google account isn't linked yet. "
                "Head to Openhome Settings, then Linked Accounts to connect it"
            )
            self.capability_worker.resume_normal_flow()
            return

        # Build the Tasks service
        try:
            service = _build_tasks_service(token)
            self.worker.editor_logging_handler.info("Google Tasks service ready.")
        except Exception as e:
            await self._speak("Couldn't connect to Google Tasks. Try again in a moment.")
            self.worker.editor_logging_handler.error(f"Tasks service build error: {e}")
            self.capability_worker.resume_normal_flow()
            return

        # Determine intent (lightweight classifier)
        routing_msg = first_msg
        intent = self._classify_intent(first_msg)
        self.worker.editor_logging_handler.info(f"[TODO] Initial intent={intent} raw={first_msg!r}")

        # If unknown — ask what they want, re-classify once
        if intent == "UNKNOWN":
            await self._speak("What would you like to do with your tasks? Add, View, Complete, Delete, or Update.")
            routing_msg = (await self.capability_worker.user_response()).strip()
            self.worker.editor_logging_handler.info(f"[TODO] Follow-up: {routing_msg!r}")
            intent = self._classify_intent(routing_msg)

            if intent == "UNKNOWN":
                await self._speak(
                    "I didn't catch that. Try something like add a task or show my list."
                )
                self.capability_worker.resume_normal_flow()
                return

        # Build full intent_data for flows that need task_title extraction
        try:
            tasks = await asyncio.to_thread(_get_tasks, service)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Initial get tasks failed: {e}")
            tasks = []

        intent_data = self._classify(routing_msg, self._tasks_context(tasks))
        intent_data["_raw"] = routing_msg

        # Route to flow
        try:
            while True:
                self.worker.editor_logging_handler.info(
                    f"[TODO] Executing intent={intent} raw={intent_data.get('_raw', '')!r}"
                )

                if intent == "ADD":
                    await self._flow_add(service, intent_data)
                elif intent == "VIEW":
                    await self._flow_view(service)
                elif intent == "COMPLETE":
                    await self._flow_complete(service, intent_data)
                elif intent == "DELETE":
                    await self._flow_delete(service, intent_data)
                elif intent == "UPDATE":
                    await self._flow_update(service, intent_data)
                elif intent == "EXIT":
                    await self._speak("All saved. Talk soon!")
                    break
                else:
                    break

                # Listen for follow-up
                follow_up = await self._ask("Anything else?")
                intent = self._classify_intent(follow_up)
                self.worker.editor_logging_handler.info(
                    f"[TODO] Follow-up intent={intent} raw={follow_up!r}"
                )

                if intent == "UNKNOWN" or intent == "EXIT":
                    if intent == "EXIT":
                        await self._speak("All saved. Talk soon!")
                    break

                # Re-classify for task_title extraction
                try:
                    tasks = await asyncio.to_thread(_get_tasks, service)
                except Exception:
                    tasks = []
                intent_data = self._classify(follow_up, self._tasks_context(tasks))
                intent_data["_raw"] = follow_up

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Tasks unhandled error: {e}")
            await self._speak("Something went wrong. Try again.")
        finally:
            self.capability_worker.resume_normal_flow()
