# Voice Shadow

Get honest, unfiltered feedback on any idea — startup pitch, life decision, business plan, creative project. Voice Shadow uses Venice's uncensored model to give you the structured critique that polite people and safety-tuned AIs won't.

## Trigger Phrases

- "shadow my idea"
- "be brutally honest"
- "tear this apart"
- "tear apart my [idea]"
- "honest critique"
- "find the flaws"
- "stress test my [plan]"
- "reality check my [idea]"
- "poke holes in [this]"
- "what's wrong with my [idea]"
- "sanity check my [plan]"
- "brutal feedback"
- "voice shadow"
- "honest feedback on [this]"

## What It Does

1. You pitch any idea in natural speech — one sentence or several
2. Voice Shadow delivers a 4-part structured critique:
   - The core flaw in the logic
   - The first objection anyone will raise
   - The hidden assumption that might be wrong
   - The one angle that actually has potential
3. You can ask it to dig deeper on any specific point
4. Bring another idea without restarting — just pitch it

## Example Session

> "shadow my idea"
>
> *Ready. Pitch me the idea — startup, plan, decision, anything.*
>
> "I want to build an app that connects freelancers with local businesses — like Fiverr but hyperlocal and focused on in-person services"
>
> *The core flaw is that in-person hyperlocal kills the scale advantage that makes marketplaces work — you're adding the friction of geography without a clear reason why businesses prefer you over Craigslist. Anyone who hears this will immediately ask why a local business needs a platform for tasks they currently solve with a phone call. Your assumption that businesses want a new discovery channel for local freelancers may be wrong — most already have a trusted person they call. The part that actually works is the trust layer — if you can build verified reviews for in-person work, that's the real gap.*
>
> "dig into the trust layer part"
>
> *Local service trust is unsolved because review platforms like Yelp are review-bombed and one-sided. If you require job completion confirmation from both sides before a review posts, you get verified two-way accountability — that's the moat Fiverr never built for in-person work.*

## Setup

Add your Venice API key in OpenHome settings:

| Key | Value |
|-----|-------|
| `venice_api_key` | Your Venice API key from [venice.ai](https://venice.ai) |

## Storage

Voice Shadow saves up to 10 past idea critiques locally so sessions are preserved. No data leaves your device except the Venice API call.

## What Makes It Different

- **Not a debate** — `debate-partner` takes an opposing side in structured rounds with scoring. Voice Shadow evaluates *your* material with no sides, no rounds, no scoreboard.
- **Not a game** — `hot-take-machine` generates AI opinions on random pop-culture topics as a competitive game. Voice Shadow is advisor mode: user-led, idea-specific, improvement-focused.
- **Genuinely uncensored** — Uses Venice's `abliteration-abliterated-model-large-v2` with Venice's system prompt disabled. No safety hedging, no "with some refinement this could work" qualifiers.
