import json
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# FUTURE LETTER WRITER — Interactive Skill (main.py)
# Record voice messages to your future self with a delivery date.
# The background daemon (background.py) handles delivery.
#
# Pattern: Greet → Record message → Set delivery date → Confirm → Save → Exit
# =============================================================================

LETTERS_FILE = "future_letters_data.json"

MAX_TURNS = 15

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "bye", "goodbye",
    "leave", "cancel", "nothing else", "no thanks",
    "i'm good", "im good", "nah",
}

RECORD_KEYWORDS = {"write", "record", "new", "create", "send", "leave", "make"}
LIST_KEYWORDS = {"list", "show", "how many", "pending", "check", "what letters"}
DELETE_KEYWORDS = {"delete", "remove", "cancel letter"}

PARSE_DATE_PROMPT = (
    "The user wants to schedule delivery of a letter to their future self.\n"
    "They said: '{raw}'\n"
    "The current date and time is {now} (timezone {tz}).\n"
    "Parse their response into a delivery date AND time. Handle natural language like:\n"
    "- 'in 10 minutes' → 10 minutes from now\n"
    "- 'in 2 hours' → two hours from now\n"
    "- 'tonight at 8pm' → today at 20:00\n"
    "- 'tomorrow morning' → tomorrow at 09:00\n"
    "- 'in a week' → 7 days from now, same time\n"
    "- 'in 6 months' / 'next year' → that far out, same time of day\n"
    "- 'on my birthday December 15' → next December 15 at 09:00\n"
    "Compute everything relative to the current date and time given above. "
    "If no time of day is specified, default to 09:00. Use 24-hour time.\n"
    "Return ONLY a JSON object: {{\"datetime\": \"YYYY-MM-DD HH:MM\", \"human\": \"readable description\"}}\n"
    "If you cannot parse it, return: {{\"datetime\": \"\", \"human\": \"\"}}"
)

CLEAN_LETTER_PROMPT = (
    "The user dictated a letter to their future self by voice. "
    "Clean it up — fix grammar, remove filler words (um, uh, like), "
    "keep the original meaning, tone, and emotion. "
    "This is a personal message, so preserve their voice.\n"
    "Return ONLY the cleaned letter text.\n\n"
    "Raw: {raw}"
)

INTENT_PROMPT = (
    "Classify this input: record, list, delete, exit, unknown.\n"
    "Context: future letter writer — record messages to future self, "
    "list pending letters, delete letters, or exit.\n"
    "Return ONLY one word.\n"
    "Input: {text}"
)

PROMPTS = [
    "What would you tell yourself six months from now?",
    "What do you want to remember about this moment?",
    "What are you hopeful about right now?",
    "What have you learned recently that you don't want to forget?",
    "What would you want your future self to know about today?",
]


class FutureLettersCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------------

    async def run(self):
        self.letters = []
        self._tz = None
        try:
            await self._boot()

            turn = 0
            idle = 0
            while turn < MAX_TURNS:
                turn += 1
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle += 1
                    if idle >= 2:
                        break
                    await self.capability_worker.speak(
                        "I'm still here. Say 'write a letter', 'check my letters', or done."
                    )
                    continue
                idle = 0

                intent = self._classify_intent(user_input)

                if intent == "record":
                    await self._handle_record()
                elif intent == "list":
                    await self._handle_list()
                    await self.capability_worker.speak(
                        "Write a letter, check your letters, or say done."
                    )
                elif intent == "delete":
                    await self._handle_delete()
                    await self.capability_worker.speak(
                        "Write a letter, check your letters, or say done."
                    )
                elif intent == "exit":
                    break
                else:
                    # Default to recording a new letter
                    await self._handle_record()

            pending = len([letter for letter in self.letters if letter.get("status") == "pending"])
            if pending > 0:
                await self.capability_worker.speak(
                    f"You have {pending} letter{'s' if pending != 1 else ''} "
                    "waiting for your future self. See you next time."
                )
            else:
                await self.capability_worker.speak(
                    "See you next time. Your future self will thank you."
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[FutureLetterWriter] Error: {e}"
            )
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Let me hand you back."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # -------------------------------------------------------------------------
    # Boot & Persistence
    # -------------------------------------------------------------------------

    async def _boot(self):
        """Load existing letters."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                LETTERS_FILE, False
            )
            if exists:
                raw = await self.capability_worker.read_file(LETTERS_FILE, False)
                self.letters = json.loads(raw)

                pending = [letter for letter in self.letters if letter.get("status") == "pending"]

                if pending:
                    nearest = min(pending, key=lambda letter: letter.get("deliver_at", ""))
                    await self.capability_worker.speak(
                        f"Welcome back to Future Letters. "
                        f"You have {len(pending)} letter{'s' if len(pending) != 1 else ''} "
                        f"waiting. The next one arrives {nearest.get('deliver_human', 'soon')}."
                    )
                else:
                    await self.capability_worker.speak(
                        "Welcome back to Future Letters. No letters pending. "
                        "Want to write one?"
                    )
            else:
                await self.capability_worker.speak(
                    "Welcome to Future Letters! Record a message to your "
                    "future self — I'll deliver it on the date you choose. "
                    "It's like a time capsule, but with your voice."
                )

            await self.capability_worker.speak(
                "Say 'write a letter', 'check my letters', or done to leave."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[FutureLetterWriter] Boot error: {e}"
            )
            await self.capability_worker.speak(
                "Welcome to Future Letters! Let's write to your future self."
            )

    async def _save_letters(self):
        """Persist letters (delete + write for JSON)."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                LETTERS_FILE, False
            )
            if exists:
                await self.capability_worker.delete_file(LETTERS_FILE, False)
            await self.capability_worker.write_file(
                LETTERS_FILE, json.dumps(self.letters), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[FutureLetterWriter] Save error: {e}"
            )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _now(self):
        """Current time in the user's timezone, falling back to server time.

        Resolves the timezone once per session and logs what was captured.
        """
        if self._tz is None:
            try:
                self._tz = self.capability_worker.get_timezone() or ""
                if self._tz:
                    self.worker.editor_logging_handler.info(
                        f"[FutureLetterWriter] Captured user timezone: {self._tz} "
                        f"(local time {datetime.now(ZoneInfo(self._tz)).strftime('%Y-%m-%d %H:%M %Z')})"
                    )
                else:
                    self.worker.editor_logging_handler.info(
                        "[FutureLetterWriter] No user timezone available; using server time."
                    )
            except Exception as e:
                self._tz = ""
                self.worker.editor_logging_handler.error(
                    f"[FutureLetterWriter] Timezone lookup failed, using server time: {e}"
                )
        if self._tz:
            try:
                return datetime.now(ZoneInfo(self._tz))
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[FutureLetterWriter] Invalid timezone '{self._tz}', using server time: {e}"
                )
        return datetime.now()

    # -------------------------------------------------------------------------
    # Intent Detection
    # -------------------------------------------------------------------------

    def _is_exit_command(self, text):
        """True only for short, explicit exit utterances ("done", "stop now").

        Deliberately strict so free-form content — like a dictated letter
        that happens to contain "quit" or "done" — is never treated as exit.
        """
        if not text:
            return False
        normalized = text.lower().strip().strip(".!?,")
        if normalized in EXIT_WORDS:
            return True
        words = [w.strip(".!?,") for w in normalized.split()]
        if len(words) <= 4:
            if any(w in EXIT_WORDS for w in words):
                return True
            if any(p in normalized for p in EXIT_WORDS if " " in p):
                return True
        return False

    def _classify_intent(self, text):
        if not text:
            return "unknown"
        lower = text.lower().strip()

        # Delete before exit, so "cancel letter" reaches the delete flow
        # instead of matching the "cancel" exit word.
        if any(w in lower for w in DELETE_KEYWORDS):
            return "delete"
        if self._is_exit_command(text):
            return "exit"
        if any(w in lower for w in LIST_KEYWORDS):
            return "list"
        if any(w in lower for w in RECORD_KEYWORDS):
            return "record"

        try:
            result = self.capability_worker.text_to_text_response(
                INTENT_PROMPT.format(text=text)
            )
            intent = result.strip().lower().rstrip(".")
            if intent in ("record", "list", "delete", "exit"):
                return intent
        except Exception:
            pass

        return "record"

    # -------------------------------------------------------------------------
    # Handlers
    # -------------------------------------------------------------------------

    async def _handle_record(self):
        """Record a new letter to future self."""
        # Offer a prompt for inspiration
        prompt = random.choice(PROMPTS)
        message = await self.capability_worker.run_io_loop(
            f"Here's something to think about: {prompt} "
            "Or just say whatever's on your mind."
        )

        if not message or not message.strip():
            await self.capability_worker.speak("I didn't catch that.")
            return
        # Only an explicit short utterance ("cancel", "stop") aborts here —
        # the letter body itself is free-form and may contain those words.
        if self._is_exit_command(message):
            await self.capability_worker.speak("No problem, cancelled.")
            return

        # Clean up the message
        await self.capability_worker.speak("Let me clean that up for you.")
        try:
            cleaned = self.capability_worker.text_to_text_response(
                CLEAN_LETTER_PROMPT.format(raw=message)
            )
            cleaned = cleaned.strip().strip('"').strip("'")
            if not cleaned:
                cleaned = message.strip()
        except Exception:
            cleaned = message.strip()

        # Read back
        await self.capability_worker.speak(f'Here\'s what you said: "{cleaned}"')
        confirmed = await self.capability_worker.run_confirmation_loop(
            "Sound good?"
        )
        if not confirmed:
            await self.capability_worker.speak("No problem, tossed it.")
            return

        # Get delivery date
        await self.capability_worker.speak(
            "When should I deliver this? You can say something like "
            "'in a month', 'next year', or a specific date."
        )
        date_input = await self.capability_worker.user_response()

        if not date_input or not date_input.strip():
            await self.capability_worker.speak(
                "I didn't catch a date. I'll set it for one month from now."
            )
            deliver_at = (self._now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
            deliver_human = "about a month from now"
            self.worker.editor_logging_handler.info(
                f"[FutureLetterWriter] No delivery time from user; defaulting to {deliver_at}."
            )
        elif self._is_exit_command(date_input):
            return
        else:
            # Parse delivery datetime via LLM
            try:
                now_dt = self._now()
                now_str = now_dt.strftime("%Y-%m-%d %H:%M")
                raw = self.capability_worker.text_to_text_response(
                    PARSE_DATE_PROMPT.format(
                        raw=date_input, now=now_str, tz=self._tz or "local time"
                    )
                )
                clean = raw.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(clean)
                deliver_human = parsed.get("human", "")

                # Validate: must be a real, zero-padded, future "YYYY-MM-DD HH:MM".
                # The daemon compares datetimes as strings, so a malformed or past
                # value would break delivery or fire immediately.
                valid_at = ""
                raw_at = parsed.get("datetime", "")
                if raw_at:
                    try:
                        dt = datetime.strptime(raw_at, "%Y-%m-%d %H:%M")
                        if dt > now_dt.replace(tzinfo=None):
                            valid_at = dt.strftime("%Y-%m-%d %H:%M")  # normalize
                    except ValueError:
                        valid_at = ""

                if valid_at:
                    deliver_at = valid_at
                    self.worker.editor_logging_handler.info(
                        f"[FutureLetterWriter] Parsed delivery time from '{date_input}' "
                        f"(now {now_str}) -> {deliver_at} ({deliver_human})."
                    )
                else:
                    deliver_at = (self._now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
                    deliver_human = "about a month from now"
                    self.worker.editor_logging_handler.info(
                        f"[FutureLetterWriter] Unusable datetime '{raw_at}' "
                        f"from '{date_input}'; defaulting to {deliver_at}."
                    )
            except Exception as e:
                deliver_at = (self._now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
                deliver_human = "about a month from now"
                self.worker.editor_logging_handler.error(
                    f"[FutureLetterWriter] Datetime parse error for '{date_input}', "
                    f"defaulting to {deliver_at}: {e}"
                )

        # Save the letter
        letter = {
            "id": f"letter_{int(self._now().timestamp())}",
            "created": self._now().strftime("%Y-%m-%d %H:%M"),
            "message": cleaned,
            "deliver_at": deliver_at,
            "deliver_human": deliver_human,
            "status": "pending",
        }
        self.letters.append(letter)
        await self._save_letters()

        await self.capability_worker.speak(
            f"Saved! Your letter will be delivered {deliver_human}. "
            "Your future self will hear it then."
        )
        await self.capability_worker.speak(
            "Write another, check your letters, or say done."
        )

    async def _handle_list(self):
        """List pending and delivered letters."""
        pending = [letter for letter in self.letters if letter.get("status") == "pending"]
        delivered = [letter for letter in self.letters if letter.get("status") == "delivered"]

        if not pending and not delivered:
            await self.capability_worker.speak(
                "No letters yet. Want to write one?"
            )
            return

        if pending:
            await self.capability_worker.speak(
                f"You have {len(pending)} pending letter{'s' if len(pending) != 1 else ''}."
            )
            for i, letter in enumerate(pending[:5], 1):
                preview = letter["message"][:80]
                await self.capability_worker.speak(
                    f"Letter {i}: arrives {letter.get('deliver_human', 'soon')}. "
                    f'Preview: "{preview}"'
                )

        if delivered:
            await self.capability_worker.speak(
                f"{len(delivered)} letter{'s' if len(delivered) != 1 else ''} "
                "already delivered."
            )

    async def _handle_delete(self):
        """Delete a pending letter."""
        pending = [letter for letter in self.letters if letter.get("status") == "pending"]

        if not pending:
            await self.capability_worker.speak("No pending letters to delete.")
            return

        if len(pending) == 1:
            preview = pending[0]["message"][:60]
            confirmed = await self.capability_worker.run_confirmation_loop(
                f'Delete your letter arriving {pending[0].get("deliver_human", "soon")}? '
                f'It says: "{preview}"'
            )
            if confirmed:
                self.letters = [
                    letter for letter in self.letters if letter["id"] != pending[0]["id"]
                ]
                await self._save_letters()
                await self.capability_worker.speak("Deleted.")
            else:
                await self.capability_worker.speak("Keeping it.")
        else:
            await self.capability_worker.speak(
                f"You have {len(pending)} pending letters. "
                "Which one — first, second, or all?"
            )
            response = await self.capability_worker.user_response()
            if not response or not response.strip():
                await self.capability_worker.speak("I didn't catch that.")
                return
            if self._is_exit_command(response):
                return

            lower_resp = response.lower()
            if "all" in lower_resp:
                confirmed = await self.capability_worker.run_confirmation_loop(
                    "Delete all pending letters? This can't be undone."
                )
                if confirmed:
                    self.letters = [
                        letter for letter in self.letters if letter.get("status") != "pending"
                    ]
                    await self._save_letters()
                    await self.capability_worker.speak("All pending letters deleted.")
            else:
                # Parse which letter by number
                number_map = {
                    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                }
                idx = None
                for word, num in number_map.items():
                    if word in lower_resp:
                        idx = num
                        break
                if idx is None:
                    match = re.search(r"(\d+)", response)
                    if match:
                        idx = int(match.group(1))

                if idx is None or idx < 1 or idx > len(pending):
                    await self.capability_worker.speak(
                        f"Please say first, second, or a number between 1 and {len(pending)}."
                    )
                    return

                target = pending[idx - 1]
                preview = target["message"][:60]
                confirmed = await self.capability_worker.run_confirmation_loop(
                    f'Delete letter {idx} arriving {target.get("deliver_human", "soon")}? '
                    f'It says: "{preview}"'
                )
                if confirmed:
                    self.letters = [
                        letter for letter in self.letters if letter["id"] != target["id"]
                    ]
                    await self._save_letters()
                    await self.capability_worker.speak("Deleted.")
                else:
                    await self.capability_worker.speak("Keeping it.")
