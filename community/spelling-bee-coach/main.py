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

# Exact (normalized) utterances that mean "say the word again"
REPEAT_PHRASES = {
    "repeat", "again", "what", "repeat that", "say it again",
    "say that again", "one more time", "come again",
}

DEFINITION_PROMPT = (
    'Give a short, clear definition of the word "{word}" in ONE sentence. '
    "Format for voice readback. Return ONLY the definition, nothing else."
)

EXTRACT_SPELLING_PROMPT = (
    "The user tried to spell a word by voice. Their response was: '{raw}'\n"
    "Extract ONLY the letters they spelled, as a single lowercase word with no "
    "spaces or punctuation. Handle phonetic letter names (e.g., 'ay' = 'a', "
    "'bee' = 'b', 'see' = 'c', 'double-u' = 'w', 'ex' = 'x', 'why' = 'y', 'zee/zed' = 'z'). "
    "Return ONLY the spelled word, nothing else."
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
            while round_num < MAX_TURNS:
                round_num += 1

                # Pick a word (prioritize weak words for spaced repetition)
                word = self._pick_word()

                # Give the word with definition
                await self._present_word(word)

                # Get spelling attempt
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak(
                        f"I didn't catch that. The word was {word}. "
                        "Let's try another one."
                    )
                    continue

                if any(w in user_input.lower() for w in EXIT_WORDS):
                    break

                # Check if they want the word repeated (exact short utterance,
                # so spelling attempts containing these substrings don't match)
                if user_input.lower().strip().strip(".!?,") in REPEAT_PHRASES:
                    await self.capability_worker.speak(f"The word is: {word}.")
                    user_input = await self.capability_worker.user_response()
                    if not user_input or any(w in user_input.lower() for w in EXIT_WORDS):
                        break

                # Extract and check spelling
                is_correct = await self._check_spelling(word, user_input)

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
                    await self.capability_worker.speak(praise)
                else:
                    self._mark_wrong(word)
                    spelled_out = ", ".join(list(word.upper()))
                    await self.capability_worker.speak(
                        f"Not quite. The correct spelling is: {spelled_out}. "
                        f"{word}. We'll practice that one again."
                    )

                # Progress update every 5 words
                if self.session_total > 0 and self.session_total % 5 == 0:
                    pct = round(self.session_correct / self.session_total * 100)
                    await self.capability_worker.speak(
                        f"Score check: {self.session_correct} out of "
                        f"{self.session_total}, that's {pct} percent. Keep going?"
                    )
                    response = await self.capability_worker.user_response()
                    if response and any(w in response.lower() for w in EXIT_WORDS):
                        break

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

        # 40% chance to revisit a weak word if any exist
        if weak and random.random() < 0.4:
            return random.choice(weak)

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

    async def _check_spelling(self, correct_word, user_input):
        """Check if the user spelled the word correctly using LLM extraction."""
        # First try direct comparison (user might type/say the word itself)
        cleaned_input = user_input.strip().lower().replace(" ", "").replace("-", "")
        if cleaned_input == correct_word.lower():
            return True

        # Use LLM to extract spelled letters from voice input
        try:
            extracted = self.capability_worker.text_to_text_response(
                EXTRACT_SPELLING_PROMPT.format(raw=user_input)
            )
            extracted_clean = extracted.strip().lower().replace(" ", "").replace("-", "")
            return extracted_clean == correct_word.lower()
        except Exception:
            # Fallback: simple letter extraction
            letters = "".join(c for c in user_input.lower() if c.isalpha())
            return letters == correct_word.lower()

    # -------------------------------------------------------------------------
    # Sign-off
    # -------------------------------------------------------------------------

    async def _sign_off(self):
        """Summarize session and save."""
        if self.session_total > 0:
            pct = round(self.session_correct / self.session_total * 100)
            await self.capability_worker.speak(
                f"Session over! You got {self.session_correct} out of "
                f"{self.session_total} correct — {pct} percent."
            )

            weak = self.progress.get("weak", [])
            if weak:
                practice_words = ", ".join(weak[:3])
                await self.capability_worker.speak(
                    f"Words to practice: {practice_words}."
                )

            mastered = len(self.progress.get("mastered", []))
            await self.capability_worker.speak(
                f"Total words mastered: {mastered}. Great job! See you next time."
            )
        else:
            await self.capability_worker.speak(
                "No worries, come back when you're ready to practice!"
            )
