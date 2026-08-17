# Astral — deterministic base capability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Skill](https://img.shields.io/badge/Category-Skill-green?style=flat-square)

Instant answers for the things with one right answer: time, date, math, money, unit conversions, grades, chemistry, physics, statistics, and number tools. Computed directly, no model. Anything else passes to your agent.

This is the generalized version of the `date-and-time` base capability. The whole engine is inlined in `main.py` (pattern and table code, no `eval`), so it runs anywhere an agent runs, no DevKit required.

## Category

**Skill.** Trigger words route a phrase here; the engine answers and the agent handles the rest.

## What it answers

- Time and date, in the agent's timezone.
- Math: add, subtract, multiply, divide, percentages, powers, roots, factorials.
- Money: tips, tax, splitting a bill.
- Unit conversions: weight, length, volume, temperature, speed, area, time, energy,
  pressure, force, data sizes, and astronomical distances.
- Grades: what you need on the final, weighted totals, percent to letter, score out of
  total, GPA over credits.
- Chemistry: molar mass for a named compound or a formula, moles and grams, molarity,
  pH, the ideal gas law, atomic mass and number for all 118 elements.
- Physics: escape velocity and surface gravity for the Sun, the Moon and every planet,
  weight on another world, free fall, kinetic and potential energy, momentum, force,
  work, power, Ohm's law, time dilation, Schwarzschild radius, photon energy, light
  travel time.
- Statistics: mean, median, mode, range, variance, sample and population standard
  deviation, z scores, combinations and permutations.
- Number tools: binary, hex and octal, logs, trig, GCD and LCM, primes and prime
  factors, modulo, the quadratic formula, percent change, fractions, significant
  figures, scientific notation.

Examples:

```
what time is it                    -> It's 3:55 pm.
what's twenty percent of eighty     -> 20 percent of 80 is 16.
convert ten pounds to kilograms     -> 10 pounds is 4.54 kilograms.
eighteen percent tip on forty five dollars
                                    -> A tip of 18 percent on 45 dollars is 8.1 dollars, for a total of 53.1.
I have an 87 and the final is worth 20 percent, what do I need to get a 90
                                    -> You'd need 102 percent on the final for 90 percent,
                                       which isn't possible. A perfect final leaves you at 89.6 percent.
molar mass of water                 -> The molar mass of water (H2O) is 18.015 grams per mole.
escape velocity of mars             -> Escape velocity at Mars is 5.02 kilometers per second,
                                       11234.25 miles per hour.
standard deviation of 4 6 8 10      -> The sample standard deviation of 4, 6, 8, 10 is 2.58,
                                       around a mean of 7.
is 91 prime                         -> No, 91 isn't prime. It's 7 times 13.
tell me a joke                       -> (nothing; the agent takes it)
```

Two things it says out loud rather than assuming. Anything resting on a grading scale
names the scale, because a scale is a convention and not a fact. A standard deviation
says whether it is the sample or the population one, because those are different numbers
and a course grades you on which you used.

## Suggested trigger words

Set these in the dashboard:

`what time`, `what's the time`, `what's the date`, `what day is it`, `calculate`, `what's`, `how much is`, `percent of`, `square root of`, `convert`, `how many`, `tip on`, `tax on`, `split`, `what do i need`, `what letter grade`, `out of`, `weighted`, `gpa`, `molar mass`, `how many moles`, `atomic mass`, `atomic number`, `molarity`, `ph of`, `escape velocity`, `surface gravity`, `kinetic energy`, `momentum`, `how long does light`, `average of`, `mean of`, `median of`, `standard deviation`, `z score`, `choose`, `in binary`, `in hexadecimal`, `log of`, `sine of`, `prime factors`, `quadratic`, `percent change`, `simplify`, `significant figures`

## How it works

`main.py` is a `MatchingCapability`. On a trigger word it takes the transcript, normalizes the punctuation, routes it through the inlined engine, and speaks the answer. The engine is one router with a fixed order: time and date first, then grades, chemistry, physics, statistics, number tools, and plain arithmetic last. Specific before general, because the general one will match a fragment of a specific question. If nothing matches, it speaks nothing and calls `resume_normal_flow()` so the agent takes the turn. Never blocks, never blanket-denies.

## Accuracy

Every answer is a formula over a table, so it is either exactly right or it does not
answer. Unit factors are the exact defined values. Molar masses are computed by parsing
the formula against the element table rather than stored per compound, because a
hand-entered constant is a typo waiting to be spoken with confidence. Surface gravity
and escape velocity are computed from mass and equatorial radius and agree with
published figures for eight bodies to better than half a percent.

120 answers are asserted byte-exact in the source repo, alongside a suite that fuzzes
four thousand utterances and rechecks every result a second independent way — statistics
against Python's own `statistics` module, factorizations multiplied back out, physics
against published constants.

## Requirements

Python standard library only. No API keys, no external services.

## Note

This version computes in the cloud, without the LLM. For the fully on-device, no-network path (wake and speech-to-text on the DevKit too), see the local DevKit build.
