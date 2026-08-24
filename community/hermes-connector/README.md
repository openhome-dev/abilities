# Hermes Connector

This ability sends your question to your own **Hermes** AI agent. Hermes can answer questions, help with tasks, and remember things for you. Your OpenHome device speaks back the answer.

[Hermes](https://github.com/NousResearch/hermes-agent) is a free, open-source AI agent you run yourself on your own computer.

This ability uses **Local Link** — a small bridge program that runs on your computer. Nothing is made public on the internet. No tunnel. No API key to paste anywhere.

## What You Need

1. Hermes installed and set up on your computer. Run `hermes setup` once if you have not already.
2. The OpenHome CLI installed on the same computer.
3. Local Link running (`openhome local start`).

## Setup Steps

### Step 1: Make sure Hermes works

In a terminal, run:

```bash
hermes dump
```

If this shows version information, Hermes is ready. If not, run `hermes setup` first.

### Step 2: Install the OpenHome CLI

From the root of the [abilities repo](https://github.com/openhome-dev/abilities):

```bash
python3 -m venv cli/.venv && source cli/.venv/bin/activate
pip install -e cli
```

### Step 3: Log in and start Local Link

```bash
openhome login
openhome local start
openhome local status
```

Keep Local Link running. It needs to stay on while you use this ability.

### Step 4: Add this ability

1. Open the OpenHome dashboard.
2. Add the **Hermes Connector** ability to your agent.
3. Set your trigger words if you want to change them (see below for the defaults).

No API keys. No secrets to set up. Local Link finds Hermes automatically.

### Step 5: Talk to Hermes

Say one of these to your OpenHome device:

- "Talk to Hermes"
- "Hermes agent"
- "Ask my agent"
- "Call Hermes"

Then ask your question. Your device sends it to Hermes through Local Link and speaks back the answer.

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
3. It sends your question to Local Link, the bridge program running on your computer.
4. Local Link runs `hermes -z "<your question>"` on your machine — a one-shot call to your own Hermes agent. This never leaves your computer.
5. Hermes thinks about your question and sends back an answer.
6. Your OpenHome device speaks the answer out loud.

## Troubleshooting

- **"Could not reach Hermes"**: check that `openhome local start` is running (`openhome local status`), and that `hermes dump` works in a terminal.
- **Nothing happens**: confirm this ability is added to your agent and its trigger words are set.

## Key SDK Functions Used

- `exec_local_command()` — sends the request to Local Link, targeting the built-in `hermes` backend.
- `speak()` — talks back to you.
- `wait_for_complete_transcription()` — waits for you to finish talking.
- `editor_logging_handler.error()` — writes errors to the log if something goes wrong, without using `print()`.
- `resume_normal_flow()` — hands control back to your agent when this ability finishes.
