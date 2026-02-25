# Noise Machine

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@yourusername-lightgrey?style=flat-square)

## What It Does
Plays relaxing ambient sounds (rain, ocean waves, cafe, white noise, etc.) for a user-selected duration. Users can stop playback anytime by saying “stop”.

## Suggested Trigger Words
- "noise machine"
- "sound machine"
- "sleep sounds"
- "play rain"
- "ocean waves"
- "white noise"
- "cafe sounds"
- "forest birds"

## Setup
- **Audio files:** Upload the 15 MP3 files into the Ability workspace (same folder as `main.py`), with these exact names:
  - `rain.mp3`
  - `heavy_rain.mp3`
  - `ocean_waves.mp3`
  - `river_stream.mp3`
  - `white_noise.mp3`
  - `pink_noise.mp3`
  - `brown_noise.mp3`
  - `forest_birds.mp3`
  - `crickets.mp3`
  - `campfire.mp3`
  - `wind.mp3`
  - `thunder.mp3`
  - `cafe.mp3`
  - `fan.mp3`
  - `waterfall.mp3`
- **Trigger words:** Set your trigger phrases in the OpenHome editor (these should match what you want users to say out loud).
- **No API keys required.**

## How It Works
1. The user launches the ability using a trigger phrase (e.g., “noise machine”).
2. The ability asks what sound the user wants (or matches it if they already said one).
3. The ability asks for a duration (e.g., “30 minutes”, “one hour”, “hour and a half”).
4. It plays the selected sound in a loop until the timer ends or the user says “stop”.
5. The ability exits cleanly back to normal OpenHome flow.

## Example Conversation
> **User:** "noise machine"  
> **AI:** "Noise machine ready. Popular sounds are: Rain, Ocean waves, White noise, Campfire, Forest birds. What would you like to hear?"  
> **User:** "cafe"  
> **AI:** "How long should I play it? You can say 30 minutes or 1 hour."  
> **User:** "one hour"  
> **AI:** "Playing Cafe for 1 hour. Say stop anytime."  
> **User:** "stop"  
> **AI:** "Okay, stopped."