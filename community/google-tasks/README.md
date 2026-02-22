# Google Tasks

Voice-powered Google Tasks management for OpenHome. Add tasks, check what's due, mark things done, get daily summaries, and switch between lists — all by voice.

## Features

- **Add Tasks** — "Add a task: call the dentist by Friday"
- **List Tasks** — "What's due today?" / "What's on my list?"
- **Complete Tasks** — "Mark call the dentist done" / "Complete task 2"
- **Daily Summary** — "Task summary" / "How's my day?"
- **Switch Lists** — "Switch to Work list" / "What lists do I have?"

## Setup

This ability uses **Google Tasks API v1** with OAuth 2.0 authentication. You'll need to set up a Google Cloud project (one-time).

### Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Go to **APIs & Services → Library**
4. Search for **"Tasks API"** and click **Enable**

### Step 2: Configure OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**
2. Choose **External** (for personal accounts)
3. Set app name (e.g., "OpenHome Tasks")
4. Add scope: `https://www.googleapis.com/auth/tasks`
5. Add your email as a **test user**

### Step 3: Create OAuth Credentials

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Web application**
4. Add **Authorized redirect URI**: `https://localhost`
5. Copy the **Client ID** and **Client Secret**

### Step 4: Connect via Voice

When you first trigger the ability, it will walk you through:
1. Entering your Client ID and Client Secret
2. Opening a browser link to authorize access
3. Pasting the authorization code

After setup, the ability remembers your credentials.

## Usage Examples

| Say This | What Happens |
|---|---|
| "Add a task: call the dentist by Friday" | Creates a task with a due date |
| "Remind me to buy groceries tomorrow" | Creates a task due tomorrow |
| "What's due today?" | Lists tasks due today |
| "What's on my list?" | Lists all incomplete tasks |
| "Mark call the dentist done" | Completes the matching task |
| "Complete task 2" | Completes the 2nd task from last listing |
| "Task summary" | Overview of overdue, today, upcoming tasks |
| "Switch to Work list" | Changes active task list |
| "What lists do I have?" | Shows all available lists |

## Voice Tips

- After listing tasks, you can reference them by number: "Mark the first one done"
- Say "done" or "stop" to exit the ability
- Due dates are **date only** — Google Tasks doesn't support specific times
- If a task name is ambiguous, you'll be asked to clarify

## Important Notes

- **Testing mode**: If your Google Cloud app is in "Testing" status, tokens expire after 7 days and you'll need to re-authorize. To avoid this, publish your app (requires Google review for external apps).
- **No text search**: Google Tasks API has no search feature. The ability fetches your tasks and matches by name using fuzzy matching.
- **Date only**: Google Tasks only stores dates, not times. "By 3pm Friday" will be stored as "Friday" with no time.
- **Timezone**: Your timezone is auto-detected from your IP on first run.

## API Reference

- [Google Tasks API v1](https://developers.google.com/tasks/reference/rest)
- [OAuth 2.0 for Google APIs](https://developers.google.com/identity/protocols/oauth2)

## Trigger Words

task, tasks, to do, todo, add a task, new task, remind me, my tasks, what's due, task list, mark done, complete task, check off, task summary, daily tasks, overdue, switch list, google tasks, what do I need to do, finish task
