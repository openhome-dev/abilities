"""The Ripter scale and per-event acoustic features."""
from __future__ import annotations

import math

import numpy as np

from . import SAMPLE_RATE

CLASSES = [
    (1.0, "whisper"),
    (3.0, "squeak"),
    (4.0, "standard-issue"),
    (5.0, "notable"),
    (6.0, "room-clearing"),
    (7.0, "structural"),
    (8.0, "evacuate"),
    (9.0, "biblical"),
]


def ripter(peak_dbfs: float, floor_dbfs: float, duration_s: float) -> float:
    """M = 2 log10(peak_rms/floor_rms) + 0.6 log10(duration/0.25), clamped 1..10."""
    energy_ratio = 10 ** ((peak_dbfs - floor_dbfs) / 20.0)
    m = 2.0 * math.log10(max(energy_ratio, 1e-6)) + 0.6 * math.log10(max(duration_s, 0.01) / 0.25)
    return round(min(10.0, max(1.0, m)), 1)


def classify_magnitude(m: float) -> str:
    name = CLASSES[0][1]
    for lo, n in CLASSES:
        if m >= lo:
            name = n
    return name


def dominant_hz(audio: np.ndarray, sr: int = SAMPLE_RATE) -> int:
    if audio.size < 64:
        return 0
    win = np.hanning(audio.size)
    spec = np.abs(np.fft.rfft(audio * win))
    freqs = np.fft.rfftfreq(audio.size, 1.0 / sr)
    band = (freqs >= 30) & (freqs <= 4000)
    if not band.any():
        return 0
    return int(round(float(freqs[band][int(np.argmax(spec[band]))])))


def tonality(audio: np.ndarray) -> float:
    """1 - spectral flatness. 0 = airy noise, 1 = pure tone."""
    if audio.size < 64:
        return 0.0
    spec = np.abs(np.fft.rfft(audio * np.hanning(audio.size))) + 1e-12
    gmean = math.exp(float(np.mean(np.log(spec))))
    amean = float(np.mean(spec))
    return round(float(min(1.0, max(0.0, 1.0 - gmean / amean))), 3)


def features(audio: np.ndarray, peak_dbfs: float, floor_dbfs: float, duration_s: float) -> dict:
    m = ripter(peak_dbfs, floor_dbfs, duration_s)
    return {
        "duration_s": round(duration_s, 2),
        "peak_dbfs": round(peak_dbfs, 1),
        "floor_dbfs": round(floor_dbfs, 1),
        "energy_ratio": round(10 ** ((peak_dbfs - floor_dbfs) / 20.0), 1),
        "magnitude": m,
        "class": classify_magnitude(m),
        "dominant_hz": dominant_hz(audio),
        "tonality": tonality(audio),
    }
