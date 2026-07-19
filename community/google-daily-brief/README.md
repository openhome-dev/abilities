# Daily Morning Brief

Daily Morning Brief is an OpenHome community ability that gives the user a short voice briefing for the day. It combines weather, today's Google Calendar events, and today's unread Gmail count into three concise spoken sections.

## What It Does

- Gives a warm morning introduction
- Fetches local weather using Open-Meteo
- Uses the user's OpenHome timezone for today's date and calendar window
- Fetches today's Google Calendar events from the primary calendar
- Counts today's unread Gmail messages in the inbox
- Synthesizes weather, email, and calendar into a short spoken briefing
- Speaks temperatures in Celsius
- Falls back from IP-based location to saved location, then timezone-based location when possible
- Stores only non-secret location preferences for faster future weather lookup
- Exits cleanly back to the normal OpenHome conversation

## Briefing Sections

| Section | Data source | What it says |
|---|---|---|
| Weather | Open-Meteo plus detected location | Current temperature, conditions, high, low, and rain chance |
| Email | Gmail API | Today's unread inbox count |
| Calendar | Google Calendar API | Up to five events from today's primary calendar |

## Example Prompts

- "Daily brief."
- "Morning brief."
- "Brief me."
- "Start my day."
- "What's up for today?"
- "What's on my calendar today?"

## Trigger Phrases

- `daily brief`
- `morning brief`
- `brief me`
- `start my day`
- `what's up for today`
- `what's on my calendar today`

Avoid using only `good morning` as the trigger phrase because it can overlap with normal assistant conversation.

## Account Linking Guide

This ability does not use a manual Google API key. It reads a Google OAuth token from OpenHome with:

```python
self.capability_worker.get_token("google")
```

Before using the ability, connect the Google account that contains the Gmail inbox and Google Calendar you want included in the brief.

1. Open OpenHome.
2. Go to **Settings -> Linked Accounts**.
3. Choose **Google**.
4. Sign in to the Google account you want to use.
5. Approve the requested Google permissions for Gmail and Calendar access.
6. Return to OpenHome and enable or install the Daily Morning Brief ability.
7. Add trigger phrases such as `daily brief`, `morning brief`, and `start my day`.
8. Start a conversation and say one of the trigger phrases.

If the Google account is not linked, the ability will say that the account is not connected and stop.

## Data Access

| Service | Authentication | Used for |
|---|---|---|
| Google Calendar API | Linked Google account | Reading today's primary calendar events |
| Gmail API | Linked Google account | Counting today's unread inbox messages |
| Open-Meteo | No API key | Fetching current weather and daily forecast |
| IP geolocation | Public client IP when available | Estimating location for weather |

The ability reads only the minimum data needed for the brief: event titles/times/locations, unread Gmail count, and weather information. It does not send emails, modify calendar events, or change tasks.

## Location Behavior

Weather needs a latitude and longitude. The ability resolves location in this order:

1. Public IP geolocation when available.
2. A previously saved location from `daily_brief_prefs.json`.
3. A timezone-based fallback for known timezones.
4. If none of those work, the weather section is reported as unavailable.

## Stored Data

The ability stores non-secret location preferences in:

```json
daily_brief_prefs.json
```

Example shape:

```json
{
  "location": {
    "lat": 40.7128,
    "lon": -74.006,
    "city": "New York",
    "source": "ip_geolocation",
    "saved_at": "2026-05-14T12:00:00+00:00"
  }
}
```

OAuth tokens are handled by OpenHome and are not stored in this file.

## Voice Flow

1. User triggers the ability.
2. The ability checks for a linked Google account.
3. It speaks a short opening line.
4. It determines the user's timezone.
5. It resolves a weather location.
6. It fetches weather, today's calendar events, and today's unread Gmail count.
7. It asks the LLM to synthesize the data into three short sections: weather, email, and calendar.
8. It speaks each section with a short pause between them.
9. It speaks a short closing line.
10. It calls `resume_normal_flow()` so the OpenHome agent can continue normally.

## Failure Handling

- If Google is not linked, the ability gives setup guidance and exits.
- If weather location cannot be determined, the weather section becomes unavailable instead of guessing.
- If Gmail or Calendar is temporarily unavailable, the brief continues with the data that did load.
- If every data source fails, the ability asks the user to try again later.
- Generated text is cleaned to remove duplicate greetings, duplicate sign-offs, markdown, URLs, and awkward formatting.

## Files

- `main.py` - ability implementation.
- `README.md` - this documentation.

Developed by [@Ammad Yousaf](https://github.com/ammyyou112).
