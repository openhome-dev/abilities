# Timers, Alarms & Reminders

A combined interactive + background daemon ability for OpenHome that handles timers, alarms, and reminders through natural voice interaction.

## How It Works

**main.py** (Interactive Skill) — Triggered by hotwords like "set a timer", "remind me", "wake me up". Uses the LLM to classify intent (create/list/cancel/delete) and parse natural language times. Writes events to `scheduled_events.json`.

**background.py** (Background Daemon) — Polls `scheduled_events.json` every 15 seconds. Fires due events with type-appropriate behavior (timers get a spoken notification, alarms play a sound, reminders speak the message). Writes `upcoming_schedule.md` so the Personality stays aware of what's scheduled.

## Voice Commands

| Action | What to say | Example response |
|--------|------------|-----------------|
| **Set a timer** | "set a timer for 5 minutes" / "timer for 30 seconds" / "start a 10 minute timer" | "5 minutes timer started." |
| **Set an alarm** | "set an alarm for 7 AM" / "wake me up at 6:30" / "alarm for 10 PM tomorrow" | "Alarm set for 7:00 AM." |
| **Set a reminder** | "remind me to call mom at 3 PM" / "reminder to take medicine at noon tomorrow" | "Got it. I'll remind you about call mom at 3:00 PM." |
| **List everything** | "list all" / "show all" / "show me everything" / "what do I have" | "You have 3 things scheduled. An alarm at 7 AM. A 5 minute timer..." |
| **List by type** | "list alarms" / "show timers" / "list reminders" | "You have one thing scheduled. An alarm at 7:00 AM." |
| **Cancel one event** | "cancel my 7 AM alarm" / "cancel the call mom reminder" | "Done. Your 7:00 AM alarm has been cancelled." |
| **Delete all of a type** | "delete alarms" / "remove timers" / "clear reminders" | "Deleted all 2 alarms." |
| **Delete everything** | "delete all" / "clear everything" / "delete everything" | "Done. Everything has been cleared." |
| **Exit** | "quit" / "exit" / "goodbye" / "bye" / "never mind" | "All done. Handing you back." |
| **Decline to do more** | "no" / "done" / "all done" / "I'm good" | "All done. Handing you back." |

### Bare Trigger Words

Saying just the trigger word starts a guided flow:

| You say | What happens |
|---------|-------------|
| "alarms" | Lists your alarms (if any), asks what you'd like to do |
| "timers" | Lists your timers (if any), asks what you'd like to do |
| "reminders" | Lists your reminders (if any), asks what you'd like to do |
| "schedule" | Lists everything scheduled, asks what you'd like to do |

If none exist, it asks "Want to set one?" — saying "yes" / "sure" / "yeah" starts creating one.

### Multi-Action Sessions

After each action the assistant asks "Anything else?" — you can chain commands:
1. "set an alarm for 7 AM" → "set a timer for 20 minutes" → "list all" → "done"

You can mix types freely — start with "alarms", then set a timer, then list reminders.

## Event Types

| Type | Trigger Example | Firing Behavior |
|------|----------------|-----------------|
| Timer | "set a timer for 20 minutes" | Speaks "Your 20-minute timer is done!" |
| Alarm | "wake me up at 7am" | Plays alarm.mp3 + speaks notification |
| Reminder | "remind me to call Sarah at 3pm" | Speaks "Reminder: call Sarah" |

## Files

| File | Purpose |
|------|---------|
| `main.py` | Interactive voice flow — classify, parse, CRUD events |
| `background.py` | Background daemon — poll, fire, update context |
| `config.json` | Ability name + hotwords |
| `alarm.mp3` | Alarm sound file |
| `scheduled_events.json` | Shared event store (persistent, user-level) |
| `upcoming_schedule.md` | Personality context file (auto-injected) |

## Known Limitations

- Timers under 15 seconds may fire up to 15s late (poll interval).
- Events are session-scoped — the daemon only runs while the user is connected. Alarms set for after the session ends won't fire until the next session.
- JSON file I/O uses delete-then-write pattern to avoid append corruption.
- List/delete/show commands are handled instantly (fast-path). Create and cancel go through the LLM, which may add a small delay.
