import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

class LocalCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    
    # Do not change following tag of register capability
    #{{register capability}}

    def get_system_prompt(self):
        system_prompt = """
            You are a Mac terminal command generator. Your ONLY purpose is to convert user requests into valid Mac terminal commands.

            Rules:
            - Respond ONLY with the terminal command, nothing else
            - Use commands that are compatible with macOS (zsh/bash)
            - Do not include explanations, quotes, or markdown formatting
            - Do not use sudo unless absolutely necessary
            - Make sure commands are safe and won't harm the system
            - If the request is unclear, provide the most reasonable command interpretation

            Examples:
            User: "list all files" -> ls -la
            User: "show current directory" -> pwd
            User: "find python files" -> find . -name "*.py"
            User: "check disk space" -> df -h
            User: "show running processes" -> ps aux

            Respond with ONLY the command, no other text.
        """
        return system_prompt

    async def first_function(self):
        user_inquiry = await self.capability_worker.wait_for_complete_transcription()

        # Get the system prompt
        system_prompt = self.get_system_prompt()
        self.worker.editor_logging_handler.info(system_prompt)

        # Use text_to_text_response to convert user inquiry to terminal command
        history = []
        terminal_command = self.capability_worker.text_to_text_response(
            user_inquiry,
            history,
            system_prompt,
        )
        self.worker.editor_logging_handler.info(terminal_command)
        
        # Clean up the response (remove any extra whitespace or newlines)
        terminal_command = terminal_command.strip()
        self.worker.editor_logging_handler.info(terminal_command)
        
        history.append(
            {
                "role": "user",
                "content": user_inquiry,
            },
        )
        history.append(
            {
                "role": "assistant",
                "content": terminal_command,
            },
        )
        # Execute the generated command
        await self.capability_worker.speak(f"Running command: {terminal_command}")
        response = await self.capability_worker.exec_local_command(terminal_command)

        self.worker.editor_logging_handler.info(response)
        # Speak the response
        check_response_system_prompt = """Your job was to return a command that can run locally on mac and you gave that 
            command earlier based on user input now tell if that was successful or not in easier terms that can be directly 
            spoken to the user for his understanding but if user wanted to get the information that's in the response return that response too."""
        result = self.capability_worker.text_to_text_response(
            "check if the command successfully ran? response is: %s"%response,
            history,
            check_response_system_prompt,
        )
        if result:
            await self.capability_worker.speak(result)
        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        # Initialize the worker and capability worker
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        self.worker.session_tasks.create(self.first_function())
