#!/usr/bin/env python3
"""Mechanical command layer — deterministic, no-LLM, no-cloud, sub-millisecond.

The efficiency wedge. Trivial commands (time / date / day / part-of-day) are
DETERMINISTIC — the answer is computed, not reasoned. OpenHome currently routes
them the full path: cloud STT → LLM agent → cloud TTS (multiple seconds, a model
invocation, network). This catches them on-device before any of that spins up.

Design goals (this is a demonstration piece — it must be flawless):
  • zero external calls, zero allocation beyond the string it returns
  • pure function of (utterance, now) — trivially testable, no globals
  • returns None when it's NOT a mechanical command → clean fall-through to the
    normal path, so it never swallows anything it shouldn't
  • small + self-contained enough to upstream into OpenHome OS as-is

Timezone: uses the device's local clock. (Set the device TZ correctly — the DevKit
image shipped Asia/Karachi; a real deploy should match the user.)
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime
import re


def _hm(now: datetime) -> str:
    return now.strftime("%I:%M %p").lstrip("0").lower()


def _time(now):
    return f"It's {_hm(now)}."


def _date(now):
    return f"Today is {now.strftime('%A, %B %d, %Y').replace(' 0', ' ')}."


def _day(now):
    return f"It's {now.strftime('%A')}."


def _month(now):
    return f"It's {now.strftime('%B')}."


def _year(now):
    return f"It's {now.strftime('%Y')}."


def _partofday(now):
    h = now.hour
    part = ("early morning" if h < 6 else "morning" if h < 12 else
            "afternoon" if h < 17 else "evening" if h < 21 else "night")
    return f"It's {part}, {_hm(now)}."


def _ampm(now):
    return f"It's {now.strftime('%p').lower()}, {_hm(now)}."


# These have to be questions about NOW, not sentences that happen to contain a time
# word. The first version matched bare "the time", "the date", "what year" and "what
# month", which meant this module — the one that runs FIRST, so nothing else gets a
# turn after it — answered:
#
#   "what year did the war end"          -> "It's 2026."
#   "what month is best to visit japan"  -> "It's August."
#   "what's the time zone in tokyo"      -> "It's 3:55 pm."
#   "what's the date of the super bowl"  -> "Today is Friday, August 7, 2026."
#   "what day of the week was I born"    -> "Today is Friday, August 7, 2026."
#
# Eight for eight on a set of ordinary phrasings, each one confidently wrong and each
# one taking the turn from an agent that could have answered properly. Every pattern
# below now names the whole question instead of a word inside it.
HANDLERS = [
    (re.compile(r"\bwhat('?s| is) the date\b|\btoday'?s date\b|\bwhat('?s| is) today\b|"
                r"\bwhat date is it\b|\btell me the date\b|\bthe date today\b"), _date),
    (re.compile(r"\bwhat day is (it|today)\b|\bwhat('?s| is) the day\b|"
                r"\bwhat day of the week is (it|today)\b"), _day),
    (re.compile(r"\bwhat month is (it|this)\b|\bcurrent month\b|"
                r"\bwhat('?s| is) the month\b"), _month),
    (re.compile(r"\bwhat year is (it|this)\b|\bcurrent year\b|"
                r"\bwhat('?s| is) the year\b"), _year),
    (re.compile(r"\bmorning or (afternoon|evening|night)\b|\bpart of the day\b"), _partofday),
    (re.compile(r"\bis it (am|pm|a\.m\.|p\.m\.)\b|\bam or pm\b"), _ampm),
    (re.compile(r"\bwhat time is it\b|\bwhat('?s| is) the time\b|\bcurrent time\b|"
                r"\btime is it now\b|\bgot the time\b|\b(do you )?have the time\b|"
                r"\btell me the time\b"), _time),
]

# Even an anchored pattern can sit inside a sentence plainly about something else.
# "Remind me at the time of the meeting" contains "the time"; so does "set an alarm for
# the time I usually wake up". A tense marker or a second subject means the question is
# not about this instant, and declining costs nothing — the agent takes the turn.
_NOT_NOW = re.compile(
    r"\b(did|was|were|had|will|would|going to|used to|next|last|upcoming|previous|"
    r"yesterday|tomorrow|born|ago|remind|reminder|alarm|schedule|calendar|"
    r"time ?zone|best (time|month|day)|of the)\b")


def handle(utterance: str, now: Optional[datetime] = None) -> Optional[str]:
    """Return a spoken answer for a mechanical command, or None to fall through."""
    now = now or datetime.now()
    t = " " + utterance.lower().strip() + " "
    if _NOT_NOW.search(t):
        return None
    for pat, fn in HANDLERS:
        if pat.search(t):
            return fn(now)
    return None


# ── demo: the efficiency contrast ─────────────────────────────────────────────
if __name__ == "__main__":
    import time as _t
    fixed = datetime(2026, 8, 3, 14, 5)   # deterministic for the demo
    queries = ["what time is it", "what's the time", "what's the date", "what day is it",
               "what month is it", "is it am or pm", "morning or afternoon",
               "what year is it", "tell me a joke"]  # last one falls through
    print("=== mechanical command layer (local, deterministic) ===")
    for q in queries:
        t0 = _t.perf_counter()
        ans = handle(q, now=fixed)
        us = (_t.perf_counter() - t0) * 1e6
        print(f"  {q:<24} -> {ans if ans else '(falls through to normal path)':<45} [{us:6.1f} µs]")
    # aggregate cost vs. the cloud path it replaces
    N = 10000
    t0 = _t.perf_counter()
    for _ in range(N):
        handle("what time is it", now=fixed)
    per = (_t.perf_counter() - t0) / N * 1e6
    print(f"\n  avg local resolve: {per:.2f} µs/call  "
          f"(vs OpenHome's current path: cloud STT + LLM + cloud TTS ≈ seconds)")
