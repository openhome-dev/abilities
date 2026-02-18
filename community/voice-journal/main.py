import json
import os
import random
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# VOICE JOURNAL
# A persistent voice journal. Users dictate entries, review past entries,
# search by topic, and delete their journal — all by voice. Data persists
# across sessions using the file storage API.
# =============================================================================

ENTRIES_FILE = "voice_journal_entries.txt"
PREFS_FILE = "voice_journal_prefs.json"

MAX_TURNS = 15

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "bye", "goodbye",
    "leave", "cancel", "nothing else", "no thanks",
    "i'm good", "im good", "i am good", "nah",
}

ADD_KEYWORDS = {"write", "add", "new", "record", "save", "log", "note", "jot"}
READ_KEYWORDS = {
    "read", "review", "hear", "listen", "playback",
    "what did", "entries", "show", "tell me",
}
SEARCH_KEYWORDS = {"search", "find", "look for", "about", "mention"}
DELETE_KEYWORDS = {"delete", "remove", "clear", "erase", "wipe"}
EDIT_KEYWORDS = {"edit", "change", "modify", "update", "fix", "correct", "revise"}
HELP_KEYWORDS = {"help", "commands", "options", "what can"}

CONVERSATIONAL_TRIGGERS = {
    "let's talk", "lets talk", "ask me questions", "conversational",
    "deep dive", "help me write", "interview me",
}

PROMPT_TRIGGERS = {
    "prompt me", "give me a prompt", "don't know what to write",
    "i don't know", "inspire me", "suggestion",
    "what should i write", "help me start",
}

JOURNAL_PROMPTS = [
    "What are you grateful for today?",
    "What was the best part of your day so far?",
    "What's something that challenged you recently?",
    "What's on your mind that you haven't said out loud?",
    "Describe a moment today that made you smile.",
    "What's something you learned this week?",
    "If you could change one thing about today, what would it be?",
    "What are you looking forward to?",
    "How are you really feeling right now?",
    "What would you tell your future self about this moment?",
]

OLDER_KEYWORDS = {"older", "previous", "more", "earlier", "before"}
NEWER_KEYWORDS = {"newer", "recent", "back", "latest", "forward", "next"}

PAGE_SIZE = 5

FILLER_EDITING = [
    "One sec, updating that entry.",
    "Got it, making that change.",
    "Updating your journal now.",
]

FILLER_SAVING = [
    "One sec, saving that.",
    "Got it, writing that down.",
    "Saving your entry now.",
]
FILLER_READING = [
    "Let me pull up your entries.",
    "One moment, checking your journal.",
    "Pulling that up for you.",
]
FILLER_CLEANING = [
    "One sec, polishing that up.",
    "Let me clean that up a bit.",
    "Tidying that up for you.",
]

CLEAN_ENTRY_PROMPT = (
    "The user dictated this journal entry by voice. Clean it up into a polished, "
    "first-person journal entry. Fix grammar, remove filler words (um, uh, like), "
    "but keep the original meaning, tone, and length. Do NOT add information. "
    "Return ONLY the cleaned entry text, nothing else.\n\n"
    "Raw entry: {raw}"
)

EXTRACT_NAME_PROMPT = (
    "The user was asked 'What should I call you?' and responded with: '{raw}'\n"
    "Extract ONLY their name or nickname from this response. "
    "Return ONLY the name, nothing else. If unclear, return 'friend'."
)

SEARCH_PROMPT = (
    "The user wants to find journal entries about: '{query}'\n"
    "Here are all their journal entries:\n{entries}\n\n"
    "Return ONLY the matching entries (with their dates). If none match, say "
    "'No entries found about that topic.' Keep it brief for voice readback."
)

SUMMARIZE_PROMPT = (
    "Summarize these journal entries in 2-3 sentences for voice readback. "
    "Mention key themes and dates briefly.\n\n{entries}"
)

INTENT_PROMPT = (
    "Classify this user input into exactly one of: add, read, search, edit, delete, exit, unknown.\n"
    "Context: this is a voice journal app. The user can add entries, read/review "
    "entries, search entries, edit an existing entry, delete all entries, or exit.\n"
    "Return ONLY one word, nothing else.\n"
    "Input: {text}"
)

FORMAT_ENTRY_PROMPT = (
    "Reformat this journal entry for spoken readback. Convert the timestamp to "
    "natural speech (e.g. 'On January 15th at 2:30 PM, you wrote:'). "
    "Keep the entry text as-is. Return ONLY the reformatted text.\n\n"
    "Entry: {entry}"
)

CONVERSATIONAL_SYSTEM_PROMPT = (
    "You are a warm journaling companion. Based on the user's previous "
    "response, ask ONE short follow-up question to help them reflect deeper. "
    "Keep it conversational and empathetic. Return ONLY the question."
)

MERGE_ENTRIES_PROMPT = (
    "Merge these question-and-answer exchanges into one cohesive first-person "
    "journal entry. Keep the user's voice and tone. Do NOT add information. "
    "Return ONLY the merged entry text, nothing else.\n\n"
    "Exchanges:\n{exchanges}"
)

EXTRACT_NUMBER_PROMPT = (
    "The user was asked to pick an entry number and responded with: '{raw}'\n"
    "Extract the number the user chose as a single digit. "
    "Handle words like 'the second one' (return 2), 'number 3' (return 3), etc. "
    "Return ONLY the number, nothing else. If unclear, return 0."
)


class VoiceJournalCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.user_prefs = {"name": "friend", "entry_count": 0}
        self.idle_count = 0

        # Grab the triggering transcription (same pattern as official abilities)
        self.initial_request = None
        try:
            self.initial_request = worker.transcription
        except (AttributeError, Exception):
            pass
        if not self.initial_request:
            try:
                self.initial_request = worker.last_transcription
            except (AttributeError, Exception):
                pass
        if not self.initial_request:
            try:
                self.initial_request = worker.current_transcription
            except (AttributeError, Exception):
                pass
        # Fallback: read from conversation history
        if not self.initial_request:
            try:
                history = worker.agent_memory.full_message_history
                if history:
                    self.initial_request = history[-1].get("content", "")
            except (AttributeError, Exception):
                pass

        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # Boot & Onboarding
    # -------------------------------------------------------------------------

    async def boot(self):
        """Check for returning user or run first-time onboarding."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )
            if exists:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                self.user_prefs = json.loads(raw)
                # Sync entry count with actual file
                await self._sync_entry_count()
                name = self.user_prefs.get("name", "friend")
                count = self.user_prefs.get("entry_count", 0)
                if count == 0:
                    await self.capability_worker.speak(
                        f"Welcome back, {name}. Your journal is empty right now."
                    )
                elif count == 1:
                    await self.capability_worker.speak(
                        f"Welcome back, {name}. You have one entry."
                    )
                else:
                    await self.capability_worker.speak(
                        f"Welcome back, {name}. You have {count} entries."
                    )
            else:
                await self._run_onboarding()
        except Exception as e:
            self._log("error", f"Boot error: {e}")
            self.user_prefs = {"name": "friend", "entry_count": 0}
            await self.capability_worker.speak("Welcome to your Voice Journal.")

    async def _run_onboarding(self):
        """First-run experience: collect name and explain commands."""
        await self.capability_worker.speak(
            "Welcome to your Voice Journal! I'll help you keep a daily "
            "journal using just your voice."
        )
        raw_name = await self.capability_worker.run_io_loop(
            "First, what should I call you?"
        )
        # Extract clean name via LLM (handles "my name is Chris" etc.)
        name = "friend"
        if raw_name and raw_name.strip():
            try:
                extracted = self.capability_worker.text_to_text_response(
                    EXTRACT_NAME_PROMPT.format(raw=raw_name)
                )
                cleaned = extracted.strip().strip('"').strip("'").strip(".")
                if cleaned and len(cleaned) < 30 and cleaned.lower() != "friend":
                    name = cleaned
                elif raw_name.strip() and len(raw_name.strip()) < 30:
                    name = raw_name.strip()
            except Exception:
                if raw_name.strip() and len(raw_name.strip()) < 30:
                    name = raw_name.strip()

        self.user_prefs = {"name": name, "entry_count": 0}
        await self._save_prefs()
        await self.capability_worker.speak(
            f"Nice to meet you, {name}! You can add entries, read past "
            "ones, search, or delete. Say done whenever you want to leave."
        )

    async def _sync_entry_count(self):
        """Sync entry count in prefs with actual entries file."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                ENTRIES_FILE, False
            )
            if not exists:
                if self.user_prefs.get("entry_count", 0) != 0:
                    self.user_prefs["entry_count"] = 0
                    await self._save_prefs()
                return
            raw = await self.capability_worker.read_file(ENTRIES_FILE, False)
            lines = [ln.strip() for ln in raw.strip().split("\n") if ln.strip()]
            actual_count = len(lines)
            if self.user_prefs.get("entry_count", 0) != actual_count:
                self.user_prefs["entry_count"] = actual_count
                await self._save_prefs()
        except Exception as e:
            self._log("warning", f"Count sync issue: {e}")

    # -------------------------------------------------------------------------
    # Intent Detection
    # -------------------------------------------------------------------------

    def _classify_intent(self, text: str) -> str:
        """Keyword-first intent detection with LLM fallback."""
        if not text or not text.strip():
            return "unknown"
        lower = text.lower().strip()

        # Check exit first — before anything else
        if any(w in lower for w in EXIT_WORDS):
            return "exit"

        # Check help
        if any(w in lower for w in HELP_KEYWORDS):
            return "help"

        # Keyword matching — order matters (most specific first)
        if any(w in lower for w in DELETE_KEYWORDS):
            return "delete"
        if any(w in lower for w in EDIT_KEYWORDS):
            return "edit"
        if any(w in lower for w in SEARCH_KEYWORDS):
            return "search"
        if any(w in lower for w in READ_KEYWORDS):
            return "read"
        if any(w in lower for w in ADD_KEYWORDS):
            return "add"

        # LLM fallback for natural phrasing the keywords missed
        try:
            result = self.capability_worker.text_to_text_response(
                INTENT_PROMPT.format(text=text)
            )
            intent = result.strip().lower().rstrip(".")
            if intent in ("add", "read", "search", "edit", "delete", "exit"):
                return intent
        except Exception as e:
            self._log("error", f"Intent classification error: {e}")

        return "unknown"

    def _extract_inline_entry(self, text: str) -> str:
        """Extract an entry if the user included it in the trigger phrase."""
        if not text:
            return ""
        lower = text.lower()
        # Patterns: "add to my journal: had a great day"
        #           "journal entry that I had a great day"
        #           "log in my journal saying today was rough"
        for sep in [":", " that ", " saying "]:
            if sep in lower:
                idx = lower.index(sep)
                after = text[idx + len(sep):].strip()
                if len(after) > 5:
                    return after
        return ""

    # -------------------------------------------------------------------------
    # Handlers
    # -------------------------------------------------------------------------

    async def _save_entry(self, cleaned: str):
        """Timestamp, append to file, update prefs."""
        await self.capability_worker.speak(random.choice(FILLER_SAVING))
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry_line = f"{timestamp} | {cleaned}"

            # Check if file already has content — prepend newline if so
            file_exists = await self.capability_worker.check_if_file_exists(
                ENTRIES_FILE, False
            )
            if file_exists:
                entry_line = "\n" + entry_line

            await self.capability_worker.write_file(
                ENTRIES_FILE, entry_line, False
            )
            self.user_prefs["entry_count"] = (
                self.user_prefs.get("entry_count", 0) + 1
            )
            await self._save_prefs()
            await self.capability_worker.speak("Done! It's in your journal.")
        except Exception as e:
            self._log("error", f"Save entry error: {e}")
            await self.capability_worker.speak(
                "Sorry, I had trouble saving that. Try again later."
            )

    async def _clean_confirm_save(self, raw_entry: str, already_cleaned: bool = False):
        """LLM clean, read back, confirm, save. Returns True if saved."""
        if already_cleaned:
            cleaned = raw_entry.strip()
        else:
            await self.capability_worker.speak(random.choice(FILLER_CLEANING))
            try:
                cleaned = self.capability_worker.text_to_text_response(
                    CLEAN_ENTRY_PROMPT.format(raw=raw_entry)
                )
                cleaned = cleaned.strip().strip('"').strip("'")
                if not cleaned:
                    cleaned = raw_entry.strip()
            except Exception:
                cleaned = raw_entry.strip()

        # Read back and confirm
        await self.capability_worker.speak(f'Here\'s what I have: "{cleaned}"')
        confirmed = await self.capability_worker.run_confirmation_loop(
            "Should I save this?"
        )

        if not confirmed:
            await self.capability_worker.speak("No problem, I tossed it.")
            return False

        await self._save_entry(cleaned)
        return True

    async def _handle_add(self, inline_entry: str = ""):
        """Add a new journal entry with optional prompt/conversational branching."""
        if inline_entry:
            raw_entry = inline_entry
        else:
            raw_entry = await self.capability_worker.run_io_loop(
                "What's on your mind? Say 'prompt me' for inspiration "
                "or 'let's talk' to go deeper."
            )

        if not raw_entry or not raw_entry.strip():
            await self.capability_worker.speak(
                "I didn't catch that. You can try again."
            )
            return

        # Check for exit words in the response
        if any(w in raw_entry.lower() for w in EXIT_WORDS):
            return

        lower = raw_entry.lower().strip()

        # Check for prompt triggers
        if any(t in lower for t in PROMPT_TRIGGERS):
            prompt = random.choice(JOURNAL_PROMPTS)
            response = await self.capability_worker.run_io_loop(prompt)
            if not response or not response.strip():
                await self.capability_worker.speak(
                    "I didn't catch that. You can try again."
                )
                return
            if any(w in response.lower() for w in EXIT_WORDS):
                return
            await self._clean_confirm_save(response)
            return

        # Check for conversational triggers
        if any(t in lower for t in CONVERSATIONAL_TRIGGERS):
            await self._handle_conversational_add()
            return

        # Default quick-add path
        await self._clean_confirm_save(raw_entry)

    async def _handle_conversational_add(self):
        """Multi-turn journaling: LLM asks follow-ups, merges into one entry."""
        exchanges = []

        # Opening question: random guided prompt
        prompt = random.choice(JOURNAL_PROMPTS)
        response = await self.capability_worker.run_io_loop(prompt)
        if not response or not response.strip():
            await self.capability_worker.speak(
                "No worries, we can try again later."
            )
            return
        if any(w in response.lower() for w in EXIT_WORDS):
            return
        exchanges.append({"q": prompt, "a": response.strip()})

        # 2 more follow-up rounds
        for _ in range(2):
            try:
                history_text = "\n".join(
                    f"Q: {ex['q']}\nA: {ex['a']}" for ex in exchanges
                )
                follow_up = self.capability_worker.text_to_text_response(
                    f"Previous exchanges:\n{history_text}\n\nAsk a follow-up:",
                    system_prompt=CONVERSATIONAL_SYSTEM_PROMPT,
                )
                follow_up = follow_up.strip()
                if not follow_up:
                    break
            except Exception:
                break

            response = await self.capability_worker.run_io_loop(follow_up)
            if not response or not response.strip():
                break
            if any(w in response.lower() for w in EXIT_WORDS):
                break
            exchanges.append({"q": follow_up, "a": response.strip()})

        if not exchanges:
            return

        # Merge all exchanges into one entry
        exchanges_text = "\n".join(
            f"Q: {ex['q']}\nA: {ex['a']}" for ex in exchanges
        )
        try:
            merged = self.capability_worker.text_to_text_response(
                MERGE_ENTRIES_PROMPT.format(exchanges=exchanges_text)
            )
            merged = merged.strip()
            if not merged:
                # Fallback: concatenate answers
                merged = " ".join(ex["a"] for ex in exchanges)
        except Exception:
            merged = " ".join(ex["a"] for ex in exchanges)

        await self._clean_confirm_save(merged, already_cleaned=True)

    async def _handle_read(self):
        """Read past journal entries."""
        count = self.user_prefs.get("entry_count", 0)
        if count == 0:
            await self.capability_worker.speak(
                "Your journal is empty. Want to add your first entry?"
            )
            return

        choice = await self.capability_worker.run_io_loop(
            "Want today's entries, recent ones, or everything?"
        )

        if not choice or not choice.strip():
            choice = "recent"

        if any(w in choice.lower() for w in EXIT_WORDS):
            return

        await self.capability_worker.speak(random.choice(FILLER_READING))

        try:
            exists = await self.capability_worker.check_if_file_exists(
                ENTRIES_FILE, False
            )
            if not exists:
                await self.capability_worker.speak("No entries found in your journal.")
                self.user_prefs["entry_count"] = 0
                await self._save_prefs()
                return

            raw = await self.capability_worker.read_file(ENTRIES_FILE, False)
            lines = [ln.strip() for ln in raw.strip().split("\n") if ln.strip()]

            if not lines:
                await self.capability_worker.speak("No entries found.")
                self.user_prefs["entry_count"] = 0
                await self._save_prefs()
                return

            lower_choice = choice.lower()

            if "today" in lower_choice:
                today_str = datetime.now().strftime("%Y-%m-%d")
                filtered = [ln for ln in lines if ln.startswith(today_str)]
                if not filtered:
                    await self.capability_worker.speak(
                        "No entries from today yet. Want to hear recent ones instead?"
                    )
                    fallback = await self.capability_worker.user_response()
                    if fallback and any(
                        w in fallback.lower()
                        for w in ("yes", "yeah", "sure", "ok", "recent")
                    ):
                        lines = lines[-5:]
                    else:
                        return
                else:
                    lines = filtered

            elif "all" in lower_choice or "everything" in lower_choice:
                pass  # use all lines
            else:
                # Default: recent (last 5)
                lines = lines[-5:]

            # Progressive disclosure for many entries
            if len(lines) > 5:
                await self.capability_worker.speak(
                    f"You have {len(lines)} entries total. Let me give you a summary."
                )
                try:
                    summary = self.capability_worker.text_to_text_response(
                        SUMMARIZE_PROMPT.format(entries="\n".join(lines))
                    )
                    await self.capability_worker.speak(summary)
                except Exception:
                    await self.capability_worker.speak(
                        f"You have {len(lines)} entries in your journal."
                    )
                more = await self.capability_worker.run_confirmation_loop(
                    "Want to hear the last five one by one?"
                )
                if not more:
                    return
                lines = lines[-5:]

            # Read entries with voice-friendly formatting
            entry_count = len(lines)
            if entry_count == 1:
                await self.capability_worker.speak("Here's your entry.")
            else:
                await self.capability_worker.speak(
                    f"Here are {entry_count} entries."
                )

            for line in lines:
                formatted = self._format_entry_for_speech(line)
                await self.capability_worker.speak(formatted)

        except Exception as e:
            self._log("error", f"Read error: {e}")
            await self.capability_worker.speak(
                "Sorry, I had trouble reading your entries."
            )

    async def _handle_search(self):
        """Search journal entries by topic using LLM."""
        count = self.user_prefs.get("entry_count", 0)
        if count == 0:
            await self.capability_worker.speak(
                "Your journal is empty. Nothing to search yet."
            )
            return

        query = await self.capability_worker.run_io_loop(
            "What would you like to search for?"
        )
        if not query or not query.strip():
            await self.capability_worker.speak("I didn't catch a search term.")
            return

        if any(w in query.lower() for w in EXIT_WORDS):
            return

        await self.capability_worker.speak("Let me search through your entries.")

        try:
            exists = await self.capability_worker.check_if_file_exists(
                ENTRIES_FILE, False
            )
            if not exists:
                await self.capability_worker.speak("No entries found.")
                return

            raw = await self.capability_worker.read_file(ENTRIES_FILE, False)
            result = self.capability_worker.text_to_text_response(
                SEARCH_PROMPT.format(query=query, entries=raw)
            )
            await self.capability_worker.speak(result)
        except Exception as e:
            self._log("error", f"Search error: {e}")
            await self.capability_worker.speak(
                "Sorry, I had trouble searching your entries."
            )

    async def _handle_delete(self):
        """Delete a single entry or all entries."""
        count = self.user_prefs.get("entry_count", 0)
        if count == 0:
            await self.capability_worker.speak("Your journal is already empty.")
            return

        choice = await self.capability_worker.run_io_loop(
            "Do you want to delete a specific entry or everything?"
        )

        if not choice or not choice.strip():
            await self.capability_worker.speak("I didn't catch that.")
            return

        if any(w in choice.lower() for w in EXIT_WORDS):
            return

        lower_choice = choice.lower()

        if any(w in lower_choice for w in ("all", "everything", "entire", "whole")):
            await self._delete_all()
        else:
            await self._delete_single()

    async def _delete_all(self):
        """Delete all journal entries after confirmation."""
        count = self.user_prefs.get("entry_count", 0)
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"This will permanently delete all {count} entries. Are you sure?"
        )

        if not confirmed:
            await self.capability_worker.speak("Okay, your entries are safe.")
            return

        await self.capability_worker.speak("Clearing your journal now.")
        try:
            exists = await self.capability_worker.check_if_file_exists(
                ENTRIES_FILE, False
            )
            if exists:
                await self.capability_worker.delete_file(ENTRIES_FILE, False)
            self.user_prefs["entry_count"] = 0
            await self._save_prefs()
            await self.capability_worker.speak(
                "Done. Your journal has been cleared."
            )
        except Exception as e:
            self._log("error", f"Delete error: {e}")
            await self.capability_worker.speak(
                "Sorry, I had trouble clearing your journal."
            )

    async def _pick_entry_by_number(self, lines, action_verb):
        """Show paginated entries and let user pick one by number.

        Returns (actual_index, lines) or (None, lines) if cancelled.
        """
        page = 0
        max_page = (len(lines) - 1) // PAGE_SIZE

        while True:
            # Calculate page slice (most recent first)
            end = len(lines) - (page * PAGE_SIZE)
            start = max(0, end - PAGE_SIZE)
            display_lines = lines[start:end]

            parts = []
            for i, line in enumerate(display_lines, 1):
                formatted = self._format_entry_for_speech(line)
                parts.append(f"Number {i}: {formatted}")

            if page == 0:
                header = "Here are your recent entries. "
            else:
                header = "Here are older entries. "
            await self.capability_worker.speak(header + " ".join(parts))

            # Build prompt
            prompt = f"Which number do you want to {action_verb}?"
            nav_hints = []
            if page < max_page:
                nav_hints.append("'older' for previous")
            if page > 0:
                nav_hints.append("'newer' for recent")
            if nav_hints:
                prompt += " Or say " + " or ".join(nav_hints) + " entries."
            choice_raw = await self.capability_worker.run_io_loop(prompt)

            if not choice_raw or not choice_raw.strip():
                await self.capability_worker.speak("I didn't catch that.")
                return None, lines
            if any(w in choice_raw.lower() for w in EXIT_WORDS):
                return None, lines

            # Check for pagination request
            lower_choice = choice_raw.lower()
            if any(w in lower_choice for w in OLDER_KEYWORDS):
                if page < max_page:
                    page += 1
                    continue
                else:
                    await self.capability_worker.speak(
                        "No more older entries. Pick a number from the list."
                    )
                    continue

            if any(w in lower_choice for w in NEWER_KEYWORDS):
                if page > 0:
                    page -= 1
                    continue
                else:
                    await self.capability_worker.speak(
                        "You're already on the most recent entries. "
                        "Pick a number from the list."
                    )
                    continue

            # Extract number via LLM
            try:
                num_str = self.capability_worker.text_to_text_response(
                    EXTRACT_NUMBER_PROMPT.format(raw=choice_raw)
                )
                num = int(num_str.strip())
            except (ValueError, Exception):
                await self.capability_worker.speak(
                    "I couldn't figure out which entry you meant."
                )
                return None, lines

            if num < 1 or num > len(display_lines):
                await self.capability_worker.speak(
                    f"Please pick a number between 1 and {len(display_lines)}."
                )
                return None, lines

            actual_idx = start + (num - 1)
            return actual_idx, lines

    async def _delete_single(self):
        """Delete a single entry by number selection."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                ENTRIES_FILE, False
            )
            if not exists:
                await self.capability_worker.speak("No entries found.")
                self.user_prefs["entry_count"] = 0
                await self._save_prefs()
                return

            raw = await self.capability_worker.read_file(ENTRIES_FILE, False)
            lines = [ln.strip() for ln in raw.strip().split("\n") if ln.strip()]

            if not lines:
                await self.capability_worker.speak("No entries found.")
                self.user_prefs["entry_count"] = 0
                await self._save_prefs()
                return

            actual_idx, lines = await self._pick_entry_by_number(
                lines, "delete"
            )
            if actual_idx is None:
                return

            old_line = lines[actual_idx]
            formatted_old = self._format_entry_for_speech(old_line)

            confirmed = await self.capability_worker.run_confirmation_loop(
                f"Delete this entry? {formatted_old}"
            )
            if not confirmed:
                await self.capability_worker.speak("Okay, kept that entry.")
                return

            # Remove the line and rewrite file
            lines.pop(actual_idx)
            await self.capability_worker.delete_file(ENTRIES_FILE, False)
            if lines:
                full_content = "\n".join(lines)
                await self.capability_worker.write_file(
                    ENTRIES_FILE, full_content, False
                )
            self.user_prefs["entry_count"] = len(lines)
            await self._save_prefs()
            await self.capability_worker.speak("Done! Entry deleted.")

        except Exception as e:
            self._log("error", f"Delete error: {e}")
            await self.capability_worker.speak(
                "Sorry, I had trouble deleting that entry."
            )

    async def _handle_edit(self):
        """Edit an existing entry by number selection."""
        count = self.user_prefs.get("entry_count", 0)
        if count == 0:
            await self.capability_worker.speak(
                "Your journal is empty. Nothing to edit."
            )
            return

        try:
            exists = await self.capability_worker.check_if_file_exists(
                ENTRIES_FILE, False
            )
            if not exists:
                await self.capability_worker.speak("No entries found.")
                self.user_prefs["entry_count"] = 0
                await self._save_prefs()
                return

            raw = await self.capability_worker.read_file(ENTRIES_FILE, False)
            lines = [ln.strip() for ln in raw.strip().split("\n") if ln.strip()]

            if not lines:
                await self.capability_worker.speak("No entries found.")
                self.user_prefs["entry_count"] = 0
                await self._save_prefs()
                return

            actual_idx, lines = await self._pick_entry_by_number(
                lines, "edit"
            )
            if actual_idx is None:
                return

            old_line = lines[actual_idx]

            # Extract original timestamp
            original_timestamp = ""
            if " | " in old_line:
                original_timestamp = old_line.split(" | ", 1)[0].strip()

            # Ask for new content
            new_raw = await self.capability_worker.run_io_loop(
                "What should this entry say now?"
            )
            if not new_raw or not new_raw.strip():
                await self.capability_worker.speak("I didn't catch that.")
                return
            if any(w in new_raw.lower() for w in EXIT_WORDS):
                return

            # LLM clean
            await self.capability_worker.speak(random.choice(FILLER_CLEANING))
            try:
                cleaned = self.capability_worker.text_to_text_response(
                    CLEAN_ENTRY_PROMPT.format(raw=new_raw)
                )
                cleaned = cleaned.strip().strip('"').strip("'")
                if not cleaned:
                    cleaned = new_raw.strip()
            except Exception:
                cleaned = new_raw.strip()

            # Read back and confirm
            await self.capability_worker.speak(f'Here\'s the updated entry: "{cleaned}"')
            confirmed = await self.capability_worker.run_confirmation_loop(
                "Should I save this change?"
            )
            if not confirmed:
                await self.capability_worker.speak("No problem, kept the original.")
                return

            # Replace line preserving original timestamp
            if original_timestamp:
                new_line = f"{original_timestamp} | {cleaned}"
            else:
                new_line = cleaned
            lines[actual_idx] = new_line

            # Delete file and rewrite (append-only API)
            await self.capability_worker.speak(random.choice(FILLER_EDITING))
            await self.capability_worker.delete_file(ENTRIES_FILE, False)
            full_content = "\n".join(lines)
            await self.capability_worker.write_file(
                ENTRIES_FILE, full_content, False
            )
            await self.capability_worker.speak("Done! Entry updated.")

        except Exception as e:
            self._log("error", f"Edit error: {e}")
            await self.capability_worker.speak(
                "Sorry, I had trouble editing that entry."
            )

    async def _handle_help(self):
        """Speak available commands."""
        await self.capability_worker.speak(
            "You can say: add an entry, read my entries, search for "
            "something, edit an entry, or delete an entry or everything. "
            "Say done to leave."
        )

    # -------------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------------

    async def run(self):
        """Main entry point for the ability."""
        try:
            await self.boot()

            # Check trigger context for immediate intent
            initial_intent = ""
            inline_entry = ""
            if self.initial_request:
                initial_intent = self._classify_intent(self.initial_request)
                if initial_intent == "add":
                    inline_entry = self._extract_inline_entry(
                        self.initial_request
                    )

            # Route initial intent
            if initial_intent == "add":
                await self._handle_add(inline_entry)
            elif initial_intent == "read":
                await self._handle_read()
            elif initial_intent == "search":
                await self._handle_search()
            elif initial_intent == "edit":
                await self._handle_edit()
            elif initial_intent == "delete":
                await self._handle_delete()
            elif initial_intent == "help":
                await self._handle_help()
            elif initial_intent == "exit":
                await self._sign_off()
                return
            else:
                # No clear intent from trigger — prompt the user
                await self.capability_worker.speak(
                    "Would you like to add a new entry, edit one, or hear past ones?"
                )

            # Main conversation loop
            for _ in range(MAX_TURNS):
                user_input = await self.capability_worker.user_response()

                # Empty input / idle handling
                if not user_input or not user_input.strip():
                    self.idle_count += 1
                    if self.idle_count >= 2:
                        await self.capability_worker.speak(
                            "Seems like you're all set. I'll close your journal."
                        )
                        break
                    else:
                        await self.capability_worker.speak(
                            "I'm listening. What would you like to do?"
                        )
                        continue
                else:
                    self.idle_count = 0

                # Classify and route
                intent = self._classify_intent(user_input)

                if intent == "exit":
                    break
                elif intent == "add":
                    inline = self._extract_inline_entry(user_input)
                    await self._handle_add(inline)
                elif intent == "read":
                    await self._handle_read()
                elif intent == "search":
                    await self._handle_search()
                elif intent == "edit":
                    await self._handle_edit()
                elif intent == "delete":
                    await self._handle_delete()
                elif intent == "help":
                    await self._handle_help()
                else:
                    # Unknown intent — try to be helpful
                    await self.capability_worker.speak(
                        "I can add entries, read them, search, edit, "
                        "or delete. What would you like?"
                    )

            await self._sign_off()

        except Exception as e:
            self._log("error", f"Voice Journal error: {e}")
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Let's try again next time."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    async def _save_prefs(self):
        """Save user preferences (delete + write pattern for JSON)."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )
            if exists:
                await self.capability_worker.delete_file(PREFS_FILE, False)
            await self.capability_worker.write_file(
                PREFS_FILE, json.dumps(self.user_prefs), False
            )
        except Exception as e:
            self._log("error", f"Save prefs error: {e}")

    async def _sign_off(self):
        """Natural sign-off message."""
        name = self.user_prefs.get("name", "friend")
        count = self.user_prefs.get("entry_count", 0)
        if count > 0:
            await self.capability_worker.speak(
                f"Take care, {name}. Your journal will be here when you get back."
            )
        else:
            await self.capability_worker.speak(
                f"See you next time, {name}."
            )

    def _format_entry_for_speech(self, entry_line: str) -> str:
        """Convert 'YYYY-MM-DD HH:MM | text' to voice-friendly format."""
        try:
            if " | " not in entry_line:
                return entry_line
            timestamp_str, text = entry_line.split(" | ", 1)
            dt = datetime.strptime(timestamp_str.strip(), "%Y-%m-%d %H:%M")
            month = dt.strftime("%B")
            day = dt.day
            hour = dt.strftime("%I:%M %p").lstrip("0")
            return f"On {month} {day} at {hour}: {text}"
        except (ValueError, IndexError):
            return entry_line

    def _log(self, level: str, msg: str):
        """Log using the platform logger."""
        try:
            handler = self.worker.editor_logging_handler
            if level == "error":
                handler.error(f"[VoiceJournal] {msg}")
            elif level == "warning":
                handler.warning(f"[VoiceJournal] {msg}")
            else:
                handler.info(f"[VoiceJournal] {msg}")
        except Exception:
            pass  # Logging should never crash the ability
