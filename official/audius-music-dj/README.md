# Audius Music Player
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-Reyad-lightgrey?style=flat-square)

## What It Does
A fully voice-controlled music player powered by the free Audius decentralized music platform.  
Ask for songs by name, artist, genre, mood, or vibe — it finds the best match, streams it live, and lets you manage a favorites list. No API key required.

## Suggested Trigger Words
- play music
- play a song
- play something
- music

## Setup
- **No API key required.** Audius is a free, open music platform.
- The ability connects automatically to the best available Audius host on startup.

## How It Works
1. User triggers with "play music" (or similar)
2. Assistant listens for a song request — by name, artist, genre, mood, era, or context
3. Searches Audius for matching tracks
4. An LLM picks the best match from the results
5. Streams the audio live and displays song metadata (title, artist, artwork)
6. After each song, the user can ask for more, add to favorites, or stop

## Features
- 🎵 **Smart Search** — supports song name, artist, genre, mood, time era, and vibe
- 🔁 **Session Mode** — establishes a broader theme across multiple songs
- ❤️ **Favorites** — add, remove, and play back your saved songs
- 🚫 **No Repeat Logic** — tracks recently played songs and avoids replaying them
- ⏸️ **Pause / Resume** — voice-controlled playback control

## Supported Genres
Alternative, Ambient, Acoustic, Blues, Classical, Country, Electronic, Folk, Funk, Hip-Hop/Rap, Indie, Jazz, Latin, Lo-Fi, Metal, Pop, Punk, R&B/Soul, Reggae, Rock, Soundtrack, World, and more.

## Supported Moods
Aggressive, Calm, Cool, Easygoing, Empowering, Energizing, Melancholy, Peaceful, Romantic, Rowdy, Sensual, Upbeat, Yearning, and more.

## Example Conversation

**User:** play music  
**AI:** *(listens for request)*

**User:** play something chill by Frank Ocean  
**AI:** I am searching a song for you, please wait!  
Now playing Thinking Bout You by Frank Ocean.  
*(song streams)* What would you like me to do next? You can say 'PLAY SOMETHING SIMILAR', 'ADD TO FAVORITES', 'PLAY MY FAVORITES', or 'STOP' to exit.

**User:** add to favorites  
**AI:** Song added to your favorites.

**User:** play something similar  
**AI:** I am searching a song for you, please wait!  
Now playing Ivy by Frank Ocean.

**User:** stop  
**AI:** Music off! Hope you enjoyed the vibes — catch you later!
