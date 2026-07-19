import random

import httpx

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =====================================================================
# AMBIENT SOUNDS — streams ambient/relaxation audio from Freesound.
# Single LLM router decides intent, single play_music streams audio.
# =====================================================================

FREESOUND_BASE = "https://freesound.org/apiv2"

# Categories registry — single source of truth. The LLM router is
# constrained to pick one of these keys (or EXIT / NOT_AMBIENT / NEEDS_INPUT).
#   query: Freesound search terms
#   label: human-friendly spoken form, must read naturally in templates
CATEGORIES = {
    "rain":        {"query": "rain ambient",         "label": "rain sounds"},
    "thunder":     {"query": "thunderstorm rain ambient", "label": "thunder sounds"},
    "wind":        {"query": "wind ambient",         "label": "wind sounds"},
    "ocean":       {"query": "ocean waves",          "label": "ocean waves"},
    "river":       {"query": "river stream",         "label": "river sounds"},
    "waterfall":   {"query": "waterfall",            "label": "waterfall sounds"},
    "forest":      {"query": "forest birds ambient", "label": "forest sounds"},
    "crickets":    {"query": "crickets night",       "label": "crickets at night"},
    "fire":        {"query": "campfire crackling",   "label": "campfire sounds"},
    "cafe":        {"query": "cafe ambience",        "label": "cafe ambience"},
    "city":        {"query": "city traffic ambient", "label": "city ambience"},
    "white_noise": {"query": "white noise",          "label": "white noise"},
    "pink_noise":  {"query": "pink noise",           "label": "pink noise"},
    "brown_noise": {"query": "brown noise",          "label": "brown noise"},
    "fan":         {"query": "fan hum ambient",      "label": "fan sounds"},
    "focus":       {"query": "ambient study",        "label": "focus sounds"},
    "sleep":       {"query": "ambient pad sleep",    "label": "sleep sounds"},
    "meditation":  {"query": "ambient meditation",   "label": "meditation sounds"},
}


def _build_router_prompt() -> str:
    """Build the LLM router prompt dynamically from CATEGORIES so
    adding/removing a category automatically updates the LLM's options."""
    catalog = "\n".join(
        f"  {key:<12}— {meta['label']}"
        for key, meta in CATEGORIES.items()
    )
    return (
        "You route voice input for an ambient sound player.\n\n"
        "WHAT IT DOES:\n"
        "Streams ambient/relaxation sounds (rain, ocean, fire, forest, "
        "etc.) one at a time. It does NOT play music, songs, artists, "
        "specific tracks, or genres like jazz/rock/pop.\n\n"
        "AVAILABLE CATEGORIES (key on left, what it plays on right):\n"
        f"{catalog}\n\n"
        "PICK EXACTLY ONE OUTCOME:\n"
        "  <category key>  — user wants one of the categories above\n"
        "  EXIT            — user wants to stop/quit/leave the session\n"
        "  NOT_AMBIENT     — user asked for music outside ambient\n"
        "                    (jazz, rock, pop, a specific song/artist, etc.)\n"
        "  NEEDS_INPUT     — message has no actionable content\n"
        "                    ('hey', 'test', 'ambient player', '')\n\n"
        "RULES:\n"
        "- If the user wants ANY ambient sound, pick the closest category.\n"
        "  Vague requests like 'play anything', 'something relaxing', or\n"
        "  'play me something good' should still pick the best-fit category\n"
        "  (e.g. rain, forest, meditation).\n"
        "- Return EXIT only for clear stop/quit/leave/done/bye intent.\n"
        "- Return NOT_AMBIENT only when the request is clearly outside\n"
        "  the ambient set (specific song/artist/non-ambient genre).\n\n"
        "EXAMPLES:\n"
        "  'play rain'              -> rain\n"
        "  'ocean for a while'      -> ocean\n"
        "  'something cozy'         -> fire\n"
        "  'help me focus'          -> focus\n"
        "  'play anything'          -> rain   (best fit)\n"
        "  'something calm'         -> meditation\n"
        "  'play jazz'              -> NOT_AMBIENT\n"
        "  'play taylor swift'      -> NOT_AMBIENT\n"
        "  'stop' / 'exit' / 'bye'  -> EXIT\n"
        "  'ambient player'         -> NEEDS_INPUT\n"
        "  'hey'                    -> NEEDS_INPUT\n\n"
        "User said: '{text}'\n\n"
        "Reply with ONLY one token: a category key, EXIT, NOT_AMBIENT, "
        "or NEEDS_INPUT. No punctuation, no explanation."
    )


ROUTER_PROMPT = _build_router_prompt()


# Single combined announcement spoken before play_music runs. Long enough
# (~15-22 words, ~5-7s spoken) to cover the silent gap while Freesound
# searches and the stream opens — so audio comes in right as the speak
# finishes, with no awkward dead air.
PLAY_ANNOUNCEMENTS = [
    "Alright, getting some {label} ready. Just a moment to set things up. "
    "{stop_hint}",
    "Sure — finding some {label} for you. One moment, then we'll drift in. "
    "{stop_hint}",
    "Cueing up some {label}, just a moment to find the right one. "
    "{stop_hint}",
    "Pulling up some {label} now. Give me a beat, then we'll ease in. "
    "{stop_hint}",
    "Setting up some {label} for you, hang with me for just a sec. "
    "{stop_hint}",
]

STOP_HINTS = [
    "Say stop whenever you'd like.",
    "Stop me anytime.",
    "Let me know when you've had enough.",
    "Say stop to ease out.",
    "Just say stop when you're ready.",
]

# Advertise breadth — touch one category from each group so users
# learn what's available without listing all 18.
INTRO_PROMPTS = [
    "Want me to play some white, pink, or brown noise, or I can play "
    "rain, ocean, or campfire sounds?",
    "I can play rain, ocean, or fire sounds — or maybe white noise, "
    "focus, or sleep sounds. What feels right?",
    "Want me to drift you into rain, ocean, or cafe sounds, or I can "
    "do white noise, focus, or sleep sounds?",
    "I can play forest, fire, or rain — or noise, focus, or meditation "
    "sounds. What sounds good?",
]

NOT_AMBIENT_REPLIES = [
    "I only do ambient — rain, ocean, fire, cafe, forest, white noise, "
    "focus, sleep, and the like. What kind of mood are you after?",
    "That one's outside my range. I do rain, ocean, fire, cafe, white "
    "noise, focus and sleep sounds. Want any of those?",
    "Not built for songs — I'm here for ambient soundscapes. Rain, ocean, "
    "campfire, cafe, focus, sleep. What sounds good?",
    "I stick to ambient sounds — nature, fire, cafe, noise, focus, sleep. "
    "Want me to try one of those instead?",
]

CONTINUE_PROMPTS = [
    "Alright. Want me to play some rain, ocean, or campfire next — or "
    "maybe white noise, focus, or sleep sounds? Or wrap up?",
    "Done with that one. I can do rain, fire, or cafe ambience — or "
    "noise, focus, or sleep sounds. Or call it here?",
    "Okay. Want to drift into rain, ocean, or campfire next? Or maybe "
    "white noise, focus, or meditation sounds? Or are we done?",
    "All set. I can play rain, fire, or ocean — or white noise, focus, "
    "or sleep sounds. Or wrap up for now?",
]

GOODBYE_REPLIES = [
    "Take care — come back when you need a moment.",
    "Be well. I'll be here when you want to slow down again.",
    "Catch you later — enjoy the quiet.",
    "Done for now. Hope you found your moment.",
]


class AmbientPlayerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    freesound_key: str = ""

    # {{register capability}}

    # ---- Helpers ----------------------------------------------------

    def _err(self, msg: str):
        self.worker.editor_logging_handler.error(msg)

    # ---- Intent router ----------------------------------------------

    def _route_intent(self, text: str) -> str:
        """Single LLM call. Returns a CATEGORIES key, EXIT, NOT_AMBIENT,
        or NEEDS_INPUT."""
        if not text or not text.strip():
            return "NEEDS_INPUT"
        try:
            raw = self.capability_worker.text_to_text_response(
                ROUTER_PROMPT.format(text=text.strip()),
                [],
            )
            raw_str = (raw or "").strip()
            if not raw_str:
                return "NEEDS_INPUT"
            # First token, lowercase, strip non-letters/underscores.
            first = ""
            for ch in raw_str.split()[0].lower():
                if ch.isalpha() or ch == "_":
                    first += ch
            if first == "exit":
                return "EXIT"
            if first in ("not_ambient", "notambient"):
                return "NOT_AMBIENT"
            if first in ("needs_input", "needsinput"):
                return "NEEDS_INPUT"
            if first in CATEGORIES:
                return first
            self._err(f"[Ambient] off-list intent: {first!r}")
            return "NEEDS_INPUT"
        except Exception as e:
            self._err(f"[Ambient] router failed: {e}")
            return "NEEDS_INPUT"

    # ---- Search + stream --------------------------------------------

    async def play_music(self, category: str) -> str:
        """Search Freesound and stream the audio.
        Returns 'STOPPED' if user interrupted, 'FINISHED' otherwise.
        Announcement is spoken in run() before calling this — this
        function does search + stream silently. Errors are logged only."""
        meta = CATEGORIES[category]

        # Search Freesound.
        params = {
            "query": meta["query"],
            "filter": "duration:[60 TO 1800] type:(mp3 OR wav)",
            "sort": "rating_desc",
            "fields": "id,name,previews,username",
            "page_size": 15,
            "token": self.freesound_key,
        }
        url = f"{FREESOUND_BASE}/search/"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 401:
                    await self.capability_worker.speak(
                        "Your Freesound key isn't working. Check it in Settings."
                    )
                    return "FINISHED"
                if resp.status_code != 200:
                    self._err(f"[Ambient] search HTTP {resp.status_code}")
                    return "FINISHED"
                results = resp.json().get("results", []) or []
                results = [r for r in results if r.get("previews", {}).get("preview-hq-mp3")]
        except Exception as e:
            self._err(f"[Ambient] search error: {e}")
            return "FINISHED"

        if not results:
            self._err(f"[Ambient] no playable results for category='{category}'")
            return "FINISHED"

        sound = random.choice(results[:5])
        stream_url = sound.get("previews", {}).get("preview-hq-mp3")
        if not stream_url:
            self._err(f"[Ambient] picked sound has no preview URL (id={sound.get('id')})")
            return "FINISHED"

        # Stream the audio chunk by chunk. Announcement was already spoken
        # in run() before this call, so go straight into streaming.
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET", stream_url, follow_redirects=True
                ) as stream_resp:
                    if stream_resp.status_code != 200:
                        self._err(f"[Ambient] stream HTTP {stream_resp.status_code}")
                        return "FINISHED"
                    await self.capability_worker.stream_init()
                    try:
                        async for chunk in stream_resp.aiter_bytes(chunk_size=25 * 1024):
                            if not chunk:
                                continue
                            if self.worker.music_mode_stop_event.is_set():
                                return "STOPPED"
                            while self.worker.music_mode_pause_event.is_set():
                                if self.worker.music_mode_stop_event.is_set():
                                    return "STOPPED"
                                await self.worker.session_tasks.sleep(0.1)
                            await self.capability_worker.send_audio_data_in_stream(chunk)
                    finally:
                        await self.capability_worker.stream_end()
        except Exception as e:
            self._err(f"[Ambient] stream error: {e}")
            return "FINISHED"

        return "FINISHED"

    # ---- Main session loop ------------------------------------------

    async def run(self):
        try:
            self.freesound_key = (
                self.capability_worker.get_api_keys("freesound_api_key") or ""
            )
        except Exception as e:
            self._err(f"[Ambient] failed to load API key: {e}")
            self.freesound_key = ""

        # Enter music mode for the whole session.
        try:
            self.worker.music_mode_event.set()
            await self.capability_worker.send_data_over_websocket(
                "music-mode", {"mode": "on"}
            )
        except Exception as e:
            self._err(f"[Ambient] music mode on failed: {e}")

        try:
            if not self.freesound_key:
                await self.capability_worker.speak(
                    "Ambient Sounds needs a Freesound API key. "
                    "Add freesound_api_key in OpenHome Settings."
                )
                return

            try:
                msg = await self.capability_worker.wait_for_complete_transcription()
            except Exception as e:
                self._err(f"[Ambient] transcription failed: {e}")
                msg = ""
            msg = msg if isinstance(msg, str) else ""

            while True:
                intent = self._route_intent(msg)

                if intent == "EXIT":
                    await self.capability_worker.speak(random.choice(GOODBYE_REPLIES))
                    return

                if intent == "NEEDS_INPUT":
                    await self.capability_worker.speak(random.choice(INTRO_PROMPTS))
                    msg = await self.capability_worker.user_response()
                    continue

                if intent == "NOT_AMBIENT":
                    await self.capability_worker.speak(random.choice(NOT_AMBIENT_REPLIES))
                    msg = await self.capability_worker.user_response()
                    continue

                # Category path: single long announcement covers the
                # search/stream-open silence, then play_music streams.
                label = CATEGORIES[intent]["label"]
                await self.capability_worker.speak(
                    random.choice(PLAY_ANNOUNCEMENTS).format(
                        label=label, stop_hint=random.choice(STOP_HINTS)
                    )
                )
                await self.play_music(intent)

                await self.capability_worker.speak(random.choice(CONTINUE_PROMPTS))

                msg = await self.capability_worker.user_response()

        except Exception as e:
            self._err(f"[Ambient] run error: {e}")
        finally:
            try:
                await self.capability_worker.send_data_over_websocket(
                    "music-mode", {"mode": "off"}
                )
            except Exception as e:
                self._err(f"[Ambient] music mode off failed: {e}")
            try:
                await self.worker.session_tasks.sleep(1.0)
            except Exception:
                pass
            self.capability_worker.resume_normal_flow()

    # ---- Entry point ------------------------------------------------

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
