# Celebration Engine

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@rawqubit-lightgrey?style=flat-square)

## What It Does

A background daemon that silently monitors your conversations for positive moments — wins, achievements, good news, milestones. When it detects one, it celebrates with you naturally. Most AI abilities only activate on problems. **This one notices when things go right.**

## Category

**Background Daemon + Interactive Skill** — the daemon (`background.py`) starts automatically when the session begins and needs no trigger words. The companion skill (`main.py`) lets you review your logged wins on demand.

## Suggested Trigger Words

For the interactive wins-recap skill:

- "my wins"
- "celebration recap"
- "what went well"
- "show my wins"
- "recap my wins"

## Setup

No API keys required. Runs entirely on the built-in LLM and conversation history.

## How It Works

1. **Listens silently** by polling conversation history every 30 seconds
2. **Scans for positive signals** using keyword detection (cheap, fast)
3. When a signal is detected, runs **LLM analysis** to confirm it's a genuine win
4. **Interrupts briefly** to celebrate — one warm, natural sentence
5. **Logs the win** to persistent storage for future recap
6. **Rate-limits** celebrations (minimum 15 messages between them)

## Detection Signals

The engine looks for phrases like:
- "I got the job", "I passed", "I won", "promotion"
- "They said yes", "deal closed", "signed the contract"
- "I graduated", "finally done", "best day ever"
- "So excited", "so proud", "great news", "amazing news"

## What Makes It Special

| Feature | Description |
|---------|-------------|
| Background-only | No trigger words — it's always listening |
| Two-stage detection | Keyword scan (fast) → LLM analysis (accurate) |
| Rate limiting | Won't celebrate too often — wins during the cooldown are deferred, not dropped |
| Persistent win log | Stores wins for recap on demand via the interactive skill |
| Contextual responses | LLM generates celebration matching the energy level |
| Non-intrusive | One sentence max, then gets out of the way |

## Example Behavior

> **User (talking to agent):** "Oh my god, I just got the email — I got the promotion!"
> **Agent:** *(continues normal flow)*
> **Celebration Engine:** *(detects win signal, runs LLM analysis)*
> **Celebration Engine:** "That promotion is well-deserved — congratulations!"
> *(returns to normal conversation)*

## Data Files

- `celebration_engine_wins.json` — log of detected positive moments (last 100)

## Technical Notes

- Uses `send_interrupt_signal()` before speaking (required for background daemons)
- Polls every 30 seconds via `session_tasks.sleep()`
- `CapabilityWorker` initialized with `self.worker`, matching the other background daemons in this repo
- No `resume_normal_flow()` — this is a standalone daemon
