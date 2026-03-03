# Quiet Company

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@freddieliang-lightgrey?style=flat-square)

## What It Does

Generates calm, soothing lectures on any topic to help you fall asleep. Pick a subject or let it choose a random one, set a duration, and relax.

## Suggested Trigger Words

- "quiet company"
- "sleep lecture"
- "help me sleep"

## Setup

- No API keys needed
- Upload the folder via the OpenHome dashboard at app.openhome.com
- Enable auto-interrupt in OpenHome settings (recommended for stop functionality)

## How It Works

1. **Topic Selection**: Name a topic (e.g., "the roman empire") or say "none" for a random calming subject
2. **Duration Selection**: Choose "short" (~3-5 min), "medium" (~8-15 min), or "long" (~15-25 min)
3. **Lecture Playback**: LLM-generated segments play one after another in a slow, calm tone
4. **Stop Anytime**: Say "stop" between segments and stay silent for 2-3 seconds to exit
5. **Natural Fade-out**: The final segment gently winds down with a soft goodbye

Say "stop", "exit", "quit", "done", "cancel", "goodbye", or "that's enough" at any point to exit.

## Example Conversation

> **User:** "Quiet company"
> **AI:** "I'll talk quietly for a while. There's nothing you need to do, and nothing you need to remember. You can relax and just listen. If you want to stop at any time, just say stop."
> **AI:** "What would you like me to talk about? You can name a topic, or say 'none' for a random topic."
> **User:** "The history of libraries"
> **AI:** "I'll talk quietly about the history of libraries."
> **AI:** "How long would you like me to keep you company? You can say short, medium, or long."
> **User:** "Short"
> **AI:** *(begins a calm, slow lecture about the history of libraries...)*
> **AI:** *(continues for 3 segments, then gently fades out)*
> **AI:** "And with that, I'll let you rest. Good night."
