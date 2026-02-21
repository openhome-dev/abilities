import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

INTRO_PROMPT = "Hi! How can I help you today?"
FEEDBACK_PROMPT = " Are you satisfied with the response?"
FINAL_PROMPT = "Thank you for using the advisor. Goodbye!"

class BasicTemplateCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    async def run(self):
        """
        The main function for the basic template capability.
        It greets the user, listens for their response, generates a reply, and asks for feedback.
        """

        # Introduce and ask for the user's input
        """
        - `speak` function is used to speak the text to the user. It takes the text as an argument.
                Here, the advisor greets the user and asks how it can help.
        """
        await self.capability_worker.speak(INTRO_PROMPT)

        """
        - `user_response` function is used to get the user's response. It returns the user's response.
                Here, the user's input is stored in the `user_input` variable.
        """
        user_input = await self.capability_worker.user_response()

        # Generate a response based on the user's input
        response_prompt = f"Give a short, helpful response to: {user_input}"
        """
        - `text_to_text_response` function is used to generate a response based on the user's input. It returns the generated response based on the input prompt.
                Here, the response is stored in the `response` variable.
        """
        response = self.capability_worker.text_to_text_response(response_prompt)

        # Speak the response and ask if the user is satisfied
        response_with_feedback_ask = response + FEEDBACK_PROMPT

        """
        - `run_io_loop` function is used to speak the response and get the user's feedback. It returns the user's feedback.
                It is a combination of `speak` and `user_response` functions.
                Here, the user's feedback is stored in the `user_feedback` variable.
        """
        user_feedback = await self.capability_worker.run_io_loop(response_with_feedback_ask)

        # Thank the user and exit
        await self.capability_worker.speak(FINAL_PROMPT)

        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        # Initialize the worker and capability worker
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        # Start the template functionality
        self.worker.session_tasks.create(self.run())
