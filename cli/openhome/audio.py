"""Real voice call — mic in, speaker out — over the OpenHome voice stream.

Parameterized port of the proven reference clients. Transport facts learned the
hard way:

* Connect with the **api_key in the URL** (``/voice-stream/<api_key>/<agent_id>``);
  the dashboard's ``web/0`` path is browser-only (needs session cookies).
* The server **requires a browser-like ``User-Agent``** on the handshake, or it
  closes with 1008 (policy violation).
* The agent streams **MP3**, so audio frames are piped straight into ``mpv``.

`bot-speak-end` timing: rather than closing mpv's stdin and waiting for the process
to exit (which respawns mpv every turn and can mis-time the signal), we keep **one
persistent mpv** and poll its **IPC socket** (`--input-ipc-server`) for
``playback-time``. We send ``bot-speak-end`` only once that time stops advancing —
i.e. playback has actually drained. (Learned from the DevKit reference client.)

Requires ``websockets``, ``pyaudio``, ``numpy`` and the ``mpv`` binary.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
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
# Playback is "drained" once playback-time hasn't advanced for this many polls.
_DRAIN_STABLE_POLLS = 4
_DRAIN_POLL_INTERVAL = 0.1
_DRAIN_MAX_POLLS = 600  # ~60s safety cap


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
        self.url = f"{config.ws_base}/websocket/voice-stream/{config.api_key}/{agent_id}"
        self._on_text = on_text
        self._note = on_status or (lambda _m: None)

        self.frames_per_buffer = _FRAMES_PER_BUFFER
        self.websocket = None
        self.is_speaking = False
        self.is_interrupted = False

        self.mpv = None
        self.sock_path = f"/tmp/openhome-mpv-{os.getpid()}.sock"

        # VAD / noise-gate state
        self.alpha = 0.95
        self.prev_noise_power = None
        self.energy_history: list[float] = []
        self.last_voice_activity = False
        self.voice_holdoff_counter = 0

        self.pa = _pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=_pyaudio.paInt16, channels=_CHANNELS, rate=_RATE,
            input=True, frames_per_buffer=self.frames_per_buffer,
        )

    # ── mpv playback (persistent + IPC) ──────────────────────────────────
    async def _ensure_mpv(self) -> None:
        if self.mpv and self.mpv.returncode is None:
            return
        self.mpv = await asyncio.create_subprocess_exec(
            "mpv", "--no-cache", "--no-terminal",
            f"--input-ipc-server={self.sock_path}",
            "--demuxer-lavf-format=mp3", "--", "fd://0",
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    async def _kill_mpv(self) -> None:
        if self.mpv:
            try:
                self.mpv.kill()
                await self.mpv.wait()
            except (ProcessLookupError, OSError):
                pass
            self.mpv = None

    async def _read_ipc_reply(self, reader):
        """Read mpv IPC lines, skipping async event lines, return the reply's
        ``data`` (or None)."""
        for _ in range(10):
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=1.0)
            except (asyncio.TimeoutError, TimeoutError):
                return None
            if not line:
                return None
            try:
                resp = json.loads(line.decode())
            except ValueError:
                continue
            if "event" in resp:  # async event, not our reply
                continue
            return resp.get("data")
        return None

    async def _connect_ipc(self):
        """Open the mpv IPC socket, retrying while mpv finishes starting up."""
        for _ in range(20):  # ~2s
            try:
                return await asyncio.open_unix_connection(self.sock_path)
            except (FileNotFoundError, ConnectionRefusedError, OSError):
                await asyncio.sleep(0.1)
        return None

    async def _await_playback_drained(self) -> None:
        """Block until playback has started AND then stopped advancing.

        Correctness depends on two guards learned from the echo bug:
        * **started** — never conclude "drained" until playback-time has actually
          advanced past 0 (otherwise initial buffering looks like silence and we'd
          open the mic while the bot is still about to speak).
        * **only count real, unchanged readings** as stable — a failed/`None` read
          is a transient miss, not progress and not a stall.
        """
        conn = await self._connect_ipc()
        if conn is None:
            await asyncio.sleep(1.0)  # no IPC — conservative fallback
            return
        reader, writer = conn
        last, stable, started = None, 0, False
        try:
            for _ in range(_DRAIN_MAX_POLLS):
                if not self.mpv or self.is_interrupted:
                    return
                writer.write(b'{"command":["get_property","playback-time"]}\n')
                await writer.drain()
                pt = await self._read_ipc_reply(reader)
                if isinstance(pt, (int, float)):
                    if pt > 0:
                        started = True
                    if last is not None and abs(pt - last) < 1e-3:
                        stable += 1
                    else:
                        stable = 0
                    last = pt
                # else: transient read miss — leave counters untouched
                if started and stable >= _DRAIN_STABLE_POLLS:
                    return
                await asyncio.sleep(_DRAIN_POLL_INTERVAL)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def _finish_speaking(self) -> None:
        """On audio-end: wait for real playback drain, then signal bot-speak-end."""
        await self._await_playback_drained()
        if self.is_interrupted:
            return
        self.is_speaking = False
        await self._send_text("bot-speak-end")
        self._note("your turn — speak")

    # ── ws helpers ────────────────────────────────────────────────────────
    async def _send_text(self, value: str) -> None:
        try:
            await self.websocket.send(json.dumps({"type": "text", "data": value}))
        except _websockets.exceptions.ConnectionClosed:
            pass

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

    async def _send_loop(self) -> None:
        buf: list[bytes] = []
        while True:
            try:
                # Keep draining the mic device so it never overflows…
                data = self.stream.read(self.frames_per_buffer, exception_on_overflow=False)
                # …but half-duplex: don't capture while the bot is speaking, or the
                # speaker audio echoes back into the mic and triggers a false barge-in
                # (laptops have no hardware echo cancellation).
                if self.is_speaking:
                    buf.clear()
                    await asyncio.sleep(0.005)
                    continue
                buf.append(self._process(data))
                if len(buf) < 5:
                    await asyncio.sleep(0.001)
                    continue
                if any(_np.frombuffer(f, dtype=_np.int16).any() for f in buf):
                    for f in buf:
                        await self.websocket.send(
                            json.dumps({"type": "audio", "data": base64.b64encode(f).decode()})
                        )
                buf = []
            except _websockets.exceptions.ConnectionClosed:
                break
            except Exception as exc:  # noqa: BLE001
                self._note(f"send error: {exc}")
            await asyncio.sleep(0.001)

    # ── receive loop ──────────────────────────────────────────────────────
    async def _recv_loop(self) -> None:
        while True:
            try:
                msg = json.loads(await self.websocket.recv())
            except _websockets.exceptions.ConnectionClosed:
                break
            except Exception:  # noqa: BLE001
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
            self.is_interrupted = False
            await self._ensure_mpv()
            self.is_speaking = True
            await self._send_text("bot-speaking")
        elif data == "interrupt":
            await self._kill_mpv()
            self.is_speaking = False
        elif data == "audio-end":
            asyncio.create_task(self._finish_speaking())

    async def _handle_audio(self, b64) -> None:
        try:
            await self.websocket.send(json.dumps({"type": "ack", "data": "audio-received"}))
        except _websockets.exceptions.ConnectionClosed:
            return
        if self.is_interrupted or not self.is_speaking:
            return
        if self.mpv and self.mpv.stdin and self.mpv.returncode is None:
            try:
                self.mpv.stdin.write(base64.b64decode(b64))
                await self.mpv.stdin.drain()
            except (BrokenPipeError, ConnectionError, ValueError):
                pass

    async def run(self) -> None:
        async with _websockets.connect(
            self.url, additional_headers={"User-Agent": _BROWSER_UA}
        ) as ws:
            self.websocket = ws
            self._note("connected — speak now (Ctrl-C to hang up)")
            await asyncio.gather(self._send_loop(), self._recv_loop())

    async def aclose(self) -> None:
        await self._kill_mpv()
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
            if self.pa:
                self.pa.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            if os.path.exists(self.sock_path):
                os.unlink(self.sock_path)
        except OSError:
            pass


def voice_call(config: Config, agent_id="0", *, on_text=None, on_status=None) -> None:
    """Run an interactive mic-in / speaker-out voice call (blocks until hung up)."""
    _require_deps()
    call = _VoiceCall(config, agent_id, on_text=on_text, on_status=on_status)

    async def _main():
        try:
            await call.run()
        finally:
            await call.aclose()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
