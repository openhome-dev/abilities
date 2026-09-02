#!/usr/bin/env python3
"""Astral study — deterministic grade arithmetic. No LLM, no cloud, µs.

The questions a student actually asks out loud, all of them plain arithmetic that a
model has no business guessing at:

  • what's left      "I have an 87 and the final is worth 20 percent,
                      what do I need to get a 90"
  • score to percent "what's my grade if I got 42 out of 50"
  • letter bands     "what letter grade is an 87"
  • weighted total   "homework is 90 worth 20 percent and exams are 84 worth 80 percent"
  • gpa             "gpa for a 4.0 in 3 credits and a 3.0 in 4 credits"

Every answer that depends on a grading scale says which scale it used, because the
scale is a convention and not a fact. Saying "an 87 is a B plus" without naming the
bands would be the confidently-wrong behaviour this whole layer exists to avoid.

handle(text) -> spoken string, or None to fall through.
"""
from __future__ import annotations
from typing import Optional
import re
from calc import numbers, _fmt   # INLINE-STRIP

# Standard 90/80/70 scale with plus-minus bands. Floor percent -> letter.
_GR_BANDS = [(97, "A plus"), (93, "A"), (90, "A minus"), (87, "B plus"), (83, "B"),
             (80, "B minus"), (77, "C plus"), (73, "C"), (70, "C minus"),
             (67, "D plus"), (63, "D"), (60, "D minus"), (0, "F")]

# Whole-letter targets, used when a target is spoken as a letter rather than a number.
_GR_TARGET = {"a": 90, "b": 80, "c": 70, "d": 60}


def _gr_letter(pct: float) -> str:
    for floor, name in _GR_BANDS:      # the table ends at 0, so this always returns
        if pct >= floor:
            return name


def _gr_article(letter: str) -> str:
    return "an" if letter[0] in "aef" else "a"


def _gr_target_percent(t: str):
    """Target as a number ('90') or as a letter ('a B'). None when absent."""
    m = re.search(r"\b(?:to get|for|get|earn|end with|finish with|need)\s+"
                  r"(?:an?\s+)?([0-9]{1,3}(?:\.[0-9]+)?)\s*(?:percent|%)?", t)
    if m:
        v = float(m.group(1))
        if 0 < v <= 150:
            return v, f"{_fmt(v)} percent"
    m = re.search(r"\b(?:to get|for|get|earn|end with|finish with|need)\s+an?\s+"
                  r"\b([abcd])\b", t)
    if m:
        letter = m.group(1)
        return _GR_TARGET[letter], f"{letter.upper()} at {_GR_TARGET[letter]} percent"
    return None


def _gr_pairs(t: str):
    """(value, weight) pairs from 'X worth Y percent' phrasings, in sentence order."""
    pairs = []
    for m in re.finditer(r"([0-9]{1,3}(?:\.[0-9]+)?)\s*(?:percent|%)?[^0-9]{0,24}?"
                         r"(?:worth|weighted|weighs|counts for|is)\s+"
                         r"([0-9]{1,3}(?:\.[0-9]+)?)\s*(?:percent|%)", t):
        pairs.append((float(m.group(1)), float(m.group(2))))
    return pairs


def handle(text: str) -> Optional[str]:
    t = " " + text.lower().strip() + " "

    # ── what do I need on the final ───────────────────────────────────────────
    if re.search(r"\bfinal\b|\blast (?:exam|test)\b", t) and re.search(r"\bneed\b|\bhave to (?:get|score)\b", t):
        wm = re.search(r"(?:worth|counts for|weighted|is)\s+([0-9]{1,3}(?:\.[0-9]+)?)\s*(?:percent|%)", t)
        cm = re.search(r"(?:i have|i've got|i got|currently|current(?:ly)? (?:at|have)|grade is|sitting at)"
                       r"\s+an?\s*([0-9]{1,3}(?:\.[0-9]+)?)", t)
        tgt = _gr_target_percent(t)
        if wm and cm and tgt:
            weight = float(wm.group(1)) / 100
            current = float(cm.group(1))
            target, target_label = tgt
            if 0 < weight < 1:
                needed = (target - current * (1 - weight)) / weight
                best = current * (1 - weight) + 100 * weight
                worst = current * (1 - weight)
                if needed > 100:
                    return (f"You'd need {_fmt(needed)} percent on the final for {target_label}, "
                            f"which isn't possible. A perfect final leaves you at {_fmt(best)} percent.")
                if needed <= 0:
                    return (f"You already have it. Even a zero on the final leaves you at "
                            f"{_fmt(worst)} percent, above {target_label}.")
                return (f"You need {_fmt(needed)} percent on the final to finish with "
                        f"{target_label}, starting from {_fmt(current)} percent with the "
                        f"final worth {_fmt(weight * 100)} percent.")

    # ── weighted course total ─────────────────────────────────────────────────
    # Excluding every sentence containing "final" was too blunt: a student listing a
    # course says "quizzes 70 worth 10 percent, labs 95 worth 30, final 88 worth 60",
    # and that is exactly this question. Only the needed-on-the-final question is
    # withheld here, and only because the branch above owns it — if that branch has an
    # incomplete sentence it stays silent rather than letting this one answer something
    # adjacent but different.
    if re.search(r"\bworth\b|\bweighted\b|\bcounts for\b", t) and not (
            re.search(r"\bfinal\b", t) and re.search(r"\bneed\b|\bhave to (?:get|score)\b", t)):
        pairs = _gr_pairs(t)
        if len(pairs) >= 2:
            total_w = sum(w for _, w in pairs)
            if total_w > 0:
                score = sum(v * w for v, w in pairs) / total_w
                letter = _gr_letter(score)
                tail = ("" if abs(total_w - 100) < 1e-9 else
                        f" That's out of {_fmt(total_w)} percent of the course so far.")
                return (f"Your weighted grade is {_fmt(score)} percent, "
                        f"{_gr_article(letter.lower())} {letter} on a standard 90/80/70 scale.{tail}")

    # ── gpa from (points, credits) pairs ──────────────────────────────────────
    if re.search(r"\bg\.?p\.?a\b|\bgrade point average\b", t):
        nums = numbers(text)
        if len(nums) >= 4 and len(nums) % 2 == 0:
            pts = nums[0::2]
            cred = nums[1::2]
            if all(0 <= p <= 4.5 for p in pts) and all(c > 0 for c in cred):
                total_c = sum(cred)
                gpa = sum(p * c for p, c in zip(pts, cred)) / total_c
                return (f"That's a {gpa:.2f} GPA over {_fmt(total_c)} credits.")
        if len(nums) == 2 and all(0 <= n <= 4.5 for n in nums):
            return None   # ambiguous — one pair could be anything; stay quiet

    # ── letter for a percent ──────────────────────────────────────────────────
    if re.search(r"\bletter grade\b|\bwhat grade is\b|\bis that an? [a-f]\b", t):
        nums = numbers(text)
        if nums and 0 <= nums[0] <= 100:
            letter = _gr_letter(nums[0])
            return (f"{_fmt(nums[0])} percent is {_gr_article(letter.lower())} {letter} "
                    f"on a standard 90/80/70 scale.")

    # ── score out of total ────────────────────────────────────────────────────
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s+(?:out of|over|of)\s+([0-9]+(?:\.[0-9]+)?)", t)
    if m and re.search(r"\bgrade\b|\bscore\b|\bgot\b|\bpercent\b|\bmissed\b", t):
        got, total = float(m.group(1)), float(m.group(2))
        if total > 0 and got <= total * 1.5:
            pct = got / total * 100
            letter = _gr_letter(pct)
            return (f"{_fmt(got)} out of {_fmt(total)} is {_fmt(pct)} percent, "
                    f"{_gr_article(letter.lower())} {letter} on a standard 90/80/70 scale.")

    return None


if __name__ == "__main__":
    for q in [
        "I have an 87 and the final is worth 20 percent, what do I need to get a 90",
        "I have a 95 and the final is worth 10 percent what do I need to get an a",
        "I have a 40 and the final is worth 20 percent what do I need to get a b",
        "what's my grade if I got 42 out of 50",
        "what letter grade is an 87",
        "homework is 90 worth 20 percent and exams are 84 worth 80 percent",
        "gpa for a 4.0 in 3 credits and a 3.0 in 4 credits",
        "what time is it",
    ]:
        print(f"  {q:70} -> {handle(q)}")
