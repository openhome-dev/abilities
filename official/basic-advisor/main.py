import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# BASIC ADVISOR
# A simple daily life advisor that asks for a problem, generates advice
# using the LLM, and collects feedback.
# =============================================================================

INTRO_PROMPT = "Hi! I'm your daily life advisor. Tell me about a problem you're facing."
FEEDBACK_PROMPT = " Are you satisfied with the advice?"
FINAL_PROMPT = "Thank you for using the daily life advisor. Goodbye!"


class BasicAdvisorCapability(MatchingCapability):
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
        self.worker.session_tasks.create(self.give_advice())

    async def give_advice(self):
        # Introduce the advisor and ask for the user's problem
        await self.capability_worker.speak(INTRO_PROMPT)

        # Wait for the user to describe their problem
        user_problem = await self.capability_worker.user_response()

        # Generate a solution using the LLM
        solution_prompt = (
            f"The user has the following problem: {user_problem}. "
            "Provide a helpful solution in just 1 or 2 sentences."
        )
        solution = self.capability_worker.text_to_text_response(solution_prompt)

        # Speak the solution and ask for feedback
        user_feedback = await self.capability_worker.run_io_loop(
            solution + FEEDBACK_PROMPT
        )

        # Thank the user and exit
        await self.capability_worker.speak(FINAL_PROMPT)
        self.capability_worker.resume_normal_flow()
