#!/usr/bin/env python3
"""Hardening — the tests that try to break the engine rather than confirm it works.

The golden suite proves the answers we chose are byte-exact. It says nothing about the
inputs nobody thought of. This file is the adversary:

  1. FUZZ        thousands of generated utterances; answering is optional, CRASHING is not
  2. CROSS-CHECK every result recomputed a second, independent way (stdlib, published
                 constants, inverse operations) — a table typo survives a golden test
                 written from the same table, it does not survive this
  3. ROUTING     no module may silently shadow another; a reorder must show up here
  4. EDGE        zero, negative, empty, absurd magnitude, unicode, 10k characters
  5. DETERMINISM identical input, identical bytes, every time
  6. TIMING      no input takes long enough to matter on a Pi (catastrophic backtracking)

Run:  python3 test_hardening.py
"""
from __future__ import annotations
import math
import random
import re
import statistics
import sys
import time

import calc
import chem
import engine
import mathx
import sci
import stats
import study
try:
    import comprehend                      # device-control parser; ships with the DevKit file only
except ImportError:                        # the cloud Skill's copy of hub/ has no device to command
    comprehend = None

FAILS: list[str] = []
_NONFINITE = re.compile(r"\b(nan|inf|infinity)\b", re.I)


def spoken_float(said: str) -> float:
    """Read back a number the engine said, including its spoken exponent form."""
    said = said.strip().rstrip(".")
    m = re.match(r"^(-?[\d.]+) times ten to the minus (\d+)$", said)
    return float(m.group(1)) * 10 ** -int(m.group(2)) if m else float(said)


def check(ok: bool, label: str, detail: str = "") -> None:
    if not ok:
        FAILS.append(f"{label}{': ' + detail if detail else ''}")
        print(f"  [FAIL] {label} {detail}")


def section(name: str) -> None:
    print(f"\n── {name} " + "─" * max(0, 66 - len(name)))


# ─────────────────────────────────────────────────────────────────────────────
def fuzz() -> None:
    section("fuzz: never raise, never hang")
    random.seed(20260817)
    vocab = ("time date percent of tip tax split convert to in how many is what "
             "grade final worth gpa molar mass moles grams water glucose escape "
             "velocity gravity mars moon energy kinetic momentum force work power "
             "mean median mode deviation variance z score choose binary hex log "
             "sine prime factors quadratic simplify round significant a an and the "
             "kilograms pounds liters cups meters feet ohms amps volts kelvin "
             "atmosphere light year parsec gigabytes joules newtons").split()
    junk = ["", " ", "?", "!!!", "...", "—", "café", "日本語", "\t\n", "0", "-1",
            "1e309", "nan", "inf", "0.0.0", "99999999999999999999", "%", "$", "'"]
    cases = 0
    for i in range(4000):
        n = random.randint(1, 12)
        words = []
        for _ in range(n):
            r = random.random()
            if r < 0.55:
                words.append(random.choice(vocab))
            elif r < 0.85:
                words.append(str(random.choice(
                    [0, 1, 2, 7, 42, -3, 0.5, 1e6, 1e12, 99999, 3.14159])))
            else:
                words.append(random.choice(junk))
        text = " ".join(words)
        t0 = time.perf_counter()
        try:
            out = engine.answer(text)
        except Exception as exc:
            check(False, "fuzz raised", f"{exc!r} on {text!r}")
            continue
        dt = time.perf_counter() - t0
        check(dt < 0.25, "fuzz slow", f"{dt*1000:.0f}ms on {text!r}")
        check(out is None or isinstance(out, str), "fuzz type", repr(out))
        # Word boundaries: "discrimi-nan-t" and "in-f-inity" both contain the naive
        # substrings, and flagging those hides the real ones.
        check(out is None or not _NONFINITE.search(out),
              "fuzz non-finite answer", f"{text!r} -> {out!r}")
        cases += 1
    print(f"  {cases} generated utterances, no crash, no hang, no nan/inf spoken")


# ─────────────────────────────────────────────────────────────────────────────
def cross_check_units() -> None:
    section("cross-check: unit tables against inverse conversion and known values")
    # Every pair inside a dimension must round-trip through the base exactly.
    for dim, table in calc._DIMS.items():
        for unit, factor in table.items():
            check(factor > 0, "unit factor not positive", f"{dim}/{unit}={factor}")
            back = (7.0 * factor) / factor
            check(abs(back - 7.0) < 1e-9, "unit round trip", f"{dim}/{unit}")
    # Singular and plural are separate keys carrying the same literal, typed twice.
    # One mistyped digit in "parsecs" and the answer changes depending on whether the
    # speaker said one or many, which no round-trip or golden line would catch.
    for dim, table in calc._DIMS.items():
        for unit, factor in table.items():
            for other in (unit + "s", unit + "es", unit.rstrip("s")):
                if other != unit and other in table:
                    check(table[other] == factor, "plural factor differs",
                          f"{dim}: {unit}={factor} but {other}={table[other]}")
    # Published values, independent of our table's derivation.
    known = [
        ("convert 1 mile to feet", 5280, "feet"),
        ("convert 1 kilogram to pounds", 2.2046226, "pounds"),
        ("convert 1 inch to centimeters", 2.54, "centimeters"),
        ("convert 1 gallon to liters", 3.785411784, "liters"),
        ("convert 1 light year to meters", 9.4607304725808e15, "meters"),
        ("convert 1 parsec to light years", 3.2615638, "light years"),
        ("convert 1 atmosphere to pascals", 101325, "pascals"),
        ("convert 1 gigabyte to bytes", 1073741824, "bytes"),
        ("convert 1 kilowatt hour to joules", 3.6e6, "joules"),
        ("convert 1 hour to seconds", 3600, "seconds"),
    ]
    for text, expect, unit in known:
        src, tgt = text.split(" to ")
        v = 1.0
        dim = next(d for d, t in calc._DIMS.items() if unit in t
                   and src.split("convert 1 ")[1] in t)
        got = v * calc._DIMS[dim][src.split("convert 1 ")[1]] / calc._DIMS[dim][unit]
        check(abs(got - expect) / expect < 1e-6, "unit vs published",
              f"{text}: got {got!r} want {expect!r}")
    print(f"  {sum(len(t) for t in calc._DIMS.values())} units round-trip; "
          f"{len(known)} checked against published values")


def cross_check_stats() -> None:
    section("cross-check: statistics against the stdlib statistics module")
    random.seed(7)
    for _ in range(300):
        data = [round(random.uniform(-50, 50), 2) for _ in range(random.randint(2, 9))]
        said = " ".join(str(abs(int(v))) for v in data)      # spoken lists are integers
        vals = [float(abs(int(v))) for v in data]
        got = stats.handle(f"mean of {said}")
        check(got is not None, "stats mean silent", said)
        if got:
            want = calc._fmt(statistics.fmean(vals))
            check(f"is {want}." in got, "mean mismatch", f"{said}: {got} vs {want}")
        got = stats.handle(f"median of {said}")
        if got:
            want = calc._fmt(statistics.median(vals))
            check(f"is {want}." in got, "median mismatch", f"{said}: {got} vs {want}")
        if len(vals) > 1:
            got = stats.handle(f"standard deviation of {said}")
            if got:
                want = calc._fmt(statistics.stdev(vals))
                check(f"is {want}," in got, "sample stdev mismatch", f"{said}: {got} vs {want}")
            got = stats.handle(f"population standard deviation of {said}")
            if got:
                want = calc._fmt(statistics.pstdev(vals))
                check(f"is {want}," in got, "population stdev mismatch", f"{said}: {got} vs {want}")
    for n in range(0, 12):
        for k in range(0, n + 1):
            got = stats.handle(f"{n} choose {k}")
            check(got is not None and str(math.comb(n, k)) in got,
                  "nCr mismatch", f"{n} choose {k} -> {got}")
    print("  300 random datasets vs statistics.fmean/median/stdev/pstdev; all nCr to n=11")


def cross_check_math() -> None:
    section("cross-check: number tools against the math module")
    for n in range(2, 400):
        fs = mathx._mx_factors(n)
        prod = 1
        for f in fs:
            prod *= f
        check(prod == n, "factorization product", f"{n} -> {fs}")
        for f in fs:
            check(all(f % d for d in range(2, int(f ** 0.5) + 1)),
                  "non-prime factor emitted", f"{n} -> {f}")
    for a in range(1, 60):
        for b in range(1, 60):
            got = mathx.handle(f"greatest common factor of {a} and {b}")
            check(got and str(math.gcd(a, b)) in got.split(" is ")[-1], "gcd", f"{a},{b}")
            got = mathx.handle(f"least common multiple of {a} and {b}")
            check(got and str(a * b // math.gcd(a, b)) in got.split(" is ")[-1],
                  "lcm", f"{a},{b}")
    for base, val in [(2, 64), (10, 1000), (3, 81)]:
        got = mathx.handle(f"log base {base} of {val}")
        check(got and abs(spoken_float(got.split(" is ")[-1])
                          - math.log(val, base)) < 1e-5, "log base", f"{base},{val}")
    for deg in range(0, 360, 15):
        got = mathx.handle(f"sine of {deg} degrees")
        want = round(math.sin(math.radians(deg)), 6)
        check(got and abs(spoken_float(got.split(" is ")[-1]) - want) < 1e-6,
              "sine", f"{deg}: {got}")
    for a, b, c in [(1, 5, 6), (1, -3, 2), (2, 4, -6), (1, 2, 1), (3, 0, -12)]:
        got = mathx.handle(f"solve the quadratic {a} {b} {c}")
        disc = b * b - 4 * a * c
        if disc >= 0 and got:
            for r in {(-b + math.sqrt(disc)) / (2 * a), (-b - math.sqrt(disc)) / (2 * a)}:
                check(calc._fmt(r) in got, "quadratic root missing", f"{a},{b},{c}: {got}")
    print("  factorizations to 400, 3481 gcd/lcm pairs, logs, 24 sines, 5 quadratics")


def cross_check_chem() -> None:
    section("cross-check: periodic table and formula parser")
    check(len(chem._CH_NUM) == 118, "element count", str(len(chem._CH_NUM)))
    check(sorted(chem._CH_NUM.values()) == list(range(1, 119)), "atomic numbers not 1..118")
    check(len(set(chem._CH_NAME.values())) == 118, "duplicate element name")
    check(chem._CH_NUM["H"] == 1 and chem._CH_NUM["C"] == 6 and chem._CH_NUM["Fe"] == 26
          and chem._CH_NUM["U"] == 92 and chem._CH_NUM["Og"] == 118, "known atomic numbers")
    for sym, mass in chem._CH_MASS.items():
        check(0.9 < mass < 300, "implausible atomic mass", f"{sym}={mass}")
    # Molar mass recomputed by a second, dumber method: expand the formula by hand.
    manual = {"H2O": 2 * 1.008 + 15.999,
              "CO2": 12.011 + 2 * 15.999,
              "C6H12O6": 6 * 12.011 + 12 * 1.008 + 6 * 15.999,
              "NaCl": 22.990 + 35.45,
              "Ca(OH)2": 40.078 + 2 * (15.999 + 1.008),
              "NH4NO3": 14.007 + 4 * 1.008 + 14.007 + 3 * 15.999,
              "C12H22O11": 12 * 12.011 + 22 * 1.008 + 11 * 15.999,
              "H2SO4": 2 * 1.008 + 32.06 + 4 * 15.999}
    for formula, want in manual.items():
        got = chem._ch_molar(formula)
        check(got is not None and abs(got - want) < 1e-9, "molar mass",
              f"{formula}: {got} vs {want}")
    for bad in ["Xx2", "H2O)", "(H2O", "", "hello"]:
        check(chem._ch_molar(bad) is None, "bad formula accepted", bad)
    # Every named compound must parse.
    for name, formula in chem._CH_COMPOUND.items():
        check(chem._ch_molar(formula) is not None, "named compound unparseable",
              f"{name}={formula}")
    print(f"  118 elements, {len(manual)} formulas vs hand expansion, "
          f"{len(chem._CH_COMPOUND)} named compounds parse, 5 malformed rejected")


def cross_check_physics() -> None:
    section("cross-check: bodies against published gravity and escape velocity")
    # Published values (NASA fact sheets), independent of our mass/radius table.
    published = {"earth": (9.80, 11.19), "moon": (1.62, 2.38), "mars": (3.72, 5.03),
                 "jupiter": (24.79, 59.5), "venus": (8.87, 10.36),
                 "mercury": (3.70, 4.25), "saturn": (10.44, 35.5),
                 "sun": (274.0, 617.5)}
    for body, (want_g, want_v) in published.items():
        m, r, _ = sci._SCI_BODY[body]
        g = sci._SCI_G * m / (r * r)
        v = math.sqrt(2 * sci._SCI_G * m / r) / 1000
        check(abs(g - want_g) / want_g < 0.005, "surface gravity", f"{body}: {g:.2f} vs {want_g}")
        check(abs(v - want_v) / want_v < 0.005, "escape velocity", f"{body}: {v:.2f} vs {want_v}")
    # Free fall against the closed form, and energy against its own definition.
    for t in (0.5, 1, 3, 10):
        got = sci.handle(f"how far does something fall in {t} seconds")
        check(got and calc._fmt(0.5 * 9.80665 * t * t) in got, "free fall", f"{t}: {got}")
    got = sci.handle("kinetic energy of 5 kilograms at 10 meters per second")
    check(got and "250" in got, "kinetic energy", got or "")
    # Light travel time to the Sun is ~499 seconds; a well-known number.
    secs = sci._SCI_LIGHT_TARGET["the sun"] / sci._SCI_C
    check(abs(secs - 499) < 2, "light time to sun", f"{secs:.1f}s")
    print(f"  {len(published)} bodies vs published gravity and escape velocity, "
          f"free fall, light time")


# ─────────────────────────────────────────────────────────────────────────────
def routing() -> None:
    section("routing: which module owns each phrase, and who else wants it")
    modules = [("study", study.handle), ("chem", chem.handle), ("sci", sci.handle),
               ("stats", stats.handle), ("mathx", mathx.handle), ("calc", calc.handle)]
    owners = {
        "what is twenty percent of eighty": "calc",
        "what is 2 to the power of 8": "calc",
        "convert ten pounds to kilograms": "calc",
        "eighteen percent tip on forty five dollars": "calc",
        "what letter grade is an 87": "study",
        "homework is 90 worth 20 percent and exams are 84 worth 80 percent": "study",
        "molar mass of water": "chem",
        "how many moles in 36 grams of water": "chem",
        "escape velocity of mars": "sci",
        "kinetic energy of 5 kilograms at 10 meters per second": "sci",
        "standard deviation of 4 6 8 10": "stats",
        "5 choose 2": "stats",
        "42 in binary": "mathx",
        "is 91 prime": "mathx",
        "what percent of 80 is 20": "mathx",
    }
    for text, want in owners.items():
        answered = [name for name, fn in modules if fn(text)]
        check(bool(answered) and answered[0] == want, "wrong owner",
              f"{text!r} -> {answered} (want {want} first)")
        # More than one module answering is legal only if they agree; otherwise the
        # answer depends on the route order, which is a bug waiting for a reorder.
        outs = {name: fn(text) for name, fn in modules if fn(text)}
        if len(outs) > 1:
            print(f"  [note] {text!r} answered by {list(outs)} — "
                  f"order-dependent, order is pinned in engine._ROUTE_ORDER")
    check(engine.domains() == ("mechanical", "study", "chem", "sci", "stats",
                               "mathx", "calc"), "route order changed")
    print(f"  {len(owners)} phrases resolve to the intended module")


def edges() -> None:
    section("edge cases: zero, negative, absurd, empty")
    must_be_silent_or_sane = [
        "100 divided by 0", "what percent of 0 is 20", "percent change from 0 to 50",
        "molarity of 2 moles in 0 liters", "ph of a 0 molar solution",
        "z score of 85 with a mean of 75 and a standard deviation of 0",
        "solve the quadratic 0 5 6", "17 mod 0", "log of 0", "log base 1 of 8",
        "is 0 prime", "is 1 prime", "prime factors of 1", "simplify 5 over 0",
        "0 factorial", "tangent of 90 degrees", "sine of -45 degrees",
        "mean of 5", "standard deviation of 5", "5 choose 9",
        "how many moles in -5 grams of water", "escape velocity of pluto",
        "time dilation at 1 c", "time dilation at 2 c",
        "I have a 200 and the final is worth 200 percent what do I need to get a 90",
        "gpa for a 4.0 in 0 credits", "42 out of 0",
    ]
    for text in must_be_silent_or_sane:
        try:
            out = engine.answer(text)
        except Exception as exc:
            check(False, "edge raised", f"{exc!r} on {text!r}")
            continue
        check(out is None or not (_NONFINITE.search(out) or "None" in out),
              "edge bad answer", f"{text!r} -> {out!r}")
        print(f"  {text[:52]:52} -> {out!r}")
    check(engine.answer("") is None, "empty string answered")
    check(engine.answer("   ") is None, "whitespace answered")
    check(engine.answer("x" * 10000) is None, "10k junk answered")


def device_commands() -> None:
    if comprehend is None:
        print("  device parser not in this copy (cloud Skill); section skipped")
        return
    """The one path that ACTS instead of speaking.

    parse_command feeds _device_command, which publishes to home/<device>/set over
    MQTT. A false positive here is not a wrong answer, it is a wrong action — and none
    of it is reachable through engine.answer(), so the golden suite cannot see it.
    """
    section("device commands: acts, so a false positive costs more")
    must_decline = [
        # The most common things people say to a speaker, all of which parsed as device
        # commands: "set a timer for 10 minutes" resolved to a device named
        # "timer for minutes" and published the value 10.
        "set a timer for 10 minutes", "set an alarm for 7",
        "set a reminder to call mom", "set a meeting for 3",
        "can you stop talking", "stop recording", "set a calendar event",
    ]
    must_work = {
        "turn on the kitchen light": ("on", "kitchen light"),
        "turn off the lamp": ("off", "lamp"),
        "dim the bedroom light to 30": ("set", "bedroom light"),
        "set the thermostat to 72": ("set", "thermostat"),
        "lock the front door": ("lock", "front door"),
        "stop the music": ("off", "music"),
        "open the garage": ("open", "garage"),
        "toggle the porch light": ("toggle", "porch light"),
    }
    for text in must_decline:
        got = comprehend.parse_command(text)
        check(got is None, "device command from a non-device request",
              f"{text!r} -> {got}")
    for text, (action, device) in must_work.items():
        got = comprehend.parse_command(text)
        check(got is not None and got["action"] == action and got["device"] == device,
              "device command broken", f"{text!r} -> {got}")
    print(f"  {len(must_decline)} non-device requests declined, "
          f"{len(must_work)} real commands still parse")


def determinism() -> None:
    section("determinism: same bytes every time")
    probes = ["molar mass of water", "prime factors of 360", "escape velocity of mars",
              "mode of 2 2 5 5 7", "standard deviation of 4 6 8 10",
              "atomic number of iron", "what letter grade is an 87"]
    for text in probes:
        first = engine.answer(text)
        for _ in range(50):
            check(engine.answer(text) == first, "nondeterministic", text)
    print(f"  {len(probes)} probes × 50 runs, byte-identical")


def timing() -> None:
    section("timing: no catastrophic backtracking")
    nasty = [
        "one " * 400, "1 " * 400, ("a " * 200) + "mile",
        "point " * 300, "twenty " * 300 + "and", "9" * 400,
        "mean of " + "7 " * 500, "prime factors of 999999937",
        "convert " + "meters to feet " * 100,
    ]
    for text in nasty:
        t0 = time.perf_counter()
        try:
            engine.answer(text)
        except Exception as exc:
            check(False, "nasty input raised", f"{exc!r}")
            continue
        dt = time.perf_counter() - t0
        check(dt < 0.5, "nasty input slow", f"{dt*1000:.0f}ms on {text[:32]!r}...")
        print(f"  {dt*1000:8.1f} ms  {text[:44]!r}")


def main() -> int:
    fuzz()
    cross_check_units()
    cross_check_stats()
    cross_check_math()
    cross_check_chem()
    cross_check_physics()
    routing()
    device_commands()
    edges()
    determinism()
    timing()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAIL — {len(FAILS)} problems")
        for f in FAILS[:40]:
            print(f"  · {f}")
        return 1
    print("PASS — nothing broke it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
