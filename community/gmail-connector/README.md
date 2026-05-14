# Gmail Voice Assistant

Gmail Voice Assistant is an OpenHome community ability for managing Gmail by voice. It uses the user's linked Google account to list emails, read messages aloud, compose new emails, reply to threads, mark messages as read, archive emails, and remember contact hints for future requests.

## What It Does

- Lists recent, unread, today, yesterday, date-specific, or sender-specific Gmail messages
- Reads a selected email aloud with a concise spoken summary
- Marks an email as read after opening it
- Lets the user reply immediately after hearing an email
- Archives an email after reading when the user asks
- Composes new emails by collecting recipient, subject, and message body
- Fixes basic grammar, spelling, and capitalization before sending
- Replies to a specific email by sender, subject, keyword, or recent list position
- Marks one email or all shown emails as read from a list follow-up
- Remembers contacts from sent and replied messages
- Resolves follow-up references like `the first one`, `the invoice email`, or `from Ahmed`

## Supported Requests

| Request type | Example | What happens |
|---|---|---|
| List emails | `Check my unread emails` | Finds matching inbox emails and reads a short numbered list |
| List by date | `What came in today?` | Searches inbox mail from the requested date range |
| List by sender | `Show emails from Ahmed` | Searches Gmail for inbox messages from that sender |
| Read email | `Read the email from Sarah` | Finds the matching email, summarizes it, and marks it read |
| Compose email | `Send an email to Ahmed` | Collects missing recipient, subject, or body, then sends |
| Reply | `Reply to the invoice email saying payment sent` | Finds the email and sends a thread reply |
| Mark read | `Mark all as read` | Marks all currently shown emails as read |
| Archive | `Archive that one` | Removes the current email from the inbox |
| More results | `Show more` | Continues through the current email list |

## Example Prompts

- "Check my unread emails."
- "What came in today?"
- "Show emails from Ahmed."
- "Show emails from last Friday."
- "Read the first one."
- "Read the email about the invoice."
- "Reply to Sarah saying sounds good."
- "Reply to the invoice email saying payment sent."
- "Send an email to Jordan."
- "Mark all as read."
- "Archive this email."

## Trigger Phrases

- `gmail`
- `open gmail`
- `check gmail`
- `check my email`
- `read my email`
- `send an email`
- `reply to email`

## Account Linking Guide

This ability does not use a manual API key. It reads a Google OAuth token from OpenHome with:

```python
self.capability_worker.get_token("google")
```

Before using the ability, connect the Google account that owns the Gmail inbox you want OpenHome to manage.

1. Open OpenHome.
2. Go to **Settings -> Linked Accounts**.
3. Choose **Google**.
4. Sign in to the Google account you want to use.
5. Approve the requested Google permissions.
6. Return to OpenHome and enable or install the Gmail ability.
7. Add trigger phrases such as `gmail`, `check my email`, and `send an email`.
8. Start a conversation and say one of the trigger phrases.

If the Google account is not linked, the ability will say that the account is not connected and stop.

## Data Access

| Service | Authentication | Used for |
|---|---|---|
| Gmail API | Linked Google account | Listing, reading, sending, replying, marking read, and archiving Gmail messages |

The ability can read email metadata and message bodies when the user asks it to list or read mail. It can send new emails and replies only during the compose or reply flows.

## Stored Data

The ability stores non-secret contact hints in:

```json
gmail_contacts.json
```

This file maps names or local email parts to email addresses so future voice requests like "email Ahmed" can resolve more easily. OAuth tokens are handled by OpenHome and are not stored in this file.

## Voice Flow

1. User triggers the ability.
2. The ability waits for the complete trigger transcription.
3. It checks for a linked Google account.
4. It builds a Gmail API service from the OpenHome Google token.
5. It classifies the request as `COMPOSE`, `REPLY`, `READ`, `LIST`, or `UNKNOWN`.
6. If the request is unclear, it asks what the user wants to do.
7. The selected flow asks for any missing details.
8. The ability performs the Gmail action.
9. The ability calls `resume_normal_flow()` so the OpenHome agent can continue normally.

## Flow Details

- **List**: searches by unread, recent, today, yesterday, sender, or a specific date, then reads emails in batches of five.
- **Read**: opens a specific email or asks the user to choose from unread messages, then summarizes the body.
- **Reply**: resolves the target email from context or Gmail search, collects reply content, lightly fixes wording, and sends the reply.
- **Compose**: extracts any fields already spoken, asks for missing fields, lightly fixes the body, and sends the email.
- **Follow-up list actions**: after listing emails, the user can read one, reply, show more, mark read, compose, or finish.

## Developer Credit

Developed by [@samsonadmasu](https://github.com/samsonadmasu).
