# Gmail Connector

A voice-powered Gmail client. Manage your inbox entirely by voice — summarize unread emails, read specific messages aloud, reply, compose, search, mark as read, archive, and triage one-by-one.

---

## What You Need Before Starting

1. A [Composio](https://composio.dev) account
2. Your Gmail account connected to Composio
3. Your Composio **API Key** and **Entity ID**

---

## Step 1 — Create a Composio Account

1. Go to [composio.dev](https://composio.dev) and sign up
2. Complete the onboarding steps

---

## Step 2 — Get Your API Key

1. In the Composio dashboard, click **Settings** in the left sidebar
2. Click the **API Keys** tab
3. Copy your API key — it starts with `ak_`
4. Save it somewhere safe — this is your `COMPOSIO_API_KEY`

---

## Step 3 — Connect Your Gmail Account

1. In the Composio dashboard, click **All Toolkits** (top right)
2. Search for **Gmail** and click on it
3. Click **Add to Project**
4. Click **Connect Account**
5. A Google sign-in window will appear — sign in and allow all permissions
6. You will be redirected back to Composio with Gmail shown as **Active**

---

## Step 4 — Get Your Entity ID

1. In the Composio dashboard, click on your **Gmail app** (e.g. `gmail-xxxxxx`) in the sidebar
2. Click **Connected Accounts**
3. You will see a table with columns: Account ID, User ID, Status
4. Copy the value in the **User ID column** — this is your **Entity ID**
5. It looks like: `pg-test-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

---

## Step 5 — Add Your Credentials to main.py

Open `main.py` and find these lines near the top:

```python
COMPOSIO_API_KEY = "YOUR_COMPOSIO_API_KEY"
COMPOSIO_USER_ID = "YOUR_COMPOSIO_USER_ID"
COMPOSIO_ENTITY_ID = "YOUR_COMPOSIO_ENTITY_ID"
```

Replace them with your actual values:

```python
COMPOSIO_API_KEY = "ak_xxxxxxxxxxxxxxxxxxxx"
COMPOSIO_USER_ID = "pg-test-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
COMPOSIO_ENTITY_ID = "pg-test-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

> **Note:** `COMPOSIO_USER_ID` and `COMPOSIO_ENTITY_ID` are the same value — both should be set to the User ID you copied in Step 4.

---

## Step 6 — Upload and Deploy

1. Zip the folder containing `main.py`, `README.md`, and `__init__.py`
2. Upload the zip to your deployment dashboard
3. Add the trigger words below to your configuration

---

## Trigger Words

```
email, emails, inbox, gmail, unread emails, new emails,
check my email, check email, read my email, read email,
any new email, do I have email, send an email, send email,
write an email, reply to email, email from, triage my email,
go through my email, catch me up on email
```

---

## How to Use It

| What You Say | What It Does |
|---|---|
| "Check my email" | Summarizes your unread inbox |
| "Did Sarah email me?" | Finds and reads Sarah's email |
| "Triage my inbox" | Goes through emails one by one |
| "Send an email to Mike" | Starts compose flow |
| "Reply — tell her I'll fix it today" | Drafts and sends a reply |
| "Archive that" | Moves current email to trash |
| "Mark it as read" | Marks current email as read |

---

## Example Conversation

```
You:  "Did Sarah email me?"
Bot:  "One sec, checking your inbox."
Bot:  "Yes — Sarah sent the Q3 deck and flagged two issues in slide 8. Want me to read the full email?"
You:  "Yes"
Bot:  [reads email summary]
Bot:  "Want to reply, archive, or move on?"
You:  "Reply — tell her I'll fix slide 8 today"
Bot:  "Here's what I'll send: I'll fix slide 8 today, thanks for flagging it. Should I send it?"
You:  "Yes"
Bot:  "Reply sent! Anything else with your email?"
You:  "No thanks"
Bot:  [exits]
```

---

## How It Was Built — For Developers

This section explains the architecture so you can build something similar or extend it.

### Core Architecture

The connector is a **single Python class** (`main.py`) with no external dependencies beyond `requests`. All Gmail operations go through **Composio** as a middleware layer — meaning you never deal with Google OAuth directly. Composio handles authentication and exposes Gmail as simple REST API calls.

### How Composio Is Used

Every Gmail action (fetch, send, reply, search) goes through one central function:

```python
def execute_composio_action(self, action_slug: str, params: dict):
    url = f"https://backend.composio.dev/api/v2/actions/{action_slug}/execute"
    payload = {
        "entityId": COMPOSIO_ENTITY_ID,
        "appName": "gmail",
        "input": params,
    }
    response = requests.post(url, json=payload, headers={"X-API-KEY": COMPOSIO_API_KEY})
```

Key things to note:
- `entityId` must match the **User ID** shown in Composio Connected Accounts — not `"default"`, not the Account ID
- `appName` must be set to `"gmail"` when not passing a `connectedAccountId`
- Action slugs like `GMAIL_FETCH_EMAILS` and `GMAIL_SEND_EMAIL` map directly to Composio's toolkit actions

### Intent Classification

Rather than hardcoding keyword matching, the developer used **LLM-based intent classification**. When the user speaks, their message is sent to a language model with a structured prompt that returns JSON like:

```json
{
  "intent": "read_specific",
  "mode": "quick",
  "details": { "sender": "Sarah" }
}
```

This makes the connector flexible — users can phrase things naturally and the system figures out what they mean without rigid command matching.

### Two Modes: Quick vs Full

- **Quick mode** — answers one question, offers a brief follow-up, then exits
- **Full mode** — opens an interactive loop, stays active until the user says done

The mode is decided automatically based on the trigger phrase using the same LLM classification step.

### Voice UX Pattern

All spoken responses are kept to 1-2 sentences. Filler speech like *"One sec, checking your inbox"* plays before API calls to avoid awkward silence while waiting for a response.

Send and reply actions always require voice confirmation before executing — the bot reads the draft aloud and waits for "yes" before sending anything.

---

### If You Want to Build Something Similar

**To connect a different app (Slack, Calendar, Notion, etc.):**
- Create a Composio account and connect your app the same way as Gmail
- Replace the action slugs (e.g. `GMAIL_FETCH_EMAILS` → `SLACK_LIST_MESSAGES`)
- Keep the same `execute_composio_action` function — only the slug and `input` params change

**To add a new Gmail action (e.g. label emails):**
- Find the slug in Composio's Gmail toolkit (e.g. `GMAIL_MODIFY_MESSAGE`)
- Add a new method calling `execute_composio_action` with the right params
- Add the intent to the classification prompt and route it in `route_session_intent`

**To swap out Composio for direct Gmail API:**
- Replace `execute_composio_action` with Google's Gmail REST API
- Handle OAuth2 yourself using `google-auth` and `google-api-python-client`
- Everything else (intent classification, conversation flow, response parsing) stays the same

**Composio action slugs used in this project:**

| Slug | What It Does |
|---|---|
| `GMAIL_FETCH_EMAILS` | List unread or searched emails |
| `GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID` | Get a single email by ID |
| `GMAIL_SEND_EMAIL` | Send a new email |
| `GMAIL_REPLY_TO_THREAD` | Reply to an existing thread |
| `GMAIL_MOVE_TO_TRASH` | Archive / trash an email |

---

## Files

| File | Purpose |
|---|---|
| `main.py` | All connector logic |
| `README.md` | This setup guide |
| `__init__.py` | Empty package marker |

---

## Troubleshooting

| Error | Fix |
|---|---|
| `Invalid uuid` | Use the **User ID** from Connected Accounts, not the Account ID |
| `No connected account found` | Your Entity ID is wrong — copy it again from Composio Connected Accounts |
| `App name and entity id must be present` | Make sure `appName: "gmail"` is included in the payload |
| `401 Unauthorized` | API key is wrong or expired — regenerate it in Composio Settings |
| `429 Rate Limited` | Wait a minute and try again |
| Gmail shown as inactive | Reconnect your Gmail account in Composio |
