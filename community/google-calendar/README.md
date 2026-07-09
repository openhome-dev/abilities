# Google Calendar Assistant

Google Calendar Assistant is an OpenHome community ability for managing Google Calendar by voice. It uses the user's linked Google account to create, list, update, and delete events from the primary Google Calendar.

## What It Does

- Creates Google Calendar events from natural spoken requests
- Supports quick event creation when the user gives title, time, attendees, location, or reminder details up front
- Supports step-by-step event creation for users who want guided prompts
- Adds event descriptions, attendees, locations, reminders, and optional Google Meet links
- Lists events for today, this week, this month, a specific date, a date range, or upcoming events
- Updates upcoming events by title or spoken reference
- Changes event title, description, date, start time, end time, location, attendees, reminders, or Google Meet settings
- Deletes upcoming events after confirming the matched event
- Uses the user's OpenHome timezone when parsing spoken dates and times
- Sends Google Calendar updates to attendees when events are created, updated, or deleted
- Exits cleanly back to the normal OpenHome conversation

## Supported Requests

| Request type | Example | What happens |
|---|---|---|
| Create event | `Schedule a meeting tomorrow at 3 PM` | Creates an event, asking only for missing details |
| Quick create | `Add dentist appointment Friday at 10 AM` | Extracts title and time from the request and creates quickly |
| Detailed create | `Create an event step by step` | Walks through title, description, time, attendees, location, Meet, and reminder |
| List events | `What's on my calendar today?` | Reads matching events from the primary calendar |
| List range | `Show my calendar from Monday to Thursday` | Lists events in that date range |
| Update event | `Move my team meeting to Friday at 2 PM` | Finds the event and applies the requested changes |
| Add attendee | `Add Sarah to the kickoff meeting` | Adds a spoken email address to an event |
| Add Meet | `Add a Google Meet link to my standup` | Updates the event with a Meet link |
| Delete event | `Delete my dentist appointment` | Confirms the matched event, then deletes it |

## Example Prompts

- "Google Calendar."
- "What's on my calendar today?"
- "Show my upcoming events."
- "Create a calendar event."
- "Schedule project sync tomorrow at 4 PM."
- "Create an event step by step."
- "Move my dentist appointment to Friday."
- "Rename the kickoff meeting to launch review."
- "Add a Google Meet link to my standup."
- "Delete my team meeting."

## Trigger Phrases

- `google calendar`
- `calendar`
- `open calendar`
- `check my calendar`
- `what's on my calendar`
- `create calendar event`
- `schedule a meeting`
- `update calendar event`
- `delete calendar event`

## Account Linking Guide

This ability does not use a manual Google API key. It reads a Google OAuth token from OpenHome with:

```python
self.capability_worker.get_token("google")
```

Before using the ability, connect the Google account that owns the calendar you want OpenHome to manage.

1. Open OpenHome.
2. Go to **Settings -> Linked Accounts**.
3. Choose **Google**.
4. Sign in to the Google account you want to use.
5. Approve the requested Google Calendar permissions.
6. Return to OpenHome and enable or install the Google Calendar ability.
7. Add trigger phrases such as `google calendar`, `check my calendar`, and `schedule a meeting`.
8. Start a conversation and say one of the trigger phrases.

If the Google account is not linked, the ability will say that the account is not connected and stop.

## Data Access

| Service | Authentication | Used for |
|---|---|---|
| Google Calendar API | Linked Google account | Creating, listing, updating, and deleting primary calendar events |
| Google Meet conference data | Linked Google account | Adding Meet links when requested |

The ability can read event titles, dates, times, descriptions, locations, attendees, reminders, and conference information when needed for the requested action. It modifies or deletes events only after the user asks for that action, and delete actions include a confirmation step.

## Voice Flow

1. User triggers the ability.
2. The ability waits for the complete trigger transcription.
3. It checks for a linked Google account.
4. It builds a Google Calendar API service from the OpenHome Google token.
5. It reads the user's OpenHome timezone.
6. It classifies the request as `CREATE`, `LIST`, `UPDATE`, `DELETE`, or `UNKNOWN`.
7. If the request is unclear, it says "Google Calendar ready" and asks what the user wants to do.
8. The selected flow asks for any missing details, performs the calendar action, and speaks the result.
9. The ability calls `resume_normal_flow()` so the OpenHome agent can continue normally.

## Flow Details

- **Create**: extracts event details from the trigger phrase when possible. If details are missing, it asks whether the user wants a quick flow or a step-by-step flow.
- **Quick create**: collects title, start time, end time, attendees, Google Meet preference, location, and reminder from one spoken response where possible. Missing required fields are requested one at a time.
- **Detailed create**: asks for title, optional description, start and end time, attendees, location, Google Meet, and reminder.
- **List**: supports today, this week, this month, a specific date, a date range, or the next upcoming events.
- **Update**: searches upcoming events in the next 30 days, matches the requested event, extracts requested changes, applies them, and allows more changes before finishing.
- **Delete**: searches upcoming events in the next 30 days, matches the requested event, asks for confirmation, then deletes it.

## Timezone and Date Handling

The ability uses `self.capability_worker.get_timezone()` and LLM-assisted parsing to turn spoken phrases like `tomorrow at 3 PM`, `next Friday`, or `from Monday to Thursday` into calendar dates and times. It validates that newly created events are in the future and asks again if the time is missing or already passed.

## Stored Data

This ability does not store local preference files. Google OAuth tokens are handled by OpenHome and are not written to this ability folder.

## Failure Handling

- If Google is not linked, the ability gives account-linking guidance and exits.
- If Google Calendar cannot be reached, the ability asks the user to try again later.
- If a date or time cannot be parsed, the ability asks the user to repeat it in a clearer form.
- If an event cannot be matched for update or delete, the ability offers nearby upcoming options or asks for the exact title.
- If the user declines a delete confirmation, the event is left unchanged.

## Developer Credit

Developed by [@Mmiless](https://github.com/Mmiless).
