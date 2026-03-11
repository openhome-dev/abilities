# Alarm & Timer

Set alarms and countdown timers entirely by voice. The background daemon fires `alarm.mp3` at the right time — even while the session is idle — and keeps ringing until you say anything to dismiss it.

## Features

- **Set alarms** — "Wake me up at 7", "Set an alarm for 5:30 PM" — LLM parses natural language times including relative day references (tomorrow, Thursday)
- **Set timers** — "Set a timer for 30 minutes", "Remind me in 2 hours" — countdown from now
- **List alarms** — hear all active alarms and timers at a glance
- **Cancel alarms** — single alarm cancelled directly; multiple alarms listed so you can pick by number
- **Background firing** — `background.py` daemon polls every 15 seconds and fires independently of whether `main.py` has run
- **Looping alarm sound** — `alarm.mp3` repeats until you say anything (voice-detected dismissal)
- **Safety cap** — auto-dismisses after ~5 minutes if no response
- **Past-time handling** — if a clock time has already passed today, automatically scheduled for tomorrow
- **Timezone-aware** — detects your local timezone via `get_timezone()` or IP geolocation fallback
- **Persistent** — alarms survive session restarts via `oh_alarms.json`

## Trigger Words

`set an alarm`, `set a timer`, `wake me up`, `remind me in`, `timer for`, `alarm for`, `set alarm`, `countdown timer`, `what alarms do i have`, `list my alarms`, `cancel my alarm`, `cancel alarm`, `cancel timer`

## Example Conversations

**Set an alarm:**
> User: "Wake me up at 7"
> AI: "Alarm set for 7:00 AM tomorrow morning."

**Set a timer:**
> User: "Set a timer for 30 minutes"
> AI: "Timer set for 30 minutes. I'll let you know when it's up."
> *(30 minutes later — alarm.mp3 plays on repeat)*
> User: "Okay, I'm up"
> AI: "Your 30 minutes timer is dismissed."

**List alarms:**
> User: "What alarms do I have?"
> AI: "You have 2 active. Alarm 1: 7:00 AM tomorrow. Timer 2: 30 minutes."

**Cancel:**
> User: "Cancel my alarm"
> AI: "Cancelled: 7:00 AM tomorrow."

## Setup

- No API key required.
- Provide `alarm.mp3` in the ability directory (OpenHome provides this separately).
- Timezone is auto-detected — no manual configuration needed.

## Storage

- `oh_alarms.json` — shared state between `main.py` and `background.py`. Schema:
  ```json
  {
    "timezone": "America/New_York",
    "alarms": [
      {
        "id": "a1b2c3d4",
        "type": "alarm",
        "created_at_epoch": 1700000000,
        "target_iso": "2026-03-05T07:00:00",
        "human_time": "7:00 AM tomorrow",
        "source_text": "wake me up at 7",
        "status": "scheduled"
      }
    ]
  }
  ```
  Status values: `scheduled`, `triggered`, `cancelled`

## Architecture

`main.py` and `background.py` never call each other — they coordinate exclusively through `oh_alarms.json`.

| File | Role |
|------|------|
| `main.py` | Interactive: handles SET_ALARM, SET_TIMER, LIST, CANCEL intents |
| `background.py` | Daemon: polls every 15s, fires alarm, detects dismissal via message history |
| `config.json` | Trigger hotwords and unique name |
| `alarm.mp3` | Alarm sound (provided by OpenHome) |
