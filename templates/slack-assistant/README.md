# Slack Assistant Template — OpenHome Ability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)

## What This Is
**This is a template ability** that turns your OpenHome agent into a hands-free Slack assistant. It connects to your Slack workspace and lets you list channels, send messages, read recent messages, browse direct messages, and search for people — all by voice.

It uses your linked Slack account via `CapabilityWorker.get_slack_key()` and the official `slack_sdk` `WebClient`, so there's no token to hardcode. The template runs a continuous menu loop and uses the LLM both to route your intent and to intelligently match the channel you name.

## Why Build This as an Ability
Every OpenHome agent can talk about Slack, **but it can't act on your workspace on its own.** This template shows you how to:
- **Actually send Slack messages** — not just draft them in conversation
- **Read what's happening** — recent messages and channel activity, spoken aloud
- **Resolve fuzzy voice input** — "the new channel" → `#new-channel` via fuzzy + LLM matching
- **Run a multi-turn assistant** — a menu loop that stays open until you say exit

## What You Can Build
Examples of abilities you could create with this template:
- **Voice Slack control** — send and read messages without touching a keyboard
- **Standup / status poster** — speak an update and post it to a channel
- **Channel briefing** — read the latest messages from a channel out loud
- **Team directory** — search for a person and pull up their handle
- **Notification relay** — post alerts to Slack from other abilities

## Setup Requirements

### 1. Link Your Slack Account
This template does **not** use a hardcoded token. It reads your linked Slack credentials at runtime:
```python
slack_token = self.capability_worker.get_slack_key()
```
Before using the ability, link Slack to OpenHome:
1. Go to [OpenHome Dashboard → Settings](https://app.openhome.com/dashboard/settings)
2. Link your Slack account
3. If it isn't linked, the ability will tell you and exit gracefully

### 2. Slack Scopes
Your linked Slack app needs scopes for the actions you use, including reading channel/conversation lists, posting messages, reading channel history, and listing users. The template calls:
- `auth_test` — identify the connected user/workspace
- `conversations_list` — list public/private channels and DMs
- `chat_postMessage` — send a message
- `conversations_history` — read recent messages
- `users_info` / `users_list` — resolve and search users

### 3. Dependencies
- `slack_sdk` (`WebClient`, `SlackApiError`)
- `difflib` (standard library) for fuzzy channel matching

## Template Trigger Words
This template uses generic Slack triggers — **customize these** for your ability:
- "open Slack" / "Slack assistant" / "check Slack"
- Configure your own trigger words in the OpenHome dashboard.

Inside the assistant you then speak natural commands: "list channels", "send a message", "read messages", "search users", or "exit".

## Using This Template

### 1. Get the Template
Add the Slack template to your agent from:
- OpenHome Dashboard abilities library, OR
- [GitHub Repository](https://github.com/OpenHome-dev/abilities)

### 2. Customize for Your Use Case
- Set your trigger words in the dashboard.
- Trim or extend the actions in `main_menu_loop()`.
- Adjust the channel-matching threshold or the message read limit.

## How the Template Works

### Template Flow
1. `initialize_slack()` reads your linked token, creates the `WebClient`, and confirms the workspace
2. The assistant speaks an intro and enters `main_menu_loop()`
3. Each turn, the LLM classifies your request into one action (list channels, list DMs, send, read, search, help)
4. Send/read flows confirm the channel and (for sends) the message before acting
5. The loop continues until you say an exit phrase ("exit", "quit", "bye", "stop", "done", "leave")
6. `resume_normal_flow()` returns control to the Agent

### Key Components

**1. Connecting With a Linked Token:**
```python
slack_token = self.capability_worker.get_slack_key()
if not slack_token:
    await self.capability_worker.speak("Your Slack account is not linked with Openhome. ...")
    return False
self.slack_client = WebClient(token=slack_token)
response = self.slack_client.auth_test()
```

**2. Intelligent Channel Matching:**
The template resolves spoken channel names in layers so casual phrasing still works:
1. `normalize_channel_name()` — lowercases and strips "#", "the", "channel", spaces → hyphens
2. `fuzzy_match_channel()` — exact, substring, then `SequenceMatcher` similarity (60% threshold)
3. `smart_channel_search()` — falls back to the LLM when fuzzy matching fails
```python
channel = await self.get_channel_intelligently(channel_input)
```
Channels are cached after the first lookup (`cached_channels`) to avoid repeat API calls.

**3. Confirm Before Acting:**
```python
confirm = await self.capability_worker.run_confirmation_loop(
    f"You want to send: {message_text}, to {readable_name}. Should I send it?"
)
if confirm:
    await self.send_message_to_channel(channel['id'], message_text)
```
Both the matched channel and the message are confirmed before anything is posted.

**4. Voice-Friendly Output:**
Channel names are spoken with hyphens/underscores converted to spaces, and reads are capped (first 10 channels, ~3 messages) so the assistant stays concise.

## Template Usage Examples

> **User:** *(trigger)* → **AI:** "Connected to Slack workspace: Acme. Hi! I'm your Slack assistant…"
>
> **User:** "list channels" → **AI:** "Here are your channels: general, engineering, random…"
>
> **User:** "send a message" → **AI:** "Which channel?" → **User:** "the new channel" → **AI:** "I found the channel new channel. Is this correct?" → … → "Message sent successfully!"
>
> **User:** "read messages from engineering" → **AI:** "Recent messages: Alex said: deploy is green…"
>
> **User:** "exit" → **AI:** "Goodbye! Come back anytime you need help with Slack."

## Customizing the Template

### 1. Add or Remove Actions
Edit `main_menu_loop()` and the `intent_prompt` to add actions (e.g. pin a message, create a channel) or remove ones you don't need.

### 2. Tune Channel Matching
Change the `0.6` similarity threshold in `fuzzy_match_channel()`, or adjust the `conversations_list` `limit`.

### 3. Adjust Read Volume
`read_recent_messages()` fetches `limit=5` and speaks the first 3 — change these for more or less context.

## Best Practices
- **Never hardcode a Slack token** — always use `get_slack_key()` and handle the unlinked case.
- **Confirm before sending** — keep `run_confirmation_loop()` for any write action.
- **Log API failures** with `logging.error` / `editor_logging_handler` and speak a clear recovery message.
- **Always call `resume_normal_flow()`** when the assistant exits.

## Troubleshooting

### "Your Slack account is not linked"
Link Slack at [Dashboard → Settings](https://app.openhome.com/dashboard/settings).

### "I couldn't find a channel matching …"
The bot only sees channels it is a member of (`is_member`). Invite the bot/user to the channel, or say "list channels" to hear available ones.

### Message Send Fails
Check for `channel_not_found` or `not_in_channel` in the logs — the connected account must be a member of the target channel.

## Links & Resources
- [Dashboard](https://app.openhome.com/dashboard)
- [Abilities Library](https://app.openhome.com/dashboard/abilities)
- [Developer Docs](https://docs.openhome.com)
- [Slack API Docs](https://api.slack.com/)

## Final Reminder
⚠️ **This template is a starting point, not a finished product.** Customize the actions, channel matching, and confirmations for your specific use case.
