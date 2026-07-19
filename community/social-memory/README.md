# Social Memory

A passive background ability that silently captures every person you mention in natural conversation and builds relationship context over time.

Just talk naturally — "had lunch with Sarah", "Jake pushed back on the proposal", "I said I'd call Marcus after the weekend". Social Memory captures it all without interrupting you. Say "social memory" anytime to query what you know about someone or review pending follow-ups.

## Trigger Phrases

- `social memory` / `my social memory`
- `tell me about [name]` / `remind me about [name]`
- `what do I know about [name]` / `what have I said about [name]`
- `who have I mentioned` / `people I've mentioned`
- `any follow-ups` / `pending follow-ups`
- `who do I owe` / `who should I reach out to`
- `add a note about [name]`
- `forget about [name]`
- `clear my social memory`

## Features

**Passive Capture**
- Listens every 15 seconds, zero friction
- Two-phase detection: fast keyword filter + LLM person extractor
- Captures name, relationship hint, context snippet, and speaker relation
- Only captures people you personally know — skips public figures and service references
- Distinguishes direct interactions ("I met with Sarah") from indirect mentions ("she told me about Jake")
- Smart dedup: 70% snippet overlap prevents capturing the same context twice
- Persists across session disconnects

**Follow-Up Tracking**
- Detects commitments in natural speech: "I'll call Marcus after the weekend"
- Resolves natural deadlines: "by Friday", "next week", "after the weekend"
- Nudges you when follow-ups go overdue (default: 3 days past deadline)
- One nudge per follow-up per day, at most one interrupt per poll cycle

**Interactive Queries**
- WHO: Full context on any person — relationship, recent mentions, pending follow-ups
- LIST: Everyone you've mentioned, sorted by recency, with follow-up count
- FOLLOWUPS: Sorted by most overdue, mark one or all done
- ADD: Manually note someone with optional follow-up
- FORGET: Remove a specific person
- CLEAR: Wipe all social memory (with confirmation)

**Personality Injection**
- Injects relationship context into the agent's personality when new people are captured
- Capped at 4 injections per session to avoid prompt bloat
- Startup notification if pending follow-ups exist on reconnect

## Setup

No external APIs or keys required.
