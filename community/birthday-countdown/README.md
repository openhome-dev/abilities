# Birthday & Event Countdown

Tracks birthdays, anniversaries, and other recurring events with persistent storage. Calculates countdowns, lists upcoming events, and generates gift ideas using the LLM.

## Triggers

- "birthday reminder"
- "birthday countdown"
- "anniversary reminder"
- "event countdown"
- "upcoming birthdays"

## Features

- Add events with name, date, type, and personal notes
- Check upcoming events sorted by nearest date
- Remove events with voice confirmation
- Gift idea generation based on stored notes about the person
- Persistent storage across sessions

## Setup

No API keys required. Events are stored in `birthday_events.json` using the platform file helpers.

## Example Usage

> "Add Sarah's birthday on March 15th, she likes hiking and coffee"
> "When is the next birthday?"
> "Gift ideas for Sarah"
> "Remove Sarah's birthday"

## Data Format

Events are stored as JSON:
```json
[
  {
    "name": "Sarah",
    "date": "03-15",
    "type": "birthday",
    "notes": "likes hiking and coffee"
  }
]
```
