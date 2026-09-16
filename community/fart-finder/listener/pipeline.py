"""The detection pipeline: gate -> detector -> event writer.

Pure signal processing only. The live daemon (microphone thread, Unix socket,
process spawn) lives in devkit_functions.py because the OpenHome upload scan
rejects `threading`, `socket`, `signal` and similar modules in every other file
of the ability zip. Replay mode drives this same pipeline from a WAV file for
tests and evaluation.
"""
from __future__ import annotations

import logging

import numpy as np

from . import FRAME_SAMPLES, SAMPLE_RATE
from .classify import Detector
from .gate import LoudnessGate, Segment
from .magnitude import features

log = logging.getLogger("fartfinder")

SENSITIVITY_THRESHOLDS = {"low": 0.6, "medium": 0.4, "high": 0.25}


def threshold_for(cfg: dict) -> float:
    return SENSITIVITY_THRESHOLDS.get(cfg.get("sensitivity", "medium"), 0.4)


class Pipeline:
    """Gate + detector + event builder. Shared by live and replay modes.

    Pure: it never touches the filesystem. `on_event(event)` receives every
    event (the owner appends it to events.jsonl); `save_snippet(event_id, audio)`
    if set returns a path string that is stored on the event; `new_id(ts)`
    makes ids; `now()` supplies wall time (injectable for tests)."""

    def __init__(self, cfg: dict, detector: Detector, new_id, now=None):
        self.cfg = cfg
        self.gate = LoudnessGate(open_db=cfg["gate_open_db"], close_db=cfg["gate_close_db"],
                                 min_ms=cfg["min_ms"], max_ms=cfg["max_ms"])
        self.detector = detector
        self.new_id = new_id
        self.now = now or (lambda: 0.0)
        self.last_event_t = -1e9
        self.started = self.now()
        self.stream_t0 = self.now()
        self.stats = {"segments": 0, "events": 0, "near_misses": 0, "suppressed": 0}
        self.on_event = None       # callback(event)
        self.save_snippet = None   # callback(event_id, audio) -> path or None

    def apply_config(self, cfg: dict) -> None:
        self.cfg = cfg
        self.detector.threshold = threshold_for(cfg)
        self.gate.open_db = cfg["gate_open_db"]
        self.gate.close_db = cfg["gate_close_db"]
        self.gate.min_ms = cfg["min_ms"]
        self.gate.max_ms = cfg["max_ms"]

    def push_frame(self, frame: np.ndarray, wall_ts: float | None = None) -> dict | None:
        seg = self.gate.push(frame)
        if seg is None:
            return None
        return self.handle_segment(seg, wall_ts)

    def flush(self, wall_ts: float | None = None) -> dict | None:
        seg = self.gate.flush()
        return self.handle_segment(seg, wall_ts) if seg else None

    def handle_segment(self, seg: Segment, wall_ts: float | None = None) -> dict | None:
        self.stats["segments"] += 1
        wall_ts = wall_ts if wall_ts is not None else self.stream_t0 + seg.end_s
        verdict = self.detector.decide(seg.audio)
        feats = features(seg.audio, seg.peak_dbfs, seg.floor_dbfs, seg.duration_s)
        log.info("segment %.2fs peak %.1f floor %.1f yamnet_fart=%.3f p2=%.3f score=%.3f top=%s",
                 seg.duration_s, seg.peak_dbfs, seg.floor_dbfs, verdict["yamnet_fart"],
                 verdict["verifier_p"], verdict["score"], verdict["top"][:3])
        if not self.cfg.get("armed", True):
            return None
        detected = verdict["detected"]
        if detected and (seg.end_s - self.last_event_t) < self.cfg["cooldown_s"]:
            self.stats["suppressed"] += 1
            return None
        if not detected and not verdict["near_miss"]:
            return None
        ev = {"id": self.new_id(wall_ts), "ts": round(wall_ts, 3), **feats,
              "yamnet_fart": verdict["yamnet_fart"], "verifier_p": verdict["verifier_p"],
              "score": verdict["score"], "near_miss": not detected, "snippet": None}
        if self.cfg.get("review_mode") and self.save_snippet is not None:
            try:
                ev["snippet"] = self.save_snippet(ev["id"], seg.audio)
            except Exception as e:  # noqa: BLE001
                log.warning("snippet save failed: %s", e)
        if detected:
            self.last_event_t = seg.end_s
            self.stats["events"] += 1
        else:
            self.stats["near_misses"] += 1
        if self.on_event:
            self.on_event(ev)
        return ev


# --------------------------------------------------------------- replay mode

def floor_lead(audio: np.ndarray, seconds: float = 0.5) -> np.ndarray:
    """0.5 s of noise at the clip's own floor, so a trimmed clip bootstraps the
    gate the way a live mic would."""
    n = FRAME_SAMPLES
    if audio.size < n * 5:
        rms = 1e-4
    else:
        frames = audio[: audio.size - audio.size % n].reshape(-1, n)
        rms = float(np.percentile(np.sqrt(np.mean(frames ** 2, axis=1)), 10))
    rng = np.random.default_rng(0)
    return (rng.normal(0, max(rms, 1e-5), int(seconds * SAMPLE_RATE))).astype(np.float32)


def replay_audio(audio: np.ndarray, cfg: dict, detector: Detector, new_id, base_ts: float = 0.0) -> list[dict]:
    """Drive the pipeline over 16 kHz float32 audio. Returns the events produced."""
    audio = np.concatenate([floor_lead(audio), np.asarray(audio, dtype=np.float32)])
    pipe = Pipeline(cfg, detector=detector, new_id=new_id, now=lambda: base_ts)
    out = []
    pipe.on_event = out.append
    for i in range(0, len(audio) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
        pipe.push_frame(audio[i:i + FRAME_SAMPLES], wall_ts=base_ts + i / SAMPLE_RATE)
    pipe.flush(wall_ts=base_ts + len(audio) / SAMPLE_RATE)
    return out
