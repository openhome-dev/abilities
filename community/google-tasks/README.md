# Google Tasks

Voice-powered Google Tasks management for OpenHome. Add tasks, check what's due, mark things done, get daily summaries, and switch between task lists — all by voice. Uses OAuth 2.0 for secure authentication with your Google account.

## What It Does

| Mode | Example Voice Commands | Description |
|---|---|---|
| **Add Task** | "Add a task: call the dentist by Friday" / "Remind me to buy groceries tomorrow" | Creates a task with optional due date and notes |
| **List Tasks** | "What's due today?" / "What's on my list?" / "Any overdue tasks?" | Lists tasks with date filtering (today, this week, overdue, all) |
| **Complete Task** | "Mark call the dentist done" / "Complete task 2" / "Mark the first one done" | Completes a task by name, number, or position |
| **Daily Summary** | "Task summary" / "How's my day?" | Overview of overdue, today, upcoming, and undated tasks |
| **Switch List** | "Switch to Work list" / "What lists do I have?" | View and switch between Google Tasks lists |

## Quick Start

### Prerequisites

You need a Google Cloud project with the Tasks API enabled. This is a one-time setup (~5 minutes).

### Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the **project dropdown** (top-left) → **New Project**
3. Name it (e.g., `OpenHome Tasks`) → click **Create**
4. Select the new project from the dropdown

### Step 2: Enable the Tasks API

5. In the left sidebar, go to **APIs & Services → Library**
6. Search for **"Tasks API"** (by Google — NOT "Cloud Tasks API")
7. Click it → click **Enable**

### Step 3: Configure OAuth Consent Screen

8. Go to **APIs & Services → OAuth consent screen** (or **Google Auth Platform → Audience** in the new UI)
9. Select **External** → click **Create**
10. Fill in:
    - **App name**: `OpenHome Tasks`
    - **User support email**: `yourname@gmail.com`
    - **Developer contact email**: `yourname@gmail.com`
11. Click **Save and Continue**
12. On the **Scopes** page → click **Add or Remove Scopes** → paste `https://www.googleapis.com/auth/tasks` → click **Update** → **Save and Continue**
13. On the **Test users** page → click **Add Users** → add your Gmail address → click **Add** → **Save and Continue**

### Step 4: Create OAuth Client ID (Web Application)

14. Go to **APIs & Services → Credentials** (or **Google Auth Platform → Clients**)
15. Click **+ CREATE CREDENTIALS → OAuth client ID**
16. Application type: **Web application**
17. Name: `OpenHome Tasks Web`
18. Under **Authorized redirect URIs** → click **+ ADD URI** → paste: `https://developers.google.com/oauthplayground`
19. Click **Create**
20. **Copy the Client ID** (looks like `123456789-xxxxxx.apps.googleusercontent.com`)
21. **Copy the Client Secret** (looks like `GOCSPX-xxxxxx`)

### Step 5: Get Refresh Token from OAuth Playground

22. Go to [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground/)
23. Click the **gear icon ⚙️** (top right) → check **"Use your own OAuth credentials"**
24. Paste your **Client ID** and **Client Secret** from steps 20-21
25. Close the settings panel
26. In the left panel, in the **"Input your own scopes"** box, type: `https://www.googleapis.com/auth/tasks`
27. Click **"Authorize APIs"**
28. Sign in with your Google account → click **Continue** → click **Continue** again
29. Back at the Playground, click **"Exchange authorization code for tokens"**
30. In the response on the right, **copy the `refresh_token` value** (starts with `1//`)

### Step 6: Configure the Ability

Open `main.py` and replace the placeholder values at the top with all three values:

```python
GOOGLE_CLIENT_ID = "123456789-xxxxxx.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "GOCSPX-xxxxxx"
GOOGLE_REFRESH_TOKEN = "1//xxxxxx"
```

With all three pre-filled, the ability **skips OAuth entirely** and connects immediately.

**Alternative options:**

- **Pre-fill credentials only**: Fill just `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. On first use, the ability will guide you through getting a refresh token via OAuth Playground by voice.
- **Voice-guided setup**: Leave all placeholders as-is. On first use, the ability will ask for everything by voice.

### Step 7: Upload to OpenHome

1. Go to the **Customize Ability** page
2. Upload all 3 files: `main.py`, `__init__.py`, `README.md`
3. Fill in:
   - **Unique Name**: `google_tasks`
   - **Description**: Voice-powered Google Tasks management
   - **Hotwords**: task, tasks, to do, todo, add a task, new task, remind me, my tasks, what's due, task list, mark done, complete task, check off, task summary, daily tasks, overdue, switch list, google tasks, what do I need to do, finish task
4. Click **Start Live Test**

### Step 8: First-Run Authorization

If you pre-filled all three constants (Option A), the ability connects automatically — no authorization step needed.

Otherwise, on first use:

1. Say **"my tasks"** to trigger the ability
2. The ability will try the **device flow** first (enter a short code at google.com/device)
3. If that fails, it falls back to **OAuth Playground**: it will ask you to get a refresh token from [developers.google.com/oauthplayground](https://developers.google.com/oauthplayground/) and paste it in
4. The ability saves your tokens and auto-refreshes them going forward

## Testing Guide

### Full Test Checklist

**OAuth & Connection:**

| # | Say | Expected |
|---|---|---|
| 1 | "my tasks" | Triggers OAuth setup on first run, or goes straight to tasks if already connected |
| 2 | (after connecting) "my tasks" again | Should NOT re-do OAuth — goes straight to tasks |

**Add Tasks:**

| # | Say | Expected |
|---|---|---|
| 3 | "add a task call the dentist by Friday" | Creates task with due date |
| 4 | "remind me to buy groceries tomorrow" | Creates task due tomorrow |
| 5 | "new task submit report" | Creates task with no due date |
| 6 | "add a task" (no details) | Asks "What's the task?" → then you provide details |

**List Tasks:**

| # | Say | Expected |
|---|---|---|
| 7 | "what's due today?" | Lists tasks due today |
| 8 | "what's due this week?" | Lists tasks due this week |
| 9 | "what's on my list?" | Lists all incomplete tasks |
| 10 | "any overdue tasks?" | Lists overdue tasks |

**Complete Tasks:**

| # | Say | Expected |
|---|---|---|
| 11 | "mark the first one done" | Completes 1st task from last listing |
| 12 | "complete task 2" | Completes 2nd task from last listing |
| 13 | "mark call the dentist done" | Fuzzy matches task by name |
| 14 | "complete something random xyz" | "I couldn't find a task matching that..." |

**Daily Summary:**

| # | Say | Expected |
|---|---|---|
| 15 | "task summary" | Summary with overdue/today/upcoming/undated counts |
| 16 | "how's my day?" | Same summary in natural language |

**Switch Lists:**

| # | Say | Expected |
|---|---|---|
| 17 | "what lists do I have?" | Shows all task lists |
| 18 | "switch to Work" | Switches active list (if you have one) |
| 19 | "switch to My Tasks" | Switches back to default list |

**Follow-up & Exit:**

| # | Say | Expected |
|---|---|---|
| 20 | (after any action, wait for "Anything else?") | Ability stays active for follow-up |
| 21 | "add a task water the plants" | Works in follow-up without re-triggering |
| 22 | "done" or "stop" | Exits ability cleanly |

## How It Works

### Architecture

```
Voice trigger → run() → load prefs → check OAuth
  → If no refresh_token → handle_oauth_setup() (device flow → OAuth Playground fallback)
  → If connected → _ensure_valid_token() (auto-refresh)
  → Classify intent via LLM → Route to handler
  → Execute handler → Speak result
  → Follow-up loop ("Anything else?")
  → User says "done" → resume_normal_flow()
```

### Key Technical Details

- **Token refresh**: Automatic before every API call. If token has <60s left, it refreshes. On 401, it retries once.
- **Fuzzy matching**: 3 layers — substring match → `difflib.SequenceMatcher` → LLM fallback. Handles "dentist" matching "call the dentist".
- **Date parsing**: LLM converts natural language ("by Friday", "next Tuesday") to RFC 3339 dates with timezone awareness.
- **Task caching**: After listing tasks, results are cached so "mark the first one done" works without re-fetching.
- **Timezone**: Auto-detected from IP on first run, stored in prefs.
- **Persistence**: All prefs stored via `capability_worker.write_file()` — no raw `open()` calls.

## Important Notes

- **Testing mode**: If your Google Cloud app is in "Testing" status, refresh tokens expire after 7 days. You'll need to re-authorize. To avoid this, publish your app (requires Google review).
- **Date only**: Google Tasks only stores dates, not times. "By 3pm Friday" → saved as "Friday".
- **No server-side search**: Google Tasks API has no search endpoint. The ability fetches tasks and matches locally using fuzzy matching.
- **Rate limits**: Google Tasks API allows 50,000 requests/day per project.

## API Reference

- [Google Tasks API v1](https://developers.google.com/tasks/reference/rest)
- [OAuth 2.0 for Google APIs](https://developers.google.com/identity/protocols/oauth2)

## Trigger Words

task, tasks, to do, todo, add a task, new task, remind me, my tasks, what's due, task list, mark done, complete task, check off, task summary, daily tasks, overdue, switch list, google tasks, what do I need to do, finish task
