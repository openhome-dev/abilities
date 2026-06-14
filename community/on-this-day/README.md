# On This Day in History

Tells you notable historical events for any calendar date, pulled live from Wikipedia's "On this day" REST feed. No API key, no setup.

Grounded, not guessed: rather than asking the agent to recall history from memory (where dates and details drift), this fetches Wikipedia's editorially curated events for the exact date, so the answers are sourced from a real, current third-party feed.

## Triggers

- "on this day"
- "what happened today in history"
- "this day in history"
- "what happened on June eleventh"

## Features

- Notable events for today, or any spoken date ("June eleventh", "Christmas")
- Defaults to today; stays in the loop so you can ask about another date
- Summarized for listening — you hear the highlights, not all 19 events
- No API key required; the Wikipedia feed is free
- Read-only: fetches public Wikipedia data, writes nothing, stores nothing

## Setup

None. The Wikipedia REST feed needs no key or token. Drop the ability in and set your trigger words in the dashboard.

## Example Usage

> "What happened today in history?"
> "Tell me about June eleventh."
> "What happened on Christmas?"
> "Done."

## How It Works

- Resolves a spoken date to a month and day, falling back to today if it is unclear
- Fetches the curated events from `en.wikipedia.org/api/rest_v1/feed/onthisday/selected/MM/DD`, sending a descriptive User-Agent (Wikimedia requires one — requests without it are rejected)
- Hands the events to the agent to summarize into a short spoken reply
- If the feed is unreachable, it says so and stays in the loop rather than failing
