import re
import time
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave"}
REPEAT_PHRASES = {"repeat", "again", "say that again", "repeat last"}
LIST_MORE_PHRASES = {"list more", "more options", "what else", "show more", "more sounds", "more"}

DEFAULT_DURATION_MINUTES = 30
MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 120

INTER_LOOP_GAP_SECONDS = 0.05
# Brief says clips are typically 30–60s; if playback returns much earlier, treat it as an interrupt.
MIN_EXPECTED_CLIP_SECONDS = 30.0
PREFS_FILE = "noise_machine_prefs.json"

SOUNDS: Dict[str, Dict[str, Any]] = {
    "rain": {
        "name": "Rain",
        "file": "rain.mp3",
        "keywords": ["rain", "rain sounds", "rainfall", "drizzle", "shower", "soft rain"],
    },
    "heavy_rain": {
        "name": "Heavy rain",
        "file": "heavy_rain.mp3",
        "keywords": ["heavy rain", "downpour", "pouring rain", "rainstorm", "storm rain"],
    },
    "ocean_waves": {
        "name": "Ocean waves",
        "file": "ocean_waves.mp3",
        "keywords": ["ocean", "waves", "sea", "beach", "shore", "surf", "wave sounds"],
    },
    "river_stream": {
        "name": "River stream",
        "file": "river_stream.mp3",
        "keywords": ["river", "stream", "creek", "brook", "flowing water", "water stream"],
    },
    "white_noise": {
        "name": "White noise",
        "file": "white_noise.mp3",
        "keywords": ["white noise", "static", "hiss", "background noise"],
    },
    "pink_noise": {
        "name": "Pink noise",
        "file": "pink_noise.mp3",
        "keywords": ["pink noise", "soft noise", "gentle noise"],
    },
    "brown_noise": {
        "name": "Brown noise",
        "file": "brown_noise.mp3",
        "keywords": ["brown noise", "deep noise", "low rumble", "bass noise"],
    },
    "forest_birds": {
        "name": "Forest birds",
        "file": "forest_birds.mp3",
        "keywords": ["forest", "birds", "birdsong", "birds chirping", "nature birds", "woods"],
    },
    "crickets": {
        "name": "Crickets",
        "file": "crickets.mp3",
        "keywords": ["crickets", "night crickets", "insects", "night sounds"],
    },
    "campfire": {
        "name": "Campfire",
        "file": "campfire.mp3",
        "keywords": ["campfire", "fire", "fireplace", "crackling", "bonfire", "embers"],
    },
    "wind": {
        "name": "Wind",
        "file": "wind.mp3",
        "keywords": ["wind", "breeze", "gust", "air", "windy"],
    },
    "thunder": {
        "name": "Thunder",
        "file": "thunder.mp3",
        "keywords": ["thunder", "storm", "lightning", "rumble", "thunderstorm"],
    },
    "cafe": {
        "name": "Cafe",
        "file": "cafe.mp3",
        "keywords": ["cafe", "coffee shop", "coffee", "restaurant", "chatter", "ambient chatter"],
    },
    "fan": {
        "name": "Fan",
        "file": "fan.mp3",
        "keywords": ["fan", "fan noise", "fan sound", "hum", "air conditioner", "ac"],
    },
    "waterfall": {
        "name": "Waterfall",
        "file": "waterfall.mp3",
        "keywords": ["waterfall", "falls", "rushing water", "water fall", "cascade"],
    },
}

POPULAR_MENU = ["rain", "ocean_waves", "white_noise", "campfire", "forest_birds"]

_FILLER_WORDS = {
    "for", "about", "around", "like", "maybe", "please", "just", "roughly", "approximately", "set", "play", "it", "to"
}

_NUM_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
_NUM_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_NUM_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_HOUR_WORDS = {"hour", "hours", "hr", "hrs"}
_MIN_WORDS = {"minute", "minutes", "min", "mins"}


def _clean(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokens(text: str) -> List[str]:
    t = _clean(text)
    if not t:
        return []
    toks = t.split()
    out: List[str] = []
    for w in toks:
        if w.endswith("s") and len(w) > 3:
            out.append(w[:-1])
        else:
            out.append(w)
    return out


def _contains_exit(text: str) -> bool:
    toks = set(_tokens(text))
    return any(w in toks for w in EXIT_WORDS)


def _is_repeat(text: str) -> bool:
    t = _clean(text)
    return any(p == t or p in t for p in REPEAT_PHRASES)


def _wants_more(text: str) -> bool:
    t = _clean(text)
    return any(p == t or p in t for p in LIST_MORE_PHRASES)


def _clamp_minutes(m: int) -> int:
    if m < MIN_DURATION_MINUTES:
        return MIN_DURATION_MINUTES
    if m > MAX_DURATION_MINUTES:
        return MAX_DURATION_MINUTES
    return m


def _format_duration(minutes: int) -> str:
    minutes = max(1, int(minutes))
    if minutes < 60:
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    hours = minutes // 60
    rem = minutes % 60
    if rem == 0:
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    hp = f"{hours} hour" if hours == 1 else f"{hours} hours"
    mp = f"{rem} minute" if rem == 1 else f"{rem} minutes"
    return f"{hp} and {mp}"


def _words_to_int(tokens: List[str]) -> Optional[int]:
    toks = [t for t in tokens if t not in {"and"} and t not in _FILLER_WORDS]
    if not toks:
        return None

    if len(toks) == 1 and re.fullmatch(r"\d{1,3}", toks[0]):
        return int(toks[0])

    if len(toks) == 1:
        w = toks[0]
        if w in _NUM_UNITS:
            return _NUM_UNITS[w]
        if w in _NUM_TEENS:
            return _NUM_TEENS[w]
        if w in _NUM_TENS:
            return _NUM_TENS[w]
        if w in {"a", "an"}:
            return 1
        return None

    a, b = toks[0], toks[1]
    if a in _NUM_TENS:
        base = _NUM_TENS[a]
        if b in _NUM_UNITS:
            return base + _NUM_UNITS[b]
        if re.fullmatch(r"\d{1,2}", b):
            return base + int(b)
        return base
    return None


def _user_mentioned_duration(text: str) -> bool:
    t = _clean(text)
    if re.search(r"\b\d+\b", t):
        return True
    for w in ["minute", "minutes", "min", "mins", "hour", "hours", "hr", "hrs", "half"]:
        if w in t:
            return True
    for w in list(_NUM_UNITS.keys()) + list(_NUM_TEENS.keys()) + list(_NUM_TENS.keys()):
        if w in t:
            return True
    return False


def _extract_duration_minutes(text: str) -> Optional[int]:
    t = _clean(text)
    if not t:
        return None

    if "half" in t and "hour" in t and "and" not in t:
        return 30

    if "half" in t and "hour" in t and "and" in t:
        m = re.search(r"\b(\d{1,2})\s*(?:and\s*)?a\s*half\s*(?:hour|hours|hr|hrs)\b", t)
        if m:
            return int(m.group(1)) * 60 + 30
        toks = _tokens(t)
        if "and" in toks:
            and_idx = toks.index("and")
            num = _words_to_int(toks[max(0, and_idx - 2):and_idx])
            if num is not None:
                return int(num) * 60 + 30
        return 90

    fm = re.search(r"\b(\d+(?:\.\d+)?)\s*(hour|hours|hr|hrs)\b", t)
    if fm:
        try:
            return int(float(fm.group(1)) * 60)
        except Exception:
            pass

    toks = _tokens(t)

    def _prev_number(idx: int) -> Optional[int]:
        collected: List[str] = []
        j = idx - 1
        while j >= 0 and len(collected) < 3:
            w = toks[j]
            if w in _FILLER_WORDS:
                j -= 1
                continue
            collected.insert(0, w)
            j -= 1
        if len(collected) >= 2:
            n = _words_to_int(collected[-2:])
            if n is not None:
                return n
        if len(collected) >= 1:
            n = _words_to_int(collected[-1:])
            if n is not None:
                return n
        return None

    hours_total = 0
    minutes_total = 0
    found_unit = False

    for i, w in enumerate(toks):
        if w in _HOUR_WORDS:
            found_unit = True
            n = _prev_number(i)
            if n is None and i - 1 >= 0 and toks[i - 1] in {"a", "an"}:
                n = 1
            if n is not None:
                hours_total += int(n)

        if w in _MIN_WORDS:
            found_unit = True
            n = _prev_number(i)
            if n is None and i - 1 >= 0 and toks[i - 1] in {"a", "an"}:
                n = 1
            if n is not None:
                minutes_total += int(n)

    if found_unit and (hours_total > 0 or minutes_total > 0):
        return hours_total * 60 + minutes_total

    m2 = re.search(r"\b(\d{1,3})\b", t)
    if m2:
        return int(m2.group(1))

    n3 = _words_to_int(toks[:2]) or _words_to_int(toks[:1])
    if n3 is not None:
        return int(n3)

    return None


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _match_sound(user_text: str) -> tuple[Optional[str], float]:
    t = _clean(user_text)
    if not t:
        return None, 0.0

    # Direct shortcuts for very short requests
    if t in {"cafe", "coffee", "restaurant"}:
        return "cafe", 1.0
    if t in {"fan"}:
        return "fan", 1.0
    if t in {"wind", "breeze"}:
        return "wind", 1.0
    if t in {"thunder", "storm"}:
        return "thunder", 1.0

    toks = set(_tokens(t))

    if t in SOUNDS:
        return t, 1.0

    best_key: Optional[str] = None
    best_score = 0.0

    for key, meta in SOUNDS.items():
        name = _clean(meta["name"])
        phrases = [name] + [_clean(k) for k in meta.get("keywords", [])]

        name_toks = set(_tokens(name))
        overlap = len(toks.intersection(name_toks))
        overlap_score = overlap / max(1, len(name_toks))

        phrase_score = 0.0
        for ph in phrases:
            if not ph:
                continue
            if ph in t or t in ph:
                phrase_score = max(phrase_score, 1.0)
                continue
            phrase_score = max(phrase_score, _similarity(t, ph))

        score = max(0.0, min(1.0, 0.55 * phrase_score + 0.45 * overlap_score))

        if score > best_score:
            best_score = score
            best_key = key

    if best_key is None:
        return None, 0.0
    return best_key, best_score


# ---------------------------
# Trigger guard: avoid auto-selecting a sound from generic activation phrases
# ---------------------------
_GENERIC_TRIGGER_WORDS = {"noise", "machine", "sound", "start", "hey", "the", "a", "an", "please", "my", "some", "play", "up"}

_SOUND_HINT_WORDS = set()
for _k, _meta in SOUNDS.items():
    _SOUND_HINT_WORDS.update(_tokens(_meta.get("name", "")))
    for _kw in _meta.get("keywords", []):
        _SOUND_HINT_WORDS.update(_tokens(_kw))

# Remove generic words so "noise machine" doesn't count as a sound hint
_SOUND_HINT_WORDS.discard("noise")
_SOUND_HINT_WORDS.discard("sound")
_SOUND_HINT_WORDS.discard("machine")


def _is_generic_trigger(text: str) -> bool:
    toks = set(_tokens(text))
    if not toks:
        return True
    if toks.issubset(_GENERIC_TRIGGER_WORDS):
        return True
    if toks.intersection(_SOUND_HINT_WORDS):
        return False
    if "noise" in toks and "machine" in toks:
        return True
    return False


class NoiseMachineCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    last_spoken: str = ""
    stop_requested: bool = False

    async def speak(self, text: str) -> None:
        self.last_spoken = text
        await self.capability_worker.speak(text)

    async def listen(self) -> str:
        try:
            msg = await self.capability_worker.user_response()
            return (msg or "").strip()
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Listen failed: {e}")
            return ""

    async def nap(self, seconds: float) -> None:
        await self.worker.session_tasks.sleep(seconds)

    async def set_music_mode(self, on: bool) -> None:
        try:
            if on:
                self.worker.music_mode_event.set()
                await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})
            else:
                await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
                self.worker.music_mode_event.clear()
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"Music mode toggle failed: {e}")

    async def safe_exit(self, message: Optional[str] = None) -> None:
        await self.set_music_mode(False)
        if message:
            await self.speak(message)
        self.capability_worker.resume_normal_flow()

    async def speak_sound_menu(self) -> None:
        popular_names = ", ".join(SOUNDS[k]["name"] for k in POPULAR_MENU)
        await self.speak(
            "Noise machine ready. Popular sounds are: "
            f"{popular_names}. What would you like to hear?"
        )

    async def speak_full_menu(self) -> None:
        first = ["Rain", "Heavy rain", "Ocean waves", "River stream", "White noise", "Pink noise", "Brown noise"]
        second = ["Forest birds", "Crickets", "Campfire", "Wind", "Thunder", "Cafe", "Fan", "Waterfall"]
        await self.speak("Here’s the full list: " + ". ".join(first) + ".")
        await self.nap(0.35)
        await self.speak(". ".join(second) + ". Which one sounds good?")

    async def ask_for_duration_minutes(self) -> int:
        await self.speak("How long should I play it? You can say 30 minutes or 1 hour.")
        ans = await self.listen()
        if _contains_exit(ans):
            await self.safe_exit("Okay.")
            raise RuntimeError("user_exit")

        mins = _extract_duration_minutes(ans)
        if mins is None:
            mins = DEFAULT_DURATION_MINUTES
            await self.speak(f"Alright. I’ll play it for {_format_duration(mins)}. Say stop anytime.")
        return _clamp_minutes(int(mins))

    async def choose_sound(self, trigger_text: str) -> Optional[str]:
        # If trigger is just "noise machine"/generic, do NOT auto-pick a sound.
        if trigger_text and not _is_generic_trigger(trigger_text):
            key, conf = _match_sound(trigger_text)
            if key and conf >= 0.60:
                return key

        await self.speak_sound_menu()
        retries = 0

        while retries < 3:
            ans = await self.listen()
            if _contains_exit(ans):
                await self.safe_exit("Okay.")
                return None
            if not ans:
                retries += 1
                await self.speak("What sound would you like?")
                continue
            if _is_repeat(ans):
                await self.speak(self.last_spoken or "Nothing to repeat yet.")
                continue
            if _wants_more(ans):
                await self.speak_full_menu()
                ans = await self.listen()
                if _contains_exit(ans):
                    await self.safe_exit("Okay.")
                    return None

            key, conf = _match_sound(ans)
            if key and conf >= 0.55:
                return key

            if key and 0.40 <= conf < 0.55:
                await self.speak(f"Did you mean {SOUNDS[key]['name']}?")
                confirm = await self.listen()
                if _contains_exit(confirm):
                    await self.safe_exit("Okay.")
                    return None
                c = _clean(confirm)
                if "yes" in c or "yeah" in c or "yep" in c or "correct" in c:
                    return key

            retries += 1
            await self.speak("Try saying rain, ocean waves, white noise, campfire, wind, thunder, fan, or waterfall.")

        await self.safe_exit("No problem. Try again anytime.")
        return None

    async def _listen_for_stop(self) -> None:
        while True:
            msg = await self.listen()
            if msg and _contains_exit(msg):
                self.stop_requested = True
                return

    async def play_for_duration(self, sound_file: str, duration_minutes: int) -> bool:
        total_seconds = int(duration_minutes) * 60
        start = time.time()
        self.stop_requested = False

        stop_task = self.worker.session_tasks.create(self._listen_for_stop())

        await self.set_music_mode(True)
        try:
            while True:
                if self.stop_requested:
                    return True
                if time.time() - start >= total_seconds:
                    return False

                clip_start = time.time()
                try:
                    await self.capability_worker.play_from_audio_file(sound_file)
                except Exception as e:
                    self.worker.editor_logging_handler.warning(f"Playback failed: {e}")
                    await self.speak("Sorry, I couldn’t play that sound. Please make sure the mp3 is uploaded.")
                    return True

                clip_elapsed = time.time() - clip_start

                # If a recent transcription contains an exit word, stop cleanly.
                try:
                    latest_any = self.capability_worker.get_latest_transcription()
                    if latest_any and _contains_exit(str(latest_any)):
                        return True
                except Exception:
                    pass

                # If the clip ends far earlier than expected (brief: ~30–60s), treat it as an interrupt
                # and stop instead of restarting the loop.
                if clip_elapsed < MIN_EXPECTED_CLIP_SECONDS:
                    try:
                        latest = self.capability_worker.get_latest_transcription()
                        if latest and _contains_exit(str(latest)):
                            return True
                    except Exception:
                        pass
                    return True

                await self.nap(INTER_LOOP_GAP_SECONDS)

        finally:
            try:
                stop_task.cancel()
            except Exception:
                pass
            await self.set_music_mode(False)

    async def run(self) -> None:
        try:
            trigger_text = str(self.capability_worker.get_trigger_context() or "")
        except Exception:
            trigger_text = ""

        if trigger_text and _contains_exit(trigger_text):
            await self.safe_exit("Okay.")
            return

        sound_key = await self.choose_sound(trigger_text)
        if not sound_key:
            return

        sound_name = SOUNDS[sound_key]["name"]
        sound_file = SOUNDS[sound_key]["file"]

        duration_minutes: Optional[int] = None
        if trigger_text and _user_mentioned_duration(trigger_text):
            duration_minutes = _extract_duration_minutes(trigger_text)

        if duration_minutes is None:
            try:
                duration_minutes = await self.ask_for_duration_minutes()
            except RuntimeError:
                return

        duration_minutes = _clamp_minutes(int(duration_minutes))

        await self.speak(f"Playing {sound_name} for {_format_duration(duration_minutes)}. Say stop anytime.")
        stopped = await self.play_for_duration(sound_file, duration_minutes)

        if stopped:
            await self.safe_exit("Okay, stopped.")
        else:
            await self.safe_exit("All done.")

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
