# Hermes Ability for OpenHome

Talk to your local **Hermes Agent** (Nous Research) through an OpenHome voice
device. Ask out loud; Hermes answers using its tools, memory, and skills, and
replies in natural spoken language.

```
You speak  ->  OpenHome (cloud)  ->  hermes_bridge.py (your PC)  ->  Hermes Agent
                  spoken reply travels back along the same path
```

OpenHome runs in the cloud and can't reach `localhost`, so a small **bridge**
runs on your PC. It holds a WebSocket to OpenHome, forwards each question to
Hermes, and returns the answer. It auto-detects how to reach Hermes and needs no
separate API server in the common case.

[![Download hermes_bridge.py](https://img.shields.io/badge/Download-hermes__bridge.py-2563EB?style=for-the-badge&logo=googledrive&logoColor=white)](https://drive.google.com/drive/folders/1n_T9wV5o9nig2Cvg4OpuU0s-DyaWKS4i)

---

## How it works

**The ability** (installed from the Marketplace) classifies your wake utterance.
If it already contains a question, the ability forwards it straight to Hermes;
otherwise it prompts you. It then loops, answering follow up questions without
needing the wake word again, until you say you're done (for example "stop",
"that's all", or "goodbye"). Hermes' raw output is rewritten into a short,
TTS friendly spoken reply.

**The bridge** picks a backend on startup. It uses **API mode** if a live
OpenAI compatible endpoint answers (a Hermes proxy, Open WebUI, or whatever you
set in `HERMES_API_URL`), and otherwise **CLI mode**, running
`hermes -z "<question>"` directly. CLI mode is the default for a standard local
Hermes setup and needs no proxy or login. The bridge warms Hermes up at startup
and falls back from API to CLI if an endpoint stops responding.

---

## Setup

**Prerequisites:** a working Hermes install (verify with `hermes -z "say hello"`),
Python 3.8 or newer, and `pip install websockets httpx`.

### Part 1: Run the bridge (your PC)

1. Download `hermes_bridge.py` (button above) onto the machine running Hermes.
2. Set your OpenHome API key (Dashboard, then Settings, then API Keys) **before**
   launching:
   ```bash
   export OPENHOME_API_KEY="oh_xxx..."
   ```
3. Run it, and keep the terminal open:
   ```bash
   python3 hermes_bridge.py
   ```
   You should see it select a backend, warm up, then print
   `Connected to OpenHome [backend=cli]`.

   To keep it running across sessions: on Linux or macOS use
   `nohup python3 hermes_bridge.py > ~/hermes_bridge.log 2>&1 &` (or `tmux`); on
   Windows use a minimized terminal or Task Scheduler.

### Part 2: Install the ability (OpenHome dashboard)

Open the Dashboard, go to the **Marketplace**, add the **Hermes** template, set
**Trigger Words** (for example `hermes` or `ask hermes`), and enable it on your
agent. You can edit it anytime in the **Live Editor**.

---

## Using it

> **"Hermes."** then *"Hermes here. What would you like to ask?"*
> **"What's my disk usage?"** then *"Your main drive is about 72 percent full,
> with roughly 64 gigabytes free."*
> **"That's all, thanks."** then *"Okay, leaving Hermes. Goodbye."*

Follow up questions don't need the wake word; the loop keeps listening until you
exit.

---

## Configuration

Environment variables (set before launching), or edit `Config` at the top of
`hermes_bridge.py`.

| Variable                  | Default            | Meaning                                          |
| ------------------------- | ------------------ | ------------------------------------------------ |
| `OPENHOME_API_KEY`        | *(required)*       | Your OpenHome API key.                           |
| `OPENHOME_HOST`           | `app.openhome.com` | OpenHome host.                                   |
| `OPENHOME_CLIENT_ID`      | `laptop`           | Device id; must match the ability's `target_id`. |
| `OPENHOME_ROLE`           | `agent`            | Connection role.                                 |
| `HERMES_API_URL`          | *(empty)*          | Force API mode against this base URL.            |
| `HERMES_API_KEY`          | *(empty)*          | Bearer token if your API endpoint needs one.     |
| `HERMES_MODEL`            | `hermes-agent`     | Model name sent in API mode.                     |
| `HERMES_BIN`              | `hermes`           | Path to the hermes CLI for CLI mode.             |
| `HERMES_CLI_EXTRA`        | *(empty)*          | Extra CLI args, such as `--yolo`.                |
| `HERMES_TIMEOUT`          | `180`              | Seconds to wait for a Hermes answer.             |
| `API_PROBE_TIMEOUT`       | `2`                | Seconds per endpoint probe at startup.           |
| `HERMES_SPEAKABLE_HINT`   | `1`                | `0` disables the concise for speech hint.        |
| `HERMES_BRIDGE_LOG_LEVEL` | `INFO`             | Logging verbosity.                               |

---

## Troubleshooting

- **"I couldn't reach Hermes":** bridge not running or Hermes not working. Test
  with `hermes -z "say hi"`.
- **"No API endpoint and hermes not found":** `hermes` isn't on PATH. Set
  `HERMES_BIN`, or run an endpoint and set `HERMES_API_URL`.
- **First question empty, second works:** cold start. Raise `HERMES_TIMEOUT`.
- **Tool calls hang:** run with `HERMES_CLI_EXTRA="--yolo"` to auto approve.
- **Replies too long:** keep `HERMES_SPEAKABLE_HINT=1` and ask narrower questions.
- **Won't connect to OpenHome:** wrong or expired key, or a different host. Check
  the dashboard.

## Security

The bridge runs Hermes with **your** permissions (shell and files), so only
trigger requests you'd run yourself. The `--yolo` flag removes the manual tool
approval step; use it knowingly. Keep `OPENHOME_API_KEY` secret and rotate it if
exposed.