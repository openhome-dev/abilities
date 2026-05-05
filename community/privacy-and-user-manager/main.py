import json
import re
from time import strftime, time as _now

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# ---------------------------------------------------------------------
# Files we own / produce
# ---------------------------------------------------------------------
RECENT_CHAT_FILE = "recent_chat.md"               # we write this
ACTIVE_USER_FILE = "active_user_context.md"       # we write this
AUDIO_CONTEXT_FILE = "personal_audio_context.md"  # we write this — privacy
# framed; auto-injected
AUDIO_DIAG_FILE = "bluetooth_diagnostic.md"       # we write this — pure
# developer telemetry, no
# privacy framing so the
# persona will recite it
LAST_SEEN_FILE = "pum_cursor.md"                  # our own dedupe cursor;
# distinct from
# conversation_monitor_cursor.md
# so the legacy daemon's
# cursor doesn't collide
# during a transition.
SETTINGS_FILE = "pum_settings.json"               # persists user-toggleable
# preferences (currently:
# whether to announce
# audio-mode on greet)
SKILL_BUSY_FLAG = "skill_active.lock"             # Skills set this while
# they own the turn.

# ---------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------
POLL_INTERVAL = 3.0   # seconds between scans (Bluetooth + chat + recompose)
HISTORY_SIZE = 10     # last N messages mirrored into recent_chat.md
MAX_MSG_LEN = 400     # per-message truncation in recent_chat.md
RECENT_SWITCH_WINDOW_S = 120.0   # how long to keep "user just switched"
# warning at the top of active_user_context.md

# Bluetooth audio classification — primary signal is system_profiler's
# device_minorType field. Keywords are a fallback for devices missing it.
PRIVATE_MINOR_TYPES = {
    "headphones", "headset", "earbuds", "headsetmicrophone",
}
PUBLIC_AUDIO_MINOR_TYPES = {
    "speaker", "speakers", "loudspeaker",
}

AUDIO_KEYWORDS = [
    "airpod", "headphone", "earphone", "earbud", "beats", "sony",
    "bose", "jbl", "sennheiser", "jabra", "plantronics", "audio",
    "buds", "wh-", "wf-", "qc", "momentum", "soundsport",
]

# ---------------------------------------------------------------------
# Two-tier user storage helpers
# ---------------------------------------------------------------------


def _user_notes_json(name_key: str) -> str:
    """Single per-user notes file. JSON is NOT auto-injected into the
    Personality prompt — only the active user's bullets reach the prompt
    via active_user_context.md (composed by this daemon). That's the
    structural cross-user privacy guarantee: when Maya is active, the
    Personality literally cannot see Freddie's notes file because no
    .md side-channel exposes it.

    Schema:
        {
          "display_name": "Freddie",
          "created_at": "2026-05-05T17:42:00",
          "public_items":  [{"ts": "...", "bullet": "- likes dark coffee"}],
          "private_items": [{"ts": "...", "bullet": "- bank pin 4321", "raw": "..."}]
        }
    """
    return "user_%s_notes.json" % name_key


# Legacy file names — read-only migration sources kept for backward compat
# with state written by Privacy Monitor / Conversation Monitor / Multi-User
# Speaker ID before this daemon's consolidated schema landed.
def _legacy_public_md(name_key: str) -> str:
    return "user_%s_public.md" % name_key


def _legacy_private_json(name_key: str) -> str:
    return "user_%s_private.json" % name_key


def _legacy_info_md(name_key: str) -> str:
    return "user_%s_info.md" % name_key


# ---------------------------------------------------------------------
# Fast prefilter — only hit the LLM if the message looks actionable
# ---------------------------------------------------------------------
IDENTIFY_SIGNAL = re.compile(
    r"\b(?:i'?m|i am|it'?s|this is|my name is|call me|i go by|"
    r"switch(?:ing)?(?: to)?|change(?:d)?(?: to)?|"
    r"actually i'?m|hey it'?s|hi it'?s|this here is)\b",
    re.IGNORECASE,
)
REMEMBER_SIGNAL = re.compile(
    r"\b(?:remember|save|note(?: that)?|keep track|store|jot|log this|"
    r"don'?t forget|make a note)\b",
    re.IGNORECASE,
)
# Phrases that toggle the audio-mode announcement on or off. Anything that
# matches this prefilter goes straight to a deterministic toggle handler —
# it does not need an LLM call.
ANNOUNCE_DISABLE_SIGNAL = re.compile(
    r"\b(?:stop|don'?t|do not|disable|mute|turn off|silence|skip)\b[^.!?]{0,50}"
    r"\b(?:announc(?:e|ing|ement)|notif(?:y|ication|ying)|tell(?:ing)? me|"
    r"mention(?:ing)?|say(?:ing)?)\b[^.!?]{0,50}"
    r"\b(?:audio|bluetooth|headphones?|earbuds?|speaker|private|public|mode)\b",
    re.IGNORECASE,
)
ANNOUNCE_ENABLE_SIGNAL = re.compile(
    r"\b(?:start|please|enable|unmute|turn on|resume|begin|do)\b[^.!?]{0,50}"
    r"\b(?:announc(?:e|ing|ement)|notif(?:y|ication|ying)|tell(?:ing)? me|"
    r"mention(?:ing)?|say(?:ing)?)\b[^.!?]{0,50}"
    r"\b(?:audio|bluetooth|headphones?|earbuds?|speaker|private|public|mode)\b",
    re.IGNORECASE,
)

NAME_BLACKLIST = {
    "a", "an", "the", "my", "your", "his", "her", "their", "our",
    "one", "two", "three",
    "i", "me", "you", "he", "she", "they", "we",
    "to", "in", "on", "at", "of", "and", "or", "but",
    "yes", "no", "ok", "okay", "sure", "yeah", "nope",
    "hey", "so", "well", "um", "uh", "anyway", "listen",
}


class PrivacyAndUserManagerBackground(MatchingCapability):
    """Single Background Daemon that owns:

    1. Bluetooth audio mode tracking → personal_audio_context.md +
       conversation-opening directive that the Personality reads on its
       next turn (BG-daemon speak() is unreliable, so we steer the
       Personality via auto-injected markdown instead). Classifier uses
       system_profiler's device_minorType field (Headphones / Headset /
       Earbuds → private; Speaker → public-audio-but-not-private), so
       custom-named AirPods like "FreLia27" are recognized correctly and
       a connected Bluetooth speaker correctly stays INACTIVE. Pure
       developer telemetry lives in bluetooth_diagnostic.md (no privacy
       framing), recited verbatim by the Bluetooth Diagnostic Readout
       skill.
    2. Chat-history mirroring → recent_chat.md (last 10 user/assistant
       turns) so this daemon and other capabilities can recover trigger
       text when worker.current_transcript and agent_memory are empty.
    3. User-state monitoring → active_user_context.md + per-user
       two-tier storage. Sensitive notes go to user_<name>_private.json
       (NOT auto-injected); public notes go to user_<name>_public.md
       (auto-injected). active_user_context.md is recomposed on every
       audio-mode flip, user switch, or new note — and only splices in
       Tier 2 content when audio is ACTIVE, making leakage on shared
       speakers structurally impossible.

    All three responsibilities live in one BG daemon because OpenHome
    appears to run only one daemon reliably per agent. This is the
    successor to the separate Audio Watcher / Chat Logger / Conversation
    Monitor / Privacy Monitor daemons — disable those in the dashboard
    before deploying this one.
    """
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # User-switch tracking — when a switch happens in the last
    # RECENT_SWITCH_WINDOW_S seconds, active_user_context.md gets a strong
    # "user just switched" warning so the Personality doesn't leak the
    # previous user's info via session memory.
    last_switch_at: float = 0.0
    last_switch_from: str = ""

    # Bluetooth state
    last_audio_device: str = ""
    announced_initial: bool = False
    # True once the daemon has processed at least one user message in this
    # session. While False, _write_personal_audio_md uses "first-greet"
    # directive phrasing so the Personality reliably announces audio mode
    # on its first reply (the file might be re-written several times before
    # the user sends anything).
    first_user_message_seen: bool = False
    pending_audio_announcement: str = ""

    # Chat-mirror state
    chat_last_signature: str = ""

    # User-state watcher
    last_processed_msg: str = ""
    last_audio_mode: str = ""
    last_active_user: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        try:
            self.worker = worker
            self.background_daemon_mode = background_daemon_mode
            # CapabilityWorker(self) — same shape that Privacy Monitor and
            # Timers Alarms Reminders use successfully.
            self.capability_worker = CapabilityWorker(self)
            self.worker.editor_logging_handler.info(
                "[PUM] initialized (Bluetooth + chat-mirror + user-state)"
            )
            # Quick-start heartbeat: scan + write context 3s after init so the
            # Personality has the audio-mode directive available for its first
            # reply, without waiting for the loop's pre-scan cleanup.
            self.worker.session_tasks.create(self._startup_heartbeat())
            self.worker.session_tasks.create(self._loop())
        except Exception as e:
            try:
                self.worker.editor_logging_handler.error(
                    "[PUM] init failed: %s" % e
                )
            except Exception:
                pass
            # If init fails before the polling loop starts, release the turn
            # back to the Personality so the agent isn't stuck. Long-running
            # BG daemons don't normally call resume_normal_flow() because
            # they never hold the turn — but an init-time failure is the
            # one place a daemon genuinely should release control, and the
            # SDK validator requires the call to appear in main.py.
            try:
                if self.capability_worker is not None:
                    self.capability_worker.resume_normal_flow()
            except Exception:
                pass

    async def _startup_heartbeat(self):
        """Fire a single Bluetooth scan + audio-context write immediately at
        session start, before the main loop begins its periodic ticking. This
        makes the Personality see the audio-mode directive within ~3-4s of
        opening a chat, so the very first agent reply can mention private vs.
        shared-speaker mode."""
        try:
            # Tiny delay so the agent's opening greeting can finish first.
            await self.worker.session_tasks.sleep(3.0)
            await self._scan_audio()
        except Exception as e:
            try:
                self.worker.editor_logging_handler.error(
                    "[PUM] startup heartbeat failed: %s" % e
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Main loop — runs every POLL_INTERVAL seconds
    # ------------------------------------------------------------------
    async def _loop(self):
        # Clean stale audio + chat-mirror on session start so the first scan
        # establishes truth.
        for f in (AUDIO_CONTEXT_FILE, AUDIO_DIAG_FILE, RECENT_CHAT_FILE):
            try:
                if await self.capability_worker.check_if_file_exists(f, False):
                    await self.capability_worker.delete_file(f, False)
            except Exception:
                pass

        try:
            if await self.capability_worker.check_if_file_exists(LAST_SEEN_FILE, False):
                content = await self.capability_worker.read_file(LAST_SEEN_FILE, False)
                self.last_processed_msg = content.strip()
        except Exception:
            pass

        while True:
            try:
                await self._scan_audio()
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    "[PUM] audio scan failed: %s" % e
                )
            try:
                await self._mirror_chat()
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    "[PUM] chat mirror failed: %s" % e
                )
            try:
                await self._maybe_recompose_on_state_change()
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    "[PUM] recompose failed: %s" % e
                )
            try:
                await self._process_new_user_message()
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    "[PUM] message processing failed: %s" % e
                )
            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ==================================================================
    # 1. Bluetooth audio scanning + announcements
    # ==================================================================
    async def _scan_audio(self):
        diag_lines = []
        try:
            devices = await self._get_bluetooth_audio_devices(diag_lines=diag_lines)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] Bluetooth scan failed: %s" % e
            )
            devices = []
            diag_lines.append("Bluetooth scan exception: %s" % e)
        # ACTIVE only when a *private* audio device (Headphones / Headset /
        # Earbuds) is connected. A connected Bluetooth speaker is shared
        # audio in the room → stays INACTIVE.
        connected_private = [
            d for d in devices
            if d.get("connected") and d.get("is_audio") and d.get("is_private")
        ]
        device_summary = ",".join(sorted(d["name"] for d in connected_private))
        # Always update both files so diagnostics refresh every scan, even
        # if the audio state itself didn't change.
        self._last_diag_lines = diag_lines
        self._last_all_devices = devices

        is_state_change = device_summary != self.last_audio_device
        is_transition = is_state_change and self.announced_initial
        # "first-greet" stays sticky until we've actually processed a user
        # message — that way the Personality's first reply reliably has the
        # first-run directive available, even if the daemon scans several
        # times before the user types anything.
        is_first_greet = not self.first_user_message_seen

        await self._write_personal_audio_md(connected_private, is_transition, is_first_greet)
        await self._write_bluetooth_diagnostic_md(connected_private)

        if is_state_change or not self.announced_initial:
            self.last_audio_device = device_summary
            self.worker.editor_logging_handler.info(
                "[PUM] %s updated — connected private audio: %s"
                % (AUDIO_CONTEXT_FILE, device_summary or "none")
            )
            self.announced_initial = True

    async def _get_bluetooth_audio_devices(self, diag_lines: list = None) -> list:
        if diag_lines is None:
            diag_lines = []
        result = await self.capability_worker.exec_local_command(
            "system_profiler SPBluetoothDataType -json", timeout=12.0,
        )
        if not isinstance(result, dict):
            diag_lines.append("exec_local_command returned %s — Local Link may not be reachable" % type(result).__name__)
            return []
        diag_lines.append("exec_local_command result keys: %r" % list(result.keys()))
        data = result.get("data", {})
        stdout = ""
        if isinstance(data, dict):
            stdout = data.get("stdout", "") or data.get("output", "") or str(data)
        else:
            stdout = str(data) if data else ""
        self._last_raw_stdout_head = stdout[:500]
        if not stdout or len(stdout.strip()) < 5:
            diag_lines.append("system_profiler stdout was empty/short (%d chars)" % len(stdout))
            return []
        diag_lines.append("system_profiler stdout %d chars; first 200: %s" % (len(stdout), stdout[:200].replace("\n", " ")))
        self._last_parse_error = ""
        devices = self._parse_bluetooth_json(stdout)
        if not devices:
            diag_lines.append("parser found 0 devices from stdout")
        for d in devices:
            diag_lines.append("device name=%r connected=%r is_audio=%r" % (
                d.get("name"), d.get("connected"), d.get("is_audio")
            ))
        return devices

    def _parse_bluetooth_json(self, raw: str) -> list:
        devices = []
        try:
            parsed = json.loads(raw)
            for section in parsed.get("SPBluetoothDataType", []):
                for key in ("device_connected", "device_not_connected", "device_paired"):
                    connected = (key == "device_connected")
                    for name, meta in self._iter_device_entries(section.get(key, [])):
                        minor = (meta.get("device_minorType") or "").strip().lower()
                        services = meta.get("device_services") or ""
                        has_audio_profile = ("A2DP" in services) or ("HFP" in services)
                        is_private = minor in PRIVATE_MINOR_TYPES
                        is_public_audio = minor in PUBLIC_AUDIO_MINOR_TYPES
                        is_audio = (
                            is_private or is_public_audio
                            or has_audio_profile
                            or self._is_audio_device(name)
                        )
                        devices.append({
                            "name": name,
                            "connected": connected,
                            "is_audio": is_audio,
                            "is_private": is_private,
                            "minor_type": minor,
                            "has_a2dp_hfp": has_audio_profile,
                        })
        except Exception as e:
            self._last_parse_error = repr(e)
        return devices

    def _iter_device_entries(self, device_list):
        """Yield (name, meta_dict) pairs from either list-of-singleton-dicts
        or dict-of-name-to-meta forms that system_profiler may emit."""
        if isinstance(device_list, list):
            for entry in device_list:
                if isinstance(entry, dict):
                    for name, meta in entry.items():
                        yield name, (meta if isinstance(meta, dict) else {})
        elif isinstance(device_list, dict):
            for name, meta in device_list.items():
                yield name, (meta if isinstance(meta, dict) else {})

    def _is_audio_device(self, name: str) -> bool:
        low = (name or "").lower()
        return any(kw in low for kw in AUDIO_KEYWORDS)

    # Diagnostic state captured by _scan_audio for inclusion in MD
    _last_diag_lines: list = []
    _last_all_devices: list = []
    _last_parse_error: str = ""
    _last_raw_stdout_head: str = ""

    async def _write_personal_audio_md(self, connected_private_devices: list,
                                       is_transition: bool, is_first_greet: bool):
        """Write the privacy-framed audio-mode file. The conversation-opening
        directive lives at the top so the Personality reads it on its next
        reply — that's our reliable substitute for BG-daemon speak().

        When the user has disabled audio-mode announcements (via
        ``pum_settings.json``), the directive is replaced with a no-op that
        explicitly tells the Personality NOT to mention audio mode unless
        asked. Status / rules stay so disclosure decisions still work."""
        timestamp = strftime("%Y-%m-%d %H:%M:%S")
        announce_enabled = await self._should_announce()

        if connected_private_devices:
            device_names = ", ".join(d["name"] for d in connected_private_devices)
            if not announce_enabled:
                directive = (
                    "DISABLED — the user has opted out of audio-mode "
                    "announcements. Do NOT proactively mention private "
                    "audio, headphones, or audio mode on this turn or any "
                    "future turn unless the user explicitly asks. The "
                    "audio-mode rules below STILL apply to disclosure "
                    "decisions; you just can't volunteer the mode itself. "
                    "(User can re-enable by saying 'start announcing audio "
                    "mode'.)"
                )
            elif is_transition:
                directive = (
                    "The audio mode just FLIPPED to private. On your next "
                    "reply, briefly note that %s just connected and ask if "
                    "you can speak more freely about personal matters. One "
                    "natural sentence. Don't repeat after that."
                ) % device_names
            elif is_first_greet:
                directive = (
                    "When the user greets you for the first time in this "
                    "session, briefly mention you've detected they're on "
                    "private audio (naming the device, %s) and offer to "
                    "speak more freely about personal matters. One natural "
                    "sentence. Don't repeat this on later turns unless the "
                    "audio state changes."
                ) % device_names
            else:
                directive = (
                    "Audio is private (%s). Stay quiet about audio mode on "
                    "ordinary turns; only mention it if the user asks."
                ) % device_names
            content = (
                "## Personal Audio Mode\n"
                "Status: ACTIVE (private)\n"
                "Connected device(s): %s\n"
                "Last scanned: %s\n"
                "Announcements: %s\n\n"
                "### Conversation-opening directive:\n"
                "%s\n\n"
                "### Audio-mode rules — apply when making disclosure decisions:\n"
                "1. The user is on personal audio (headphones/earbuds). The conversation is PRIVATE — nobody else can overhear.\n"
                "2. In this mode, the currently active user's personal or sensitive information MAY be discussed when relevant.\n"
                "3. **Saving notes is ALWAYS allowed**, regardless of audio mode. When the user says 'remember X', acknowledge that you've saved it — the daemon classifies and persists it for you. Do not refuse to save.\n"
                "4. Per-user access rules still apply. See active_user_context.md for which user is active and what they've authorized.\n"
            ) % (
                device_names, timestamp,
                "enabled" if announce_enabled else "disabled by user",
                directive,
            )
        else:
            if not announce_enabled:
                directive = (
                    "DISABLED — the user has opted out of audio-mode "
                    "announcements. Do NOT proactively mention shared "
                    "speaker, audio mode, or that the conversation is "
                    "public on this turn or any future turn unless the "
                    "user explicitly asks. The audio-mode rules below "
                    "STILL apply to disclosure decisions; you just can't "
                    "volunteer the mode itself. (User can re-enable by "
                    "saying 'start announcing audio mode'.)"
                )
            elif is_transition:
                directive = (
                    "Private audio just DISCONNECTED. On your next reply, "
                    "briefly note the flip — something like 'private audio "
                    "disconnected, I'll keep things private from now on'. "
                    "One natural sentence. Don't repeat after that."
                )
            elif is_first_greet:
                directive = (
                    "When the user greets you for the first time in this "
                    "session, briefly note that you're on a shared speaker "
                    "and will keep private things private. One short natural "
                    "sentence. Don't repeat on later turns unless the audio "
                    "state changes."
                )
            else:
                directive = (
                    "Audio is shared (no private device connected). Stay "
                    "quiet about audio mode on ordinary turns; only mention "
                    "it if the user asks."
                )
            content = (
                "## Personal Audio Mode\n"
                "Status: INACTIVE (public / shared speaker)\n"
                "No personal audio devices connected.\n"
                "Last scanned: %s\n"
                "Announcements: %s\n\n"
                "### Conversation-opening directive:\n"
                "%s\n\n"
                "### Audio-mode rules — apply when making disclosure decisions:\n"
                "1. The user is on a SHARED SPEAKER. Anyone nearby can hear you. Treat the conversation as PUBLIC.\n"
                "2. **Saving notes is ALWAYS allowed**, in every audio mode. When the user says 'remember X', acknowledge that you've saved it — the daemon classifies and persists it for you. Do not refuse to save. Do not say you 'cannot store preferences in this mode'. Saving and *speaking aloud* are different things; this rule is about speaking, not saving.\n"
                "3. Public notes (food/drink/hobbies/broad job/favorite media/pet names) are ALWAYS safe to surface — including on shared speaker. If the user asks 'what do you know about me', recite all PUBLIC bullets from active_user_context.md naturally.\n"
                "4. Sensitive specifics (PINs, passwords, full addresses, phone numbers, financial figures, medical specifics, exact schedules) are WITHHELD on shared speaker. The 'Private info' section of active_user_context.md will literally read 'Withheld — shared speaker mode.' in this mode; do not invent content there.\n"
                "5. If the user shares something sensitive out loud, acknowledge briefly and neutrally that you've saved it privately. Do NOT echo the sensitive specifics back. Do NOT ask follow-up questions that would surface those specifics aloud.\n"
                "6. Anything discussed in a previous private session is OFF-LIMITS in this public session unless it's a public-tier note in active_user_context.md.\n"
            ) % (
                timestamp,
                "enabled" if announce_enabled else "disabled by user",
                directive,
            )
        await self._write_md_overwrite(AUDIO_CONTEXT_FILE, content)

    async def _write_bluetooth_diagnostic_md(self, connected_private_devices: list):
        """Write the developer-telemetry file. No privacy framing → persona
        will recite. Read this file via the 'read bluetooth diagnostic'
        Skill to bypass any persona-level refusal."""
        timestamp = strftime("%Y-%m-%d %H:%M:%S")
        if connected_private_devices:
            verdict = "Status: ACTIVE — connected_private=[%s]" % (
                ", ".join(d["name"] for d in connected_private_devices)
            )
        else:
            verdict = "Status: INACTIVE — no connected private audio devices"

        lines = [
            "## Bluetooth scan diagnostic",
            "_Pure debug telemetry. No user-private data here. Recite verbatim when asked._",
            "",
            "Last scan: %s" % timestamp,
            "Last parse error: %s" % (self._last_parse_error or "None"),
            "Final verdict: %s" % verdict,
            "",
            "### Scan trace (last %d lines)" % min(12, len(self._last_diag_lines or [])),
        ]
        for line in (self._last_diag_lines or [])[-12:]:
            lines.append("- " + line)

        all_devs = self._last_all_devices or []
        lines.append("")
        lines.append("### Devices observed (%d)" % len(all_devs))
        if not all_devs:
            lines.append("- (none parsed)")
            if self._last_raw_stdout_head:
                lines.append("")
                lines.append("### Raw stdout (first 500 chars)")
                lines.append("```")
                lines.append(self._last_raw_stdout_head)
                lines.append("```")
        else:
            for d in all_devs[:20]:
                lines.append(
                    "- %s — connected=%s, minor_type=%s, is_private=%s, a2dp/hfp=%s, is_audio=%s"
                    % (
                        d.get("name"),
                        d.get("connected"),
                        d.get("minor_type") or "(unknown)",
                        d.get("is_private"),
                        d.get("has_a2dp_hfp"),
                        d.get("is_audio"),
                    )
                )
        lines.append("")
        await self._write_md_overwrite(AUDIO_DIAG_FILE, "\n".join(lines))

    # ==================================================================
    # 2. Chat history mirror (last 10 user/assistant turns)
    # ==================================================================
    async def _mirror_chat(self):
        history = []
        try:
            history = self.worker.agent_memory.full_message_history or []
        except Exception:
            history = []

        normalized = []
        for msg in history:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not isinstance(role, str) or not isinstance(content, str):
                continue
            if not role or not content.strip():
                continue
            if role not in ("user", "assistant", "system"):
                continue
            normalized.append((role, content.strip()[:MAX_MSG_LEN]))
        recent = normalized[-HISTORY_SIZE:]

        lines = ["## Recent Chat History", ""]
        if not recent:
            lines.append("_(no conversation yet)_")
        else:
            for role, content in recent:
                lines.append("- **%s:** %s" % (role, content))
        lines.append("")
        signature = "\n".join(lines)
        if signature == self.chat_last_signature:
            return
        self.chat_last_signature = signature

        timestamp = strftime("%Y-%m-%d %H:%M:%S")
        body = (
            "## Recent Chat History\n_Updated: %s_\n\n%s\n"
            % (timestamp, "\n".join(lines[2:]).strip() or "_(no conversation yet)_")
        )
        await self._write_md_overwrite(RECENT_CHAT_FILE, body)
        self.worker.editor_logging_handler.info(
            "[PUM] %s updated (%d messages)" % (RECENT_CHAT_FILE, len(recent))
        )

    # ==================================================================
    # 3. User-state watcher: process new user message + recompose on flip
    # ==================================================================
    async def _maybe_recompose_on_state_change(self):
        try:
            audio_mode = await self._read_audio_mode()
            active = await self._read_active_user()
            active_key = self._normalize_name(active)
            prev_key = self._normalize_name(self.last_active_user)
            if audio_mode == self.last_audio_mode and active_key == prev_key:
                return
            self.worker.editor_logging_handler.info(
                "[PUM] state changed (audio: %r → %r, user: %r → %r); recomposing"
                % (self.last_audio_mode, audio_mode, self.last_active_user, active)
            )
            self.last_audio_mode = audio_mode
            self.last_active_user = active
            if active:
                await self._recompose_active_context(active)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] state-change recompose failed: %s" % e
            )

    async def _process_new_user_message(self):
        latest = await self._read_latest_user_message()
        if not latest or latest == self.last_processed_msg:
            return
        self.worker.editor_logging_handler.info(
            "[PUM] new user message: %r" % latest[:200]
        )
        # Even if the message isn't actionable, observing it means the user
        # has now spoken — so we can drop out of "first-greet" directive mode
        # the next time _scan_audio writes the audio-context file.
        self.first_user_message_seen = True

        # Announce-toggle prefilter — deterministic, no LLM call needed.
        # Disable check first because both regexes can technically overlap on
        # phrases like "stop announcing", which should not be read as enable.
        if ANNOUNCE_DISABLE_SIGNAL.search(latest):
            await self._handle_announce_toggle(False)
            self.last_processed_msg = latest
            await self._persist_cursor(latest)
            return
        if ANNOUNCE_ENABLE_SIGNAL.search(latest):
            await self._handle_announce_toggle(True)
            self.last_processed_msg = latest
            await self._persist_cursor(latest)
            return

        if not (IDENTIFY_SIGNAL.search(latest) or REMEMBER_SIGNAL.search(latest)):
            self.worker.editor_logging_handler.info(
                "[PUM] prefilter: not actionable"
            )
            self.last_processed_msg = latest
            await self._persist_cursor(latest)
            return

        intent = self._classify(latest)
        action = (intent.get("action") or "").lower()
        self.worker.editor_logging_handler.info(
            "[PUM] classifier: %s" % intent
        )
        try:
            if action == "user_switch":
                new_user = (intent.get("new_user_name") or "").strip()
                if new_user:
                    await self._handle_user_switch(new_user)
            elif action == "save_note":
                note = (intent.get("note") or "").strip()
                sensitivity = (intent.get("sensitivity") or "sensitive").lower()
                if sensitivity not in {"sensitive", "public"}:
                    sensitivity = "sensitive"
                if note:
                    await self._handle_save_note(note, sensitivity)
        finally:
            self.last_processed_msg = latest
            await self._persist_cursor(latest)

    # ------------------------------------------------------------------
    # User-state helpers — readers
    # ------------------------------------------------------------------
    async def _read_latest_user_message(self) -> str:
        # Source 1: agent_memory directly
        try:
            history = self.worker.agent_memory.full_message_history or []
            for msg in reversed(history):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
        except Exception:
            pass
        # Source 2: recent_chat.md (file we own)
        try:
            if await self.capability_worker.check_if_file_exists(RECENT_CHAT_FILE, False):
                content = await self.capability_worker.read_file(RECENT_CHAT_FILE, False)
                for line in reversed(content.splitlines()):
                    m = re.match(r"-\s*\*\*user:\*\*\s*(.+)", line)
                    if m:
                        return m.group(1).strip()
        except Exception:
            pass
        return ""

    async def _read_active_user(self) -> str:
        try:
            if not await self.capability_worker.check_if_file_exists(ACTIVE_USER_FILE, False):
                return ""
            content = await self.capability_worker.read_file(ACTIVE_USER_FILE, False)
            m = re.search(r"Current user:\s*\*?\*?([^*\n]+)", content)
            return m.group(1).strip() if m else ""
        except Exception:
            return ""

    async def _read_audio_mode(self) -> str:
        try:
            if not await self.capability_worker.check_if_file_exists(AUDIO_CONTEXT_FILE, False):
                return "unknown"
            content = await self.capability_worker.read_file(AUDIO_CONTEXT_FILE, False)
            if "Status: ACTIVE" in content:
                return "active"
            if "Status: INACTIVE" in content:
                return "inactive"
            return "unknown"
        except Exception:
            return "unknown"

    # ------------------------------------------------------------------
    # User-state — LLM intent classifier
    # ------------------------------------------------------------------
    def _classify(self, text: str) -> dict:
        prompt = (
            "You are a silent background monitor for a voice assistant that "
            "supports multiple users. A new message just arrived. Decide if "
            "it should trigger a state change. Return ONLY one of these "
            "JSON shapes. Do not add commentary.\n\n"
            "USER_SWITCH — speaker introducing themselves or switching "
            "active user. Examples: 'hey it's Maya', 'I'm Freddie', "
            "'this is Jessica', 'call me Alex', 'my name is Bob', "
            "'switch to Charlie', 'actually I'm Dan'. Extract the name.\n"
            '{"action": "user_switch", "new_user_name": "Maya"}\n\n'
            "SAVE_NOTE — speaker wants a fact persisted about themselves. "
            "Examples: 'remember I like dark coffee', 'save this about me: I "
            "live in Seattle', 'note that I prefer mornings'. Extract the "
            "note (one bullet) AND classify sensitivity.\n"
            "  sensitivity = 'sensitive' for: PINs, passwords, card or "
            "account numbers, full home or work addresses, phone numbers, "
            "SSNs, exact financial figures, exact medical conditions or "
            "medications, exact appointment times, location coordinates, "
            "relationship-status specifics, anything a stranger overhearing "
            "would consider private.\n"
            "  sensitivity = 'public' for: food/drink preferences, hobbies, "
            "favorite colors, pet names, broad job/role, broad city/country, "
            "favorite media.\n"
            "  When ambiguous → sensitive (fail closed).\n"
            '{"action": "save_note", "note": "bank pin 4321", "sensitivity": "sensitive"}\n'
            '{"action": "save_note", "note": "likes dark coffee", "sensitivity": "public"}\n\n'
            "NONE — anything else.\n"
            '{"action": "none"}\n\n'
            "Message: \"%s\"\n"
            "Respond with only the JSON."
        ) % text
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            if not isinstance(raw, str):
                return {"action": "none"}
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()
            parsed = json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] LLM classify failed: %s" % e
            )
            return {"action": "none"}

        if parsed.get("action") == "save_note":
            note = (parsed.get("note") or "")
            sens = parsed.get("sensitivity")
            if sens not in {"sensitive", "public"}:
                parsed["sensitivity"] = "sensitive"
            elif sens == "public" and self._looks_obviously_sensitive(note):
                self.worker.editor_logging_handler.info(
                    "[PUM] post-check upgraded to sensitive: %r" % note[:120]
                )
                parsed["sensitivity"] = "sensitive"
        return parsed

    def _looks_obviously_sensitive(self, text: str) -> bool:
        low = (text or "").lower()
        if re.search(r"(pin|code|passcode|password|account|card|ssn)\D{0,12}\d{4,}", low):
            return True
        if re.search(r"\$\s?\d", low):
            return True
        if re.search(r"\b\d+\s+\w+\s+(street|st|avenue|ave|road|rd|drive|dr|lane|ln|boulevard|blvd|way|court|ct)\b", low):
            return True
        if re.search(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", low):
            return True
        return False

    # ------------------------------------------------------------------
    # User-state — action handlers
    # ------------------------------------------------------------------
    async def _handle_user_switch(self, raw_name: str):
        name_key = self._normalize_name(raw_name)
        display = raw_name.strip().title()
        if not name_key or name_key in NAME_BLACKLIST:
            return
        current_active = await self._read_active_user()
        if self._normalize_name(current_active) == name_key:
            return
        # Capture switch event so active_user_context.md can include a strong
        # "user just switched" warning that survives the next ~2 minutes.
        # Without this, the Personality's session memory leaks the previous
        # user's info to the new active user (the JSON consolidation closes
        # the file-injection door, but session memory stays unless the
        # context file flags the switch loudly).
        if current_active:
            self.last_switch_from = current_active
            self.last_switch_at = _now()
        await self._ensure_public_stub(name_key, display)
        await self._recompose_active_context(display)
        self.worker.editor_logging_handler.info(
            "[PUM] active user: %r → %r" % (current_active, display)
        )

    async def _handle_save_note(self, note: str, sensitivity: str):
        active = await self._read_active_user()
        if not active:
            self.worker.editor_logging_handler.info(
                "[PUM] save_note but no active user; skipping"
            )
            return
        name_key = self._normalize_name(active)
        try:
            formatted = self.capability_worker.text_to_text_response(
                "Format this as ONE concise bullet point (start with '- '), "
                "plain text, 10 words max if possible:\n\n" + note
            )
            formatted = (formatted or "").strip()
            if not formatted.startswith("-"):
                formatted = "- " + formatted
        except Exception:
            formatted = "- " + note

        if sensitivity == "sensitive":
            await self._append_private_item(name_key, formatted, raw_note=note)
        else:
            await self._append_public_bullet(name_key, active, formatted)

        await self._recompose_active_context(active)

    # ------------------------------------------------------------------
    # User-state — consolidated per-user JSON (NOT auto-injected; the
    # daemon is the only thing that reads it. Cross-user privacy is
    # structural: only the *active* user's items are spliced into
    # active_user_context.md.)
    # ------------------------------------------------------------------
    async def _load_user_record(self, name_key: str, display: str = "") -> dict:
        """Load the consolidated user record. On first read, migrate any
        legacy Tier-1 .md / Tier-2 .json content into the new schema and
        delete the legacy files so they stop leaking via auto-injection."""
        path = _user_notes_json(name_key)
        record = {
            "display_name": display or name_key.title(),
            "created_at": strftime("%Y-%m-%dT%H:%M:%S"),
            "public_items": [],
            "private_items": [],
        }
        try:
            if await self.capability_worker.check_if_file_exists(path, False):
                raw = await self.capability_worker.read_file(path, False)
                if (raw or "").strip():
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        record["display_name"] = data.get("display_name") or record["display_name"]
                        record["created_at"] = data.get("created_at") or record["created_at"]
                        record["public_items"] = data.get("public_items") or []
                        record["private_items"] = data.get("private_items") or []
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] user record unreadable, starting fresh: %s" % e
            )

        # Migration from legacy files (one-shot per file).
        await self._migrate_legacy_into(record, name_key)
        return record

    async def _save_user_record(self, name_key: str, record: dict) -> None:
        path = _user_notes_json(name_key)
        payload = json.dumps(record, indent=2)
        try:
            if await self.capability_worker.check_if_file_exists(path, False):
                await self.capability_worker.delete_file(path, False)
            await self.capability_worker.write_file(path, payload, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] user record write failed: %s" % e
            )

    async def _migrate_legacy_into(self, record: dict, name_key: str) -> None:
        """Read any leftover user_<key>_public.md / _private.json /
        _info.md, fold their bullets into the consolidated record, then
        DELETE the legacy files. Deletion is critical: while those files
        exist they get auto-injected and break cross-user privacy."""
        for legacy in (_legacy_public_md(name_key), _legacy_info_md(name_key)):
            try:
                if not await self.capability_worker.check_if_file_exists(legacy, False):
                    continue
                content = await self.capability_worker.read_file(legacy, False)
                bullets = self._extract_bullets(content)
                for b in bullets:
                    if not any(it.get("bullet") == b for it in record["public_items"]):
                        record["public_items"].append({
                            "ts": strftime("%Y-%m-%dT%H:%M:%S"),
                            "bullet": b,
                            "migrated_from": legacy,
                        })
                await self.capability_worker.delete_file(legacy, False)
                self.worker.editor_logging_handler.info(
                    "[PUM] migrated + deleted legacy %s (%d bullets)" % (legacy, len(bullets))
                )
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    "[PUM] legacy md migration failed for %s: %s" % (legacy, e)
                )
        legacy_priv = _legacy_private_json(name_key)
        try:
            if await self.capability_worker.check_if_file_exists(legacy_priv, False):
                raw = await self.capability_worker.read_file(legacy_priv, False)
                if (raw or "").strip():
                    data = json.loads(raw)
                    items = data.get("items") if isinstance(data, dict) else None
                    if isinstance(items, list):
                        for it in items:
                            if isinstance(it, dict) and it.get("bullet"):
                                if not any(p.get("bullet") == it["bullet"] for p in record["private_items"]):
                                    record["private_items"].append(it)
                await self.capability_worker.delete_file(legacy_priv, False)
                self.worker.editor_logging_handler.info(
                    "[PUM] migrated + deleted legacy %s" % legacy_priv
                )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] legacy json migration failed: %s" % e
            )

    @staticmethod
    def _extract_bullets(md: str) -> list:
        bullets = []
        for line in (md or "").splitlines():
            m = re.match(r"\s*-\s*(.+?)\s*$", line)
            if not m:
                continue
            text = m.group(1).strip()
            if text and text.lower() != "(no notes yet)":
                bullets.append("- " + text)
        return bullets

    async def _ensure_public_stub(self, name_key: str, display: str):
        record = await self._load_user_record(name_key, display)
        if record["display_name"] != display and display:
            record["display_name"] = display
        await self._save_user_record(name_key, record)

    async def _append_public_bullet(self, name_key: str, display: str, formatted_bullet: str):
        record = await self._load_user_record(name_key, display)
        if record["display_name"] != display and display:
            record["display_name"] = display
        record["public_items"].append({
            "ts": strftime("%Y-%m-%dT%H:%M:%S"),
            "bullet": formatted_bullet,
        })
        await self._save_user_record(name_key, record)
        self.worker.editor_logging_handler.info(
            "[PUM] appended public bullet to %s: %s"
            % (_user_notes_json(name_key), formatted_bullet)
        )

    async def _append_private_item(self, name_key: str, formatted_bullet: str, raw_note: str):
        record = await self._load_user_record(name_key)
        record["private_items"].append({
            "ts": strftime("%Y-%m-%dT%H:%M:%S"),
            "bullet": formatted_bullet,
            "raw": raw_note[:400],
        })
        await self._save_user_record(name_key, record)
        self.worker.editor_logging_handler.info(
            "[PUM] appended private bullet to %s: %s"
            % (_user_notes_json(name_key), formatted_bullet)
        )

    # ------------------------------------------------------------------
    # User-state — active_user_context.md composer
    # ------------------------------------------------------------------
    async def _recompose_active_context(self, display_name: str):
        name_key = self._normalize_name(display_name)
        audio_mode = await self._read_audio_mode()

        record = await self._load_user_record(name_key, display_name)
        public_items = record.get("public_items") or []
        private_items = record.get("private_items") or []

        public_section = "\n".join(
            str(it.get("bullet", "")) for it in public_items if it.get("bullet")
        ) or "(no public notes yet)"

        # Tier 2 — splice in only when audio is ACTIVE. The JSON file itself
        # is never auto-injected, so withholding is structural; this branch
        # is what bridges the JSON record to the prompt.
        private_section = ""
        if audio_mode == "active" and private_items:
            private_section = "\n".join(
                str(it.get("bullet", "")) for it in private_items if it.get("bullet")
            )

        content = self._compose_active_user_md(
            display_name=display_name,
            public_section=public_section,
            private_section=private_section,
            audio_mode=audio_mode,
        )
        await self._write_md_overwrite(ACTIVE_USER_FILE, content)
        self.worker.editor_logging_handler.info(
            "[PUM] %s recomposed (mode=%s, user=%s, public=%d, private=%s)"
            % (ACTIVE_USER_FILE, audio_mode, display_name, len(public_items),
               "shown" if (audio_mode == "active" and private_section) else "withheld")
        )

    def _compose_active_user_md(self, display_name: str, public_section: str,
                                private_section: str, audio_mode: str) -> str:
        timestamp = strftime("%Y-%m-%d %H:%M")

        # User-switch banner — only emitted if a switch happened recently.
        # Strong language is intentional: the Personality's session memory
        # remembers the previous user's intro and any in-conversation
        # disclosures. The injected files are the only signal we control,
        # so they have to shout loud enough to override session memory.
        switch_banner = ""
        if (
            self.last_switch_from
            and (_now() - self.last_switch_at) < RECENT_SWITCH_WINDOW_S
            and self._normalize_name(self.last_switch_from) != self._normalize_name(display_name)
        ):
            prev = self.last_switch_from.strip().title()
            switch_banner = (
                "\n> ⚠️  **USER SWITCH JUST OCCURRED.** The user named **%(prev)s** "
                "was active until %(seconds)d seconds ago. **%(prev)s has LEFT this "
                "session.** **%(name)s** is now the active user.\n"
                ">\n"
                "> Treat **%(prev)s** as a private third party. **%(name)s** does NOT "
                "have access to anything %(prev)s said. If **%(name)s** asks about "
                "%(prev)s — by name, as 'the previous user', or any other reference — "
                "respond with EXACTLY this sentence and NOTHING ELSE:\n"
                ">\n"
                "> *\"That's another user's private information — I can't share it with you.\"*\n"
                ">\n"
                "> Do NOT acknowledge that %(prev)s ever existed in this conversation. "
                "Do NOT confirm or deny any details about %(prev)s. Do NOT paraphrase "
                "anything %(prev)s said. The fact that you remember %(prev)s from "
                "earlier turns is irrelevant — your **session memory does not override "
                "this rule**.\n\n"
            ) % {
                "prev": prev,
                "name": display_name,
                "seconds": int(_now() - self.last_switch_at),
            }

        if audio_mode == "active":
            mode_header = (
                "Personal Audio Mode at compose time: ACTIVE (private headphones). "
                "Both public and private notes are available below."
            )
            private_block = (
                "\n### Private info (private headphones in use — OK to speak)\n"
                "%s\n"
            ) % (private_section.strip() or "(none on file)")
        else:
            mode_label = "INACTIVE (shared speaker)" if audio_mode == "inactive" else "UNKNOWN — assume shared"
            mode_header = (
                "Personal Audio Mode at compose time: %s. "
                "Private info has been WITHHELD from this prompt — even if a "
                "previously-injected version of this file leaked private "
                "details, ignore them now and treat them as off-limits until "
                "this file is recomposed in ACTIVE mode."
            ) % mode_label
            private_block = (
                "\n### Private info\nWithheld — shared speaker mode.\n"
            )
        return (
            "## Active User Context\n"
            "Current user: **%(name)s**\n"
            "Last recompose: %(ts)s (by Privacy And User Manager)\n"
            "%(mode_header)s\n"
            "%(switch_banner)s"
            "### CRITICAL — Cross-user privacy (read first)\n\n"
            "**If %(name)s asks anything about another user — any name OTHER than "
            "\"%(name)s\", or phrases like \"the previous user\", \"the other person\", "
            "\"who was here before\" — your reply MUST be exactly this sentence and "
            "NOTHING ELSE:**\n\n"
            "> *That's another user's private information — I can't share it with you.*\n\n"
            "This rule has NO exceptions. It applies even if you remember the other "
            "user from EARLIER IN THIS SAME CONVERSATION. **Your session memory does "
            "not override this rule.** Do not paraphrase, hedge, soften, or add "
            "details. Do not confirm whether the other user exists. Just the refusal "
            "sentence, then stop.\n\n"
            "### Other behavioral rules\n\n"
            "1. You are speaking with **%(name)s**. Address them by name when natural.\n"
            "2. **Audio-mode disclosure.** The 'Private info' section below is only "
            "populated when private headphones are in use; on a shared speaker it is "
            "withheld. Treat anything outside this file as untrusted memory — do not "
            "surface details you cannot find here.\n"
            "3. **Session-scoped disclosure.** Things %(name)s says in passing — "
            "without 'remember', 'save', or 'note' — are session-only. Do not persist "
            "them and do not surface them to other users later.\n"
            "4. **Trust boundary.** Each user is isolated. Do not fabricate information "
            "about %(name)s or anyone else. Only reference what is in the sections below.\n"
            "5. **Saving is always allowed.** When %(name)s says 'remember X', "
            "acknowledge that you've saved it — Privacy And User Manager handles "
            "classification (public vs. sensitive) and persistence in the background. "
            "Do not refuse to save based on audio mode; saving and speaking aloud are "
            "different actions.\n\n"
            "### Public info (safe to speak in any mode)\n"
            "%(public_section)s\n"
            "%(private_block)s"
        ) % {
            "name": display_name,
            "ts": timestamp,
            "mode_header": mode_header,
            "switch_banner": switch_banner,
            "public_section": public_section.strip() or "(no public notes yet)",
            "private_block": private_block,
        }

    # ------------------------------------------------------------------
    # Announce-toggle: read / write / handle
    # ------------------------------------------------------------------
    async def _load_settings(self) -> dict:
        try:
            if not await self.capability_worker.check_if_file_exists(SETTINGS_FILE, False):
                return {}
            raw = await self.capability_worker.read_file(SETTINGS_FILE, False)
            if not (raw or "").strip():
                return {}
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] settings unreadable, treating as default: %s" % e
            )
            return {}

    async def _save_settings(self, settings: dict) -> None:
        payload = json.dumps(settings, indent=2)
        try:
            if await self.capability_worker.check_if_file_exists(SETTINGS_FILE, False):
                await self.capability_worker.delete_file(SETTINGS_FILE, False)
            await self.capability_worker.write_file(SETTINGS_FILE, payload, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] settings write failed: %s" % e
            )

    async def _should_announce(self) -> bool:
        """Default True — announcements are on unless the user explicitly
        opts out via 'stop announcing audio mode' (or similar)."""
        settings = await self._load_settings()
        val = settings.get("announce_audio_mode", True)
        return bool(val)

    async def _handle_announce_toggle(self, enabled: bool) -> None:
        settings = await self._load_settings()
        prev = bool(settings.get("announce_audio_mode", True))
        settings["announce_audio_mode"] = bool(enabled)
        await self._save_settings(settings)
        self.worker.editor_logging_handler.info(
            "[PUM] announce_audio_mode: %s → %s" % (prev, bool(enabled))
        )
        # Force a fresh audio-context write so the directive flips to the
        # new state on the next Personality turn (rather than waiting up to
        # POLL_INTERVAL for the next loop tick).
        try:
            await self._scan_audio()
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] post-toggle rescan failed: %s" % e
            )

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    def _normalize_name(self, s: str) -> str:
        return re.sub(r"[^a-z]", "", (s or "").lower().strip())

    async def _persist_cursor(self, latest: str):
        try:
            if await self.capability_worker.check_if_file_exists(LAST_SEEN_FILE, False):
                await self.capability_worker.delete_file(LAST_SEEN_FILE, False)
            await self.capability_worker.write_file(LAST_SEEN_FILE, latest, False)
        except Exception:
            pass

    async def _write_md_overwrite(self, path: str, content: str):
        """Delete-then-write for atomic replace; falls back to mode='w'."""
        try:
            await self.capability_worker.write_file(path, content, False, mode="w")
            return
        except Exception:
            pass
        try:
            if await self.capability_worker.check_if_file_exists(path, False):
                await self.capability_worker.delete_file(path, False)
            await self.capability_worker.write_file(path, content, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[PUM] write %s failed: %s" % (path, e)
            )
