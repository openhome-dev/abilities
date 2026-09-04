# The engine

`main.py` next door is generated from these files. Edit here, then run:

```bash
python3 hub/build_ability.py          # rewrite main.py from the sources
python3 hub/build_ability.py --check  # fail if main.py is out of date
```

One module per subject: `mechanical.py` (time and date), `calc.py` (arithmetic, money,
ten unit dimensions), `study.py` (grades and GPA), `chem.py` (the periodic table, molar
mass by formula parse, moles, molarity, pH, ideal gas), `sci.py` (mechanics, planet mass
and size, gravity, relativity, light), `stats.py` (descriptive statistics and counting),
`mathx.py` (bases, logs, trig, primes, quadratics, fractions). `engine.py` is the one
router they sit behind. Pattern and table code, standard library only, no model, no
network. A module returns nothing when the question is not its business, so the agent
takes the turn.

## Tests

```bash
cd hub
python3 test_golden.py            # 155 phrases pinned byte for byte, silence included
python3 test_artifact_parity.py   # main.py answers every phrase exactly as the source does
python3 test_hardening.py         # four thousand generated utterances, every result rechecked a second way
```

The parity test also holds two rules the platform imposes. The uploaded file must not
carry `from __future__ import annotations`, because the platform comments that line out,
and the engine must not use a PEP 604 union, because without that import a `str | None`
annotation is evaluated eagerly and quietly requires Python 3.10. The test execs the
generated region with nothing added, so a slip fails on Python 3.9 here rather than on a
device.

The same directory also builds the DevKit ability's `devkit_functions.py` when it sits
beside a `community/` tree. In this repo there is one target, the `main.py` next door.
