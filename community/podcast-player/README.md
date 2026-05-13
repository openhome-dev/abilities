# Podcast Player

Voice-controlled OpenHome ability for finding and playing podcast episodes through Listen Notes.

## What It Does

- **Browse trending picks** — reads out three top trending episodes and lets you pick one.
- **Play the latest episode** of a named podcast — jumps straight into the newest episode.
- **Search a podcast by name** — finds the show and lets you choose from its recent episodes.
- **Find episodes by guest, topic, or episode title** — e.g. "Lex Fridman with Jensen Huang".
- **Play a random pick** — but only when you explicitly ask for one; otherwise it confirms first.
- **Resolve follow-up references** like "the second one" or "the one with Jensen" against the last set of spoken options.
- **Stream playable episode audio** in music mode.
- After each episode, **ask if you want another** or end the session.

## Conversation Flow

```
[ ability triggered ]
   │
   ▼
"What do you want to listen to?"
   │
   ├─► you name a podcast        ──►  search → pick episode → play
   ├─► you ask for the latest    ──►  search → newest episode → play
   ├─► you ask for trending      ──►  read 3 picks → you choose → play
   ├─► you ask for a random      ──►  asks "anything in mind?" first
   ├─► you describe an episode   ──►  search by guest/topic → play
   └─► you say goodbye           ──►  exit
   │
   ▼
[ episode plays ]
   │
   ▼
"Want me to find you something else, or are you good for now?"
   │
   ├─► another request           ──►  loop back to the top
   └─► "I'm done" / "stop"       ──►  exit
```

## Example Voice Interactions

**Trending pick**

```
User:      Open podcast player.
Assistant: What do you want to listen to?
User:      What's trending right now?
Assistant: Here are three trending picks: <ep1> from <show1>, <ep2> from <show2>,
           and <ep3> from <show3>. Which one would you like?
User:      The second one.
Assistant: Here's <ep2> from <show2>.
           [plays audio]
Assistant: Want me to find you something else, or are you good for now?
```

**Latest episode of a named podcast**

```
User:      Play the latest Lex Fridman episode.
Assistant: Let me search for that right now…
Assistant: Here's <newest episode title> from Lex Fridman Podcast.
           [plays audio]
```

**Search by guest**

```
User:      Find me the Lex Fridman episode with Jensen Huang.
Assistant: Let me search for that episode…
Assistant: Here's <episode title> from Lex Fridman Podcast.
           [plays audio]
```

**Random — note the confirmation step**

```
User:      Just play something.
Assistant: Any particular show or topic you have in mind? Or should I just
           pick something for you?
User:      Surprise me.
Assistant: Give me just a moment, I'll find you something good.
           [plays a randomly-picked trending episode]
```

## Suggested Trigger Phrases

- "podcast player"
- "play a podcast"
- "find a podcast"
- "open podcast player"
- "play the latest <podcast name>"

Configure trigger matching in the OpenHome dashboard.

## Getting a Listen Notes API Key

This ability calls the Listen Notes Podcast API (v2). You need a free account and an API key.

1. Go to https://www.listennotes.com/api/
2. Click **Get free API key** (top right). Sign in with Google or create an email account.
3. After signing in, open the dashboard at https://www.listennotes.com/api/dashboard/. The **API Key** is shown there — copy the long alphanumeric string.
4. The **FREE** plan gives 300 requests per month with full v2 access — enough for personal use. Paid plans are listed on the same page if you need more.
5. The key looks like `1a2b3c4d5e6f...` (32+ chars). Do NOT share it publicly or commit it to git.

### Adding the key to OpenHome

In **OpenHome Settings → API Keys**, add a new key with this exact name:

```text
listen_notes_api_key
```

Paste your Listen Notes key as the value and save.

Do **not** hardcode the key in `main.py` or store it in any prefs/config file.

## Main Intents

The LLM classifier returns one of six intents:

| Intent | When it fires | What happens |
|---|---|---|
| `browse_trending` | "what's trending", "popular podcasts", "what's hot" | Reads three top trending episodes; you pick one. |
| `play_random` | "random", "surprise me", "you pick", "any podcast" | Confirms first — only plays after explicit OK. |
| `play_latest` | "latest <podcast>", "newest <podcast> episode", "most recent" | Plays the newest episode of the named podcast directly. |
| `play_podcast` | User names a show without a specific episode | Searches the show, lists its recent episodes, you pick. |
| `play_episode` | User names a podcast plus guest/topic/episode title | Searches episodes (scoped to the podcast when given) and plays the best match. |
| `exit` | "stop", "I'm done", "that's all", "goodbye", "cancel" | Ends the session. |

## Follow-up Resolution

After the ability speaks a list of options (trending picks or recent episodes), you can reply with:

- **Ordinal** — "the first", "second one", "third one"
- **Descriptor** — "the one with Jensen", "the longer one", "the new one"
- **Re-route** — "actually, find me Huberman" → re-enters intent classification
- **Exit** — "none of those", "stop"

The `select_from_options` helper in `main.py` does this matching via the LLM.

## After Playback

When an episode finishes (or the user stops it), the ability speaks one of the
`CONTINUE_PROMPTS` — e.g. *"Want me to find you something else, or are you
good for now?"* — and loops back to intent classification. Any exit phrase
ends the session cleanly.

## Files

- `main.py` — ability implementation.
- `README.md` — this documentation.

## Listen Notes Endpoints Used

| Endpoint | Used for |
|---|---|
| `GET /best_podcasts` | Trending pool (browse + random) |
| `GET /search?type=podcast` | Resolving a named podcast |
| `GET /search?type=episode` | Episode lookup by title / guest / topic |
| `GET /podcasts/{id}/episodes` | Recent episodes of a selected podcast |

Audio is streamed from the `audio` URL returned by Listen Notes. If an episode
has no playable audio, the ability tells the user and asks for another pick.

## Notes

- Uses Listen Notes API **v2**.
- Uses `CapabilityWorker(self.worker)` and `self.worker.session_tasks.create(self.run())`.
- Trending pool size is 10 (`TRENDING_POOL_SIZE`); three are spoken to the user (`TRENDING_SPOKEN_OPTIONS`).
- Every spoken line goes through a short LLM "naturalness pass" so the wording sounds conversational, while podcast/episode/guest names are preserved exactly.
- Errors are summarized into a short friendly spoken sentence rather than read verbatim.
