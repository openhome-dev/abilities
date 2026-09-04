#!/usr/bin/env python3
"""Astral chem — deterministic chemistry. No LLM, no cloud, µs.

  • elements   "atomic mass of carbon", "atomic number of iron", "symbol for potassium"
  • compounds  "molar mass of water", "molecular weight of glucose", "molar mass of CaCO3"
  • moles      "how many moles in 36 grams of water",
               "how many grams in 2 moles of glucose", "how many atoms in 2 moles"
  • solutions  "molarity of 2 moles in 4 liters", "ph of a 0.001 molar solution"
  • gases      "volume of 2 moles at 300 kelvin and 1 atmosphere"

Molar masses are COMPUTED from the element table by parsing the formula, never typed
in per compound. A hand-entered molar mass is a typo waiting to be spoken with total
confidence; a parsed one is wrong only if the periodic table is wrong.

Elements with no stable isotope carry their longest-lived isotope's mass and say so.

handle(text) -> spoken string, or None to fall through.
"""
from __future__ import annotations
from typing import Optional
import re
import math
from calc import numbers, _fmt, _fmt_spoken   # INLINE-STRIP

_CH_NA = 6.02214076e23      # Avogadro, exact
_CH_R = 0.082057366         # gas constant, L·atm/(mol·K)

# symbol name mass  (mass* = no stable isotope; the longest-lived one)
_CH_RAW = """H hydrogen 1.008|He helium 4.0026|Li lithium 6.94|Be beryllium 9.0122|
B boron 10.81|C carbon 12.011|N nitrogen 14.007|O oxygen 15.999|F fluorine 18.998|
Ne neon 20.180|Na sodium 22.990|Mg magnesium 24.305|Al aluminum 26.982|
Si silicon 28.085|P phosphorus 30.974|S sulfur 32.06|Cl chlorine 35.45|Ar argon 39.95|
K potassium 39.098|Ca calcium 40.078|Sc scandium 44.956|Ti titanium 47.867|
V vanadium 50.942|Cr chromium 51.996|Mn manganese 54.938|Fe iron 55.845|
Co cobalt 58.933|Ni nickel 58.693|Cu copper 63.546|Zn zinc 65.38|Ga gallium 69.723|
Ge germanium 72.630|As arsenic 74.922|Se selenium 78.971|Br bromine 79.904|
Kr krypton 83.798|Rb rubidium 85.468|Sr strontium 87.62|Y yttrium 88.906|
Zr zirconium 91.224|Nb niobium 92.906|Mo molybdenum 95.95|Tc technetium 98*|
Ru ruthenium 101.07|Rh rhodium 102.91|Pd palladium 106.42|Ag silver 107.87|
Cd cadmium 112.41|In indium 114.82|Sn tin 118.71|Sb antimony 121.76|
Te tellurium 127.60|I iodine 126.90|Xe xenon 131.29|Cs cesium 132.91|
Ba barium 137.33|La lanthanum 138.91|Ce cerium 140.12|Pr praseodymium 140.91|
Nd neodymium 144.24|Pm promethium 145*|Sm samarium 150.36|Eu europium 151.96|
Gd gadolinium 157.25|Tb terbium 158.93|Dy dysprosium 162.50|Ho holmium 164.93|
Er erbium 167.26|Tm thulium 168.93|Yb ytterbium 173.05|Lu lutetium 174.97|
Hf hafnium 178.49|Ta tantalum 180.95|W tungsten 183.84|Re rhenium 186.21|
Os osmium 190.23|Ir iridium 192.22|Pt platinum 195.08|Au gold 196.97|
Hg mercury 200.59|Tl thallium 204.38|Pb lead 207.2|Bi bismuth 208.98|
Po polonium 209*|At astatine 210*|Rn radon 222*|Fr francium 223*|Ra radium 226*|
Ac actinium 227*|Th thorium 232.04|Pa protactinium 231.04|U uranium 238.03|
Np neptunium 237*|Pu plutonium 244*|Am americium 243*|Cm curium 247*|
Bk berkelium 247*|Cf californium 251*|Es einsteinium 252*|Fm fermium 257*|
Md mendelevium 258*|No nobelium 259*|Lr lawrencium 266*|Rf rutherfordium 267*|
Db dubnium 268*|Sg seaborgium 269*|Bh bohrium 270*|Hs hassium 269*|
Mt meitnerium 278*|Ds darmstadtium 281*|Rg roentgenium 282*|Cn copernicium 285*|
Nh nihonium 286*|Fl flerovium 289*|Mc moscovium 290*|Lv livermorium 293*|
Ts tennessine 294*|Og oganesson 294*"""

_CH_MASS, _CH_NAME, _CH_NUM, _CH_BY_NAME, _CH_UNSTABLE = {}, {}, {}, {}, set()
for _i, _row in enumerate(x.strip() for x in _CH_RAW.replace("\n", "").split("|")):
    _sym, _nm, _ms = _row.split()
    if _ms.endswith("*"):
        _ms = _ms[:-1]
        _CH_UNSTABLE.add(_sym)
    _CH_MASS[_sym] = float(_ms)
    _CH_NAME[_sym] = _nm
    _CH_NUM[_sym] = _i + 1
    _CH_BY_NAME[_nm] = _sym
_CH_BY_NAME.update({"aluminium": "Al", "sulphur": "S", "caesium": "Cs"})

# Spoken names -> formula. The molar mass is then computed, not stored.
_CH_COMPOUND = {
    "water": "H2O", "heavy water": "D2O", "table salt": "NaCl", "salt": "NaCl",
    "sodium chloride": "NaCl", "glucose": "C6H12O6", "sucrose": "C12H22O11",
    "table sugar": "C12H22O11", "sugar": "C12H22O11", "carbon dioxide": "CO2",
    "carbon monoxide": "CO", "oxygen gas": "O2", "nitrogen gas": "N2",
    "hydrogen gas": "H2", "ozone": "O3", "ammonia": "NH3", "methane": "CH4",
    "ethane": "C2H6", "propane": "C3H8", "butane": "C4H10", "ethanol": "C2H6O",
    "methanol": "CH4O", "acetic acid": "C2H4O2", "sulfuric acid": "H2SO4",
    "hydrochloric acid": "HCl", "nitric acid": "HNO3", "phosphoric acid": "H3PO4",
    "sodium hydroxide": "NaOH", "potassium hydroxide": "KOH",
    "calcium carbonate": "CaCO3", "sodium bicarbonate": "NaHCO3",
    "baking soda": "NaHCO3", "calcium hydroxide": "Ca(OH)2", "magnesium oxide": "MgO",
    "aluminum oxide": "Al2O3", "iron oxide": "Fe2O3", "silicon dioxide": "SiO2",
    "hydrogen peroxide": "H2O2", "urea": "CH4N2O", "benzene": "C6H6",
    "caffeine": "C8H10N4O2", "aspirin": "C9H8O4", "acetone": "C3H6O",
    "ammonium nitrate": "NH4NO3", "calcium chloride": "CaCl2",
    "potassium chloride": "KCl", "sodium sulfate": "Na2SO4",
    "copper sulfate": "CuSO4", "silver nitrate": "AgNO3", "nitrous oxide": "N2O",
}
_CH_MASS["D"] = 2.014                      # deuterium, for heavy water
_CH_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)|(\()|(\))(\d*)")


def _ch_count(x: float) -> str:
    """Avogadro-scale counts spoken as powers of ten. '1204428152 quadrillion' is
    not a number anyone can hear."""
    if x >= 1e15:
        exp = math.floor(math.log10(x))
        return f"{x/10**exp:.3g} times ten to the {exp}"
    return _fmt_spoken(x)


def _ch_molar(formula: str):
    """Molar mass of a formula, parentheses included. None if any symbol is unknown."""
    stack, total = [], 0.0
    if not re.fullmatch(r"(?:[A-Z][a-z]?\d*|\(|\)\d*)+", formula):
        return None
    for m in _CH_TOKEN.finditer(formula):
        sym, count, open_p, close_p, close_n = m.groups()
        if open_p:
            stack.append(total)
            total = 0.0
        elif close_p:
            if not stack:
                return None
            total = total * (int(close_n) if close_n else 1) + stack.pop()
        else:
            if sym not in _CH_MASS:
                return None
            total += _CH_MASS[sym] * (int(count) if count else 1)
    return None if stack else total


def _ch_find(text: str, t: str):
    """(display name, formula, molar mass) for whatever compound was named."""
    for name in sorted(_CH_COMPOUND, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", t):
            f = _CH_COMPOUND[name]
            return name, f, _ch_molar(f)
    for nm, sym in _CH_BY_NAME.items():
        if re.search(r"\b" + nm + r"\b", t):
            return nm, sym, _CH_MASS[sym]
    for tok in re.findall(r"\b((?:[A-Z][a-z]?\d*|\([A-Za-z0-9]+\)\d*)+)\b", text):
        if len(tok) > 1 or tok in _CH_MASS:
            mass = _ch_molar(tok)
            if mass:
                return tok, tok, mass
    return None, None, None


def handle(text: str) -> Optional[str]:
    t = " " + text.lower().strip() + " "
    nums = numbers(text)

    # ── element facts ─────────────────────────────────────────────────────────
    if re.search(r"\batomic (?:mass|weight)\b", t):
        for nm, sym in _CH_BY_NAME.items():
            if re.search(r"\b" + nm + r"\b", t):
                tail = (" — it has no stable isotope, so that's its longest-lived one"
                        if sym in _CH_UNSTABLE else "")
                return (f"The atomic mass of {nm} is {_CH_MASS[sym]:g} atomic mass "
                        f"units{tail}.")
    if re.search(r"\batomic number\b", t):
        for nm, sym in _CH_BY_NAME.items():
            if re.search(r"\b" + nm + r"\b", t):
                return f"{nm.title()} is element number {_CH_NUM[sym]}, symbol {sym}."
    if re.search(r"\bsymbol for\b|\bchemical symbol\b", t):
        for nm, sym in _CH_BY_NAME.items():
            if re.search(r"\b" + nm + r"\b", t):
                return f"The symbol for {nm} is {sym}, element number {_CH_NUM[sym]}."

    # ── molar mass ────────────────────────────────────────────────────────────
    if re.search(r"\bmolar mass\b|\bmolecular (?:mass|weight)\b|\bformula (?:mass|weight)\b", t):
        name, formula, mass = _ch_find(text, t)
        if mass:
            said = f"{name} ({formula})" if name != formula else formula
            return f"The molar mass of {said} is {mass:.3f} grams per mole."
        return None

    # ── moles <-> grams ───────────────────────────────────────────────────────
    if re.search(r"\bmoles?\b", t) and re.search(r"\bgrams?\b", t):
        name, formula, mass = _ch_find(text, t)
        if mass and nums:
            # The question word decides the direction. "how many grams in 2 moles"
            # and "how many moles in 36 grams" mention both units in the same order,
            # so word order cannot be the signal — asking for grams and being told
            # moles is a fluent, confident, wrong answer.
            if re.search(r"how many grams?\b|\bgrams? (?:are |is )?in\b.*\bmoles?\b", t) \
                    and not re.search(r"how many moles?\b", t):
                want = "grams"
            elif re.search(r"how many moles?\b", t):
                want = "moles"
            else:
                want = "moles" if re.search(r"\bgrams?\b", t).start() < re.search(r"\bmoles?\b", t).start() else "grams"
            if want == "moles":
                grams = nums[0]
                return (f"{_fmt(grams)} grams of {name} is {grams/mass:.4g} moles, "
                        f"at {mass:.3f} grams per mole.")
            moles = nums[0]
            return (f"{_fmt(moles)} moles of {name} is {moles*mass:.4g} grams, "
                    f"at {mass:.3f} grams per mole.")

    # ── particle count ────────────────────────────────────────────────────────
    if re.search(r"\bhow many (?:atoms|molecules|particles)\b", t) and re.search(r"\bmoles?\b", t) and nums:
        n = nums[0] * _CH_NA
        return f"{_fmt(nums[0])} moles is {_ch_count(n)} particles, by Avogadro's number."

    # ── molarity ──────────────────────────────────────────────────────────────
    if re.search(r"\bmolarity\b|\bmolar concentration\b", t) and len(nums) >= 2 and nums[1]:
        return (f"{_fmt(nums[0])} moles in {_fmt(nums[1])} liters is "
                f"{nums[0]/nums[1]:.4g} molar.")

    # ── pH ────────────────────────────────────────────────────────────────────
    if re.search(r"\bp\.?h\b", t) and nums and nums[0] > 0:
        conc = nums[0]
        # -log10 of the concentration. For an acid that IS the pH; for a hydroxide it
        # is the pOH. Same arithmetic, two names, so the variable is named after the
        # arithmetic — calling it `ph` and then using it as pOH was correct and read
        # like a bug, which is its own kind of defect.
        neg_log = -math.log10(conc)
        kind = "acidic" if neg_log < 7 else "basic" if neg_log > 7 else "neutral"
        if re.search(r"\bhydroxide\b|\bpoh\b|\bbase\b", t):
            return (f"A {conc:.4g} molar hydroxide solution has a pOH of {_fmt(neg_log)}, "
                    f"so a pH of {_fmt(14-neg_log)}.")
        return f"A {conc:.4g} molar solution has a pH of {_fmt(neg_log)}, which is {kind}."

    # ── ideal gas ─────────────────────────────────────────────────────────────
    if re.search(r"\bideal gas\b|\bpv\s*=\s*nrt\b", t) or (
            re.search(r"\bmoles?\b", t) and re.search(r"\bkelvin\b", t)
            and re.search(r"\batmospheres?\b|\batm\b", t)):
        mo = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*moles?", t)
        kv = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*kelvin", t)
        at = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:atmospheres?|atm)", t)
        if mo and kv and at and float(at.group(1)):
            n, tk, p = float(mo.group(1)), float(kv.group(1)), float(at.group(1))
            v = n * _CH_R * tk / p
            atm_word = "atmosphere" if abs(p - 1) < 1e-9 else "atmospheres"
            return (f"{_fmt(n)} moles at {_fmt(tk)} kelvin and {_fmt(p)} {atm_word} "
                    f"occupies {v:.4g} liters.")

    return None


if __name__ == "__main__":
    for q in [
        "molar mass of water", "molecular weight of glucose", "molar mass of CaCO3",
        "molar mass of Ca(OH)2", "atomic mass of carbon", "atomic number of iron",
        "symbol for potassium", "atomic mass of technetium",
        "how many moles in 36 grams of water",
        "how many grams in 2 moles of glucose",
        "how many atoms in 2 moles", "molarity of 2 moles in 4 liters",
        "ph of a 0.001 molar solution",
        "volume of 2 moles at 300 kelvin and 1 atmosphere", "what time is it",
    ]:
        print(f"  {q:50} -> {handle(q)}")
