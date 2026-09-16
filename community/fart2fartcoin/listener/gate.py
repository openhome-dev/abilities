"""Stage 0: loudness gate with an adaptive noise floor.

Feed 20 ms frames of float32 PCM. The gate opens when a frame is more than
`open_db` above the floor and closes when it has stayed within `close_db`
of the floor for `hold_ms`. Segments outside [min_ms, max_ms] are discarded.
Emitted segments carry pre-roll and post-roll so the classifier sees onset
and tail.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from . import FRAME_MS, SAMPLE_RATE

FLOOR_TAU_S = 10.0      # time constant of the noise-floor average
HOLD_MS = 150           # quiet time required before closing
PREROLL_MS = 200
POSTROLL_MS = 200
MIN_FLOOR_DBFS = -80.0  # never let the floor go below this (silent rooms)
BOOTSTRAP_FRAMES = 25   # first 0.5 s: learn the floor from the quietest frames
BOOTSTRAP_MIN = 5       # frames needed before the gate may open


def rms_dbfs(frame: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)))) if frame.size else 0.0
    return 20.0 * math.log10(max(r, 1e-9))


@dataclass
class Segment:
    audio: np.ndarray            # float32 PCM including pre/post roll
    start_s: float               # stream time when the gate opened
    end_s: float                 # stream time when the gate closed
    peak_dbfs: float
    floor_dbfs: float
    frame_dbfs: list = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


class LoudnessGate:
    def __init__(self, open_db=12.0, close_db=6.0, min_ms=150, max_ms=4000,
                 sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS):
        self.open_db = open_db
        self.close_db = close_db
        self.min_ms = min_ms
        self.max_ms = max_ms
        self.sr = sample_rate
        self.frame_ms = frame_ms
        self.floor_dbfs = -50.0
        self._floor_alpha = frame_ms / 1000.0 / FLOOR_TAU_S
        self._pre = deque(maxlen=max(1, PREROLL_MS // frame_ms))
        self._open = False
        self._buf: list[np.ndarray] = []
        self._levels: list[float] = []
        self._quiet_frames = 0
        self._post_needed = max(1, POSTROLL_MS // frame_ms)
        self._post_left = 0
        self._pending: Segment | None = None
        self._t = 0.0
        self._open_t = 0.0
        self._close_t = 0.0
        self.muted_until = 0.0
        self._wait_quiet = False   # after a too-long burst, stay shut until the room is quiet
        self._boot: list[float] = []

    @property
    def is_open(self) -> bool:
        return self._open

    def mute(self, seconds: float) -> None:
        """Ignore input for `seconds` of stream time (speaker is talking)."""
        self.muted_until = max(self.muted_until, self._t + seconds)
        if self._open:
            self._discard()

    def _discard(self):
        self._open = False
        self._buf = []
        self._levels = []
        self._quiet_frames = 0

    def push(self, frame: np.ndarray) -> Segment | None:
        """Push one frame. Returns a Segment when one completes, else None."""
        level = rms_dbfs(frame)
        t = self._t
        self._t += self.frame_ms / 1000.0

        # Finish post-roll of a pending segment.
        if self._pending is not None:
            self._pending.audio = np.concatenate([self._pending.audio, frame])
            self._post_left -= 1
            if self._post_left <= 0:
                seg, self._pending = self._pending, None
                return seg
            return None

        if t < self.muted_until:
            self._pre.append(frame)
            return None

        if len(self._boot) < BOOTSTRAP_FRAMES:
            self._boot.append(level)
            self.floor_dbfs = max(float(np.percentile(self._boot, 20)), MIN_FLOOR_DBFS)
            if len(self._boot) < BOOTSTRAP_MIN:
                self._pre.append(frame)
                return None

        if not self._open:
            # Update floor only from quiet frames.
            if level < self.floor_dbfs + self.open_db:
                target = max(level, MIN_FLOOR_DBFS)
                self.floor_dbfs += self._floor_alpha * (target - self.floor_dbfs)
            self._pre.append(frame)
            if self._wait_quiet:
                if level < self.floor_dbfs + self.close_db:
                    self._wait_quiet = False
                return None
            if level > self.floor_dbfs + self.open_db:
                self._open = True
                self._open_t = t
                self._buf = list(self._pre)
                self._levels = [level]
                self._quiet_frames = 0
            return None

        # Gate is open.
        self._buf.append(frame)
        self._levels.append(level)
        dur_ms = (self._t - self._open_t) * 1000.0
        if level < self.floor_dbfs + self.close_db:
            self._quiet_frames += 1
        else:
            self._quiet_frames = 0

        closed = self._quiet_frames * self.frame_ms >= HOLD_MS
        too_long = dur_ms > self.max_ms
        if not (closed or too_long):
            return None

        self._close_t = self._t - (self._quiet_frames * self.frame_ms / 1000.0 if closed else 0.0)
        active_ms = (self._close_t - self._open_t) * 1000.0
        audio = np.concatenate(self._buf).astype(np.float32)
        levels = self._levels
        self._discard()
        if too_long or active_ms < self.min_ms:
            self._pre.clear()
            if too_long:
                # The room got louder and stayed there (fan, traffic). Re-seed
                # the floor from this burst so the gate can close again.
                self.floor_dbfs = max(float(np.percentile(levels, 20)), MIN_FLOOR_DBFS)
                self._wait_quiet = True
            return None
        seg = Segment(audio=audio, start_s=self._open_t, end_s=self._close_t,
                      peak_dbfs=max(levels), floor_dbfs=self.floor_dbfs,
                      frame_dbfs=levels)
        self._pending = seg
        self._post_left = self._post_needed
        self._pre.clear()
        return None

    def flush(self) -> Segment | None:
        """End of stream: close an open gate and return any pending segment."""
        if self._pending is not None:
            seg, self._pending = self._pending, None
            return seg
        if not self._open:
            return None
        active_ms = (self._t - self._open_t) * 1000.0
        audio = np.concatenate(self._buf).astype(np.float32)
        levels = self._levels
        end_t = self._t
        self._discard()
        if active_ms < self.min_ms or active_ms > self.max_ms:
            return None
        return Segment(audio=audio, start_s=self._open_t, end_s=end_t,
                       peak_dbfs=max(levels), floor_dbfs=self.floor_dbfs, frame_dbfs=levels)
