import json
import os
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# MUSIC PLAYER
# Demonstrates two ways to play audio:
# 1. Download from a URL and play with play_audio()
# 2. Play a local file with play_from_audio_file()
#
# Uses music mode to signal the system that audio playback is active.
# =============================================================================

# Example public domain music URL (replace with your own source)
SAMPLE_MUSIC_URL = "https://cdn.pixabay.com/download/audio/2023/10/22/audio_6d1fc2e6c3.mp3?filename=rise-up-172724.mp3"


class MusicPlayerCapability(MatchingCapability):
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
        self.worker.session_tasks.create(self.play_music())

    async def enter_music_mode(self):
        """Signal the system that music playback is active."""
        self.worker.music_mode_event.set()
        await self.capability_worker.send_data_over_websocket(
            "music-mode", {"mode": "on"}
        )

    async def exit_music_mode(self):
        """Signal the system that music playback has ended."""
        await self.capability_worker.send_data_over_websocket(
            "music-mode", {"mode": "off"}
        )
        self.worker.music_mode_event.clear()

    async def play_music(self):
        await self.capability_worker.speak("Playing some music for you.")

        try:
            # Enter music mode (updates LEDs, pauses listening)
            await self.enter_music_mode()

            # Option 1: Download and play from URL
            self.worker.editor_logging_handler.info("[Music] Downloading audio...")
            response = requests.get(SAMPLE_MUSIC_URL)

            if response.status_code == 200:
                await self.capability_worker.play_audio(response.content)
            else:
                self.worker.editor_logging_handler.error(
                    f"[Music] Download failed: {response.status_code}"
                )
                await self.capability_worker.speak("Sorry, I couldn't load the music.")

            # Option 2: Play from a local file in the Ability folder
            # Uncomment the line below and add a song.mp3 to your Ability folder:
            # await self.capability_worker.play_from_audio_file("song.mp3")

            # Exit music mode
            await self.exit_music_mode()

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Music] Error: {e}")
            await self.exit_music_mode()
            await self.capability_worker.speak("Something went wrong with playback.")

        self.capability_worker.resume_normal_flow()
