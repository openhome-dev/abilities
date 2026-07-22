import re

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


EXIT_WORDS = ["stop translation", "stop", "exit", "quit", "cancel", "done", "goodbye", "bye"]


def _strip_links_for_voice(text: str) -> str:
    cleaned = re.sub(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", r"\1", text or "")
    cleaned = re.sub(r"(?:https?://|www\.)\S+", "", cleaned)
    cleaned = re.sub(r"`{1,3}", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*]\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class VoiceInterpreterCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("[VoiceInterpreter] Starting Universal Voice Interpreter")

            # Ask for the languages dynamically
            await self.capability_worker.speak("Translation mode starting. What two languages would you like to translate between?")
            languages_input = await self.capability_worker.user_response()

            # Ensure the user didn't instantly try to exit
            if not languages_input or languages_input.strip().lower().strip(" .!?,") in EXIT_WORDS:
                self.worker.editor_logging_handler.info("[VoiceInterpreter] User exited during language selection.")
                await self.capability_worker.speak("Interpreter cancelled.")
                return

            self.worker.editor_logging_handler.info(f"[VoiceInterpreter] Target languages string: {languages_input}")
            await self.capability_worker.speak(f"Perfect. I am now acting as an interpreter for {languages_input}. You can begin speaking. Say 'Stop translation' at any time to exit.")

            # The continuous translation loop
            empty_streak = 0
            while True:
                user_input = await self.capability_worker.user_response()

                # Clean punctuation for the exit check
                clean_input = (user_input or "").lower().strip(" .!?,")

                # Handle silence / no transcription: a natural pause between speakers is
                # expected, so reprompt tolerance is high — only exit after repeated silence.
                if not clean_input:
                    empty_streak += 1
                    if empty_streak >= 3:
                        self.worker.editor_logging_handler.info("[VoiceInterpreter] Exiting after repeated silence.")
                        await self.capability_worker.speak("I haven't heard anything, so I'll stop translating for now.")
                        break
                    continue
                empty_streak = 0

                # Exit condition (the escape hatch) — checked before any LLM call
                if clean_input in EXIT_WORDS:
                    self.worker.editor_logging_handler.info("[VoiceInterpreter] User exited the translation loop.")
                    await self.capability_worker.speak("Translation mode deactivated. Returning you to the normal agent.")
                    break

                # Log the input text
                self.worker.editor_logging_handler.info(f"[VoiceInterpreter] Translating: {user_input}")

                # Use the OpenHome LLM to detect and translate dynamically
                prompt = (
                    f"You are a real-time interpreter between the following two languages: {languages_input}. "
                    "Detect the language of the provided text. If it is in the first language, translate it to the "
                    "second language. If it is in the second language, translate it to the first language. ONLY output "
                    "the final translated text, absolutely nothing else. Do not add conversational filler, quotes, "
                    "markdown, or stage directions. "
                    f"Text: {user_input}"
                )

                # Fetch translated response (guard against LLM errors and empty output)
                try:
                    translated_text = self.capability_worker.text_to_text_response(prompt)
                except Exception as translate_error:
                    self.worker.editor_logging_handler.error(f"[VoiceInterpreter] Translation failed: {translate_error}")
                    await self.capability_worker.speak("Sorry, I couldn't translate that. Please try again.")
                    continue

                spoken = _strip_links_for_voice(translated_text)
                if not spoken:
                    self.worker.editor_logging_handler.warning("[VoiceInterpreter] Empty translation returned.")
                    await self.capability_worker.speak("Sorry, I couldn't translate that. Please try again.")
                    continue

                # Speak it aloud
                await self.capability_worker.speak(spoken)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoiceInterpreter] Error in Voice Interpreter: {str(e)}")
            await self.capability_worker.speak("Sorry, I encountered an error during translation. Deactivating.")
        finally:
            # Mandatory: Release control back to the core OpenHome Agent on every exit path
            self.worker.editor_logging_handler.info("[VoiceInterpreter] Resuming normal flow.")
            self.capability_worker.resume_normal_flow()
