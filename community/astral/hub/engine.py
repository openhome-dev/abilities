#!/usr/bin/env python3
"""Astral engine — the one router every surface uses.

`answer(text, now)` is the whole contract: a spoken string when Astral is certain, and
None when it isn't, so the agent takes the turn. There is exactly one routing order and
it lives here — the DevKit ability, the cloud Skill and the tests all run this same
function, so a phrase can never resolve one way on the device and another way in the
cloud.

ORDER IS BEHAVIOUR. Specific domains run before general arithmetic, because the
general one will happily match a fragment of a specific question: "2 to the power of 8"
contains the word power, "how many grams in 2 moles" contains a unit. Each module is
responsible for returning None fast when the question isn't its business; moving a
module up this list without re-running the goldens is how a wrong answer ships.
"""
from __future__ import annotations
from typing import Optional
import re
from datetime import datetime                                        # INLINE-STRIP
import mechanical
import calc
import study
import chem
import sci
import stats
import mathx              # INLINE-STRIP

# Specific -> general. Time and date first: they are the cheapest and the most
# unambiguous. calc last: it is the catch-all for plain arithmetic and conversions.
#
# ONE list. There used to be two — a _ROUTE_ORDER tuple of names that domains() and
# the tests read, and a separate hardcoded tuple of functions that actually did the
# routing. Reordering either one left the other still claiming the old order, which
# means the test asserting the route order could pass while the real order had
# changed. A test that can lie about the thing it guards is worse than no test.
# The flag is whether the module takes the clock; only time and date does.
_ROUTE = (
    ("mechanical", mechanical.handle, True),
    ("study", study.handle, False),
    ("chem", chem.handle, False),
    ("sci", sci.handle, False),
    ("stats", stats.handle, False),
    ("mathx", mathx.handle, False),
    ("calc", calc.handle, False),
)


def normalize(text: str) -> str:
    """Clean what speech-to-text actually hands over, not what a test types.

    Whisper punctuates. It returns "What is 20% of 80?" and "What letter grade is an
    87?", and a trailing question mark or a percent sign is enough to stop the number
    patterns matching — so the engine answered both of those on clean text and neither
    of them out loud. The cloud Skill had a normalizer; the device file never did, so
    the two surfaces disagreed on the one input that actually occurs.

    Deliberately gentle. An earlier version of this lowercased everything and stripped
    every non-word character, which would take Ca(OH)2 apart — the chemistry parser
    needs both the capitals and the parentheses. So this only touches the symbols
    speech-to-text substitutes for words, and sentence-final punctuation.
    """
    text = (text or "").replace("%", " percent ").replace("$", " dollars ")
    text = text.replace("°", " degrees ").replace("’", "'")
    text = re.sub(r"[?!,;:]", " ", text)
    text = re.sub(r"\.(?=\s|$)", " ", text)          # sentence dots, not decimal points
    return re.sub(r"\s+", " ", text).strip()


def answer(text: str, now: Optional[datetime] = None) -> Optional[str]:
    if not text or not text.strip():
        return None
    text = normalize(text)
    if not text:
        return None
    for _name, fn, takes_clock in _ROUTE:
        r = fn(text, now) if takes_clock else fn(text)
        if r:
            return r
    return None


def domains() -> tuple:
    """The routing order, read off the thing that actually routes."""
    return tuple(name for name, _fn, _clock in _ROUTE)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(answer(" ".join(sys.argv[1:])) or "(no exact answer — the agent takes it)")
    else:
        for q in ["what time is it", "20 percent of 80", "molar mass of water",
                  "escape velocity of mars", "standard deviation of 4 6 8 10",
                  "42 in binary", "what letter grade is an 87", "tell me a joke"]:
            print(f"  {q:36} -> {answer(q)}")
