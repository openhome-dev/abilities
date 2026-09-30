# Slack Voice Operator

A voice-first Slack companion for OpenHome. Read and summarise channel activity, catch @mentions, and send messages — all hands-free, with LLM-powered summaries instead of raw message dumps.

## What makes it different from Alexa

| Feature | Alexa Slack Skill | Slack Voice Operator |
|---------|------------------|---------------------|
| Message reading | Reads messages verbatim | LLM condenses to 2–3 sentence summary |
| @mention alerts | Reads all messages | Proactive interrupt only for @mentions, urgency-scored |
| Recipient lookup | Exact handle required | Natural name ("message Jake") fuzzy-matched |
| Channel resolution | Exact channel name | "my product channel" → LLM-matched |
| Background monitoring | None | Daemon polls every 10 min, interrupts only on new mentions |

## Setup

### 1. Link Your Slack Account

1. Go to [OpenHome Dashboard → Settings](https://app.openhome.com/dashboard/settings)
2. Link your Slack account

That's it. No bot app to create, no scopes to configure, no token to copy. The platform handles OAuth and provides the token to the ability at runtime.

### 2. First Voice Run

Say any trigger phrase — the ability connects automatically, confirms the workspace name, and asks which channels to watch for background mention alerts.

## Trigger Phrases

- `check my Slack` / `any Slack messages`
- `any mentions` / `did anyone ping me`
- `what's new in Slack` / `what did I miss on Slack`
- `summarize #engineering` / `what happened in product`
- `message Jake on Slack: I'll be 5 minutes late`
- `send a Slack message to #general`
- `list my Slack channels`
- `change my Slack settings`

## Example Conversations

**Checking mentions:**
> "Any mentions?"
> → "You have 2 mentions in the last 24 hours. Alex pinged you in #engineering asking for a review on PR 47. Sara asked in #product when the design spec will be ready."

**Channel summary:**
> "What's happening in engineering?"
> → "Here's what's happening in #engineering: The team decided to delay the v2 release by one sprint. There's a blocker on the auth service — Ben is investigating. Three PRs are waiting for review."

**Sending a message:**
> "Message Jake: I'll be a few minutes late to standup."
> → "Sending to Jake Smith: 'I'll be a few minutes late to standup' — shall I send it?"
> "Yes."
> → "Sent."

**Background interrupt (no trigger needed):**
> "Heads up — you have 1 urgent Slack mention in #engineering. Say 'check my Slack' for details."

## Storage

All data is persisted in context storage under key `slack_voice_operator`:
- `slack_user_id` — your Slack User ID (resolved by display name on first run)
- `watch_channels` — channel IDs monitored by the background daemon
- `channel_cache` — list of all channels the bot has access to
- `user_cache` — workspace member list for name resolution
- `last_mention_ts` — timestamp of the last processed @mention

## How this differs from the Slack Assistant template

OpenHome ships a basic `slack-assistant` template. Slack Voice Operator goes further in three ways:

| Capability | Slack Assistant template | Slack Voice Operator |
|---|---|---|
| Session type | Single-intent, one-shot | Multi-intent conversation loop |
| Background monitoring | None | Daemon polls every 10 min, urgency-scored |
| API pagination | No (first page only) | Full cursor-based pagination for channels, users, history |
| LLM summaries | No | All responses condensed by LLM before speaking |
| Name resolution | Exact handle required | Fuzzy-matched against full member list |

## Notes

- The background daemon polls every 10 minutes. It only interrupts for @mentions, never for general channel activity.
- Channel and user lists are fully paginated — works with large workspaces.
- Channels are fetched from your linked account — you'll only see channels you're already a member of.
