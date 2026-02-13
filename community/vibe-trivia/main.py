import json
import re
from typing import Any

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

DEFAULT_NUM_QUESTIONS = 3
MAX_NUM_QUESTIONS = 10

EXIT_WORDS = {"stop", "exit", "quit", "cancel", "done", "bye", "goodbye"}

BEST_SCORE_FILE = "vibe_trivia_best_score.json"

INTRO = (
    "Welcome to Vibe Trivia. Pick a category like movies, science, or history. "
    "Or say random."
)

ASK_NUM_QUESTIONS = (
    f"How many questions would you like? You can say a number from 1 to {MAX_NUM_QUESTIONS}."
)

CONFIRM_START = "Great. We'll do {num} questions on {cat}. Ready to start?"

GENERATE_QUESTIONS_PROMPT = (
    "Generate {num} multiple-choice trivia questions about '{cat}'. "
    "Difficulty: medium. "
    "Return ONLY valid JSON (no markdown). "
    "Return a JSON array of objects. Each object MUST have:\n"
    "- question: string\n"
    "- choices: array of 4 strings (A, B, C, D choices, but do NOT prefix with 'A)' etc)\n"
    "- correct_answer: one of 'A','B','C','D'\n"
)

ANSWER_JUDGE_PROMPT = (
    "You are grading a trivia answer.\n"
    "Question: {question}\n"
    "Choices:\n"
    "A: {a}\n"
    "B: {b}\n"
    "C: {c}\n"
    "D: {d}\n"
    "Correct letter: {correct_letter}\n"
    "User answer: {user_answer}\n\n"
    "Is the user's answer correct? Respond with ONLY 'yes' or 'no'."
)


class VibeTriviaCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker | None = None
    capability_worker: CapabilityWorker | None = None
    initial_request: str | None = None
    hotwords: list[str] = ["start vibe trivia", "vibe trivia", "trivia time", "quiz me", "play trivia", "start a quiz"]

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.initial_request = None
        try:
            self.initial_request = worker.transcription
        except Exception:
            pass
        if not self.initial_request:
            try:
                self.initial_request = worker.last_transcription
            except Exception:
                pass
        if not self.initial_request:
            try:
                self.initial_request = worker.current_transcription
            except Exception:
                pass

        self.worker.session_tasks.create(self.run())

    def _log_info(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(msg)

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(msg)

    def _is_exit(self, text: str | None) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return any(w in lowered for w in EXIT_WORDS)

    def _extract_first_int(self, text: str) -> int | None:
        m = re.search(r"\b(\d+)\b", text)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    def _clean_json(self, raw: str) -> str:
        cleaned = raw.strip()
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            return cleaned[start:end + 1]
        return cleaned

    def _validate_questions(self, data: Any) -> list[dict]:
        if not isinstance(data, list):
            return []
        validated: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            q = item.get("question")
            choices = item.get("choices")
            correct = item.get("correct_answer")
            if not isinstance(q, str) or not q.strip():
                continue
            if not isinstance(choices, list) or len(choices) != 4:
                continue
            if not all(isinstance(c, str) and c.strip() for c in choices):
                continue
            if not isinstance(correct, str):
                continue
            correct_letter = correct.strip().upper()
            if correct_letter not in {"A", "B", "C", "D"}:
                continue
            validated.append(
                {
                    "question": q.strip(),
                    "choices": [c.strip() for c in choices],
                    "correct_answer": correct_letter,
                }
            )
        return validated

    def _extract_letter(self, text: str) -> str | None:
        m = re.search(r"\b([ABCD])\b", text.upper())
        if m:
            return m.group(1)
        return None

    def _normalize_for_match(self, text: str) -> str:
        lowered = text.lower()
        lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered).strip()
        return lowered

    def _guess_choice_by_text(self, user_answer: str, choices: list[str]) -> str | None:
        ua = self._normalize_for_match(user_answer)
        if not ua:
            return None
        normalized_choices = [self._normalize_for_match(c) for c in choices]

        for idx, c in enumerate(normalized_choices):
            if not c:
                continue
            if ua == c or ua in c or c in ua:
                return "ABCD"[idx]

        return None

    def _looks_like_trigger_echo(self, text: str) -> bool:
        lowered = text.lower().strip()
        if not lowered:
            return False
        if self.initial_request and lowered == self.initial_request.lower().strip():
            return True
        if any(hw and hw in lowered for hw in self.hotwords):
            return True
        return False

    async def _listen_nonempty(
        self, prompt: str, retries: int = 2, exit_ok: bool = True
    ) -> str | None:
        assert self.capability_worker is not None

        if self.worker:
            await self.worker.session_tasks.sleep(0.2)

        current_prompt = prompt
        for attempt in range(retries + 1):
            text = await self.capability_worker.run_io_loop(current_prompt)

            if exit_ok and self._is_exit(text):
                return None

            if text and text.strip() and not self._looks_like_trigger_echo(text):
                return text.strip()

            if text and text.strip() and self._looks_like_trigger_echo(text):
                self._log_info("[VibeTrivia] Ignoring trigger-echo transcription")

            self._log_info(
                f"[VibeTrivia] Empty/invalid response (attempt {attempt + 1}/{retries + 1})"
            )
            if attempt < retries:
                current_prompt = "I didn't catch that. Please say it again."
            else:
                return None

    async def _read_best(self) -> tuple[int, int] | None:
        if not self.capability_worker:
            return None
        try:
            exists = await self.capability_worker.check_if_file_exists(
                BEST_SCORE_FILE, False
            )
            if not exists:
                return None
            raw = await self.capability_worker.read_file(BEST_SCORE_FILE, False)
            data = json.loads(raw) if raw else {}
            best_correct = int(data.get("best_correct", 0))
            best_total = int(data.get("best_total", 0))
            if best_total <= 0:
                return None
            return best_correct, best_total
        except Exception as e:
            self._log_error(f"[VibeTrivia] Failed to read best score: {e}")
            return None

    async def _write_best(self, best_correct: int, best_total: int):
        if not self.capability_worker:
            return
        try:
            payload = json.dumps(
                {"best_correct": best_correct, "best_total": best_total}, indent=2
            )
            await self.capability_worker.write_file(BEST_SCORE_FILE, payload, False)
        except Exception as e:
            self._log_error(f"[VibeTrivia] Failed to write best score: {e}")

    async def _ask_num_questions(self) -> int | None:
        assert self.capability_worker is not None

        user_input = await self._listen_nonempty(ASK_NUM_QUESTIONS, retries=1)
        if user_input is None:
            await self.capability_worker.speak("Okay, exiting trivia.")
            return None

        n = self._extract_first_int(user_input or "")
        if n is None:
            await self.capability_worker.speak(
                f"No worries. We'll do {DEFAULT_NUM_QUESTIONS}."
            )
            return DEFAULT_NUM_QUESTIONS

        n = max(1, min(MAX_NUM_QUESTIONS, n))
        return n

    async def _generate_questions(self, num: int, category: str) -> list[dict] | None:
        assert self.capability_worker is not None

        last_raw: str | None = None
        for attempt in range(1, 4):
            try:
                prompt = GENERATE_QUESTIONS_PROMPT.format(num=num, cat=category)
                raw = self.capability_worker.text_to_text_response(prompt)
                last_raw = raw
                cleaned = self._clean_json(raw)
                parsed = json.loads(cleaned)
                questions = self._validate_questions(parsed)
                if len(questions) >= num:
                    return questions[:num]
                raise ValueError("Not enough validated questions")
            except Exception as e:
                self._log_error(
                    f"[VibeTrivia] Question generation attempt {attempt} failed: {e}"
                )
                if attempt < 3:
                    await self.capability_worker.speak(
                        "Hang on—I had trouble generating questions. Let me try again."
                    )
                else:
                    if last_raw:
                        self._log_error(
                            f"[VibeTrivia] Last raw generation output: {last_raw[:500]}"
                        )
        return None

    async def _ask_one(self, idx: int, total: int, q: dict) -> bool | None:
        assert self.capability_worker is not None

        question = q["question"]
        choices: list[str] = q["choices"]
        correct_letter: str = q["correct_answer"]

        prompt = (
            f"Question {idx} of {total}. {question}. "
            f"A: {choices[0]}. "
            f"B: {choices[1]}. "
            f"C: {choices[2]}. "
            f"D: {choices[3]}."
        )
        user_answer = await self._listen_nonempty(prompt, retries=1)

        if user_answer is None:
            return None

        letter = self._extract_letter(user_answer or "")
        if not letter:
            letter = self._guess_choice_by_text(user_answer or "", choices)

        if letter:
            return letter == correct_letter

        try:
            judge_prompt = ANSWER_JUDGE_PROMPT.format(
                question=question,
                a=choices[0],
                b=choices[1],
                c=choices[2],
                d=choices[3],
                correct_letter=correct_letter,
                user_answer=user_answer,
            )
            result = self.capability_worker.text_to_text_response(judge_prompt)
            return "yes" in (result or "").lower()
        except Exception as e:
            self._log_error(f"[VibeTrivia] Judge failed: {e}")
            return False

    async def run(self):
        try:
            if not self.capability_worker:
                return

            self._log_info("[VibeTrivia] Ability started")
            await self.capability_worker.speak("Vibe Trivia activated.")

            category_input = await self._listen_nonempty(INTRO, retries=2)
            if category_input is None:
                await self.capability_worker.speak("Okay, exiting trivia.")
                return

            category = (category_input or "").strip()
            if not category:
                category = "random"
            if category.lower() == "random":
                category = "general knowledge"

            num = await self._ask_num_questions()
            if num is None:
                return

            confirmed = await self.capability_worker.run_confirmation_loop(
                CONFIRM_START.format(num=num, cat=category)
            )
            if not confirmed:
                await self.capability_worker.speak("No problem. Come back anytime.")
                return

            await self.capability_worker.speak("Awesome. Here we go.")
            questions = await self._generate_questions(num=num, category=category)
            if not questions:
                await self.capability_worker.speak(
                    "Sorry, I couldn't generate a quiz right now. Try again in a bit."
                )
                return

            score = 0
            for i, q in enumerate(questions, start=1):
                is_correct = await self._ask_one(i, num, q)
                if is_correct is None:
                    await self.capability_worker.speak("All good. Ending the quiz.")
                    return
                if is_correct:
                    score += 1
                    await self.capability_worker.speak("Correct.")
                else:
                    await self.capability_worker.speak("Not quite.")

            await self.capability_worker.speak(
                f"Final score: {score} out of {num}. Thanks for playing!"
            )

            previous = await self._read_best()
            if previous is None:
                await self._write_best(score, num)
                await self.capability_worker.speak("That's your first recorded score. Nice.")
                return

            prev_correct, prev_total = previous
            prev_pct = prev_correct / prev_total if prev_total else 0.0
            pct = score / num if num else 0.0

            if (pct > prev_pct) or (pct == prev_pct and score > prev_correct):
                await self._write_best(score, num)
                await self.capability_worker.speak("New best score!")
            else:
                await self.capability_worker.speak(
                    f"Your best so far is {prev_correct} out of {prev_total}."
                )

        except Exception as e:
            self._log_error(f"[VibeTrivia] Unexpected error: {e}")
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Sorry—something went wrong. Exiting trivia."
                )
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()
