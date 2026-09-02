# OpenHome Local Link — Terminal Control Template

![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)
![Category](https://img.shields.io/badge/Category-Local-green?style=flat-square)

Turn a voice request into a real terminal command on your own computer. You speak,
an LLM converts it to a shell command, it runs on your machine through the **OpenHome
CLI's Local Link bridge**, and the result is spoken back in plain language.

---

## ⚠️ Deprecation Notice

The old setup for this template — **downloading `local_client.py` from Google Drive
and running it by hand** — is **deprecated. Do not use it.**

Local execution now runs through the **OpenHome CLI** (`openhome local`), which ships
in this repository, is versioned and reviewable, and manages the connection for you.
If you have an old `local_client.py` running, stop it and follow the setup below.

---

## How It Works

```
You speak  ->  OpenHome (cloud)  ->  Local Link bridge (openhome CLI, your PC)  ->  your shell
                        spoken reply travels back along the same path
```

OpenHome runs in the cloud and cannot reach your computer directly. The **Local Link
bridge** (`openhome local`) is a small process you run on your machine. It holds a
connection to your Agent and routes each request to a local handler. This template
uses the built-in **`local-link`** handler — a raw shell executor that is always
available once the bridge is running.

The ability itself:
1. Captures your spoken request.
2. Asks the LLM to turn it into one shell command.
3. Sends the command over Local Link with `exec_local_command()`.
4. The bridge runs it in your shell and returns the output.
5. The LLM rewrites the output into a short spoken reply.

---

## Setup

### 1. Install the OpenHome CLI

From the root of this repository (requires Python 3.10+):

```bash
python3 -m venv cli/.venv && source cli/.venv/bin/activate
pip install -e cli
```

Full CLI reference: [`cli/README.md`](../../cli/README.md) ·
Official guide: <https://docs.openhome.com/guides/getting-started/cli>

### 2. Log in

```bash
openhome login          # paste your API key from Dashboard -> Settings -> API Keys
```

### 3. Start the Local Link bridge

Run this on the computer you want to control, and keep it running:

```bash
openhome local start     # start the bridge in the background
openhome local status    # confirm it is running
openhome local logs      # watch requests and replies live (Ctrl-C to stop)
openhome local stop      # stop it
```

`openhome local run` runs it in the foreground for debugging. `start` / `run` accept
`--client-id` (device name, default `laptop`), `--role` (default `agent`), and
`--timeout` (per-request seconds, default `30`).

Once the bridge is running, the **`local-link`** handler is available automatically —
no extra download, no client file to edit.

### 4. Add the ability

Add the **OpenHome Local Link** template to your Agent from the Dashboard, set your
**Trigger Words** (for example `terminal`, `run command`), and test it in the Live
Editor.

---

## What You Can Build

- A system monitor (disk, CPU, memory, battery)
- A file-management assistant (create, move, find files)
- A dev-environment controller (git, npm, build scripts)
- An application launcher
- Network diagnostics (ping, traceroute)

---

## Core Function: `exec_local_command()`

Sends a command over Local Link and returns the result.

```python
async def exec_local_command(
    self,
    command: str | dict,
    target_id: str | None = None,   # device id (default: "laptop")
    timeout: float = 10.0,          # seconds to wait
)
```

```python
# A plain string runs on the raw-shell `local-link` handler:
response = await self.capability_worker.exec_local_command("df -h")

# Longer commands: raise the timeout
response = await self.capability_worker.exec_local_command(
    "find / -name '*.log'", timeout=30.0
)
```

---

## Customizing the Template

**Change how commands are generated** — edit the system prompt in `get_system_prompt()`
so it targets your OS and use case (the default targets macOS zsh/bash).

**Confirm dangerous commands** before running them:

```python
terminal_command = self.capability_worker.text_to_text_response(...)

if any(danger in terminal_command for danger in ("rm ", "sudo", "shutdown", "dd ")):
    await self.capability_worker.speak(f"This runs: {terminal_command}. Confirm?")
    if "yes" not in (await self.capability_worker.user_response() or "").lower():
        await self.capability_worker.speak("Cancelled.")
        self.capability_worker.resume_normal_flow()
        return

response = await self.capability_worker.exec_local_command(terminal_command)
```

**Handle timeouts and errors** so a turn never goes silent:

```python
try:
    response = await self.capability_worker.exec_local_command(terminal_command)
except Exception as e:
    self.worker.editor_logging_handler.error(f"Command failed: {e}")
    await self.capability_worker.speak("That command failed or timed out.")
finally:
    self.capability_worker.resume_normal_flow()
```

---

## Safety

- The `local-link` handler runs commands **in your shell, with your permissions** —
  there is no sandbox. Only trigger requests you would run yourself.
- Add a confirmation step (above) for anything destructive (`rm`, `sudo`,
  `shutdown`, `dd`).
- Keep your OpenHome API key private; rotate it if it is exposed.

---

## Troubleshooting

- **"Local Link isn't connected":** the bridge isn't running. Start it with
  `openhome local start`, then check `openhome local status`. If you're logged out,
  run `openhome login` first.
- **Commands time out:** raise the timeout (`exec_local_command(cmd, timeout=60.0)`)
  and watch `openhome local logs` to see what ran.
- **Nothing happens:** confirm the ability's trigger words are set in the Dashboard
  and that the bridge is running on the machine you expect (`--client-id`).

---

## `local-link` vs `openclaw`

Both run through the same `openhome local` bridge, as two handlers:

| Handler | What it does | Needs |
|---|---|---|
| **`local-link`** (this template) | Runs a single shell command directly | Nothing — always available with the bridge |
| **`openclaw`** | Natural-language desktop automation via OpenClaw | OpenClaw installed and its gateway running |

Use **`local-link`** for direct, concrete terminal commands. See the
[`openclaw`](../openclaw) template for LLM-driven automation.

---

## Links

- [OpenHome CLI reference](../../cli/README.md)
- [Official CLI guide](https://docs.openhome.com/guides/getting-started/cli)
- [Dashboard](https://app.openhome.com/dashboard) · [API Keys](https://app.openhome.com/dashboard/settings)

> This template is a starting point. Customize the prompt, add safety checks, and make
> it yours before relying on it.
