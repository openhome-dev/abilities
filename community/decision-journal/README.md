# Decision Journal

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-hassan1731996-blue?style=flat-square)

Passively captures the decisions you make in conversation — *"I decided to take the startup job"*, *"I'm going with the Toyota"*, *"I'm torn between two offers"* — and stores them with context. Later, review your decisions, record how they turned out, run reflective sessions, and hear patterns in how you decide.

## What It Does

A passive background daemon listens every 15 seconds. When you make or deliberate on a significant decision, it quietly logs it. Ask anytime to review your journal, record outcomes, reflect on a specific choice, or get an LLM-synthesized read on your decision-making style.

## Trigger Words

- `decision journal` / `my decisions` / `my decision journal`
- `what decisions have I made` / `show my decisions`
- `how did that decision turn out` / `record an outcome` / `decision outcome`
- `my decision patterns` / `what patterns do you see in my decisions`
- `reflect on a decision` / `help me reflect on a decision`
- `add a decision` / `log a decision`
- `clear my decisions` / `decision stats`
- `notify me when you capture a decision` / `stop notifying me about decisions`

## How It Works

1. **Background daemon starts automatically** when you connect a session
2. Every 15 seconds it scans new messages for decision-making language
3. A two-phase filter catches genuine significant decisions (fast keyword scan → LLM significance classifier)
4. Trivial choices ("I'll grab coffee") are filtered out — only meaningful decisions are captured
5. Say *"decision journal"* to review your queue, record outcomes, or explore patterns
6. After 14 days without an outcome on a major decision, you'll get a gentle follow-up nudge

## Features

- **Passive capture** — just talk naturally, no trigger word needed to log decisions
- **Two-phase detection** — keyword filter + LLM classifier to avoid trivial or third-party decisions
- **Deliberation tracking** — captures "I'm torn between X and Y" before the decision is made
- **Outcome recording** — mark decisions as good call, bad call, mixed, or too soon to tell
- **Reflection sessions** — 2-round guided reflection with thoughtful follow-up questions
- **Pattern analysis** — LLM synthesizes 2-3 concrete patterns from your decision history (needs 5+ decisions)
- **Stale-outcome nudge** — gentle daily reminder for HIGH significance decisions after 14 days
- **Startup notification** — hear pending-outcome count when you reconnect (if 2+)
- **Daily briefing** — reminder at start of new day if decisions need outcomes
- **Manual add** — `add a decision: [topic]` with category and alternative prompts
- **Category grouping** — career / financial / health / relationship / personal / other
- **Persistent** — journal survives session disconnects
- **Dedup** — 60% word-overlap check prevents capturing the same decision twice

## What Gets Captured

| Captured | Not Captured |
|---|---|
| "I decided to take the startup job" | "Should I take the job?" (asking agent) |
| "I'm going with the Toyota over the Honda" | "I'll grab coffee" (trivial) |
| "I've made up my mind — I'm moving to Austin" | "She decided to quit" (third party) |
| "I'm torn between two job offers" | "I'll check my email" (daily task) |
| "I committed to starting therapy" | "What would you do?" (directed at agent) |

## Example Conversation

**User:** *(talking naturally)* "I've made up my mind — I'm going with the startup offer over the corporate one."

*(15 seconds pass — daemon captures it silently)*

**User:** "Decision journal."

**Coach:** "You have 1 decision logged. 1 career decision: take the startup offer over the corporate one. It still needs an outcome. Want me to review it, record an outcome, or show your decision patterns?"

**User:** "Reflect on it."

**Coach:** "Looking back — what made the startup feel like the right call over the stability of the corporate offer?"

**User:** "Honestly, I just couldn't see myself being happy in a big company."

**Coach:** "That's a really self-aware answer — knowing what you need from your work environment is often the clearest signal. The logical arguments can go either way, but your gut was telling you something about fit, not just opportunity."

*(Two weeks later, unprompted)*

**Coach:** "It's been over 2 weeks since you decided to take the startup offer. How's that going? Say 'decision journal' to update it."

## Storage

All data is stored in `decision_journal.json`:
- **Decisions** — up to 50 active items (pending + resolved)
- **History** — up to 100 archived items
- **Settings** — notify_on_capture, last_brief_date, last_nudge_date
- **Stats** — total captured and total with outcomes
- **Meta** — session pointer for reconnect deduplication

## Setup

No external API keys required. Uses your agent's built-in LLM for decision classification, reflection, and pattern analysis.
