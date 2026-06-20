import json
import random

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# SPELLING BEE COACH
# An interactive spelling practice ability with spaced repetition,
# difficulty levels, and persistent progress tracking across sessions.
#
# Pattern: Greet → Choose mode → Quiz loop → Score → Exit
# =============================================================================

PROGRESS_FILE = "spelling_bee_progress.json"

MAX_TURNS = 30

# Speak a brief score update every N words (statement only, never a question).
SCORE_UPDATE_EVERY = 10

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "bye", "goodbye",
    "leave", "cancel", "nothing else", "no thanks",
    "i'm good", "im good", "nah",
}

# Difficulty-tiered word lists
WORDS_EASY = [
    "apple", "house", "water", "happy", "green", "light", "music",
    "river", "beach", "cloud", "table", "chair", "smile", "dance",
    "friend", "school", "garden", "purple", "orange", "silver",
]
WORDS_MEDIUM = [
    "beautiful", "necessary", "calendar", "separate", "different",
    "tomorrow", "surprise", "elephant", "chocolate", "adventure",
    "dinosaur", "invisible", "fantastic", "wonderful", "important",
    "dangerous", "hurricane", "passenger", "structure", "celebrate",
]
WORDS_HARD = [
    "accommodate", "bureaucracy", "conscientious", "entrepreneur",
    "hemorrhage", "mischievous", "occasionally", "questionnaire",
    "reconnaissance", "surveillance", "onomatopoeia", "Mediterranean",
    "bibliography", "chrysanthemum", "fluorescent", "kaleidoscope",
    "phenomenon", "pneumonia", "pseudonym", "silhouette",
]

DIFFICULTY_MAP = {
    "easy": WORDS_EASY,
    "medium": WORDS_MEDIUM,
    "hard": WORDS_HARD,
}

GENERATE_WORD_PROMPT = (
    "Generate a single {difficulty}-level English vocabulary word for a "
    "spelling bee practice session. The word should NOT be any of these: {exclude}. "
    "Return ONLY the word, nothing else."
)

# Correct answers in a row required to retire a word as "mastered"
MASTERY_STREAK = 3

# Cap on how many "weak" words to keep, so the stored list can't grow forever.
# Keeps the most recent misses for spaced repetition.
MAX_WEAK_WORDS = 100

# Exact (normalized) utterances that mean "say the word again"
REPEAT_PHRASES = {
    "repeat", "again", "what", "repeat that", "say it again",
    "say that again", "one more time", "come again",
}

DEFINITION_PROMPT = (
    'Give a short, clear definition of the word "{word}" in ONE sentence. '
    "Format for voice readback. Return ONLY the definition, nothing else."
)

INTERPRET_SPELLING_PROMPT = (
    'The user is in a spelling quiz. The current word is "{word}".\n'
    "Their spoken response was: '{raw}'\n"
    "Classify their intent and return ONLY JSON:\n"
    '{{"intent": "spell|stop|repeat|skip", "letters": "<letters if spelling, else empty>"}}\n'
    "- spell: they tried to spell the word (letter names, or said the word itself). "
    "Extract the letters as a single lowercase word, handling phonetic letter names "
    "('ay'=a, 'bee'=b, 'see'=c, 'double-u'=w, 'ex'=x, 'why'=y, 'zee/zed'=z).\n"
    "- stop: they want to end the session (e.g. 'done', 'stop', 'no', 'nope', "
    "'I don't want to continue', 'that's enough').\n"
    "- repeat: they want to hear the word again.\n"
    "- skip: they want to skip this word and move on."
)


class SpellingbeecoachCapability(MatchingCapability):
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
        self.progress = {"total_correct": 0, "total_attempted": 0, "mastered": [], "weak": []}
        self.session_correct = 0
        self.session_total = 0
        self.current_difficulty = "medium"
        self.session_missed = []
        try:
            await self._boot()

            await self.capability_worker.speak(
                "What difficulty would you like? Easy, medium, or hard?"
            )
            diff_input = await self.capability_worker.user_response()

            if diff_input and diff_input.strip():
                lower = diff_input.lower().strip()
                if "easy" in lower:
                    self.current_difficulty = "easy"
                elif "hard" in lower:
                    self.current_difficulty = "hard"
                else:
                    self.current_difficulty = "medium"

                if any(w in lower for w in EXIT_WORDS):
                    await self._sign_off()
                    return

            await self.capability_worker.speak(
                f"Great, {self.current_difficulty} mode. Let's begin! "
                "I'll give you a word, you spell it out loud. Say done to stop."
            )

            round_num = 0
            idle = 0
            while round_num < MAX_TURNS:
                round_num += 1

                # Pick a word (prioritize weak words for spaced repetition)
                word = self._pick_word()
                await self._present_word(word)

                user_input = await self.capability_worker.user_response()

                # No response — nudge, then bail after two silent turns.
                if not user_input or not user_input.strip():
                    idle += 1
                    if idle >= 2:
                        break
                    await self.capability_worker.speak(
                        f"I didn't catch that. The word was {word}. "
                        "Spell it, or say done to stop."
                    )
                    continue
                idle = 0

                # Fast-path explicit stop before any LLM work.
                if self._is_stop(user_input):
                    break

                # Figure out what they meant: spell, stop, repeat, or skip.
                intent, letters = self._interpret_response(word, user_input)

                if intent == "stop":
                    break
                if intent == "skip":
                    await self.capability_worker.speak("No problem, let's move on.")
                    continue
                if intent == "repeat":
                    await self.capability_worker.speak(
                        f"The word is: {word}. Now spell it."
                    )
                    user_input = await self.capability_worker.user_response()
                    if not user_input or self._is_stop(user_input):
                        break
                    intent, letters = self._interpret_response(word, user_input)
                    if intent != "spell":
                        continue

                # Score the spelling.
                cleaned = letters.strip().lower().replace(" ", "").replace("-", "")
                direct = user_input.strip().lower().replace(" ", "").replace("-", "")
                is_correct = cleaned == word.lower() or direct == word.lower()

                self.session_total += 1
                self.progress["total_attempted"] += 1

                if is_correct:
                    self.session_correct += 1
                    self.progress["total_correct"] += 1
                    self._mark_correct(word)
                    praise = random.choice([
                        "Correct!", "Nailed it!", "Perfect!", "You got it!",
                        "Spot on!", "That's right!", "Well done!",
                    ])
                    await self.capability_worker.speak(f"{praise} Here's the next one.")
                else:
                    self._mark_wrong(word)
                    if word not in self.session_missed:
                        self.session_missed.append(word)
                    spelled_out = ", ".join(list(word.upper()))
                    await self.capability_worker.speak(
                        f"Not quite — {word} is spelled {spelled_out}. Let's try another."
                    )

                # Brief score update every SCORE_UPDATE_EVERY words — just a
                # statement, no prompt. The user can stop any time by saying so.
                if self.session_total > 0 and self.session_total % SCORE_UPDATE_EVERY == 0:
                    pct = round(self.session_correct / self.session_total * 100)
                    await self.capability_worker.speak(
                        f"Nice — {self.session_correct} out of {self.session_total} so far, "
                        f"{pct} percent."
                    )

            await self._sign_off()

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SpellingBee] Error: {e}"
            )
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Let me hand you back."
                )
            except Exception:
                pass
        finally:
            await self._save_progress()
            self.capability_worker.resume_normal_flow()

    # -------------------------------------------------------------------------
    # Boot & Persistence
    # -------------------------------------------------------------------------

    async def _boot(self):
        """Load saved progress."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PROGRESS_FILE, False
            )
            if exists:
                raw = await self.capability_worker.read_file(PROGRESS_FILE, False)
                self.progress = json.loads(raw)
                total = self.progress.get("total_attempted", 0)
                correct = self.progress.get("total_correct", 0)
                mastered = len(self.progress.get("mastered", []))

                if total > 0:
                    pct = round(correct / total * 100)
                    await self.capability_worker.speak(
                        f"Welcome back to Spelling Bee! You've practiced "
                        f"{total} words with {pct} percent accuracy. "
                        f"{mastered} words mastered."
                    )
                else:
                    await self.capability_worker.speak(
                        "Welcome back to Spelling Bee! Ready to practice?"
                    )
            else:
                await self.capability_worker.speak(
                    "Welcome to Spelling Bee Coach! I'll give you words to "
                    "spell, track your progress, and focus on the ones you "
                    "find tricky."
                )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SpellingBee] Boot error: {e}"
            )
            await self.capability_worker.speak(
                "Welcome to Spelling Bee Coach! Let's practice some words."
            )

    async def _save_progress(self):
        """Persist progress (delete + write for JSON)."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PROGRESS_FILE, False
            )
            if exists:
                await self.capability_worker.delete_file(PROGRESS_FILE, False)
            await self.capability_worker.write_file(
                PROGRESS_FILE, json.dumps(self.progress), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SpellingBee] Save error: {e}"
            )

    # -------------------------------------------------------------------------
    # Word Selection (Spaced Repetition)
    # -------------------------------------------------------------------------

    def _pick_word(self):
        """Pick a word, prioritizing weak words for spaced repetition."""
        weak = self.progress.get("weak", [])
        mastered = set(self.progress.get("mastered", []))
        word_list = DIFFICULTY_MAP.get(self.current_difficulty, WORDS_MEDIUM)

        # 40% chance to revisit a weak word — but only ones from the chosen
        # difficulty, so easy/medium never surfaces a word from the hard list.
        weak_in_level = [w for w in weak if w in word_list]
        if weak_in_level and random.random() < 0.4:
            return random.choice(weak_in_level)

        # Filter out mastered words
        available = [w for w in word_list if w not in mastered]
        if not available:
            # All built-in words mastered — generate a fresh word via LLM
            generated = self._generate_word(mastered)
            if generated:
                return generated
            available = word_list  # Fallback: recycle the built-in list

        return random.choice(available)

    def _generate_word(self, exclude):
        """Generate a new practice word once the built-in list is mastered."""
        try:
            raw = self.capability_worker.text_to_text_response(
                GENERATE_WORD_PROMPT.format(
                    difficulty=self.current_difficulty,
                    exclude=", ".join(sorted(exclude)),
                )
            )
            word = raw.strip().strip(".\"'").lower()
            if word and word.isalpha() and word not in exclude:
                return word
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SpellingBee] Word generation error: {e}"
            )
        return None

    def _mark_correct(self, word):
        """Track correct answer. Mastered after MASTERY_STREAK correct in a row."""
        weak = self.progress.get("weak", [])
        mastered = self.progress.get("mastered", [])
        streaks = self.progress.get("streaks", {})

        if word in weak:
            weak.remove(word)

        streaks[word] = streaks.get(word, 0) + 1
        if streaks[word] >= MASTERY_STREAK and word not in mastered:
            mastered.append(word)

        self.progress["weak"] = weak
        self.progress["mastered"] = mastered
        self.progress["streaks"] = streaks

    def _mark_wrong(self, word):
        """Track wrong answer. Add to weak words and reset its mastery streak."""
        weak = self.progress.get("weak", [])
        mastered = self.progress.get("mastered", [])
        streaks = self.progress.get("streaks", {})

        streaks[word] = 0
        if word not in weak:
            weak.append(word)
        # Keep only the most recent misses so the list stays bounded.
        weak = weak[-MAX_WEAK_WORDS:]
        if word in mastered:
            mastered.remove(word)

        self.progress["weak"] = weak
        self.progress["mastered"] = mastered
        self.progress["streaks"] = streaks

    # -------------------------------------------------------------------------
    # Word Presentation & Checking
    # -------------------------------------------------------------------------

    async def _present_word(self, word):
        """Say the word with its explanation, then prompt the user to spell it."""
        # Fetch the definition first so word and explanation flow back-to-back.
        try:
            definition = self.capability_worker.text_to_text_response(
                DEFINITION_PROMPT.format(word=word)
            )
        except Exception:
            definition = ""

        intro = f"Your word is: {word}."
        if definition:
            intro = f"{intro} {definition}"
        await self.capability_worker.speak(intro)
        await self.capability_worker.speak("Now, spell it. Say the letters out loud.")

    def _is_stop(self, text):
        """True for short, explicit stop/exit utterances (fast keyword path)."""
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

    def _interpret_response(self, word, raw):
        """Classify a quiz response as spell/stop/repeat/skip, with letters
        extracted for spelling attempts. Returns (intent, letters)."""
        # Direct match — they said the word itself.
        direct = raw.strip().lower().replace(" ", "").replace("-", "")
        if direct == word.lower():
            return "spell", word.lower()

        try:
            out = self.capability_worker.text_to_text_response(
                INTERPRET_SPELLING_PROMPT.format(word=word, raw=raw)
            )
            data = json.loads(out.replace("```json", "").replace("```", "").strip())
            intent = data.get("intent", "spell")
            if intent not in ("spell", "stop", "repeat", "skip"):
                intent = "spell"
            return intent, str(data.get("letters", "") or "")
        except Exception:
            # Fallback: treat as a spelling attempt, extract letters directly.
            return "spell", "".join(c for c in raw.lower() if c.isalpha())

    # -------------------------------------------------------------------------
    # Sign-off
    # -------------------------------------------------------------------------

    async def _sign_off(self):
        """Summarize session and save."""
        if self.session_total > 0:
            pct = round(self.session_correct / self.session_total * 100)
            mastered = len(self.progress.get("mastered", []))
            result = (
                f"Session over! You got {self.session_correct} out of "
                f"{self.session_total} correct, {pct} percent, with "
                f"{mastered} word{'s' if mastered != 1 else ''} mastered."
            )
            # Only suggest words actually missed this session.
            if self.session_missed:
                result += f" Words to practice: {', '.join(self.session_missed[:3])}."
            await self.capability_worker.speak(result)
        else:
            await self.capability_worker.speak(
                "No worries, come back when you're ready to practice!"
            )

        # Offer a one-time reset before leaving (only if there's progress).
        if self.progress.get("total_attempted", 0) or self.progress.get("mastered"):
            do_reset = await self.capability_worker.run_confirmation_loop(
                "Before you go, want me to reset your progress?"
            )
            if do_reset:
                self.progress = {
                    "total_correct": 0, "total_attempted": 0,
                    "mastered": [], "weak": [], "streaks": {},
                }
                await self._save_progress()
                await self.capability_worker.speak("Done, progress reset. See you next time!")
                return

        await self.capability_worker.speak("See you next time!")
