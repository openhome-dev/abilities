# Hermes Connector

This ability sends your question to your own **Hermes** AI agent. Hermes can answer questions, help with tasks, and remember things for you. Your OpenHome device speaks back the answer.

[Hermes](https://github.com/NousResearch/hermes-agent) is a free, open-source AI agent you run yourself on your own computer.

## What You Need

Before you start, get these three things ready:

1. A computer running Hermes.
2. Hermes's "API server" turned on. This lets other apps, like this ability, talk to Hermes.
3. A public web address for your Hermes computer, plus a secret password. Steps below show you how to make both.

## Setup Steps

### Step 1: Turn on Hermes's API server

On the computer running Hermes, open the file `~/.hermes/.env`. Add these two lines:

```
API_SERVER_ENABLED=true
API_SERVER_KEY=your-own-secret-password-here
```

For `API_SERVER_KEY`, use a long, random password. Do not use a simple word like "password123". This password protects your Hermes agent — anyone who has it can send it commands.

Restart Hermes so the change takes effect:

```
hermes gateway restart
```

### Step 2: Give your Hermes computer a public web address

Your Hermes computer is normally private — nothing outside your home network can reach it. A **tunnel** gives it a public web address safely. Pick one option:

**Option A: Tailscale Funnel** (free, needs a [Tailscale](https://tailscale.com) account)

```
tailscale funnel --bg 8642
```

This prints a web address like `https://your-computer-name.ts.net`. Copy it — you will need it in Step 3.

**Option B: Cloudflare Tunnel** (free, no account needed for quick testing)

```
cloudflared tunnel --url http://localhost:8642
```

This prints a web address like `https://random-words.trycloudflare.com`. Copy it.

> Both options are free. Tailscale Funnel gives you an address that stays the same each time. Cloudflare's free tunnel gives you a new address every time you start it — fine for testing, not for daily use.

### Step 3: Add this ability's secrets in OpenHome

1. Open the OpenHome dashboard.
2. Go to **Abilities** and open **Hermes Connector**.
3. Find the **API Keys** section.
4. Add two keys:
   - `hermes_api_url` — paste the web address from Step 2. (Example: `https://your-computer-name.ts.net` — no extra text, just the address.)
   - `hermes_api_key` — paste the password you made in Step 1.
5. Save your changes.
6. Assign this ability to your agent.

### Step 4: Talk to Hermes

Say one of these to your OpenHome device:

- "Talk to Hermes"
- "Hermes agent"
- "Ask my agent"
- "Call Hermes"

Then ask your question. Your device sends it to Hermes and speaks back the answer.

## Keep Your Password Safe

Your `hermes_api_key` works like a key to your computer — whoever has it can send commands to your Hermes agent. Do not share it. Do not post it online, in chat, or in a screenshot. If you think someone else got it, make a new password in Step 1 and update it in Step 3.

## Trigger Words

- "talk to hermes"
- "hermes agent"
- "relay to hermes"
- "hermes relay"
- "forward to hermes"
- "my agent"
- "call hermes"
- "ask my agent"
- "tell my agent"

## How It Works

1. You say a trigger word, like "Hermes agent," followed by your question.
2. This ability reads your question.
3. It sends your question to your Hermes agent over the internet, using the web address and password you set up.
4. Hermes agent thinks about your question and sends back an answer.
5. Your OpenHome device speaks the answer out loud.

## Key SDK Functions Used

- `get_api_keys()` — reads the `hermes_api_url` and `hermes_api_key` secrets you set up.
- `speak()` — talks back to you.
- `wait_for_complete_transcription()` — waits for you to finish talking.
- `editor_logging_handler.error()` — writes errors to the log if something goes wrong, without using `print()`.
- `resume_normal_flow()` — hands control back to your agent when this ability finishes.
