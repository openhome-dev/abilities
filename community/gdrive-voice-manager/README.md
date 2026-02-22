# Google Drive Voice Manager — OpenHome Ability

---

## What This Ability Does

Google Drive Voice Manager lets users search, read, summarize, expand, and save documents in Google Drive using natural voice commands. It handles OAuth, token refresh, intent classification, routing, and Drive API interaction in a structured, fault-tolerant way.

---

## Supported Commands

- Search files by name
- Search inside document content
- Read and summarize a document (PDFs not supported)
- Expand (go deeper into) the current document
- List recently modified files
- Browse folder contents
- Set a default notes folder
- Save a quick note to Drive as a Google Doc

All search results are cached for follow-up selections like “the second one” or partial name matches.

---

## Design Principles

### Intent Detection + Central Routing

All user input flows through a single classifier (`classify_trigger_context`) that returns structured JSON.

{
  "mode": "...",
  "search_query": "...",
  "file_reference": "...",
  "folder_name": "...",
  "note_content": "...",
  "file_type": "doc|sheet|slides|pdf|any"
}

The dispatcher routes strictly based on `mode`. Handlers are isolated and deterministic.

### Deterministic Shortcuts

Before invoking the classifier:

- Ordinal / partial matches resolve from `recent_results`
- “Go deeper” shortcuts expand the active document
- Exit words immediately terminate

This reduces unnecessary LLM calls and keeps behavior predictable.

### Single Drive API Wrapper

All Google requests go through `drive_request()`:

- Token refresh before every call
- Retry-on-401 once
- Scope-based invalidation on 403
- `timeout=10` enforced
- `fields` parameter always used
- `trashed=false` always included

No handler talks directly to `requests`.

### Persistence Model

- Stored in `gdrive_manager_prefs.json`
- Delete-then-write pattern
- `_session_` keys never persisted
- Refresh + access tokens stored locally

---

## Google Drive OAuth Setup

Before the Google Drive Voice Manager can access a user’s Drive, it must be authorized via OAuth 2.0 using a Google Cloud project.

This ability uses the Google Drive API with offline access (refresh tokens enabled).

---

## Overview

The OAuth flow:

1. User creates OAuth credentials in Google Cloud Console.
2. User pastes Client ID and Client Secret into the assistant.
3. Assistant generates a consent URL.
4. User authorizes access in browser.
5. Assistant exchanges authorization code for:
   - access_token
   - refresh_token
6. Tokens are stored in `gdrive_manager_prefs.json`.
7. All future API calls automatically refresh tokens when needed.

Scope used:

https://www.googleapis.com/auth/drive

This grants full Drive access for search, read, and document creation.

---

## Step-by-Step: Create OAuth Credentials

### 1️⃣ Create or Select a Google Cloud Project

Go to:

https://console.cloud.google.com

Create a new project or select an existing one.

Note: creating a new project does **not** automatically switch to it in GCC.
If you're using a new project, make sure you click on your current project at the
top of the screen to open the project picker, then select the new project.

---

### 2️⃣ Enable the Google Drive API

Navigate (by clicking on the navigation menu on the left side of your screen) to:

APIs & Services → Library

Search for:

Google Drive API

Click **Enable**.

---

### 3️⃣ Configure OAuth Consent Screen

Navigate to:

APIs & Services → OAuth Consent Screen

- Choose **External**
- Fill in:
  - App name
  - User support email
- Save

Then:

- Go to **Audience** (on your left in the OAuth menu, below the button that opens the
general navigation menu)
- Click **Add Users**
- Add your Google account email as a test user

---

### 4️⃣ Create OAuth Client Credentials

Navigate to:

APIs & Services → Credentials

Click:

Create Credentials → OAuth client ID

Select:

Application Type: Desktop App

Create it.

Copy:

- Client ID
- Client Secret

You will paste these into the assistant during setup.

---

## Authorization Flow

Once credentials are provided:

1. The assistant generates a consent URL.
2. User opens the link and signs in.
3. After approval, Google redirects to:

http://localhost:1

This will fail — that is expected.

4. Copy the value after:

code=

Stop at the first `&`.

5. Paste that code back into the assistant.

---

## Token Exchange

The assistant exchanges the authorization code at:

https://oauth2.googleapis.com/token

It receives:

- access_token
- refresh_token
- expires_in

The refresh token is required for persistent access.

If Google does not return a refresh token, revoke app access in your Google account settings and retry.

---

## Token Storage

Tokens are stored in:

gdrive_manager_prefs.json

Stored fields:

- client_id
- client_secret
- refresh_token
- access_token
- token_expires_at
- user_email

Session-only fields (e.g., currently opened document) are never persisted.

---

## Automatic Token Refresh

Before every Drive API request:

- The assistant checks token_expires_at
- If expired (or within 60 seconds of expiry):
- It refreshes the access token automatically
- If refresh fails with `invalid_grant` or `invalid_client`:
- Stored tokens are invalidated
- User must re-run OAuth setup

---

## Error Handling

- Missing refresh token → OAuth setup required
- 401 Unauthorized → Refresh token + retry once
- 403 insufficient scopes → Tokens invalidated
- Expired token → Auto refresh
- Corrupt prefs file → File deleted + reset

---

## Security Notes

- OAuth is performed locally.
- Redirect URI used: http://localhost:1
- `access_type=offline` and `prompt=consent` ensure refresh token issuance.
- Credentials are stored locally via the SDK file system.
- No tokens are logged.

---

## Reconnecting Drive

If authorization expires or is revoked:

1. Tokens are invalidated.
2. On next run, OAuth setup automatically restarts.

No manual cleanup is required.

---

## Required Google APIs

Only one API must be enabled:

- Google Drive API

No Gmail or additional APIs are required.

---

## Minimal Required Scope

https://www.googleapis.com/auth/drive

This scope enables:

- File search
- Content export
- Folder browsing
- Document creation (Quick Save)

---

If setup completes successfully, the assistant confirms with:

> Connected! I can see your Drive.

You are now ready to search, read, and save files using voice.

---

## How to Extend It

### Add a New Mode

1. Update the classifier schema (`classify_trigger_context`)
2. Add mode handling in `dispatch()`
3. Implement `_run_<mode>()`
4. Ensure:
   - No raw `requests` calls (use `drive_request`)
   - No direct token logic
   - `resume_normal_flow()` is never called inside handlers
   - All Drive queries include `trashed=false`
   - `fields` parameter is minimal

### Add Deterministic Shortcuts

Add logic inside `_conversation_loop` before classification.
Keep shortcuts short and explicit — never ambiguous.

### Add Drive Queries

Always:

- Use MIME filtering when relevant
- Cap `pageSize`
- Use relative timestamps via `_format_relative_time`
- Cache `recent_results` if follow-up selection should work

---

## Suggested Trigger Words

Examples:

- “Drive”
- “Google Drive”
- “Check my Drive”
- “Search my Drive”
- “Open Drive”

Hotwords should clearly indicate Drive intent and avoid generic collisions.

Note: It is highly recommended that you change the default trigger words of the live web
search ability, otherwise you are likely to accidentally invoke it when directing
the assistant to navigate your drive.

---

## Troubleshooting

### “Authorization expired”

- Refresh token likely invalid
- Re-run OAuth setup
- If no refresh token returned, revoke the app in Google Account settings and retry

### "Something went wrong while searching your Drive."

Check your permissions in Google Cloud Console.

### “Couldn’t reach Google Drive”

- Network issue
- Expired token that failed refresh
- Invalid client credentials

### Search returns nothing

- Query may be content-based but classified as name search
- Try explicitly: “Search inside documents for …”

### PDF won’t read

PDF export is not supported for voice summarization.

### Folder ambiguity

If multiple folders match, clarify by saying the full name or “the first one.”

---

This ability is designed to be:

- Deterministic where possible
- LLM-driven at the intent layer and summarization layer
- Safe in token lifecycle management
- Easy to extend without breaking architecture