"""
Private Notes Ability
=====================
A voice-first note-taking skill that keeps notes private by design.

Trigger words: note, notes, take a note, note this down, read my notes, 
               delete my notes, my notes, edit my note, update my note,
               change my note, fix my note

Notes are stored in notes.json (not .md) so the memory watcher never picks
them up and the Personality never surfaces them unprompted.
"""

import json
from datetime import datetime
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class PrivateNotesCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    NOTES_FILE = "private_notes.json"

    # {{register capability}}

    def call(self, worker: AgentWorker):
        worker.editor_logging_handler.info("[PrivateNotes] call() invoked")
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.log("=== Private Notes ability STARTED ===")

            trigger_context = await self.get_trigger_context()
            self.log(f"Trigger context: '{trigger_context}'")

            intent = self.classify_intent(trigger_context)
            self.log(f"Classified intent: {intent}")

            if intent["action"] == "create":
                await self.handle_create_note(intent.get("content"))
            elif intent["action"] == "read":
                await self.handle_read_notes(intent.get("filter"))
            elif intent["action"] == "edit":
                await self.handle_edit_note(intent.get("filter"))
            elif intent["action"] == "delete":
                await self.handle_delete_notes(intent.get("filter"))

        except Exception as e:
            self.log_err(f"Error in Private Notes: {str(e)}")
            await self.capability_worker.speak(
                "Sorry, I ran into a problem with your notes. Try again?"
            )
        finally:
            self.log("=== Private Notes ability STOPPED ===")
            self.capability_worker.resume_normal_flow()

    # ── Trigger Context ──────────────────────────────────────────────

    async def get_trigger_context(self) -> str:
        """Get the utterance that triggered this ability."""
        trigger = await self.capability_worker.wait_for_complete_transcription()
        self.log(f"Got trigger: '{trigger}'")
        return trigger or ""

    # ── Intent Classification ────────────────────────────────────────

    def classify_intent(self, trigger_context: str) -> dict:
        """Classify what the user wants to do with notes.

        Uses fast keyword matching for common phrases first, only falling
        back to an LLM call for ambiguous inputs.
        """
        lower = trigger_context.lower().replace("-", " ") if trigger_context else ""
        while "  " in lower:
            lower = lower.replace("  ", " ")
        lower = lower.strip()

        # ── Fast path: READ ──────────────────────────────────────────
        read_verbs = ["read ", "what ", "play ", "list ", "show ", "tell ", "go through "]
        is_read_intent = (
            ("note" in lower and any(lower.startswith(w) for w in read_verbs))
            or lower.strip() == "my notes"
        )

        if is_read_intent:
            filt = self._extract_filter(lower)
            self.log(f"Fast path → read, filter={filt}")
            return {"action": "read", "filter": filt, "content": None}

        # ── Fast path: DELETE ────────────────────────────────────────
        if any(w in lower for w in ["delete", "remove", "clear", "erase"]) and "note" in lower:
            filt = self._extract_filter(lower)
            self.log(f"Fast path → delete, filter={filt}")
            return {"action": "delete", "filter": filt, "content": None}

        # ── Fast path: EDIT ──────────────────────────────────────────
        edit_verbs = ["edit ", "update ", "change ", "modify ", "fix "]
        is_edit_intent = (
            "note" in lower and any(w in lower for w in edit_verbs)
        )
        if is_edit_intent:
            filt = self._extract_filter(lower)
            if filt == "all":
                filt = "last"
            self.log(f"Fast path → edit, filter={filt}")
            return {"action": "edit", "filter": filt, "content": None}

        # ── Fast path: CREATE ────────────────────────────────────────
        create_prefixes = [
            "take a note", "take note", "note this down", "note this",
            "new note", "save a note", "add a note", "jot this down",
            "make a note", "i want to make a note",
        ]
        for prefix in create_prefixes:
            if prefix in lower:
                idx = lower.index(prefix) + len(prefix)
                remainder = trigger_context[idx:].strip().lstrip(".,;:- ")
                content = remainder if len(remainder) > 2 else None
                self.log(f"Fast path → create, content={'yes' if content else 'no'}")
                return {"action": "create", "filter": None, "content": content}

        # Bare "note" or "notes" with no other signal → default to create
        if lower.strip() in ("note", "notes"):
            self.log("Fast path → bare trigger, defaulting to create")
            return {"action": "create", "filter": None, "content": None}

        # ── Slow path: LLM classification ────────────────────────────
        return self._llm_classify(trigger_context)

    def _extract_filter(self, lower: str) -> str:
        """Extract filter value from a lowercased utterance.

        Returns a special value ("all", "last", "today"), a single keyword,
        or a pipe-separated list of keywords for compound queries
        (e.g. "milk|cars" from "about milk or cars").
        """
        raw = None

        if "last" in lower:
            return "last"
        elif "today" in lower:
            return "today"
        elif " about " in lower:
            raw = lower.split(" about ", 1)[1].strip().rstrip(".")
        elif " on " in lower and "note" in lower.split(" on ")[0]:
            raw = lower.split(" on ", 1)[1].strip().rstrip(".")
        elif " from " in lower:
            after_from = lower.split(" from ", 1)[1].strip().rstrip(".")
            if after_from == "today":
                return "today"
            return after_from

        if not raw:
            return "all"

        # Split compound queries: "milk or cars", "milk and cars",
        # "milk, cars, and dogs"
        parts = []
        for chunk in raw.replace(",", " , ").split():
            if chunk in ("or", "and", ",", "&"):
                continue
            parts.append(chunk)

        if len(parts) > 1:
            return "|".join(parts)
        elif len(parts) == 1:
            return parts[0]
        return "all"

    def _llm_classify(self, trigger_context: str) -> dict:
        """Use the LLM to classify ambiguous intent."""
        prompt = f"""Classify this user request about notes. Return ONLY valid JSON.

User said: "{trigger_context}"

Classify into one of these actions:
- "create": User wants to take/add/save a new note.
- "read": User wants to hear/read their notes.
- "edit": User wants to edit/update/change/fix an existing note.
- "delete": User wants to delete/clear/remove notes.

For "read", "edit", and "delete", extract the filter:
- "today": notes from today
- "last": just the most recent note  
- "all": all notes
- "X_minutes_ago": if user says "from X minutes ago"
- For topic searches like "about groceries", extract just the keyword (e.g., "groceries")

If action is "create" and they already dictated content, extract it.

Return format:
{{"action": "create|read|edit|delete", "filter": "today|last|all|X_minutes_ago|keyword|null", "content": "note content if provided or null"}}

Return ONLY the JSON object, no markdown, no explanation."""

        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()

        try:
            result = json.loads(clean)
            if result.get("action") not in ["create", "read", "edit", "delete"]:
                result["action"] = "create"
            # Normalize compound filters the LLM may return as plain text
            filt = result.get("filter")
            if filt and isinstance(filt, str) and filt not in ("all", "last", "today", "null", None):
                parts = []
                for chunk in filt.replace(",", " , ").split():
                    if chunk.lower() in ("or", "and", ",", "&"):
                        continue
                    parts.append(chunk.lower())
                if len(parts) > 1:
                    result["filter"] = "|".join(parts)
                elif len(parts) == 1:
                    result["filter"] = parts[0]
            return result
        except json.JSONDecodeError:
            self.log_err(f"Failed to parse intent JSON: {clean}")
            return {"action": "create", "filter": None, "content": None}

    # ── Filter Helpers ───────────────────────────────────────────────

    def _filter_label(self, filter_type: str) -> str:
        """Return a spoken label describing the active filter, or '' for no filter."""
        if not filter_type or filter_type == "all":
            return ""
        if filter_type == "today":
            return " from today"
        if filter_type == "last":
            return ""
        if filter_type.endswith("_minutes_ago"):
            try:
                minutes = int(filter_type.replace("_minutes_ago", ""))
                return f" from about {minutes} minutes ago"
            except ValueError:
                return ""
        keywords = [k.strip() for k in filter_type.split("|") if k.strip()]
        if keywords:
            return " about " + " or ".join(keywords)
        return ""

    def _expand_keyword(self, kw: str) -> list:
        """Return a keyword plus its singular/plural variant for fuzzy matching."""
        variants = [kw]
        if kw.endswith("s"):
            variants.append(kw[:-1])           # "cars" → "car"
            if kw.endswith("ies"):
                variants.append(kw[:-3] + "y")  # "berries" → "berry"
            elif kw.endswith("es"):
                variants.append(kw[:-2])        # "boxes" → "box"
        else:
            variants.append(kw + "s")           # "car" → "cars"
        return variants

    def _note_matches_keywords(self, note_content: str, keywords: list) -> bool:
        """Check if note content matches any keyword, accounting for plural/singular."""
        content_lower = note_content.lower()
        for kw in keywords:
            variants = self._expand_keyword(kw)
            for variant in variants:
                if variant in content_lower:
                    self.log(f"Matched variant '{variant}' in '{content_lower}'")
                    return True
        return False

    def filter_notes(self, notes: list, filter_type: str) -> list:
        """Filter notes based on the filter type.

        Supports pipe-separated keywords for compound queries
        (e.g. "milk|cars" matches notes containing "milk" OR "cars").
        """
        self.log(f"filter_notes called: filter_type='{filter_type}', {len(notes)} notes")

        if filter_type == "last":
            return [notes[-1]] if notes else []

        if filter_type == "today":
            today = datetime.now().date()
            return [
                n for n in notes
                if datetime.fromisoformat(n["created_at_iso"]).date() == today
            ]

        if filter_type == "all":
            return notes

        if filter_type:
            keywords = [k.strip().lower() for k in filter_type.split("|") if k.strip()]
            self.log(f"filter_notes keywords: {keywords}")
            self.log(f"filter_notes note contents: {[n['content'] for n in notes]}")
            result = [
                n for n in notes
                if self._note_matches_keywords(n["content"], keywords)
            ]
            self.log(f"filter_notes matched {len(result)} notes")
            return result

        return notes

    # ── Note CRUD ────────────────────────────────────────────────────

    async def handle_create_note(self, existing_content: str = None):
        """Handle note creation. If content provided, save it. Otherwise prompt."""
        if existing_content and len(existing_content.strip()) > 2:
            cleaned = self.clean_dictation(existing_content)
            await self.save_note(cleaned)
            await self.capability_worker.speak("Noted.")
            return

        await self.capability_worker.speak("Go ahead.")

        self.log(">>> Recording started: waiting for note dictation")
        raw_dictation = await self.capability_worker.user_response()
        self.log(f"<<< Recording stopped: got '{raw_dictation}'")

        if not raw_dictation or raw_dictation.strip() == "":
            await self.capability_worker.speak("I didn't catch that.")
            return

        if self.classify_yes_no_cancel(raw_dictation, "cancel") == "cancel":
            await self.capability_worker.speak("Cancelled.")
            return

        cleaned = self.clean_dictation(raw_dictation)
        await self.save_note(cleaned)
        await self.capability_worker.speak("Noted.")

    def clean_dictation(self, raw: str) -> str:
        """Use LLM to clean up raw voice dictation into a proper note."""
        prompt = f"""Clean up this voice dictation into a clear, concise note.

Raw dictation: "{raw}"

Rules:
- Fix obvious speech-to-text errors
- Remove filler words (um, uh, like, you know)
- Fix punctuation and capitalization
- Keep the meaning exactly as intended
- Don't add information that wasn't there
- Don't make it longer than necessary
- If it's already clean, return it as-is

Return ONLY the cleaned note text, nothing else."""

        cleaned = self.capability_worker.text_to_text_response(prompt)
        return cleaned.strip().strip('"').strip("'")

    async def save_note(self, content: str):
        """Save a note to the JSON file."""
        notes = await self.load_notes()

        tz = self.capability_worker.get_timezone()
        now = datetime.now()

        note = {
            "id": f"note_{int(now.timestamp() * 1000)}",
            "content": content,
            "created_at_iso": now.isoformat(),
            "created_at_epoch": int(now.timestamp()),
            "timezone": tz,
            "human_time": now.strftime("%I:%M %p on %A, %b %d, %Y")
        }

        notes.append(note)
        await self.save_notes_list(notes)
        self.log(f"Saved note: {note['id']}")

    async def load_notes(self) -> list:
        """Load existing notes from JSON file."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                self.NOTES_FILE, False
            )
            if not exists:
                return []

            raw = await self.capability_worker.read_file(self.NOTES_FILE, False)
            return json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            self.log_err(f"Error loading notes: {e}")
            return []

    async def handle_read_notes(self, filter_type: str = None):
        """Read notes back to the user with optional filtering."""
        notes = await self.load_notes()

        if not notes:
            await self.capability_worker.speak("You don't have any notes yet.")
            return

        filter_type = filter_type or "all"
        filtered = self.filter_notes(notes, filter_type)

        if not filtered:
            if filter_type == "today":
                await self.capability_worker.speak("No notes from today.")
            else:
                label = filter_type.replace("|", " or ")
                if len(notes) <= 3:
                    previews = [n["content"][:40] for n in notes]
                    summary = ". ".join(previews)
                    await self.capability_worker.speak(
                        f"No notes about {label}. You have {len(notes)}: {summary}."
                    )
                else:
                    await self.capability_worker.speak(
                        f"No notes about {label}. You have {len(notes)} total. Want me to read them all?"
                    )
                    response = await self.capability_worker.user_response()
                    if response and self.classify_yes_no_cancel(response, "read all notes") == "yes":
                        filtered = notes
                    else:
                        return

        if not filtered:
            return

        if filter_type == "last":
            note = filtered[0]
            await self.capability_worker.speak(
                f"Your last note, from {self.friendly_time(note)}: {note['content']}"
            )
        elif len(filtered) == 1:
            note = filtered[0]
            await self.capability_worker.speak(
                f"You have one note{self._filter_label(filter_type)}: {note['content']}"
            )
        else:
            await self.capability_worker.speak(
                f"You have {len(filtered)} notes{self._filter_label(filter_type)}. Here they are."
            )
            for i, note in enumerate(filtered, 1):
                await self.worker.session_tasks.sleep(0.5)
                time_str = self.friendly_time(note)
                await self.capability_worker.speak(
                    f"{time_str}: {note['content']}"
                )

                if i >= 10 and i < len(filtered):
                    remaining = len(filtered) - i
                    await self.capability_worker.speak(
                        f"That's the first 10. {remaining} more. Want me to continue?"
                    )
                    response = await self.capability_worker.user_response()
                    if response and self.classify_yes_no_cancel(response, "continue reading") == "yes":
                        continue
                    else:
                        break

    async def handle_edit_note(self, filter_type: str = None):
        """Edit an existing note. Find it by filter, read it back, collect replacement."""
        notes = await self.load_notes()

        if not notes:
            await self.capability_worker.speak("You don't have any notes to edit.")
            return

        filter_type = filter_type or "last"

        # Find the target note
        if filter_type == "last":
            target = notes[-1]
        elif filter_type == "today":
            today = datetime.now().date()
            today_notes = [
                n for n in notes
                if datetime.fromisoformat(n["created_at_iso"]).date() == today
            ]
            if not today_notes:
                await self.capability_worker.speak("No notes from today to edit.")
                return
            if len(today_notes) == 1:
                target = today_notes[0]
            else:
                await self.capability_worker.speak(
                    f"You have {len(today_notes)} notes from today. I'll edit the most recent one."
                )
                target = today_notes[-1]
        elif filter_type and filter_type.endswith("_minutes_ago"):
            try:
                minutes = int(filter_type.replace("_minutes_ago", ""))
                now = datetime.now()
                target_time = now.timestamp() - (minutes * 60)
                matching = [
                    n for n in notes
                    if abs(n["created_at_epoch"] - target_time) < 120
                ]
                if not matching:
                    await self.capability_worker.speak(f"No notes from around {minutes} minutes ago.")
                    return
                target = matching[0]
            except ValueError:
                await self.capability_worker.speak("Couldn't understand that time. Try again?")
                return
        else:
            matching = self.filter_notes(notes, filter_type)
            if not matching:
                label = self._filter_label(filter_type).strip()
                await self.capability_worker.speak(f"No notes {label}.")
                return
            if len(matching) == 1:
                target = matching[0]
            else:
                await self.capability_worker.speak(
                    f"Found {len(matching)} notes{self._filter_label(filter_type)}. I'll edit the most recent one."
                )
                target = matching[-1]

        # Read back and ask for replacement
        await self.capability_worker.speak(
            f"Here's the note: {target['content']}. What should it say instead?"
        )

        raw_response = await self.capability_worker.user_response()

        if not raw_response or raw_response.strip() == "":
            await self.capability_worker.speak("I didn't catch that. Edit cancelled.")
            return

        lower_resp = raw_response.lower().strip()
        if any(phrase in lower_resp for phrase in
               ["never mind", "cancel", "forget it", "stop", "don't edit"]):
            await self.capability_worker.speak("Okay, kept it as is.")
            return

        cleaned = self.clean_dictation(raw_response)

        for n in notes:
            if n["id"] == target["id"]:
                n["content"] = cleaned
                n["edited_at_iso"] = datetime.now().isoformat()
                break

        await self.save_notes_list(notes)
        await self.capability_worker.speak("Updated.")

    async def handle_delete_notes(self, filter_type: str = None):
        """Delete notes with confirmation."""
        notes = await self.load_notes()

        if not notes:
            await self.capability_worker.speak("You don't have any notes to delete.")
            return

        filter_type = filter_type or "all"
        label = self._filter_label(filter_type).strip()
        self.log(f"handle_delete_notes: filter_type='{filter_type}', label='{label}', {len(notes)} notes")

        # Handle "delete all" separately since it skips filtering
        if filter_type == "all":
            await self.capability_worker.speak(
                f"Delete all {len(notes)} notes? This can't be undone. Say yes to confirm."
            )
            response = await self.capability_worker.user_response()
            if response and self.classify_yes_no_cancel(response, "confirm deletion") == "yes":
                await self.capability_worker.delete_file(self.NOTES_FILE, False)
                await self.capability_worker.speak("All notes deleted.")
            else:
                await self.capability_worker.speak("Okay, kept them.")
            return

        # Find matching notes
        if filter_type == "last":
            matching = [notes[-1]]
        elif filter_type == "today":
            today = datetime.now().date()
            matching = [
                n for n in notes
                if datetime.fromisoformat(n["created_at_iso"]).date() == today
            ]
        elif filter_type.endswith("_minutes_ago"):
            try:
                minutes = int(filter_type.replace("_minutes_ago", ""))
                now = datetime.now()
                target_time = now.timestamp() - (minutes * 60)
                matching = [
                    n for n in notes
                    if abs(n["created_at_epoch"] - target_time) < 120
                ]
            except ValueError:
                await self.capability_worker.speak("Couldn't understand that time. Try again?")
                return
        else:
            # Keyword filter — uses filter_notes which handles plural/singular
            matching = self.filter_notes(notes, filter_type)

        self.log(f"handle_delete_notes: found {len(matching)} matching notes")

        if not matching:
            await self.capability_worker.speak(f"No notes{' ' + label if label else ''}.")
            return

        # Confirm deletion
        if len(matching) == 1:
            note = matching[0]
            await self.capability_worker.speak(
                f"Delete this note: '{note['content'][:50]}'? Say yes to confirm."
            )
        else:
            await self.capability_worker.speak(
                f"Found {len(matching)} notes{' ' + label if label else ''}. Delete all of them? Say yes to confirm."
            )

        response = await self.capability_worker.user_response()
        if response and self.classify_yes_no_cancel(response, "confirm deletion") == "yes":
            matching_ids = {n["id"] for n in matching}
            remaining = [n for n in notes if n["id"] not in matching_ids]
            await self.save_notes_list(remaining)
            if len(matching) == 1:
                await self.capability_worker.speak("Deleted.")
            else:
                await self.capability_worker.speak(f"Deleted {len(matching)} notes.")
        else:
            await self.capability_worker.speak("Okay, kept them.")

    # ── Storage ──────────────────────────────────────────────────────

    async def save_notes_list(self, notes: list):
        """Save the full notes list (used after modifications)."""
        try:
            exists = await self.capability_worker.check_if_file_exists(self.NOTES_FILE, False)
            if exists:
                await self.capability_worker.delete_file(self.NOTES_FILE, False)

            if notes:
                await self.capability_worker.write_file(
                    self.NOTES_FILE,
                    json.dumps(notes, indent=2),
                    False
                )
        except Exception as e:
            self.log_err(f"Failed to save notes list: {e}")
            raise

    # ── Time Helpers ─────────────────────────────────────────────────

    def friendly_time(self, note: dict) -> str:
        """Generate a friendly time description for a note."""
        try:
            created = datetime.fromisoformat(note["created_at_iso"])
            now = datetime.now()
            diff = now - created

            if diff.days == 0:
                if diff.seconds < 60:
                    return "Just now"
                elif diff.seconds < 3600:
                    mins = diff.seconds // 60
                    return f"{mins} minute{'s' if mins != 1 else ''} ago"
                else:
                    hours = diff.seconds // 3600
                    return f"{hours} hour{'s' if hours != 1 else ''} ago"
            elif diff.days == 1:
                return "Yesterday"
            elif diff.days < 7:
                return created.strftime("%A")
            else:
                return created.strftime("%b %d")
        except Exception:
            return note.get("human_time", "Unknown time")

    # ── Logging & Helpers ────────────────────────────────────────────

    def log(self, message: str):
        self.worker.editor_logging_handler.info(f"[PrivateNotes] {message}")

    def log_err(self, message: str):
        self.worker.editor_logging_handler.error(f"[PrivateNotes] {message}")

    def classify_yes_no_cancel(self, user_input: str, context: str) -> str:
        """Use LLM to classify user response as yes, no, or cancel."""
        prompt = f"""Classify this user response. Context: user was asked about {context}.

User said: "{user_input}"

Classify as exactly one of:
- "yes": User is agreeing, confirming, or saying yes in any way
- "no": User is declining, refusing, or saying no
- "cancel": User wants to exit, stop, or cancel the whole interaction

Return ONLY one word: yes, no, or cancel. Nothing else."""

        raw = self.capability_worker.text_to_text_response(prompt)
        result = raw.strip().lower().replace('"', '').replace("'", "")

        if result in ["yes", "no", "cancel"]:
            return result
        if "yes" in result:
            return "yes"
        elif "cancel" in result:
            return "cancel"

        self.log(f"Ambiguous yes/no/cancel: '{raw}' -> defaulting to 'no'")
        return "no"
