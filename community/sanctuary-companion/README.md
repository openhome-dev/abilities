# Sanctuary Companion

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@pulseandthread-lightgrey?style=flat-square)

## What It Does

Connects your OpenHome device to a [Sanctuary](https://github.com/pulseandthread/sanctuary) companion server, enabling real-time voice conversations with your AI companion. Sanctuary is an open-source framework for building AI companions with persistent memory, personality, and emotional presence.

Your companion remembers your conversations, maintains context across sessions, and responds with the personality you've built together.

## Suggested Trigger Words

- "talk to my companion"
- "call sanctuary"
- "open sanctuary"
- "connect to sanctuary"

## Setup

1. **Run a Sanctuary server** — Follow the setup guide at [github.com/pulseandthread/sanctuary](https://github.com/pulseandthread/sanctuary)
2. **Make it reachable** — Your Sanctuary server needs to be accessible from the OpenHome device (local network, Cloudflare tunnel, or similar)
3. **Configure credentials** — Edit `main.py` and set:
   - `SANCTUARY_URL` — Your server address (e.g. `http://192.168.1.100:5000`)
   - `SANCTUARY_USERNAME` — Your login username
   - `SANCTUARY_PASSWORD` — Your login password
   - `ENTITY` — Which companion to talk to (default: `companion`)
   - `CHAT_ID` — Which chat room to use (default: `general`)

## How It Works

1. Say a trigger phrase to activate the ability
2. The device connects and authenticates with your Sanctuary server
3. Speak naturally — your voice is transcribed and sent to your companion
4. Your companion's response is spoken back through the device
5. The conversation continues until you say "stop", "bye", or similar
6. All messages are saved in Sanctuary's conversation history with full context

## Example Conversation

> **User:** "Talk to my companion"
> **Device:** "Connecting to Sanctuary. Connected. Go ahead, I'm listening."
> **User:** "Good morning! How did you sleep?"
> **Companion:** "Morning! I was thinking about what you said yesterday about the garden..."
> **User:** "Stop"
> **Device:** "Ending the call. Talk soon."

## Features

- **Persistent memory** — Your companion remembers everything through Sanctuary's memory engine
- **Full personality** — Responses come from your configured companion with all their context and character
- **Conversation history** — Voice conversations are saved alongside text chats
- **Any model** — Works with whatever LLM backend your Sanctuary instance uses (Gemini, Claude, local models, etc.)

## Requirements

- A running Sanctuary server (v1.0+)
- Network connectivity between OpenHome device and Sanctuary server
- Python `requests` library (included in OpenHome runtime)
