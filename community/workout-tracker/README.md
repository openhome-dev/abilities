# Workout Tracker

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@rawqubit-lightgrey?style=flat-square)

## What It Does

A voice-driven exercise tracker that logs workouts, tracks daily streaks, monitors weekly goals, and provides AI-powered progress summaries. All data persists across sessions — the more you use it, the more useful it becomes.

## Suggested Trigger Words

- "workout"
- "exercise"
- "log workout"
- "I just worked out"
- "fitness tracker"
- "how many workouts"
- "workout stats"

## Setup

No API keys required. This ability runs entirely using the LLM and file persistence.

## How It Works

1. **Log workouts** by voice — "I did 30 pushups" or "ran 3 miles"
2. LLM parses exercise type, amount, and unit from natural language
3. Tracks **daily streaks** (consecutive days with workouts)
4. Monitors progress toward a **weekly goal** (default: 4/week, configurable)
5. Provides **stats** — this week, this month, all time, exercise variety
6. **History** readback with voice-friendly date formatting
7. AI-generated **weekly summaries** with encouragement

## Features

| Feature | Description |
|---------|-------------|
| Natural language logging | "Did 50 pushups", "ran a 5k", "45 minutes of yoga" |
| Streak tracking | Consecutive days with at least one workout |
| Weekly goals | Configurable target, progress alerts |
| Exercise variety | Tracks how many different exercises per week |
| History readback | Voice-friendly formatting ("Yesterday: 30 pushups") |
| Weekly AI summary | LLM-powered analysis of your week's training |
| Persistent storage | All data survives across sessions |

## Example Conversation

> **User:** "Workout tracker"
> **AI:** "Welcome back, Chris. You've logged 3 workouts this week out of your 4 goal. 5-day streak going!"
> **User:** "I just did 30 pushups and 50 squats"
> **AI:** "Logged 30 reps pushups! That's a 6-day streak! One more workout to hit your weekly goal!"
> **User:** "How am I doing?"
> **AI:** "This week: 4 workouts across 3 different exercises. Goal: 4 per week. Current streak: 6 days. This month: 12. All time: 47."
> **User:** "Set my goal to 5"
> **AI:** "Goal updated to 5 workouts per week. You got this!"
> **User:** "Done"
> **AI:** "Keep it up! You're on a 6-day streak. See you next time."

## Data Files

- `workout_tracker_log.json` — workout entries (date, exercise, amount, unit)
- `workout_tracker_prefs.json` — user preferences (name, weekly goal)
