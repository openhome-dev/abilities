# Outlook Calendar Ability

A voice-first calendar assistant for OpenHome. It connects to Microsoft Outlook via the Microsoft Graph API and gives users a spoken briefing of their day, plus the ability to create, reschedule, shorten, cancel, and manage attendees on calendar events — all through natural voice conversation.

---

## What It Does

- **Briefs you on your day** — upcoming meetings, who's on them, where they are
- **Creates events** — "Schedule a meeting with Jesse at 3 PM"
- **Reschedules events** — "Push my standup back 30 minutes"
- **Shortens or extends events** — "Make my 1:1 30 minutes instead"
- **Cancels events** — "Cancel my 4 PM"
- **Adds attendees** — "Invite jane at example dot com to the team sync"
- **Handles conflicts** — warns you when changes would overlap other meetings and offers to cascade the adjustment
- **Detects your location** — uses your IP to find local time, timezone, and weather (only mentioned if you have an in-person meeting)

---

## File Structure

```
OutlookCalendar/
├── main.py       # All ability logic
├── config.json   # Hotwords and unique name
└── README.md     # This file
```

---

## Setup

### 1. Get a Microsoft Graph Access Token

This ability uses the **Microsoft Graph API** to read and write your Outlook calendar. You need a valid OAuth 2.0 access token with the following permissions:

| Permission | Why |
|---|---|
| `Calendars.ReadWrite` | Read and modify calendar events |
| `User.Read` | Fetch your display name and email |

**How to get a token (quickest method for testing):**
1. Go to [Microsoft Graph Explorer](https://developer.microsoft.com/en-us/graph/graph-explorer)
2. Sign in with your Microsoft / Outlook account
3. Click your profile icon → copy the **Access Token**

For production, set up a proper OAuth app in [Azure Portal](https://portal.azure.com) under **App Registrations**.

---

### 2. Edit `main.py`

Open `main.py` and update the three constants near the top of the file:

```python
GRAPH_ACCESS_TOKEN = "YOUR_TOKEN_HERE"   # Paste your Graph access token
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"  # Leave this as-is
YOUR_EMAIL = "YOUR_EMAIL_HERE"           # Your Outlook email address
```

> ⚠️ **Important:** Access tokens expire (usually after 1 hour). For long-term use, implement a refresh token flow or use a service principal with a client credential.

---

### 3. Add `config.json`

Create a `config.json` file in the same folder as `main.py`:

```json
{
  "unique_name": "outlook_calendar",
  "matching_hotwords": [
    "what's on my calendar",
    "catch me up",
    "what do I have today",
    "check my schedule",
    "what's my day look like",
    "calendar check",
    "open my calendar"
  ]
}
```

You can add or remove hotwords to match however your users naturally trigger it.

---

### 4. Upload to OpenHome

- Zip the folder containing `main.py` and `config.json`
- Upload the zip in the OpenHome Live Editor or Ability Manager
- Assign it to a Personality

---

## How It Works

The ability has two modes it picks automatically based on how the user triggered it:

**Quick Mode** — triggered by a specific question ("what's on my calendar?")
- Answers the specific question directly
- Offers one follow-up, then exits cleanly

**Full Mode** — triggered by a broad request ("catch me up", "what's my day look like")
- Plays a filler phrase while fetching data in the background
- Delivers a full spoken briefing of your day
- Stays in a conversation loop until you say an exit word

### Exit Words
Say any of these to end the session:
`done`, `exit`, `stop`, `quit`, `bye`, `goodbye`, `nothing else`, `all good`, `I'm good`

---

## Voice Interaction Examples

| You say | What happens |
|---|---|
| "What's my day look like?" | Full briefing of your day |
| "What's on my calendar?" | Quick answer with your next events |
| "Push my standup back 30 minutes" | Reschedules it, warns you of conflicts |
| "Cancel my 4 PM" | Asks for confirmation, then cancels |
| "Schedule a call with Marcus at 2 PM" | Creates the event |
| "Add jane at acme dot com to the team sync" | Adds her as an attendee |
| "Shorten my next meeting to 30 minutes" | Updates the duration |

---

## Location & Weather

The ability uses your IP address to detect your city and timezone automatically. Weather is only mentioned if you have a meeting with a physical location (not a Zoom/Teams link) — no one needs to hear the weather for a video call.

If you're running OpenHome on a cloud server (AWS, GCP, Azure, etc.), the ability detects this and falls back to default location settings. Update these defaults in `main.py` if needed:

```python
# In collect_geo_context(), fallback section:
city = "New York"
region = "New York"
country = "US"
lat = 40.71
lon = -74.01
timezone = "America/New_York"
```

---

## Troubleshooting

**"Something went wrong. Signing off."**
Check the editor logs. Common causes: expired access token, incorrect email address in `YOUR_EMAIL`, or a network timeout on the Graph API.

**Events aren't showing up**
The ability only fetches events from now until midnight in your local timezone. Past events won't appear. Confirm your `YOUR_EMAIL` matches the account your token is scoped to.

**Timezone is wrong**
The ability auto-detects timezone from your IP. If it's incorrect (e.g., running on a server), set the fallback timezone values manually in the `collect_geo_context()` method.

**Token expired**
Graph API tokens typically expire after 1 hour. Refresh your token in Graph Explorer or implement a proper refresh token flow in production.

**Conflicts aren't being caught**
Conflict detection compares event times in UTC. If you see incorrect conflict warnings, check that your calendar events have a timezone set (not just a bare `dateTime` with no offset).

---

## Dependencies

All standard. No additional pip installs required beyond what OpenHome provides:

- `requests` — Graph API calls
- `json`, `os`, `re`, `datetime`, `random` — all Python standard library
- `zoneinfo` — built into Python 3.9+

---

## Notes for Developers

- **Never hardcode a production token** in `main.py`. Use environment variables or a secrets manager for production deployments.
- The ability refreshes calendar data after every write operation (create, update, cancel) so responses stay accurate within the same session.
- Session history is kept in memory only — it resets each time the ability is invoked.
- All logging goes through `self.worker.editor_logging_handler` — check the OpenHome Live Editor log panel when debugging.
