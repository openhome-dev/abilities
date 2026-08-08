import asyncio
import errno
import json
import logging
import os
import signal
import socket as sock_mod
import subprocess
import sys
import time
from pathlib import Path

# Quieten chatty BLE logging in production.
logging.getLogger("bleak").setLevel(logging.WARNING)
logging.getLogger("bleak.backends.bluezdbus").setLevel(logging.WARNING)
logging.getLogger("HueBLE").setLevel(logging.WARNING)

try:
    from devkit_utils.devkit_logging import web_logger as log
except ImportError:
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(__name__)

# HueBLE is imported lazily inside the daemon so the short-lived client side
# doesn't pay the bleak import cost on every invocation.

# ---- Paths and tunables --------------------------------------------------
SOCKET_PATH            = "/tmp/hue_ble.sock"
PID_PATH               = "/tmp/hue_ble.pid"
DAEMON_LOG_PATH        = "/tmp/hue_ble.log"
STATUS_PATH            = "/tmp/hue_ble_status.json"
KNOWN_DEVICE_PATH      = Path(os.environ.get(
    "HUE_BLE_DEVICE_PATH",
    str(Path.home() / ".cache" / "openhome" / "hue_ble_device.json"),
))
DAEMON_READY_TIMEOUT_S = 60      # total daemon ready timeout (kept for hue_verify)
CONNECT_POLL_S         = 5       # how long each hue_connect call waits before returning "still_connecting"
CLIENT_RECV_TIMEOUT_S  = 20      # per-call socket timeout
KEEPALIVE_INTERVAL_S   = 45      # daemon health ping interval
DISCOVER_TIMEOUT_S     = 8
CONNECT_TIMEOUT_S      = 20


# ---- Daemon status file (written by daemon, read by client) --------------
def _write_status(phase: str, **kwargs) -> None:
    try:
        payload = {"phase": phase}
        payload.update(kwargs)
        Path(STATUS_PATH).write_text(json.dumps(payload))
    except OSError:
        pass


def _read_status() -> dict:
    try:
        return json.loads(Path(STATUS_PATH).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


# ---- OpenHome-style structured output ------------------------------------
def _emit_success(metric: str, spoken: str, data: dict = None) -> None:
    payload = {"success": True, "metric": metric, "spoken_response": spoken,
               "data": data or {}, "error": None}
    serialized = json.dumps(payload)
    log.info("stdout payload: %s", serialized)
    print(serialized)


def _emit_error(metric: str, code: str, message: str, spoken: str) -> None:
    log.error("%s failed [%s]: %s", metric, code, message)
    payload = {"success": False, "metric": metric, "spoken_response": spoken,
               "data": {}, "error": {"code": code, "message": message}}
    serialized = json.dumps(payload)
    log.info("stdout payload: %s", serialized)
    print(serialized)


def _spoken_for_error(code: str, default: str) -> str:
    if code == "no_bulb_found":
        return "I couldn't find a Hue bulb in range."
    if code == "not_paired":
        return ("The bulb refused the connection because it isn't paired yet. "
                "Put it in pairing mode using the Hue app, then try again.")
    if code == "no_daemon":
        return "The bulb isn't connected. Please trigger the ability again."
    if code == "timeout":
        return "The bulb didn't respond in time."
    return default


# CLIENT side (short-lived, called by OpenHome per request)
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        return e.errno == errno.EPERM  # exists but we can't signal


def _daemon_pid():
    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
        return pid if _pid_alive(pid) else None
    except (FileNotFoundError, ValueError, PermissionError):
        return None


def _daemon_socket_ready() -> bool:
    """Quick connect-attempt to see if the daemon is accepting commands."""
    if not Path(SOCKET_PATH).exists():
        return False
    try:
        s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(SOCKET_PATH)
        s.close()
        return True
    except (OSError, sock_mod.timeout):
        return False


def _send_command(payload: dict, recv_timeout: float = CLIENT_RECV_TIMEOUT_S) -> dict:
    """Send one JSON line, read one JSON line back. Closes socket either way."""
    s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
    s.settimeout(recv_timeout)
    try:
        s.connect(SOCKET_PATH)
        s.sendall((json.dumps(payload) + "\n").encode())
        # Read until newline.
        buf = bytearray()
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\n" in buf:
                break
        if not buf:
            return {"ok": False, "error": {"code": "no_response", "message": "daemon closed socket"}}
        line = buf.split(b"\n", 1)[0]
        try:
            return json.loads(line.decode())
        except json.JSONDecodeError as e:
            return {"ok": False, "error": {"code": "bad_response", "message": str(e)}}
    except FileNotFoundError:
        return {"ok": False, "error": {"code": "no_daemon", "message": "socket missing"}}
    except ConnectionRefusedError:
        return {"ok": False, "error": {"code": "no_daemon", "message": "connection refused"}}
    except sock_mod.timeout:
        return {"ok": False, "error": {"code": "timeout", "message": "no response in time"}}
    except Exception as e:
        return {"ok": False, "error": {"code": "socket_error", "message": str(e)}}
    finally:
        try:
            s.close()
        except Exception:
            pass


def _spawn_daemon() -> None:
    """Spawn the background daemon process detached from us."""
    # Clean any stale leftovers (only if no live daemon is using them).
    if _daemon_pid() is None:
        for path in (SOCKET_PATH, PID_PATH):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                log.warning("could not remove stale %s: %s", path, e)

    log_fp = open(DAEMON_LOG_PATH, "a")
    log_fp.write(f"\n---- daemon spawn at {time.strftime('%Y-%m-%d %H:%M:%S')} ----\n")
    log_fp.flush()

    subprocess.Popen(
        [sys.executable, os.path.realpath(__file__), "_daemon"],
        stdin=subprocess.DEVNULL,
        stdout=log_fp,
        stderr=log_fp,
        start_new_session=True,  # detach from our process group
        close_fds=True,
    )


def _wait_for_daemon_ready(timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _daemon_socket_ready():
            # Confirm with a ping (daemon may have only just opened the socket).
            resp = _send_command({"cmd": "ping"}, recv_timeout=3.0)
            if resp.get("ok"):
                return True
        time.sleep(0.5)
    return False


def _known_device_address() -> str | None:
    env_address = os.environ.get("HUE_BLE_ADDRESS", "").strip()
    if env_address:
        return env_address

    try:
        payload = json.loads(KNOWN_DEVICE_PATH.read_text())
    except (FileNotFoundError, PermissionError, json.JSONDecodeError, OSError):
        return None

    address = str(payload.get("address") or "").strip()
    return address or None


async def _find_known_device(BleakScanner):
    address = _known_device_address()
    if not address:
        return None

    log.info("daemon: looking for remembered Hue bulb at %s", address)
    try:
        device = await BleakScanner.find_device_by_address(
            address,
            timeout=DISCOVER_TIMEOUT_S,
        )
    except Exception as e:
        log.warning("daemon: remembered Hue lookup failed: %s", e)
        return None

    if device is None:
        log.warning("daemon: remembered Hue bulb not found; falling back to discovery")
        return None

    return device


def _save_known_device(device) -> None:
    try:
        KNOWN_DEVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "address": device.address,
            "name": device.name,
            "saved_at": int(time.time()),
        }
        KNOWN_DEVICE_PATH.write_text(json.dumps(payload, indent=2))
    except OSError as e:
        log.warning("daemon: could not save Hue bulb address: %s", e)


# ==========================================================================
# DAEMON side (long-lived, started by _spawn_daemon)
# ==========================================================================
async def _daemon_main() -> int:
    """The daemon process entry point."""
    try:
        from HueBLE import HueBleLight, discover_lights  # daemon-only deps
        from bleak import BleakScanner
    except ImportError:
        log.info("daemon: HueBLE not found — installing via pip")
        subprocess.run(
            ["sudo", "python3", "-m", "pip", "install", "hueble", "--break-system-packages"],
            check=True,
        )
        from HueBLE import HueBleLight, discover_lights
        from bleak import BleakScanner

    try:
        Path(PID_PATH).write_text(str(os.getpid()))
    except OSError as e:
        log.error("daemon could not write PID file: %s", e)
        return 1

    log.info("daemon: starting (pid=%d)", os.getpid())

    # ---- BLE: use remembered address, then discovery fallback -------------
    _write_status("scanning")
    device = await _find_known_device(BleakScanner)
    if device is None:
        log.info("daemon: scanning for Hue bulbs (timeout ~%ds)", DISCOVER_TIMEOUT_S)
        try:
            lights = await asyncio.wait_for(discover_lights(),
                                            timeout=DISCOVER_TIMEOUT_S + 2)
        except asyncio.TimeoutError:
            log.error("daemon: discovery timed out")
            _cleanup_daemon_files()
            return 2

        if not lights:
            log.error("daemon: no Hue bulbs found in scan")
            _cleanup_daemon_files()
            return 3

        device = lights[0]

    _write_status("connecting", address=device.address)
    log.info("daemon: connecting to %s", device.address)
    light = HueBleLight(device)

    try:
        await asyncio.wait_for(light.connect(), timeout=CONNECT_TIMEOUT_S)
    except Exception as e:
        log.error("daemon: connect failed: %s", e)
        _cleanup_daemon_files()
        return 4

    if not light.connected:
        log.error("daemon: connect returned but light not connected")
        _cleanup_daemon_files()
        return 5

    _write_status("connected", address=device.address)
    log.info("daemon: BLE connected to %s", device.address)
    _save_known_device(device)

    # Poll once so HueBLE populates supports_*/model/firmware/min-max mireds.
    try:
        await asyncio.wait_for(light.poll_state(), timeout=12)
        log.info("daemon: poll_state complete; model=%s firmware=%s",
                 light.model, light.firmware)
    except Exception as e:
        log.warning("daemon: initial poll_state failed (continuing): %s", e)

    capabilities = {
        "address":          light.address,
        "name":             light.name,
        "name_in_app":      light.name_in_app,
        "manufacturer":     light.manufacturer,
        "model":            light.model,
        "firmware":         light.firmware,
        "supports_on_off":      bool(light.supports_on_off),
        "supports_brightness":  bool(light.supports_brightness),
        "supports_colour_temp": bool(light.supports_colour_temp),
        "supports_colour_xy":   bool(light.supports_colour_xy),
        "supports_effects":     bool(light.supports_effects),
        "minimum_mireds":   light.minimum_mireds,
        "maximum_mireds":   light.maximum_mireds,
    }

    # ---- Shared state ---------------------------------------------------
    ble_lock = asyncio.Lock()
    shutdown_event = asyncio.Event()
    state = {"light": light, "address": device.address, "capabilities": capabilities}

    # ---- Signal handlers ------------------------------------------------
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            pass

    # ---- Unix socket server ---------------------------------------------
    server = await asyncio.start_unix_server(
        lambda r, w: _handle_client(r, w, state, ble_lock, shutdown_event),
        path=SOCKET_PATH,
    )
    os.chmod(SOCKET_PATH, 0o600)
    log.info("daemon: listening on %s", SOCKET_PATH)

    # ---- Keep-alive task ------------------------------------------------
    keepalive_task = asyncio.create_task(
        _keepalive_loop(state, ble_lock, shutdown_event)
    )

    # ---- Wait for shutdown ----------------------------------------------
    await shutdown_event.wait()
    log.info("daemon: shutdown signal received")

    # ---- Cleanup --------------------------------------------------------
    server.close()
    try:
        await asyncio.wait_for(server.wait_closed(), timeout=3)
    except asyncio.TimeoutError:
        pass

    keepalive_task.cancel()
    try:
        await keepalive_task
    except (asyncio.CancelledError, Exception):
        pass

    try:
        await asyncio.wait_for(light.disconnect(), timeout=5)
    except Exception as e:
        log.warning("daemon: disconnect error during shutdown: %s", e)

    _cleanup_daemon_files()
    log.info("daemon: exited cleanly")
    return 0


def _cleanup_daemon_files() -> None:
    for path in (SOCKET_PATH, PID_PATH, STATUS_PATH):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("could not remove %s: %s", path, e)


async def _keepalive_loop(state: dict, ble_lock: asyncio.Lock,
                          shutdown_event: asyncio.Event) -> None:
    """Periodically record daemon health without competing with user commands."""
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=KEEPALIVE_INTERVAL_S)
            return  # shutdown
        except asyncio.TimeoutError:
            pass

        light = state["light"]
        state["last_keepalive_at"] = time.time()
        state["last_ble_connected"] = bool(light.connected)
        log.debug("daemon: keepalive ping ok (ble_connected=%s)", light.connected)


def _error_code_for_exception(exc: Exception) -> str:
    msg = str(exc)
    if "Insufficient Authentication" in msg or "Authentication" in msg:
        return "not_paired"
    return "ble_error"


async def _handle_client(reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter,
                         state: dict,
                         ble_lock: asyncio.Lock,
                         shutdown_event: asyncio.Event) -> None:
    """Handle one client connection: read one JSON line, write one JSON line."""
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=5)
        if not raw:
            return
        try:
            req = json.loads(raw.decode().strip())
        except json.JSONDecodeError as e:
            await _write_response(writer, {"ok": False,
                                           "error": {"code": "bad_request", "message": str(e)}})
            return

        cmd = req.get("cmd", "")
        light = state["light"]

        if cmd == "ping":
            await _write_response(writer, {"ok": True, "data": {
                "address": state["address"],
                "ble_connected": bool(state["light"].connected),
            }})
            return

        if cmd == "capabilities":
            await _write_response(writer, {"ok": True, "data": state["capabilities"]})
            return

        if cmd == "shutdown":
            await _write_response(writer, {"ok": True, "data": {"shutting_down": True}})
            shutdown_event.set()
            return

        caps = state["capabilities"]

        async with ble_lock:
            try:
                if cmd == "on":
                    if not caps.get("supports_on_off"):
                        resp = {"ok": False, "error": {"code": "unsupported", "message": "bulb does not support on/off"}}
                    else:
                        await light.set_power(True)
                        resp = {"ok": True, "data": {"power": True}}
                elif cmd == "off":
                    if not caps.get("supports_on_off"):
                        resp = {"ok": False, "error": {"code": "unsupported", "message": "bulb does not support on/off"}}
                    else:
                        await light.set_power(False)
                        resp = {"ok": True, "data": {"power": False}}
                elif cmd == "brightness":
                    if not caps.get("supports_brightness"):
                        resp = {"ok": False, "error": {"code": "unsupported", "message": "bulb does not support brightness"}}
                    else:
                        val = max(1, min(254, int(req.get("value", 128))))
                        await light.set_brightness(val)
                        resp = {"ok": True, "data": {"brightness": val}}
                elif cmd == "temp":
                    if not caps.get("supports_colour_temp"):
                        resp = {"ok": False, "error": {"code": "unsupported", "message": "bulb does not support colour temperature"}}
                    else:
                        lo = caps.get("minimum_mireds") or 153
                        hi = caps.get("maximum_mireds") or 500
                        val = max(lo, min(hi, int(req.get("value", 300))))
                        await light.set_colour_temp(val)
                        resp = {"ok": True, "data": {"colour_temp": val, "range": [lo, hi]}}
                elif cmd == "color":
                    if not caps.get("supports_colour_xy"):
                        resp = {"ok": False, "error": {"code": "unsupported", "message": "bulb does not support colour"}}
                    else:
                        x = max(0.0, min(1.0, float(req.get("x", 0.0))))
                        y = max(0.0, min(1.0, float(req.get("y", 0.0))))
                        await light.set_colour_xy(x, y)
                        resp = {"ok": True, "data": {"x": x, "y": y}}
                elif cmd == "status":
                    await light.poll_state()
                    resp = {"ok": True, "data": {
                        "address": light.address,
                        "name": light.name,
                        "model": light.model,
                        "firmware": light.firmware,
                        "power": light.power_state,
                        "brightness": light.brightness,
                        "colour_temp": light.colour_temp,
                        "colour_xy": list(light.colour_xy) if light.colour_xy else None,
                    }}
                else:
                    resp = {"ok": False, "error": {"code": "unknown_cmd", "message": cmd}}
            except Exception as e:
                msg = str(e)
                code = _error_code_for_exception(e)
                resp = {"ok": False, "error": {"code": code, "message": msg}}

        await _write_response(writer, resp)

    except asyncio.TimeoutError:
        log.warning("daemon: client read timeout")
    except Exception as e:
        log.exception("daemon: handler error: %s", e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _write_response(writer: asyncio.StreamWriter, payload: dict) -> None:
    try:
        writer.write((json.dumps(payload) + "\n").encode())
        await writer.drain()
    except Exception as e:
        log.warning("daemon: write_response failed: %s", e)


# ==========================================================================
# Colour conversion (client side, kept tiny)
# ==========================================================================
def _rgb_to_xy(r: int, g: int, b: int) -> tuple:
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    r = pow((r + 0.055) / 1.055, 2.4) if r > 0.04045 else r / 12.92
    g = pow((g + 0.055) / 1.055, 2.4) if g > 0.04045 else g / 12.92
    b = pow((b + 0.055) / 1.055, 2.4) if b > 0.04045 else b / 12.92
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = X + Y + Z
    if total == 0:
        return 0.0, 0.0
    return X / total, Y / total


# ==========================================================================
# Public DevKit functions
# ==========================================================================
def _emit_from_daemon_response(metric: str, resp: dict, ok_spoken: str,
                               fail_default: str) -> None:
    if resp.get("ok"):
        _emit_success(metric, ok_spoken, resp.get("data") or {})
        return
    err = resp.get("error") or {}
    code = err.get("code", "unknown")
    msg = err.get("message", "")
    _emit_error(metric, code, msg, _spoken_for_error(code, fail_default))


def hue_connect(*_args) -> None:
    """Start the persistent daemon (if not already running) and confirm BLE.

    Returns quickly (within CONNECT_POLL_S seconds).  If the daemon is still
    starting it emits {"still_connecting": True} so main.py can retry rather
    than blocking inside a subprocess that the devkit may time-out and kill.
    """
    metric = "hue_connect"

    # Daemon already up — check that BLE is actually live before trusting it.
    if _daemon_pid() is not None and _daemon_socket_ready():
        ping = _send_command({"cmd": "ping"}, recv_timeout=3.0)
        if ping.get("ok") and ping.get("data", {}).get("ble_connected"):
            # BLE is live — return capabilities.
            caps_resp = _send_command({"cmd": "capabilities"}, recv_timeout=3.0)
            if caps_resp.get("ok"):
                _emit_success(metric, "Connected to the bulb.", caps_resp.get("data") or {})
                return
        # Daemon is up but BLE is dropped (e.g. factory reset, bulb power-cycled).
        # Kill it so we can start fresh and rediscover the (possibly new) MAC.
        log.warning("hue_connect: daemon running but BLE not connected; restarting for fresh discovery")
        pid = _daemon_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
            except OSError:
                pass
        _cleanup_daemon_files()

    # Spawn only if no daemon is running.
    if _daemon_pid() is None:
        try:
            _spawn_daemon()
        except Exception as e:
            _emit_error(metric, "spawn_failed", str(e), "I couldn't start the bulb connector.")
            return

    # Wait a short window; return "still_connecting" if daemon isn't ready yet
    # so the caller can retry without holding a long-lived subprocess open.
    if _wait_for_daemon_ready(CONNECT_POLL_S):
        resp = _send_command({"cmd": "capabilities"}, recv_timeout=3.0)
        if resp.get("ok"):
            _emit_success(metric, "Connected to the bulb.", resp.get("data") or {})
        else:
            _emit_from_daemon_response(metric, resp,
                                       "Connected to the bulb.",
                                       "I couldn't connect to the bulb.")
        return

    # Daemon is still connecting — include current phase so caller can speak progress.
    phase = _read_status().get("phase", "scanning")
    _emit_success(metric, "", {"still_connecting": True, "phase": phase})


def hue_capabilities(*_args) -> None:
    """Return what the bulb supports (brightness / temp / colour / etc.)."""
    metric = "hue_capabilities"
    resp = _send_command({"cmd": "capabilities"}, recv_timeout=3.0)
    if resp.get("ok"):
        d = resp.get("data") or {}
        bits = []
        if d.get("supports_on_off"):      bits.append("on/off")
        if d.get("supports_brightness"):  bits.append("brightness")
        if d.get("supports_colour_temp"): bits.append("white temperature")
        if d.get("supports_colour_xy"):   bits.append("colour")
        if d.get("supports_effects"):     bits.append("effects")
        feature_list = ", ".join(bits) if bits else "no controllable features detected"
        model = d.get("model") or "unknown model"
        _emit_success(metric, f"This is a {model}. It supports {feature_list}.", d)
    else:
        _emit_from_daemon_response(metric, resp, "", "I couldn't read the bulb's capabilities.")


def hue_on(*_args) -> None:
    resp = _send_command({"cmd": "on"})
    _emit_from_daemon_response("hue_on", resp, "Turning the light on.",
                               "I couldn't turn the light on.")


def hue_off(*_args) -> None:
    resp = _send_command({"cmd": "off"})
    _emit_from_daemon_response("hue_off", resp, "Turning the light off.",
                               "I couldn't turn the light off.")


def hue_brightness(val: str = "128") -> None:
    metric = "hue_brightness"
    try:
        level = max(1, min(254, int(val)))
    except (TypeError, ValueError):
        _emit_error(metric, "invalid_arg", f"bad brightness value: {val!r}",
                    "I need a brightness number between 1 and 254.")
        return
    resp = _send_command({"cmd": "brightness", "value": level})
    _emit_from_daemon_response(metric, resp, _brightness_spoken(level),
                               "I couldn't change the brightness.")


def _brightness_spoken(level: int) -> str:
    if level >= 250:
        return "Setting brightness to full."
    if 124 <= level <= 130:
        return "Setting brightness to half."
    percent = max(1, min(100, round(level * 100 / 254)))
    return f"Setting brightness to {percent} percent."


def hue_temp(val: str = "300") -> None:
    metric = "hue_temp"
    try:
        mireds = max(153, min(500, int(val)))
    except (TypeError, ValueError):
        _emit_error(metric, "invalid_arg", f"bad colour temp: {val!r}",
                    "I need a colour temperature between 153 and 500.")
        return
    resp = _send_command({"cmd": "temp", "value": mireds})
    _emit_from_daemon_response(metric, resp, f"Setting colour temperature to {mireds} mireds.",
                               "I couldn't change the colour temperature.")


def hue_color(val: str = "255,255,255") -> None:
    metric = "hue_color"
    try:
        parts = [int(p) for p in val.split(",")]
        if len(parts) != 3:
            raise ValueError(f"need 3 components, got {len(parts)}")
        r, g, b = (max(0, min(255, p)) for p in parts)
    except (TypeError, ValueError) as e:
        _emit_error(metric, "invalid_arg", f"bad colour value {val!r}: {e}",
                    "I need three numbers from zero to 255 for red, green, and blue.")
        return
    x, y = _rgb_to_xy(r, g, b)
    resp = _send_command({"cmd": "color", "x": x, "y": y})
    if resp.get("ok"):
        data = dict(resp.get("data") or {})
        data.update({"r": r, "g": g, "b": b})
        _emit_success(metric, f"Setting colour to red {r}, green {g}, blue {b}.", data)
    else:
        _emit_from_daemon_response(metric, resp, "", "I couldn't change the colour.")


def hue_status(*_args) -> None:
    metric = "hue_status"
    resp = _send_command({"cmd": "status"})
    if resp.get("ok"):
        data = resp.get("data") or {}
        power = "on" if data.get("power") else "off"
        bri = data.get("brightness")
        bri_phrase = f", brightness {bri}" if bri is not None else ""
        _emit_success(metric, f"The light is {power}{bri_phrase}.", data)
    else:
        _emit_from_daemon_response(metric, resp, "", "I couldn't read the bulb's status.")


def hue_disconnect(*_args) -> None:
    """Tell the daemon to disconnect from BLE and exit."""
    metric = "hue_disconnect"
    pid = _daemon_pid()
    if pid is None:
        _emit_success(metric, "Disconnected from the bulb.", {"daemon_was_running": False})
        return

    # Try graceful shutdown via socket first.
    resp = _send_command({"cmd": "shutdown"}, recv_timeout=3.0)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _daemon_pid() is not None:
        time.sleep(0.2)

    if _daemon_pid() is None:
        _emit_success(metric, "Disconnected from the bulb.", {"daemon_was_running": True})
        return

    # Socket shutdown failed (e.g. daemon still starting up); kill by PID.
    pid = _daemon_pid()
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and _daemon_pid() is not None:
                time.sleep(0.2)
        except OSError:
            pass

    _cleanup_daemon_files()
    _emit_success(metric, "Disconnected from the bulb.", {"daemon_was_running": True})


def hue_verify(*_args) -> None:
    """Run a self-test through every supported capability. Use this to debug."""
    metric = "hue_verify"

    # Ensure daemon is up.
    if _daemon_pid() is None or not _daemon_socket_ready():
        try:
            _spawn_daemon()
        except Exception as e:
            _emit_error(metric, "spawn_failed", str(e), "Verification could not start.")
            return
        if not _wait_for_daemon_ready(DAEMON_READY_TIMEOUT_S):
            _emit_error(metric, "no_daemon", "daemon not ready",
                        "Verification could not start.")
            return

    caps_resp = _send_command({"cmd": "capabilities"}, recv_timeout=3.0)
    if not caps_resp.get("ok"):
        _emit_from_daemon_response(metric, caps_resp, "", "Couldn't read capabilities.")
        return
    caps = caps_resp.get("data") or {}

    results = [{"step": "capabilities", "ok": True, "detail": caps}]

    def _step(name: str, payload: dict, pause: float = 0.4):
        resp = _send_command(payload, recv_timeout=10.0)
        results.append({"step": name, "ok": bool(resp.get("ok")),
                        "detail": resp.get("data") if resp.get("ok") else resp.get("error")})
        time.sleep(pause)

    # On/off
    if caps.get("supports_on_off"):
        _step("on",  {"cmd": "on"})
        _step("off", {"cmd": "off"})
        _step("on_again", {"cmd": "on"})

    # Brightness sweep
    if caps.get("supports_brightness"):
        for level in (10, 80, 180, 254):
            _step(f"brightness={level}", {"cmd": "brightness", "value": level})

    # Colour temperature sweep
    if caps.get("supports_colour_temp"):
        lo = caps.get("minimum_mireds") or 153
        hi = caps.get("maximum_mireds") or 500
        mid = (lo + hi) // 2
        for mireds in (lo, mid, hi):
            _step(f"temp={mireds}", {"cmd": "temp", "value": mireds})

    # Colour sweep (CIE xy approximations of red/green/blue)
    if caps.get("supports_colour_xy"):
        for label, x, y in (("red", 0.7, 0.3), ("green", 0.17, 0.7), ("blue", 0.15, 0.06)):
            _step(f"color={label}", {"cmd": "color", "x": x, "y": y})

    # Final status
    _step("final_status", {"cmd": "status"})

    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    spoken = f"Verification complete. {passed} of {total} steps passed."
    _emit_success(metric, spoken, {"passed": passed, "total": total, "results": results})


# ==========================================================================
# Dispatch
# ==========================================================================
FUNCTION_REGISTRY = {
    "hue_connect":      hue_connect,
    "hue_capabilities": hue_capabilities,
    "hue_on":           hue_on,
    "hue_off":          hue_off,
    "hue_brightness":   hue_brightness,
    "hue_temp":         hue_temp,
    "hue_color":        hue_color,
    "hue_status":       hue_status,
    "hue_verify":       hue_verify,
    "hue_disconnect":   hue_disconnect,
}


def main():
    # Special internal mode: run as the long-lived daemon.
    if len(sys.argv) >= 2 and sys.argv[1] == "_daemon":
        try:
            sys.exit(asyncio.run(_daemon_main()))
        except Exception:
            log.exception("daemon: unhandled exception")
            _cleanup_daemon_files()
            sys.exit(99)

    if len(sys.argv) < 2:
        _emit_error("dispatch", "missing_function", "No function name provided.",
                    "No DevKit function was provided.")
        sys.exit(1)

    function_name = sys.argv[1]
    function_args = sys.argv[2:]
    fn = FUNCTION_REGISTRY.get(function_name)
    if fn is None:
        _emit_error("dispatch", "unknown_function", f"unknown function: {function_name}",
                    "The requested DevKit function is not available.")
        sys.exit(1)

    try:
        fn(*function_args)
    except TypeError as e:
        log.exception("Invalid arguments for %s", function_name)
        _emit_error(function_name, "invalid_arguments", str(e),
                    "The DevKit function received invalid arguments.")
        sys.exit(1)
    except Exception as e:
        log.exception("Unhandled error while running %s", function_name)
        _emit_error(function_name, "unhandled_error", str(e),
                    "The DevKit function failed unexpectedly.")
        sys.exit(1)


if __name__ == "__main__":
    main()
