"""OpenHome Local Link — a persistent WebSocket worker on the user's machine.

It connects to the user's OpenHome agent, receives requests, runs each against a
local agent (raw shell, Hermes, or OpenClaw), and returns the reply.

Exposed through ``openhome local``:

    openhome local start     start Local Link in the background
    openhome local stop      stop it
    openhome local status    is it running?
    openhome local logs      stream requests and responses (Ctrl-C to stop)
    openhome local run       run in the foreground (debugging)

Message contract (over ``/ws/local_link/``), all JSON text frames. Requests
arrive from the SDK as {"type":"command","data":{"cmd": <string>}}; our protocol
is JSON-encoded inside that cmd string:

    inbound  cmd = '{"type":"discover"}'
             cmd = '{"type":"command","target":"<agent>","data":"<text>","timeout":<s>}'
             cmd = '<raw shell command>'        plain string -> local-link, legacy
             {"type":"ping"}

    outbound {"type":"response","data":{"os","agents","unavailable"}}
             {"type":"response","data":{"status":"ok","data":"<text>","target"}}
             {"type":"response","data":{"status":"error","error":"<why>","target"}}
             {"type":"pong"}

Detection and invocation go through each tool's own commands to stay
cross-platform. The local-link agent is a raw shell executor — first-class on
macOS/Linux, best-effort on Windows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from .config import CONFIG_DIR, Config

LOCAL_DIR = CONFIG_DIR / "local"
PID_FILE = LOCAL_DIR / "local.pid"
LOG_FILE = LOCAL_DIR / "local.log"

log = logging.getLogger("openhome.local")
MAX_LOG_CHARS = 400
DETECT_TIMEOUT = 5.0

# Agent readiness.
READY = "ready"          # installed and usable now
NOT_READY = "not_ready"  # installed but can't serve yet (needs an action)
ABSENT = "absent"        # not installed


# ── logging ──────────────────────────────────────────────────────────────────
def setup_logging(foreground: bool) -> None:
    """Attach a rotating file handler always, plus a screen handler in the
    foreground. Safe to call more than once."""
    if log.handlers:
        return
    log.setLevel(logging.DEBUG)
    log.propagate = False

    LOCAL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    log.addHandler(file_handler)

    if foreground:
        try:
            import coloredlogs
            coloredlogs.install(
                level="DEBUG", logger=log,
                fmt="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S",
            )
        except ImportError:
            screen = logging.StreamHandler()
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
    homebrew, ...), so we look beyond ``shutil.which``."""
    found = shutil.which(name)
    if found:
        return found

    home = os.path.expanduser("~")
    dirs = [
        os.path.join(home, ".npm-global", "bin"),
        os.path.join(home, ".npm", "bin"),
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

    for directory in dirs:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


# ── agents ───────────────────────────────────────────────────────────────────
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


def detect_hermes() -> tuple[str, str]:
    """Ready if `hermes dump` (a fast status probe) succeeds."""
    binary = which("hermes")
    if not binary:
        return ABSENT, ""
    try:
        proc = subprocess.run([binary, "dump"], capture_output=True, timeout=DETECT_TIMEOUT)
    except Exception:
        return NOT_READY, "Hermes is installed but not responding. Try `hermes doctor`."
    if proc.returncode == 0:
        return READY, ""
    return NOT_READY, "Hermes is installed but not configured. Run `hermes setup`."


def detect_openclaw() -> tuple[str, str]:
    """Ready only if the OpenClaw gateway is up. Uses ``gateway status --json
    --no-probe`` so the check reflects the service and doesn't fail on unresolved
    auth (the auth-gated probe gives false negatives on fresh installs)."""
    binary = which("openclaw")
    if not binary:
        return ABSENT, ""
    hint = "OpenClaw is installed but its gateway isn't running. Run `openclaw gateway start`."
    try:
        proc = subprocess.run(
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
        proc = subprocess.run(
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
    proc = subprocess.run(
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
    "hermes": {"detect": detect_hermes, "run": ["hermes", "-z"]},
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
        proc = subprocess.run([binary, *detect[1:]], capture_output=True, timeout=DETECT_TIMEOUT)
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
    proc = subprocess.run([binary, *run[1:], data], capture_output=True, text=True, timeout=timeout)
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
    try:
        return {"status": "ok", "data": run_backend(spec, data, timeout)}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"{target} timed out"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


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


def run_worker(config: Config, client_id: str = "laptop", role: str = "agent",
               timeout: float = 30.0, once: bool = False) -> int:
    """Run Local Link in the foreground; also the process ``start`` launches."""
    setup_logging(foreground=sys.stderr.isatty())
    try:
        asyncio.run(serve(config, client_id, role, timeout, once))
    except KeyboardInterrupt:
        log.info("Local Link stopped (keyboard interrupt)")
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
    proc = subprocess.Popen(
        [sys.executable, "-m", "openhome.cli", "local", "run",
         "--client-id", client_id, "--role", role, "--timeout", str(timeout)],
        stdout=logfile, stderr=logfile, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    print("Local Link started. View activity with `openhome local logs`.")
    return 0


def stop() -> int:
    """Stop the background Local Link (SIGTERM, then SIGKILL if needed)."""
    pid = read_pid()
    if not pid or not is_alive(pid):
        print("Local Link is not running.")
        PID_FILE.unlink(missing_ok=True)
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not is_alive(pid):
                break
            time.sleep(0.1)
        if is_alive(pid):
            os.kill(pid, signal.SIGKILL)
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