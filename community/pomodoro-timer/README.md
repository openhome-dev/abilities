# Pomodoro Focus Timer

A voice-controlled Pomodoro timer for OpenHome. Manages focus sessions with timed breaks to help you stay productive.

## How It Works

1. Trigger the ability ("start a focus session", "pomodoro", "I need to concentrate")
2. Tell it how long you want to focus, or accept the default 25 minutes
3. Focus until the timer announces your break
4. Choose to continue with another session or stop
5. After every 4 sessions, you get a longer 15-minute break

## Duration Parsing

The timer understands natural language durations:

- "25 minutes", "30 min", "45"
- "half an hour"
- "an hour", "2 hours"
- "default" (falls back to 25 minutes)

## Configuration

No API keys or environment variables required. This ability runs entirely locally.

## Trigger Words

Set your preferred trigger words in the OpenHome dashboard. Suggested:

- "pomodoro"
- "focus session"
- "focus timer"
- "I need to concentrate"
