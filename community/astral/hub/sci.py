#!/usr/bin/env python3
"""Astral sci — deterministic physics and astronomy. No LLM, no cloud, µs.

Closed-form formulas over a table of measured constants. Every answer here is the
same arithmetic a student does by hand, so it is either exactly right or it doesn't
answer at all. Nothing is recalled from a model, which is the point: an LLM asked for
the escape velocity of Mars produces a number that is usually close and occasionally
invented. This produces sqrt(2GM/R) and says which body it used.

  • bodies      "escape velocity of mars", "surface gravity of the moon",
                "how much would I weigh on mars at 180 pounds"
  • motion      "how far does something fall in 3 seconds",
                "how fast after falling for 3 seconds"
  • mechanics   "kinetic energy of 5 kilograms at 10 meters per second",
                "momentum of 5 kilograms at 3 meters per second",
                "force of 10 kilograms at 2 meters per second squared",
                "work done by 20 newtons over 5 meters", "power of 100 joules in 5 seconds"
  • circuits    "voltage across 5 ohms with 2 amps"
  • relativity  "time dilation at 0.9 c", "schwarzschild radius of the sun"
  • light       "how long does light take to reach earth from the sun",
                "energy of a photon at 500 nanometers"

handle(text) -> spoken string, or None to fall through.
"""
from __future__ import annotations
from typing import Optional
import re
import math
from calc import numbers, _fmt, _fmt_spoken, _LENGTH   # INLINE-STRIP

# ── measured constants (CODATA / IAU) ─────────────────────────────────────────
_SCI_G = 6.67430e-11        # gravitational constant, m^3 kg^-1 s^-2
_SCI_C = 299792458.0        # speed of light, m/s (exact)
_SCI_G0 = 9.80665            # standard gravity, m/s^2 (exact)
_SCI_H = 6.62607015e-34     # Planck, J s (exact)
_SCI_MSUN = 1.98847e30         # solar mass, kg
_SCI_LY = _LENGTH["light year"]   # one definition, shared with the unit table
_SCI_MPS_TO_MPH = 2.2369362920544    # m/s -> mph, exact from the mile definition

# body -> (mass kg, EQUATORIAL radius m, mean distance from Earth m or None)
#
# Equatorial, not volumetric-mean. This is not a detail: a gas giant is visibly
# oblate, and GM/R^2 with Jupiter's mean radius (69,911 km) gives 25.92 m/s^2 while
# every reference table a student will check says 24.79 — the value at the equatorial
# radius (71,492 km). Same for Saturn, 11.19 against a published 10.44. Using mean
# radii made this engine confidently disagree with the textbook on two headline
# numbers. With equatorial radii, every body agrees with the published surface gravity
# and escape velocity to better than half a percent, and test_hardening.py asserts it.
_SCI_BODY = {
    "sun": (1.98847e30, 6.957e8, 1.495978707e11),
    "mercury": (3.3011e23, 2.4405e6, 9.17e10),
    "venus": (4.8675e24, 6.0518e6, 4.14e10),
    "earth": (5.97217e24, 6.378137e6, None),
    "moon": (7.342e22, 1.7381e6, 3.844e8),
    "mars": (6.4171e23, 3.3962e6, 7.83e10),
    "jupiter": (1.8982e27, 7.1492e7, 6.288e11),
    "saturn": (5.6834e26, 6.0268e7, 1.275e12),
    "uranus": (8.6810e25, 2.5559e7, 2.723e12),
    "neptune": (1.02413e26, 2.4764e7, 4.351e12),
    "pluto": (1.303e22, 1.1883e6, 5.75e12),
}
_SCI_M_TO_MI = 1 / 1609.344   # exact: 1 mile = 1609.344 m
_SCI_ALIAS = {"the sun": "sun", "the moon": "moon", "the earth": "earth"}

# Things light travels to, in metres. The solar-system distances are READ OFF the
# body table rather than restated here: writing 3.844e8 twice is one edit away from
# the Moon being two different distances depending on which question you asked.
_SCI_LIGHT_TARGET = {name: dist for name, (_m, _r, dist) in _SCI_BODY.items() if dist}
_SCI_LIGHT_TARGET.update({"the " + n: _SCI_LIGHT_TARGET[n] for n in ("sun", "moon")})
_SCI_LIGHT_TARGET.update({          # beyond the solar system, so not in the body table
    "alpha centauri": 4.1315e16, "proxima centauri": 3.996e16,
    "sirius": 8.14e16, "the andromeda galaxy": 2.4e22, "andromeda": 2.4e22,
    "the galactic center": 2.5e20, "the center of the galaxy": 2.5e20,
})


def _sci_body(t: str):
    for phrase, name in _SCI_ALIAS.items():
        if re.search(r"\b" + phrase + r"\b", t):
            return name
    for name in _SCI_BODY:
        if re.search(r"\b" + name + r"\b", t):
            return name
    return None


def _sci_said(body: str) -> str:
    """The Sun and the Moon take an article; the planets don't."""
    return "the " + body.title() if body in ("sun", "moon") else body.title()


def _sci_far(metres: float) -> str:
    """Distance said usefully: kilometers up close, light years once that stops
    meaning anything to a human ear."""
    if metres >= 1e15:
        return f"{_fmt_spoken(metres/_SCI_LY)} light years"
    return f"{_fmt_spoken(metres/1000)} kilometers"


def _sci_secs(seconds: float) -> str:
    """Seconds said the way a person would say them."""
    if seconds < 1e-6:
        return f"{seconds*1e9:.2f}".rstrip("0").rstrip(".") + " nanoseconds"
    if seconds < 1e-3:
        return f"{seconds*1e6:.2f}".rstrip("0").rstrip(".") + " microseconds"
    if seconds < 1:
        return f"{seconds*1e3:.2f}".rstrip("0").rstrip(".") + " milliseconds"
    if seconds < 90:
        return _fmt(seconds) + (" second" if abs(seconds - 1) < 1e-9 else " seconds")
    if seconds < 5400:
        return _fmt(seconds / 60) + " minutes"
    if seconds < 172800:
        return _fmt(seconds / 3600) + " hours"
    if seconds < 3.156e7:
        return _fmt(seconds / 86400) + " days"
    return _fmt_spoken(seconds / 3.15576e7) + " years"


def handle(text: str) -> Optional[str]:
    t = " " + text.lower().strip() + " "
    nums = numbers(text)
    body = _sci_body(t)

    # ── mass and size (reviewer, 2026-09-01: the most common planet questions,
    #    and the table already holds mass and equatorial radius for every body) ──
    if body and re.search(r"\bmass of\b|\bhow massive\b|\bhow heavy is\b|\bhow much does .* weigh\b", t) \
            and not nums and "molar" not in t and "atomic" not in t:
        m, _, _ = _SCI_BODY[body]
        unit = "kilograms"
        if "pound" in t:                       # exact: 1 lb = 0.45359237 kg
            m, unit = m / 0.45359237, "pounds"
        exp = int(math.floor(math.log10(m)))
        mant = m / 10 ** exp
        return (f"The mass of {_sci_said(body)} is about {_fmt(mant)} times ten to the "
                f"{exp} {unit}.")
    if body and re.search(r"\bdiameter of\b|\bradius of\b|\bhow big is\b|\bhow wide is\b|\bhow large is\b", t) \
            and "schwarzschild" not in t and "event horizon" not in t:
        _, r, _ = _SCI_BODY[body]
        if "radius" in t:
            return (f"The radius of {_sci_said(body)} is {_fmt(r/1000)} kilometers, "
                    f"{_fmt(r*_SCI_M_TO_MI)} miles.")
        return (f"The diameter of {_sci_said(body)} is {_fmt(2*r/1000)} kilometers, "
                f"{_fmt(2*r*_SCI_M_TO_MI)} miles.")

    # ── escape velocity ───────────────────────────────────────────────────────
    if "escape velocity" in t:
        if body:
            m, r, _ = _SCI_BODY[body]
            v = math.sqrt(2 * _SCI_G * m / r)
            return (f"Escape velocity at {_sci_said(body)} is {_fmt(v/1000)} kilometers per second, "
                    f"{_fmt(v*_SCI_MPS_TO_MPH)} miles per hour.")
        return None

    # ── surface gravity ───────────────────────────────────────────────────────
    if re.search(r"\bsurface gravity\b|\bgravity (?:on|at|of)\b", t) and body:
        m, r, _ = _SCI_BODY[body]
        g = _SCI_G * m / (r * r)
        return (f"Surface gravity on {_sci_said(body)} is {_fmt(g)} meters per second squared, "
                f"{_fmt(g/_SCI_G0)} times Earth's.")

    # ── weight on another world ───────────────────────────────────────────────
    if re.search(r"\bweigh\b|\bweight\b", t) and body and body != "earth" and nums:
        m, r, _ = _SCI_BODY[body]
        ratio = (_SCI_G * m / (r * r)) / _SCI_G0
        unit = "pounds" if re.search(r"\bpounds?\b|\blbs?\b", t) else \
               "kilograms" if re.search(r"\bkilograms?\b|\bkg\b", t) else "units"
        return (f"{_fmt(nums[0])} {unit} on Earth is {_fmt(nums[0]*ratio)} {unit} on "
                f"{_sci_said(body)}, at {_fmt(ratio)} times Earth's gravity.")

    # ── Schwarzschild radius ──────────────────────────────────────────────────
    if re.search(r"\bschwarzschild\b|\bevent horizon\b", t):
        mass = None
        if re.search(r"\bsolar mass(?:es)?\b", t) and nums:
            mass, label = nums[0] * _SCI_MSUN, f"{_fmt(nums[0])} solar masses"
        elif body:
            mass, label = _SCI_BODY[body][0], _sci_said(body)
        elif nums and re.search(r"\bkilograms?\b|\bkg\b", t):
            mass, label = nums[0], f"{_fmt(nums[0])} kilograms"
        if mass:
            rs = 2 * _SCI_G * mass / (_SCI_C ** 2)
            said = (f"{_fmt(rs/1000)} kilometers" if rs >= 1000 else
                    f"{_fmt(rs)} meters" if rs >= 0.01 else
                    f"{_fmt_spoken(rs)} meters")
            return f"The Schwarzschild radius of {label} is {said}."

    # ── light travel time ─────────────────────────────────────────────────────
    if re.search(r"\blight\b", t) and re.search(r"\btake\b|\btravel\b|\breach\b|\bget (?:to|from)\b", t):
        for name, dist in sorted(_SCI_LIGHT_TARGET.items(), key=lambda kv: -len(kv[0])):
            if re.search(r"\b" + re.escape(name) + r"\b", t):
                said = name if name.startswith("the ") else \
                    ("the " + name if name in ("sun", "moon") else name)
                return (f"Light takes {_sci_secs(dist / _SCI_C)} to cross the "
                        f"{_sci_far(dist)} to {said}.")
        return None

    # ── free fall ─────────────────────────────────────────────────────────────
    if re.search(r"\bfall(?:s|ing)?\b|\bdropped?\b", t) and nums:
        secs = nums[0]
        if re.search(r"\bhow fast\b|\bvelocity\b|\bspeed\b", t):
            v = _SCI_G0 * secs
            return (f"After falling {_fmt(secs)} seconds it's going {_fmt(v)} meters per second, "
                    f"{_fmt(v*_SCI_MPS_TO_MPH)} miles per hour, ignoring air resistance.")
        if re.search(r"\bhow far\b|\bdistance\b|\bfall\b", t):
            d = 0.5 * _SCI_G0 * secs * secs
            return (f"In {_fmt(secs)} seconds it falls {_fmt(d)} meters, "
                    f"{_fmt(d/0.3048)} feet, ignoring air resistance.")

    # ── kinetic / potential energy ────────────────────────────────────────────
    if "kinetic energy" in t and len(nums) >= 2:
        m, v = nums[0], nums[1]
        return f"The kinetic energy is {_fmt_spoken(0.5*m*v*v)} joules, from one half m v squared."
    if re.search(r"\bpotential energy\b", t) and len(nums) >= 2:
        m, h = nums[0], nums[1]
        return f"The potential energy is {_fmt_spoken(m*_SCI_G0*h)} joules, from m g h."

    # ── momentum / force / work / power ───────────────────────────────────────
    if "momentum" in t and len(nums) >= 2:
        return (f"The momentum is {_fmt_spoken(nums[0]*nums[1])} kilogram meters per second, "
                f"from m v.")
    if (re.search(r"\bforce\b", t) and len(nums) >= 2 and not re.search(r"\bpounds? force\b", t)
            and re.search(r"\bnewtons?\b|\bkilograms?\b|\bacceleration\b|\bmeters per second squared\b", t)):
        return f"The force is {_fmt_spoken(nums[0]*nums[1])} newtons, from m a."
    if re.search(r"\bwork\b", t) and len(nums) >= 2 and re.search(r"\bnewtons?\b|\bjoules?\b", t):
        return f"The work done is {_fmt_spoken(nums[0]*nums[1])} joules, from force times distance."
    # "2 to the power of 8" also contains the word power; without the unit guard this
    # branch answered "0.25 watts" and stole an existing golden.
    if (re.search(r"\bpower\b", t) and len(nums) >= 2 and nums[1]
            and re.search(r"\bjoules?\b|\bwatts?\b", t) and "to the power" not in t):
        return f"The power is {_fmt_spoken(nums[0]/nums[1])} watts, from joules per second."

    # ── Ohm's law ─────────────────────────────────────────────────────────────
    if re.search(r"\bohms?\b|\bamp(?:ere)?s?\b|\bvolts?\b", t) and len(nums) >= 2:
        has_ohm = re.search(r"\bohms?\b", t)
        has_amp = re.search(r"\bamp(?:ere)?s?\b", t)
        has_volt = re.search(r"\bvolts?\b", t)
        a, b = nums[0], nums[1]
        if has_ohm and has_amp and not has_volt:
            ohms = a if has_ohm.start() < has_amp.start() else b
            amps = b if has_ohm.start() < has_amp.start() else a
            return f"That's {_fmt(ohms*amps)} volts, from V equals I R."
        if has_volt and has_ohm and not has_amp:
            volts = a if has_volt.start() < has_ohm.start() else b
            ohms = b if has_volt.start() < has_ohm.start() else a
            if ohms:
                return f"That's {_fmt(volts/ohms)} amps, from I equals V over R."
        if has_volt and has_amp and not has_ohm:
            volts = a if has_volt.start() < has_amp.start() else b
            amps = b if has_volt.start() < has_amp.start() else a
            if amps:
                return f"That's {_fmt(volts/amps)} ohms, from R equals V over I."

    # ── time dilation ─────────────────────────────────────────────────────────
    if re.search(r"\btime dilation\b|\blorentz factor\b|\bgamma at\b", t) and nums:
        frac = nums[0] / 100 if nums[0] > 1 and "percent" in t else nums[0]
        if 0 <= frac < 1:
            gamma = 1 / math.sqrt(1 - frac * frac)
            return (f"At {_fmt(frac)} times the speed of light the Lorentz factor is "
                    f"{_fmt(gamma)}, so moving clocks run {_fmt(gamma)} times slower.")

    # ── photon energy ─────────────────────────────────────────────────────────
    if re.search(r"\bphoton\b", t) and nums:
        nm = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:nanometers?|nm)\b", t)
        if nm:
            lam = float(nm.group(1)) * 1e-9
            e = _SCI_H * _SCI_C / lam
            return (f"A {_fmt(float(nm.group(1)))} nanometer photon carries {_fmt_spoken(e)} joules, "
                    f"{_fmt(e/1.602176634e-19)} electron volts.")
        if re.search(r"\bhertz\b|\bhz\b", t):
            e = _SCI_H * nums[0]
            return f"That photon carries {_fmt_spoken(e)} joules."

    return None


if __name__ == "__main__":
    for q in [
        "escape velocity of mars", "what's the surface gravity of the moon",
        "how much would I weigh on mars at 180 pounds",
        "how far does something fall in 3 seconds",
        "how fast is it going after falling for 3 seconds",
        "kinetic energy of 5 kilograms at 10 meters per second",
        "potential energy of 2 kilograms at 10 meters",
        "momentum of 5 kilograms at 3 meters per second",
        "force of 10 kilograms at 2 meters per second squared",
        "work done by 20 newtons over 5 meters",
        "power of 100 joules in 5 seconds",
        "schwarzschild radius of the sun", "schwarzschild radius of 10 solar masses",
        "how long does light take to reach the moon",
        "how long does light take to get to andromeda",
        "voltage across 5 ohms with 2 amps",
        "time dilation at 0.9 c",
        "energy of a photon at 500 nanometers",
        "what time is it",
    ]:
        print(f"  {q:52} -> {handle(q)}")
