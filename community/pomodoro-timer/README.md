# Pomodoro Focus Timer

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@jibzus-lightgrey?style=flat-square)

## What It Does

A voice-controlled Pomodoro timer that manages focus sessions with timed breaks. Supports natural language durations, multi-session loops, and automatic long breaks every 4 sessions.

## Suggested Trigger Words

- "pomodoro"
- "focus session"
- "focus timer"
- "I need to concentrate"

## Setup

No API keys or environment variables required. This ability runs entirely locally.

## How It Works

1. Ask how long you want to focus (default: 25 minutes)
2. Parse your response — understands "25 minutes", "half an hour", "1.5 hours", or bare numbers
3. Run a timed focus session using `session_tasks.sleep()`
4. Announce break time (5 minutes, or 15 minutes after every 4th session)
5. Ask if you want to continue or stop
6. Repeat until you say an exit word, then summarize your total focus time

## Example Conversation

> **User:** "Start a focus session"
> **AI:** "How long would you like to focus? I'll default to 25 minutes."
> **User:** "Half an hour"
> **AI:** "Starting focus session 1. 30 minutes on the clock. Good luck."
> *(30 minutes later...)*
> **AI:** "Focus session complete. Take a 5-minute break. Say stop to finish, or anything else to keep going."
> **User:** "Keep going"
> **AI:** "Enjoy your 5-minute break."
> *(5 minutes later...)*
> **AI:** "Break's over. Ready for the next session."
> **AI:** "Starting focus session 2. 30 minutes on the clock. Good luck."
> *(30 minutes later...)*
> **AI:** "Focus session complete. Take a 5-minute break. Say stop to finish, or anything else to keep going."
> **User:** "Stop"
> **AI:** "Great work. You completed 2 focus sessions, totaling 60 minutes. See you next time."
