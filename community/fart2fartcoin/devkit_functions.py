"""Fart Finder device side. Runs on the DevKit (or a Mac stand-in).

This is the one file the OpenHome upload scan exempts, so everything that
touches the OS lives here: config and event files, model loading, the
microphone thread, the Unix socket, process spawn. `listener/` is pure signal
processing and imports nothing beyond numpy.

RPC (called by OpenHome as `python devkit_functions.py <fn> <args...>`; prints
exactly one JSON object on stdout):
    start_listener [config_json]   spawn the daemon if not running
    stop_listener                   ask the daemon to exit
    poll_events [since_id]          events after since_id ("0" = today)
    status                          armed, sensitivity, floor, uptime, journal
    set_config <config_json>        merge and apply config
    mute <seconds>                  ignore the mic while the speaker talks
    inject <file.wav>               dev: feed a WAV through the live daemon as if the mic heard it

Developer commands (same entry point):
    _daemon                         run the listener in the foreground
    replay <file.wav> [sensitivity] run the live pipeline over a file
    record <seconds> <out.wav>      capture the mic (for datasets)
    devices                         list input devices
    selftest                        DevKit owners: check mic, model, CPU; paste the JSON back to us

State: ~/.fartfinder/ (override with FARTFINDER_STATE_DIR).
"""
from __future__ import annotations

import errno
import json
import logging
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

from listener import FRAME_SAMPLES, SAMPLE_RATE  # noqa: E402
from listener.classify import Detector, parse_class_map  # noqa: E402
from listener.pipeline import SENSITIVITY_THRESHOLDS, Pipeline, replay_audio, threshold_for  # noqa: E402

try:
    from devkit_utils.devkit_logging import web_logger as log  # DevKit runtime
except Exception:  # noqa: BLE001
    log = logging.getLogger("fartfinder.rpc")   # configured in main(); silent when imported

dlog = logging.getLogger("fartfinder")

READY_TIMEOUT_S = 25.0
RECV_TIMEOUT_S = 5.0
MODELS = HERE / "listener" / "models"

# ------------------------------------------------------------------- config

DEFAULTS = {
    "device": "default",
    "sample_rate": 16000,
    "sensitivity": "medium",
    "gate_open_db": 12.0,
    "gate_close_db": 6.0,
    "min_ms": 150,
    "max_ms": 4000,
    "cooldown_s": 10.0,
    "review_mode": False,
    "armed": True,
}


def state_dir() -> Path:
    d = os.environ.get("FARTFINDER_STATE_DIR")
    p = Path(d) if d else Path.home() / ".fartfinder"
    p.mkdir(parents=True, exist_ok=True)
    return p


def socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime and Path(runtime).is_dir() else Path("/tmp")
    return str(base / "fartfinder.sock")


def pid_path() -> Path:
    return state_dir() / "daemon.pid"


def log_path() -> Path:
    return state_dir() / "daemon.log"


def events_path() -> Path:
    return state_dir() / "events.jsonl"


def config_path() -> Path:
    return state_dir() / "listener.json"


def snippets_dir() -> Path:
    d = state_dir() / "snippets"
    d.mkdir(exist_ok=True)
    return d


def normalize(cfg: dict | None) -> dict:
    """Merge with defaults and coerce types. Unknown keys are dropped."""
    out = dict(DEFAULTS)
    for k, v in (cfg or {}).items():
        if k not in DEFAULTS:
            continue
        default = DEFAULTS[k]
        if isinstance(default, bool):
            out[k] = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on")
        elif isinstance(default, float):
            out[k] = float(v)
        elif isinstance(default, int):
            out[k] = int(v)
        else:
            out[k] = v
    if out["sensitivity"] not in SENSITIVITY_THRESHOLDS:
        out["sensitivity"] = "medium"
    return out


def load_config() -> dict:
    try:
        with open(config_path()) as f:
            return normalize(json.load(f))
    except (FileNotFoundError, ValueError):
        return normalize(None)


def save_config(cfg: dict) -> dict:
    cfg = normalize(cfg)
    with open(config_path(), "w") as f:
        json.dump(cfg, f, indent=2)
    return cfg


# ------------------------------------------------------------------- events

def new_id(ts: float | None = None) -> str:
    ts = ts or time.time()
    stamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%dT%H%M%S.") + f"{int((ts % 1) * 1000):03d}Z"
    return f"{stamp}-{secrets.token_hex(2)}"


def append_event(event: dict, path: Path | None = None) -> None:
    with open(path or events_path(), "a") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")


def read_events(path: Path | None = None) -> list[dict]:
    out = []
    try:
        with open(path or events_path()) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    return out


def events_today(evs: list[dict] | None = None, now: float | None = None) -> list[dict]:
    evs = read_events() if evs is None else evs
    day = datetime.fromtimestamp(now or time.time()).date()
    return [e for e in evs if datetime.fromtimestamp(e.get("ts", 0)).date() == day and not e.get("near_miss")]


def events_since(since_id: str, path: Path | None = None) -> list[dict]:
    """Events with id > since_id. '0' or '' means everything from today."""
    evs = read_events(path)
    if since_id in ("", "0", None):
        return events_today(evs)
    return [e for e in evs if e.get("id", "") > since_id]


def journal(evs: list[dict] | None = None) -> dict:
    t = events_today(evs)
    if not t:
        return {"count": 0, "max_magnitude": None, "last_ts": None}
    biggest = max(t, key=lambda e: e.get("magnitude", 0))
    return {"count": len(t), "max_magnitude": biggest.get("magnitude"),
            "max_class": biggest.get("class"), "last_ts": t[-1].get("ts")}


# ------------------------------------------------------------------- models

def load_detector(threshold: float = 0.4) -> Detector:
    with open(MODELS / "yamnet_class_map.csv") as f:
        classes = parse_class_map(f.read())
    head = None
    head_path = MODELS / "head.npz"
    if head_path.exists():
        d = np.load(head_path)
        head = {k: d[k] for k in ("w", "b", "mu", "sd")}
    return Detector(str(MODELS / "yamnet.tflite"), classes, head, threshold)


def load_audio_16k(path: str) -> np.ndarray:
    import soundfile as sf
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    audio = audio[:, 0]
    if sr != SAMPLE_RATE:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(sr, SAMPLE_RATE)
        audio = resample_poly(audio, SAMPLE_RATE // g, sr // g).astype(np.float32)
    return audio


def replay_file(path: str, cfg: dict, detector: Detector | None = None, events_out: Path | None = None) -> list[dict]:
    detector = detector or load_detector(threshold_for(cfg))
    detector.threshold = threshold_for(cfg)
    evs = replay_audio(load_audio_16k(path), cfg, detector, new_id, base_ts=time.time())
    if events_out is not None:
        for e in evs:
            append_event(e, events_out)
    return evs


# -------------------------------------------------------------- live daemon

class Daemon:
    """Mic thread -> Pipeline; `dispatch()` answers JSON commands."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        detector = load_detector(threshold_for(cfg))
        self.pipe = Pipeline(cfg, detector=detector, new_id=new_id, now=time.time)
        self.pipe.on_event = self._on_event
        self.pipe.save_snippet = self._save_snippet
        self.frames: queue.Queue = queue.Queue(maxsize=500)
        self.stop_evt = threading.Event()
        self.stream = None
        self.last_id = "0"

    def _on_event(self, ev):
        append_event(ev)
        if not ev.get("near_miss"):
            self.last_id = ev["id"]
            dlog.info("EVENT %s magnitude %.1f (%s)", ev["id"], ev["magnitude"], ev["class"])

    def _save_snippet(self, ev_id: str, audio: np.ndarray) -> str:
        import soundfile as sf
        p = snippets_dir() / f"{ev_id}.wav"
        sf.write(str(p), audio, SAMPLE_RATE)
        return str(p)

    def _audio_cb(self, indata, frames, time_info, status):
        if status:
            dlog.warning("audio status: %s", status)
        try:
            self.frames.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def _open_stream(self):
        import sounddevice as sd
        dev = self.cfg["device"]
        device = None if dev in ("default", "", None) else (int(dev) if str(dev).isdigit() else dev)
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                     blocksize=FRAME_SAMPLES, device=device, callback=self._audio_cb)
        self.stream.start()
        dlog.info("mic open: %s @ %d Hz", sd.query_devices(self.stream.device)["name"], SAMPLE_RATE)

    def _audio_loop(self):
        self.pipe.stream_t0 = time.time()
        while not self.stop_evt.is_set():
            try:
                frame = self.frames.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.pipe.push_frame(frame)
            except Exception:  # noqa: BLE001
                dlog.exception("pipeline error")

    def status(self) -> dict:
        return {"ok": True, "armed": bool(self.cfg.get("armed", True)),
                "sensitivity": self.cfg["sensitivity"],
                "floor_dbfs": round(self.pipe.gate.floor_dbfs, 1),
                "uptime_s": int(time.time() - self.pipe.started),
                "today": journal(), "stats": self.pipe.stats,
                "head_loaded": self.pipe.detector.head.loaded, "last_id": self.last_id,
                "pid": os.getpid()}

    def dispatch(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "ping":
            return {"ok": True, "pid": os.getpid()}
        if cmd == "poll":
            evs = [e for e in events_since(req.get("since", "0")) if not e.get("near_miss")]
            return {"ok": True, "events": evs, "last_id": evs[-1]["id"] if evs else req.get("since", "0"),
                    "daemon_alive": True}
        if cmd == "status":
            return self.status()
        if cmd == "config":
            self.cfg = save_config({**self.cfg, **(req.get("config") or {})})
            self.pipe.apply_config(self.cfg)
            return {"ok": True, "config": self.cfg}
        if cmd == "mute":
            secs = float(req.get("seconds", 3.0))
            self.pipe.gate.mute(secs)
            return {"ok": True, "muted_s": secs}
        if cmd == "inject":
            # Dev hook: queue a file's audio as mic frames. Same gate, same
            # detector, same event path; only the room is skipped.
            audio = load_audio_16k(req["path"])
            n = 0
            for i in range(0, len(audio) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
                try:
                    self.frames.put(audio[i:i + FRAME_SAMPLES], timeout=2.0)
                    n += 1
                except queue.Full:
                    break
            return {"ok": True, "frames": n, "seconds": round(n * FRAME_SAMPLES / SAMPLE_RATE, 2)}
        if cmd == "stop":
            self.stop_evt.set()
            return {"ok": True}
        return {"ok": False, "error": f"unknown cmd: {cmd}"}

    def _serve(self):
        path = socket_path()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(8)
        srv.settimeout(0.5)

        def handle(conn):
            conn.settimeout(5.0)
            try:
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                resp = self.dispatch(json.loads(buf.decode() or "{}"))
            except Exception as e:  # noqa: BLE001
                resp = {"ok": False, "error": f"bad request: {e}"}
            try:
                conn.sendall((json.dumps(resp) + "\n").encode())
            finally:
                conn.close()

        while not self.stop_evt.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
        srv.close()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    def run(self):
        pid_path().write_text(str(os.getpid()))
        self._open_stream()
        threads = [threading.Thread(target=self._audio_loop, daemon=True),
                   threading.Thread(target=self._serve, daemon=True)]
        for t in threads:
            t.start()
        dlog.info("daemon ready. socket=%s events=%s", socket_path(), events_path())
        try:
            while not self.stop_evt.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_evt.set()
            if self.stream:
                self.stream.stop()
                self.stream.close()
            for t in threads:
                t.join(timeout=2.0)
            try:
                pid_path().unlink()
            except FileNotFoundError:
                pass
            dlog.info("daemon stopped")


def run_daemon(cfg: dict | None = None, foreground: bool = False) -> None:
    handlers = [logging.StreamHandler(sys.stderr)] if foreground else [logging.FileHandler(log_path())]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=handlers, force=True)
    Daemon(cfg or load_config()).run()


# ------------------------------------------------------------- daemon control

def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _ok(**kw) -> dict:
    return {"ok": True, **kw}


def _err(msg: str, **kw) -> dict:
    return {"ok": False, "error": msg, **kw}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        return e.errno == errno.EPERM


def _daemon_pid() -> int | None:
    try:
        pid = int(pid_path().read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    return pid if _pid_alive(pid) else None


def _send(payload: dict, timeout: float = RECV_TIMEOUT_S) -> dict:
    path = socket_path()
    if not Path(path).exists():
        return _err("daemon not running")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
        s.sendall((json.dumps(payload) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode() or "{}")
    except (OSError, ValueError) as e:
        return _err(f"daemon unreachable: {e}")
    finally:
        s.close()


def _spawn() -> None:
    log_fp = open(log_path(), "a")
    log_fp.write(f"\n---- spawn at {time.strftime('%Y-%m-%d %H:%M:%S')} ----\n")
    log_fp.flush()
    subprocess.Popen(
        [sys.executable, os.path.realpath(__file__), "_daemon"],
        cwd=str(HERE),
        stdin=subprocess.DEVNULL, stdout=log_fp, stderr=log_fp,
        start_new_session=True, close_fds=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def _wait_ready(timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _send({"cmd": "ping"}, timeout=2.0).get("ok"):
            return True
        time.sleep(0.5)
    return False


# ------------------------------------------------------------------ RPC fns

def start_listener(config_json: str = "{}") -> None:
    cfg = normalize({**load_config(), **json.loads(config_json or "{}")})
    save_config(cfg)
    if _send({"cmd": "ping"}).get("ok"):
        _send({"cmd": "config", "config": cfg})
        _emit(_ok(pid=_daemon_pid(), already_running=True))
        return
    _spawn()
    if _wait_ready(READY_TIMEOUT_S):
        _emit(_ok(pid=_daemon_pid(), already_running=False))
    else:
        _emit(_err("daemon did not become ready", log=str(log_path())))


def stop_listener() -> None:
    r = _send({"cmd": "stop"})
    if not r.get("ok"):
        pid = _daemon_pid()
        if pid:
            os.kill(pid, 15)
            r = _ok(killed=pid)
    _emit(r)


def poll_events(since_id: str = "0") -> None:
    r = _send({"cmd": "poll", "since": since_id})
    if not r.get("ok"):
        r["events"] = []
        r["last_id"] = since_id
        r["daemon_alive"] = False
    _emit(r)


def status() -> None:
    r = _send({"cmd": "status"})
    if not r.get("ok"):
        r["daemon_alive"] = False
    _emit(r)


def set_config(config_json: str) -> None:
    cfg = json.loads(config_json)
    r = _send({"cmd": "config", "config": cfg})
    if not r.get("ok"):
        saved = save_config({**load_config(), **cfg})   # daemon down: persist for next start
        r = _ok(config=saved, daemon_alive=False)
    _emit(r)


def mute(seconds: str = "3") -> None:
    _emit(_send({"cmd": "mute", "seconds": float(seconds)}))


def inject(path: str) -> None:
    _emit(_send({"cmd": "inject", "path": str(Path(path).resolve())}, timeout=30.0))


# ------------------------------------------------------------ dev commands

def _cmd_replay(path: str, sensitivity: str = "medium") -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr, force=True)
    evs = replay_file(path, normalize({"sensitivity": sensitivity}))
    for e in evs:
        sys.stdout.write(json.dumps(e) + "\n")
    hits = [e for e in evs if not e["near_miss"]]
    sys.stderr.write(f"{len(hits)} event(s), {len(evs) - len(hits)} near miss(es)\n")


def _cmd_record(seconds: str, out: str, device: str = "") -> None:
    import sounddevice as sd
    import soundfile as sf
    dev = None if not device else (int(device) if device.isdigit() else device)
    sys.stderr.write(f"recording {seconds}s ...\n")
    data = sd.rec(int(float(seconds) * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=dev)
    sd.wait()
    sf.write(out, data, SAMPLE_RATE)
    sys.stderr.write(f"wrote {out}\n")


def _cmd_devices() -> None:
    import sounddevice as sd
    sys.stdout.write(str(sd.query_devices()) + "\n")


def _cmd_selftest(seconds: str = "3") -> None:
    """One JSON report covering everything week 5 of the plan needs to know."""
    import platform
    report = {"ok": True, "platform": platform.platform(), "python": sys.version.split()[0],
              "machine": platform.machine(), "state_dir": str(state_dir()), "checks": {}}

    def check(name, fn):
        t = time.monotonic()
        try:
            report["checks"][name] = {"ok": True, "result": fn(), "ms": int((time.monotonic() - t) * 1000)}
        except Exception as e:  # noqa: BLE001
            report["ok"] = False
            report["checks"][name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def devices():
        import sounddevice as sd
        return [{"index": i, "name": d["name"], "in": d["max_input_channels"], "rate": d["default_samplerate"]}
                for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]

    def mic():
        import sounddevice as sd
        cfg = load_config()
        dev = cfg["device"]
        device = None if dev in ("default", "", None) else (int(dev) if str(dev).isdigit() else dev)
        data = sd.rec(int(float(seconds) * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1,
                      dtype="float32", device=device)
        sd.wait()
        x = data[:, 0]
        rms = float(np.sqrt(np.mean(x ** 2)) + 1e-9)
        return {"device": sd.query_devices(device or sd.default.device[0])["name"], "seconds": float(seconds),
                "rms_dbfs": round(20 * np.log10(rms), 1), "peak_dbfs": round(20 * np.log10(float(np.abs(x).max()) + 1e-9), 1),
                "flat_zero": bool(np.abs(x).max() < 1e-6)}

    def model():
        det = load_detector()
        wav = np.random.default_rng(0).normal(0, 0.05, SAMPLE_RATE).astype(np.float32)
        t = time.monotonic()
        det.decide(wav)
        return {"yamnet_loaded": True, "head_loaded": det.head.loaded,
                "infer_ms_per_second_of_audio": int((time.monotonic() - t) * 1000)}

    def daemon_alive():
        return _send({"cmd": "ping"}).get("ok", False)

    def cpu():
        try:
            load = os.getloadavg()
            return {"loadavg_1m": round(load[0], 2), "cpus": os.cpu_count()}
        except OSError:
            return {"cpus": os.cpu_count()}

    check("input_devices", devices)
    check("mic_capture", mic)
    check("model", model)
    check("daemon_alive", daemon_alive)
    check("cpu", cpu)
    _emit(report)


FUNCTIONS = {
    "start_listener": start_listener,
    "stop_listener": stop_listener,
    "poll_events": poll_events,
    "status": status,
    "set_config": set_config,
    "mute": mute,
    "inject": inject,
    "replay": _cmd_replay,
    "record": _cmd_record,
    "devices": _cmd_devices,
    "selftest": _cmd_selftest,
}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    if argv and argv[0] == "_daemon":
        run_daemon(foreground="--fg" in argv)
        return 0
    if not argv:
        _emit(_err("no function name"))
        return 1
    fn = FUNCTIONS.get(argv[0])
    if fn is None:
        _emit(_err(f"unknown function: {argv[0]}"))
        return 1
    try:
        fn(*argv[1:])
        return 0
    except TypeError as e:
        _emit(_err(f"invalid arguments: {e}"))
        return 1
    except Exception as e:  # noqa: BLE001
        log.exception("unhandled error in %s", argv[0])
        _emit(_err(f"unhandled: {e}"))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
