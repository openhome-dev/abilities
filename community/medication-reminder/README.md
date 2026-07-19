# Medication Reminder

Voice-first medication manager for OpenHome. Set up your full medication schedule in one utterance, get contextual reminders with food/timing instructions, acknowledge doses by voice, snooze reminders, track refill supply, and get a weekly adherence report — all hands-free.

**No API keys required.** Optionally queries OpenFDA for drug information (free, no key).

---

## Trigger Phrases

| What you say | What happens |
|---|---|
| "add metformin 500mg twice a day with meals and aspirin at night" | Sets up both medications in one shot |
| "I took my metformin" | Logs dose as taken, clears the reminder |
| "remind me in 30 minutes" | Snoozes the current reminder |
| "skipping this one" | Logs dose as intentionally skipped |
| "what medications do I have today?" | Status: taken, overdue, upcoming |
| "how have I been with my medications?" | Weekly adherence report |
| "what is metformin for?" | Drug information via OpenFDA + LLM |
| "I just refilled my metformin, 90 tablets" | Updates supply count |
| "remove aspirin from my schedule" | Deactivates medication |

---

## Setup — Natural Language Parsing

You can add multiple medications in a single sentence. The LLM extracts name, dose, schedule, and food/timing instructions automatically.

**Examples:**
- *"Take lisinopril 10mg once in the morning and metformin 500mg twice a day with meals"*
- *"Add aspirin 100mg at bedtime"*
- *"I need to take three medications: atorvastatin at night, metformin with breakfast and dinner, and vitamin D in the morning"*

Default times if not specified: morning = 8am, afternoon = 1pm, evening = 6pm, night/bedtime = 9pm.

After setup, you'll be asked if you want to track your supply for refill alerts.

---

## Within a Session

After any response, you can continue the conversation:
- Say **"status"** — see what's taken, overdue, and upcoming today
- Say **"report"** — weekly adherence percentage per medication
- Say **"what is [medication] for"** — drug information
- Say **"refill"** — update your supply count
- Say **"done"** or **"stop"** to exit

---

## Background Daemon

The daemon runs every 60 seconds and:

| Event | What fires |
|---|---|
| Scheduled dose time reached | Contextual reminder: *"Time for your Metformin 500mg — take it with your meal."* |
| 10 minutes with no acknowledgment | Gentle follow-up: *"Did you take your Metformin?"* |
| 30 minutes with no acknowledgment | Dose marked as missed in your log |
| Snooze expires | Reminder re-fires |
| Supply drops below 7 days | Refill alert fires once per day |

### Streak Motivation
If you've taken a medication consistently for 5+ days, the reminder includes your streak: *"You've kept up 7 days in a row — great work."*

---

## Adherence Report

On-demand summary of the last 7 days:
> *"You took 11 out of 14 scheduled doses this week — 79% adherence. You missed 2 Metformin doses and 1 Aspirin dose."*

---

## Supply Tracking

Set your tablet count when prompted during setup (or say "refill" anytime). The daemon calculates days remaining based on your doses-per-day and alerts you proactively when you're within 7 days of running out.

---

## Data Source

| Source | Use | Key required |
|---|---|---|
| KV Storage (local) | Medication schedule, dose log, pending alerts | None |
| [OpenFDA](https://api.fda.gov) | Drug indication information | None |
| Built-in LLM | Schedule parsing, adherence reports, drug info fallback | None |
