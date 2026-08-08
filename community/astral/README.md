# Astral — deterministic base capability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Skill](https://img.shields.io/badge/Category-Skill-green?style=flat-square)

Instant answers for the everyday things with one right answer: time, date, math, money, and unit conversions. Computed directly, no model. Anything else passes to your agent.

This is the generalized version of the `date-and-time` base capability. The whole engine is inlined in `main.py` (pattern and table code, no `eval`), so it runs anywhere an agent runs, no DevKit required.

## Category

**Skill.** Trigger words route a phrase here; the engine answers and the agent handles the rest.

## What it answers

- Time and date, in the agent's timezone.
- Math: add, subtract, multiply, divide, percentages, square root.
- Money: tips, tax, splitting a bill.
- Unit conversions: weight, length, volume, temperature.

Examples:

```
what time is it                    -> It's 3:55 pm.
what's the date                     -> Today is Friday, August 7, 2026.
what's twenty percent of eighty     -> 20 percent of 80 is 16.
convert ten pounds to kilograms     -> 10 pounds is 4.54 kilograms.
eighteen percent tip on forty five dollars
                                    -> A tip of 18 percent on 45 dollars is 8.1 dollars, for a total of 53.1.
square root of 155                  -> The square root of 155 is 12.45.
tell me a joke                       -> (nothing; the agent takes it)
```

## Suggested trigger words

Set these in the dashboard:

`what time`, `what's the time`, `what's the date`, `what day is it`, `calculate`, `what's`, `how much is`, `percent of`, `square root of`, `convert`, `how many`, `tip on`, `tax on`, `split`

## How it works

`main.py` is a `MatchingCapability`. On a trigger word it takes the transcript, normalizes the punctuation, routes it through the inlined engine (time and date first, then math, money, and conversions), and speaks the answer. If nothing matches, it speaks nothing and calls `resume_normal_flow()` so the agent takes the turn. Never blocks, never blanket-denies.

## Requirements

Python standard library only. No API keys, no external services.

## Note

This version computes in the cloud, without the LLM. For the fully on-device, no-network path (wake and speech-to-text on the DevKit too), see the local DevKit build.
