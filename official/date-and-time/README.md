# Date & Time
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-Reyad-lightgrey?style=flat-square)

## What It Does
Instantly tells you the current date, time, or both — just by asking.  
No API, no setup, no delay. Uses your device's local clock.

## Suggested Trigger Words
- what time is it
- what's the time
- current time
- what's today's date


## Setup
- **No API key required.**
- No external dependencies — uses Python's built-in `datetime` module.

## How It Works
1. User asks about the time, date, or both
2. Ability detects keywords — "time" and/or "date" — in the message
3. Fetches the current value from the device clock
4. Returns a clean, spoken-friendly response instantly

## Example Conversation

**User:** What time is it?  
**AI:** Time is 14:35:20.

**User:** What's today's date?  
**AI:** Date is Tuesday 17 February 2026.

**User:** What's the date and time?  
**AI:** Date is Tuesday 17 February 2026.  
Time is 14:35:20.
