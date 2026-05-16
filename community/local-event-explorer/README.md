# Events Explorer

Event Explorer is an OpenHome community ability for finding events by voice. It helps users discover concerts, comedy, sports, festivals, hackathons, workshops, networking events, food events, wellness events, and other local things to do.

## What It Does

- Finds events in a city the user names
- Uses the user's saved home city when no city is provided
- Handles nearby searches with IP-based city detection when available
- Understands common city aliases like `NYC`, `LA`, `SF`, and `Vegas`
- Parses natural date phrases like `tonight`, `tomorrow`, `this weekend`, `next week`, and `May 20`
- Defaults to `this week` when the user does not provide a date
- Shows a short list of matching events
- Lets the user ask for more results
- Lets the user ask for details about a specific event
- Lets the user add an event to Google Calendar when Google OAuth is available

## Event Types

The ability supports broad event categories, including:

- Concerts and music
- Comedy and stand-up
- Sports
- Theater, opera, dance, and shows
- Festivals, fairs, expos, and conferences
- Hackathons, coding events, startup events, and tech meetups
- Workshops, seminars, networking, career fairs, and bootcamps
- Art, film, poetry, talks, books, and museum events
- Food, drink, wine, beer, tastings, and markets
- Yoga, fitness, wellness, running, and community events
- Family, kids, charity, volunteer, nightlife, parties, and DJ events

## Data Sources

Events Explorer can use three event sources:

| Source | OpenHome API key name | Role |
|---|---|---|
| Ticketmaster Discovery API | `ticketmaster_api_key` | Primary structured event search |
| Serper.dev | `serper_api_key` | Google Events and search fallback |
| SeatGeek | `seatgeek_api_key` | Fallback when Ticketmaster returns no events |

For hackathons and tech events, Serper can also use organic search results from event-focused domains such as Devpost, Eventbrite, Meetup, Luma, MLH, HackerEarth, Devfolio, Unstop, Startup Grind, Techstars, and Product Hunt.

Google Calendar does not need a separate API key. The ability uses the user's linked Google account through OpenHome OAuth when available.

## Trigger Phrases

- `event explorer`
- `events`
- `find events`
- `open event finder`
- `open events`
- `local event explorer`

## Example Prompts

- "Find comedy shows in Dallas this weekend."
- "Concerts in New York tonight."
- "Hackathons in San Francisco."
- "AI workshops in Austin next week."
- "Startup networking events in NYC."
- "Food events in Chicago."
- "Wellness events near me."
- "Tell me more about the first one."
- "Show me more."
- "Add that to my calendar."
- "Change city to Seattle."
- "No thanks."

## Setup

Add any event API keys you want to use in **OpenHome Settings -> API Keys**.

Use these exact key names:

- `ticketmaster_api_key`
- `serper_api_key`
- `seatgeek_api_key`

At least one event source should be configured for useful results. Ticketmaster is the best first key to add. Serper is especially helpful for broader web-discovered events like hackathons and workshops.

### Ticketmaster API Key

Ticketmaster is the best primary source for concerts, sports, comedy, theater, festivals, and ticketed events.

1. Go to the Ticketmaster Developer Portal: `https://developer.ticketmaster.com/`
2. Sign in or create a free developer account.
3. Open **My Apps**.
4. Create a new app, or open the default app Ticketmaster creates for you.
5. Copy the **Consumer Key**. This is the Discovery API key.
6. In OpenHome, go to **Settings -> API Keys**.
7. Add a key named:

```text
ticketmaster_api_key
```

8. Paste the Ticketmaster Consumer Key as the value.

### Serper API Key

Serper is used for Google Events-style search and broader web discovery. It is especially useful for hackathons, startup events, tech meetups, workshops, and community events that may not appear in Ticketmaster.

1. Go to Serper: `https://serper.dev/`
2. Sign in or create an account.
3. Open the Serper dashboard.
4. Copy your API key.
5. In OpenHome, go to **Settings -> API Keys**.
6. Add a key named:

```text
serper_api_key
```

7. Paste the Serper API key as the value.

### SeatGeek API Key

SeatGeek is used as a fallback source when Ticketmaster does not return results.

1. Go to SeatGeek Developer settings: `https://seatgeek.com/account/develop`
2. Sign in or create a SeatGeek account.
3. Register a new app.
4. Copy the **Client ID**.
5. In OpenHome, go to **Settings -> API Keys**.
6. Add a key named:

```text
seatgeek_api_key
```

7. Paste the SeatGeek Client ID as the value.

You usually do not need the SeatGeek Client Secret for this ability.

### Google Calendar

Google Calendar does not use a manual API key in this ability. If the user's Google account is linked in OpenHome, the ability can use that OAuth connection to add events directly to the calendar.

If Google is not linked, the ability falls back to a pre-filled Google Calendar link when possible.

## Saved Preferences

The ability stores only non-secret user preferences in:

```json
{
  "home_city": "Dallas"
}
```

Do not store API keys in the prefs file.

## Voice Flow

1. User opens the ability.
2. User gives an event type, city, or date.
3. The ability resolves city and date context.
4. It searches available event sources.
5. It speaks a short result list.
6. User can ask for details, more results, a different search, or calendar save.

## Developer Credit

Developed by [@megz2020](https://github.com/megz2020).
