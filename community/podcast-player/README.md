# Podcast Player

## What It Does

A fully voice-controlled podcast player powered by the Listen Notes API.
Search for podcast episodes, browse podcasts, get the latest episodes, or say “surprise me” to instantly stream a random episode.

The ability streams podcast audio directly and supports natural conversational navigation.

## Suggested Trigger Words

- podcast

- listen to podcast

- search podcast

- play episode

- surprise me

## Setup

- Get a free API key from Listen Notes: https://www.listennotes.com/api/dashboard/#apps

- Open main.py and replace:

- API_KEY = "YOUR_LISTEN_NOTES_API_KEY"

- with your actual API key.

## How It Works

User triggers the ability (e.g., “podcast”)

Assistant asks what the user would like to listen to

User can:

Search for an episode

Search for a podcast and browse its latest episodes

Ask for a random episode

The assistant streams the episode audio live

User can:

Ask what’s currently playing

Choose another episode

Stop playback

## Features

- 🎙️Episode Search — Find podcast episodes by topic or keywords

- 📻 Podcast Search — Browse podcasts and select from recent episodes

- 🎲 Surprise Mode — Instantly play a random episode

- 🔊 Live Audio Streaming — Streams audio directly within the session

- ❓ What’s Playing — Ask what episode is currently playing

- ⛔ Voice Exit Control — Stop playback anytime

Example Conversation

**User:**: podcast
**AI:**: What would you like to listen to? You can search for an episode, a podcast, or say surprise me.

**User:**: search artificial intelligence
**AI:**: Here are a few options:

The Future of AI from Tech Today, 42 minutes.

AI in Healthcare from Innovation Weekly, 35 minutes.

Machine Learning Basics from Data Talks, 28 minutes.
Choose 1, 2, or 3.

**User:**: first
**AI:**: Playing The Future of AI from Tech Today.
(audio streams)

**User:**: what’s playing
**AI:**: You're listening to The Future of AI from Tech Today.

**User:**: stop
**AI:**: Stopping playback.

## Notes

- Requires an active internet connection

- Uses the Listen Notes public podcast API

- Some episodes may not contain playable audio URLs

- treaming performance depends on the source audio host
