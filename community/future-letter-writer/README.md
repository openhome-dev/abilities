# Future Letter Writer

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@rawqubit-lightgrey?style=flat-square)

## What It Does

Record voice messages to your future self. Set a delivery date — one week, one month, one year — and the background daemon delivers the message by speaking it aloud when the date arrives. A voice-powered time capsule.

## Category

**Interactive Combined** — `main.py` (interactive skill) + `background.py` (delivery daemon)

## Suggested Trigger Words

- "future letter"
- "letter to myself"
- "time capsule"
- "message to future me"
- "write to my future self"
- "future message"

## Setup

No API keys required. Uses LLM for date parsing and message cleanup.

## How It Works

### Recording (main.py)
1. Offers a reflection prompt for inspiration
2. User dictates their message by voice
3. LLM cleans up filler words while preserving tone
4. Reads back for confirmation
5. User sets delivery date in natural language ("in 6 months", "next birthday")
6. LLM parses date, saves to shared JSON file

### Delivery (background.py)
1. Polls `future_letters_data.json` every 60 seconds
2. Checks if any pending letter's delivery date has arrived
3. Interrupts conversation to deliver: "You left yourself a message..."
4. Reads the message aloud with the date it was written
5. Marks letter as "delivered" in the shared file

## Features

| Feature | Description |
|---------|-------------|
| Voice recording | Dictate messages naturally, LLM cleans them up |
| Natural date parsing | "In a month", "next year", "January 2027" all work |
| Reflection prompts | Inspiration questions if you're not sure what to say |
| Read-back confirmation | Hear your cleaned message before saving |
| Automatic delivery | Background daemon delivers on the right date |
| List & manage | View pending letters, delete unwanted ones |
| Combined pattern | `main.py` for interaction, `background.py` for delivery |

## Example Conversation

> **User:** "Future letter"
> **AI:** "Welcome back to Future Letters. You have 2 letters waiting. The next one arrives in about a month."
> **User:** "Write a new one"
> **AI:** "Here's something to think about: What would you tell yourself six months from now? Or just say whatever's on your mind."
> **User:** "Hey future me. I just started the new job and I'm nervous but excited. Remember this feeling — the butterflies are a good sign."
> **AI:** "Here's what you said: 'Hey future me. I just started the new job and I'm nervous but excited. Remember this feeling — the butterflies are a good sign.' Sound good?"
> **User:** "Yes"
> **AI:** "When should I deliver this?"
> **User:** "In six months"
> **AI:** "Saved! Your letter will be delivered about six months from now. Your future self will hear it then."

### Delivery (automatic, months later):
> **AI:** "You left yourself a message. Written on June 10th, you said: 'Hey future me. I just started the new job and I'm nervous but excited. Remember this feeling — the butterflies are a good sign.' That was a message from your past self."

## Data Files

- `future_letters_data.json` — letters with messages, delivery dates, and status

## File Structure

```
future-letter-writer/
├── main.py         # Interactive — record, list, delete letters
├── background.py   # Background — deliver letters on their date
└── README.md
```
