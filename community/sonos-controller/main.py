"""
Sonos Controller OpenHome Ability

Uses soco-cli (`sonos` command, installed globally) via LocalLink.
No helper script needed — commands run directly on local machine.

Trigger: say "sonos" to open a command session.
"""

import json

from src.agent.capability import MatchingCapability


from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# ─── Configuration ────────────────────────────────────────────────────────────

PREFS_FILE = "sonos_ability_prefs.json"

TRIGGER_WORDS = ["sonos"]

EXIT_WORDS = [
    "done", "exit", "stop", "quit", "bye", "goodbye",
    "nothing else", "that's all", "that's it", "i'm done",
]

SPOTIFY_CLIENT_ID = "XXXXXXXXXXXXXXXX"
SPOTIFY_CLIENT_SECRET = "XXXXXXXXXXXXXXXX"

# Apple Music — MusicKit credentials (fill in to enable)
# Get from developer.apple.com → Certificates, Identifiers & Profiles → Keys
APPLE_TEAM_ID = ""            # 10-char Team ID
APPLE_KEY_ID = ""             # 10-char MusicKit Key ID
APPLE_PRIVATE_KEY_PATH = ""   # path to .p8 file on local machine, e.g. /home/user/AuthKey_XXXXXXXXXX.p8
APPLE_STOREFRONT = "us"       # ISO 3166-1 alpha-2 storefront code

# ─── Ability Class ────────────────────────────────────────────────────────────


class SonosControllerCapability(MatchingCapability):

    class _ExitSession(Exception):
        """Raised to cleanly exit the session loop from any depth."""
        """
        Controls Sonos via soco-cli over LocalLink.

    Say "sonos" to open session, then:
      play / pause / next / previous
      volume up/down/set N
      mute / unmute
      shuffle / repeat / crossfade on|off
      play favorite <name> / play playlist <name>
      what's playing / list favorites / list rooms
      pause all / resume all
      sleep timer / group rooms / ungroup
      set default room
    Exit word closes session.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    current_room: str = None
    available_rooms: list = None

    # Do not change following tag of register capability
    #{{register capability}}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.log("=== Sonos ability call() invoked ===")

        self.current_room = None
        self.available_rooms = []

        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.log("=== Sonos ability STARTED ===")
            await self._boot()
        except self._ExitSession:
            pass
        except Exception as e:
            self.log_err(f"Unhandled error in run(): {e}")
            await self.capability_worker.speak("Something went wrong. Try again.")
        finally:
            self.log("=== Sonos ability STOPPED ===")
            self.capability_worker.resume_normal_flow()

    async def _boot(self):
        await self._load_prefs()

        rooms = await self._fetch_rooms()
        if not rooms:
            await self.capability_worker.speak(
                "Can't find Sonos speakers. Check they're on the same network."
            )
            return

        self.available_rooms = rooms

        if self.current_room and self.current_room not in self.available_rooms:
            self.log(f"Saved room '{self.current_room}' gone, clearing.")
            self.current_room = None

        if not self.current_room and len(self.available_rooms) == 1:
            self.current_room = self.available_rooms[0]

        room_hint = f" Defaulting to {self.current_room}." if self.current_room else ""
        await self.capability_worker.speak(f"Sonos ready.{room_hint} What do you want?")

        await self._run_session()

    # ── Command Loop ──────────────────────────────────────────────────────────

    async def _run_session(self):
        while True:
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                continue

            if self._is_exit(user_input):
                await self.capability_worker.speak("Later.")
                return

            intent = self._classify_intent(user_input)
            self.log(f"Intent: {intent}")
            await self._handle_intent(intent)

    async def _prompt_user(self, prompt: str) -> str | None:
        """Speak prompt, collect response. Returns None if user exits."""
        await self.capability_worker.speak(prompt)
        response = await self.capability_worker.user_response()
        if response and self._is_exit(response):
            await self.capability_worker.speak("Later.")
            raise self._ExitSession()
        return response

    # ── Intent Classification ─────────────────────────────────────────────────

    def _classify_intent(self, user_input: str) -> dict:
        rooms_str = ", ".join(self.available_rooms) if self.available_rooms else "none"
        current = self.current_room or "none selected"

        prompt = (
            f"Available Sonos rooms: {rooms_str}\n"
            f"Current default room: {current}\n\n"
            "Classify the Sonos control intent. "
            "Return ONLY valid JSON, no markdown.\n\n"
            "Allowed intents:\n"
            "  play, pause, playpause, next, previous,\n"
            "  volume_up, volume_down, volume_set,\n"
            "  mute, unmute, toggle_mute,\n"
            "  shuffle_on, shuffle_off, repeat_on, repeat_off, crossfade_on, crossfade_off,\n"
            "  play_search, play_favorite, play_playlist, play_spotify, play_apple_music,\n"
            "  what_playing, list_favorites, list_rooms,\n"
            "  set_default_room, pause_all, resume_all,\n"
            "  sleep, group_rooms, ungroup, unknown\n\n"
            "Use play_apple_music when user says 'on apple music' or 'from apple music' or explicitly wants Apple Music.\n"
            "Use play_spotify when user says 'on spotify' or 'from spotify' or explicitly wants Spotify.\n"
            "Use play_search when user says 'play X' without specifying source, favorite, or playlist.\n"
            "Use play_favorite only when user explicitly says 'favorite'. "
            "Use play_playlist only when user explicitly says 'playlist'.\n\n"
            "For play_search, play_spotify, and play_apple_music: set media_type based on what the user asked for.\n"
            '  "track" — default, or user says "song", "track"\n'
            '  "album" — user says "album", "the album X"\n'
            '  "playlist" — user says "playlist", "the playlist X"\n'
            "Strip the media type word from the name field (e.g. 'play the album Abbey Road' → name='Abbey Road', media_type='album').\n"
            "If the user specifies an artist (e.g. 'play Woods by Mac Miller', 'play something by Radiohead'), "
            "set artist to the artist name and name to the song/album/playlist name. "
            "Strip 'by' from both fields.\n\n"
            "Schema: "
            '{"intent":"<intent>","room":"<room or null>","value":<number or null>,"name":"<string or null>","artist":"<string or null>","media_type":"<track|album|playlist or null>"}\n\n'
            f'User said: "{user_input}"'
        )

        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            self.log_err(f"JSON parse failed: {clean[:200]}")
            return {"intent": "unknown"}

    # ── Intent Router ─────────────────────────────────────────────────────────

    async def _handle_intent(self, intent: dict) -> bool:
        action = intent.get("intent", "unknown")
        room = intent.get("room") or self.current_room
        value = intent.get("value")
        name = intent.get("name")
        media_type = intent.get("media_type") or "track"
        artist = intent.get("artist")

        room_free = {
            "pause_all", "resume_all", "list_favorites",
            "list_rooms", "set_default_room", "unknown",
        }

        if action not in room_free and not room and len(self.available_rooms) > 1:
            preview = ", ".join(self.available_rooms[:4])
            response = await self._prompt_user(f"Which room? I see {preview}.")
            matched = self._match_room(response)
            if matched:
                self.current_room = matched
                intent["room"] = matched
                return await self._handle_intent(intent)
            await self.capability_worker.speak(f"Didn't catch that. Options: {preview}.")
            return False

        # ── Playback ──
        if action == "play":
            await self.capability_worker.speak("Resuming...")
            ok = await self._action(room, "", "play")
            if ok:
                await self._announce_now_playing(room)
            else:
                await self.capability_worker.speak("Couldn't resume.")
            return ok

        if action == "pause":
            await self.capability_worker.speak("Pausing...")
            ok = await self._action(room, "", "pause")
            if ok:
                await self.capability_worker.speak("Paused.")
            return ok

        if action == "playpause":
            await self.capability_worker.speak("Toggling...")
            ok = await self._action(room, "", "playpause")
            if ok:
                await self._announce_now_playing(room)
            return ok

        if action == "next":
            await self.capability_worker.speak("Skipping...")
            ok = await self._action(room, "", "next")
            if ok:
                await self._announce_now_playing(room)
            return ok

        if action == "previous":
            await self.capability_worker.speak("Going back...")
            ok = await self._action(room, "", "prev")
            if ok:
                await self._announce_now_playing(room)
            return ok

        # ── Volume ──
        if action == "volume_up":
            step = int(value) if value else 5
            await self.capability_worker.speak("Turning up...")
            ok = await self._action(room, "", "relative_volume", f"+{step}")
            if ok:
                await self.capability_worker.speak("Done.")
            return ok

        if action == "volume_down":
            step = int(value) if value else 5
            await self.capability_worker.speak("Turning down...")
            ok = await self._action(room, "", "relative_volume", f"-{step}")
            if ok:
                await self.capability_worker.speak("Done.")
            return ok

        if action == "volume_set":
            if value is None:
                response = await self._prompt_user("What volume? 0 to 100.")
                value = self._extract_number(response)
                if value is None or not (0 <= value <= 100):
                    await self.capability_worker.speak("Say a number 0 to 100.")
                    return False
            vol = max(0, min(100, int(value)))
            await self.capability_worker.speak(f"Setting to {vol}...")
            ok = await self._action(room, "", "volume", vol)
            if ok:
                await self.capability_worker.speak(f"Volume set to {vol}.")
            return ok

        # ── Mute ──
        if action == "mute":
            await self.capability_worker.speak("Muting...")
            ok = await self._action(room, "", "mute", "on")
            if ok:
                await self.capability_worker.speak("Muted.")
            return ok

        if action == "unmute":
            await self.capability_worker.speak("Unmuting...")
            ok = await self._action(room, "", "mute", "off")
            if ok:
                await self.capability_worker.speak("Unmuted.")
            return ok

        if action == "toggle_mute":
            await self.capability_worker.speak("Toggling mute...")
            result = await self._sonos(room, "mute")
            if not result["ok"]:
                await self.capability_worker.speak(f"Couldn't check mute state on {room}.")
                return False
            current_mute = result["stdout"].strip().lower()
            new_state = "off" if current_mute == "on" else "on"
            ok = await self._action(room, "", "mute", new_state)
            if ok:
                await self.capability_worker.speak("Muted." if new_state == "on" else "Unmuted.")
            return ok

        # ── Play mode ──
        if action == "shuffle_on":
            await self.capability_worker.speak("Setting shuffle...")
            ok = await self._action(room, "", "shuffle", "on")
            if ok:
                await self.capability_worker.speak("Shuffle on.")
            return ok

        if action == "shuffle_off":
            await self.capability_worker.speak("Setting shuffle...")
            ok = await self._action(room, "", "shuffle", "off")
            if ok:
                await self.capability_worker.speak("Shuffle off.")
            return ok

        if action == "repeat_on":
            await self.capability_worker.speak("Setting repeat...")
            ok = await self._action(room, "", "repeat", "all")
            if ok:
                await self.capability_worker.speak("Repeat on.")
            return ok

        if action == "repeat_off":
            await self.capability_worker.speak("Setting repeat...")
            ok = await self._action(room, "", "repeat", "off")
            if ok:
                await self.capability_worker.speak("Repeat off.")
            return ok

        if action == "crossfade_on":
            await self.capability_worker.speak("Setting crossfade...")
            ok = await self._action(room, "", "cross_fade", "on")
            if ok:
                await self.capability_worker.speak("Crossfade on.")
            return ok

        if action == "crossfade_off":
            await self.capability_worker.speak("Setting crossfade...")
            ok = await self._action(room, "", "cross_fade", "off")
            if ok:
                await self.capability_worker.speak("Crossfade off.")
            return ok

        # ── Content ──
        if action == "play_search":
            if not name:
                name = await self._prompt_user("What do you want to play?")
            if not name:
                return False
            await self.capability_worker.speak("Searching...")
            # Try Sonos favorite first, then Sonos playlist, then Spotify
            fav_result = await self._sonos(room, "play_fav", f'"{name}"')
            if fav_result["ok"]:
                await self._announce_now_playing(room)
                return True
            pl_result = await self._sonos(room, "add_playlist_to_queue", f'"{name}"')
            if pl_result["ok"]:
                await self._sonos(room, "play")
                await self._announce_now_playing(room)
                return True
            self.log(f"Not in favorites/playlists, falling back to Spotify for {name!r} artist={artist!r} (type={media_type})")
            uri = await self._spotify_search(name, media_type, artist)
            if uri:
                self.log(f"Spotify URI found: {uri}")
                if await self._play_spotify_uri(room, uri, media_type):
                    await self._announce_now_playing(room)
                    return True
                await self.capability_worker.speak("Found it on Spotify but Sonos couldn't play it.")
                return False
            await self.capability_worker.speak(f"Couldn't find '{name}' anywhere.")
            return False

        if action == "play_spotify":
            if not name:
                name = await self._prompt_user("What do you want from Spotify?")
            if not name:
                return False
            self.log(f"Spotify direct play: {name!r} artist={artist!r} (type={media_type})")
            await self.capability_worker.speak("Searching...")
            uri = await self._spotify_search(name, media_type, artist)
            if not uri:
                await self.capability_worker.speak(f"Nothing found on Spotify for '{name}'.")
                return False
            self.log(f"Spotify URI found: {uri}")
            if await self._play_spotify_uri(room, uri, media_type):
                await self._announce_now_playing(room)
                return True
            await self.capability_worker.speak("Found it on Spotify but Sonos couldn't play it.")
            return False

        if action == "play_apple_music":
            if not name:
                name = await self._prompt_user("What do you want from Apple Music?")
            if not name:
                return False
            self.log(f"Apple Music direct play: {name!r}")
            await self.capability_worker.speak("Searching...")
            uri = await self._apple_music_search(name)
            if not uri:
                await self.capability_worker.speak(f"Nothing found on Apple Music for '{name}'.")
                return False
            self.log(f"Apple Music URI found: {uri}, sending to Sonos pfq")
            result = await self._sonos(room, "play_uri", f'"{uri}"')
            if result["ok"]:
                await self._announce_now_playing(room)
                return True
            self.log_err(f"Sonos play_uri failed for Apple Music URI {uri} — URI format may need adjustment (see TODO in _apple_music_search)")
            await self.capability_worker.speak("Found it on Apple Music but Sonos couldn't play it.")
            return False

        if action == "play_favorite":
            if not name:
                name = await self._prompt_user("Which favorite?")
            if not name:
                return False
            await self.capability_worker.speak("Searching...")
            ok = await self._action(room, "", "play_fav", f'"{name}"')
            if ok:
                await self._announce_now_playing(room)
            else:
                await self.capability_worker.speak(f"Couldn't find favorite '{name}'.")
            return ok

        if action == "play_playlist":
            if not name:
                name = await self._prompt_user("Which playlist?")
            if not name:
                return False
            await self.capability_worker.speak("Searching...")
            ok = await self._action(room, "", "add_playlist_to_queue", f'"{name}"')
            if ok:
                await self._action(room, "", "play")
                await self._announce_now_playing(room)
                return True
            await self.capability_worker.speak(f"Couldn't find playlist '{name}'.")
            return False

        # ── Status queries ──
        if action == "what_playing":
            await self._speak_now_playing(room)
            return True

        if action == "list_favorites":
            target = room or (self.available_rooms[0] if self.available_rooms else None)
            await self._speak_favorites(target)
            return True

        if action == "list_rooms":
            await self._speak_rooms()
            return True

        # ── Preferences ──
        if action == "set_default_room":
            target = room or name
            if not target:
                target = await self._prompt_user("Which room should I default to?")
            matched = self._match_room(target) if target else None
            if matched:
                self.current_room = matched
                await self._save_prefs()
                await self.capability_worker.speak(f"Got it, defaulting to {matched}.")
                return True
            rooms_str = ", ".join(self.available_rooms[:4])
            await self.capability_worker.speak(f"Didn't find that room. Try: {rooms_str}.")
            return False

        # ── Global actions ──
        if action == "pause_all":
            anchor = self.current_room or self.available_rooms[0]
            result = await self._sonos(anchor, "pause_all")
            await self.capability_worker.speak(
                "Paused everything." if result["ok"] else "Couldn't pause all rooms."
            )
            return result["ok"]

        if action == "resume_all":
            result = await self._run_cmd('sonos ":all" play')
            await self.capability_worker.speak(
                "Resuming all rooms." if result["ok"] else "Couldn't resume all rooms."
            )
            return result["ok"]

        # ── Sleep timer ──
        if action == "sleep":
            minutes = int(value) if value else 30
            return await self._action(room, f"Sleep timer set for {minutes} minutes.", "sleep_timer", f"{minutes}m")

        # ── Grouping ──
        if action == "group_rooms":
            response = await self._prompt_user("Which rooms? Say the names.")
            lower = response.lower() if response else ""
            mentioned = [r for r in self.available_rooms if r.lower() in lower]
            if len(mentioned) >= 2:
                leader, joiner = mentioned[0], mentioned[1]
                result = await self._sonos(joiner, "group", f'"{leader}"')
                if result["ok"]:
                    await self.capability_worker.speak(f"Grouped {joiner} with {leader}.")
                    return True
                await self.capability_worker.speak("Couldn't group those rooms.")
                return False
            elif len(mentioned) == 1 and self.current_room:
                joiner = mentioned[0]
                result = await self._sonos(joiner, "group", f'"{self.current_room}"')
                if result["ok"]:
                    await self.capability_worker.speak(f"Grouped {joiner} with {self.current_room}.")
                    return True
                await self.capability_worker.speak("Couldn't group those rooms.")
                return False
            await self.capability_worker.speak(
                f"Need two room names. Available: {', '.join(self.available_rooms[:4])}."
            )
            return False

        if action == "ungroup":
            return await self._action(room, f"Separated {room} from the group.", "ungroup")

        # ── Unknown ──
        response = self.capability_worker.text_to_text_response(
            f'User said: "{intent}". '
            "You are a concise voice assistant for Sonos. "
            "In 1-2 sentences say what commands you support: "
            "play, pause, volume, next/previous, shuffle, repeat, "
            "favorites, playlists, what's playing, pause all, sleep timer, grouping."
        )
        await self.capability_worker.speak(response)
        return False

    # ── soco-cli Helpers ──────────────────────────────────────────────────────

    async def _run_cmd(self, cmd: str) -> dict:
        """Run arbitrary command via LocalLink. Returns {ok, stdout, stderr}."""
        self.log(f"CMD → {cmd}")
        raw = await self.capability_worker.exec_local_command(cmd)
        if isinstance(raw, dict):
            data = raw.get("data", raw)
            if isinstance(data, dict):
                result = {
                    "ok": data.get("returncode", 1) == 0,
                    "stdout": data.get("stdout", "").strip(),
                    "stderr": data.get("stderr", "").strip(),
                }
                rc = data.get("returncode", "?")
                if result["ok"]:
                    self.log(f"CMD OK (rc={rc}) stdout={result['stdout'][:200]!r}")
                else:
                    self.log_err(f"CMD FAIL (rc={rc}) stdout={result['stdout'][:200]!r} stderr={result['stderr'][:200]!r}")
                return result
        self.log_err(f"CMD bad response type={type(raw).__name__} raw={str(raw)[:200]!r}")
        return {"ok": False, "stdout": "", "stderr": str(raw)}

    async def _sonos(self, room: str, *args) -> dict:
        """Run: sonos -l "<room>" <args>"""
        safe = room.replace('"', '\\"')
        args_str = " ".join(str(a) for a in args)
        self.log(f"SONOS [{room}] {args_str}")
        return await self._run_cmd(f'sonos -l "{safe}" {args_str}')

    async def _action(self, room: str, success_msg: str, *args) -> bool:
        """Run room command, speak result."""
        if not room:
            await self.capability_worker.speak("Which room?")
            return False
        result = await self._sonos(room, *args)
        if result["ok"]:
            if success_msg:
                await self.capability_worker.speak(success_msg)
            return True
        self.log_err(f"Failed ({' '.join(str(a) for a in args)} on {room}): {result['stderr']}")
        await self.capability_worker.speak(f"Couldn't do that on {room}.")
        return False

    async def _fetch_rooms(self) -> list | None:
        """Run sonos-discover, parse room names from table output."""
        self.log("Discovering Sonos rooms via sonos-discover...")
        result = await self._run_cmd("sonos-discover")
        if not result["stdout"]:
            self.log_err("sonos-discover returned no output")
            return None
        rooms = []
        import re
        for line in result["stdout"].splitlines():
            # Data rows contain an IP address — room name is text before it
            match = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', line)
            if match:
                name = line[:match.start()].strip()
                if name:
                    rooms.append(name)
        if rooms:
            self.log(f"Discovered rooms: {rooms}")
        else:
            self.log_err(f"No rooms parsed from output: {result['stdout'][:300]!r}")
        return rooms if rooms else None

    # ── Status / Query ────────────────────────────────────────────────────────

    async def _announce_now_playing(self, room: str):
        """Short announcement of what just started playing. Fetches track info from Sonos."""
        if not room:
            return
        track_result = await self._sonos(room, "track")
        if not track_result["ok"]:
            return
        title = ""
        artist = ""
        for line in track_result["stdout"].splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip()
                if key == "title":
                    title = val
                elif key == "artist":
                    artist = val
        if artist and title:
            await self.capability_worker.speak(f"Now playing '{title}' by {artist}.")
        elif title:
            await self.capability_worker.speak(f"Now playing '{title}'.")

    async def _speak_now_playing(self, room: str):
        if not room:
            if self.available_rooms:
                room = self.available_rooms[0]
            else:
                await self.capability_worker.speak("No rooms to check.")
                return

        state_result = await self._sonos(room, "state")
        track_result = await self._sonos(room, "track")
        vol_result = await self._sonos(room, "volume")

        state = state_result["stdout"] if state_result["ok"] else "STOPPED"
        volume = vol_result["stdout"] if vol_result["ok"] else "?"

        title = ""
        artist = ""
        if track_result["ok"]:
            for line in track_result["stdout"].splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip().lower()
                    val = val.strip()
                    if key == "title":
                        title = val
                    elif key == "artist":
                        artist = val

        if state in ("PLAYING", "TRANSITIONING"):
            if artist and title:
                await self.capability_worker.speak(
                    f"Playing '{title}' by {artist} in {room}, volume {volume}."
                )
            elif title:
                await self.capability_worker.speak(f"Playing '{title}' in {room}, volume {volume}.")
            else:
                await self.capability_worker.speak(f"{room} is playing, volume {volume}.")
        elif state in ("PAUSED_PLAYBACK", "STOPPED"):
            if title:
                suffix = f" by {artist}" if artist else ""
                await self.capability_worker.speak(f"{room} is paused on '{title}'{suffix}.")
            else:
                await self.capability_worker.speak(f"{room} is paused.")
        else:
            await self.capability_worker.speak(f"{room} is {state.lower().replace('_', ' ')}.")

    async def _speak_favorites(self, room: str):
        if not room:
            await self.capability_worker.speak("Need a room to list favorites.")
            return
        result = await self._sonos(room, "list_favs")
        if not result["ok"] or not result["stdout"]:
            await self.capability_worker.speak("Couldn't retrieve favorites.")
            return
        names = [l.strip() for l in result["stdout"].splitlines() if l.strip()]
        if not names:
            await self.capability_worker.speak("No favorites saved.")
            return
        shown = names[:5]
        listed = ", ".join(shown[:-1]) + f" and {shown[-1]}" if len(shown) > 1 else shown[0]
        extra = f" and {len(names) - 5} more" if len(names) > 5 else ""
        await self.capability_worker.speak(f"Favorites: {listed}{extra}. Which would you like?")

    async def _speak_rooms(self):
        if not self.available_rooms:
            await self.capability_worker.speak("No Sonos rooms found.")
            return
        count = len(self.available_rooms)
        if count == 1:
            await self.capability_worker.speak(f"One room: {self.available_rooms[0]}.")
        else:
            listed = ", ".join(self.available_rooms[:-1]) + f" and {self.available_rooms[-1]}"
            await self.capability_worker.speak(f"{count} rooms: {listed}.")

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _load_prefs(self):
        try:
            exists = await self.capability_worker.check_if_file_exists(PREFS_FILE, False)
            if exists:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                prefs = json.loads(raw)
                saved = prefs.get("default_room")
                if saved:
                    self.current_room = saved
        except Exception as e:
            self.log_err(f"Failed to load prefs: {e}")

    async def _save_prefs(self):
        try:
            prefs = {"default_room": self.current_room}
            await self.capability_worker.delete_file(PREFS_FILE, False)
            await self.capability_worker.write_file(PREFS_FILE, json.dumps(prefs), False)
        except Exception as e:
            self.log_err(f"Failed to save prefs: {e}")

    # ── Spotify ───────────────────────────────────────────────────────────────

    async def _play_spotify_uri(self, room: str, uri: str, media_type: str = "track") -> bool:
        """Play a Spotify URI on a room via sharelink."""
        # Convert spotify:type:id → https://open.spotify.com/type/id
        link = uri
        if uri.startswith("spotify:"):
            parts = uri.split(":")
            if len(parts) == 3:
                link = f"https://open.spotify.com/{parts[1]}/{parts[2]}"
        self.log(f"sharelink → {link}")
        share_result = await self._sonos(room, "sharelink", f'"{link}"')
        if not share_result["ok"]:
            self.log_err(f"sharelink failed: {share_result['stderr']}")
            return False
        # sharelink stdout returns queue position of first added track
        queue_pos = share_result["stdout"].strip()
        self.log(f"sharelink returned queue position: {queue_pos!r}")
        if queue_pos:
            play_result = await self._sonos(room, "play_from_queue", queue_pos)
        else:
            self.log_err("sharelink returned no queue position, cannot start playback")
            return False
        if not play_result["ok"]:
            self.log_err(f"play_from_queue failed: {play_result['stderr']}")
            return False
        if media_type == "album":
            self.log("Album detected, setting repeat all")
            await self._sonos(room, "repeat", "all")
        return True

    async def _spotify_token(self) -> str | None:
        """Client Credentials flow → access token."""
        self.log("Requesting Spotify access token...")
        result = await self._run_cmd(
            f'curl -s -X POST "https://accounts.spotify.com/api/token"'
            f' -u "{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"'
            f' -d "grant_type=client_credentials"'
        )
        if not result["ok"] or not result["stdout"]:
            self.log_err("Spotify token request failed — no output")
            return None
        try:
            data = json.loads(result["stdout"])
            token = data.get("access_token")
            if token:
                self.log(f"Spotify token obtained (len={len(token)})")
            else:
                self.log_err(f"Spotify token missing in response: {result['stdout'][:200]!r}")
            return token
        except json.JSONDecodeError as e:
            self.log_err(f"Spotify token JSON parse failed: {e} — raw={result['stdout'][:200]!r}")
            return None

    async def _spotify_search(self, query: str, media_type: str = "track", artist: str = None) -> str | None:
        """Search Spotify. media_type: track, album, or playlist. Returns first URI or None."""
        self.log(f"Spotify search: {query!r} artist={artist!r} (type={media_type})")
        token = await self._spotify_token()
        if not token:
            return None
        safe_query = query.replace('"', "").replace("'", "")
        if artist:
            safe_artist = artist.replace('"', "").replace("'", "")
            safe_query = f"{safe_query} artist:{safe_artist}"
        self.log(f"Spotify searching {media_type}s for {safe_query!r}")
        result = await self._run_cmd(
            f'curl -s -G "https://api.spotify.com/v1/search"'
            f' --data-urlencode "q={safe_query}"'
            f' -d "type={media_type}&limit=5"'
            f' -H "Authorization: Bearer {token}"'
        )
        if not result["ok"] or not result["stdout"]:
            self.log_err(f"Spotify {media_type} search returned no output")
            return None
        try:
            data = json.loads(result["stdout"])
        except json.JSONDecodeError as e:
            self.log_err(f"Spotify {media_type} search JSON parse failed: {e}")
            return None
        items = [i for i in data.get(f"{media_type}s", {}).get("items", []) if i]
        self.log(f"Spotify {media_type} results: {len(items)} non-null items")
        for item in items:
            uri = item.get("uri")
            name = item.get("name", "?")
            self.log(f"Spotify result candidate: {name!r} → {uri}")
            if uri:
                self.log(f"Spotify using: {name!r} ({uri})")
                return uri
        self.log("Spotify search: no results")
        return None

    # ── Apple Music ───────────────────────────────────────────────────────────

    async def _apple_music_token(self) -> str | None:
        """Generate MusicKit ES256 JWT on local machine using cryptography lib."""
        if not APPLE_TEAM_ID or not APPLE_KEY_ID or not APPLE_PRIVATE_KEY_PATH:
            self.log_err("Apple Music credentials not configured — set APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY_PATH")
            return None
        self.log("Generating Apple Music MusicKit JWT...")
        # Build Python one-liner to run on local machine.
        # Uses only double quotes inside so it can be wrapped in single quotes for shlex.
        code = (
            "import time,base64,json;"
            "from cryptography.hazmat.primitives import hashes,serialization;"
            "from cryptography.hazmat.primitives.asymmetric import ec;"
            "from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature;"
            "now=int(time.time());"
            f'h=base64.urlsafe_b64encode(json.dumps({{"alg":"ES256","kid":"{APPLE_KEY_ID}"}}).encode()).rstrip(b"=").decode();'
            f'p=base64.urlsafe_b64encode(json.dumps({{"iss":"{APPLE_TEAM_ID}","iat":now,"exp":now+3600}}).encode()).rstrip(b"=").decode();'
            "m=(h+\".\"+p).encode();"
            f'k=serialization.load_pem_private_key(open("{APPLE_PRIVATE_KEY_PATH}","rb").read(),password=None);'
            "r,s=decode_dss_signature(k.sign(m,ec.ECDSA(hashes.SHA256())));"
            "sig=base64.urlsafe_b64encode(r.to_bytes(32,\"big\")+s.to_bytes(32,\"big\")).rstrip(b\"=\").decode();"
            "print(h+\".\"+p+\".\"+sig)"
        )
        result = await self._run_cmd(f"python3 -c '{code}'")
        if not result["ok"] or not result["stdout"]:
            self.log_err("Apple Music JWT generation failed — ensure `cryptography` is installed: pip install cryptography")
            return None
        token = result["stdout"].strip()
        self.log(f"Apple Music token generated (len={len(token)})")
        return token

    async def _apple_music_search(self, query: str) -> str | None:
        """Search Apple Music catalog. Returns catalog ID or None.
        NOTE: Sonos play_uri format for Apple Music IDs needs verification through testing.
        """
        token = await self._apple_music_token()
        if not token:
            return None
        safe_query = query.replace('"', "").replace("'", "")
        self.log(f"Apple Music searching: {safe_query!r}")
        result = await self._run_cmd(
            f'curl -s -G "https://api.music.apple.com/v1/catalog/{APPLE_STOREFRONT}/search"'
            f' --data-urlencode "term={safe_query}"'
            f' -d "types=playlists,songs,albums&limit=5"'
            f' -H "Authorization: Bearer {token}"'
        )
        if not result["ok"] or not result["stdout"]:
            self.log_err("Apple Music search returned no output")
            return None
        try:
            data = json.loads(result["stdout"])
        except json.JSONDecodeError as e:
            self.log_err(f"Apple Music search JSON parse failed: {e}")
            return None
        results = data.get("results", {})
        for kind in ("playlists", "albums", "songs"):
            items = results.get(kind, {}).get("data", [])
            if items:
                item = items[0]
                name = item.get("attributes", {}).get("name", "?")
                catalog_id = item.get("id", "")
                self.log(f"Apple Music top {kind[:-1]}: {name!r} id={catalog_id}")
                if catalog_id:
                    return catalog_id
        self.log("Apple Music search: no results")
        return None

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _match_room(self, user_input: str) -> str | None:
        lower = user_input.lower()
        for room in self.available_rooms:
            if room.lower() == lower:
                return room
        for room in self.available_rooms:
            if room.lower() in lower or lower in room.lower():
                return room
        words = lower.split()
        for room in self.available_rooms:
            if any(w in room.lower().split() for w in words):
                return room
        return None

    def _extract_number(self, text: str) -> int | None:
        for token in text.split():
            try:
                return int(token.replace("%", "").strip())
            except ValueError:
                continue
        return None

    def _is_exit(self, text: str) -> bool:
        lower = text.lower()
        return any(w in lower for w in EXIT_WORDS)

    def log(self, message: str):
        self.worker.editor_logging_handler.info(f"[SonosAbility] {message}")

    def log_err(self, message: str):
        self.worker.editor_logging_handler.error(f"[SonosAbility] {message}")
