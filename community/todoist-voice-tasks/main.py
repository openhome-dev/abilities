"""
Todoist Voice Task Manager — Voice CRUD for Todoist via REST API v1.
Add, update, complete, reopen, delete tasks; list overdue/today. LLM classifies intent.
"""
import json
import re
from datetime import datetime, timezone

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# -----------------------------------------------------------------------------
# Todoist API key: get a free token at https://app.todoist.com/prefs/integrations
# Use a real key to build and test. Before submitting a PR, use placeholder only:
#   API_KEY = "REPLACE_WITH_YOUR_KEY"
# -----------------------------------------------------------------------------
API_KEY = "REPLACE_WITH_YOUR_KEY"

# URLs must match test_todoist_local.py exactly (same base + paths: /tasks, /tasks/{id}, /tasks/{id}/close, /tasks/{id}/reopen)
TODOIST_BASE = "https://api.todoist.com/api/v1"


class TodoistVoiceTasksCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def _headers(self):
        return {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _strip_markdown_links(text: str) -> str:
        """Replace [label](url) with label for clean display."""
        if not text:
            return text
        return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)

    def _get_tasks(self):
        """Fetch tasks via GET api/v1/tasks. Returns normalized list or None."""
        if not API_KEY or API_KEY == "REPLACE_WITH_YOUR_KEY":
            return None
        try:
            r = requests.get(
                f"{TODOIST_BASE}/tasks",
                headers=self._headers(),
                timeout=10,
            )
            if r.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[Todoist] GET tasks {r.status_code}: {r.text[:200]}"
                )
                return None
            data = r.json()
            raw = data.get("results", data if isinstance(data, list) else [])
            if not isinstance(raw, list):
                raw = []
            out = []
            for t in raw:
                if not isinstance(t, dict):
                    continue
                content = t.get("content", "")
                out.append({
                    "id": t.get("id"),
                    "content": self._strip_markdown_links(content),
                    "due": t.get("due"),
                    "is_completed": t.get("checked", t.get("is_completed", False)),
                })
            return out
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Todoist] GET tasks error: {e}")
            return None

    def _add_task(self, content: str, due_string: str | None = None) -> bool:
        """Create a task. Returns True on success."""
        if not content.strip():
            return False
        if not API_KEY or API_KEY == "REPLACE_WITH_YOUR_KEY":
            return False
        body = {"content": content.strip()}
        if due_string and due_string.strip():
            body["due_string"] = due_string.strip()
        try:
            r = requests.post(
                f"{TODOIST_BASE}/tasks",
                headers=self._headers(),
                json=body,
                timeout=10,
            )
            if r.status_code not in (200, 201):
                self.worker.editor_logging_handler.error(
                    f"[Todoist] POST task {r.status_code}: {r.text[:200]}"
                )
                return False
            return True
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Todoist] POST task error: {e}")
            return False

    def _close_task(self, task_id: str) -> bool:
        """Mark task complete. Returns True on success."""
        if not API_KEY or API_KEY == "REPLACE_WITH_YOUR_KEY":
            return False
        try:
            r = requests.post(
                f"{TODOIST_BASE}/tasks/{task_id}/close",
                headers=self._headers(),
                timeout=10,
            )
            if r.status_code not in (200, 204):
                self.worker.editor_logging_handler.error(
                    f"[Todoist] POST close {r.status_code}: {r.text[:200]}"
                )
                return False
            return True
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Todoist] POST close error: {e}")
            return False

    def _update_task(
        self,
        task_id: str,
        content: str | None = None,
        due_string: str | None = None,
    ) -> bool:
        """Update task content and/or due date."""
        if not API_KEY or API_KEY == "REPLACE_WITH_YOUR_KEY":
            return False
        body = {}
        if content is not None and content.strip():
            body["content"] = content.strip()
        if due_string is not None and due_string.strip():
            body["due_string"] = due_string.strip()
        if not body:
            return True
        try:
            r = requests.post(
                f"{TODOIST_BASE}/tasks/{task_id}",
                headers=self._headers(),
                json=body,
                timeout=10,
            )
            if r.status_code not in (200, 204):
                self.worker.editor_logging_handler.error(
                    f"[Todoist] POST update {r.status_code}: {r.text[:200]}"
                )
                return False
            return True
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Todoist] POST update error: {e}")
            return False

    def _reopen_task(self, task_id: str) -> bool:
        """Reopen (uncomplete) a completed task."""
        if not API_KEY or API_KEY == "REPLACE_WITH_YOUR_KEY":
            return False
        try:
            r = requests.post(
                f"{TODOIST_BASE}/tasks/{task_id}/reopen",
                headers=self._headers(),
                timeout=10,
            )
            if r.status_code not in (200, 204):
                self.worker.editor_logging_handler.error(
                    f"[Todoist] POST reopen {r.status_code}: {r.text[:200]}"
                )
                return False
            return True
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Todoist] POST reopen error: {e}")
            return False

    def _delete_task(self, task_id: str) -> bool:
        """Delete a task permanently."""
        if not API_KEY or API_KEY == "REPLACE_WITH_YOUR_KEY":
            return False
        try:
            r = requests.delete(
                f"{TODOIST_BASE}/tasks/{task_id}",
                headers=self._headers(),
                timeout=10,
            )
            if r.status_code not in (200, 204):
                self.worker.editor_logging_handler.error(
                    f"[Todoist] DELETE task {r.status_code}: {r.text[:200]}"
                )
                return False
            return True
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Todoist] DELETE task error: {e}")
            return False

    @staticmethod
    def _parse_due_from_content(text: str) -> tuple[str, str | None]:
        """Extract optional due_string from phrase. Fallback when LLM doesn't return 'due'. Todoist accepts natural language (see their Help)."""
        text = text.strip()
        lower = text.lower()
        due = None
        # Order: longer/more specific first (e.g. "tomorrow at 9am" before "tomorrow")
        for pattern in [
            r"tomorrow at \d{1,2}(?::\d{2})?\s*(?:am|pm)?",
            r"tomorrow morning|tom afternoon|tom evening|tom night",
            r"today at \d{1,2}(?::\d{2})?\s*(?:am|pm)?",
            r"next (?:mon|tue|wed|thur|fri|sat|sun)day",
            r"next (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
            r"next week",
            r"next month",
            r"in \d+\s*(?:days?|weeks?|months?)",
            r"tomorrow",
            r"today",
            r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+\d{4})?",
            r"\d{1,2}/\d{1,2}(?:/\d{2,4})?",
            r"\d{4}-\d{2}-\d{2}",
            r"end of (?:month|week)",
            r"this weekend",
            r"next weekend",
        ]:
            m = re.search(pattern, lower, re.IGNORECASE)
            if m:
                due = text[m.start() : m.end()].strip()
                content = (text[: m.start()] + text[m.end() :]).strip()
                content = re.sub(r"\s+", " ", content).strip()
                if content:
                    return content, due
                return text, due
        return text, None

    def _llm_intent(self, user_input: str) -> dict:
        """Use LLM to classify intent and extract content/task_ref. Returns dict with intent, content (optional), task_ref (optional)."""
        if not user_input or not user_input.strip():
            return {"intent": "unknown", "content": "", "task_ref": "", "due": ""}
        prompt = """You are a Todoist voice assistant. The user said: "{user_input}"

Decide what they want. Reply with ONLY a JSON object, no other text. Use this exact format:
{{"intent": "<one of: add, delete, update, complete, reopen, list, overdue, today, completed, exit, unknown>", "content": "<task title only for add; new text for update; empty otherwise>", "task_ref": "<first or last or phrase to match task; empty for add/overdue/today/list/completed/exit>", "due": "<date phrase if user said when (e.g. tomorrow, next week, March 15, today at 5pm); empty otherwise>"}}

Rules:
- add: user wants to create a task. Put ONLY the task title in "content" (no date). If they said when it's due (today, tomorrow, next week, next Friday, March 15, jan 27, in 5 days), put that phrase in "due".
- delete: user wants to remove a task. Use task_ref "first" or "last" or a word/phrase that identifies the task (e.g. "milk", "call mom").
- update: user wants to change a task. Put the new task text in "content" (no date), use task_ref to identify which task. If they said a new due date, put it in "due".
- complete: user wants to mark a task done. task_ref "first" or "last" or phrase to match.
- reopen: user wants to uncomplete or reopen a completed task. Phrases include "uncomplete", "reopen", "undo complete", "mark incomplete", "bring back", "uncomplete this". task_ref "first" or "last" or phrase to match (among completed).
- list: user wants to hear ALL their active tasks (e.g. "list my tasks", "list all", "show my tasks", "what are my tasks"). Leave content and task_ref empty.
- overdue: user wants to hear only overdue tasks. Leave content and task_ref empty.
- today: user wants to hear only today's tasks. Leave content and task_ref empty.
- exit: user wants to stop (stop, exit, done, bye, etc.). Leave content and task_ref empty.
- unknown: you cannot tell. Leave content, task_ref, and due empty.""".format(
            user_input=user_input.replace('"', '\\"')
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt).strip()
            # Strip markdown code block if present
            if raw.startswith("```"):
                raw = re.sub(r"^```\w*\n?", "", raw)
            if raw.endswith("```"):
                raw = re.sub(r"\n?```\s*$", "", raw)
            raw = raw.strip()
            data = json.loads(raw)
            intent = (data.get("intent") or "unknown").strip().lower()
            if intent not in ("add", "delete", "update", "complete", "reopen", "list", "overdue", "today", "completed", "exit", "unknown"):
                intent = "unknown"
            return {
                "intent": intent,
                "content": (data.get("content") or "").strip(),
                "task_ref": (data.get("task_ref") or "").strip().lower(),
                "due": (data.get("due") or "").strip(),
            }
        except (json.JSONDecodeError, TypeError) as e:
            self.worker.editor_logging_handler.error(f"[Todoist] LLM intent parse error: {e}")
            return {"intent": "unknown", "content": "", "task_ref": "", "due": ""}

    def _resolve_task(
        self,
        tasks: list,
        task_ref: str,
        active_only: bool = True,
    ) -> dict | None:
        """Resolve task_ref (first, last, or phrase) to a task dict. active_only=True = incomplete, False = completed."""
        if not tasks:
            return None
        if active_only:
            filtered = [t for t in tasks if not t.get("is_completed")]
        else:
            filtered = [t for t in tasks if t.get("is_completed")]
        if not filtered:
            return None
        if not task_ref or task_ref == "first":
            return filtered[0]
        if task_ref == "last":
            return filtered[-1]
        ref_lower = task_ref.lower()
        for t in filtered:
            if ref_lower in (t.get("content") or "").lower():
                return t
        return filtered[0]

    def _filter_overdue(self, tasks: list) -> list:
        """Filter tasks where due date is in the past."""
        now = datetime.now(timezone.utc)
        out = []
        for t in tasks:
            due = t.get("due")
            if not due:
                continue
            date_str = due.get("date") if isinstance(due, dict) else str(due)
            if not date_str:
                continue
            try:
                # API can return "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SSZ"
                if "T" in date_str:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(date_str + "T00:00:00+00:00")
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < now and not t.get("is_completed"):
                    out.append(t)
            except (ValueError, TypeError):
                continue
        return out

    def _filter_today(self, tasks: list) -> list:
        """Filter tasks due today (local date)."""
        today = datetime.now().date()
        out = []
        for t in tasks:
            due = t.get("due")
            if not due:
                continue
            date_str = due.get("date") if isinstance(due, dict) else str(due)
            if not date_str:
                continue
            try:
                if "T" in date_str:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(date_str + "T00:00:00")
                d = dt.date() if hasattr(dt, "date") else dt
                if d == today and not t.get("is_completed"):
                    out.append(t)
            except (ValueError, TypeError):
                continue
        return out

    async def run(self):
        try:
            await self.capability_worker.speak(
                "Todoist here. You can add, update, complete, uncomplete, reopen, or delete tasks, or list all, overdue, or today. Say stop when done."
            )
            while True:
                user_input = await self.capability_worker.user_response()
                if not user_input or not user_input.strip():
                    continue
                parsed = self._llm_intent(user_input)
                intent = parsed.get("intent", "unknown")
                content = parsed.get("content", "")
                task_ref = parsed.get("task_ref", "")
                due_from_llm = parsed.get("due", "").strip()

                if intent == "exit":
                    await self.capability_worker.speak("Goodbye!")
                    break

                if intent == "add":
                    if not content:
                        await self.capability_worker.speak("What task should I add? Say something like: add buy milk.")
                        continue
                    due_string = due_from_llm or None
                    if not due_string:
                        content_clean, due_string = self._parse_due_from_content(content)
                        if not content_clean:
                            content_clean = content
                    else:
                        content_clean = content.strip()
                    ok = self._add_task(content_clean, due_string)
                    if ok:
                        msg = f"Added task: {content_clean}."
                        if due_string:
                            msg += f" Due {due_string}."
                        await self.capability_worker.speak(msg)
                    else:
                        await self.capability_worker.speak(
                            "Couldn't add the task. Check your API token in the ability setup and try again."
                        )
                    continue

                if intent == "delete":
                    tasks = self._get_tasks()
                    if tasks is None:
                        await self.capability_worker.speak(
                            "Couldn't reach Todoist. Check your API token and try again."
                        )
                        continue
                    task = self._resolve_task(tasks, task_ref or "first", active_only=True)
                    if not task:
                        await self.capability_worker.speak("No task to delete.")
                        continue
                    task_id = str(task.get("id"))
                    name = (task.get("content") or "Task")[:40]
                    if self._delete_task(task_id):
                        await self.capability_worker.speak(f"Deleted: {name}.")
                    else:
                        await self.capability_worker.speak("Couldn't delete that task. Try again.")
                    continue

                if intent == "update":
                    tasks = self._get_tasks()
                    if tasks is None:
                        await self.capability_worker.speak(
                            "Couldn't reach Todoist. Check your API token and try again."
                        )
                        continue
                    task = self._resolve_task(tasks, task_ref or "first", active_only=True)
                    if not task:
                        await self.capability_worker.speak("No task to update.")
                        continue
                    task_id = str(task.get("id"))
                    if not content and not due_from_llm:
                        await self.capability_worker.speak("What should the task say? Say the new text.")
                        continue
                    due_string = due_from_llm or None
                    if not due_string:
                        content_clean, due_string = self._parse_due_from_content(content)
                        if not content_clean:
                            content_clean = content
                    else:
                        content_clean = content.strip() if content else None
                    if self._update_task(task_id, content=content_clean, due_string=due_string):
                        if content_clean:
                            await self.capability_worker.speak(f"Updated to: {content_clean}.")
                        elif due_string:
                            await self.capability_worker.speak(f"Due set to {due_string}.")
                        else:
                            await self.capability_worker.speak("Updated.")
                    else:
                        await self.capability_worker.speak("Couldn't update that task. Try again.")
                    continue

                if intent == "complete":
                    tasks = self._get_tasks()
                    if tasks is None:
                        await self.capability_worker.speak(
                            "Couldn't reach Todoist. Check your API token and try again."
                        )
                        continue
                    task = self._resolve_task(tasks, task_ref or "first", active_only=True)
                    if not task:
                        await self.capability_worker.speak("No active tasks to complete.")
                        continue
                    task_id = str(task.get("id"))
                    name = (task.get("content") or "Task")[:40]
                    if self._close_task(task_id):
                        await self.capability_worker.speak(f"Marked complete: {name}.")
                    else:
                        await self.capability_worker.speak("Couldn't mark that task complete. Try again.")
                    continue

                if intent == "reopen":
                    tasks = self._get_tasks()
                    if tasks is None:
                        await self.capability_worker.speak(
                            "Couldn't reach Todoist. Check your API token and try again."
                        )
                        continue
                    task = self._resolve_task(tasks, task_ref or "first", active_only=False)
                    if not task:
                        await self.capability_worker.speak("No completed task to reopen.")
                        continue
                    task_id = str(task.get("id"))
                    name = (task.get("content") or "Task")[:40]
                    if self._reopen_task(task_id):
                        await self.capability_worker.speak(f"Reopened: {name}.")
                    else:
                        await self.capability_worker.speak("Couldn't reopen that task. Try again.")
                    continue

                if intent == "list":
                    tasks = self._get_tasks()
                    if tasks is None:
                        await self.capability_worker.speak(
                            "Couldn't reach Todoist. Check your API token and try again."
                        )
                        continue
                    active = [t for t in tasks if not t.get("is_completed")]
                    if not active:
                        await self.capability_worker.speak("You have no active tasks.")
                    else:
                        names = [t.get("content", "Unnamed")[:40] for t in active[:10]]
                        if len(active) > 10:
                            names.append(f"and {len(active) - 10} more")
                        await self.capability_worker.speak(
                            f"You have {len(active)} task(s): " + ", ".join(names) + "."
                        )
                    continue

                if intent == "overdue":
                    tasks = self._get_tasks()
                    if tasks is None:
                        await self.capability_worker.speak(
                            "Couldn't reach Todoist. Check your API token and try again."
                        )
                        continue
                    overdue = self._filter_overdue(tasks)
                    if not overdue:
                        await self.capability_worker.speak("You have no overdue tasks.")
                    else:
                        names = [t.get("content", "Unnamed")[:40] for t in overdue[:7]]
                        if len(overdue) > 7:
                            names.append(f"and {len(overdue) - 7} more")
                        await self.capability_worker.speak(
                            f"You have {len(overdue)} overdue: " + ", ".join(names) + "."
                        )
                    continue

                if intent == "today":
                    tasks = self._get_tasks()
                    if tasks is None:
                        await self.capability_worker.speak(
                            "Couldn't reach Todoist. Check your API token and try again."
                        )
                        continue
                    today_list = self._filter_today(tasks)
                    if not today_list:
                        await self.capability_worker.speak("Nothing due today.")
                    else:
                        names = [t.get("content", "Unnamed")[:40] for t in today_list[:7]]
                        if len(today_list) > 7:
                            names.append(f"and {len(today_list) - 7} more")
                        await self.capability_worker.speak(
                            f"You have {len(today_list)} due today: " + ", ".join(names) + "."
                        )
                    continue

                # unknown
                await self.capability_worker.speak(
                    "You can add, update, complete, uncomplete (reopen), or delete a task, or list all tasks, overdue, or today. Say stop to exit."
                )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Todoist] run error: {e}")
            await self.capability_worker.speak("Something went wrong. Exiting Todoist.")
        finally:
            self.capability_worker.resume_normal_flow()
