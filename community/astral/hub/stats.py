#!/usr/bin/env python3
"""Astral stats — deterministic descriptive statistics and counting. No LLM, µs.

  • centre      "average of 4 6 8 and 10", "median of 3 7 2 9", "mode of 2 2 5 7"
  • spread      "standard deviation of 4 6 8 10", "variance of 4 6 8 10",
                "range of 3 7 2 9"
  • position    "z score of 85 with a mean of 75 and a standard deviation of 5"
  • counting    "5 choose 2", "permutations of 5 taken 2"

Sample versus population is stated out loud rather than assumed silently — they are
different numbers and a stats class grades you on which one you used. Ask for the
population one by name and you get it.

handle(text) -> spoken string, or None to fall through.
"""
from __future__ import annotations
from typing import Optional
import re
import math
from calc import numbers, _fmt, _ONES, _TENS   # INLINE-STRIP

_ST_KEY = re.compile(r"\b(?:mean|average|median|mode|range|variance|"
                     r"standard deviation|std dev)\b")


def _st_list(text: str, t: str) -> list[float]:
    """The data as SEPARATE values.

    calc.numbers() deliberately merges an adjacent run — "twenty five" is one number,
    not two. A data list is the opposite problem: "4 6 8 10" is four numbers, and
    merging them answers 28. So the list is tokenised here instead, with one English
    concession: a tens word followed by a ones word ("twenty five") is still one
    number, because nobody reads a list as "twenty, five" out loud.
    """
    m = _ST_KEY.search(t)
    tail = t[m.end():] if m else t
    tail = re.sub(r"^\s*(?:of|for|is|are|was|were|the numbers?|these)\s+", " ", tail)
    toks = [w for w in re.split(r"[^a-z0-9.]+", tail) if w]
    vals, i = [], 0
    while i < len(toks):
        w = toks[i]
        if w.replace(".", "", 1).isdigit():
            vals.append(float(w))
        elif w in _TENS:
            if i + 1 < len(toks) and toks[i + 1] in _ONES and toks[i + 1] not in ("a", "an"):
                vals.append(float(_TENS[w] + _ONES[toks[i + 1]]))
                i += 2
                continue
            vals.append(float(_TENS[w]))
        elif w in _ONES and w not in ("a", "an"):
            vals.append(float(_ONES[w]))
        i += 1
    return vals


def _st_said(vals: list[float]) -> str:
    return ", ".join(_fmt(v) for v in vals)


def handle(text: str) -> Optional[str]:
    t = " " + text.lower().strip() + " "

    # ── z score (checked before the plain mean/deviation words) ───────────────
    if re.search(r"\bz[- ]?score\b", t):
        x = re.search(r"z[- ]?score (?:of|for) ([0-9]+(?:\.[0-9]+)?)", t)
        mu = re.search(r"mean (?:of|is) ([0-9]+(?:\.[0-9]+)?)", t)
        sd = re.search(r"(?:standard )?deviation (?:of|is) ([0-9]+(?:\.[0-9]+)?)", t)
        if x and mu and sd and float(sd.group(1)):
            z = (float(x.group(1)) - float(mu.group(1))) / float(sd.group(1))
            side = "above" if z >= 0 else "below"
            return (f"The z score is {_fmt(z)}, {_fmt(abs(z))} standard deviations "
                    f"{side} the mean.")
        return None

    # ── counting ──────────────────────────────────────────────────────────────
    m = re.search(r"([0-9]+)\s+choose\s+([0-9]+)", t)
    if m:
        n, k = int(m.group(1)), int(m.group(2))
        if 0 <= k <= n <= 170:
            return f"{n} choose {k} is {_fmt(math.comb(n, k))} combinations."
    if re.search(r"\bpermutations?\b", t):
        vals = numbers(text)
        if len(vals) >= 2:
            n, k = int(vals[0]), int(vals[1])
            if 0 <= k <= n <= 170:
                return f"{n} things taken {k} at a time is {_fmt(math.perm(n, k))} permutations."
        elif len(vals) == 1 and 0 <= vals[0] <= 170:
            n = int(vals[0])
            return f"{n} things can be arranged {_fmt(math.factorial(n))} ways."

    # ── descriptive statistics ────────────────────────────────────────────────
    wants = None
    if re.search(r"\b(?:mean|average)\b", t):
        wants = "mean"
    if re.search(r"\bmedian\b", t):
        wants = "median"
    if re.search(r"\bmode\b", t):
        wants = "mode"
    if re.search(r"\brange of\b", t):
        wants = "range"
    if re.search(r"\bvariance\b", t):
        wants = "variance"
    if re.search(r"\bstandard deviation\b|\bstd dev\b", t):
        wants = "stdev"
    if not wants:
        return None

    vals = _st_list(text, t)
    if len(vals) < 2:
        return None
    n = len(vals)
    said = _st_said(vals)

    if wants == "mean":
        return f"The mean of {said} is {_fmt(sum(vals)/n)}."
    if wants == "median":
        s = sorted(vals)
        med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
        return f"The median of {said} is {_fmt(med)}."
    if wants == "mode":
        counts = {}
        for v in vals:
            counts[v] = counts.get(v, 0) + 1
        top = max(counts.values())
        if top == 1:
            return f"{said} has no mode — every value appears once."
        modes = [v for v, c in counts.items() if c == top]
        which = " and ".join(_fmt(v) for v in modes)
        return (f"The mode of {said} is {which}, appearing {top} times."
                if len(modes) == 1 else
                f"{said} is multimodal: {which}, each appearing {top} times.")
    if wants == "range":
        return f"The range of {said} is {_fmt(max(vals) - min(vals))}, from {_fmt(min(vals))} to {_fmt(max(vals))}."

    mean = sum(vals) / n
    ss = sum((v - mean) ** 2 for v in vals)
    population = bool(re.search(r"\bpopulation\b", t))
    div = n if population else n - 1
    var = ss / div
    label = "population" if population else "sample"
    if wants == "variance":
        return f"The {label} variance of {said} is {_fmt(var)}."
    return (f"The {label} standard deviation of {said} is {_fmt(math.sqrt(var))}, "
            f"around a mean of {_fmt(mean)}.")


if __name__ == "__main__":
    for q in [
        "average of 4 6 8 and 10", "median of 3 7 2 9", "mode of 2 2 5 7",
        "range of 3 7 2 9", "standard deviation of 4 6 8 10",
        "population standard deviation of 4 6 8 10", "variance of 4 6 8 10",
        "z score of 85 with a mean of 75 and a standard deviation of 5",
        "5 choose 2", "permutations of 5 taken 2", "what time is it",
    ]:
        print(f"  {q:58} -> {handle(q)}")
