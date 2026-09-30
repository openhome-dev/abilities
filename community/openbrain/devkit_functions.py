#!/usr/bin/env python3
"""Public MIT DevKit shim: transcripts in, one JSON result out.

Ask the owner hub through its socket/CLI, then the proprietary astral-kernel package
in requirements.txt. Its contract is astral_kernel.answer(text, now=None) -> str | None.
An unhandled question lets the OpenHome agent take the turn; installation failures
are explained. Telemetry/MQTT stay here, engine rules stay in the package/private hub.

    python3 devkit_functions.py respond what is twenty percent of eighty
    python3 devkit_functions.py health
"""
import json
import os
import shutil
import subprocess
import sys
import time

# Native sudo calls have HOME=/root. Explicit paths keep hub reads/writes with its owner.
DEVICE_HOME = os.environ.get("ASTRAL_HOME") or "/home/openhome"
HUB = os.path.join(DEVICE_HOME, "astral-voice/hub-v2")
HUB_USER = "openhome"
HUB_PYTHON = os.path.join(DEVICE_HOME, "astral-voice/kws-venv/bin/python3")
BRIDGE = os.path.join(HUB, "ability_bridge.py")
CONTEXT = "/tmp/astral_ctx.json"


# ── the one line of JSON this file exists to print ───────────────────────────────────
def _emit_success(spoken, data=None):
    print(json.dumps({"success": True, "spoken_response": spoken,
                      "data": data or {}, "error": None}))


def _emit_error(code, message):
    print(json.dumps({"success": False, "spoken_response": "", "data": {},
                      "error": {"code": code, "message": message}}))


def _emit_none():
    """No exact answer. An empty spoken_response tells main.py to defer to the agent."""
    print(json.dumps({"success": True, "spoken_response": "", "data": {}, "error": None}))


# ── where answers come from ──────────────────────────────────────────────────────────
def kernel():
    """The Astral engine, if the package is installed here."""
    try:
        import astral_kernel
    except ImportError:
        return None
    return astral_kernel


def resident_hub(args, timeout):
    """Use the owner service when present. None means nothing was handed to it."""
    # An explicitly isolated audit must never reach production state through IPC.
    if os.environ.get("ASTRAL_STATE"):
        return None
    where = os.path.join(DEVICE_HOME, "astral-voice/state/ability.sock")
    if not os.path.exists(where):
        return None
    import errno
    import math
    import pwd
    import socket
    import stat
    try:
        info = os.lstat(where)
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != pwd.getpwnam(HUB_USER).pw_uid
                or info.st_mode & 0o077):
            return None
    except (OSError, KeyError):
        return None
    if not math.isfinite(timeout) or timeout <= 0:
        return {"ok": True, "kind": "timeout"}
    deadline = time.clock_gettime(time.CLOCK_MONOTONIC) + timeout
    payload = (json.dumps({"args": list(args), "deadline": deadline}) + "\n").encode()
    if len(payload) > 65536:
        return {"ok": False, "error": "bridge request too large"}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(timeout)
        try:
            channel.connect(where)
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ECONNREFUSED):
                return None
            return {"ok": False, "error": "cannot connect to owner bridge"}
        if hasattr(socket, "SO_PEERCRED"):
            import struct
            credentials = channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            if struct.unpack("3i", credentials)[1] != info.st_uid:
                return None
        try:
            channel.sendall(payload)
            line = bytearray()
            while not line.endswith(b"\n") and len(line) <= 1024 * 1024:
                remaining = deadline - time.clock_gettime(time.CLOCK_MONOTONIC)
                if remaining <= 0:
                    return {"ok": True, "kind": "timeout"}
                channel.settimeout(remaining)
                chunk = channel.recv(min(65536, 1024 * 1024 + 1 - len(line)))
                if not chunk:
                    break
                line.extend(chunk)
            if len(line) > 1024 * 1024 or not line.endswith(b"\n"):
                if time.clock_gettime(time.CLOCK_MONOTONIC) >= deadline:
                    return {"ok": True, "kind": "timeout"}
                return {"ok": False, "error": "incomplete owner bridge response"}
            result = json.loads(line)
            if not isinstance(result, dict):
                raise ValueError("bridge response is not an object")
            return result
        except socket.timeout:
            return {"ok": True, "kind": "timeout"}
        except (OSError, ValueError):
            # The request may have performed a state change. Never rerun it via
            # the CLI just because its reply was lost or malformed.
            return {"ok": False, "error": "owner bridge response failed"}


def hub(*args, timeout=10, deadline=None):
    """Return the owner's result within the caller's remaining budget, or None if absent."""
    if deadline is not None:
        timeout = min(timeout, max(0, deadline - time.monotonic()))
    if timeout <= 0:
        return {"ok": True, "kind": "timeout"}
    if not os.path.exists(BRIDGE):
        return None
    python = HUB_PYTHON if os.path.exists(HUB_PYTHON) else "python3"
    invoke = [python, BRIDGE] + [str(a) for a in args]
    # Explicit audit state must survive the root-to-owner boundary. Normal platform
    # calls do not set it, so the hub continues to use the owner's regular state.
    if os.environ.get("ASTRAL_STATE"):
        invoke = ["env", "ASTRAL_STATE=" + os.environ["ASTRAL_STATE"]] + invoke
    cmd = ["sudo", "-n", "-u", HUB_USER, "-H"] + invoke if os.geteuid() == 0 else invoke
    try:
        out = resident_hub([str(a) for a in args], timeout)
        if out is None:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = json.loads((r.stdout or "").strip().splitlines()[-1])
        if isinstance(out, dict) and out.get("ok"):
            return out
        # A hub that ANSWERED with a failure is not a hub that is absent, and the two
        # must not be reported as the same thing: absent means "try the kernel", failed
        # means "this device has a hub and it is broken".
        return {"ok": True, "kind": "broken", "why": (out or {}).get("error")
                if isinstance(out, dict) else None}
    except subprocess.TimeoutExpired:
        # Slow is not the same as impossible, and the caller must be able to tell them
        # apart: a cold mathematics kernel is tens of seconds in a fresh process.
        return {"ok": True, "kind": "timeout"}
    except Exception:                        # noqa: BLE001 — the caller is a voice
        return None


def why_nothing_works():
    """Explain a missing engine; silence would disguise it as an ordinary decline."""
    return ("The Astral engine is not installed on this device. "
            "Install the astral-kernel package, or the local hub, and ask me again.")


# ── the functions the platform calls ─────────────────────────────────────────────────
def respond(*words):
    """A transcript in, an exact answer out — or nothing, and the agent takes the turn."""
    q = " ".join(str(w) for w in words).strip()
    if not q:
        _emit_none()
        return

    # 1. the hub: the same engine plus everything on the card
    deadline = time.monotonic() + 12  # Native node stops at 15s; reserve reply time.
    out = hub("answer", "--agent", q, deadline=deadline)
    if out and out.get("kind") == "timeout":
        out = hub("offer", "--agent", q, timeout=8, deadline=deadline)
    if out and out.get("kind") == "timeout":
        _emit_success("The local engine did not reply in time.", {"query": q, "from": "timeout"})
        return
    if out and out.get("kind") == "answer" and out.get("say"):
        _emit_success(out["say"], {"query": q, "from": "hub", "class": out.get("class")})
        return
    if out and out.get("kind") == "ask" and out.get("say"):
        _emit_success(out["say"], {"query": q, "from": "hub", "offer": True,
                                   "routes": out.get("routes") or [],
                                   "class": out.get("class")})
        return

    # 2. the kernel package
    engine = kernel()
    if engine is not None:
        said = engine.answer(q)
        if said:
            _emit_success(said, {"query": q, "from": "kernel"})
            return
        commanded = _device_command(q)
        if commanded:
            _emit_success(commanded, {"query": q, "from": "kernel"})
            return
        # A failed hub is still a failure when the fallback has no answer.

    # 3. report a broken or missing engine; otherwise the agent takes the turn.
    if out and out.get("kind") == "broken":
        _emit_success("The local engine is installed but it failed to answer. "
                      "Ask me again, or check the hub.", {"query": q, "from": "broken"})
        return
    if out is None and engine is None:
        _emit_success(why_nothing_works(), {"query": q, "from": "nothing"})
        return
    _emit_none()


# The daemon's budget, and why it is a fraction of respond()'s. Measured here: a native
# callback's median round trip is 181-203 ms and a tier-0 answer computes in under 1.4 ms,
# so a genuinely instant answer is IPC-bound at about a fifth of a second.
NOW_BUDGET_SECONDS = 1.0


def respond_now(*words):
    """The background daemon's path: an answer only while it is still faster than the cloud.

    Same engine as respond() on a one-second budget, and silence for everything else. The
    daemon speaks by interrupting the agent mid-sentence, which is only justified while the
    local answer is cheaper AND faster; once it is not faster, deferring to the cloud is the
    correct ranked outcome. So a timeout says nothing here. respond() answers a slow engine
    with "the local engine did not reply in time", which is right for somebody waiting on it
    and exactly wrong to sever a sentence to announce.
    """
    q = " ".join(str(w) for w in words).strip()
    deadline = time.monotonic() + NOW_BUDGET_SECONDS
    out = hub("answer", "--agent", q, timeout=NOW_BUDGET_SECONDS, deadline=deadline) if q else None
    if out and out.get("kind") == "answer" and out.get("say"):
        _emit_success(out["say"], {"query": q, "from": "hub", "class": out.get("class")})
        return
    # The compiled package is in-process and costs no IPC, so it can still come in under
    # the budget. Past the deadline nothing is instant any more, whatever it would say.
    engine = kernel() if q and time.monotonic() < deadline else None
    said = engine.answer(q) if engine is not None else None
    if said:
        _emit_success(said, {"query": q, "from": "kernel"})
        return
    _emit_none()                             # not ours, not instant, or not working


def _device_command(q):
    """Device control: the engine understands it, this file publishes it.

    The split is deliberate. Understanding "dim the bedroom light to thirty" is engine
    work; putting a byte on an MQTT topic is device work, and device work belongs in the
    file that runs on the device.
    """
    engine = kernel()
    if engine is None or not hasattr(engine, "command"):
        return None
    cmd = engine.command(q, _last_device())
    if not cmd or not cmd.get("topic"):
        return None
    _remember_device(cmd.get("device"))
    ok = _publish(cmd["topic"], cmd.get("payload", ""))
    if ok is None:
        return "MQTT isn't set up on this device yet."
    return cmd.get("spoken") if ok else "I couldn't reach the {}.".format(cmd.get("device"))


def _last_device():
    try:
        with open(CONTEXT) as f:
            return json.load(f).get("device")
    except Exception:                        # noqa: BLE001
        return None


def _remember_device(device):
    if not device:
        return
    try:
        with open(CONTEXT, "w") as f:
            json.dump({"device": device}, f)
    except OSError:
        pass


def _publish(topic, payload):
    """True sent, False failed, None no broker tools installed."""
    try:
        r = subprocess.run(["mosquitto_pub", "-t", topic, "-m", str(payload)],
                           capture_output=True, timeout=4)
        return r.returncode == 0
    except FileNotFoundError:
        return None
    except Exception:                        # noqa: BLE001
        return False


def device_control(action="", device="", *_):
    said = _device_command("turn {} the {}".format(action, device)) if device else None
    if said:
        _emit_success(said, {"action": action, "device": device})
    else:
        _emit_error("device_failed", "Could not command the device.")


def due_alerts(*_):
    """Timers and reminders that have come due, for the background daemon to speak."""
    out = hub("alerts")
    if out is None:
        _emit_success("", {"count": 0, "hub": False})
        return
    _emit_success(out.get("say") or "", {"count": out.get("count", 0), "hub": True})


def heard(*words):
    """Keep a turn the platform transcribed. Records for the corpus; never speaks."""
    text = " ".join(str(w) for w in words).strip()
    if not text:
        _emit_none()
        return
    out = hub("heard", text, timeout=3)
    _emit_success("", {"kept": bool(out and out.get("kept")), "hub": out is not None})


def route_answer(route="", *words):
    """Use the route the user chose; report failures explicitly.

    cloud:openhome declines locally so the current agent can take the turn.
    Other named routes are handled by the owner's hub configuration.
    """
    q = " ".join(str(w) for w in words).strip()
    if not route or not q:
        _emit_error("no_route", "A route and a question are both required.")
        return
    if route == "cloud:openhome" or route == "cloud":
        # The agent is already on this turn: choosing it means this ability stays quiet
        # and lets it answer. Nothing is sent anywhere by this file.
        _emit_none()
        return
    out = hub("route", route, q, timeout=12)
    if out is None:
        _emit_error("no_hub", "This device has no local hub to route through.")
        return
    if out.get("kind") == "answer" and out.get("say"):
        _emit_success(out["say"], {"query": q, "route": route})
        return
    where = "the Mac" if route == "mac" else "your {}".format(route)
    _emit_success("I couldn't reach {} right now.".format(where),
                  {"query": q, "route": route, "unreachable": True})


# ── this device, about itself ────────────────────────────────────────────────────────
def get_temperature(*_):
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            c = int(f.read().strip()) / 1000
        _emit_success("The DevKit is at {:.0f} degrees Celsius.".format(c),
                      {"celsius": round(c, 1)})
    except Exception as e:                   # noqa: BLE001
        _emit_error("temp_unavailable", str(e))


def get_uptime(*_):
    try:
        with open("/proc/uptime") as f:
            s = float(f.read().split()[0])
        h, m = int(s // 3600), int((s % 3600) // 60)
        _emit_success("Up {} hours and {} minutes.".format(h, m) if h
                      else "Up {} minutes.".format(m), {"seconds": int(s)})
    except Exception as e:                   # noqa: BLE001
        _emit_error("uptime_unavailable", str(e))


def get_disk(*_):
    try:
        total, used, free = shutil.disk_usage("/")
        _emit_success("Disk is {} percent used, with {} gigabytes free.".format(
            round(used / total * 100), free // 10**9),
            {"used_percent": round(used / total * 100), "free_gb": free // 10**9})
    except Exception as e:                   # noqa: BLE001
        _emit_error("disk_unavailable", str(e))


def get_memory(*_):
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("MemTotal", "MemAvailable"):
                    info[k] = int(v.split()[0])
        used = round((1 - info["MemAvailable"] / info["MemTotal"]) * 100)
        _emit_success("Memory is {} percent used.".format(used), {"used_percent": used})
    except Exception as e:                   # noqa: BLE001
        _emit_error("memory_unavailable", str(e))


def health(*_):
    """What this ability can reach, for anybody wondering why it is quiet."""
    engine = kernel()
    have_hub = os.path.exists(BRIDGE)
    parts = ["kernel " + engine.__version__ if engine else "no kernel package",
             "local hub installed" if have_hub else "no local hub"]
    _emit_success("Astral: " + ", ".join(parts) + ".",
                  {"kernel": bool(engine), "hub": have_hub,
                   "version": engine.__version__ if engine else None})


FUNCTION_REGISTRY = {
    "respond": respond,
    "device_control": device_control,
    "respond_now": respond_now,
    "due_alerts": due_alerts,
    "heard": heard,
    "route_answer": route_answer,
    "get_temperature": get_temperature,
    "get_uptime": get_uptime,
    "get_disk": get_disk,
    "get_memory": get_memory,
    "health": health,
}


def main():
    if len(sys.argv) < 2:
        _emit_error("no_function", "No function name given.")
        return
    name, args = sys.argv[1], sys.argv[2:]
    func = FUNCTION_REGISTRY.get(name)
    if func is None:
        respond(name, *args)                 # anything unrecognised is a question
        return
    try:
        func(*args)
    except TypeError:
        respond(*args)
    except Exception as e:                   # noqa: BLE001 — never a traceback into a voice
        _emit_error("unexpected", str(e))


if __name__ == "__main__":
    main()
