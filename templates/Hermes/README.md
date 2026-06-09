# Hermes Template — Voice-Controlled AI Automations

## What This Is

**This is a template ability** that connects OpenHome to [Hermes Agent](https://github.com/NousResearch/hermes-agent) — an open-source AI automation framework that runs on your own machine.

Use your voice to run one-shot AI tasks, create scheduled automations, set up webhook triggers, and manage your entire automation stack — all without touching a terminal.

## What You Can Build

- **Research assistant** — "research AI news and send to Telegram"
- **Daily digest** — "create a morning briefing every day at 9"
- **GitHub automation** — "review every new PR and post a comment"
- **System monitor** — "alert me on Discord if disk space drops below 10%"
- **Custom workflows** — any repeating task you want AI to handle

## How It Differs from OpenClaw

| | OpenClaw | Hermes |
|---|---|---|
| Runs | Arbitrary terminal commands | AI-powered tasks and automations |
| LLM API needed | Yes (in OpenClaw daemon) | Yes (in Hermes) |
| Scheduling | No | Yes — cron + human-readable intervals |
| Webhooks | No | Yes — GitHub, HTTP, any event |
| Delivery | Terminal output | Telegram, Discord, Slack, email, GitHub |
| Model choice | OpenClaw's model | Any — Claude, GPT, DeepSeek, local |

## Requirements

### 1. Hermes Agent

```bash
pip install hermes-agent
hermes setup
```

Follow the setup to add your LLM API key (supports Claude, OpenAI, DeepSeek, and more).

### 2. Local Connect Client

Hermes commands run via `exec_local_command()` — you need either:

- **[Local Connect client](https://drive.google.com/file/d/12Is4eXchH5dDjlG39Knp4oRuD-V3D-v_/view?usp=drive_link)** (simpler, Python only)
- **[OpenClaw client](https://drive.google.com/drive/folders/10qK75I-bFB2D98YJ6dH3tQFsvEk44Y7-)** (full-featured, desktop app)

Both bridge OpenHome voice → your local machine.

### 3. Verify Hermes is in PATH

```bash
hermes --version
hermes status
```

## Trigger Words (Customize These)

Set your own in the OpenHome Live Editor or when creating the ability:

```
"hermes", "run automation", "create automation",
"hey hermes", "automate", "schedule a task"
```

## Example Voice Commands

**One-shot tasks:**
> "Research today's top AI stories and send to Telegram"
> "Summarize my GitHub notifications"
> "Find the top 5 trending repos this week"

**Create automations:**
> "Create a daily digest every morning at 9"
> "Set up a weekly report every Monday"
> "Check Hacker News hourly and send highlights"

**Manage automations:**
> "What automations are running"
> "Run my morning digest now"
> "Pause the email checker"
> "Delete the weekly report"

**Status:**
> "Check Hermes status"
> "List my webhooks"

## Customizing the Template

### Change the default delivery target

In `main.py`, update `SYSTEM_PROMPT` to default to your preferred delivery:

```python
# Change "telegram" to "discord", "slack", "email", etc.
"- Use --deliver discord by default unless user specifies otherwise"
```

### Add domain-specific commands

Extend `SYSTEM_PROMPT` with your own examples:

```python
SYSTEM_PROMPT = """
...existing prompt...

MY CUSTOM EXAMPLES:
User: "check the deploy" -> hermes run "Check if the latest deploy at myapp.com succeeded. Look for errors in the last 10 minutes." --deliver telegram
User: "morning standup" -> hermes cron trigger morning-standup
"""
```

### Multi-step confirmation

```python
async def first_function(self):
    user_inquiry = await self.capability_worker.wait_for_complete_transcription()

    hermes_command = self.capability_worker.text_to_text_response(
        user_inquiry, [], SYSTEM_PROMPT
    ).strip()

    # Confirm before creating automations
    if "cron create" in hermes_command:
        await self.capability_worker.speak(f"I'll create that automation. Confirm?")
        confirmation = await self.capability_worker.user_response()
        if "yes" not in confirmation.lower():
            await self.capability_worker.speak("Cancelled.")
            self.capability_worker.resume_normal_flow()
            return

    # ... rest of flow
```

## How It Works

```
Voice input
    ↓
OpenHome captures transcription
    ↓
LLM converts to hermes CLI command
    ↓
exec_local_command() sends to local client
    ↓
Local client runs: hermes run / hermes cron create / etc.
    ↓
Hermes executes AI task on your machine
    ↓
Raw output returned
    ↓
LLM formats into spoken response (2 sentences max)
    ↓
OpenHome speaks result
```

## Links

- **Hermes Agent:** [github.com/NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- **Hermes Docs:** [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com)
- **Local Connect client:** [Download](https://drive.google.com/file/d/12Is4eXchH5dDjlG39Knp4oRuD-V3D-v_/view?usp=drive_link)
- **OpenClaw client:** [Download](https://drive.google.com/drive/folders/10qK75I-bFB2D98YJ6dH3tQFsvEk44Y7-)
- **OpenHome Dashboard:** [app.openhome.com](https://app.openhome.com)
