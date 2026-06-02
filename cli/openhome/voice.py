"""Voice-to-voice WebSocket client for OpenHome agents.

Connects to ``wss://<base>/websocket/voice-stream/<api_key>/<agent_id>`` and speaks
the OpenHome session protocol so a trigger phrase fires the matching ability —
without going through the dashboard (action #5). Text in, text out (the audio
lifecycle messages are acknowledged so the server keeps the session alive).

Two entry points:

* :func:`trigger_once` — send one phrase, return the agent's reply (good for scripts).
* :class:`VoiceSession` — an interactive send/receive loop (used by ``openhome call``).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Callable

from websocket import WebSocketApp, ABNF

from . import endpoints
from .config import Config
from .errors import NotAuthenticatedError, OpenHomeError

_PING_INTERVAL = 30
_WS_ORIGIN = "https://app.openhome.com"
# Note: Origin is passed via run_forever(origin=...), NOT here — putting it in the
# header list too makes websocket-client send a duplicate Origin and the server
# rejects the handshake with "invalid Origin header: multiple values".
_WS_HEADERS = [
    (
        "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
]


@dataclass
class TextMessage:
    content: str
    role: str
    live: bool
    final: bool


def _build_url(config: Config, agent_id: str) -> str:
    if not config.api_key:
        raise NotAuthenticatedError(
            "Voice calls need an API key. Set OPENHOME_API_KEY."
        )
    return f"{config.ws_base}{endpoints.voice_stream(config.api_key, agent_id)}"


class VoiceSession:
    """A live voice-stream connection to one agent.

    Callbacks (all optional):
        on_connect()                         — socket open and ready
        on_message(TextMessage)              — assistant/user text frames
        on_event(type:str, data)             — every frame (for logging)
        on_error(Exception)
        on_close(code:int)
    """

    def __init__(
        self,
        config: Config,
        agent_id: str,
        *,
        on_connect: Callable[[], None] | None = None,
        on_message: Callable[[TextMessage], None] | None = None,
        on_event: Callable[[str, object], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_close: Callable[[int], None] | None = None,
    ):
        self._config = config
        self._agent_id = agent_id
        self._on_connect = on_connect
        self._on_message = on_message
        self._on_event = on_event
        self._on_error = on_error
        self._on_close = on_close

        self._app: WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._ping_stop = threading.Event()
        self._closed = threading.Event()

    # ── lifecycle ───────────────────────────────────────────────────────
    def connect(self) -> "VoiceSession":
        url = _build_url(self._config, self._agent_id)
        self._app = WebSocketApp(
            url,
            header=_WS_HEADERS,
            on_open=self._handle_open,
            on_message=self._handle_message,
            on_error=self._handle_error,
            on_close=self._handle_close,
        )
        self._thread = threading.Thread(
            target=self._app.run_forever,
            kwargs={
                "ping_interval": 0,  # we send our own protocol-level pings
                "origin": _WS_ORIGIN,  # single Origin header (see _WS_HEADERS note)
                "suppress_origin": False,
            },
            daemon=True,
        )
        self._thread.start()
        return self

    def send(self, msg_type: str, data: object) -> None:
        if self._app and self._app.sock and self._app.sock.connected:
            self._app.send(json.dumps({"type": msg_type, "data": data}))

    def say(self, text: str) -> None:
        """Send user speech (transcribed text) to the agent."""
        self.send("transcribed", text)

    def close(self) -> None:
        self._ping_stop.set()
        if self._app:
            self._app.close()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the connection closes. Returns True if it closed in time."""
        return self._closed.wait(timeout)

    # ── internal handlers ───────────────────────────────────────────────
    def _handle_open(self, _app: WebSocketApp) -> None:
        threading.Thread(target=self._ping_loop, daemon=True).start()
        if self._on_connect:
            self._on_connect()

    def _ping_loop(self) -> None:
        while not self._ping_stop.wait(_PING_INTERVAL):
            self.send("ping", None)

    def _handle_message(self, _app: WebSocketApp, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        msg_type = msg.get("type")
        data = msg.get("data")

        if msg_type == "message" and isinstance(data, dict):
            content = data.get("content")
            if content and self._on_message:
                self._on_message(
                    TextMessage(
                        content=content,
                        role=data.get("role", "assistant"),
                        live=bool(data.get("live")),
                        final=bool(data.get("final")),
                    )
                )
        elif msg_type == "text":
            # Audio lifecycle handshake — required by the protocol.
            if data == "audio-init":
                self.send("text", "bot-speaking")
            elif data == "audio-end":
                self.send("text", "bot-speak-end")
        elif msg_type == "audio":
            # Acknowledge audio receipt even in text-only mode.
            self.send("ack", "audio-received")
        elif msg_type == "error-event":
            err = data if isinstance(data, dict) else {}
            message = err.get("message") or err.get("title") or "Unknown server error"
            if self._on_error:
                self._on_error(OpenHomeError(message))

        if self._on_event:
            self._on_event(msg_type, data)

    def _handle_error(self, _app: WebSocketApp, error: Exception) -> None:
        if self._on_error:
            self._on_error(error)

    def _handle_close(self, _app: WebSocketApp, code: int | None, _msg: str | None) -> None:
        self._ping_stop.set()
        self._closed.set()
        if self._on_close:
            self._on_close(code or 1000)


def trigger_once(
    config: Config,
    agent_id: str,
    phrase: str,
    *,
    timeout: float = 30.0,
    greeting_wait: float = 10.0,
) -> str:
    """Send one phrase and return the agent's reply that the phrase produced.

    Agents greet on connect, so this waits for the agent's opening line (the first
    assistant message) before sending ``phrase`` — otherwise the greeting would be
    mistaken for the answer. If no greeting arrives within ``greeting_wait`` seconds,
    the phrase is sent anyway. Returns the assistant's reply text, or "" on timeout.
    """
    state = {"reply": "", "phrase_sent": False, "seen_any": False}
    done = threading.Event()

    def send_phrase() -> None:
        if not state["phrase_sent"]:
            state["phrase_sent"] = True
            session.say(phrase)

    def on_connect() -> None:
        # Fallback only if the agent never says anything (no greeting at all).
        def maybe_send():
            if not state["seen_any"]:
                send_phrase()
        t = threading.Timer(greeting_wait, maybe_send)
        t.daemon = True
        t.start()

    def on_message(m: TextMessage) -> None:
        if m.role != "assistant":
            return
        state["seen_any"] = True  # marks even live frames, so a slow greeting counts
        if not m.final:
            return
        if not state["phrase_sent"]:
            # That was the greeting — now ask, and capture the next final as the reply.
            send_phrase()
        else:
            state["reply"] = m.content
            done.set()

    def on_error(_e: Exception) -> None:
        done.set()

    session = VoiceSession(
        config,
        agent_id,
        on_connect=on_connect,
        on_message=on_message,
        on_error=on_error,
        on_close=lambda _code: done.set(),
    )
    session.connect()
    if done.wait(timeout):
        time.sleep(0.2)  # brief grace for trailing frames
    session.close()
    return state["reply"]
