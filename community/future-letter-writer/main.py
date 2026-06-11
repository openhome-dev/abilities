import json
import random
import re
from datetime import datetime, timedelta

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
    "The user wants to set a delivery date for a letter to their future self.\n"
    "They said: '{raw}'\n"
    "Today's date is {today}.\n"
    "Parse their response into a delivery date. Handle natural language like:\n"
    "- 'in a month' → one month from today\n"
    "- 'next year' → one year from today\n"
    "- 'in 6 months' → six months from today\n"
    "- 'on my birthday December 15' → next December 15\n"
    "- 'January 2027' → January 1, 2027\n"
    "- 'in a week' → 7 days from today\n"
    "Return ONLY a JSON object: {{\"date\": \"YYYY-MM-DD\", \"human\": \"readable description\"}}\n"
    "If you cannot parse a date, return: {{\"date\": \"\", \"human\": \"\"}}"
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


class FutureLetterWriterCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.letters = []
        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            await self._boot()

            turn = 0
            while turn < MAX_TURNS:
                turn += 1
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    continue

                intent = self._classify_intent(user_input)

                if intent == "record":
                    await self._handle_record()
                elif intent == "list":
                    await self._handle_list()
                elif intent == "delete":
                    await self._handle_delete()
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
                    nearest = min(pending, key=lambda letter: letter.get("deliver_date", ""))
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
            deliver_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
            deliver_human = "about a month from now"
        elif self._is_exit_command(date_input):
            return
        else:
            # Parse date via LLM
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                raw = self.capability_worker.text_to_text_response(
                    PARSE_DATE_PROMPT.format(raw=date_input, today=today)
                )
                clean = raw.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(clean)
                deliver_date = parsed.get("date", "")
                deliver_human = parsed.get("human", "")

                if not deliver_date:
                    deliver_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
                    deliver_human = "about a month from now"
            except Exception:
                deliver_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
                deliver_human = "about a month from now"

        # Save the letter
        letter = {
            "id": f"letter_{int(datetime.now().timestamp())}",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "message": cleaned,
            "deliver_date": deliver_date,
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
