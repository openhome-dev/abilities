# Porch

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@kortexa--ai-lightgrey?style=flat-square)

## What It Does
A minimal test ability for the [Porch](https://github.com/kortexa-ai/openhome-porch) macOS client. Sends commands to your Mac via `exec_local_command()` to verify the end-to-end connection is working.

## Suggested Trigger Words
- "porch"
- "open porch"

## Setup
1. Install and run [Porch](https://github.com/kortexa-ai/openhome-porch) on your Mac
2. Upload this ability to OpenHome and set trigger words in the dashboard

## How It Works
1. Say the trigger word
2. Porch asks what to do
3. Say "open dashboard" → opens app.openhome.com in your Mac's browser
4. Say "stop" or "cancel" to exit

## Supported Commands

| Command | What it does |
|---------|-------------|
| "open dashboard" | Opens app.openhome.com in your default browser |

More commands coming as Porch develops.

## Example Conversation
> **User:** "porch"
> **AI:** "Porch here. What should I do?"
> **User:** "open dashboard"
> **AI:** "Opening the OpenHome dashboard."
> *(Browser opens app.openhome.com on your Mac)*

## Logs
Look for `[Porch]` entries in OpenHome Live Editor logs.
