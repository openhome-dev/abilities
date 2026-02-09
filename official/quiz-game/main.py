import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# QUIZ GAME
# An AI-generated trivia quiz. The LLM creates questions, the user answers,
# and the LLM evaluates responses. Tracks score across rounds.
# =============================================================================

QUIZ_CATEGORY = "General Knowledge"
NUM_QUESTIONS = 3

QUIZ_INTRO = "Welcome to the Quiz! I'll ask you {num} questions on {cat}."
FEEDBACK_CORRECT = "That's correct!"
FEEDBACK_INCORRECT = "Sorry, that's incorrect."
FINAL_SCORE = "You got {correct} out of {total} correct! Thanks for playing!"

GENERATE_QUESTIONS_PROMPT = (
    "Generate {num} multiple-choice questions on {cat}. "
    "Each question should have four choices labeled A, B, C, and D, and specify the correct answer. "
    "Return ONLY a JSON list where each element has 'question', 'choices' (list of strings), "
    "and 'correct_answer'. No other text."
)

ANSWER_CHECK_PROMPT = (
    "Question: '{question}'\n"
    "Correct answer: '{correct}'\n"
    "User's response: '{user_answer}'\n"
    "Is the user's response correct? Consider synonyms and variations. "
    "Respond with only 'yes' or 'no'."
)

EXIT_WORDS = {"exit", "stop", "quit", "cancel"}


class QuizGameCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    quiz_questions: list = []

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
        self.quiz_questions = []
        self.worker.session_tasks.create(self.run_quiz())

    async def generate_questions(self):
        """Use the LLM to generate quiz questions as JSON."""
        try:
            prompt = GENERATE_QUESTIONS_PROMPT.format(
                num=NUM_QUESTIONS, cat=QUIZ_CATEGORY
            )
            raw = self.capability_worker.text_to_text_response(prompt)
            clean = raw.replace("```json", "").replace("```", "").strip()
            self.quiz_questions = json.loads(clean)
        except json.JSONDecodeError:
            self.worker.editor_logging_handler.error("[Quiz] Failed to parse questions JSON")
            await self.capability_worker.speak("Sorry, I had trouble generating questions. Let me try again.")
            await self.generate_questions()

    async def ask_question(self, question_data: dict) -> bool | None:
        """Ask one question, return True/False/None (None = user wants to exit)."""
        question_text = question_data["question"] + " " + " ".join(question_data["choices"])
        await self.capability_worker.speak(question_text)

        user_answer = await self.capability_worker.user_response()

        # Check if user wants to exit
        if any(word in user_answer.lower() for word in EXIT_WORDS):
            await self.capability_worker.speak("Exiting the quiz. See you next time!")
            return None

        # Use LLM to check the answer
        check_prompt = ANSWER_CHECK_PROMPT.format(
            question=question_data["question"],
            correct=question_data["correct_answer"],
            user_answer=user_answer,
        )
        result = self.capability_worker.text_to_text_response(check_prompt)
        return "yes" in result.lower()

    async def run_quiz(self):
        correct_count = 0
        await self.capability_worker.speak(
            QUIZ_INTRO.format(num=NUM_QUESTIONS, cat=QUIZ_CATEGORY)
        )

        # Generate questions
        await self.generate_questions()

        # Ask each question
        for question in self.quiz_questions[:NUM_QUESTIONS]:
            is_correct = await self.ask_question(question)

            if is_correct is None:
                break  # User exited

            if is_correct:
                await self.capability_worker.speak(FEEDBACK_CORRECT)
                correct_count += 1
            else:
                await self.capability_worker.speak(FEEDBACK_INCORRECT)
        else:
            # Only show final score if we completed all questions
            await self.capability_worker.speak(
                FINAL_SCORE.format(correct=correct_count, total=NUM_QUESTIONS)
            )

        self.capability_worker.resume_normal_flow()
