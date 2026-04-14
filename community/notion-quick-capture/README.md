# Notion Quick Capture

Turn OpenHome into a voice inbox for your Notion workspace. Capture tasks, notes, search pages, read content, and query databases — all by voice.

## What It Does

| Mode | You Say | What Happens |
|------|---------|-------------|
| **Quick Add** | "Add to my tasks: review the PR by Friday" | Creates a page in your Tasks database with title + due date |
| **Quick Note** | "Add a note: the client wants blue, not green" | Saves a note under your Voice Notes page |
| **Search** | "Find my notes about marketing" | Searches page titles, speaks matching results |
| **Read Page** | "Read me the onboarding doc" | Fetches page content, speaks an LLM summary |
| **Query Database** | "What tasks are due this week?" | Queries your database with filters, speaks results |

## Setup

### 1. Create a Notion Integration

1. Go to [notion.so/profile/integrations](https://www.notion.so/profile/integrations)
2. Click **New integration**
3. Name it **OpenHome**
4. Select your workspace
5. Under Capabilities, enable: **Read content**, **Update content**, **Insert content**
6. Click Submit, then copy the **Internal Integration Token** (starts with `ntn_`)

### 2. Share Pages and Databases

**This is the step people forget.** The integration can only see pages and databases you explicitly share with it.

For each database or page you want to use:

1. Open it in Notion
2. Click the **···** menu (top right)
3. Select **Add connections**
4. Find and select **OpenHome**

At minimum, share:
- Your **Tasks** database (or whatever you use for to-dos)
- A **Voice Notes** page (create one if you don't have it — just a blank page where notes will be saved as sub-pages)

### 3. First Run

When you first say "Notion" to OpenHome, the ability walks you through setup:

1. It asks for your integration token — paste it when prompted
2. It guides you to share your databases
3. It discovers shared databases and assigns nicknames automatically
4. It asks for your notes page name

After setup, you're ready to go. Preferences are saved across sessions.

### Alternative: Pre-set Token

If you prefer, you can set the token directly in `main.py` before uploading:

```python
NOTION_INTEGRATION_TOKEN = "ntn_your_token_here"
```

The ability will use this token and skip the token entry step during setup.

## Trigger Words

- "notion"
- "add to my tasks"
- "new task"
- "add a note"
- "add to notion"
- "notion note"
- "search notion"
- "find in notion"
- "read from notion"
- "notion tasks"
- "what tasks"
- "capture to notion"

## Example Conversations

**Quick Add:**
> "Add to my tasks: review the PR by Friday"
> → "Added 'Review the PR' to your tasks, due 2026-03-06."

**Quick Note:**
> "Add a note: onboarding should start with a video, not a form"
> → "Noted — saved 'Onboarding flow improvement' to your notes."

**Search:**
> "Search Notion for marketing plan"
> → "I found 2 pages matching 'marketing plan': Marketing Plan Q1, Marketing Strategy. Want me to read any of these?"

**Read Page:**
> "Read me the project brief"
> → Speaks a 3-5 sentence summary of the page content.

**Query Database:**
> "What tasks are due this week?"
> → "You have 4 tasks due this week. Review the PR is due Friday..."

## How It Works

- **LLM as intent router**: Voice input is classified into one of five modes using the LLM, with heuristic fallback
- **Schema-aware property parsing**: Database schemas are fetched and cached (30-min TTL). The LLM maps natural language to actual database properties
- **Relative date resolution**: "by Friday", "tomorrow", "next week" are resolved to ISO dates using the current date
- **Title-only search**: Notion's search API matches page/database titles, not page body content

## Limitations (V1)

- Cannot update existing page properties (no "mark as done")
- Cannot append to existing pages
- Cannot search inside page content (title-only search)
- Single workspace only
- Max 3 configured databases
- Max 8 items spoken in query results

## APIs Used

- Notion API (`https://api.notion.com/v1`)
  - `POST /search` — Find pages and databases
  - `POST /pages` — Create pages
  - `GET /databases/{id}` — Fetch database schema
  - `POST /databases/{id}/query` — Query with filters
  - `GET /blocks/{id}/children` — Read page content
  - `GET /users/me` — Validate token
