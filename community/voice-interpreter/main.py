from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

class VoiceInterpreterCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("Starting Universal Voice Interpreter")
            
            # Ask for the languages dynamically
            await self.capability_worker.speak("Translation mode starting. What two languages would you like to translate between?")
            languages_input = await self.capability_worker.user_response()
            
            # Ensure the user didn't instantly try to exit
            if not languages_input or languages_input.strip().lower() in ["stop", "exit", "quit", "cancel", "stop translation"]:
                self.worker.editor_logging_handler.info("User exited during language selection.")
                await self.capability_worker.speak("Interpreter cancelled.")
                self.capability_worker.resume_normal_flow()
                return

            self.worker.editor_logging_handler.info(f"Target languages string: {languages_input}")
            await self.capability_worker.speak(f"Perfect. I am now acting as an interpreter for {languages_input}. You can begin speaking. Say 'Stop translation' at any time to exit.")
            
            # The continuous translation loop
            while True:
                user_input = await self.capability_worker.user_response()
                
                # Clean punctuation for the exit check
                clean_input = user_input.lower().strip(" .!?,")
                
                # Exit condition (the escape hatch)
                if not clean_input or clean_input in ["stop translation", "stop", "exit", "quit", "cancel"]:
                    self.worker.editor_logging_handler.info("User exited the translation loop.")
                    await self.capability_worker.speak("Translation mode deactivated. Returning you to the normal agent.")
                    break
                
                # Log the input text
                self.worker.editor_logging_handler.info(f"Translating: {user_input}")

                # Use the OpenHome LLM to detect and translate dynamically
                prompt = f"You are a real-time interpreter between the following two languages: {languages_input}. Detect the language of the provided text. If it is in the first language, translate it to the second language. If it is in the second language, translate it to the first language. ONLY output the final translated text, absolutely nothing else. Do not add conversational filler. Text: {user_input}"
                
                # Fetch translated response
                translated_text = self.capability_worker.text_to_text_response(prompt)
                
                # Speak it aloud
                await self.capability_worker.speak(translated_text)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error in Voice Interpreter: {str(e)}")
            await self.capability_worker.speak("Sorry, I encountered an error during translation. Deactivating.")
        finally:
            # Mandatory: Release control back to the core OpenHome Agent on every exit path
            self.worker.editor_logging_handler.info("Resuming normal flow.")
            self.capability_worker.resume_normal_flow()
