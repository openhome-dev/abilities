import json
import os

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# Voice ID for "American, Mid-aged, Male, News"
VOICE_ID = "29vD33N1CtxCmqQRPOHJ"


class UnitConverterCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        # Using the exact pattern from the Developer Docs
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
        # Using session_tasks.create as required by the Managed Lifecycle
        self.worker.session_tasks.create(self.unit_converter_logic())

    async def unit_converter_logic(self):
        try:
            self.worker.editor_logging_handler.info("Unit Converter Started.")
            # 1. Startup: Keep it short
            await self.capability_worker.text_to_speech("Ready.", VOICE_ID)
            while True:
                # 2. Wait for user response
                user_input = await self.capability_worker.user_response()
                if not user_input or len(user_input.strip()) == 0:
                    continue
                # 3. Exit Handling
                if any(
                    word in user_input.lower()
                    for word in ["exit", "stop", "quit", "done"]
                ):
                    await self.capability_worker.text_to_speech("Goodbye.", VOICE_ID)
                    break
                # 4. Strict LLM Prompt for Zero-Fluff results
                system_prompt = (
                    "STRICT ROLE: Silent mathematical engine. "
                    "TASK: Convert units with high numerical accuracy. "
                    "FORMAT: '<input> is about <output>.' "
                    "RULE: No filler. No weather comments. No 'Sure'. "
                    "RULE: Use the word 'point' for decimals (e.g., '0 point 4 7')."
                )
                # Generate result
                answer = self.capability_worker.text_to_text_response(
                    prompt_text=user_input, system_prompt=system_prompt
                )
                # 5. Clean and Speak
                # Split to ensure we only take the math sentence
                clean_answer = answer.split("?")[0].split("!")[0].strip()
                await self.capability_worker.text_to_speech(
                    f"{clean_answer}. Anything else?", VOICE_ID
                )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Ability Error: {str(e)}")
        finally:
            # 6. CRITICAL: Resume normal flow per SDK requirements
            self.capability_worker.resume_normal_flow()
