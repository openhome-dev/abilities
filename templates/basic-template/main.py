import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

INTRO_PROMPT = "Hi! I'm your daily life advisor. Please tell me about a problem you're facing."
FEEDBACK_PROMPT = " Are you satisfied with the advice?"
FINAL_PROMPT = "Thank you for using the daily life advisor. Goodbye!"

class QjbvjkbCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    async def give_advice(self):
        """
        The main function for giving advice to the user. 
        It asks the user about their problem, provides a solution, and asks for feedback.
        """

        # Introduce the advisor and ask for the user's problem
        """
        - `speak` function is used to speak the text to the user. It takes the text as an argument. 
                Here, the advisor introduces itself and asks the user about their problem.
        """
        await self.capability_worker.speak(INTRO_PROMPT)

        """
        - `user_response` function is used to get the user's response. It returns the user's response.
                Here, the user's problem is stored in the `user_problem` variable.
        """
        user_problem = await self.capability_worker.user_response()

        # Generate a solution based on the problem
        solution_prompt = f"The user has the following problem: {user_problem}. Provide a helpful solution in just 1 or 2 sentences."
        """
        - `text_to_text_response` function is used to generate a solution based on the user's input. It returns the generated response based on the input prompt.
                Here, the response is stored in the `solution` variable.
        """
        solution = self.capability_worker.text_to_text_response(solution_prompt)

        # Speak the solution and ask if the user is satisfied
        solution_with_feedback_ask = solution + FEEDBACK_PROMPT
        
        """
        - `run_io_loop` function is used to speak the solution and get the user's feedback. It returns the user's feedback.
                It is a combination of `speak` and `user_response` functions.
                Here, the user's feedback is stored in the `user_feedback` variable.
        """
        user_feedback = await self.capability_worker.run_io_loop(solution_with_feedback_ask)

        # Exit the capability if the user is not satisfied
        await self.capability_worker.speak(FINAL_PROMPT)

        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        # Initialize the worker and capability worker
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        # Start the advisor functionality
        self.worker.session_tasks.create(self.give_advice())
