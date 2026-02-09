# Sound Generator

![Official](https://img.shields.io/badge/OpenHome-Official-blue?style=flat-square)

Generates AI sound effects using ElevenLabs. Describe any sound and hear it instantly. Supports modifying, enhancing, replaying, and adjusting duration.

## Trigger Words

- "make a sound"
- "create a sound"
- "sound effect"
- "generate a sound"

## Setup

**Requires an ElevenLabs API key.**

1. Get an API key at [elevenlabs.io](https://elevenlabs.io)
2. Replace `YOUR_ELEVENLABS_API_KEY_HERE` in `main.py`

## How It Works

1. User describes a sound ("thunder in a canyon")
2. API generates the sound effect
3. Audio plays back immediately
4. User can then:
   - **Modify:** "Make it longer" / "Make it shorter"
   - **Enhance:** "Enhance it" (LLM improves the prompt)
   - **Replay:** "Play it again"
   - **New sound:** Describe something else
   - **Exit:** "Stop" / "Done"

## Commands

| Say | What Happens |
|-----|-------------|
| "thunder in a canyon" | Generates new sound |
| "make it longer" | Regenerates at +3 seconds |
| "make it shorter" | Regenerates at -2 seconds |
| "enhance it" | LLM improves the prompt, regenerates |
| "again" / "replay" | Replays last sound |
| "stop" / "done" | Exits the Ability |

## Example Conversation

> **User:** "Make a sound"
> **AI:** "Sound generator ready. Describe what you want to hear."
> **User:** "Rain on a tin roof"
> **AI:** "Creating rain on a tin roof."
> *[Sound plays]*
> **AI:** "There we go. You can modify it or ask for a new sound."
> **User:** "Make it longer"
> **AI:** "Regenerating at 8.0 seconds."
> *[Longer version plays]*
> **User:** "Done"
> **AI:** "Closing sound generator."
