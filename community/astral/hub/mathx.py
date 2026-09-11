#!/usr/bin/env python3
"""Astral mathx — the rest of the deterministic math. No LLM, no cloud, µs.

Everything here is a closed-form answer a calculator would give, which is exactly the
class a language model should never be asked for:

  • bases        "42 in binary", "255 in hexadecimal", "binary 1011 in decimal"
  • logs         "log of 1000", "natural log of 10", "log base 2 of 64"
  • trig         "sine of 30 degrees", "cosine of 60 degrees"
  • number theory "greatest common factor of 12 and 18", "least common multiple of 4 and 6",
                 "is 91 prime", "prime factors of 360", "17 mod 5"
  • algebra      "solve the quadratic 1 5 6"
  • percent      "what percent of 80 is 20", "percent change from 40 to 50"
  • fractions    "3 over 8 as a decimal", "0.375 as a fraction", "simplify 18 over 24"
  • rounding     "round 3.14159 to 3 significant figures",
                 "write 0.00045 in scientific notation"

handle(text) -> spoken string, or None to fall through.
"""
from __future__ import annotations
from typing import Optional
import re
import math
from fractions import Fraction
from calc import _fmt   # INLINE-STRIP

_MX_DIGITS = re.compile(r"-?\d+(?:\.\d+)?")


def _mx_fmt(x: float) -> str:
    """Six significant digits. calc._fmt stops at two decimals, which is right for
    money and wrong for a logarithm: ln 10 is 2.3026, not 2.3.

    Rounding to six places also turns anything under 1e-6 into a flat "0" — the same
    say-zero-about-a-non-zero-number failure _fmt had. The sine of a very small angle
    is small, not nothing."""
    # Two different tiny things. sin(180 degrees) is EXACTLY zero and comes back as
    # 1.22e-16 — float residue from the identity, and reading that out as an answer is
    # noise pretending to be precision. The sine of a genuinely tiny angle is a real
    # small number and must not be flattened to "0". The line between them sits well
    # below anything a person says out loud and well above double-precision residue.
    if abs(x) < 1e-12:
        return "0"
    if abs(x) < 1e-6:
        return f"{x:.4g}".replace("e-0", " times ten to the minus ").replace(
            "e-", " times ten to the minus ")
    return f"{round(x, 6):g}"


def _mx_seq(t: str) -> list[float]:
    """Digit tokens, kept separate. calc.numbers() merges "1 5 6" into 12, which is
    right for spoken quantities and wrong for a list of coefficients."""
    return [float(x) for x in _MX_DIGITS.findall(t)]


def _mx_factors(n: int) -> list[int]:
    out, d = [], 2
    while d * d <= n:
        while n % d == 0:
            out.append(d)
            n //= d
        d += 1 if d == 2 else 2
    if n > 1:
        out.append(n)
    return out


def _mx_said_factors(fs: list[int]) -> str:
    groups, out = {}, []
    for f in fs:
        groups[f] = groups.get(f, 0) + 1
    for base, power in groups.items():
        out.append(f"{base}" if power == 1 else f"{base} to the {power}")
    return " times ".join(out)


def handle(text: str) -> Optional[str]:
    t = " " + text.lower().strip() + " "

    # ── number bases ──────────────────────────────────────────────────────────
    m = re.search(r"\b(?:binary|base two)\s+([01]+)\b", t)
    if m and re.search(r"\bdecimal\b|\bbase ten\b|\bin decimal\b", t):
        return f"Binary {m.group(1)} is {int(m.group(1), 2)} in decimal."
    m = re.search(r"\b(?:hex|hexadecimal|base sixteen)\s+([0-9a-f]+)\b", t)
    if m and re.search(r"\bdecimal\b|\bbase ten\b", t):
        return f"Hex {m.group(1).upper()} is {int(m.group(1), 16)} in decimal."
    m = re.search(r"([0-9]+)\s+(?:in|to|as)\s+(binary|hex|hexadecimal|octal|base two|base sixteen|base eight)\b", t)
    if m:
        n, base = int(m.group(1)), m.group(2)
        if base in ("binary", "base two"):
            return f"{n} in binary is {bin(n)[2:]}."
        if base in ("octal", "base eight"):
            return f"{n} in octal is {oct(n)[2:]}."
        return f"{n} in hexadecimal is {hex(n)[2:].upper()}."

    # ── logarithms ────────────────────────────────────────────────────────────
    m = re.search(r"log(?:arithm)?\s+base\s+([0-9]+(?:\.[0-9]+)?)\s+of\s+([0-9]+(?:\.[0-9]+)?)", t)
    if m:
        b, x = float(m.group(1)), float(m.group(2))
        if b > 0 and b != 1 and x > 0:
            return f"Log base {_fmt(b)} of {_fmt(x)} is {_mx_fmt(math.log(x, b))}."
    m = re.search(r"\bnatural log(?:arithm)?\s+(?:of\s+)?([0-9]+(?:\.[0-9]+)?)", t)
    if m and float(m.group(1)) > 0:
        return f"The natural log of {_fmt(float(m.group(1)))} is {_mx_fmt(math.log(float(m.group(1))))}."
    m = re.search(r"\blog(?:arithm)?\s+(?:of\s+)?([0-9]+(?:\.[0-9]+)?)", t)
    if m and float(m.group(1)) > 0:
        return f"The log of {_fmt(float(m.group(1)))} is {_mx_fmt(math.log10(float(m.group(1))))}, base ten."

    # ── trigonometry ──────────────────────────────────────────────────────────
    m = re.search(r"\b(sine|sin|cosine|cos|tangent|tan)\s+(?:of\s+)?(-?[0-9]+(?:\.[0-9]+)?)", t)
    if m:
        fn, v = m.group(1), float(m.group(2))
        radians = bool(re.search(r"\bradians?\b", t))
        ang = v if radians else math.radians(v)
        unit = "radians" if radians else "degrees"
        if fn in ("tangent", "tan") and abs(math.cos(ang)) < 1e-12:
            return f"The tangent of {_fmt(v)} {unit} is undefined — the cosine is zero there."
        val = (math.sin(ang) if fn in ("sine", "sin") else
               math.cos(ang) if fn in ("cosine", "cos") else math.tan(ang))
        name = {"sin": "sine", "cos": "cosine", "tan": "tangent"}.get(fn, fn)
        return f"The {name} of {_fmt(v)} {unit} is {_mx_fmt(val)}."

    # ── number theory ─────────────────────────────────────────────────────────
    if re.search(r"\bgreatest common (?:factor|divisor)\b|\bgcf\b|\bgcd\b", t):
        vals = _mx_seq(t)
        if len(vals) >= 2:
            a, b = int(vals[0]), int(vals[1])
            return f"The greatest common factor of {a} and {b} is {math.gcd(a, b)}."
    if re.search(r"\bleast common multiple\b|\blcm\b", t):
        vals = _mx_seq(t)
        if len(vals) >= 2:
            a, b = int(vals[0]), int(vals[1])
            if a and b:
                return f"The least common multiple of {a} and {b} is {a*b//math.gcd(a, b)}."
    m = re.search(r"\bis\s+([0-9]+)\s+(?:a\s+)?prime\b", t)
    if m:
        n = int(m.group(1))
        fs = _mx_factors(n) if n > 1 else []
        if n < 2:
            return f"{n} is not prime — primes start at 2."
        if len(fs) == 1:
            return f"Yes, {n} is prime."
        return f"No, {n} isn't prime. It's {_mx_said_factors(fs)}."
    if re.search(r"\bprime factor", t):
        vals = _mx_seq(t)
        if vals and 1 < vals[0] <= 1e12:
            n = int(vals[0])
            return f"The prime factors of {n} are {_mx_said_factors(_mx_factors(n))}."
    m = re.search(r"([0-9]+)\s*(?:mod|modulo|modulus)\s*([0-9]+)", t)
    if m and int(m.group(2)):
        a, b = int(m.group(1)), int(m.group(2))
        return f"{a} mod {b} is {a % b}."

    # ── quadratic ─────────────────────────────────────────────────────────────
    if re.search(r"\bquadratic\b", t):
        vals = _mx_seq(t)
        if len(vals) >= 3 and vals[0]:
            a, b, c = vals[0], vals[1], vals[2]
            disc = b * b - 4 * a * c
            if disc < 0:
                return (f"With a {_fmt(a)}, b {_fmt(b)}, c {_fmt(c)} the discriminant is "
                        f"{_fmt(disc)}, so there are no real roots.")
            r1 = (-b + math.sqrt(disc)) / (2 * a)
            r2 = (-b - math.sqrt(disc)) / (2 * a)
            if disc == 0:
                return f"With a {_fmt(a)}, b {_fmt(b)}, c {_fmt(c)} there's one root, x equals {_fmt(r1)}."
            return (f"With a {_fmt(a)}, b {_fmt(b)}, c {_fmt(c)} the roots are "
                    f"{_fmt(r1)} and {_fmt(r2)}.")

    # ── percent relationships ─────────────────────────────────────────────────
    m = re.search(r"what percent of\s+([0-9]+(?:\.[0-9]+)?)\s+is\s+([0-9]+(?:\.[0-9]+)?)", t)
    if m and float(m.group(1)):
        whole, part = float(m.group(1)), float(m.group(2))
        return f"{_fmt(part)} is {_fmt(part/whole*100)} percent of {_fmt(whole)}."
    m = re.search(r"percent (?:change|increase|decrease|difference)\s+from\s+([0-9]+(?:\.[0-9]+)?)\s+to\s+([0-9]+(?:\.[0-9]+)?)", t)
    if m and float(m.group(1)):
        a, b = float(m.group(1)), float(m.group(2))
        pct = (b - a) / a * 100
        word = "increase" if pct >= 0 else "decrease"
        return f"From {_fmt(a)} to {_fmt(b)} is a {_fmt(abs(pct))} percent {word}."

    # ── fractions ─────────────────────────────────────────────────────────────
    m = re.search(r"([0-9]+)\s*(?:over|/|divided by)\s*([0-9]+)\s*(?:as a decimal|in decimal)", t)
    if m and int(m.group(2)):
        a, b = int(m.group(1)), int(m.group(2))
        return f"{a} over {b} is {round(a/b, 6):g} as a decimal."
    m = re.search(r"(?:simplify|reduce)\s+([0-9]+)\s*(?:over|/)\s*([0-9]+)", t)
    if m and int(m.group(2)):
        fr = Fraction(int(m.group(1)), int(m.group(2)))
        if fr.denominator == 1:
            return f"{m.group(1)} over {m.group(2)} simplifies to {fr.numerator}."
        return f"{m.group(1)} over {m.group(2)} simplifies to {fr.numerator} over {fr.denominator}."
    m = re.search(r"([0-9]*\.[0-9]+)\s+as a fraction", t)
    if m:
        fr = Fraction(m.group(1)).limit_denominator(10000)
        return f"{m.group(1)} as a fraction is {fr.numerator} over {fr.denominator}."

    # ── rounding and notation ─────────────────────────────────────────────────
    m = re.search(r"round\s+(-?[0-9]+(?:\.[0-9]+)?)\s+to\s+([0-9]+)\s+(significant figures?|sig figs?|decimal places?|decimals?)", t)
    if m:
        x, k, kind = float(m.group(1)), int(m.group(2)), m.group(3)
        if kind.startswith("sig"):
            if x == 0:
                return "Zero to any number of significant figures is 0."
            r = round(x, -int(math.floor(math.log10(abs(x)))) + (k - 1))
            return f"{m.group(1)} to {k} significant figures is {r:g}."
        return f"{m.group(1)} to {k} decimal places is {round(x, k):.{k}f}."
    m = re.search(r"(-?[0-9]*\.?[0-9]+)\s+in scientific notation", t)
    if m:
        x = float(m.group(1))
        if x != 0:
            exp = math.floor(math.log10(abs(x)))
            mant = x / (10 ** exp)
            return (f"{m.group(1)} in scientific notation is {round(mant, 6):g} times ten "
                    f"to the {'minus ' if exp < 0 else ''}{abs(exp)}.")

    return None


if __name__ == "__main__":
    for q in [
        "42 in binary", "255 in hexadecimal", "binary 1011 in decimal",
        "hex 1f in decimal", "log of 1000", "natural log of 10",
        "log base 2 of 64", "sine of 30 degrees", "cosine of 60 degrees",
        "tangent of 45 degrees", "greatest common factor of 12 and 18",
        "least common multiple of 4 and 6", "is 91 prime", "is 97 prime",
        "prime factors of 360", "17 mod 5", "solve the quadratic 1 5 6",
        "solve the quadratic 1 2 5", "what percent of 80 is 20",
        "percent change from 40 to 50", "3 over 8 as a decimal",
        "simplify 18 over 24", "0.375 as a fraction",
        "round 3.14159 to 3 significant figures", "0.00045 in scientific notation",
        "what time is it",
    ]:
        print(f"  {q:44} -> {handle(q)}")
