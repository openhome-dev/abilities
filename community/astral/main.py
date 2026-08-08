"""Astral - deterministic base capability for OpenHome.

Answers the exact-answer class without the LLM: time, date, math, money, and unit
conversions. The whole engine is inlined below (pattern-and-table code, no model, no
network), so this runs anywhere an agent runs - no DevKit required. Modeled on the
official date-and-time base capability, generalized.

If nothing matches, it speaks nothing and hands the turn back so the agent takes it.
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
import re

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


# ---------------- time / date (mechanical.py, inlined) ----------------

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


# ordered: most specific first. each entry (pattern, handler).
HANDLERS = [
    (re.compile(r"\bwhat day of the (week|month)\b|\bwhat('?s| is) the date\b|"
                r"\btoday'?s date\b|\bwhat('?s| is) today\b|\bthe date\b"), _date),
    (re.compile(r"\bwhat day( of the week)? is it\b|\bwhat('?s| is) the day\b|"
                r"\bwhat day is (it|today)\b"), _day),
    (re.compile(r"\bwhat month\b|\bwhich month\b"), _month),
    (re.compile(r"\bwhat year\b|\bwhich year\b"), _year),
    (re.compile(r"\bmorning or (afternoon|evening|night)\b|\bpart of the day\b"), _partofday),
    (re.compile(r"\bis it (am|pm|a\.m\.|p\.m\.)\b|\bam or pm\b"), _ampm),
    (re.compile(r"\bwhat('?s| is)?( the)? time\b|\bwhat time is it\b|"
                r"\bcurrent time\b|\btime is it\b|\bgot the time\b|\bthe time\b"), _time),
]


def mech_handle(utterance: str, now: datetime | None = None) -> str | None:
    """Return a spoken answer for a mechanical command, or None to fall through."""
    now = now or datetime.now()
    t = " " + utterance.lower().strip() + " "
    for pat, fn in HANDLERS:
        if pat.search(t):
            return fn(now)
    return None

# ── demo: the efficiency contrast ─────────────────────────────────────────────


# ---------------- math / money / conversions (calc.py, inlined) ----------------

# ── number words → value (STT emits words: "twenty five", "one hundred") ──────
_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19, "a": 1, "an": 1}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_SCALE = {"thousand": 1000, "million": 1000000, "billion": 1000000000}


def _int_words(toks: list[str]) -> float:
    total, cur = 0, 0
    for t in toks:
        if t.replace(".", "", 1).isdigit():
            cur += float(t)
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
        v = parse_number(m.group(0).strip())
        if v is not None:
            out.append(v)
    return out


def _fmt(x: float) -> str:
    return str(int(x)) if abs(x - round(x)) < 1e-9 else f"{x:.2f}".rstrip("0").rstrip(".")


# ── unit conversion tables (to a base per dimension) ──────────────────────────
_WEIGHT = {"gram": 1, "grams": 1, "g": 1, "kilogram": 1000, "kilograms": 1000, "kg": 1000,
           "kilo": 1000, "kilos": 1000, "pound": 453.592, "pounds": 453.592, "lb": 453.592,
           "lbs": 453.592, "ounce": 28.3495, "ounces": 28.3495, "oz": 28.3495,
           "ton": 1e6, "tons": 1e6, "stone": 6350.29}
_LENGTH = {"meter": 1, "meters": 1, "metre": 1, "m": 1, "centimeter": 0.01, "centimeters": 0.01,
           "cm": 0.01, "millimeter": 0.001, "mm": 0.001, "kilometer": 1000, "kilometers": 1000,
           "km": 1000, "inch": 0.0254, "inches": 0.0254, "foot": 0.3048, "feet": 0.3048,
           "yard": 0.9144, "yards": 0.9144, "mile": 1609.34, "miles": 1609.34}
_VOLUME = {"liter": 1, "liters": 1, "litre": 1, "l": 1, "milliliter": 0.001, "ml": 0.001,
           "cup": 0.236588, "cups": 0.236588, "gallon": 3.78541, "gallons": 3.78541,
           "quart": 0.946353, "pint": 0.473176, "tablespoon": 0.0147868, "teaspoon": 0.00492892}
_DIMS = {"weight": _WEIGHT, "length": _LENGTH, "volume": _VOLUME}


def _find_units(text: str):
    """(dim, unit, position) for every unit word, so we can order by the sentence."""
    found = []
    for dim, table in _DIMS.items():
        for u in table:
            m = re.search(r"\b" + re.escape(u) + r"\b", text)
            if m:
                found.append((dim, u, m.start()))
    return found


def _convert(text: str, nums):
    if not nums:
        return None
    v = nums[0]
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
            return f"{_fmt(v)} {src[1]} is {_fmt(base / _DIMS[dim][tgt[1]])} {tgt[1]}."
    return None

# ── main ──────────────────────────────────────────────────────────────────────


def vocabulary() -> set:
    """All words calc understands — added to the ASR grammar so math commands transcribe."""
    words = set()
    for tbl in (_WEIGHT, _LENGTH, _VOLUME):
        words.update(tbl.keys())
    words.update(_ONES)
    words.update(_TENS)
    words.update(_SCALE)
    words.update("plus minus times divided by multiply subtract add over percent of half "
                 "double twice squared square root tip tax split between among people "
                 "fahrenheit celsius centigrade degrees dollars cents point convert how "
                 "many in to and total less".split())
    return {w for w in words if w.isascii()}


def calc_handle(text: str) -> str | None:
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

# ============================ Astral capability ============================


def _normalize(msg: str) -> str:
    """The agent's transcript can carry punctuation the parsers choke on ("155?", "20%").
    Flatten to bare words and digits, keep apostrophes."""
    msg = (msg or "").strip().lower()
    msg = msg.replace("%", " percent ").replace("$", " dollars ").replace("\u00b0", " degrees ")
    msg = re.sub(r"[^\w\s']", " ", msg)
    return re.sub(r"\s+", " ", msg).strip()


class AstralCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            msg = _normalize(await self.capability_worker.wait_for_complete_transcription())
            if not msg:
                return
            tz = self.capability_worker.get_timezone()
            now = datetime.now(ZoneInfo(tz)) if tz else datetime.now()

            answer = mech_handle(msg, now)          # time / date, in the agent's timezone
            if answer is None:
                answer = calc_handle(msg)           # math / money / conversions
            if answer:
                await self.capability_worker.speak(answer)
            # else: not an exact-answer question -> stay quiet, the agent takes it
        except Exception as error:
            self.worker.editor_logging_handler.error(f"Astral failed: {error}")
        finally:
            self.capability_worker.resume_normal_flow()
