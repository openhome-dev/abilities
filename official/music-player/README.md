# Music Player

![Official](https://img.shields.io/badge/OpenHome-Official-blue?style=flat-square)

Plays music from a URL or local file. Demonstrates music mode, audio downloading, and the `play_audio` / `play_from_audio_file` APIs.

## Trigger Words

- "play music"
- "play a song"
- "play some music"
- "music player"

## Setup

No API key required. Uses a sample public domain track by default.

To play your own music, either:
- Change `SAMPLE_MUSIC_URL` to a direct MP3 URL
- Or place an MP3 file in this folder and use `play_from_audio_file("yourfile.mp3")`

## How It Works

1. Enters music mode (signals hardware/UI that audio is playing)
2. Downloads MP3 from URL
3. Plays the audio
4. Exits music mode
5. Returns to normal conversation

## Key SDK Functions Used

- `play_audio()` — Play audio from bytes
- `play_from_audio_file()` — Play audio from Ability folder
- `send_data_over_websocket()` — Toggle music mode
- `music_mode_event` — Hardware state flag

## Example Conversation

> **User:** "Play some music"
> **AI:** "Playing some music for you."
> *[Music plays]*
