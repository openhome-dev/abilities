import json
import re
import os
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# SOUND GENERATOR
# Generates AI sound effects using the ElevenLabs Sound Generation API.
# Supports creating, modifying, replaying, and adjusting duration.
# =============================================================================

# --- CONFIGURATION ---
# Replace with your ElevenLabs API key
ELEVENLABS_API_KEY = "YOUR_ELEVENLABS_API_KEY_HERE"
ELEVENLABS_SOUND_URL = "https://api.elevenlabs.io/v1/sound-generation"

DEFAULT_DURATION = 5.0
MAX_DURATION = 30.0
MIN_DURATION = 0.5

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "leave"}
REPLAY_WORDS = {"again", "replay", "repeat", "one more time"}

ENHANCE_PROMPT = (
    "Enhance this sound effect prompt for an AI generator. "
    "Add details about texture, acoustics, and environment. Keep it under 20 words. "
    "Input: '{input}'\nEnhanced:"
)


class SoundGeneratorCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    current_description: str = None
    current_duration: float = None
    last_audio_bytes: bytes = None

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
        self.current_description = None
        self.current_duration = None
        self.last_audio_bytes = None
        self.worker.session_tasks.create(self.run_sound_loop())

    async def generate_sound(self, description: str, duration: float) -> bytes | None:
        """Call ElevenLabs Sound Generation API."""
        duration = max(MIN_DURATION, min(MAX_DURATION, duration))

        payload = {
            "text": description,
            "prompt_influence": 0.3,
            "duration_seconds": duration,
        }

        self.worker.editor_logging_handler.info(
            f"[SoundGen] Generating: '{description}' ({duration}s)"
        )

        try:
            response = requests.post(
                ELEVENLABS_SOUND_URL,
                json=payload,
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
            )

            if response.status_code == 200:
                self.current_description = description
                self.current_duration = duration
                self.last_audio_bytes = response.content
                return response.content
            else:
                self.worker.editor_logging_handler.error(
                    f"[SoundGen] API error: {response.status_code} {response.text}"
                )
                return None

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SoundGen] Exception: {e}")
            return None

    def parse_duration(self, text: str) -> float | None:
        """Extract a duration in seconds from user input."""
        match = re.search(r"(\d+(?:\.\d+)?)\s*sec", text.lower())
        if match:
            return float(match.group(1))

        keywords = {"short": 2.0, "long": 8.0, "longer": 10.0, "shorter": 2.0}
        for word, val in keywords.items():
            if word in text.lower():
                return val
        return None

    async def run_sound_loop(self):
        await self.capability_worker.speak(
            "Sound generator ready. Describe what you want to hear."
        )

        while True:
            user_input = await self.capability_worker.user_response()
            if not user_input:
                continue

            lower = user_input.lower().strip()

            # Exit check
            if any(w in lower for w in EXIT_WORDS):
                await self.capability_worker.speak("Closing sound generator.")
                break

            # Replay check
            if self.last_audio_bytes and any(w in lower for w in REPLAY_WORDS):
                await self.capability_worker.speak("Replaying.")
                await self.capability_worker.play_audio(self.last_audio_bytes)
                continue

            # Duration adjustment
            if self.current_description and ("longer" in lower or "shorter" in lower):
                current = self.current_duration or DEFAULT_DURATION
                new_dur = current + 3.0 if "longer" in lower else max(MIN_DURATION, current - 2.0)
                await self.capability_worker.speak(f"Regenerating at {new_dur} seconds.")
                audio = await self.generate_sound(self.current_description, new_dur)
                if audio:
                    await self.capability_worker.play_audio(audio)
                continue

            # Enhance existing sound
            if self.current_description and "enhance" in lower:
                await self.capability_worker.speak("Enhancing.")
                new_desc = self.capability_worker.text_to_text_response(
                    ENHANCE_PROMPT.format(input=self.current_description)
                ).replace('"', "").replace("'", "").strip()
                audio = await self.generate_sound(new_desc, self.current_duration or DEFAULT_DURATION)
                if audio:
                    await self.capability_worker.play_audio(audio)
                continue

            # New sound
            duration = self.parse_duration(user_input) or DEFAULT_DURATION
            await self.capability_worker.speak(f"Creating {user_input}.")
            audio = await self.generate_sound(user_input, duration)
            if audio:
                await self.capability_worker.play_audio(audio)
                await self.capability_worker.speak("There we go. You can modify it or ask for a new sound.")
            else:
                await self.capability_worker.speak("Sorry, I couldn't generate that sound.")

        self.capability_worker.resume_normal_flow()
