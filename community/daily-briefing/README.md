# Daily Briefing

A "good morning" voice ability for OpenHome that delivers a concise 30-second morning summary combining real-time weather, an inspirational quote, and a fun fact — all woven into a natural-sounding conversational briefing by the LLM.

## What It Does

When triggered, the ability:

1. Fetches current weather from **Open-Meteo** (free, no API key)
2. Fetches a daily quote from **ZenQuotes** (free, no API key)
3. Fetches a random fun fact from **Useless Facts API** (free, no API key)
4. Passes all three data points to the LLM, which weaves them into a natural 3-sentence morning briefing
5. Speaks the briefing aloud

After the briefing, users can:
- Ask for **more details** on the weather, quote, or fun fact
- **Change the city** for a different weather location
- **Hear the briefing again**
- Say **"done"** to exit

## Suggested Trigger Words

- "Good morning"
- "Morning briefing"
- "Daily briefing"
- "Start my day"
- "Morning update"
- "Give me my briefing"

## Example Conversation

> **User:** "Good morning"
>
> **Speaker:** "One moment, getting your morning update."
>
> **Speaker:** "Good morning! It's 45 degrees and partly cloudy in New York — layer up if you're heading out. Here's some wisdom from Mark Twain: 'The secret of getting ahead is getting started.' And fun fact — the first email was sent in 1971!"
>
> **Speaker:** "Want details on weather, quote, or fact? Or say done."
>
> **User:** "Tell me more about the weather"
>
> **Speaker:** "It's 45 degrees Fahrenheit with partly cloudy skies. Might want a jacket today!"
>
> **User:** "Change city to Austin"
>
> **Speaker:** "Which city would you like the briefing for?"
>
> **User:** "Austin"
>
> **Speaker:** *(delivers new briefing for Austin)*
>
> **User:** "Done"
>
> **Speaker:** "Have a great day!"

## Setup

No API keys required. All three APIs used are completely free and keyless:

| API | Purpose | URL |
|-----|---------|-----|
| Open-Meteo | Weather | api.open-meteo.com |
| ZenQuotes | Daily quote | zenquotes.io |
| Useless Facts | Fun fact | uselessfacts.jsph.pl |

Default location is New York. Users can change the city by voice during the session.

## How the SDK Is Used

| SDK Method | Purpose |
|------------|---------|
| `speak()` | Deliver the briefing and responses to the user |
| `run_io_loop()` | Ask follow-up prompts and listen for user replies |
| `text_to_text_response()` | LLM weaves raw API data into a conversational briefing; also used for city name extraction fallback |
| `user_response()` | Capture user input for city changes |
| `resume_normal_flow()` | Hand control back to the Personality when done |
| `editor_logging_handler` | Log API errors without using print() |

## Architecture

- **Keyword-first detection** for commands (weather/quote/fact/exit/location) — no LLM round-trip for simple intents
- **LLM fallback** for city name extraction when keyword match fails
- **Graceful degradation** — if any API fails, the briefing still delivers with available data
- **Interaction loop** with max 10 turns to prevent runaway sessions
- All exit paths call `resume_normal_flow()`
