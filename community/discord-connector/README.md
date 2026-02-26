# Discord Connector

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@burhan-lightgrey?style=flat-square)

## What It Does

A voice-powered Discord client. Read messages, post updates, get channel digests, list and switch channels — all by voice. Uses the Discord Bot API for real-time server access.

## Suggested Trigger Words
- "discord"
- "discord messages"
- "check discord"
- "discord digest"
- "post to discord"
- "discord update"
- "what's happening on discord"
- "discord channel"
- "send a discord message"

## Setup

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create a New Application → go to **Bot** → **Reset Token** → copy it
3. Under **Privileged Gateway Intents**, enable **MESSAGE CONTENT INTENT**
4. Go to **OAuth2 → URL Generator** → select scope `bot` → select permissions: `Read Messages/View Channels`, `Send Messages`, `Read Message History`
5. Use the generated URL to invite the bot to your server
6. Replace `REPLACE_WITH_YOUR_BOT_TOKEN` in `main.py` with your token

## How It Works

**Quick Mode** (e.g., "read my discord messages"):
- Answers the specific question → brief follow-up → exits

**Full Mode** (e.g., "check discord" / "discord digest"):
- Connects to your saved channel → gives a digest → enters interactive loop
- You can read messages, post updates, switch channels, or ask for digests
- Say "done" or "exit" to leave

### Features

| Feature | What It Does |
|---------|-------------|
| Read Messages | Fetches recent messages and reads them aloud |
| Post Update | Compose and send a message to a channel via voice |
| Get Digest | Summarizes recent channel activity into a spoken briefing |
| List Channels | Lists available text channels in the server |
| Switch Channel | Switch to a different channel by name |

### Persistence

- Remembers your preferred server and channel across sessions
- Auto-selects the first text channel on first run

## Example Conversation

> **User:** "Check Discord"
> **AI:** "Connected to general. Let me check what's new."
> **AI:** "The channel's been active today. Sarah shared a deployment update, and Mike asked about the API docs."
> **User:** "Post great work team"
> **AI:** "I'll post to general: Great work team. Should I send it?"
> **User:** "Yes"
> **AI:** "Posted!"
> **User:** "Switch to announcements"
> **AI:** "Switched to announcements."
> **User:** "Give me a digest"
> **AI:** "Here's what's been happening in announcements..."
> **User:** "Done"
> **AI:** "Got it. Closing Discord. Have a good one!"
