# Google Calendar Ability

Voice-controlled Google Calendar integration for OpenHome. Supports scheduling, rescheduling, deleting events, managing attendees, listing schedules, querying who's on a meeting, and conflict detection.

## Setup

### Google Account

Link your Google account in OpenHome settings. The ability uses the platform's built-in Google authentication — no API keys or tokens to configure manually.

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
| Schedule | "Schedule a meeting with Mark tomorrow at 3 PM", "Schedule a call with Jim Friday at noon" |
| Reschedule | "Move the standup to 4 PM", "Reschedule test meeting to Friday" |
| Delete | "Cancel the meeting tomorrow", "Delete the standup" |
| Rename | "Rename the standup meeting to team sync", "Change the name of that call" |
| Make recurring | "Make that a weekly recurring", "Set the standup to repeat every week" |
| List | "What's on my calendar tomorrow", "What do I have at 2 PM" |
| Invite | "Add Tim to the standup", "Invite Jessica to that meeting" |
| Remove attendee | "Take Gus off the invite", "Remove Sophia from the weekly standup" |
| Query attendees | "Who's on the standup?", "Who's attending the meeting tomorrow?" |
| Accept invite | "Accept that invite", "Accept the shared meeting" |
| Decline invite | "Decline the invite", "Turn down that meeting" |
| Set reminder | "Remind me 20 minutes before my workout session", "Set a 60 minute reminder for the board meeting" |

## Key Behaviors

**Active capability (main.py)**

Handles all user-initiated calendar actions above. At any confirmation step the user can append a
follow-on request — "Sounds good, but also invite John" — and both actions execute. After any
operation, vague references like "that meeting" or "this event" resolve to the last touched event
without re-searching.

When scheduling or rescheduling, overlapping events are detected and the user is warned before
proceeding. List queries like "what do I have at 2 PM" find events spanning that time, not just
events starting then.

If an event name isn't recognized, the ability asks for clarification and retries the lookup up to
twice — it does not drop context or treat the clarification as a new scheduling request.

Per-meeting reminder preferences are stored persistently and survive restarts. Contacts are resolved
by first name from a local contact list. Timezone is automatically detected from your OpenHome profile.

**Background daemon (background.py)**

Polls the calendar every 30 seconds and maintains a local events cache and `upcoming_schedule.md`.
Proactively interrupts with spoken notifications for:

- New invites received from other organizers — "You got an invite to Shared Meeting today at 8 PM"
- Events cancelled by the organizer
- Events renamed or rescheduled externally
- Attendees accepting or declining
- New attendees added to an event you're on

Meeting reminders fire based on per-event preferences stored in `user_preferences.md`. The default
lead time is configurable, and individual meetings can have their own override (e.g.
`Standup meeting: 30 min`, `HR meeting: 60 min`).

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
Remind me about
