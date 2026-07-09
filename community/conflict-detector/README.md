# Conflict Detector

A passive background ability that extracts your plans and commitments from natural conversation and cross-checks every new one against existing ones for scheduling conflicts. When a clash is detected, it interrupts immediately — naming both commitments and explaining exactly why they conflict.

Just talk naturally — "I'll call Marcus on Friday", "flying out Thursday night", "meeting with the team Monday morning". Conflict Detector captures it all silently and flags contradictions the moment they appear.

## Trigger Phrases

- `conflict detector` / `my conflicts` / `any conflicts`
- `check my conflicts` / `conflicting plans` / `schedule conflicts`
- `what have I committed to` / `my commitments` / `what commitments do I have`
- `check my schedule` / `what's on my plate` / `what do I have coming up`
- `add a commitment` / `log a commitment`
- `dismiss this conflict` / `ignore this conflict`
- `clear my commitments` / `wipe my conflicts`

## Features

**Passive Capture**
- Listens every 15 seconds, zero friction
- Word count gate + LLM commitment extractor
- Captures type (meeting / call / travel / task / social / deadline), people involved, date, time, and duration per commitment
- Natural date resolution: day names, relative phrases ("after the weekend", "in 3 days"), specific dates ("May 10th")
- 70% word overlap dedup prevents capturing the same plan twice
- Only captures definite commitments — skips maybes, hypotheticals, and vague plans with no time reference

**Conflict Detection**
- Two-phase check: free same-date scan first, LLM only when a candidate is found
- Adjacent-day travel detection — overnight travel flagged against next-morning commitments
- Conflict pair dedup so the same clash never fires twice
- Severity classification: hard (impossible to do both) vs soft (tight but possible)
- Proactive interrupt: "Heads up — you said you'd [A] but you also mentioned [B]. [reason]."

**Interactive Queries**
- LIST: Upcoming commitments sorted by date, with open conflict count
- CONFLICTS: Open conflicts sorted by severity, dismiss individually or all at once
- ADD: Manually log a commitment with date and optional time
- DISMISS: Remove a specific detected conflict
- CLEAR: Wipe all commitments and conflicts (with confirmation)

**Smart Maintenance**
- Daily stale commitment expiry — past commitments auto-archived to prevent false positives
- Startup notification if unalerted conflicts exist from a previous session
- Persists across session disconnects

## Setup

No external APIs or keys required.
