# Sleep Logger

A voice-based sleep tracker with persistent storage and LLM-powered analysis. Log your sleep, view weekly summaries, and discover patterns in your sleep habits.

## Triggers

- "sleep tracker"
- "log sleep"
- "sleep logger"
- "how did I sleep"
- "sleep summary"

## Features

- Log bedtime, wake time, quality (1-5), and notes via voice
- Automatic sleep duration calculation
- Weekly summaries with averages and best/worst nights
- Trend analysis correlating notes (exercise, caffeine, stress) with sleep quality
- Updates existing entries for the same day instead of duplicating
- Persistent storage across sessions

## Setup

No API keys required. Sleep data is stored in `sleep_log.json` using the platform file helpers.

## Example Usage

> "I slept from 11 PM to 7 AM, quality 4 out of 5, I exercised yesterday"
> "How did I sleep this week?"
> "Show me my sleep trends"

## Data Format

Entries are stored as JSON:
```json
[
  {
    "date": "2026-02-24",
    "bedtime": "23:00",
    "waketime": "07:00",
    "hours": 8.0,
    "quality": 4,
    "notes": "exercised"
  }
]
```
