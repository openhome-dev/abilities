# Movie Recommender

Movie Recommender is an OpenHome community ability for discovering movies by voice. It helps users find recommendations, trending titles, similar movies, release dates, ratings, summaries, and streaming options using The Movie Database (TMDB).

## What It Does

- Recommends movies by genre, mood, year, or free-text request
- Finds trending and top-rated movies
- Finds similar movies from a title the user likes
- Gives details about a specific movie from the current results or by title
- Answers release-date questions, including upcoming movie phrasing
- Speaks ratings with a natural quality label like excellent, solid, mixed, or rough
- Looks up US streaming providers through TMDB watch providers
- Lets the user ask for more results without starting over
- Summarizes the current movie picks
- Handles vague requests with a clarifying question instead of a weak search
- Resolves ordinals and pronouns like `the second one`, `it`, and `that one`
- Gives one idle nudge after silence, then exits cleanly if the user stays quiet

## Supported Requests

| Request type | Example | What happens |
|---|---|---|
| Recommendation | `Recommend something scary` | Searches TMDB for matching movies and speaks a few picks |
| Trending | `What's trending in movies?` | Returns currently trending movies |
| Top-rated | `Best movies of all time` | Returns highly rated movies |
| Similar movies | `Movies like Inception` | Finds the source title, then recommends similar titles |
| Details | `Tell me about the second one` | Opens a specific movie and speaks a short synopsis |
| Release date | `When does it come out?` | Gives the release date for a named or focused movie |
| Rating | `What's that rated?` | Speaks the TMDB score with a short quality description |
| Watch providers | `Where can I watch it?` | Lists available US streaming providers from TMDB |
| More results | `Show me more` | Pages through the current search |
| Summaries | `What are these about?` | Gives short overviews of current picks |

## Voice Flow

```
[ ability triggered ]
   │
   ▼
"What movie are you in the mood for?"  (skipped if trigger has a real request)
   │
   ▼
classify_intent  →  one of: recommend / like / details / release /
                    rating / watch / more / summaries / ask / exit
   │
   ▼
handler speaks a short filler, calls TMDB, speaks results
   │
   ▼
continue prompt — turn 1 rich, turn 2 short, turn 3+ silent
   │
   ├─► next request          ──►  loop
   └─► exit phrase / silence ──►  end
```

## Example Prompts

- "What's trending in movies?"
- "Find me some best movies."
- "Recommend something scary."
- "Sci-fi releases in 2025."
- "Animated sci-fi movies."
- "Movies like The Matrix."
- "Search for Batman."
- "Tell me about the second one."
- "Is it released already?"
- "When does it come out?"
- "What's that rated?"
- "Where can I watch it?"
- "Stop, I want action movies." *(treated as a new search — "stop" alone exits, "stop, I want X" routes to recommend)*
- "Recommend more like these."
- "Stop."
- "Goodbye."
- "I don't want any movie."

## Trigger Phrases

- "movie recommender"
- "recommend a movie"
- "what should I watch"
- "trending movies"
- "movie suggestion"

## Data Source

Movie Recommender uses TMDB for movie search, discovery, details, ratings, release dates, similar movies, and watch providers.

| Source | OpenHome API key name | Role |
|---|---|---|
| The Movie Database (TMDB) | `tmdb_api_key` | Movie discovery, metadata, ratings, release dates, similar titles, and watch providers |

## Setup

Add your TMDB v3 API key in **OpenHome Settings → API Keys**:

```text
tmdb_api_key
```

Use the short TMDB v3 API key only. Do not use the API Read Access Token or API Secret, and do not hardcode the key in `main_v4.py`.

### Getting a TMDB API Key

1. Create or sign in to a TMDB account.
2. Open your account settings.
3. Go to the **API** section.
4. Request API access if it is not already enabled.
5. Choose **Developer** access and fill out the required application details.
6. After approval, copy the short key labeled `API Key (v3 auth)`.
7. In OpenHome, open **Settings -> API Keys**.
8. Add a new key named `tmdb_api_key`.
9. Paste the TMDB v3 API key as the value and save it.

If TMDB rejects the key, confirm that the saved value is the short v3 API key and that there are no extra spaces before or after it.

## Voice UX Notes

- **Short fillers** before TMDB calls so the user knows the ability is working.
- **Pre-formatted spoken lines** — no LLM naturalize pass between filler and result, which keeps mic-hot time short and avoids STT stitching artifacts.
- **Continue prompts taper** — turn 1 is a rich invitation ("Want details, more picks, or a different vibe?"), turn 2 is a shorter directional prompt, turn 3 onward listens silently so the ability stops sounding like a checkout clerk.
- **Exit routing owned by the LLM** — "stop", "okay stop", "stop now", "don't want any movie", "alright bye", "I'm done" are all recognized.
- **First-turn STT-bleed guard** — an exit phrase on the very first input is ignored once (a buffered wake-word can look like exit).

## Developer Credit

Developed by [@rizwan-095](https://github.com/rizwan-095).
