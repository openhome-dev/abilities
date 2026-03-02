import json
import random
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# =============================================================================
# CONFIGURATION & CONSTANTS
# =============================================================================

# Voice ID for the sleep lecture voice (calm, soothing tone)
SLEEP_VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # Use the same voice as the sound ability, or change to your preferred voice

INTRO_PROMPT = (
    "I'll talk quietly for a while. "
    "There's nothing you need to do, and nothing you need to remember. "
    "You can relax and just listen. "
    "If you want to stop at any time, just say stop."
)

TOPIC_PROMPT = (
    "What would you like me to talk about? "
    "You can name a topic, or say 'none' for a random topic."
)

DURATION_PROMPT = (
    "How long would you like me to keep you company? "
    "You can say short, medium, or long."
)

LECTURE_TOPICS = [
    "the slow formation of sedimentary rock layers",
    "the history of library cataloging systems",
    "the life cycle of moss in temperate forests",
    "the physics of wave patterns in still water",
    "the development of postal systems through history",
    "the chemistry of slow-burning candles",
    "the taxonomy of common household dust",
    "the gradual weathering of stone monuments",
    "the principles of long-distance telegraph systems",
    "the process of paper manufacturing in the 19th century"
]

# Duration mapped to lecture segments
DURATION_SEGMENTS = {
    "short": 3,    # ~3-5 minutes per segment
    "medium": 8,   # ~8-15 minutes
    "long": 15     # ~15-25 minutes
}

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "goodbye", "that's enough"}

CLOSING_STATEMENTS = [
    "Rest well. I'll fade out now.",
    "Sleep peacefully. Good night.",
    "I'll let you drift off now. Good night.",
    "Rest easy. I'll be quiet now.",
    "Sweet dreams. I'll go now."
]


class QuietCompanyCapability(MatchingCapability):
    # --- REQUIRED FIELD DEFINITIONS ---
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    
    current_topic: str = None
    segment_count: int = 0
    should_stop: bool = False
    # ----------------------------------

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        # os import ONLY allowed inside this method
        import os
        
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
        
        # Reset state
        self.current_topic = None
        self.segment_count = 0
        self.should_stop = False
        
        self.worker.session_tasks.create(self.run_quiet_lecture())

    async def speak(self, text: str):
        """Use text_to_speech with the sleep voice"""
        await self.capability_worker.text_to_speech(text, SLEEP_VOICE_ID)

    async def run_quiet_lecture(self):
        """Main lecture loop with stop functionality"""
        try:
            # Intro
            await self.speak(INTRO_PROMPT)

            # --- Topic selection ---
            await self.speak(TOPIC_PROMPT)
            topic_response = await self.capability_worker.user_response()

            # Clean up the response - sometimes it includes the trigger phrase
            if topic_response:
                topic_response = topic_response.lower()
                # Remove trigger phrases that might have been captured
                for trigger in ["quiet company", "sleep lecture", "help me sleep"]:
                    topic_response = topic_response.replace(trigger, "").strip()
                topic_response = topic_response.strip(". ,")

            # Check for immediate exit
            if topic_response and any(word in topic_response.lower() for word in EXIT_WORDS):
                await self.speak(random.choice(CLOSING_STATEMENTS))
                self.capability_worker.resume_normal_flow()
                return

            # Handle "none" or empty response
            if not topic_response or topic_response.strip() in ["none", "."]:
                self.current_topic = random.choice(LECTURE_TOPICS)
            else:
                self.current_topic = topic_response.strip()

            await self.speak(f"I'll talk quietly about {self.current_topic}.")

            # --- Duration selection ---
            await self.speak(DURATION_PROMPT)
            duration_response = await self.capability_worker.user_response()

            # Check for exit during duration selection
            if duration_response and any(word in duration_response.lower() for word in EXIT_WORDS):
                await self.speak(random.choice(CLOSING_STATEMENTS))
                self.capability_worker.resume_normal_flow()
                return

            duration_key = duration_response.lower().strip() if duration_response else "short"

            # Map variations to standard keys
            if "short" in duration_key or "quick" in duration_key or "brief" in duration_key:
                duration_key = "short"
            elif "long" in duration_key or "extended" in duration_key:
                duration_key = "long"
            else:
                duration_key = "medium"

            self.segment_count = DURATION_SEGMENTS.get(duration_key, DURATION_SEGMENTS["short"])

            self.worker.editor_logging_handler.info(
                f"[SleepLectures] Topic: {self.current_topic}, Segments: {self.segment_count}"
            )

            # --- Lecture session with interruptible segments ---
            for i in range(self.segment_count):
                # Check if user wants to stop
                if self.should_stop:
                    break

                is_final_segment = (i == self.segment_count - 1)

                if is_final_segment:
                    # FINAL SEGMENT: natural fade-out
                    lecture_prompt = (
                        f"You are giving a slow, calm, sleep-inducing lecture about {self.current_topic}. "
                        "Speak in long, gentle sentences with soft repetition. "
                        "Avoid excitement, urgency, questions, or dramatic conclusions. "
                        "This is the final segment. Gently wind down the topic and naturally "
                        "fade out with a soft closing like 'And with that, I'll let you rest. Good night.' "
                        "Keep it around 250-300 words. The tone should be like a bedtime story that slowly ends."
                    )
                else:
                    lecture_prompt = (
                        f"You are giving a slow, calm, sleep-inducing lecture about {self.current_topic}. "
                        "Speak in long, gentle sentences with soft repetition. "
                        "Avoid excitement, urgency, questions, or dramatic points. "
                        "This should feel like quiet background audio that helps someone drift off to sleep. "
                        "Keep it around 250-300 words. Maintain a steady, unhurried pace."
                    )

                self.worker.editor_logging_handler.info(
                    f"[SleepLectures] Generating segment {i+1}/{self.segment_count}"
                )

                try:
                    lecture_text = self.capability_worker.text_to_text_response(lecture_prompt)
                except Exception as e:
                    self.worker.editor_logging_handler.error(f"[SleepLectures] LLM failed: {e}")
                    await self.speak("I lost my train of thought. Let me try again.")
                    continue

                # Speak the lecture segment
                await self.speak(lecture_text)

                # Check if user interrupted during this segment
                # With auto-interrupt, user speech gets captured even during TTS
                if not is_final_segment:
                    # Check for user input (captured by auto-interrupt)
                    user_input = await self.capability_worker.user_response()

                    # Only stop if user said a stop word, otherwise continue
                    if user_input:
                        self.worker.editor_logging_handler.info(f"[SleepLectures] User said: {user_input}")
                        if any(word in user_input.lower() for word in EXIT_WORDS):
                            self.worker.editor_logging_handler.info(f"[SleepLectures] Stop detected, exiting")
                            await self.speak(random.choice(CLOSING_STATEMENTS))
                            self.capability_worker.resume_normal_flow()
                            return
                        else:
                            # User interrupted but didn't say stop - replay this segment
                            self.worker.editor_logging_handler.info(f"[SleepLectures] Non-stop interruption, replaying segment")
                            await self.speak(lecture_text)

            # If we completed all segments naturally (not stopped early)
            if self.should_stop:
                await self.speak(random.choice(CLOSING_STATEMENTS))

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SleepLectures] Unexpected error: {e}")
            await self.speak("Something went wrong. Sorry about that.")

        self.capability_worker.resume_normal_flow()