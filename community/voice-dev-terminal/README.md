# Voice Dev Terminal

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hasni1731996-lightgrey?style=flat-square)

A voice-native developer terminal for OpenHome. Say "terminal", then keep talking — run git commands, check disk space, find files, tail logs — all hands-free, with LLM-generated commands and spoken summaries of the output.

## What Makes It Different

The closest existing templates are **`openhome-local-link`**, **`openclaw`**, and **`hermes`** — each solves a different problem:

| | `openhome-local-link` | `openclaw` / `hermes` | Voice Dev Terminal |
|---|---|---|---|
| Mechanism | `exec_local_command` (shell) | WebSocket → persistent agent process | `exec_local_command` (shell) |
| Session | One command, exits | One-shot delegation | Stays open for multiple commands |
| Requires extra software | No | Yes (OpenClaw / Hermes agent running) | No |
| Command source | LLM one-shot | Delegated to agent | LLM with full conversation history |
| Output | Raw string spoken back | Agent's reply | LLM-summarized into natural speech |
| Dangerous commands | No guard | Handled by agent | Voice confirmation required |
| Inline trigger | No | No | "terminal, git status" runs immediately |

**OpenClaw and Hermes** connect to persistent agent processes running on your machine via WebSocket — they're delegation layers for agent-based workflows. Voice Dev Terminal is an ad-hoc interactive shell session: no persistent process needed, just the Local Link bridge.

**`openhome-local-link`** is the closest comparator. It runs one command and exits. Voice Dev Terminal keeps the session open, maintains conversation history across commands (so "do it again but verbose" works), and adds a danger-token confirmation step before running destructive commands.

## Trigger Phrases

- `terminal` / `open terminal` / `dev terminal` / `developer terminal`
- `run command` / `run a command` / `execute command`

## Example Conversations

**Basic session:**
> "terminal"
> → "Terminal ready. What do you need?"
> "what's my git status?"
> → "Running that now. You're on branch main, 2 files modified and not staged."
> "show recent commits"
> → "Running that now. 3 commits in the last day. Latest: fix auth bug, 2 hours ago."
> "done"
> → "Got it."

**Inline trigger (no prompt needed):**
> "terminal, check disk space"
> → "Running that now. Your disk is 78% full — 56 gigs free of 256."

**Dangerous command:**
> "remove the build folder"
> → "That runs: rm -rf ./build. Confirm?"
> "yes"
> → "Running that now. Done."

**Context-aware follow-up:**
> "list python files"
> → "Running that now. Found 12 Python files in this directory."
> "do it again but only in the src folder"
> → "Running that now." (LLM resolves to `find ./src -name "*.py"`)

## Exit Phrases

`done` · `bye` · `goodbye` · `that's all` · `all done` · `close terminal` · `never mind`

## Safety

Dangerous command tokens (`rm`, `rmdir`, `sudo`, `shutdown`, `reboot`, `kill`, `pkill`, `dd`, `mkfs`) trigger a spoken confirmation before the command runs. Say anything other than "yes" to cancel.

Commands run in your shell with your own permissions — the Local Link bridge provides no sandbox.

## Setup

This ability requires the **OpenHome CLI Local Link bridge** running on your machine.

### 1. Install the CLI

From the root of this repository (Python 3.10+):

```bash
python3 -m venv cli/.venv && source cli/.venv/bin/activate
pip install -e cli
```

### 2. Log in

```bash
openhome login   # paste your API key from Dashboard → Settings → API Keys
```

### 3. Start the bridge

```bash
openhome local start    # runs in the background
openhome local status   # confirm it's running
openhome local logs     # watch commands and output in real time
```

Keep it running while you use the ability.

### 4. Add the ability

Add **Voice Dev Terminal** to your Agent from the Dashboard and set the trigger words above.

## Notes

- The LLM targets macOS zsh/bash. On Linux, most commands work as-is; adjust the system prompt in `get_system_prompt()` if needed.
- Long-running commands time out after 30 seconds. Raise the timeout in `exec_local_command()` for things like `npm install` or large `find` operations.
- Conversation history is in-memory and resets when the session exits. There is no persistent command log.

## Author

Muhammad Hassan
