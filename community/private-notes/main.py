import json
from datetime import datetime
from uuid import uuid4

from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

NOTES_FILE = "private_notes.json"
MAX_READBACK = 3
MAX_TURNS = 4


# LLM picks one tool per turn; loop ends when it calls "finish".
SYSTEM_PROMPT = """
You are an OpenHome private notes ability.

Return ONLY valid JSON with exactly this shape:
{
  "name": "write_note|read_notes|search_notes|delete_notes|ask_followup|finish",
  "arguments": {}
}

Available tools:

1) write_note — create or overwrite a note
{"name": "write_note", "arguments": {"note_id": null, "title": "string", "content": "string"}}
note_id=null creates a new note (no confirmation needed).
note_id=<uuid> overwrites. Python will ask the confirmation question.

2) read_notes — read notes by id
{"name": "read_notes", "arguments": {"note_ids": ["uuid"]}}
note_ids must always be a JSON array, even when reading one note.

3) search_notes — search private notes by title or content
{"name": "search_notes", "arguments": {"query": "string"}}
Use this when the user asks for notes about a topic and the title/index is not enough.

4) delete_notes — delete notes by id
{"name": "delete_notes", "arguments": {"note_ids": ["uuid"]}}
note_ids must always be a JSON array, even when deleting one note.
Python will ask the confirmation question before deleting.

5) ask_followup — ask the user for clarification
{"name": "ask_followup", "arguments": {"question": "string"}}

6) finish — speak a final response to the user
{"name": "finish", "arguments": {"response": "string"}}

Rules:
- The note index is sorted by updated_at descending. Latest note = first id.
- Never invent note ids. Resolve titles to ids from the note index.
- If ambiguous, use ask_followup.
- If there are no notes and the user asks to read, update, or delete notes, finish by saying there are no private notes yet.
- ask_followup is only for missing or ambiguous user intent. Do not use ask_followup to confirm overwrite or delete.
- After a tool result, call finish. Do not use ask_followup after a tool result.
- For delete requests, call delete_notes with the matching ids. Python will ask the yes/no confirmation.
- For overwrite requests, call write_note with the matching id. Python will ask the yes/no confirmation.
- If the user asks to update or overwrite a note but does not provide the new content, use ask_followup to ask what should change.
- For topic or keyword searches, call search_notes with the user's search phrase.
- Create short, useful titles. Prefer noun phrases like "Parking", "Travel Prep", or "Dentist". Do not title notes "my note", "your parking note", "the note", or similar UI phrases.
- Keep content faithful to the user's meaning. Do not add extra tasks or advice.
- After a tool result is shown, call finish with a concise voice-friendly response.
- If a tool result has "ok": false, say that nothing changed and briefly explain why.
- If search_notes returns multiple matches, summarize up to the returned notes and mention if more exist.
- When reading notes aloud, say the title, a natural relative timestamp (e.g. "from today", "yesterday afternoon"), and the content.
- Keep responses short, warm, and conversational. Like talking to a friend.
- Plain spoken English only. No markdown, no bullet points, no numbered lists, no emoji, no URLs, no special formatting.
""".strip()


class PrivateNotesCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        """Entry point. Framework calls this when the ability is triggered."""
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        """
        Main flow:
        1. Get user request (from transcription or by asking)
        2. Load notes from file
        3. Run the tool loop until the LLM calls finish
        """
        self.worker.editor_logging_handler.info("[PrivateNotes] Ability started")
        try:
            request_text = (await self.capability_worker.wait_for_complete_transcription() or "").strip()
            if not request_text:
                await self.capability_worker.speak(
                    "Private notes is open. What would you like to do?"
                )
                request_text = await self._get_user_input(
                    "I didn't catch anything for private notes."
                )
                if not request_text:
                    return

            try:
                notebook = await self._load_notebook()
            except ValueError as exc:
                self.worker.editor_logging_handler.error(f"[PrivateNotes] Notebook load error: {exc}")
                await self.capability_worker.speak(
                    "I couldn't safely read your saved private notes, so I won't change them yet."
                )
                return

            # Capture time once so the context prefix stays identical across turns (LLM caching).
            now = datetime.now(ZoneInfo(self.capability_worker.get_timezone()))

            tool_handlers = {
                "write_note": self._handle_write_note,
                "read_notes": self._handle_read_notes,
                "search_notes": self._handle_search_notes,
                "delete_notes": self._handle_delete_notes,
            }

            history = [{"role": "user", "content": self._build_context(request_text, notebook, now)}]

            for _ in range(MAX_TURNS):
                # text_to_text_response is sync — no await
                llm_response = self.capability_worker.text_to_text_response(
                    history[-1]["content"],
                    history=history[:-1],
                    system_prompt=SYSTEM_PROMPT,
                )
                try:
                    tool_call = self._parse_tool_call(llm_response)
                except (json.JSONDecodeError, TypeError):
                    history.append({"role": "assistant", "content": llm_response})
                    history.append({
                        "role": "user",
                        "content": (
                            "That was not valid tool JSON. Return ONLY valid JSON "
                            "with a supported tool name and arguments."
                        ),
                    })
                    continue
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("arguments", {})
                if not isinstance(tool_args, dict):
                    history.append({"role": "assistant", "content": llm_response})
                    history.append({
                        "role": "user",
                        "content": (
                            "Tool arguments must be a JSON object. Return ONLY valid JSON "
                            "with a supported tool name and an object-valued arguments field."
                        ),
                    })
                    continue
                self.worker.editor_logging_handler.info(f"[PrivateNotes] Tool={tool_name}")

                history.append({"role": "assistant", "content": llm_response})

                if tool_name == "finish":
                    await self.capability_worker.speak(tool_args.get("response", ""))
                    return

                if tool_name == "ask_followup":
                    question = tool_args.get("question", "")
                    await self.capability_worker.speak(question)
                    followup = await self._get_user_input(
                        "I didn't catch anything, so I didn't change your notes."
                    )
                    if not followup:
                        return
                    history.append({"role": "user", "content": followup})
                    continue

                handler = tool_handlers.get(tool_name)
                if not handler:
                    break  # unknown tool — fall through to "couldn't complete" message

                result = await handler(notebook, tool_args, now)

                if result.get("notes_changed"):
                    await self._save_notebook(notebook)

                # Feed result back so the LLM can call finish with a spoken summary
                history.append({"role": "user", "content": json.dumps(result, ensure_ascii=True)})

            await self.capability_worker.speak(
                "I couldn't complete that note request."
            )
        except Exception as exc:
            self.worker.editor_logging_handler.error(f"[PrivateNotes] Unexpected error: {exc}")
            await self.capability_worker.speak(
                "Something went wrong with your private notes."
            )
        finally:
            self.worker.editor_logging_handler.info("[PrivateNotes] Ability ended")
            self.capability_worker.resume_normal_flow()

    # --- Context ---

    def _build_context(self, request_text: str, notebook: dict, now: datetime) -> str:
        """Build the initial user message with time, request, and note index."""
        notes = sorted(
            notebook["notes"], key=lambda n: n.get("updated_at", ""), reverse=True
        )
        note_index = {
            "note_count": len(notes),
            "notes": [
                {"id": n.get("id"), "title": n.get("title"), "updated_at": n.get("updated_at")}
                for n in notes
            ],
        }
        return (
            f"Current local time: {now.isoformat()}\n"
            f"User request: {request_text}\n"
            f"Note index:\n{json.dumps(note_index, ensure_ascii=True)}"
        )

    # --- Tool handlers ---

    async def _handle_write_note(self, notebook: dict, args: dict, now: datetime) -> dict:
        """Create a new note (note_id=null) or overwrite an existing one (with confirmation)."""
        note_id = args.get("note_id")
        title = self._normalize_title(args.get("title"))
        content = str(args.get("content") or "").strip()
        timestamp = now.isoformat()

        if not content:
            return {
                "ok": False,
                "notes_changed": False,
                "error": "missing note content",
            }

        if not title:
            title = "Untitled note"

        if not note_id:
            notebook["notes"].append({
                "id": str(uuid4()),
                "title": title,
                "content": content,
                "created_at": timestamp,
                "updated_at": timestamp,
            })
            return {"ok": True, "notes_changed": True, "status": "created", "title": title}

        existing = next((n for n in notebook["notes"] if n.get("id") == note_id), None)
        if not existing:
            return {"ok": False, "notes_changed": False, "error": "note not found"}

        question = f"Overwrite note titled {existing.get('title') or 'Untitled note'}"
        if not await self.capability_worker.run_confirmation_loop(question):
            return {"ok": True, "notes_changed": False, "status": "cancelled"}

        existing["title"] = title
        existing["content"] = content
        existing["updated_at"] = timestamp
        return {"ok": True, "notes_changed": True, "status": "updated", "title": title}

    async def _handle_read_notes(self, notebook: dict, args: dict, _now: datetime) -> dict:
        """Return matched notes (capped at MAX_READBACK). LLM formats them for speech."""
        note_ids = self._requested_note_ids(args)
        if not note_ids:
            return {
                "ok": False,
                "notes_changed": False,
                "error": "no matching notes found",
                "notes": [],
            }

        matched = sorted(
            [n for n in notebook["notes"] if n.get("id") in note_ids],
            key=lambda n: n.get("updated_at", ""),
            reverse=True,
        )
        if not matched:
            return {
                "ok": False,
                "notes_changed": False,
                "error": "no matching notes found",
                "notes": [],
            }

        capped = matched[:MAX_READBACK]
        return {
            "ok": True,
            "notes_changed": False,
            "total_matched": len(matched),
            "total_returned": len(capped),
            "total_remaining": max(len(matched) - len(capped), 0),
            "notes": [
                {"title": n.get("title"), "content": n.get("content"), "updated_at": n.get("updated_at")}
                for n in capped
            ],
        }

    async def _handle_search_notes(self, notebook: dict, args: dict, _now: datetime) -> dict:
        """Search notes without exposing every note body in the initial LLM context."""
        query = str(args.get("query") or "").strip().lower()
        if not query:
            return {
                "ok": False,
                "notes_changed": False,
                "error": "missing search query",
                "notes": [],
            }

        matched = sorted(
            [
                n for n in notebook["notes"]
                if query in str(n.get("title") or "").lower()
                or query in str(n.get("content") or "").lower()
            ],
            key=lambda n: n.get("updated_at", ""),
            reverse=True,
        )
        if not matched:
            return {
                "ok": False,
                "notes_changed": False,
                "error": "no matching notes found",
                "notes": [],
            }

        capped = matched[:MAX_READBACK]
        return {
            "ok": True,
            "notes_changed": False,
            "total_matched": len(matched),
            "total_returned": len(capped),
            "total_remaining": max(len(matched) - len(capped), 0),
            "notes": [
                {"title": n.get("title"), "content": n.get("content"), "updated_at": n.get("updated_at")}
                for n in capped
            ],
        }

    async def _handle_delete_notes(self, notebook: dict, args: dict, _now: datetime) -> dict:
        """Delete notes by id after user confirms."""
        ids_to_delete = self._requested_note_ids(args)
        matched_notes = [
            n for n in notebook["notes"] if n.get("id") in ids_to_delete
        ]
        if not matched_notes:
            return {
                "ok": False,
                "notes_changed": False,
                "deleted_count": 0,
                "error": "no matching notes found",
            }

        note_count = len(matched_notes)
        noun = "note" if note_count == 1 else "notes"
        question = f"Delete {note_count} matching private {noun}"
        if not await self.capability_worker.run_confirmation_loop(question):
            return {"ok": True, "notes_changed": False, "deleted_count": 0, "status": "cancelled"}

        before = len(notebook["notes"])
        notebook["notes"] = [n for n in notebook["notes"] if n.get("id") not in ids_to_delete]
        deleted_count = before - len(notebook["notes"])
        return {"ok": True, "notes_changed": deleted_count > 0, "deleted_count": deleted_count, "status": "deleted"}

    # --- Storage ---

    async def _load_notebook(self) -> dict:
        """Load notes from JSON file, or refuse malformed stored data."""
        if not await self.capability_worker.check_if_file_exists(NOTES_FILE, False):
            return {"schema_version": 2, "notes": []}
        raw = await self.capability_worker.read_file(NOTES_FILE, False)
        try:
            notebook = json.loads(raw or "")
        except json.JSONDecodeError as exc:
            raise ValueError("private_notes.json is not valid JSON") from exc
        if isinstance(notebook, list):
            notebook = {"schema_version": 2, "notes": notebook}
        return self._normalize_notebook(notebook)

    async def _save_notebook(self, notebook: dict):
        """Write notes to JSON file, sorted by most recently updated."""
        notebook = self._normalize_notebook(notebook)
        notebook["notes"] = sorted(
            notebook["notes"], key=lambda n: n.get("updated_at", ""), reverse=True
        )
        # write_file appends, so delete first to avoid corrupted JSON
        if await self.capability_worker.check_if_file_exists(NOTES_FILE, False):
            await self.capability_worker.delete_file(NOTES_FILE, False)
        await self.capability_worker.write_file(
            NOTES_FILE, json.dumps(notebook, ensure_ascii=True), False,
        )

    # --- Helpers ---

    async def _get_user_input(self, fallback_msg: str) -> str | None:
        """Wait for transcription; speak fallback and return None if empty."""
        text = (await self.capability_worker.wait_for_complete_transcription() or "").strip()
        if not text:
            await self.capability_worker.speak(fallback_msg)
        return text or None

    def _normalize_title(self, title: object) -> str:
        """Normalize title formatting without rewriting the user's meaning."""
        return str(title or "").strip().strip('"').strip("'").strip()

    def _requested_note_ids(self, args: dict) -> list:
        """Return note_ids only when the tool call used the documented list shape."""
        match args.get("note_ids") or []:
            case [*note_ids]:
                return note_ids
            case _:
                return []

    def _normalize_notebook(self, notebook: object) -> dict:
        """Validate notebook shape without silently discarding saved data."""
        if not isinstance(notebook, dict):
            raise ValueError("notebook root is not an object")

        notes = notebook.get("notes")
        if not isinstance(notes, list):
            raise ValueError("notebook notes is not a list")

        if not all(isinstance(note, dict) for note in notes):
            raise ValueError("notebook contains a non-object note")

        required_fields = ("id", "title", "content", "created_at", "updated_at")
        for note in notes:
            if any(not isinstance(note.get(field), str) for field in required_fields):
                raise ValueError("notebook contains a malformed note")

        normalized = dict(notebook)
        normalized["schema_version"] = notebook.get("schema_version", 2)
        normalized["notes"] = notes
        return normalized

    def _parse_tool_call(self, llm_response: str) -> dict:
        """Parse model tool JSON, tolerating common markdown fences."""
        cleaned = llm_response.replace("```json", "").replace("```", "").strip()
        tool_call = json.loads(cleaned)
        if not isinstance(tool_call, dict):
            raise TypeError("tool call must be a JSON object")
        return tool_call
