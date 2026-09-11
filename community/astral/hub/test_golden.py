#!/usr/bin/env python3
"""Golden byte tests — the pre-mortem's real guard.

Each deterministic answer is asserted BYTE-EXACT against a known-good string. A table
typo or a formatting drift changes the bytes and fails here, so a confidently-wrong
answer never ships. This is the whole "byte-identical for precision" idea, minus the
framework: a dict and an assert.

Three sections:
  GOLDEN   the original engine answers, called directly, unchanged since the DevKit
           proving run — these are the byte contract the shipped ability was accepted on
  ROUTED   everything routed through engine.answer(), so ROUTING is tested too: a
           module stealing another module's phrase shows up here as a changed byte
  SILENT   questions Astral must NOT answer, because deferring is a feature

Run:  python3 test_golden.py   (exit 0 = all byte-exact)
"""
import sys
from datetime import datetime
import mechanical
import calc
import engine

NOW = datetime(2026, 8, 7, 15, 55)   # fixed clock so time/date answers are stable

GOLDEN = {
    ("mech", "what time is it"): "It's 3:55 pm.",
    ("mech", "what's the date"): "Today is Friday, August 7, 2026.",
    ("mech", "what day is it"): "It's Friday.",
    ("calc", "what is twenty percent of eighty"): "20 percent of 80 is 16.",
    ("calc", "convert ten pounds to kilograms"): "10 pounds is 4.54 kilograms.",
    ("calc", "how many cups are in two liters"): "2 liters is 8.45 cups.",
    ("calc", "seventy fahrenheit to celsius"): "70 degrees Fahrenheit is 21.11 degrees Celsius.",
    ("calc", "what is the square root of 155"): "The square root of 155 is 12.45.",
    ("calc", "eighteen percent tip on forty five dollars"):
        "A tip of 18 percent on 45 dollars is 8.1 dollars, for a total of 53.1.",
    ("calc", "one hundred divided by four"): "100 divided by 4 is 25.",
    ("calc", "how many minutes in two hours"): "2 hours is 120 minutes.",
    ("calc", "convert 60 mph to kph"): "60 mph is 96.56 kph.",
    ("calc", "convert 100 square meters to square feet"):
        "100 square meters is 1076.39 square feet.",
    ("calc", "5 factorial"): "5 factorial is 120.",
    ("calc", "2 cubed"): "2 cubed is 8.",
    ("calc", "what is 2 to the power of 8"): "2 to the power of 8 is 256.",
    ("calc", "cube root of 27"): "The cube root of 27 is 3.",
    ("calc", "42 in roman numerals"): "42 in roman numerals is XLII.",
}

ROUTED = {
    # ── the two accuracy bugs these tests exist to keep dead ──────────────────
    # An article before a digit used to add one: "a 15 percent tip" answered 16.
    "a 15 percent tip on 60 dollars":
        "A tip of 15 percent on 60 dollars is 9 dollars, for a total of 69.",
    # A truncated mile constant used to answer 5279.99.
    "how many feet in a mile": "1 mile is 5280 feet.",

    # ── grades ────────────────────────────────────────────────────────────────
    "what letter grade is an 87":
        "87 percent is a B plus on a standard 90/80/70 scale.",
    "what's my grade if I got 42 out of 50":
        "42 out of 50 is 84 percent, a B on a standard 90/80/70 scale.",
    "I have an 87 and the final is worth 20 percent, what do I need to get a 90":
        "You'd need 102 percent on the final for 90 percent, which isn't possible. "
        "A perfect final leaves you at 89.6 percent.",
    "I have a 95 and the final is worth 10 percent what do I need to get an a":
        "You need 45 percent on the final to finish with A at 90 percent, starting "
        "from 95 percent with the final worth 10 percent.",
    "homework is 90 worth 20 percent and exams are 84 worth 80 percent":
        "Your weighted grade is 85.2 percent, a B on a standard 90/80/70 scale.",
    "gpa for a 4.0 in 3 credits and a 3.0 in 4 credits":
        "That's a 3.43 GPA over 7 credits.",
    # The word "final" used to disable this branch outright, so the most natural way
    # to list a course — which almost always names the final — answered nothing.
    "quizzes 70 worth 10 percent labs 95 worth 30 percent final 88 worth 60 percent":
        "Your weighted grade is 88.3 percent, a B plus on a standard 90/80/70 scale.",

    # ── chemistry ─────────────────────────────────────────────────────────────
    "molar mass of water": "The molar mass of water (H2O) is 18.015 grams per mole.",
    "molecular weight of glucose":
        "The molar mass of glucose (C6H12O6) is 180.156 grams per mole.",
    "molar mass of Ca(OH)2": "The molar mass of Ca(OH)2 is 74.092 grams per mole.",
    "atomic number of iron": "Iron is element number 26, symbol Fe.",
    "atomic mass of carbon": "The atomic mass of carbon is 12.011 atomic mass units.",
    "how many moles in 36 grams of water":
        "36 grams of water is 1.998 moles, at 18.015 grams per mole.",
    "how many grams in 2 moles of glucose":
        "2 moles of glucose is 360.3 grams, at 180.156 grams per mole.",
    "molarity of 2 moles in 4 liters": "2 moles in 4 liters is 0.5 molar.",
    "ph of a 0.001 molar solution":
        "A 0.001 molar solution has a pH of 3, which is acidic.",
    "volume of 2 moles at 300 kelvin and 1 atmosphere":
        "2 moles at 300 kelvin and 1 atmosphere occupies 49.23 liters.",

    # ── physics and astronomy ─────────────────────────────────────────────────
    # 5.02, not the 5.03 you see quoted: that figure uses the volumetric mean radius
    # while the published surface gravity uses the equatorial one. This engine uses the
    # equatorial radius for both, which agrees with every published surface gravity and
    # every published escape velocity to better than half a percent. Asserted in
    # test_hardening.cross_check_physics against NASA's numbers for eight bodies.
    "escape velocity of mars":
        "Escape velocity at Mars is 5.02 kilometers per second, 11234.25 miles per hour.",
    "what's the surface gravity of the moon":
        "Surface gravity on the Moon is 1.62 meters per second squared, 0.17 times Earth's.",
    "how much would I weigh on mars at 180 pounds":
        "180 pounds on Earth is 68.16 pounds on Mars, at 0.38 times Earth's gravity.",
    "how far does something fall in 3 seconds":
        "In 3 seconds it falls 44.13 meters, 144.78 feet, ignoring air resistance.",
    "kinetic energy of 5 kilograms at 10 meters per second":
        "The kinetic energy is 250 joules, from one half m v squared.",
    "momentum of 5 kilograms at 3 meters per second":
        "The momentum is 15 kilogram meters per second, from m v.",
    "work done by 20 newtons over 5 meters":
        "The work done is 100 joules, from force times distance.",
    "schwarzschild radius of the sun":
        "The Schwarzschild radius of the Sun is 2.95 kilometers.",
    # Mass and size come straight off the body table (reviewer request, 2026-09-01).
    # Radii are equatorial, so diameters are twice the equatorial radius: Mars 6792.4,
    # Jupiter 142984, Earth 12756.27, all NASA's published figures to the digit.
    "mass of earth":
        "The mass of Earth is about 5.97 times ten to the 24 kilograms.",
    "what's the mass of venus":
        "The mass of Venus is about 4.87 times ten to the 24 kilograms.",
    "how heavy is the sun":
        "The mass of the Sun is about 1.99 times ten to the 30 kilograms.",
    "mass of the moon in pounds":
        "The mass of the Moon is about 1.62 times ten to the 23 pounds.",
    "diameter of mars":
        "The diameter of Mars is 6792.4 kilometers, 4220.6 miles.",
    "what is the diameter of earth":
        "The diameter of Earth is 12756.27 kilometers, 7926.38 miles.",
    "radius of the moon":
        "The radius of the Moon is 1738.1 kilometers, 1080.01 miles.",
    "how big is jupiter":
        "The diameter of Jupiter is 142984 kilometers, 88846.14 miles.",
    "how long does light take to reach the moon":
        "Light takes 1.28 seconds to cross the 384400 kilometers to the moon.",
    "voltage across 5 ohms with 2 amps": "That's 10 volts, from V equals I R.",

    # ── statistics ────────────────────────────────────────────────────────────
    "average of 4 6 8 and 10": "The mean of 4, 6, 8, 10 is 7.",
    "median of 3 7 2 9": "The median of 3, 7, 2, 9 is 5.",
    "standard deviation of 4 6 8 10":
        "The sample standard deviation of 4, 6, 8, 10 is 2.58, around a mean of 7.",
    "population standard deviation of 4 6 8 10":
        "The population standard deviation of 4, 6, 8, 10 is 2.24, around a mean of 7.",
    "5 choose 2": "5 choose 2 is 10 combinations.",
    "z score of 85 with a mean of 75 and a standard deviation of 5":
        "The z score is 2, 2 standard deviations above the mean.",

    # ── number tools ──────────────────────────────────────────────────────────
    "42 in binary": "42 in binary is 101010.",
    "255 in hexadecimal": "255 in hexadecimal is FF.",
    "log base 2 of 64": "Log base 2 of 64 is 6.",
    "natural log of 10": "The natural log of 10 is 2.30259.",
    "sine of 30 degrees": "The sine of 30 degrees is 0.5.",
    "greatest common factor of 12 and 18":
        "The greatest common factor of 12 and 18 is 6.",
    "is 91 prime": "No, 91 isn't prime. It's 7 times 13.",
    "prime factors of 360":
        "The prime factors of 360 are 2 to the 3 times 3 to the 2 times 5.",
    "17 mod 5": "17 mod 5 is 2.",
    "solve the quadratic 1 5 6": "With a 1, b 5, c 6 the roots are -2 and -3.",
    "what percent of 80 is 20": "20 is 25 percent of 80.",
    "percent change from 40 to 50": "From 40 to 50 is a 25 percent increase.",
    "simplify 18 over 24": "18 over 24 simplifies to 3 over 4.",
    "round 3.14159 to 3 significant figures":
        "3.14159 to 3 significant figures is 3.14.",

    # ── paths the coverage pass found had never once been exercised ───────────
    "split 120 between 4 people": "120 split between 4 is 30 dollars each.",
    "half of 90": "Half of 90 is 45.",
    "double 45": "Double 45 is 90.",
    "two thousand divided by four": "2000 divided by 4 is 500.",
    "I have a 95 and the final is worth 10 percent what do I need to get a b":
        "You already have it. Even a zero on the final leaves you at 85.5 percent, "
        "above B at 80 percent.",
    "symbol for potassium": "The symbol for potassium is K, element number 19.",
    "atomic mass of gold": "The atomic mass of gold is 196.97 atomic mass units.",
    "ph of a 0.001 molar hydroxide solution":
        "A 0.001 molar hydroxide solution has a pOH of 3, so a pH of 11.",
    "how many atoms in 3 moles":
        "3 moles is 1.81 times ten to the 24 particles, by Avogadro's number.",
    "how long does light take to reach mars":
        "Light takes 4.35 minutes to cross the 78.3 million kilometers to mars.",
    "how long does light take to reach andromeda":
        "Light takes 2.54 million years to cross the 2.54 million light years to andromeda.",
    "time dilation at 0.99 c":
        "At 0.99 times the speed of light the Lorentz factor is 7.09, so moving clocks "
        "run 7.09 times slower.",
    "current through 10 ohms at 5 volts": "That's 0.5 amps, from I equals V over R.",
    "mean of twenty five thirty and thirty five": "The mean of 25, 30, 35 is 30.",
    "permutations of 5 taken 2": "5 things taken 2 at a time is 20 permutations.",
    "mode of 2 5 7": "2, 5, 7 has no mode — every value appears once.",
    "binary 1011 in decimal": "Binary 1011 is 11 in decimal.",
    "hex ff in decimal": "Hex FF is 255 in decimal.",
    "42 in octal": "42 in octal is 52.",
    "is 97 prime": "Yes, 97 is prime.",
    "3 over 8 as a decimal": "3 over 8 is 0.375 as a decimal.",
    "round 2.71828 to 2 decimal places": "2.71828 to 2 decimal places is 2.72.",
    "0.00045 in scientific notation":
        "0.00045 in scientific notation is 4.5 times ten to the minus 4.",

    # The four most basic operations had no golden at all until the coverage pass
    # went looking. Everything shipped, nothing checked them.
    "fifteen plus twenty seven": "15 plus 27 is 42.",
    "50 minus 18": "50 minus 18 is 32.",
    "12 times 8": "12 times 8 is 96.",
    "nine squared": "9 squared is 81.",
    # The router's own time path: every other routed phrase skips the first branch.
    "what time is it": "It's 3:55 pm.",
    "what day is it": "It's Friday.",
    "0.375 as a fraction": "0.375 as a fraction is 3 over 8.",
    "simplify 8 over 4": "8 over 4 simplifies to 2.",
    "round 0 to 3 significant figures": "Zero to any number of significant figures is 0.",
    "energy of a photon at 500 nanometers":
        "A 500 nanometer photon carries 3.973 times ten to the minus 19 joules, "
        "2.48 electron volts.",
    "permutations of 5": "5 things can be arranged 120 ways.",
    "range of 3 7 2 9": "The range of 3, 7, 2, 9 is 7, from 2 to 9.",
    "molar mass of iron": "The molar mass of iron (Fe) is 55.845 grams per mole.",
    # _fmt used to render any non-zero value under 0.005 as "0", so this echoed
    # "0 moles is ...".
    "how many atoms in 0.000001 moles":
        "1 times ten to the minus 6 moles is 6.02 times ten to the 17 particles, "
        "by Avogadro's number.",

    # ── last of the untested branches, found by the coverage pass ─────────────
    "schwarzschild radius of 10 solar masses":
        "The Schwarzschild radius of 10 solar masses is 29.53 kilometers.",
    "how fast is it going after falling for 3 seconds":
        "After falling 3 seconds it's going 29.42 meters per second, 65.81 miles per "
        "hour, ignoring air resistance.",
    "potential energy of 2 kilograms at 10 meters":
        "The potential energy is 196.13 joules, from m g h.",
    "energy of a photon at 500 hertz":
        "That photon carries 3.313 times ten to the minus 31 joules.",
    "mean of four six and eight": "The mean of 4, 6, 8 is 6.",
    "sine of 0.00001 degrees":
        "The sine of 1 times ten to the minus 5 degrees is 1.745 times ten to the minus 7.",
    # "close enough to an integer" was also true of every number smaller than the
    # tolerance, so this said "0 moles is ...".
    "how many atoms in 0.0000000001 moles":
        "1 times ten to the minus 10 moles is 60.22 trillion particles, by "
        "Avogadro's number.",

    # ── new unit dimensions ───────────────────────────────────────────────────
    "convert 1 light year to kilometers": "1 light year is 9.46 trillion kilometers.",
    "convert 2 gigabytes to megabytes": "2 gigabytes is 2048 megabytes.",
    "convert 60 miles per hour to meters per second":
        "60 miles per hour is 26.82 meters per second.",
    "how many watt hours in a kilowatt hour": "1 kilowatt hour is 1000 watt hours.",
    "convert 1 atmosphere to kilopascals": "1 atmosphere is 101.33 kilopascals.",
    # Multi-word units that contain a shorter unit of the SAME dimension. Matching
    # unit-by-unit reported both, and _convert picks by distance to the number, so the
    # shorter one could win: the Aug-7 build answered "1 mile is 1.61 kilometers" when
    # asked about a nautical mile.
    "how many kilometers in a nautical mile": "1 nautical mile is 1.85 kilometers.",
    "convert 2 metric tons to pounds": "2 metric tons is 4409.25 pounds.",
    "convert 2 short tons to kilograms": "2 short tons is 1814.37 kilograms.",
    "how many joules in 200 food calories": "200 food calories is 836800 joules.",
    "convert 3 kilowatt hours to watt hours": "3 kilowatt hours is 3000 watt hours.",
}

# Deferring is a feature: these must produce nothing so the agent takes the turn.
SILENT = [
    "tell me a joke", "what's the meaning of life", "who won the game last night",
    "why is the sky blue", "remind me to call mom", "I like miles and kilometers",

    # Sentences that contain a time word but are not asking what time it is. The
    # mechanical module runs FIRST, so anything it claims here is a wrong answer
    # nothing downstream can correct. All ten of these were answered confidently
    # before the patterns were anchored: "what year did the war end" -> "It's 2026."
    "what year did the war end",
    "what month is best to visit japan",
    "what's the time zone in tokyo",
    "what is the date of the super bowl",
    "remind me at the time of the meeting",
    "what day of the week was I born",
    "what year is the next olympics",
    "set an alarm for the time I usually wake up",
    "what time does the store close",
    "what was the date of the moon landing",

    # Ordinary speech containing a trigger word from the hotword list. Astral will be
    # handed these turns on the device; it must give every one of them straight back.
    "double check the front door is locked",
    "is amazon prime worth it",
    "round up everyone for dinner",
    "how fast can you get here",
    "what's the temperature outside",
    "play some music",
    "how many people are coming tonight",
    "convert this document to pdf for me",
    "split the group into two teams",
    "what's the average person like in that city",
]


def _run(kind, text):
    if kind == "mech":
        return mechanical.handle(text, NOW)
    return calc.handle(text)


def main():
    fails = 0
    print("── original engine goldens ─────────────────────────────────────────")
    for (kind, text), expected in GOLDEN.items():
        got = _run(kind, text) or ""
        ok = got.encode() == expected.encode()
        fails += not ok
        print(f"  [{'OK ' if ok else 'FAIL'}] {len(got.encode()):>3}B  {text[:44]:44}  {got!r}")
        if not ok:
            print(f"        expected {expected!r}")

    print("\n── routed through engine.answer ────────────────────────────────────")
    for text, expected in ROUTED.items():
        got = engine.answer(text, NOW) or ""
        ok = got.encode() == expected.encode()
        fails += not ok
        print(f"  [{'OK ' if ok else 'FAIL'}] {len(got.encode()):>3}B  {text[:52]:52}  {got!r}")
        if not ok:
            print(f"        expected {expected!r}")

    print("\n── must stay silent ────────────────────────────────────────────────")
    for text in SILENT:
        got = engine.answer(text, NOW)
        ok = got is None
        fails += not ok
        print(f"  [{'OK ' if ok else 'FAIL'}] {text[:52]:52}  {got!r}")

    total = len(GOLDEN) + len(ROUTED) + len(SILENT)
    print(f"\n{'PASS' if not fails else 'FAIL'} — {total} outputs checked byte-exact"
          f"{'' if not fails else f', {fails} wrong'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
