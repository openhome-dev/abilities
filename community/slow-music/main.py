import re
import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
import requests


AUDIUS_APP_NAME = "OpenHome"

MUSIC_CATEGORIES = {
    "slow_music": "slow calm instrumental",
    "relaxing_music": "relaxing soothing peaceful",
    "meditation_music": "meditation zen mindfulness",
    "lofi_music": "lofi chill beats",
    "piano_music": "piano soft classical",
    "ambient_music": "ambient atmospheric drone",
    "jazz_music": "smooth jazz relaxing",
    "nature_music": "nature sounds rain forest",
    "acoustic_music": "acoustic guitar soft",
    "classical_music": "classical orchestra calm",
    "sleep_music": "deep sleep calm dreamy",
    "spa_music": "spa wellness tranquil",
}

# Instant keyword matching — no LLM round-trip needed
CATEGORY_KEYWORDS = {
    "slow": "slow_music",
    "calm": "slow_music",
    "gentle": "slow_music",
    "relax": "relaxing_music",
    "sooth": "relaxing_music",
    "peaceful": "relaxing_music",
    "meditat": "meditation_music",
    "zen": "meditation_music",
    "mindful": "meditation_music",
    "lofi": "lofi_music",
    "lo-fi": "lofi_music",
    "lo fi": "lofi_music",
    "chill": "lofi_music",
    "study": "lofi_music",
    "beats": "lofi_music",
    "piano": "piano_music",
    "ambient": "ambient_music",
    "atmospheric": "ambient_music",
    "jazz": "jazz_music",
    "nature": "nature_music",
    "rain": "nature_music",
    "forest": "nature_music",
    "ocean": "nature_music",
    "waves": "nature_music",
    "acoustic": "acoustic_music",
    "guitar": "acoustic_music",
    "classical": "classical_music",
    "orchestra": "classical_music",
    "symphony": "classical_music",
    "sleep": "sleep_music",
    "dream": "sleep_music",
    "lullaby": "sleep_music",
    "bedtime": "sleep_music",
    "spa": "spa_music",
    "wellness": "spa_music",
    "tranquil": "spa_music",
}

MUSIC_LIST_DISPLAY = [
    {"key": "slow_music", "label": "🎵 Slow & Calm"},
    {"key": "relaxing_music", "label": "😌 Relaxing"},
    {"key": "meditation_music", "label": "🧘 Meditation"},
    {"key": "lofi_music", "label": "🎧 Lo-Fi Beats"},
    {"key": "piano_music", "label": "🎹 Piano"},
    {"key": "ambient_music", "label": "🌌 Ambient"},
    {"key": "jazz_music", "label": "🎷 Jazz"},
    {"key": "nature_music", "label": "🌿 Nature Sounds"},
    {"key": "acoustic_music", "label": "🎸 Acoustic"},
    {"key": "classical_music", "label": "🎻 Classical"},
    {"key": "sleep_music", "label": "😴 Sleep"},
    {"key": "spa_music", "label": "💆 Spa & Wellness"},
]

FALLBACK_URL = "https://audius-content-12.cultur3stake.com/tracks/cidstream/QmTzKayW8ueYVsibsvT1T3kGFzM71UtBUDwz7iCjGcEKPB?id3=true&id3_artist=Ewil+TheDemonDude%21&id3_title=Outro%3A+Turn+Off&signature=%7B%22data%22%3A%22%7B%5C%22cid%5C%22%3A%5C%22QmTzKayW8ueYVsibsvT1T3kGFzM71UtBUDwz7iCjGcEKPB%5C%22%2C%5C%22timestamp%5C%22%3A1770237264000%2C%5C%22trackId%5C%22%3A123456%2C%5C%22userId%5C%22%3A0%7D%22%2C%22signature%22%3A%220xae01bf14dea5931f00565f648b19d90956c46d71cd85e3e04021e8e02b8b44e1033ace2cebc915d8cdb83d9346b590d3b568f227ceba75c53434b66a262d8dbe00%22%7D&skip_play_count=true"


class PlaySleepMusicCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    #{{register capability}}
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

    # ── Audius helpers ────────────────────────────────────────────

    def get_audius_host(self):
        if self.audius_host:
            return self.audius_host
        try:
            resp = requests.get("https://api.audius.co", timeout=10)
            if resp.status_code == 200:
                hosts = resp.json().get("data", [])
                if hosts:
                    self.audius_host = hosts[0]
                    return self.audius_host
        except Exception:
            pass
        self.audius_host = "https://discoveryprovider.audius.co"
        return self.audius_host

    def search_track_on_audius(self, query):
        host = self.get_audius_host()
        try:
            resp = requests.get(
                f"{host}/v1/tracks/search",
                params={"query": query, "app_name": AUDIUS_APP_NAME},
                timeout=15,
            )
            if resp.status_code == 200:
                tracks = resp.json().get("data", [])
                if tracks:
                    track = tracks[0]
                    return (
                        track.get("id"),
                        track.get("title", "Unknown"),
                        track.get("user", {}).get("name", "Unknown Artist"),
                    )
        except Exception:
            pass
        return None

    def download_track_bytes(self, track_id):
        host = self.get_audius_host()
        try:
            resp = requests.get(
                f"{host}/v1/tracks/{track_id}/stream",
                params={"app_name": AUDIUS_APP_NAME},
                timeout=120,
            )
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.content
        except Exception:
            pass
        return None

    def download_from_url(self, url):
        try:
            resp = requests.get(url, timeout=120)
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.content
        except Exception:
            pass
        return None

    # ── Detection helpers ─────────────────────────────────────────

    def quick_match_category(self, user_input):
        """Instant keyword match — no LLM call needed."""
        text = user_input.lower()
        for keyword, category in CATEGORY_KEYWORDS.items():
            if keyword in text:
                return category
        return None

    def extract_sound_category(self, user_input):
        """Keyword match first, LLM only as fallback."""
        quick = self.quick_match_category(user_input)
        if quick:
            return quick
        try:
            category_list = ", ".join(MUSIC_CATEGORIES.keys())
            prompt = (
                f"The user said: '{user_input}'. "
                f"Return the single best match from: {category_list}. "
                f"Return ONLY the key. Default: slow_music"
            )
            result = self.capability_worker.text_to_text_response(prompt).strip().lower()
            if result in MUSIC_CATEGORIES:
                return result
        except Exception:
            pass
        return "slow_music"

    def detect_command(self, user_input):
        """Fast keyword command detection with LLM fallback."""
        text = user_input.lower()

        if any(w in text for w in ("stop", "pause", "end", "quit", "exit", "enough", "done", "turn off")):
            return "stop"
        if any(w in text for w in ("timer", "minute", "hour", "auto stop", "schedule")):
            return "timer"
        if any(w in text for w in ("list", "option", "menu", "available", "what can", "choices")):
            return "list"
        if any(w in text for w in ("play", "change", "switch", "put on", "try", "listen", "want")):
            return "play"

        try:
            prompt = f"User said: '{user_input}'. Return ONLY ONE: play, stop, timer, list, help"
            cmd = self.capability_worker.text_to_text_response(prompt).strip().lower()
            if cmd in ("play", "stop", "timer", "list", "help"):
                return cmd
        except Exception:
            pass
        return "play"

    def extract_timer_duration(self, user_input):
        """Regex first, LLM fallback."""
        text = user_input.lower()
        total = 0
        hour_match = re.search(r"(\d+)\s*hour", text)
        min_match = re.search(r"(\d+)\s*min", text)
        if hour_match:
            total += int(hour_match.group(1)) * 60
        if min_match:
            total += int(min_match.group(1))
        if total > 0:
            return total

        bare_match = re.search(r"(\d+)", text)
        if bare_match and not hour_match:
            val = int(bare_match.group(1))
            if 1 <= val <= 480:
                return val

        try:
            prompt = f"Extract timer duration in MINUTES from: '{user_input}'. Return ONLY a number. Default: 0"
            result = int(self.capability_worker.text_to_text_response(prompt).strip())
            return result if result > 0 else None
        except Exception:
            return None

    # ── UI helpers ────────────────────────────────────────────────

    async def send_music_list(self):
        """Push the visual category list to the client UI."""
        await self.capability_worker.send_data_over_websocket(
            "music-list", {"categories": MUSIC_LIST_DISPLAY}
        )

    async def send_now_playing(self, title, artist):
        """Push now-playing info to the client UI."""
        await self.capability_worker.send_data_over_websocket(
            "music-mode", {"mode": "on", "track": title, "artist": artist}
        )

    async def send_music_off(self):
        await self.capability_worker.send_data_over_websocket(
            "music-mode", {"mode": "off"}
        )

    # ── Playback ──────────────────────────────────────────────────

    async def play_track(self, sound_category):
        query = MUSIC_CATEGORIES.get(sound_category, "slow calm instrumental")
        sound_display = sound_category.replace("_", " ")

        await self.capability_worker.speak(f"Finding {sound_display} for you.")

        audio_bytes = None
        track_title = sound_display
        track_artist = "Audius"

        result = self.search_track_on_audius(query)
        if result:
            track_id, track_title, track_artist = result
            audio_bytes = self.download_track_bytes(track_id)

        if not audio_bytes:
            audio_bytes = self.download_from_url(FALLBACK_URL)
            track_title = "Outro: Turn Off"
            track_artist = "Ewil TheDemonDude"

        if not audio_bytes:
            await self.capability_worker.speak("Couldn't load the music. Please try again.")
            return False

        try:
            self.worker.music_mode_event.set()
            await self.send_now_playing(track_title, track_artist)

            await self.capability_worker.speak(
                f"Now playing {track_title} by {track_artist}."
            )

            await self.capability_worker.play_audio(audio_bytes)

            await self.send_music_off()
            self.worker.music_mode_event.clear()

            self.current_sound = sound_category
            self.current_track_name = track_title
            self.current_artist = track_artist
            self.is_playing = True
            return True

        except Exception:
            await self.send_music_off()
            self.worker.music_mode_event.clear()
            await self.capability_worker.speak("Something went wrong. Please try again.")
            return False

    async def stop_music(self):
        if self.is_playing:
            self.is_playing = False
            self.current_sound = None
            self.current_track_name = None
            self.current_artist = None
            await self.send_music_off()
            self.worker.music_mode_event.clear()
            await self.capability_worker.speak("Music stopped. Sweet dreams!")

    async def set_timer(self, minutes):
        try:
            if self.timer_task:
                self.timer_task.cancel()

            await self.capability_worker.speak(f"Sleep timer set for {minutes} minutes.")

            async def timer_countdown():
                await self.worker.session_tasks.sleep(minutes * 60)
                await self.stop_music()
                await self.capability_worker.speak("Timer's up. Goodnight!")

            self.timer_task = self.worker.session_tasks.create(timer_countdown())
        except Exception:
            await self.capability_worker.speak("Couldn't set the timer. Try again.")

    # ── Request handling ──────────────────────────────────────────

    async def handle_user_request(self, user_input):
        command = self.detect_command(user_input)

        if command == "play":
            sound_category = self.extract_sound_category(user_input)
            await self.play_track(sound_category)
            return True

        elif command == "stop":
            await self.stop_music()
            if self.timer_task:
                self.timer_task.cancel()
            return False

        elif command == "timer":
            duration = self.extract_timer_duration(user_input)
            if duration:
                await self.set_timer(duration)
            else:
                await self.capability_worker.speak(
                    "How many minutes? Say something like timer 30 minutes."
                )
            return True

        elif command == "list":
            await self.send_music_list()
            await self.capability_worker.speak("Here are your options. Just pick one.")
            return True

        else:
            await self.send_music_list()
            await self.capability_worker.speak("Pick something from the list, or say stop.")
            return True

    # ── Main flow ─────────────────────────────────────────────────

    async def run_sleep_music(self):
        category = None
        show_list = False

        if self.initial_request:
            category = self.quick_match_category(self.initial_request)
            # Also check if user explicitly asked for a list
            cmd = self.detect_command(self.initial_request)
            if cmd == "list":
                show_list = True

        if show_list:
            # User asked for the list — show it even if we matched a category
            await self.send_music_list()
            await self.capability_worker.speak("Here's the music menu. What would you like?")
            user_choice = await self.capability_worker.user_response()
            category = self.extract_sound_category(user_choice)
            success = await self.play_track(category)
        elif category:
            # User said e.g. "Play slow music" — go straight to playback
            success = await self.play_track(category)
        else:
            # No clear category in trigger — show list and ask
            await self.send_music_list()
            await self.capability_worker.speak("Here's the music menu. What would you like?")
            user_choice = await self.capability_worker.user_response()
            category = self.extract_sound_category(user_choice)
            success = await self.play_track(category)

        if not success:
            await self.capability_worker.speak("Returning to main menu.")
            self.capability_worker.resume_normal_flow()
            return

        # Interaction loop — short prompt, let user drive
        max_interactions = 20
        for _ in range(max_interactions):
            try:
                response = await self.capability_worker.run_io_loop(
                    "Say change, timer, or stop anytime."
                )
                should_continue = await self.handle_user_request(response)
                if not should_continue:
                    break
            except Exception:
                break

        if self.is_playing:
            await self.stop_music()

        if self.timer_task:
            self.timer_task.cancel()

        self.capability_worker.resume_normal_flow()

    def call(self, worker):
            self.worker = worker
            self.capability_worker = CapabilityWorker(self.worker)
            self.current_sound = None
            self.current_track_name = None
            self.current_artist = None
            self.timer_task = None
            self.is_playing = False
            self.audius_host = None

            # Try to grab the transcription that triggered this capability
            self.initial_request = None
            try:
                self.initial_request = worker.transcription
            except (AttributeError, Exception):
                pass
            if not self.initial_request:
                try:
                    self.initial_request = worker.last_transcription
                except (AttributeError, Exception):
                    pass
            if not self.initial_request:
                try:
                    self.initial_request = worker.current_transcription
                except (AttributeError, Exception):
                    pass

            self.worker.session_tasks.create(self.run_sleep_music())
