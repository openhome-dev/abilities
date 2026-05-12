# OpenHome Daily Brief

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@ammyyou112-lightgrey?style=flat-square)

## What It Does

Voice-activated morning briefing that fetches weather, Google Calendar, and Gmail, then turns everything into one short spoken summary. Calendar events use the user's OpenHome timezone. Weather is spoken in Celsius when location can be detected, with a timezone-based fallback when precise location is unavailable.

## Suggested Trigger Words

Recommended trigger words and phrases:

- "daily brief"
- "morning brief"
- "what's up for today"
- "what's on my calendar today"
- "brief me"
- "start my day"

Avoid relying on very generic phrases like "good morning" on their own, because they can overlap with normal assistant conversation more easily.

## Setup

1. **Connect Google** — In OpenHome, go to **Settings** -> **Linked accounts** and connect your Google account.

2. **Grant access** — Make sure Google Calendar and Gmail access are enabled for the linked account.

3. **Upload** — Zip this folder, upload to [app.openhome.com](https://app.openhome.com) → Abilities → Add Custom Ability, set trigger words in the dashboard.

If Google is not connected, the Ability will say: "Your Google account isn't connected. Go to Settings, Linked accounts, and connect Google."

## Files To Include

For a clean ability package, include:

- `main.py`
- `README.md`

Do not include local cache files, `__pycache__/`, or other editor-generated artifacts in the uploaded zip.

## How It Works

1. User says a trigger phrase (e.g. "daily brief").
2. Ability checks that the user's Google account is connected.
3. Ability fetches weather (Open-Meteo, free), calendar (Google Calendar API), and unread Gmail count.
4. LLM synthesizes the data into one short spoken briefing using plain spoken English.
5. Ability says "Have a great day" and exits.

## Voice UX Notes

- The spoken briefing is intentionally short and split into small speech chunks for smart-speaker playback.
- Temperatures are always spoken in Celsius.
- The generated briefing is cleaned to avoid duplicate greetings, duplicate sign-offs, markdown-like formatting, and awkward long chunks.
- Gmail is summarized as unread count only for a faster main briefing.
- If precise weather location is unavailable, the Ability falls back to a timezone-based location hint instead of inventing a city.

## Failure Handling

- If Google is not connected, the Ability gives a spoken setup instruction and exits.
- If one service is unavailable, the briefing still continues with the data that is available.
- If all services fail, the Ability says to try again in a moment.
- If weather location cannot be determined, the briefing says weather is unavailable instead of guessing.

## Example Conversation

> **User:** "Daily brief."
> **AI:** "Good morning! Let me get your brief."
> **AI:** "It's Friday, May 8. It's 26 degrees Celsius with clear skies in San Francisco. You have 12 unread emails. You have 1 meeting on 11 AM wiht the dev team."
> **AI:** "Have a great day!"
