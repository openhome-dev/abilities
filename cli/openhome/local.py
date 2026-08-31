from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import logging.handlers
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from .config import CONFIG_DIR, Config

LOCAL_DIR = CONFIG_DIR / "local"
PID_FILE = LOCAL_DIR / "local.pid"
LOG_FILE = LOCAL_DIR / "local.log"

log = logging.getLogger("openhome.local")
MAX_LOG_CHARS = 400
IS_WINDOWS = platform.system() == "Windows"
DETECT_TIMEOUT = 20.0 if IS_WINDOWS else 5.0  # node/CLI cold-start is slower on Windows

# Agent readiness.
READY = "ready"          # installed and usable now
NOT_READY = "not_ready"  # installed but can't serve yet (needs an action)
ABSENT = "absent"        # not installed


# ── Hermes ACP transport ─────────────────────────────────────────────────────
# Hermes is driven over ACP (Agent Client Protocol) instead of a cold
# `hermes -z` per turn. One `hermes acp` process is spawned at startup and held
# warm; each request reuses it, so Hermes keeps its prompt cache, memory, and
# session context across turns. The utterance is sent as a structured ACP field
# (not a shell arg), so nothing is shell-interpreted.
#
# A dedicated asyncio loop runs in a background thread and owns the connection;
# the synchronous agent-run path submits work to it and blocks for the reply,
# matching the existing run_backend contract.

_acp = {
    "thread": None,     # background thread running the asyncio loop
    "loop": None,       # that thread's event loop
    "conn": None,       # ClientSideConnection to hermes acp
    "proc": None,       # the hermes acp subprocess
    "session_id": None, # the warm ACP session
    "ready": False,     # handshake completed
    "error": None,      # last startup error (for detection hint)
    "hinted": False,    # whether the voice-brevity hint has been sent yet
}


def _acp_available() -> bool:
    """True if the `agent-client-protocol` package is importable."""
    try:
        import acp  # noqa: F401
        return True
    except Exception:
        return False


def _acp_text_of(update) -> str | None:
    """Pull spoken-reply text out of a session_update payload. Only
    agent_message_chunk is the actual answer; agent_thought_chunk is Hermes's
    internal reasoning and must NOT be spoken/returned."""
    if getattr(update, "session_update", None) != "agent_message_chunk":
        return None
    content = getattr(update, "content", None)
    if content is not None:
        text = getattr(content, "text", None)
        if isinstance(text, str):
            return text
    return None


def _acp_extract_reply(prompt_response, collected_text) -> str:
    """Pull speakable text from a prompt round-trip: prefer text streamed via
    session_update; fall back to any text on the PromptResponse.

    Streamed agent_message_chunk fragments are raw substrings of one flowing
    message (verified against real Hermes output, e.g. one chunk was literally
    ') was:\\n\\n' with its own embedded newline) - they must be concatenated
    directly with NO separator. Joining with '\\n' would insert a spurious
    newline between every token.
    """
    text = "".join(t for t in collected_text if t).strip()
    if text:
        return text
    for attr in ("content", "text", "stop_reason"):
        val = getattr(prompt_response, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "(no response)"


async def _spawn_hermes_acp(binary: str, env: dict):
    """Spawn `hermes acp` as a long-lived subprocess, Windows-safe.

    On Windows, `binary` may resolve to a `.cmd`/`.bat` shim (needs the shell
    to run at all - the same WinError 193 class of issue `_run` works around
    for sync calls) or a native `.exe` (the common case, since Hermes is
    normally pip/uv-installed with a real launcher stub - but we can't be
    certain across every install method, so handle both). Runs in its own
    process group on Windows so it can be cleanly torn down as a unit.
    """
    kw = dict(
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env,
    )
    if IS_WINDOWS:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        if os.path.splitext(binary)[1].lower() in (".cmd", ".bat"):
            cmdline = subprocess.list2cmdline([binary, "acp"])
            return await asyncio.create_subprocess_shell(cmdline, **kw)
    return await asyncio.create_subprocess_exec(binary, "acp", **kw)


async def _acp_start(timeout: float) -> None:
    """Spawn `hermes acp`, run initialize -> new_session, hold the connection."""
    import acp
    from acp import Client, connect_to_agent
    from acp.meta import PROTOCOL_VERSION
    from acp.schema import RequestPermissionResponse, DeniedOutcome, AllowedOutcome

    collected: list[str] = []
    kind_counts: dict[str, int] = {}

    class _LocalLinkClient(Client):
        # NOTE: the acp library invokes these with keyword arguments matching
        # its Client protocol (session_id=..., update=..., etc.) - NOT a single
        # `params` object. Signatures below match acp.interfaces.Client exactly.

        async def session_update(self, session_id, update, **kwargs):
            kind = getattr(update, "session_update", type(update).__name__)
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            text = _acp_text_of(update)
            if text:
                collected.append(text)

        async def request_permission(self, session_id, tool_call, options, **kwargs):
            # TODO(voice-approvals): forward to the ability and map the spoken
            # answer onto allow_once / allow_session / deny. Until that lands we
            # fail safe by denying (matching ACP's own timeout/error behavior).
            #
            # Logged at INFO (not DEBUG): this has never fired in testing yet,
            # so when it does we want the real payload visible by default to
            # learn its actual shape (the wire schema has no "allow_session"
            # kind - only allow_once/allow_always/reject_once/reject_always -
            # so "Allow for session" apparently surfaces via option_id/name,
            # not kind; we don't yet know its exact string).
            tool_name = getattr(tool_call, "title", None) or getattr(tool_call, "tool_call_id", "?")
            opts_desc = [(getattr(o, "option_id", "?"), getattr(o, "name", "?"), getattr(o, "kind", "?"))
                         for o in options]
            log.info("Hermes ACP permission request: tool=%r options=%r", tool_name, opts_desc)
            reject = next((o for o in options if getattr(o, "kind", "") == "reject_once"), None)
            if reject is not None:
                log.info("Hermes ACP permission: denying (option_id=%s)", reject.option_id)
                return RequestPermissionResponse(
                    outcome=AllowedOutcome(outcome="selected", option_id=reject.option_id))
            log.warning("Hermes ACP permission: no reject_once option offered; denying via cancelled outcome")
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))

        async def write_text_file(self, session_id, path, content, **kwargs):
            log.debug("acp write_text_file (ignored): %s", path)
            return None

        async def read_text_file(self, session_id, path, line=None, limit=None, **kwargs):
            log.debug("acp read_text_file (ignored): %s", path)
            from acp.schema import ReadTextFileResponse
            return ReadTextFileResponse(content="")

    env = dict(os.environ)
    env["HERMES_ACP_SKIP_CONFIGURED_MCP"] = "1"
    binary = which("hermes") or "hermes"
    proc = await _spawn_hermes_acp(binary, env)
    _acp["proc"] = proc
    _acp["_collected"] = collected
    _acp["_kind_counts"] = kind_counts

    async def _drain_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            log.debug("hermes-acp: %s", line.decode(errors="replace").rstrip())
    asyncio.ensure_future(_drain_stderr())

    conn = connect_to_agent(_LocalLinkClient(), proc.stdin, proc.stdout)
    init_resp = await asyncio.wait_for(conn.initialize(protocol_version=PROTOCOL_VERSION), timeout)
    log.debug("acp initialize response: %r", init_resp)
    sess = await asyncio.wait_for(conn.new_session(cwd=os.path.expanduser("~")), timeout)
    log.debug("acp new_session response: %r", sess)
    if not getattr(sess, "session_id", None):
        raise RuntimeError(f"new_session returned no session_id: {sess!r}")

    # Explicitly request the safest mode ("default" = ask before edits) rather
    # than relying on whatever Hermes defaults to. Best-effort: some Hermes
    # versions may not expose a "default" mode id, so don't fail startup over it.
    try:
        modes = getattr(getattr(sess, "modes", None), "available_modes", None) or []
        if any(getattr(m, "id", None) == "default" for m in modes):
            await conn.set_session_mode(session_id=sess.session_id, mode_id="default")
    except Exception as exc:
        log.debug("acp set_session_mode(default) failed (continuing): %s", exc)

    _acp["conn"] = conn
    _acp["session_id"] = sess.session_id
    _acp["ready"] = True
    log.info("Hermes ACP ready (session=%s)", sess.session_id)


def acp_start(timeout: float = 30.0) -> bool:
    """Spawn and hold the Hermes ACP connection on a background loop. Returns
    True on success. Safe to call once at worker startup."""
    if _acp["ready"]:
        return True
    if not _acp_available():
        _acp["error"] = "acp-missing"
        return False

    loop = asyncio.new_event_loop()

    def _run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, daemon=True, name="hermes-acp")
    thread.start()
    _acp["thread"] = thread
    _acp["loop"] = loop

    fut = asyncio.run_coroutine_threadsafe(_acp_start(timeout), loop)
    try:
        fut.result(timeout=timeout + 5)
        return True
    except Exception as exc:
        _acp["error"] = str(exc)
        log.error("Hermes ACP failed to start: %s", exc)
        acp_stop()
        return False


async def _acp_shutdown() -> None:
    """Cancel pending ACP tasks and close the subprocess cleanly, run ON the
    ACP loop (must happen before the loop is stopped, or asyncio complains
    about destroyed tasks / a closed event loop on exit)."""
    proc = _acp.get("proc")
    if proc is not None:
        if IS_WINDOWS:
            # If hermes was spawned via a shell wrapper (.cmd/.bat shim),
            # proc.terminate() only kills that cmd.exe wrapper, leaving the
            # real hermes process - and anything IT spawned, e.g. its own
            # terminal-tool sandboxes - orphaned. taskkill /T kills the whole
            # process tree given the top PID, which is correct either way.
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/T", "/F", "/PID", str(proc.pid),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=5.0)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
        else:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def acp_stop() -> None:
    """Tear down the ACP process and its background loop."""
    loop = _acp.get("loop")
    if loop is not None and loop.is_running():
        fut = asyncio.run_coroutine_threadsafe(_acp_shutdown(), loop)
        try:
            fut.result(timeout=5.0)
        except Exception:
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
    thread = _acp.get("thread")
    if thread is not None:
        thread.join(timeout=2.0)
    for k in ("thread", "loop", "conn", "proc", "session_id"):
        _acp[k] = None
    _acp["hinted"] = False
    _acp["ready"] = False


# ACP has no session-level "system prompt" field (checked: neither new_session
# nor prompt() accept one) - the only lever is the prompt content itself. So we
# prepend this once, on the FIRST turn of each session, to steer Hermes toward
# short, speakable replies instead of its normal (often long, markdown-heavy,
# tool-narrating) chat style.
VOICE_SYSTEM_HINT = (
    "[You are Hermes Agent, accessed through OpenHome, a voice AI platform. "
    "This conversation happens over a voice interface - your reply will be "
    "spoken aloud, not read as text.\n\n"
    "Respond quickly: give the answer first, don't narrate what you're about "
    "to do, and don't over-deliberate before acting. Your full tools and "
    "capabilities remain available - use them whenever they're genuinely "
    "needed for a correct answer - but skip using a tool just to double-check "
    "something you're already confident about.\n\n"
    "Keep replies short and speakable: a few plain sentences, no markdown, "
    "no bullet lists, no code blocks, no headers. If asked about \"Hermes\" "
    "or yourself, that's you - answer directly rather than treating it as a "
    "separate system to consult.]\n\n"
)


def _acp_alive() -> bool:
    """True if the held ACP subprocess is still running."""
    proc = _acp.get("proc")
    if proc is None:
        return False
    return proc.returncode is None


# One ACP session and one streamed-chunk buffer are shared by all callers, and
# handle_message dispatches each request on its own thread - so two overlapping
# hermes requests would interleave into the same buffer and corrupt both
# replies (verified: both callers got each other's chunks). Serialize them.
_acp_request_lock = threading.Lock()


def run_hermes_acp(data: str, timeout: float) -> str:
    """Send one utterance over the held ACP connection and return the reply.

    Drop-in runner for the hermes agent (replaces the old ``hermes -z`` path).
    Requests are serialized: one Hermes turn at a time per worker.
    """
    # Wait for any in-flight turn, but don't queue forever - a caller that
    # can't get the lock in time gets a clean timeout rather than hanging.
    if not _acp_request_lock.acquire(timeout=timeout):
        raise TimeoutError("another Hermes request is still running")
    try:
        return _run_hermes_acp_locked(data, timeout)
    finally:
        _acp_request_lock.release()


def _run_hermes_acp_locked(data: str, timeout: float) -> str:
    """The actual ACP round-trip. Caller must hold _acp_request_lock."""
    if not _acp["ready"]:
        # Lazy start if the worker didn't (e.g. first request before startup).
        if not acp_start(timeout):
            raise RuntimeError(_acp.get("error") or "Hermes ACP not available")
    elif not _acp_alive():
        # The held subprocess died (crash, OOM-kill, user killed it). Without
        # this, `ready` stays True forever and every later request fails
        # against a dead connection until someone restarts the whole worker.
        # Respawn once; a fresh process means a fresh session, so the voice
        # hint is re-sent and prior conversation context is lost - which is
        # unavoidable, since ACP sessions live in the process that died.
        log.warning("Hermes ACP process is gone - restarting it")
        acp_stop()
        if not acp_start(timeout):
            raise RuntimeError(_acp.get("error") or "Hermes ACP could not be restarted")

    from acp import text_block

    collected = _acp.get("_collected")
    if collected is not None:
        collected.clear()
    kind_counts = _acp.get("_kind_counts")
    if kind_counts is not None:
        kind_counts.clear()

    session_id = _acp["session_id"]
    if not _acp.get("hinted"):
        data = VOICE_SYSTEM_HINT + data
        _acp["hinted"] = True
    log.info("Hermes ACP request: %s", shorten(data))

    async def _prompt():
        conn = _acp["conn"]
        try:
            return await asyncio.wait_for(
                conn.prompt(session_id=session_id, prompt=[text_block(data)]),
                timeout,
            )
        except asyncio.TimeoutError:
            # Don't just walk away: tell Hermes to actually stop the turn (it
            # keeps running server-side otherwise, wasting tool calls/tokens
            # after we've already given up and returned an error upstream).
            log.warning("Hermes ACP turn exceeded %.0fs - cancelling", timeout)
            try:
                await conn.cancel(session_id=session_id)
            except Exception as exc:
                log.debug("acp cancel() failed (turn may have already ended): %s", exc)
            raise

    fut = asyncio.run_coroutine_threadsafe(_prompt(), _acp["loop"])
    try:
        resp = fut.result(timeout=timeout + 5)
    except (TimeoutError, asyncio.TimeoutError, concurrent.futures.TimeoutError):
        # NOTE: these three are the SAME class as of Python 3.11+, but this
        # module supports >=3.10 where they are distinct - catch all three
        # explicitly rather than relying on the 3.11+ unification.
        # This catches both the inner wait_for timeout (which already
        # cancelled the turn above) and a genuine outer hang. Use fut.done()
        # to tell them apart so we don't call cancel() twice for one timeout.
        if not fut.done():
            # The coroutine itself never returned even after our extra grace
            # period - the event loop may be stuck, not just the ACP turn.
            log.error("Hermes ACP appears unresponsive (event loop did not "
                      "finish the cancel attempt within the grace period)")
        raise
    reply = _acp_extract_reply(resp, collected or [])
    log.info("Hermes ACP reply (%s, stop=%s): %s",
              ", ".join(f"{k}={v}" for k, v in (kind_counts or {}).items()) or "no updates",
              getattr(resp, "stop_reason", "?"), shorten(reply))
    return reply


# ── logging ──────────────────────────────────────────────────────────────────
def setup_logging(foreground: bool) -> None:
    """Attach a rotating file handler always, plus a screen handler in the
    foreground. Safe to call more than once.

    ``openhome local start`` runs detached (foreground=False) and writes ONLY
    to the file - there is no screen handler in that case - and
    ``openhome local logs`` reads directly from this same file. So the file
    handler's level is what actually controls verbosity for the common
    start+logs workflow, not just ``openhome local run``. Both default to
    INFO so hermes-acp's internal chatter (every streamed token, subprocess
    stderr, plugin registration spam) doesn't drown normal use; set
    OPENHOME_DEBUG=1 (before ``start`` or ``run``) for full DEBUG detail when
    troubleshooting.
    """
    if log.handlers:
        return
    log.setLevel(logging.DEBUG)
    log.propagate = False
    file_level = logging.DEBUG if os.environ.get("OPENHOME_DEBUG") else logging.INFO
    screen_level = file_level

    LOCAL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    log.addHandler(file_handler)

    if foreground:
        try:
            import coloredlogs
            coloredlogs.install(
                level=screen_level, logger=log,
                fmt="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S",
            )
        except ImportError:
            screen = logging.StreamHandler()
            screen.setLevel(screen_level)
            screen.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"
            ))
            log.addHandler(screen)


def shorten(text: str) -> str:
    """Collapse whitespace and truncate for tidy log lines."""
    text = " ".join((text or "").split())
    if len(text) <= MAX_LOG_CHARS:
        return text
    return text[:MAX_LOG_CHARS] + f"… ({len(text)} chars)"


def os_name() -> str:
    """Normalized OS id (mac / linux / windows) for the agent's prompt."""
    system = platform.system()
    return {"Darwin": "mac", "Linux": "linux", "Windows": "windows"}.get(system, system.lower())


# ── finding binaries ─────────────────────────────────────────────────────────
def which(name: str) -> str | None:
    """Locate a binary across the places package managers install it. A detached
    worker rarely inherits the user's full interactive PATH (nvm, pnpm, bun,
    homebrew, ...), so we look beyond ``shutil.which``.

    On Windows, prefer an executable extension (.cmd/.exe/.bat): npm drops both
    a bare (extensionless, Unix) shim and a .cmd next to each other, and running
    the bare one raises WinError 193 ("not a valid Win32 application")."""
    if IS_WINDOWS:
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(name + ext)
            if found:
                return found
        found = shutil.which(name)
        if found and os.path.splitext(found)[1].lower() in (".cmd", ".exe", ".bat"):
            return found
    else:
        found = shutil.which(name)
        if found:
            return found

    home = os.path.expanduser("~")
    dirs = [
        os.path.join(home, ".npm-global", "bin"),
        os.path.join(home, ".npm", "bin"),
        os.path.join(home, "AppData", "Roaming", "npm"),
        os.path.join(home, "node_modules", ".bin"),
        os.path.join(home, ".local", "share", "pnpm"),
        os.path.join(home, ".bun", "bin"),
        os.path.join(home, ".volta", "bin"),
        os.path.join(home, ".yarn", "bin"),
        os.path.join(home, ".config", "yarn", "global", "node_modules", ".bin"),
        "/usr/local/bin",
        "/usr/bin",
        "/opt/homebrew/bin",
        "/home/linuxbrew/.linuxbrew/bin",
        os.path.join(home, ".local", "bin"),
        os.path.join(home, "bin"),
    ]

    for base in (
        os.path.join(home, ".nvm", "versions", "node"),
        os.path.join(home, "n", "versions", "node"),
        os.path.join(home, ".local", "share", "fnm", "node-versions"),
        os.path.join(home, ".asdf", "installs", "nodejs"),
    ):
        if os.path.isdir(base):
            for version in os.listdir(base):
                dirs.append(os.path.join(base, version, "bin"))
                dirs.append(os.path.join(base, version, "installation", "bin"))

    # On Windows try executable extensions FIRST (never the bare Unix shim).
    exts = [".cmd", ".exe", ".bat"] if IS_WINDOWS else [""]
    for directory in dirs:
        for ext in exts:
            candidate = os.path.join(directory, name + ext)
            if os.path.isfile(candidate) and (IS_WINDOWS or os.access(candidate, os.X_OK)):
                return candidate
    return None


# ── agents ───────────────────────────────────────────────────────────────────
def _run(cmd, **kw):
    """subprocess.run that runs node/pip .cmd shims correctly on Windows.

    On Windows the bare (extensionless) npm shim raises WinError 193, and
    ``shell=True`` with a list drops args - so on Windows we resolve the real
    path via ``which`` and run it through the shell as one properly quoted
    string. On Mac/Linux this is a transparent passthrough to subprocess.run.
    """
    if IS_WINDOWS and isinstance(cmd, (list, tuple)) and cmd:
        first = str(cmd[0])
        if not os.path.isabs(first):
            first = which(cmd[0]) or first
        cmd = subprocess.list2cmdline([first, *[str(a) for a in cmd[1:]]])
        kw["shell"] = True
    return subprocess.run(cmd, **kw)


def gateway_running(obj) -> bool | None:
    """Scan an OpenClaw status JSON for a running signal, tolerant of schema
    changes across versions. Returns True/False, or None if nothing recognizable."""
    truthy = {"running", "ok", "active", "up", "healthy", "online", "ready"}
    falsy = {"stopped", "down", "inactive", "dead", "offline", "error", "unavailable"}

    def scan(node, depth=0):
        if depth > 4:
            return None
        if isinstance(node, dict):
            for key, value in node.items():
                key_l = str(key).lower()
                if key_l in {"running", "isrunning", "alive", "healthy", "ready"} and isinstance(value, bool):
                    return value
                if key_l in {"status", "state", "runtime", "health"} and isinstance(value, str):
                    value_l = value.lower()
                    if value_l in truthy:
                        return True
                    if value_l in falsy:
                        return False
                found = scan(value, depth + 1)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = scan(item, depth + 1)
                if found is not None:
                    return found
        return None

    return scan(obj)


def _hermes_acp_ok(binary: str) -> bool:
    """True if `hermes acp --check` succeeds (ACP extra installed + usable)."""
    try:
        proc = _run([binary, "acp", "--check"],
                              capture_output=True, timeout=DETECT_TIMEOUT)
        return proc.returncode == 0
    except Exception as exc:
        log.debug("hermes acp --check failed: %s", exc)
        return False


_acp_install_attempted = False


def _install_hermes_acp() -> bool:
    """Install the ACP extra into the user's Hermes checkout (acp only, never
    Hermes itself). Returns True if the ACP extra is present afterwards.

    Attempted AT MOST ONCE per process: this runs a pip install with a 300s
    timeout, and detect_hermes() is on three hot paths (startup, every
    discover, every run_agent). Without this guard, a machine where the
    install fails - offline, wrong Python, no write permission - would block
    for up to 5 minutes on *every* voice request, repeatedly.
    """
    global _acp_install_attempted
    if _acp_install_attempted:
        return False
    _acp_install_attempted = True

    checkout = os.path.expanduser("~/.hermes/hermes-agent")
    if not os.path.isdir(checkout):
        return False
    cmd = None
    if which("uv"):
        cmd = ["uv", "pip", "install", "-e", ".[acp]"]
    else:
        py = which("python3") or which("python")
        if py:
            cmd = [py, "-m", "pip", "install", "-e", ".[acp]"]
    if not cmd:
        return False
    log.info("installing Hermes ACP extra (%s)", " ".join(cmd))
    try:
        proc = _run(cmd, cwd=checkout, capture_output=True, timeout=300)
    except Exception as exc:
        log.warning("Hermes ACP install failed: %s", exc)
        return False
    ok = _hermes_acp_ok(which("hermes") or "hermes")
    if not ok:
        # Don't discard the install's own output - it's the only clue to why
        # `.[acp]` didn't take (network failure, wrong Python, etc).
        out = (proc.stdout or b"").decode(errors="replace").strip()
        err = (proc.stderr or b"").decode(errors="replace").strip()
        log.warning("Hermes ACP install did not result in a working ACP (exit %s)", proc.returncode)
        if out:
            log.warning("  install stdout: %s", shorten(out))
        if err:
            log.warning("  install stderr: %s", shorten(err))
    return ok


def detect_hermes(allow_install: bool = False) -> tuple[str, str]:
    """Ready if Hermes is installed AND its ACP interface works. We drive
    Hermes over ACP, so ACP is required.

    ``allow_install`` gates the (slow, one-shot) attempt to install the ACP
    extra. Only worker startup passes True - detection also runs on every
    discover and every request, and a pip install must never happen inside a
    live voice request.
    """
    binary = which("hermes")
    if not binary:
        return ABSENT, ""
    if _hermes_acp_ok(binary):
        return READY, ""
    if allow_install and _install_hermes_acp():
        return READY, ""
    return NOT_READY, ("Hermes is installed but its ACP interface isn't available. "
                       "Install it with: cd ~/.hermes/hermes-agent && uv pip install -e '.[acp]'")


def detect_openclaw() -> tuple[str, str]:
    """Ready only if the OpenClaw gateway is up. Uses ``gateway status --json
    --no-probe`` so the check reflects the service and doesn't fail on unresolved
    auth (the auth-gated probe gives false negatives on fresh installs)."""
    binary = which("openclaw")
    if not binary:
        return ABSENT, ""
    hint = "OpenClaw is installed but its gateway isn't running. Run `openclaw gateway start`."
    try:
        proc = _run(
            [binary, "gateway", "status", "--json", "--no-probe"],
            capture_output=True, text=True, timeout=DETECT_TIMEOUT,
        )
    except Exception:
        return NOT_READY, hint

    running = None
    if proc.stdout:
        try:
            running = gateway_running(json.loads(proc.stdout))
        except ValueError:
            running = None
    if running is None:
        running = proc.returncode == 0
    return (READY, "") if running else (NOT_READY, hint)


_openclaw_agent_id: str | None = None


def openclaw_agent_id(binary: str) -> str:
    """Resolve OpenClaw's default agent id (cached), falling back to 'main'."""
    global _openclaw_agent_id
    if _openclaw_agent_id:
        return _openclaw_agent_id
    agent_id = "main"
    try:
        proc = _run(
            [binary, "agents", "list", "--json"],
            capture_output=True, text=True, timeout=DETECT_TIMEOUT,
        )
        if proc.returncode == 0 and proc.stdout:
            data = json.loads(proc.stdout)
            agents = data.get("agents") if isinstance(data, dict) else data
            if isinstance(agents, list) and agents:
                default = next(
                    (a for a in agents if isinstance(a, dict) and a.get("default")),
                    agents[0],
                )
                if isinstance(default, dict):
                    agent_id = default.get("id") or default.get("name") or "main"
                elif isinstance(default, str):
                    agent_id = default
    except Exception:
        pass
    _openclaw_agent_id = agent_id
    return agent_id


def parse_openclaw_reply(stdout: str) -> str | None:
    """Extract the reply from ``openclaw agent --json`` output, or None if the
    output isn't parseable JSON."""
    try:
        obj = json.loads(stdout)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    result = obj.get("result")
    if isinstance(result, dict):
        payloads = result.get("payloads")
        if isinstance(payloads, list):
            texts = [p.get("text") for p in payloads if isinstance(p, dict) and p.get("text")]
            if texts:
                return "\n".join(texts).strip()
        meta = result.get("meta")
        if isinstance(meta, dict):
            visible = meta.get("finalAssistantVisibleText")
            if isinstance(visible, str) and visible.strip():
                return visible.strip()
    return None


def run_openclaw(data: str, timeout: float) -> str:
    """Run one OpenClaw agent turn through the gateway and return the reply.

    ``--agent`` gives the turn a session target; ``--json`` gives clean output we
    parse. (This is the agent path, not ``message send``, which is channel messaging.)
    """
    binary = which("openclaw") or "openclaw"
    agent = openclaw_agent_id(binary)
    proc = _run(
        [binary, "agent", "--agent", agent, "--message", data, "--json"],
        capture_output=True, text=True, timeout=timeout,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()

    reply = parse_openclaw_reply(out)
    if reply is not None:
        return reply
    if "error" in err.lower() or "error" in out.lower():
        detail = (err or out).splitlines()[0] if (err or out) else "unknown error"
        return f"OpenClaw couldn't complete that: {detail}"
    return out or err or "(no output)"


AGENTS: dict[str, dict] = {
    "local-link": {"detect": None, "run": "shell"},
    "hermes": {"detect": detect_hermes, "run": run_hermes_acp},
    "openclaw": {"detect": detect_openclaw, "run": run_openclaw},
}


def agent_status(spec: dict) -> tuple[str, str]:
    """Return (state, hint) for an agent. detect=None -> READY; a callable is
    used as-is; a list is ``which`` + probe, where exit 0 is READY."""
    detect = spec["detect"]
    if detect is None:
        return READY, ""
    if callable(detect):
        try:
            return detect()
        except Exception:
            return ABSENT, ""
    binary = which(detect[0])
    if not binary:
        return ABSENT, ""
    try:
        proc = _run([binary, *detect[1:]], capture_output=True, timeout=DETECT_TIMEOUT)
        return (READY, "") if proc.returncode == 0 else (NOT_READY, f"{detect[0]} is installed but not ready.")
    except Exception:
        return NOT_READY, f"{detect[0]} is installed but not responding."


def run_backend(spec: dict, data: str, timeout: float) -> str:
    """Execute a request against an agent and return speakable text."""
    run = spec["run"]
    if callable(run):
        return run(data, timeout)
    if run == "shell":
        proc = subprocess.run(data, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode == 0:
            return out or "(no output)"
        return err or out or f"command failed (exit {proc.returncode})"
    binary = which(run[0]) or run[0]
    proc = _run([binary, *run[1:], data], capture_output=True, text=True, timeout=timeout)
    return (proc.stdout or proc.stderr).strip()


def discover_status() -> tuple[list[str], list[dict]]:
    """Detect every agent: (ready_ids, not_ready) where not_ready holds
    {"id", "hint"} for agents installed but unable to serve yet."""
    ready: list[str] = []
    not_ready: list[dict] = []
    for name, spec in AGENTS.items():
        state, hint = agent_status(spec)
        if state == READY:
            ready.append(name)
        elif state == NOT_READY:
            not_ready.append({"id": name, "hint": hint})
    return ready, not_ready


def discover_agents() -> list[str]:
    """Ready agent ids only."""
    ready, _ = discover_status()
    return ready


def run_agent(target: str, data: str, timeout: float) -> dict:
    """Route one request to ``target`` and return a response payload."""
    spec = AGENTS.get(target)
    if spec is None:
        return {"status": "error", "error": f"unknown agent: {target}"}
    state, hint = agent_status(spec)
    if state != READY:
        return {"status": "error", "error": hint or f"{target} is not available"}
    if target == "hermes":
        # ACP turns can involve several LLM calls plus tool execution (we've
        # seen 40s+ turns); don't let the generic 30s default cut them off.
        timeout = max(timeout, 120.0)
    try:
        return {"status": "ok", "data": run_backend(spec, data, timeout)}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"{target} timed out after {timeout:.0f}s"}
    except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
        return {"status": "error", "error": f"{target} timed out after {timeout:.0f}s"}
    except Exception as exc:
        return {"status": "error", "error": str(exc) or f"{type(exc).__name__} (no message)"}


# ── messages ─────────────────────────────────────────────────────────────────
def dumps(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=True)


def loads(text: str) -> dict:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {"type": "command", "data": str(obj)}
    except json.JSONDecodeError:
        return {"type": "command", "data": text}


def parse_protocol(inner: str) -> dict | None:
    """Return our protocol message if ``inner`` is one, else None (a plain string
    is a raw shell command)."""
    text = (inner or "").strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(obj, dict) and obj.get("type") in ("discover", "command", "ping"):
        return obj
    return None


async def handle_message(ws, msg: dict, default_timeout: float) -> None:
    """Dispatch one inbound frame and send the reply."""
    mtype = msg.get("type")

    if mtype == "command":
        data = msg.get("data")
        if isinstance(data, dict):
            data = data.get("cmd", "")
        inner = str(data or "")
        default_target = msg.get("target") or "local-link"
        proto = parse_protocol(inner)

        if proto is not None and proto.get("type") == "ping":
            log.debug("← ping ↔ pong")
            await ws.send(dumps({"type": "response", "data": {"pong": True}}))
            return

        if proto is not None and proto.get("type") == "discover":
            log.info("← discover")
            ready, not_ready = await asyncio.to_thread(discover_status)
            payload = {"os": os_name(), "agents": ready, "unavailable": not_ready}
            extra = f" | not ready: {', '.join(a['id'] for a in not_ready)}" if not_ready else ""
            log.info("→ os=%s agents: %s%s", payload["os"], ", ".join(ready) or "(none)", extra)
            await ws.send(dumps({"type": "response", "data": payload}))
            return

        if proto is not None and proto.get("type") == "command":
            target = proto.get("target") or default_target
            payload = proto.get("data")
            if isinstance(payload, dict):
                payload = payload.get("cmd", "")
            request = str(payload or "")
            timeout = float(proto.get("timeout") or default_timeout)
        else:
            target = default_target
            request = inner
            timeout = float(msg.get("timeout") or default_timeout)

        if not request:
            log.warning("← command target=%s (empty, ignored)", target)
            return

        log.info('← command target=%s data="%s"', target, shorten(request))
        result = await asyncio.to_thread(run_agent, target, request, timeout)
        result["target"] = target
        if result.get("status") == "ok":
            log.info('→ response target=%s status=ok data="%s"', target, shorten(result.get("data", "")))
        else:
            log.warning("→ response target=%s status=error error=%s", target, result.get("error"))
        await ws.send(dumps({"type": "response", "data": result}))
        return

    log.debug("← ignored message type=%s", mtype)



# ── connection ───────────────────────────────────────────────────────────────
def local_link_url(config: Config, client_id: str, role: str) -> str:
    """Build the authenticated Local Link WebSocket URL."""
    query = urlencode({"api_key": config.api_key, "client_id": client_id, "role": role})
    return f"{config.ws_base}/ws/local_link/?{query}"


async def serve(config: Config, client_id: str, role: str, timeout: float, once: bool) -> None:
    """Connect Local Link and handle messages, reconnecting with backoff on
    failure. Stops after one connection when ``once`` is set."""
    import websockets

    if not config.api_key:
        raise SystemExit("No API key. Run `openhome login` or set OPENHOME_API_KEY.")

    # Spawn and hold the Hermes ACP connection up front so requests are served
    # by a warm process. Best-effort: if Hermes/ACP isn't present the hermes
    # agent simply reports not-ready via detection; the worker still runs.
    if which("hermes"):
        state, _ = detect_hermes(allow_install=True)
        if state == READY:
            acp_start(timeout)

    url = local_link_url(config, client_id, role)
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(url, max_size=2**20, ping_interval=20) as ws:
                log.info("Local Link connected (device=%s, role=%s)", client_id, role)
                backoff = 1.0
                async for message in ws:
                    if isinstance(message, bytes):
                        continue
                    await handle_message(ws, loads(message), timeout)
        except (OSError, asyncio.TimeoutError) as exc:
            log.warning("Local Link disconnected: %s", exc)
        except Exception as exc:  # noqa: BLE001 — keep Local Link alive
            log.error("Local Link error: %s", exc)
        if once:
            return
        log.info("Local Link reconnecting in %.0fs…", backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30.0)


def _install_stop_signal_handler() -> None:
    """Make ``openhome local stop`` trigger the same graceful shutdown path as
    Ctrl-C, so ``finally: acp_stop()`` actually runs instead of the process
    being killed before any cleanup code executes.

    - POSIX (Mac/Linux): ``stop`` sends SIGTERM, for which Python has no
      default handler - without this, SIGTERM kills the process immediately
      (verified directly), leaking the held ``hermes acp`` subprocess.
    - Windows: ``os.kill(pid, SIGTERM)`` does not deliver a catchable signal
      at all - Python implements it as an immediate TerminateProcess call,
      which gives the target no chance to clean up regardless of handlers.
      The only Windows signal that is both catchable and can be aimed at one
      specific other process is CTRL_BREAK_EVENT, which needs the target in
      its own process group (``start`` sets this up) and an explicit
      SIGBREAK handler, since there is no default one. ``stop`` sends
      CTRL_BREAK_EVENT first, for exactly this reason.
    """
    def _handler(signum, frame):
        raise KeyboardInterrupt()

    try:
        if IS_WINDOWS:
            signal.signal(signal.SIGBREAK, _handler)
        else:
            signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError, AttributeError) as exc:
        log.debug("could not install stop-signal handler: %s", exc)


def run_worker(config: Config, client_id: str = "laptop", role: str = "agent",
               timeout: float = 30.0, once: bool = False) -> int:
    """Run Local Link in the foreground; also the process ``start`` launches."""
    setup_logging(foreground=sys.stderr.isatty())
    _install_stop_signal_handler()
    try:
        asyncio.run(serve(config, client_id, role, timeout, once))
    except KeyboardInterrupt:
        log.info("Local Link stopped")
    finally:
        acp_stop()
    return 0


# ── process control (start / stop / status / logs) ───────────────────────────
def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start(client_id: str = "laptop", role: str = "agent", timeout: float = 30.0) -> int:
    """Launch Local Link as a detached background process."""
    LOCAL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    pid = read_pid()
    if pid and is_alive(pid):
        print(f"Local Link is already running (PID {pid}). Stop it with `openhome local stop`.")
        return 1

    logfile = open(LOG_FILE, "a", encoding="utf-8")  # noqa: SIM115 — handed to the child
    popen_kwargs = dict(stdout=logfile, stderr=logfile, stdin=subprocess.DEVNULL)
    if IS_WINDOWS:
        # CREATE_NEW_PROCESS_GROUP: lets `stop` target this process alone
        # with CTRL_BREAK_EVENT for a graceful shutdown.
        # CREATE_NO_WINDOW: no console window popping up for a background worker.
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, "-m", "openhome.cli", "local", "run",
         "--client-id", client_id, "--role", role, "--timeout", str(timeout)],
        **popen_kwargs,
    )
    PID_FILE.write_text(str(proc.pid))
    print("Local Link started. View activity with `openhome local logs`.")
    return 0


def stop() -> int:
    """Stop the background Local Link, gracefully first, then force if needed."""
    pid = read_pid()
    if not pid or not is_alive(pid):
        print("Local Link is not running.")
        PID_FILE.unlink(missing_ok=True)
        return 0
    try:
        if IS_WINDOWS:
            # CTRL_BREAK_EVENT is the only Windows signal that is both
            # catchable and can target one specific process (needs that
            # process in its own group, which `start` sets up). Plain
            # SIGTERM on Windows is an immediate, uncatchable TerminateProcess
            # - no chance for the target to clean up - so it's reserved below
            # as the escalation if the graceful path doesn't respond in time.
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not is_alive(pid):
                break
            time.sleep(0.1)
        if is_alive(pid):
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    except OSError as exc:
        print(f"Could not stop Local Link (PID {pid}): {exc}")
        return 1
    PID_FILE.unlink(missing_ok=True)
    print("Local Link stopped.")
    return 0


def status() -> int:
    """Print whether Local Link is running."""
    pid = read_pid()
    if pid and is_alive(pid):
        print(f"Local Link is running (PID {pid}).")
    else:
        print("Local Link is not running.")
        PID_FILE.unlink(missing_ok=True)
    return 0


def logs(follow: bool = True, lines: int = 50) -> int:
    """Print recent Local Link logs, then live-tail (unless ``follow`` is False)."""
    if not LOG_FILE.exists():
        print("No logs yet. Start Local Link with `openhome local start`.")
        return 0

    with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
        tail = f.readlines()[-lines:]
    sys.stdout.write("".join(tail))
    sys.stdout.flush()
    if not follow:
        return 0

    try:
        f = open(LOG_FILE, encoding="utf-8", errors="replace")
        f.seek(0, os.SEEK_END)
        inode = os.fstat(f.fileno()).st_ino
        while True:
            line = f.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
                continue
            try:
                if os.stat(LOG_FILE).st_ino != inode:   # rotated -> reopen
                    f.close()
                    f = open(LOG_FILE, encoding="utf-8", errors="replace")
                    inode = os.fstat(f.fileno()).st_ino
                    continue
            except OSError:
                pass
            time.sleep(0.3)
    except KeyboardInterrupt:
        print()
    finally:
        try:
            f.close()
        except Exception:
            pass
    return 0