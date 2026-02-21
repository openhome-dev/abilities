# Google Daily Brief

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@ammyyou112-lightgrey?style=flat-square)

## What It Does

Voice-activated morning briefing that fetches weather, Google Calendar, and Gmail in parallel, then synthesizes everything into one ~60-second spoken summary. Weather is personalized per user via IP geolocation.

## Suggested Trigger Words

- "good morning"
- "give me my brief"
- "give me a brief"
- "daily brief"
- "brief me"
- "start my day"
- "what did I miss"

## Setup

1. **Google Cloud Console** — Create a project, enable Google Calendar API and Gmail API, create OAuth 2.0 credentials (Desktop app), and download the JSON.

2. **Get tokens** — Run `get_google_token.py` (in project root) with your credentials to obtain access and refresh tokens via OAuth flow.

3. **Update main.py** — Replace `YOUR_CLIENT_ID_HERE`, `YOUR_CLIENT_SECRET_HERE`, `YOUR_ACCESS_TOKEN_HERE`, and `YOUR_REFRESH_TOKEN_HERE` with your values.

4. **Upload** — Zip this folder, upload to [app.openhome.com](https://app.openhome.com) → Abilities → Add Custom Ability, set trigger words in the dashboard.

## How It Works

1. User says a trigger phrase (e.g. "good morning").
2. Ability fetches weather (Open-Meteo, free), calendar (Google Calendar API), and email (Gmail API) in parallel.
3. LLM synthesizes the data into one cohesive spoken briefing.
4. User can say "repeat", "check my calendar", or "no" to exit.

## Example Conversation

> **User:** "Good morning."
> **AI:** "Good morning! Let me get your brief."
> **AI:** "Right now in Lahore it's 79 degrees with clear skies. Your calendar is clear today. You've got 201 unread emails including one from iCloud about storage. That's your brief!"
> **AI:** "Anything else?"
> **User:** "Check my calendar."
> **AI:** "There's nothing on your calendar today."
> **AI:** "Anything else?"
> **User:** "No."
> **AI:** "Have a great day!"
