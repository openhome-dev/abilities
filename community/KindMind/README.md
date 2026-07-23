# KindMind

An AI Emotional Stabilizer, built as an OpenHome Ability.

KindMind's only job is to help someone become calmer, safer, and more grounded — one step at a time, at *their* pace. It never advances to the next step of an exercise until the person has actually affirmed they're ready, and everything it says is generated live by an LLM rather than read from a script.

## How it works

```
Emotion → Stabilize → [ User chooses → Feature → Check in → Continue if needed ]
```

1. **Emotion** — KindMind listens first, and checks specifically for panic-level distress (a deliberate, deterministic override, since that's the one moment where guessing wrong matters most).
2. **Stabilize** — routes into whichever response fits best: guided breathing, grounding, mindfulness, tiny next step, safe space mode, or panic mode. This choice is made by one open LLM judgment over the full message, not a rigid keyword→response table.
3. **The loop** — once stabilized, the person chooses what happens next (another technique, a mood booster, building a comfort plan, or wrapping up), KindMind delivers it, checks in on how they feel, and asks if they'd like to continue. This repeats until they're done — a real, open-ended conversation, not a fixed script.

Every multi-step exercise is gated by the same primitive: `wait_for_ready()` — speak, listen, and only move forward on a real affirming signal. Saying "stop" at any point exits cleanly and hands control back to the Agent.

## Features

| Feature | What it does |
|---|---|
| Emotion Detection | Reads what's going on from the first thing the person says |
| Guided Breathing | In → hold → out, paced to how the person is speaking |
| Grounding (5-4-3-2-1) | One sense at a time, waits for a real answer before moving on |
| Mindfulness | A gentle present-moment pause — body, breath, one sense |
| Tiny Next Step | For overwhelm — narrows to one 5-minute task |
| One-Minute Reset | A compressed version for when someone doesn't want a long conversation |
| Panic Mode | Interrupt-priority; tightly guided, literal reassurance only |
| Safe Space Mode | Pure listening — no advice, no redirection |
| Comfort Plan | Built with the user, not handed to them — a story, music suggestion, or encouragement, based on what they say they want |
| Quotes & Affirmations | Offered, never automatic |
| Mood Check-In | Closes every pass through the loop |

## Trigger words

`I need to calm down` · `help me breathe` · `I'm panicking` · `ground me` · `I feel anxious` · `talk me down` · `I need some comfort` · `check on me` · `kindmind`

## Files

- `main.py` — the Ability itself (`KindmindCapability`)
- `__init__.py` — package init

## Known limitations (be honest with judges about these)

- **Classifier reliability is untested at scale.** Every routing decision (emotion, affirmation, feature choice) depends on the LLM returning one clean word. It generally will, but hasn't been stress-tested against messy real speech.
- **No crisis-escalation path.** KindMind handles panic and distress, but doesn't currently recognize or route on signs of actual self-harm risk. Worth a deliberate conversation before this goes anywhere beyond a hackathon demo.
