# Gmail Connector

A voice-powered Gmail client for OpenHome. Manage your inbox entirely by voice — summarize unread emails, read specific messages aloud, reply, compose, search, mark as read, archive, and triage one-by-one.

## Features

- **Summarize Unread** — Get a quick spoken overview of your inbox
- **Read Specific** — "What did Sarah say?" reads back a matching email
- **Reply** — Dictate a reply, hear the draft read back, confirm before sending
- **Compose** — Multi-turn flow: recipient → subject → body → confirm → send
- **Search** — Find emails by sender, keywords, or date range
- **Mark as Read** — "Mark it as read" after listening to an email
- **Archive** — "Archive that" to remove from inbox (non-destructive)
- **Triage Mode** — Walk through unread emails one by one with quick actions

## Modes

| Mode | Trigger Examples | Behavior |
|------|-----------------|----------|
| **Quick** | "Did Sarah email me?", "Send Mike a quick email" | Answer the question, brief follow-up window, exit |
| **Full** | "Check my email", "Triage my inbox", "Catch me up" | Summary or triage, then open Q&A loop until exit |

## Suggested Trigger Words

- email
- emails
- inbox
- gmail
- unread emails
- new emails
- check my email
- check email
- read my email
- read email
- any new email
- do I have email
- send an email
- send email
- write an email
- reply to email
- email from
- triage my email
- go through my email
- catch me up on email

## Setup

### Prerequisites

1. A [Composio](https://composio.dev) account with a connected Google/Gmail account
2. Your Composio API key and connected account ID

### Configuration

1. Replace the placeholder values in `main.py`:
   ```python
   COMPOSIO_API_KEY = "YOUR_COMPOSIO_API_KEY"
   COMPOSIO_USER_ID = "YOUR_COMPOSIO_USER_ID"
   ```

2. Upload the ability zip to the OpenHome dashboard
3. Add the trigger words above to your ability configuration

### Composio Slugs

The ability uses these Composio action slugs (may need adjustment per your account):

- `GMAIL_FETCH_EMAILS` — list unread emails
- `GMAIL_GET_MESSAGE` — get single email by ID
- `GMAIL_SEND_EMAIL` — send a new email
- `GMAIL_REPLY_TO_THREAD` — reply to a thread
- `GMAIL_SEARCH` — search emails
- `GMAIL_MODIFY_MESSAGE` — add/remove labels (mark read, archive)

> **Tip:** Build a small debug ability first to test which slugs work with your Composio account and what the response format looks like.

## Example Conversations

### Quick Mode
```
User: "Did Sarah email me?"
Bot:  "One sec, checking your inbox."
Bot:  "Yes — Sarah sent the Q3 deck and flagged two issues in slide 8. Want me to read the full email?"
User: "Yes"
Bot:  [reads email summary]
Bot:  "Want to reply, archive, or move on?"
User: "Reply — tell her I'll fix slide 8 today"
Bot:  "Here's what I'll send: 'I'll fix slide 8 today — thanks for flagging it.' Should I send it?"
User: "Yes"
Bot:  "Reply sent! Anything else with your email?"
User: "No thanks"
Bot:  [exits to normal flow]
```

### Triage Mode
```
User: "Triage my inbox"
Bot:  "One sec, checking your inbox."
Bot:  "You have 5 unread emails. Let's go through them."
Bot:  "First — Sarah sent the Q3 deck with two issues flagged."
Bot:  "Reply, skip, mark read, or archive?"
User: "Archive"
Bot:  "Archived. Next — newsletter from TechCrunch about AI funding."
Bot:  "Reply, skip, mark read, or archive?"
User: "Skip"
...
```

## Voice UX Notes

- All spoken output is kept to 1-2 sentences
- Email addresses are read as "name at domain dot com"
- Dates are spoken naturally ("Tuesday at 3 PM")
- Filler speech plays before API calls to avoid silence
- Send/reply always requires voice confirmation
- Idle detection: 2 consecutive silences triggers exit offer

## Error Handling

- API timeouts: spoken fallback message
- 401 (expired token): prompts user to reconnect Gmail
- 429 (rate limit): asks user to try again in a minute
- No unread emails: "Your inbox is clear" (not treated as error)
- Unmatched sender: asks for more details instead of failing

## Files

- `main.py` — All ability logic (single class)
- `README.md` — This file
- `__init__.py` — Empty (package marker)
