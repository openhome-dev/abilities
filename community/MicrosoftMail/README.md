# Microsoft 365 Email Management

Voice-only assistant for managing your Outlook / Microsoft 365 inbox. One script, one class (`OutlookConnectorCapability`), using the Microsoft Graph API.

---

## What It Does

- **Summarize** — "What's in my inbox?" → short spoken summary of unread emails; optional "go through them" triage.
- **Read** — "What did Sarah say?" → match by sender/subject, read back that email (HTML stripped, voice-friendly).
- **Reply** — Reply to the current email; LLM drafts from your words; always confirm before sending.
- **Compose** — "Send an email to Mike" or "Write a quick email"; collects recipient (resolves names from recent emails or asks for address), subject, body; confirms before send. Cancellable at any step.
- **Search** — "Find the email about the budget" / "Did Sarah email me this week?" → Graph `$search` / `$filter`; offers to read the most recent.
- **Mark read** — "Mark it as read" for the current email.
- **Archive** — "Archive that" → move to Outlook Archive folder (mark read before move).
- **Triage** — "Go through my inbox" → one-by-one: short summary per email, then "Reply, skip, mark as read, or archive?"

**Two modes**

- **Quick** — Single question (e.g. "Did Sarah email me?", "Send Ryan a quick email"); answer then brief follow-up window and exit.
- **Full** — "Check my email" / "Triage my inbox"; summary or triage, then an open session loop until the user exits or goes idle.

All send/reply actions read back the draft and require confirmation before sending. Recipient names are resolved to email addresses from recent inbox traffic when possible; otherwise the user is asked for the address.

---

## Setup

You need **CLIENT_ID** and **REFRESH_TOKEN** for this to work. Set them at the top of `main.py` (or via env). For how to get and configure your token, see the **refresh_token README**.

---

## Variables and limits

Defined at the top of `main.py`; you can change them to tune behaviour.

| Variable | Default | Meaning |
|----------|---------|---------|
| `CLIENT_ID` | (set by you) | Azure AD app ID. Required for Graph API. |
| `REFRESH_TOKEN` | (set by you) | OAuth2 refresh token for the user’s Outlook. Required. See refresh_token README. |
| `TENANT_ID` | `"consumers"` | Use `"consumers"` for personal Microsoft accounts; use your tenant ID for work/school. |
| `MAX_UNREAD_FETCH` | 15 | Max number of unread emails fetched from the inbox for summary, read, and triage. |
| `MAX_SUMMARY_INPUT` | 15 | Max number of emails sent to the LLM for the inbox summary. |
| `MAX_SEARCH_RESULTS` | 5 | Max number of emails returned from a search. |
| `MAX_TRIAGE_BATCH` | 10 | Max number of emails walked through in one triage session (“go through my inbox”). |
| `PREFS_FILE` | `outlook_connector_prefs.json` | Filename for persistent user preferences. |
| `CACHE_FILE` | `outlook_connector_cache.json` | Filename for session cache (e.g. fetched unread list). |

---

## Structure

- **Single class:** `OutlookConnectorCapability(MatchingCapability)` in `main.py`.
- **Entry:** `call(worker)` → `run()`: load prefs, fetch unread from Graph, get trigger context, classify intent (LLM) → quick or full mode.
- **Graph helpers:** `outlook_list_unread`, `outlook_get_message`, `outlook_send_reply`, `outlook_send_new`, `outlook_mark_read`, `outlook_archive`, `outlook_search*`, `outlook_get_archive_folder_id`, etc. All go through `graph_request()` with token refresh.
- **Voice:** Spoken text is kept short; emails are summarized or summarized then "read full?"; addresses spoken as "name at domain dot com"; HTML stripped from bodies before speaking.

---

## Errors

- API/connection failures → user hears: *"I'm having trouble connecting to Outlook right now. Try again in a minute."*
- 401 → *"I need you to reconnect your Outlook account."*
- 403 → permission message; 429 → rate limit message.
- Unresolved recipient name → *"I don't have an email address for [name]. What's their email?"*

---

## Reference

- [Microsoft Graph Mail API](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview)
- Developer brief: see the Outlook Connector Ability Developer Brief for full feature list, UX rules, and API details.
