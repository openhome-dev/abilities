#!/usr/bin/env python3
"""Astral calc — deterministic math, money, and unit conversion. No LLM, no cloud, µs.

Handles the everyday-convenience commands that should never round-trip to a model:
  • arithmetic     "what's fifteen plus twenty seven", "12 times 8", "half of 90"
  • percentages    "20 percent of 80", "what's 15 percent of 200"
  • money          "18 percent tip on 45 dollars", "split 120 between 4",
                   "8.5 percent tax on 60"
  • conversions    "convert 5 pounds to kilograms", "how many cups in 2 liters",
                   "6 feet in meters", "70 fahrenheit to celsius"

handle(text) -> spoken string, or None to fall through to the normal path.
All parsing is pattern + table based (no eval) so it is safe on voice input.
"""
from __future__ import annotations
from typing import Optional
import re

# ── number words → value (STT emits words: "twenty five", "one hundred") ──────
_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19, "a": 1, "an": 1}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_SCALE = {"thousand": 1000, "million": 1000000, "billion": 1000000000}


def _int_words(toks: list[str]) -> float:
    # "a"/"an" is only the number one when nothing else in the run is a number.
    # "a mile" is 1 mile, but "a 15 percent tip" is 15, not 16, and "an 87" is 87,
    # not 88. Counting the article unconditionally made every article-plus-digit
    # phrase answer one too high — a spoken-wrong answer, which is the one thing
    # this engine exists to make impossible.
    real = any(t.replace(".", "", 1).isdigit() or t in _TENS or t == "hundred"
               or t in _SCALE or (t in _ONES and t not in ("a", "an"))
               for t in toks)
    total, cur = 0, 0
    for t in toks:
        if t.replace(".", "", 1).isdigit():
            cur += float(t)
        elif t in ("a", "an"):
            cur += 0 if real else 1
        elif t in _ONES:
            cur += _ONES[t]
        elif t in _TENS:
            cur += _TENS[t]
        elif t == "hundred":
            cur = (cur or 1) * 100
        elif t in _SCALE:
            total += (cur or 1) * _SCALE[t]
            cur = 0
        # ignore "and"
    return total + cur


def parse_number(s: str):
    s = s.strip().lower().replace("-", " ")
    try:
        return float(s)
    except ValueError:
        pass
    if "point" in s:
        whole, frac = s.split("point", 1)
        w = _int_words(whole.split()) if whole.strip() else 0
        digits = "".join(str(int(_ONES[t])) for t in frac.split() if t in _ONES)
        return float(f"{w}.{digits}") if digits else w
    toks = [t for t in s.split() if t in _ONES or t in _TENS or t == "hundred"
            or t in _SCALE or t.replace(".", "", 1).isdigit()]
    return _int_words(toks) if toks else None


_NUMRUN = re.compile(r"((?:\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
                     r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
                     r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
                     r"point|and|a|an)\b|\d+(?:\.\d+)?)(?:\s+|$))+")


def numbers(text: str) -> list[float]:
    out = []
    for m in _NUMRUN.finditer(text.lower()):
        run = m.group(0).strip()
        # A run that is nothing but an article is not a number. "a photon" was
        # yielding 1 and shifting every positional formula by one argument; the
        # legitimate "how many feet in a mile" case is handled by _convert, which
        # assumes a quantity of one when no number is spoken at all.
        if all(w in ("a", "an", "and") for w in run.split()):
            continue
        v = parse_number(run)
        if v is not None:
            out.append(v)
    return out


def _fmt(x: float) -> str:
    # round(), not int(). int() truncates, so a float that lands a hair BELOW an
    # integer — 101.99999999999996 out of any ordinary division — printed as 101
    # while the guard above had already decided it was an integer. Off by one, out
    # loud, with full confidence.
    # "close enough to an integer" is also true of every number smaller than the
    # tolerance, so 1e-10 was being called an integer and printed as 0 — the same
    # say-zero-about-a-non-zero-number bug as below, one branch earlier. A genuinely
    # tiny value is not an integer; it falls through to the spoken form.
    if abs(x - round(x)) < 1e-9 and not (x and abs(x) < 1e-9):
        return str(int(round(x)))
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    # Two decimals turn every non-zero value under 0.005 into "0", so "how many atoms
    # in 0.000001 moles" answered "0 moles is ...". Saying zero about something that
    # is not zero is the failure this engine exists to prevent, even in an echo.
    if s in ("0", "-0"):
        # Said, not printed: "1e-06" is read aloud as gibberish. Same phrasing as
        # _fmt_spoken uses at the other end of the scale.
        g = f"{x:.4g}"
        return g.replace("e-0", " times ten to the minus ").replace(
            "e-", " times ten to the minus ") if "e" in g else g
    return s


def _fmt_spoken(x: float) -> str:
    """Same number, said out loud. 9460730472580.8 is not an answer anyone can hear,
    so anything past a million becomes '9.46 trillion' and anything under a millionth
    keeps its significant digits instead of collapsing to '0'."""
    a = abs(x)
    if a >= 1e15:
        return f"{x/1e15:.2f}".rstrip("0").rstrip(".") + " quadrillion"
    if a >= 1e12:
        return f"{x/1e12:.2f}".rstrip("0").rstrip(".") + " trillion"
    if a >= 1e9:
        return f"{x/1e9:.2f}".rstrip("0").rstrip(".") + " billion"
    if a >= 1e6:
        return f"{x/1e6:.2f}".rstrip("0").rstrip(".") + " million"
    if a and a < 0.001:
        return f"{x:.4g}".replace("e-0", " times ten to the minus ").replace("e-", " times ten to the minus ")
    return _fmt(x)


_ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def _to_roman(n: int) -> str:
    out = ""
    for v, s in _ROMAN:
        while n >= v:
            out += s
            n -= v
    return out


# ── unit conversion tables (to a base per dimension) ──────────────────────────
# Factors are the exact defined values, not rounded ones. A truncated constant is a
# wrong answer with extra steps: mile = 1609.34 answered "a mile is 5279.99 feet".
_WEIGHT = {"gram": 1, "grams": 1, "g": 1, "kilogram": 1000, "kilograms": 1000, "kg": 1000,
           "kilo": 1000, "kilos": 1000, "milligram": 0.001, "milligrams": 0.001, "mg": 0.001,
           "pound": 453.59237, "pounds": 453.59237, "lb": 453.59237,
           "lbs": 453.59237, "ounce": 28.349523125, "ounces": 28.349523125, "oz": 28.349523125,
           # "ton" from an American voice is the short ton; the metric one has its own
           # names. Collapsing them into one number was a factor-of-1.1 error waiting.
           "ton": 907184.74, "tons": 907184.74, "short ton": 907184.74, "short tons": 907184.74,
           "tonne": 1e6, "tonnes": 1e6, "metric ton": 1e6, "metric tons": 1e6,
           "stone": 6350.29318, "amu": 1.66053906660e-24}
_LENGTH = {"meter": 1, "meters": 1, "metre": 1, "m": 1, "centimeter": 0.01, "centimeters": 0.01,
           "cm": 0.01, "millimeter": 0.001, "mm": 0.001, "micrometer": 1e-6, "micron": 1e-6,
           "nanometer": 1e-9, "nanometers": 1e-9, "nm": 1e-9,
           "kilometer": 1000, "kilometers": 1000,
           "km": 1000, "inch": 0.0254, "inches": 0.0254, "foot": 0.3048, "feet": 0.3048,
           "yard": 0.9144, "yards": 0.9144, "mile": 1609.344, "miles": 1609.344,
           "nautical mile": 1852, "nautical miles": 1852,
           # astronomical distances — exact IAU definitions
           "light year": 9.4607304725808e15, "light years": 9.4607304725808e15,
           "lightyear": 9.4607304725808e15, "lightyears": 9.4607304725808e15,
           "parsec": 3.0856775814913673e16, "parsecs": 3.0856775814913673e16,
           "astronomical unit": 1.495978707e11, "astronomical units": 1.495978707e11}
_VOLUME = {"liter": 1, "liters": 1, "litre": 1, "l": 1, "milliliter": 0.001, "milliliters": 0.001,
           "ml": 0.001, "cup": 0.2365882365, "cups": 0.2365882365,
           "gallon": 3.785411784, "gallons": 3.785411784,
           "quart": 0.946352946, "quarts": 0.946352946, "pint": 0.473176473,
           "pints": 0.473176473, "tablespoon": 0.01478676478125,
           "tablespoons": 0.01478676478125, "teaspoon": 0.00492892159375,
           "teaspoons": 0.00492892159375, "cubic meter": 1000, "cubic meters": 1000}
# base = meters per second
_SPEED = {"mph": 0.44704, "kph": 1 / 3.6, "kmh": 1 / 3.6, "knot": 1852 / 3600, "knots": 1852 / 3600,
          "mps": 1, "meters per second": 1, "feet per second": 0.3048,
          "miles per hour": 0.44704, "kilometers per hour": 1 / 3.6}
# base = square meters
_AREA = {"square meter": 1, "square meters": 1, "sqm": 1, "square foot": 0.09290304,
         "square feet": 0.09290304, "sqft": 0.09290304, "acre": 4046.8564224,
         "acres": 4046.8564224, "square inch": 0.00064516, "square inches": 0.00064516,
         "hectare": 10000, "hectares": 10000, "square kilometer": 1e6, "square kilometers": 1e6,
         "square mile": 2589988.110336, "square miles": 2589988.110336}
# base = seconds (time DURATION units, not the clock — those are mechanical.py)
_TIME = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60, "hour": 3600, "hours": 3600,
         "day": 86400, "days": 86400, "week": 604800, "weeks": 604800,
         "year": 31557600, "years": 31557600, "millisecond": 0.001, "milliseconds": 0.001}
# base = joules
_ENERGY = {"joule": 1, "joules": 1, "kilojoule": 1000, "kilojoules": 1000, "kj": 1000,
           "calorie": 4.184, "calories": 4.184, "kilocalorie": 4184, "kilocalories": 4184,
           "food calorie": 4184, "food calories": 4184,
           "watt hour": 3600, "watt hours": 3600, "kilowatt hour": 3.6e6,
           "kilowatt hours": 3.6e6, "electron volt": 1.602176634e-19,
           "electron volts": 1.602176634e-19, "btu": 1055.05585262}
# base = pascals
_PRESSURE = {"pascal": 1, "pascals": 1, "kilopascal": 1000, "kilopascals": 1000, "kpa": 1000,
             "bar": 100000, "bars": 100000, "atmosphere": 101325, "atmospheres": 101325,
             "atm": 101325, "psi": 6894.757293168, "torr": 133.32236842105263,
             "millimeters of mercury": 133.32236842105263}
# base = newtons
_FORCE = {"newton": 1, "newtons": 1, "kilonewton": 1000, "kilonewtons": 1000,
          "pound force": 4.4482216152605, "pounds force": 4.4482216152605, "dyne": 1e-5}
# base = bytes (binary multiples — the convention every CS course teaches)
_DATA = {"byte": 1, "bytes": 1, "bit": 0.125, "bits": 0.125, "kilobyte": 1024, "kilobytes": 1024,
         "kb": 1024, "megabyte": 1048576, "megabytes": 1048576, "mb": 1048576,
         "gigabyte": 1073741824, "gigabytes": 1073741824, "gb": 1073741824,
         "terabyte": 1099511627776, "terabytes": 1099511627776, "tb": 1099511627776,
         "megabit": 131072, "megabits": 131072, "gigabit": 134217728, "gigabits": 134217728}
# Order matters: a compound unit contains a simple one, so the compound dimension has
# to win the match. "square meter" contains "meter" (area before length), "meters per
# second" contains "meters" (speed before length), "kilowatt hour" contains "hour"
# (energy before time), "millimeters of mercury" contains "millimeters" (pressure
# before length). Reordering this dict silently changes answers — add new dimensions
# above the simple ones they can shadow, and add a golden line for the collision.
_DIMS = {"area": _AREA, "energy": _ENERGY, "speed": _SPEED, "pressure": _PRESSURE,
         "force": _FORCE, "data": _DATA, "weight": _WEIGHT, "length": _LENGTH,
         "volume": _VOLUME, "time": _TIME}

# One compiled alternation per dimension instead of one regex per unit. The old
# version ran ~250 separate re.search calls on every sentence — more than the re
# module's pattern cache holds — which measured 1.7 ms per conversion on the Pi.
# Longest-first also fixes a real shadowing bug: "nautical mile" used to match both
# "nautical mile" AND "mile" at overlapping positions, and _convert picks by distance
# to the number, so the wrong one could win and answer a statute-mile conversion.
_DIM_RE = {dim: re.compile(r"\b(" + "|".join(re.escape(u) for u in
                                             sorted(table, key=len, reverse=True)) + r")\b")
           for dim, table in _DIMS.items()}


def _find_units(text: str):
    """(dim, unit, position) for every unit word, so we can order by the sentence."""
    found = []
    for dim, pattern in _DIM_RE.items():
        seen = set()
        for m in pattern.finditer(text):
            if m.group(1) not in seen:          # first occurrence of each unit, as before
                seen.add(m.group(1))
                found.append((dim, m.group(1), m.start()))
    return found


def _convert(text: str, nums):
    # "how many feet in a mile" names no quantity — the question is about one of them.
    # Only an explicit asking shape gets that default, so merely mentioning two units
    # in passing doesn't make Astral volunteer a conversion nobody requested.
    if nums:
        v = nums[0]
    elif re.search(r"\bhow many\b|\bconvert\b|\bin (?:a|an|one)\b", text):
        v = 1
    else:
        return None
    nm = _NUMRUN.search(text)
    npos = nm.start() if nm else 0                    # source = the unit nearest the number

    # temperature (non-linear) — direction from which unit sits by the number
    f = re.search(r"\bfahrenheit\b", text)
    c = re.search(r"\b(?:celsius|centigrade)\b", text)
    if f and c:
        return (f"{_fmt(v)} degrees Fahrenheit is {_fmt((v-32)*5/9)} degrees Celsius."
                if abs(f.start() - npos) <= abs(c.start() - npos) else
                f"{_fmt(v)} degrees Celsius is {_fmt(v*9/5+32)} degrees Fahrenheit.")

    units = _find_units(text)
    for dim in _DIMS:
        du = [u for u in units if u[0] == dim]
        if len(du) >= 2:
            du.sort(key=lambda x: abs(x[2] - npos))   # nearest number = source
            src, tgt = du[0], du[1]
            base = v * _DIMS[dim][src[1]]
            return f"{_fmt(v)} {src[1]} is {_fmt_spoken(base / _DIMS[dim][tgt[1]])} {tgt[1]}."
    return None

# ── main ──────────────────────────────────────────────────────────────────────


def handle(text: str) -> Optional[str]:
    t = " " + text.lower().strip() + " "
    nums = numbers(text)

    # conversions first (they contain unit words)
    conv = _convert(t, nums)
    if conv:
        return conv

    # money: tip
    if "tip" in t and nums:
        amount = max(nums)
        pct = next((n for n in nums if n != amount and n <= 100), 18)
        tip = amount * pct / 100
        return (f"A tip of {_fmt(pct)} percent on {_fmt(amount)} dollars is "
                f"{_fmt(tip)} dollars, for a total of {_fmt(amount + tip)}.")
    # money: tax
    if "tax" in t and len(nums) >= 2:
        pct, amount = min(nums), max(nums)
        tax = amount * pct / 100
        return (f"{_fmt(pct)} percent tax on {_fmt(amount)} is {_fmt(tax)} dollars, "
                f"total {_fmt(amount + tax)}.")
    # money: split
    if ("split" in t or "divide" in t) and ("between" in t or "among" in t or "people" in t) and len(nums) >= 2:
        amount, people = max(nums), min(nums)
        if people:
            return f"{_fmt(amount)} split between {_fmt(people)} is {_fmt(amount/people)} dollars each."

    # percentage: "P percent of X"
    m = re.search(r"([0-9.]+|\w[\w ]*?)\s+percent of\s+([0-9.]+|\w[\w ]*)", t)
    if m:
        p, x = parse_number(m.group(1)), parse_number(m.group(2))
        if p is not None and x is not None:
            return f"{_fmt(p)} percent of {_fmt(x)} is {_fmt(x*p/100)}."

    # half / quarter / double of X
    if "half of" in t and nums:
        return f"Half of {_fmt(nums[0])} is {_fmt(nums[0]/2)}."
    if ("double" in t or "twice" in t) and nums:
        return f"Double {_fmt(nums[0])} is {_fmt(nums[0]*2)}."

    # square root / squared
    if "square root of" in t and nums:
        return f"The square root of {_fmt(nums[0])} is {_fmt(nums[0] ** 0.5)}."
    if ("squared" in t) and nums:
        return f"{_fmt(nums[0])} squared is {_fmt(nums[0] ** 2)}."
    if "cubed" in t and nums:
        return f"{_fmt(nums[0])} cubed is {_fmt(nums[0] ** 3)}."
    if "cube root of" in t and nums:
        return f"The cube root of {_fmt(nums[0])} is {_fmt(round(nums[0] ** (1 / 3), 4))}."
    if "to the power" in t and len(nums) >= 2:
        return f"{_fmt(nums[0])} to the power of {_fmt(nums[1])} is {_fmt(nums[0] ** nums[1])}."
    if "factorial" in t and nums:
        n = int(nums[0])
        if 0 <= n <= 20:
            f = 1
            for i in range(2, n + 1):
                f *= i
            return f"{n} factorial is {_fmt(f)}."
    if "roman numeral" in t and nums:
        n = int(nums[0])
        if 0 < n < 4000:
            return f"{_fmt(n)} in roman numerals is {_to_roman(n)}."

    # arithmetic: A <op> B
    if len(nums) >= 2:
        a, b = nums[0], nums[1]
        if re.search(r"\bplus\b|\badd\b|\band\b", t) and not any(w in t for w in ("percent", "tip", "tax", "split")):
            if "plus" in t or "add" in t:
                return f"{_fmt(a)} plus {_fmt(b)} is {_fmt(a+b)}."
        if re.search(r"\bminus\b|\bsubtract\b|\bless\b|\btake away\b", t):
            return f"{_fmt(a)} minus {_fmt(b)} is {_fmt(a-b)}."
        if re.search(r"\btimes\b|\bmultiplied\b|\bmultiply\b", t) or re.search(r"\bx\b", t):
            return f"{_fmt(a)} times {_fmt(b)} is {_fmt(a*b)}."
        if re.search(r"\bdivided by\b|\bdivide\b|\bover\b", t):
            if b:
                return f"{_fmt(a)} divided by {_fmt(b)} is {_fmt(a/b)}."
    return None


if __name__ == "__main__":
    tests = [
        "what's fifteen plus twenty seven", "12 times 8", "100 divided by 4",
        "20 percent of 80", "what is 15 percent of 200", "half of 90",
        "18 percent tip on 45 dollars", "split 120 between 4 people",
        "8.5 percent tax on 60", "convert 5 pounds to kilograms",
        "how many cups in 2 liters", "6 feet in meters",
        "70 fahrenheit to celsius", "square root of 144", "nine squared",
        "what time is it",  # falls through
    ]
    for q in tests:
        print(f"  {q:42} -> {handle(q)}")
