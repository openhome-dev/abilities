# Kortexa Radio

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@kortexa--ai-lightgrey?style=flat-square)

## What It Does
Streams AI-generated radio from [radio.kortexa.ai](https://radio.kortexa.ai) to your OpenHome device. Music, DJ announcements, and news segments — all generated in real-time by AI.

## Suggested Trigger Words
- "start radio"
- "kortexa radio"

## Setup
No setup required. The stream is public.

## How It Works
1. Say the trigger word
2. The ability enters music mode and starts streaming
3. Interrupt (wake word or touch) to stop — control returns to the agent
4. Say the trigger word again to restart

## Example Conversation
> **User:** "start radio"
> **AI:** "Tuning in to Kortexa Radio."
> *(AI-generated music plays through the device)*
>
> *(User interrupts)*
> **AI:** *(agent resumes normal conversation)*
>
> **User:** "start radio"
> **AI:** "Tuning in to Kortexa Radio."
> *(Music plays again)*

## Stream Details
- Format: MP3, 128kbps, 48kHz stereo
- Source: https://api.kortexa.ai/radio/stream
- Content: AI-generated music, DJ segments, news updates
- Programming changes by time of day

## Logs
Look for `[KortexaRadio]` entries in OpenHome Live Editor logs.
