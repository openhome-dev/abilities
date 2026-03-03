# Google Calendar Ability

Voice-controlled Google Calendar integration for OpenHome. Supports scheduling, rescheduling, deleting events, managing attendees, listing schedules, querying who's on a meeting, and conflict detection.

## Setup

### Google Cloud Credentials

You need three values: a **Client ID**, **Client Secret**, and **Refresh Token** with the `calendar.events` scope.

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or select an existing one).
3. Enable the **Google Calendar API** under APIs & Services > Library.
4. Go to APIs & Services > Credentials > Create Credentials > OAuth 2.0 Client ID.
   - Application type: **Desktop app**.
   - After creating, go back into the credential and add `http://localhost:8080/` under **Authorized redirect URIs**.
5. Copy the **Client ID** and **Client Secret**.
6. Run the token generation script locally with your id and secret values to get a refresh token:

```
pip install google-auth-oauthlib
```

```
python token_gen.py
```

This opens a browser window to sign in with the Google account whose calendar you want to control. After authorizing, it prints the refresh token.

7. Paste all three into `main.py`:

```python
CLIENT_ID = "your-client-id"
CLIENT_SECRET = "your-client-secret"
REFRESH_TOKEN = "your-refresh-token"
```

Also set your timezone:

```python
DEFAULT_TIMEZONE = "America/Los_Angeles"
```

### contacts.json

Place a `contacts.json` file in the ability directory (next to `main.py`). This maps names to email addresses so the ability can resolve spoken names to calendar invitees.

Two formats are supported:

**Simple** -- just name-to-email:

```json
{
  "Dude": "dude@example.com",
  "Buddy": "buddy@example.com"
}
```

**With aliases** -- for names that speech-to-text frequently mishears:

```json
{
  "Friend": {
    "email": "friend@example.com",
    "aliases": ["Fren", "Frind", "Fred"]
  }
}
```

Aliases are matched phonetically by the LLM, so STT errors like "Von" for "Vaughn" get resolved correctly. Without this file, attendee features (invite, remove, query) are disabled.

## Supported Intents

| Intent | Example phrases |
|---|---|
| Schedule | "Schedule a meeting with 'sales meeting' for tomorrow at 3 PM" |
| Reschedule | "Move the standup to 4 PM", "Reschedule test meeting to Friday" |
| Delete | "Cancel the sales meeting tomorrow", "Delete the standup" |
| List | "What's on my calendar tomorrow", "What do I have at 2 PM" |
| Invite | "Add Vaughn to the standup meeting", "Invite Chris to that meeting" |
| Remove attendee | "Take Melody off the invite", "Remove Vaughn from the meeting" |
| Query attendees | "Who's on the standup?", "Who's attending the meeting tomorrow?" |

## Key Behaviors

**Conflict detection** -- When scheduling or rescheduling, the ability checks for overlapping events and warns before proceeding.

**Time awareness** -- Queries like "what do I have at 2 PM" find events that span that time, not just events starting at that time. Events in progress or starting soon are flagged.

**Compound confirmations** -- At any confirmation step, the user can say "Sounds good, but also invite Melody" and both actions are handled.

**Session context** -- After any operation, "that meeting" / "this event" resolves to the last touched event without re-searching.

## Recommended Hotwords

Calendar
Schedule
What is on my
Reschedule
Invite
Uninvite
Push back
What do I have going on
Who's on
Who's going to be
Cancel
Meeting
