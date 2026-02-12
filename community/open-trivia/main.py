import json
import os
from typing import Any, Dict, Optional

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

TRIVIA_VOICE_ID = "29vD33N1CtxCmqQRPOHJ"


class QuestionResult:
    EXIT = "exit"
    NEXT = "next"
    REPEAT = "repeat"


class OpenTriviaCapability(MatchingCapability):

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # =====================================================
    # REGISTER
    # =====================================================

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

    # =====================================================
    # UTILITIES
    # =====================================================

    def _safe_json(self, raw: Any) -> Optional[Dict[str, Any]]:
        """Safely parse JSON returned from LLM."""
        if not isinstance(raw, str):
            return None
        try:
            cleaned = raw.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def _is_yes(self, text: Optional[str]) -> bool:
        normalized = (text or "").strip().lower()
        words = normalized.replace(".", "").replace(",", "").split()
        return words and words[0] in ["yes", "yeah", "yep", "ok", "okay"]

    def _is_no(self, text: Optional[str]) -> bool:
        normalized = (text or "").strip().lower()
        words = normalized.replace(".", "").replace(",", "").split()
        return words and words[0] in ["no", "nope", "nah", "quit", "exit", "stop"]

    # =====================================================
    # LLM FUNCTIONS
    # =====================================================

    def detect_intent(self, user_input: str) -> str:
        """
        Uses LLM to detect high-level intent:
        - quit
        - repeat
        - change_question
        - answer
        - unknown
        """

        prompt = f"""
You are classifying a player's intent inside a voice-based trivia game.

Determine the SINGLE best intent from the list below.

INTENT DEFINITIONS:

quit:
The player wants to stop the game completely.
Examples:
- "I want to quit"
- "I'm done"
- "Stop the game"
- "Exit"
- "That's enough"
- "I don't want to continue"
- "Let's stop here"

repeat:
The player wants the SAME question asked again.
Examples:
- "Repeat the question"
- "Say that again"
- "Can you repeat it?"
- "I didn't hear it"
- "Again please"

change_question:
The player wants a DIFFERENT question.
Examples:
- "Give me another one"
- "Change the question"
- "New question"
- "Skip this one"

answer:
The player is attempting to answer the question, even if unsure.
Examples:
- "I think it's B"
- "Is it Saturn?"
- "Maybe C"
- "I'll go with A"
- "Not sure, but B"

unknown:
The message does not clearly match any category.

IMPORTANT:
- If the user is expressing uncertainty about the answer (e.g., "I'm not sure, maybe B"),
  classify as "answer".
- Only classify as "quit" if they clearly intend to stop the game.
- Do not guess. Choose the closest valid category.

Return ONLY valid JSON:
{{"intent": "quit"}}

User message:
"{user_input}"
"""

        raw = self.capability_worker.text_to_text_response(prompt)
        parsed = self._safe_json(raw)

        if not parsed:
            return "unknown"

        intent = parsed.get("intent")
        if not isinstance(intent, str):
            return "unknown"

        return intent.strip().lower()

    def interpret_answer(self, question, options, user_input) -> Optional[str]:
        """Uses LLM to map user speech to option A/B/C/D."""

        prompt = f"""
    You are mapping a spoken trivia answer to a multiple choice option.

    Question:
    {question}

    Options:
    A: {options['A']}
    B: {options['B']}
    C: {options['C']}
    D: {options['D']}

    Player said:
    "{user_input}"

    RULES:

    1. If the player clearly chooses a letter, return that letter.

    Examples:
    - "A"
    - "It's B"
    - "I think it's C"
    - "I'll go with D"
    - "Maybe A"
    - "Is it B?"
    - "Not sure, but C"

    2. If the player says the FULL answer text instead of the letter,
    match it to the correct option and return its letter.

    Example:
    If option B is "Saturn" and the player says:
    - "Saturn"
    - "I think it's Saturn"
    You must return: B

    3. If the player paraphrases an option,
    choose the closest matching option based on meaning.

    4. If the player expresses uncertainty BUT still selects a letter,
    return that letter.

    Examples:
    - "I'm not sure, maybe B"
    - "I'll guess D"

    5. If the player does NOT select any option at all,
    return ?.

    Examples:
    - "I don't know"
    - "No idea"
    - "I'm not sure"

    6. Do NOT guess randomly.
    7. Do NOT explain your reasoning.
    8. Output EXACTLY one character:
    A, B, C, D, or ?
    """

        raw = self.capability_worker.text_to_text_response(prompt)

        if not isinstance(raw, str):
            return None

        cleaned = raw.strip().upper()

        if cleaned in ["A", "B", "C", "D"]:
            return cleaned

        if cleaned == "?":
            return None

        return None

    def generate_question(self) -> Optional[Dict[str, Any]]:
        """Uses LLM to generate a new trivia question."""

        prompt = """
    Generate a random multiple choice trivia question.

    Return JSON in this exact format:
    {
    "question": "...",
    "options": {
        "A": "...",
        "B": "...",
        "C": "...",
        "D": "..."
    },
    "correct_answer": "B",
    "explanation": "Short explanation"
    }

    Rules:
    - The correct_answer must be one of A, B, C, or D.
    - Keep explanation short (1 sentence).
    - Do not include extra text outside JSON.
    """

        raw = self.capability_worker.text_to_text_response(prompt)
        data = self._safe_json(raw)
        if not data:
            return None

        if not all(k in data for k in ("question", "options", "correct_answer", "explanation")):
            return None

        options = data["options"]
        if not isinstance(options, dict):
            return None

        for key in ("A", "B", "C", "D"):
            if key not in options:
                return None

        correct = str(data["correct_answer"]).strip().upper()
        if correct:
            correct = correct[0]

        if correct not in options:
            return None

        data["correct_answer"] = correct
        return data

    def generate_feedback(self, question, correct_answer, explanation, correct):
        """Uses LLM to generate natural host-style feedback."""

        result = "correct" if correct else "incorrect"

        prompt = f"""
You are the energetic host of Open Trivia.

The player was {result}.
Question: {question}
Correct Answer: {correct_answer}
Explanation: {explanation}

Generate a short natural spoken response.
"""
        return self.capability_worker.text_to_text_response(prompt).strip()

    # =====================================================
    # ROUTING AFTER ANSWER
    # =====================================================

    async def route_post_answer(self, question, options, correct, explanation, user_input):

        intent = self.detect_intent(user_input)

        if intent == "quit":
            await self.capability_worker.speak(
                "Alright, we'll stop here. Thanks for playing Open Trivia."
            )
            return QuestionResult.EXIT

        if intent == "repeat":
            return QuestionResult.REPEAT

        if intent == "change_question":
            await self.capability_worker.speak(
                "Sure, let's try a different one."
            )
            return QuestionResult.NEXT

        # Default: treat as answer
        selected = self.interpret_answer(question, options, user_input)

        if not selected:
            await self.capability_worker.speak(
                "I didn't quite catch that. Let's try that question again."
            )
            return QuestionResult.REPEAT

        is_correct = selected == correct
        spoken_correct = f"{correct}. {options[correct]}"

        feedback = self.generate_feedback(
            question,
            spoken_correct,
            explanation,
            is_correct
        )

        await self.capability_worker.text_to_speech(
            feedback,
            TRIVIA_VOICE_ID
        )

        return await self.route_continue_decision()

    # =====================================================
    # CONTINUE DECISION (Deterministic)
    # =====================================================

    async def route_continue_decision(self):

        await self.capability_worker.speak(
            "Would you like another question? Please say Yes or No."
        )

        first = await self.capability_worker.user_response()

        if self._is_yes(first):
            return QuestionResult.NEXT

        if self._is_no(first):
            await self.capability_worker.speak(
                "Thanks for playing Open Trivia. See you next time."
            )
            return QuestionResult.EXIT

        # Clarify once only
        await self.capability_worker.speak(
            "I just need a yes or no."
        )

        second = await self.capability_worker.user_response()

        if self._is_yes(second):
            return QuestionResult.NEXT

        await self.capability_worker.speak(
            "Alright, we'll stop here. Thanks for playing."
        )
        return QuestionResult.EXIT

    # =====================================================
    # QUESTION HANDLER
    # =====================================================

    async def handle_question(self):

        data = self.generate_question()
        if not data:
            return QuestionResult.EXIT

        question = data["question"]
        options = data["options"]
        correct = data["correct_answer"]
        explanation = data["explanation"]

        while True:

            await self.capability_worker.text_to_speech(
                f"{question} "
                f"A. {options['A']}. "
                f"B. {options['B']}. "
                f"C. {options['C']}. "
                f"D. {options['D']}. "
                f"Please say A, B, C, or D.",
                TRIVIA_VOICE_ID
            )

            user_input = await self.capability_worker.user_response()

            result = await self.route_post_answer(
                question,
                options,
                correct,
                explanation,
                user_input
            )

            if result == QuestionResult.REPEAT:
                continue

            return result

    # =====================================================
    # MAIN FLOW
    # =====================================================

    async def trivia_flow(self):

        await self.capability_worker.speak(
            "Welcome to Open Trivia. Ready to test your knowledge?"
        )

        start = await self.capability_worker.user_response()

        if self._is_no(start):
            await self.capability_worker.speak(
                "No problem. Maybe next time."
            )
            self.capability_worker.resume_normal_flow()
            return

        while True:

            result = await self.handle_question()

            if result == QuestionResult.EXIT:
                break

            if result == QuestionResult.NEXT:
                continue

        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(worker)
        self.worker.session_tasks.create(self.trivia_flow())
