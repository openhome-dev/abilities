"""Real voice call — mic in, speaker out — over the OpenHome voice stream.

This is a parameterized port of the proven reference client. Transport notes
learned the hard way:

* Connect with the **api_key in the URL** (``/voice-stream/<api_key>/<agent_id>``);
  the dashboard's ``web/0`` path is browser-only (needs session cookies).
* The server **requires a browser-like ``User-Agent``** on the handshake — a
  default Python UA is rejected with 1008 (policy violation).
* The agent streams **MP3**, so audio frames are piped straight into ``mpv``.

Mic capture + VAD + barge-in (interrupt) mirror the reference. Requires
``websockets``, ``pyaudio``, ``numpy`` and the ``mpv`` binary.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess

from .config import Config
from .errors import NotAuthenticatedError, OpenHomeError

try:
    import numpy as _np
    import pyaudio as _pyaudio
    import websockets as _websockets
except ImportError:  # pragma: no cover
    _np = _pyaudio = _websockets = None

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_RATE = 16000
_CHANNELS = 1
_FRAMES_PER_BUFFER = 3200


def _require_deps() -> None:
    if _websockets is None or _pyaudio is None or _np is None:
        raise OpenHomeError(
            "Voice calls need extra packages. Install them with:\n"
            "    pip install websockets pyaudio numpy\n"
            "(pyaudio needs PortAudio: macOS `brew install portaudio`, "
            "Linux `apt install portaudio19-dev`)."
        )
    if shutil.which("mpv") is None:
        raise OpenHomeError(
            "Voice calls play audio via 'mpv', which isn't installed.\n"
            "  macOS: brew install mpv   |   Linux: apt install mpv"
        )


class _VoiceCall:
    def __init__(self, config: Config, agent_id, on_text=None, on_status=None):
        if not config.api_key:
            raise NotAuthenticatedError("Voice calls need an API key. Set OPENHOME_API_KEY.")
        self.api_key = config.api_key
        self.agent_id = agent_id
        self.url = (
            f"{config.ws_base}/websocket/voice-stream/{self.api_key}/{self.agent_id}"
        )
        self._on_text = on_text
        self._note = on_status or (lambda _m: None)

        self.format = _pyaudio.paInt16
        self.channels = _CHANNELS
        self.rate = _RATE
        self.frames_per_buffer = _FRAMES_PER_BUFFER

        self.websocket = None
        self.should_send_audio = True
        self.is_speaking = False
        self.mpv = None

        # noise-reduction / VAD state
        self.alpha = 0.95
        self.prev_noise_power = None
        self.energy_history: list[float] = []
        self.last_voice_activity = False
        self.voice_holdoff_counter = 0

        self.pa = _pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.frames_per_buffer,
        )

    # ── mic processing (VAD + noise gate) ────────────────────────────────
    def _process(self, audio_data: bytes) -> bytes:
        arr = _np.frombuffer(audio_data, dtype=_np.int16).astype(_np.float32) / 32768.0
        rms = float(_np.sqrt(_np.mean(arr**2)))

        self.energy_history.append(rms)
        if len(self.energy_history) > 30:
            self.energy_history.pop(0)
        base = float(_np.mean(self.energy_history))
        threshold = base * (1.8 if self.is_speaking else 1.2)

        if not self.last_voice_activity:
            significant = rms > threshold * 1.2
        else:
            significant = rms > threshold * 0.8
        if significant:
            self.last_voice_activity = True
            self.voice_holdoff_counter = 0
        else:
            self.voice_holdoff_counter += 1
            if self.voice_holdoff_counter > 10:
                self.last_voice_activity = False

        if self.is_speaking and rms < threshold * 2.0:
            return b"\x00" * len(audio_data)
        if not self.last_voice_activity:
            return b"\x00" * len(audio_data)

        if self.prev_noise_power is None:
            self.prev_noise_power = rms**2
        noise_power = self.alpha * self.prev_noise_power + (1 - self.alpha) * rms**2
        self.prev_noise_power = noise_power
        gain = max(1 - (noise_power / (rms**2 + 1e-10)), 0.1)
        if self.is_speaking:
            gain *= 0.3
        return (arr * gain * 32768).astype(_np.int16).tobytes()

    # ── send loop ─────────────────────────────────────────────────────────
    async def _send_loop(self) -> None:
        buf: list[bytes] = []
        while True:
            try:
                if not self.should_send_audio:
                    await asyncio.sleep(0.01)
                    continue
                data = self.stream.read(self.frames_per_buffer, exception_on_overflow=False)
                buf.append(self._process(data))
                if len(buf) < 5:
                    continue
                has_audio = any(_np.frombuffer(f, dtype=_np.int16).any() for f in buf)
                if has_audio:
                    if self.is_speaking:  # barge-in
                        await self._interrupt()
                    for f in buf:
                        await self.websocket.send(
                            json.dumps({"type": "audio", "data": base64.b64encode(f).decode()})
                        )
                buf = []
            except _websockets.exceptions.ConnectionClosed:
                break
            except Exception as exc:  # noqa: BLE001
                self._note(f"send error: {exc}")
            await asyncio.sleep(0.01)

    async def _interrupt(self) -> None:
        if self.mpv and self.mpv.stdin:
            try:
                self.mpv.stdin.write(b"q\n")
                await self.mpv.stdin.drain()
            except (BrokenPipeError, ConnectionError):
                pass
        await self.websocket.send(json.dumps({"type": "text", "data": "interrupt-event"}))
        self.is_speaking = False

    # ── receive loop ──────────────────────────────────────────────────────
    async def _recv_loop(self) -> None:
        while True:
            try:
                msg = json.loads(await self.websocket.recv())
            except _websockets.exceptions.ConnectionClosed:
                break
            except Exception as exc:  # noqa: BLE001
                self._note(f"recv error: {exc}")
                continue

            t = msg.get("type")
            if t == "message":
                if self._on_text:
                    self._on_text(msg.get("data", {}))
            elif t == "text":
                await self._handle_text(msg.get("data"))
            elif t == "audio":
                await self._handle_audio(msg.get("data"))

    async def _handle_text(self, data) -> None:
        if data == "audio-init":
            self.is_speaking = True
            self.mpv = await asyncio.create_subprocess_exec(
                "mpv", "--no-cache", "--no-terminal", "--", "fd://0",
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            await self.websocket.send(json.dumps({"type": "text", "data": "bot-speaking"}))
        elif data == "interrupt":
            if self.mpv and self.mpv.stdin:
                self.mpv.stdin.write(b"q\n")
                await self.mpv.stdin.drain()
            self.is_speaking = False
        elif data == "audio-end":
            if self.mpv and self.mpv.stdin:
                try:
                    self.mpv.stdin.close()
                except BrokenPipeError:
                    pass
                await self.mpv.communicate()
                self.mpv = None
            self.is_speaking = False
            await self.websocket.send(json.dumps({"type": "text", "data": "bot-speak-end"}))

    async def _handle_audio(self, b64) -> None:
        await self.websocket.send(json.dumps({"type": "ack", "data": "audio-received"}))
        if self.mpv and self.mpv.stdin and self.is_speaking:
            try:
                self.mpv.stdin.write(base64.b64decode(b64))
                await self.mpv.stdin.drain()
            except (BrokenPipeError, ConnectionError):
                pass

    async def run(self) -> None:
        async with _websockets.connect(
            self.url, additional_headers={"User-Agent": _BROWSER_UA}
        ) as ws:
            self.websocket = ws
            self._note("connected — speak now (Ctrl-C to hang up)")
            await asyncio.gather(self._send_loop(), self._recv_loop())

    def close(self) -> None:
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
            if self.pa:
                self.pa.terminate()
        except Exception:  # noqa: BLE001
            pass


def voice_call(config: Config, agent_id="0", *, on_text=None, on_status=None) -> None:
    """Run an interactive mic-in / speaker-out voice call (blocks until hung up)."""
    _require_deps()
    call = _VoiceCall(config, agent_id, on_text=on_text, on_status=on_status)
    try:
        asyncio.run(call.run())
    except KeyboardInterrupt:
        pass
    finally:
        call.close()
