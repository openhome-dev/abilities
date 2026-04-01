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
  "name": "write_note|read_notes|delete_notes|ask_followup|finish",
  "arguments": {}
}

Available tools:

1) write_note — create or overwrite a note
{"name": "write_note", "arguments": {"note_id": null, "title": "string", "content": "string", "confirmation": "string or null"}}
note_id=null creates a new note (no confirmation needed).
note_id=<uuid> overwrites — provide a short spoken confirmation question.

2) read_notes — read notes by id
{"name": "read_notes", "arguments": {"note_ids": ["uuid"]}}

3) delete_notes — delete notes by id
{"name": "delete_notes", "arguments": {"note_ids": ["uuid"], "confirmation": "string"}}
Always provide a short spoken confirmation question (e.g. "Delete your grocery list?").

4) ask_followup — ask the user for clarification
{"name": "ask_followup", "arguments": {"question": "string"}}

5) finish — speak a final response to the user
{"name": "finish", "arguments": {"response": "string"}}

Rules:
- The note index is sorted by updated_at descending. Latest note = first id.
- Never invent note ids. Resolve titles to ids from the note index.
- If ambiguous, use ask_followup.
- Create short, useful titles. Keep content faithful to the user's meaning.
- After a tool result is shown, call finish with a concise voice-friendly response.
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

            notebook = await self._load_notebook()

            # Capture time once so the context prefix stays identical across turns (LLM caching).
            now = datetime.now(ZoneInfo(self.capability_worker.get_timezone()))

            tool_handlers = {
                "write_note": self._handle_write_note,
                "read_notes": self._handle_read_notes,
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
                # LLMs sometimes wrap JSON in markdown fences
                tool_call = json.loads(llm_response.replace("```json", "").replace("```", "").strip())
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("arguments", {})
                self.worker.editor_logging_handler.info(f"[PrivateNotes] Tool={tool_name}")

                history.append({"role": "assistant", "content": llm_response})

                if tool_name == "finish":
                    await self.capability_worker.speak(tool_args.get("response", ""))
                    return

                if tool_name == "ask_followup":
                    await self.capability_worker.speak(tool_args.get("question", ""))
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
        title = args.get("title", "")
        content = args.get("content", "")
        timestamp = now.isoformat()

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

        if not await self.capability_worker.run_confirmation_loop(args.get("confirmation", "")):
            return {"ok": True, "notes_changed": False, "status": "cancelled"}

        existing["title"] = title
        existing["content"] = content
        existing["updated_at"] = timestamp
        return {"ok": True, "notes_changed": True, "status": "updated", "title": title}

    async def _handle_read_notes(self, notebook: dict, args: dict, _now: datetime) -> dict:
        """Return matched notes (capped at MAX_READBACK). LLM formats them for speech."""
        note_ids = set(args.get("note_ids", []))
        matched = sorted(
            [n for n in notebook["notes"] if n.get("id") in note_ids],
            key=lambda n: n.get("updated_at", ""),
            reverse=True,
        )
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
        ids_to_delete = set(args.get("note_ids", []))

        if not await self.capability_worker.run_confirmation_loop(args.get("confirmation", "")):
            return {"ok": True, "notes_changed": False, "deleted_count": 0, "status": "cancelled"}

        before = len(notebook["notes"])
        notebook["notes"] = [n for n in notebook["notes"] if n.get("id") not in ids_to_delete]
        deleted_count = before - len(notebook["notes"])
        return {"ok": True, "notes_changed": deleted_count > 0, "deleted_count": deleted_count, "status": "deleted"}

    # --- Storage ---

    async def _load_notebook(self) -> dict:
        """Load notes from JSON file, or return empty notebook if missing."""
        if not await self.capability_worker.check_if_file_exists(NOTES_FILE, False):
            return {"schema_version": 2, "notes": []}
        raw = await self.capability_worker.read_file(NOTES_FILE, False)
        data = json.loads(raw)
        if isinstance(data, list):
            return {"schema_version": 2, "notes": data}
        return data

    async def _save_notebook(self, notebook: dict):
        """Write notes to JSON file, sorted by most recently updated."""
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
