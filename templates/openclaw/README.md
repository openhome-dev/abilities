# OpenClaw — Voice-Controlled Computer Automation Template

![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)
![Category](https://img.shields.io/badge/Category-Local-green?style=flat-square)

Drive your computer by voice through **OpenClaw** — a local AI agent for desktop
automation (app control, file workflows, system actions). You speak a natural-language
task, it runs on your machine through the **OpenHome CLI's Local Link bridge**, and the
result is spoken back.

---

## ⚠️ Deprecation Notice

The old setup for this template — **downloading the "OpenClaw client" from Google Drive
and connecting it manually** — is **deprecated. Do not use it.**

OpenHome now reaches OpenClaw through the **OpenHome CLI** (`openhome local`), which
ships in this repository and has a built-in **`openclaw` handler** that detects and
drives your local OpenClaw gateway. There is no separate client to download. If you
have an old OpenClaw client running, stop it and follow the setup below.

---

## How It Works

```
You speak  ->  OpenHome (cloud)  ->  Local Link bridge (openhome CLI)  ->  OpenClaw gateway  ->  your computer
                              spoken reply travels back along the same path
```

OpenHome runs in the cloud and cannot reach your computer directly. The **Local Link
bridge** (`openhome local`) runs on your machine and routes each request to a local
handler. Its built-in **`openclaw`** handler detects your running OpenClaw gateway and
forwards tasks to it. This ability sends its request to that handler and speaks the
reply.

---

## Setup

### 1. Install and configure OpenClaw

```bash
npm install -g openclaw@latest
openclaw onboard --install-daemon      # configure OpenClaw + add your LLM API key
openclaw gateway start                 # start the gateway the bridge connects to
openclaw gateway status                # confirm it is running
```

OpenClaw needs its own LLM API key (OpenAI, Anthropic, etc.), added during `onboard`.

### 2. Install the OpenHome CLI and log in

From the root of this repository (Python 3.10+):

```bash
python3 -m venv cli/.venv && source cli/.venv/bin/activate
pip install -e cli
openhome login          # paste your API key from Dashboard -> Settings -> API Keys
```

Full CLI reference: [`cli/README.md`](../../cli/README.md) ·
Official guide: <https://docs.openhome.com/guides/getting-started/cli>

### 3. Start the Local Link bridge

Run this on the same computer where OpenClaw is installed, and keep it running:

```bash
openhome local start     # start the bridge in the background
openhome local status    # confirm it is running
openhome local logs      # watch requests and replies live (Ctrl-C to stop)
```

When the OpenClaw gateway is up, the bridge detects `openclaw` as a ready handler.
You can confirm this in `openhome local logs` — a discovery line lists the available
handlers. If OpenClaw is installed but the gateway is off, the log shows a hint to run
`openclaw gateway start`.

### 4. Route the ability to the OpenClaw handler

**Important:** the Local Link bridge runs plain requests on the raw-shell `local-link`
handler by default. To reach the **`openclaw`** handler, the ability must send its
request with `target: "openclaw"`:

```python
import json

payload = {"type": "command", "target": "openclaw", "data": user_inquiry}
response = await self.capability_worker.exec_local_command(json.dumps(payload))
# response -> {"status": "ok", "data": "<reply>", "target": "openclaw"}
await self.capability_worker.speak(response["data"])
```

Set the target once in `main.py` and every request in the ability goes to OpenClaw.

### 5. Add the ability

Add the **OpenClaw** template to your Agent from the Dashboard, set your **Trigger
Words** (for example `open`, `run on my computer`), and test in the Live Editor.

---

## What You Can Build

- An application launcher and manager
- A "start my workday" routine (open apps, tabs, tools)
- File and folder automation
- A development-environment controller
- Screenshot and screen-recording tools

---

## Core Function: `exec_local_command()`

```python
async def exec_local_command(
    self,
    command: str | dict,
    target_id: str | None = None,   # device id (default: "laptop")
    timeout: float = 10.0,          # seconds to wait
)
```

`command` carries the Local Link protocol. To target the OpenClaw handler, pass the
JSON shown in step 4. Raise `timeout` for long automations:

```python
payload = {"type": "command", "target": "openclaw", "data": "compile the project", "timeout": 60}
response = await self.capability_worker.exec_local_command(json.dumps(payload), timeout=75.0)
```

---

## Customizing and Safety

- **Confirm destructive tasks** (restart, delete, shutdown) before sending them:

  ```python
  if any(word in user_inquiry.lower() for word in ("restart", "shutdown", "delete")):
      await self.capability_worker.speak("That changes your system. Confirm?")
      if "yes" not in (await self.capability_worker.user_response() or "").lower():
          await self.capability_worker.speak("Cancelled.")
          self.capability_worker.resume_normal_flow()
          return
  ```

- OpenClaw runs with **your user permissions**. Only trigger tasks you would run
  yourself, and keep your OpenHome API key private.
- Keep spoken replies short — one or two sentences — so the interaction feels responsive.

---

## Troubleshooting

- **`openclaw` not detected:** the gateway isn't running. Run `openclaw gateway start`,
  then `openclaw gateway status`, and restart the bridge with
  `openhome local stop && openhome local start`.
- **"Local Link isn't connected":** the bridge isn't running (`openhome local start`),
  or you're logged out (`openhome login`).
- **Tasks time out:** raise the timeout in the payload, and watch `openhome local logs`.

---

## `openclaw` vs `local-link`

Both run through the same `openhome local` bridge, as two handlers:

| Handler | What it does | Needs |
|---|---|---|
| **`openclaw`** (this template) | Natural-language desktop automation via OpenClaw | OpenClaw installed + gateway running |
| **`local-link`** | Runs a single shell command directly | Nothing — always available with the bridge |

Use **`openclaw`** for LLM-driven automation. For direct terminal commands, see the
[`openhome-local-link`](../openhome-local-link) template.

---

## Links

- [OpenHome CLI reference](../../cli/README.md)
- [Official CLI guide](https://docs.openhome.com/guides/getting-started/cli)
- [Dashboard](https://app.openhome.com/dashboard) · [API Keys](https://app.openhome.com/dashboard/settings)

> This template is a starting point. Set the OpenClaw target, add safety checks, and
> customize the logic before relying on it.
