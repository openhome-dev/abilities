# Ambient Sounds

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)

## What It Does

Ambient Sounds streams relaxing, focus-friendly, and sleep-inducing audio on demand — rain, ocean, cafe, fire, forest, white noise, focus drones, sleep pads, and more. It fetches a fresh sound from [Freesound](https://freesound.org) every session, so you're never stuck with the same loop.

Just talk naturally:
- *"Play rain"*
- *"Ocean waves"*
- *"Something cozy"*
- *"Help me focus"*
- *"White noise"*
- *"Stop"*

No audio files bundled. Nothing to upload. Just an API key.

## Suggested Trigger Words

- "Ambient sounds"
- "Play rain" / "Play ocean" / "Play campfire" / "Play cafe sounds"
- "White noise" / "Pink noise" / "Brown noise"
- "Help me focus" / "Help me sleep" / "Help me relax"
- "Forest sounds" / "Crickets at night" / "Thunder"
- "Play something relaxing" / "Play me anything"

## Categories

| Group | Categories |
|---|---|
| **Weather** | rain, thunder, wind |
| **Water** | ocean, river, waterfall |
| **Nature** | forest, crickets |
| **Cozy** | fire (campfire), cafe |
| **Urban** | city ambience |
| **Noise** | white noise, pink noise, brown noise, fan |
| **Focus / Sleep** | focus sounds, sleep sounds, meditation |

The LLM router maps freeform requests ("something calm", "play anything", "rainy afternoon") to the best-fit category. Requests outside the ambient set (jazz, rock, a specific song or artist) get a polite redirect.

## Features

- **LLM-driven intent routing** — one model call per turn decides whether you want a category, an exit, a non-ambient redirect, or a clarification.
- **Curated 18-category set** — each category has hand-tuned Freesound search terms verified to return relevant results.
- **Streaming playback** — audio is streamed chunk-by-chunk from Freesound's CDN, no file downloads.
- **Snappy stop/pause** — checks `music_mode_stop_event` and `music_mode_pause_event` per audio chunk for fast interruption.
- **Music mode session wrap** — music mode is enabled on the websocket for the whole session so the device knows audio is active.
- **Conversational loop** — after each play, asks if you want another sound or to wrap up. Session continues until you explicitly exit.
- **Atmospheric tone** — spoken responses are intentionally calm and matched to the ambient mood (no rushed/robotic phrasing).

## Setup

1. Sign up at [freesound.org](https://freesound.org) and apply for an API key at [freesound.org/apiv2/apply/](https://freesound.org/apiv2/apply/).
2. In OpenHome, open **Settings → API Keys** and add a new key:
   - **Name:** `freesound_api_key`
   - **Value:** your Freesound token
3. Trigger the ability with any phrase above.

### API Used

| API | Key Required | Purpose |
|-----|:---:|---------|
| Freesound | Yes | Search + stream ambient/nature/relaxation sounds |

Freesound free tier: **60 requests/minute, 2000/day** — well above what this ability uses (one search per play).

## Example Conversation

> **User:** "Play rain"
>
> **AI:** "Alright, getting some rain sounds ready. Just a moment to set things up. Say stop whenever you'd like."
>
> *(streams rain audio)*
>
> **User:** "Stop"
>
> **AI:** *(stops audio)* "Alright. Want me to play some rain, ocean, or campfire next — or maybe white noise, focus, or sleep sounds? Or wrap up?"
>
> **User:** "Cafe sounds"
>
> **AI:** "Sure — finding some cafe ambience for you. One moment, then we'll drift in. Stop me anytime."
>
> *(streams cafe ambience)*

---

> **User:** "Play something to help me focus"
>
> **AI:** "Cueing up some focus sounds, just a moment to find the right one. Just say stop when you're done."
>
> *(streams focus drone)*

---

> **User:** "Play taylor swift"
>
> **AI:** "I only do ambient — rain, ocean, fire, cafe, forest, white noise, focus, sleep, and the like. What kind of mood are you after?"

---

> **User:** "Exit"
>
> **AI:** "Catch you later — enjoy the quiet."

## How It Works

1. **Trigger arrives** — OpenHome routes the user's voice to this ability.
2. **Intent routing** — a single LLM call (`text_to_text_response`) classifies the message into one of:
   - a **category key** (e.g., `rain`, `ocean`, `focus`)
   - `EXIT` — user wants to stop/quit/leave
   - `NOT_AMBIENT` — user asked for music outside the ambient set
   - `NEEDS_INPUT` — message has no actionable content
3. **Announcement** — for a category, the ability speaks a short atmospheric line that bridges the search latency.
4. **Search** — Freesound is searched with the category's curated query, filtered to 1–30 minute duration MP3/WAV results, sorted by rating.
5. **Pick** — random choice from the top 5 results (keeps repeats fresh).
6. **Stream** — `httpx.AsyncClient.stream` pulls the audio. Each 25KB chunk is forwarded to the SDK via `send_audio_data_in_stream`. Stop and pause events are checked per chunk.
7. **Continue prompt** — when playback ends (user stop or natural end), the ability asks if you want another sound. Your reply goes back through the LLM router.
8. **Session exit** — when the router returns `EXIT`, the ability speaks a goodbye, clears music mode, and yields control back to OpenHome.

## Notes

- Audio is streamed from Freesound's CDN — requires internet.
- Each playback is a single play-through of whatever sound was picked (no internal looping). To extend, the user simply says "another" / "more" / picks another category when prompted.
- API errors (Freesound 5xx, network failure, empty results) are logged and the session continues with a continue prompt — no spoken error noise.
