# Curiosity Queue

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-hassan1731996-blue?style=flat-square)

Passively captures moments when you voice genuine curiosity — *"I wonder how X works"*, *"I don't know why Y"*, *"I should look that up"* — and silently queues them. Ask anytime to hear your list, get spoken explanations, or add items manually.

## What It Does

A passive background daemon listens to your conversation every 15 seconds. When you express intellectual curiosity, it quietly saves the topic. Later, ask *"what am I curious about?"* to review your queue and get LLM-generated answers spoken aloud.

## Trigger Words

- `what am I curious about`
- `my curiosity queue` / `curiosity queue`
- `what have I been wondering`
- `show my curiosities` / `curiosity list`
- `explain one of my curiosities`
- `random curiosity`
- `add to my curiosity queue`
- `notify me when you capture`
- `stop notifying me`
- `clear answered curiosities`

## How It Works

1. **Background daemon starts automatically** when you connect a session — no trigger needed
2. Every 15 seconds it checks new messages for curiosity-expressing phrases
3. A two-phase filter catches genuine intellectual wonder (fast keyword scan → LLM classifier)
4. Duplicate topics are skipped using 60% word-overlap detection
5. Say *"what am I curious about?"* to hear your pending queue
6. Say *"explain it"* or *"explain the first one"* to get a spoken answer
7. Topics are marked as answered and saved — history is always available

## Features

- **Passive capture** — just talk naturally, no trigger word needed to add items
- **Two-phase detection** — fast keyword filter + LLM classifier to minimize false positives
- **Smart dedup** — 60% word-overlap check prevents capturing the same topic twice
- **LLM answers** — 3-4 sentence conversational explanations, spoken aloud
- **Explore modes** — explain one, explain all, pick by number or say "random"
- **Manual add** — `add to my curiosity queue: why do cats purr`
- **Instant explain mode** — get a spoken notification every time a topic is captured
- **History** — see your last 5 answered curiosities
- **Persistent** — queue survives session disconnects
- **Queue management** — clear answered items or clear everything

## What Gets Captured

| Captured | Not Captured |
|---|---|
| "I wonder how neural networks learn" | "What's the weather today?" |
| "I've always wondered why the sky is blue" | "Can you play some music?" |
| "I don't know why inflation causes interest rates to rise" | "What time is it?" |
| "I should look up how vaccines work" | "Yes, okay, thanks" |
| "Funny how time seems to slow down when you're scared" | "How do I turn this off?" |

## Example Conversation

**User:** *(talking naturally)* "I wonder how black holes actually form. Like, what starts that process?"

*(15 seconds pass — daemon captures it silently)*

**User:** "What am I curious about?"

**Coach:** "You have 1 curiosity waiting. 1. how black holes actually form. Want me to explain it? Say a number, say 'random', or say stop."

**User:** "Yes, explain it."

**Coach:** "Black holes form when a massive star — at least 20 times the mass of our sun — runs out of nuclear fuel and collapses under its own gravity. The collapse is so violent that nothing, not even light, can escape the resulting singularity. What's fascinating is that the boundary you can't escape from, called the event horizon, isn't a physical surface — it's just a point of no return in space. And here's the mind-bending part: somewhere in the universe right now, a star is collapsing into a black hole as we speak."

**User:** "Add to my curiosity queue: why do we dream?"

**Coach:** "Added! You now have 1 curiosity to explore."

## Notification Mode

Say **"notify me when you capture a curiosity"** to enable instant notifications — each time a topic is captured, you'll hear: *"Just added to your curiosity queue: [topic]. Ask me to explain anytime."*

Say **"stop notifying me"** to return to silent capture mode.

## Storage

All data is stored in `curiosity_queue.json`:
- **Queue** — up to 50 pending and answered items
- **History** — up to 100 archived/answered items
- **Settings** — instant explain preference
- **Stats** — total captured and answered counts

## Setup

No external API keys required. Uses your agent's built-in LLM for curiosity classification and answer generation.
