import json
import re
from typing import Any

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "no"}

INTRO = "Unit converter ready. What would you like to convert?"

CONVERT_PROMPT = (
    "You are a unit converter assistant. "
    "The user said: '{user_input}'. "
    "Convert the requested units and respond with ONLY the answer in one clear sentence. "
    "Be concise and natural. Examples: "
    "'100 grams is about 3.5 ounces.' "
    "'72 Fahrenheit is 22 Celsius.' "
    "'One cup is 16 tablespoons.' "
    "If the request is unclear or not a conversion, say: 'I didn't catch that conversion. Try again.'"
)

ANYTHING_ELSE = "Anything else to convert?"


class UnitConverterCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    #{{register capability}}
    worker: AgentWorker | None = None
    capability_worker: CapabilityWorker | None = None

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
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
        lowered = text.lower().strip()
        return any(w in lowered for w in EXIT_WORDS)

    async def run(self):
        try:
            if not self.capability_worker:
                return

            self._log_info("[UnitConverter] Ability started")

            if self.worker:
                await self.worker.session_tasks.sleep(0.3)

            max_conversions = 20
            for _ in range(max_conversions):
                if _ == 0:
                    user_input = await self.capability_worker.run_io_loop(INTRO)
                else:
                    user_input = await self.capability_worker.run_io_loop(ANYTHING_ELSE)

                if self._is_exit(user_input):
                    await self.capability_worker.speak("Got it. See you next time.")
                    return

                if not user_input or not user_input.strip():
                    continue

                try:
                    prompt = CONVERT_PROMPT.format(user_input=user_input)
                    result = self.capability_worker.text_to_text_response(prompt)
                    
                    if result and result.strip():
                        await self.capability_worker.speak(result.strip())
                    else:
                        await self.capability_worker.speak(
                            "I didn't catch that conversion. Try again."
                        )
                except Exception as e:
                    self._log_error(f"[UnitConverter] Conversion failed: {e}")
                    await self.capability_worker.speak(
                        "Sorry, I had trouble with that. Try again."
                    )

            await self.capability_worker.speak("Ending the converter. Bye!")

        except Exception as e:
            self._log_error(f"[UnitConverter] Unexpected error: {e}")
            if self.capability_worker:
                await self.capability_worker.speak("Something went wrong. Exiting.")
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()

