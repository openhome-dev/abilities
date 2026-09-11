#!/usr/bin/env python3
"""The shipped files must answer exactly what the hub answers.

The DevKit ability and the cloud Skill each carry an inlined copy of the engine. A copy
is a chance to disagree, and a disagreement here is the worst kind: the same sentence
answered one way on the device and another way in the cloud, with both sounding sure.

This runs the ENGINE REGION lifted straight out of each shipped file — not the hub
modules — against the hub, over every phrase the golden suite covers. It also asserts
the generator has been run, so an edit to hub/ that never reached the artifacts fails
here rather than on the device.

Run:  python3 test_artifact_parity.py
"""
import pathlib
import re
import subprocess
import sys
from datetime import datetime

import engine
from test_golden import GOLDEN, ROUTED, SILENT, NOW

HUB = pathlib.Path(__file__).resolve().parent
REPO = HUB.parent
BEGIN = "# ===== ASTRAL ENGINE"
END = "# ===== END ASTRAL ENGINE ====="

ARTIFACTS = ["community/astral/devkit_functions.py", "community/astral-skill/main.py"]
if not (REPO / "community").is_dir() and (REPO / "main.py").is_file():
    ARTIFACTS = ["main.py"]          # upstream layout: hub/ ships inside the ability folder


def load_region(rel: str):
    """Exec just the generated engine region, with nothing else from the file.

    Running it standalone is also the test that the region really is self-contained:
    if a generated function reaches for something defined in the device wrapper or in
    the capability class, it raises here instead of on the Pi."""
    src = (REPO / rel).read_text()
    start = src.index(BEGIN)
    stop = src.index(END) + len(END)
    # The platform comments out `from __future__ import annotations` on upload, so the
    # shipped file must not rely on it: every annotation has to evaluate eagerly on the
    # runtime's Python, which for the DevKit is whatever the image ships. So the host
    # may not carry the future import as CODE (a comment mentioning it is fine), the
    # region may not use PEP 604 unions, and the exec below adds nothing — if a
    # `str | None` slips back in, it raises right here on Python 3.9.
    code_lines = [ln for ln in src[:start].splitlines() if ln.startswith("from __future__")]
    assert not code_lines, f"{rel} carries a future import the platform will strip: {code_lines}"
    region = src[start:stop]
    bad = [ln for ln in region.splitlines() if re.search(r"\bNone \||\| None\b", ln)]
    assert not bad, f"{rel} engine region uses PEP 604 unions the runtime cannot evaluate: {bad[:3]}"
    ns = {"re": re, "datetime": datetime, "__name__": "astral_region"}
    exec(compile(region, rel, "exec"), ns)
    return ns


def main() -> int:
    corpus = [t for (_, t) in GOLDEN] + list(ROUTED) + SILENT
    fails = 0

    print("── generator is up to date ─────────────────────────────────────────")
    r = subprocess.run([sys.executable, str(HUB / "build_ability.py"), "--check"],
                       capture_output=True, text=True, cwd=REPO)
    print("  " + r.stdout.strip().replace("\n", "\n  "))
    fails += r.returncode != 0

    for rel in ARTIFACTS:
        print(f"\n── {rel} ─────────────────────────────────")
        try:
            ns = load_region(rel)
        except Exception as exc:
            print(f"  [FAIL] engine region will not run standalone: {exc!r}")
            fails += 1
            continue
        answer = ns.get("astral_answer")
        if not answer:
            print("  [FAIL] no astral_answer in the generated region")
            fails += 1
            continue
        bad = 0
        for text in corpus:
            want = engine.answer(text, NOW)
            got = answer(text, NOW)
            if (got or "") != (want or ""):
                bad += 1
                print(f"  [FAIL] {text!r}\n         hub      {want!r}\n         artifact {got!r}")
        fails += bad
        print(f"  {len(corpus) - bad}/{len(corpus)} phrases identical to the hub")

    print(f"\n{'PASS' if not fails else 'FAIL'} — {len(corpus)} phrases × "
          f"{len(ARTIFACTS)} artifacts")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
