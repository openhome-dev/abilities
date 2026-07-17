import asyncio
import json
import secrets
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

_EXIT_PHRASES = (
    "exit", "quit", "that's all", "nevermind", "never mind",
    "go back", "stop player", "stop playing", "goodbye",
)
_NEXT_PHRASES = ("next", "skip", "next song", "next track")
_RANDOM_PHRASES = ("random", "anything", "surprise me", "whatever", "shuffle", "any song")


class AhmedmusicCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    async def _load_songs(self) -> list:
        catalog_path = "songs.json"
        if not await self.capability_worker.check_if_file_exists(catalog_path, in_ability_directory=True):
            return []
        try:
            data = await self.capability_worker.read_file(catalog_path, in_ability_directory=True)
            songs = json.loads(data)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ahmedmusic] songs.json error: {e}")
            return []
        return [s for s in songs if await self.capability_worker.check_if_file_exists(s.get("file", ""), in_ability_directory=True)]

    def _match_song(self, text: str, songs: list) -> int:
        """Return index of matching song, or -1 if none found."""
        t = text.lower().strip()
        for i, song in enumerate(songs):
            title = song["title"].lower()
            if title in t or t in title:
                return i
            for kw in song.get("keywords", []):
                if kw.lower() in t:
                    return i
        return -1

    async def _ask_for_song(self, songs: list, current_idx: int = -1, prompt: str = None) -> int:
        """Prompt user to pick a song. Returns song index, or -1 to exit."""
        if prompt is None:
            names = ", ".join(s["title"] for s in songs)
            prompt = (
                f"I have {len(songs)} songs: {names}. "
                "Which one would you like? Say a song title, next, random, or exit."
            )

        self.worker.music_mode_event.clear()
        await self.worker.session_tasks.sleep(0.2)

        for attempt in range(3):
            await self.capability_worker.speak(prompt)
            await self.worker.session_tasks.sleep(0.35)
            response = await self.capability_worker.user_response()
            r = response.lower().strip()

            if any(kw in r for kw in _EXIT_PHRASES):
                return -1

            if any(kw in r for kw in _NEXT_PHRASES):
                return (current_idx + 1) % len(songs)

            if any(kw in r for kw in _RANDOM_PHRASES):
                return secrets.randbelow(len(songs))

            idx = self._match_song(response, songs)
            if idx >= 0:
                return idx

            prompt = "I didn't catch that. Say a song title, say random, or say exit."

        return 0

    async def play_audio(self) -> None:
        try:
            songs = await self._load_songs()
            if not songs:
                await self.capability_worker.speak("No songs found in my music library.")
                return

            self.worker.music_mode_event.set()
            await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})

            initial_text = self.worker.final_user_input if hasattr(self.worker, "final_user_input") else ""
            current_idx = self._match_song(initial_text, songs)
            if current_idx < 0:
                current_idx = await self._ask_for_song(songs)
                if current_idx < 0:
                    await self.capability_worker.speak("Okay, just say play my music whenever you're ready.")
                    return

            while current_idx >= 0:
                song = songs[current_idx]
                await self.capability_worker.speak(f"Playing {song['title']}")

                self.worker.music_mode_event.set()
                self.worker._music_mode_last_cmd = None
                self.worker.music_mode_stop_event.clear()
                self.worker.music_mode_pause_event.clear()

                await self.capability_worker.play_from_audio_file(song["file"])

                cmd = self.worker._music_mode_last_cmd if hasattr(self.worker, "_music_mode_last_cmd") else None

                if cmd == "exit":
                    self.worker.music_mode_event.clear()
                    break

                elif cmd == "next":
                    current_idx = (current_idx + 1) % len(songs)
                    next_song = songs[current_idx]
                    await self.capability_worker.speak(f"Up next: {next_song['title']}")
                    continue

                else:
                    current_idx = await self._ask_for_song(
                        songs,
                        current_idx=current_idx,
                        prompt="Song finished. Say a title, next, random, or exit."
                    )
                    if current_idx >= 0:
                        self.worker.music_mode_event.set()

            await self.capability_worker.speak(
                "Exiting music mode. I'll be here if you need me."
            )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ahmedmusic] Error: {e}")
        finally:
            await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
            self.worker.music_mode_event.clear()
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.play_audio())