# YouTube Search & Play

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@ammyyou112-lightgrey?style=flat-square)

## What It Does
Search and play YouTube videos by voice. Say what you want to hear, and this ability finds it on YouTube and streams the audio through OpenHome.

## Suggested Trigger Words
- "play on YouTube"
- "YouTube"
- "play video"
- "search YouTube"
- "find on YouTube"

## Setup

**You need to subscribe to two free RapidAPI APIs (same API key works for both):**

1. **YouTube Search API** (by Elis) – [Subscribe](https://rapidapi.com/elis-api-provider/api/youtube-search-api) to the free plan
2. **YouTube MP3** (by ytjar) – [Subscribe](https://rapidapi.com/ytjar/api/youtube-mp36) to the free plan

**Add your credentials to main.py:**
- Replace `RAPIDAPI_KEY` with your RapidAPI key
- Replace `RAPIDAPI_USERNAME` with your RapidAPI profile username (fixes 404 when streaming – find it at [rapidapi.com/developer/app](https://rapidapi.com/developer/app))

## How It Works
1. User says a trigger phrase like "play on YouTube"
2. Ability asks what they want to play
3. User speaks a song or video name
4. Ability searches YouTube, gets the audio URL, and streams it in music mode
5. When done, asks if they want to play something else
6. User can say "stop" to exit, or "pause" / "continue" during playback

## Example Conversation

> **User:** "Play on YouTube"
>
> **AI:** "What would you like to play from YouTube?"
>
> **User:** "Play Bohemian Rhapsody"
>
> **AI:** "Searching YouTube... Playing Bohemian Rhapsody by Queen"
>
> *[Audio streams]*
>
> **AI:** "Done playing. Want to play something else?"
>
> **User:** "No, stop"
>
> **AI:** "Okay, stopping YouTube."
