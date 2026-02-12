import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# VOICE UNIT CONVERTER
# A voice-powered unit converter. Ask any conversion in natural language
# and get the answer instantly. No API needed — the LLM handles everything.
# =============================================================================

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave"}

SYSTEM_PROMPT = (
    "You are a unit converter. The user will ask you to convert between units. "
    "Respond with ONLY the conversion result in one short sentence. "
    "Do not explain the formula. Do not add disclaimers. Just give the answer. "
    "Example: '200 grams is about 7 ounces.'"
)


class VoiceUnitConverterCapability(MatchingCapability):
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
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("[VoiceUnitConverter] Ability started")

            await self.capability_worker.speak(
                "Unit converter ready. What would you like to convert?"
            )

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input:
                    await self.capability_worker.speak(
                        "I didn't catch that. What would you like to convert?"
                    )
                    continue

                if any(word in user_input.lower() for word in EXIT_WORDS):
                    await self.capability_worker.speak("Goodbye!")
                    break

                try:
                    response = self.capability_worker.text_to_text_response(
                        user_input, system_prompt=SYSTEM_PROMPT
                    )
                    await self.capability_worker.speak(response)
                    await self.capability_worker.speak("Anything else?")
                except Exception as e:
                    self.worker.editor_logging_handler.error(
                        f"[VoiceUnitConverter] LLM error: {e}"
                    )
                    await self.capability_worker.speak(
                        "Sorry, I had trouble with that. Try again."
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[VoiceUnitConverter] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Exiting unit converter."
            )
        finally:
            self.worker.editor_logging_handler.info("[VoiceUnitConverter] Ability ended")
            self.capability_worker.resume_normal_flow()
