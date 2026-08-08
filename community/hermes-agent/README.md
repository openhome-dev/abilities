# Hermes Agent Bridge

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@r0b0tlab-lightgrey?style=flat-square)

## What It Does

Hermes Agent Bridge turns an OpenHome speaker into a voice front end for a local Hermes Agent install. It sends a spoken task through OpenHome's local command bridge, runs `hermes chat -q` on the linked computer, then reads back a short voice-friendly result.

## Suggested Trigger Words

- "ask Hermes"
- "run Hermes"
- "Hermes agent"
- "send this to Hermes"

## Setup

1. Install Hermes Agent on the computer connected to OpenHome.

   Linux, macOS, WSL2, or Android Termux:
   ```bash
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
   source ~/.bashrc   # or source ~/.zshrc
   ```

   Windows PowerShell:
   ```powershell
   iex (irm https://hermes-agent.nousresearch.com/install.ps1)
   ```

2. Configure Hermes and verify a normal chat works before using this Ability.

   Fast path with Nous Portal:
   ```bash
   hermes setup --portal
   hermes chat -q "Reply with: ready for OpenHome."
   ```

   If you use your own provider, run:
   ```bash
   hermes model
   hermes chat -q "Reply with: ready for OpenHome."
   ```

3. Connect the OpenHome local command bridge on the same computer. This Ability uses `exec_local_command()`, so the local client must be running and connected with your OpenHome API key from `https://app.openhome.com/dashboard/settings`.

4. Upload this folder to `https://app.openhome.com/dashboard/abilities` with Add Custom Ability.

5. Set the suggested trigger words in the dashboard and test in Live Editor.

## How It Works

1. You say a trigger phrase such as "ask Hermes" plus the task.
2. OpenHome captures the complete transcription.
3. The Ability blocks obviously unsafe requests and asks for confirmation before tasks that may change the local system.
4. The Ability checks `hermes --version` on the linked computer.
5. The Ability runs `hermes chat -q <task>` through `exec_local_command()`.
6. Hermes completes the task locally using its configured model, tools, skills, memory, and terminal backend.
7. OpenHome rewrites the Hermes result into one or two spoken sentences and returns to normal flow.

## Example Conversation

> **User:** "ask Hermes to summarize the current git status in my project"
> **OpenHome:** "Sending that to Hermes. This may take a minute."
> **OpenHome:** "Hermes says your branch is clean and up to date."

> **User:** "run Hermes and push my latest code"
> **OpenHome:** "That may change your local system. Should Hermes run it?"
> **User:** "yes"
> **OpenHome:** "Sending that to Hermes. This may take a minute."
> **OpenHome:** "Hermes pushed the branch successfully."

## Safety Behavior

This Ability improves on the minimal OpenClaw-style pass-through by adding:

- a Hermes availability check before dispatch;
- confirmation for tasks involving deletes, installs, deploys, commits, pushes, payments, sends, or other local-system changes;
- rejection for obviously unsafe requests such as drive wipes, credential theft, malware, and security bypasses;
- shell-safe prompt quoting before calling `hermes chat -q`;
- structured response parsing for `data`, `stdout`, `output`, `message`, and `error` responses;
- short voice rewriting instead of speaking raw command output.

## Troubleshooting

### "Hermes is not available on the linked computer yet"

Run these on the linked computer:

```bash
hermes --version
hermes chat -q "Reply with: ready."
```

If those fail, finish Hermes setup first with `hermes setup --portal` or `hermes model`.

### OpenHome does not reach the computer

Keep the OpenHome local command bridge running. The Ability depends on `exec_local_command()` just like the Local and OpenClaw templates.

### Hermes runs too long

Increase `HERMES_TIMEOUT_SECONDS` in `main.py` for long research or coding tasks. Keep spoken prompts short so the voice interaction does not feel stuck.

### Wrong computer receives the task

Set `HERMES_TARGET_ID` in `main.py` to the target device identifier used by your local bridge.

## Notes for Builders

- Trigger words live in the OpenHome dashboard, not in code.
- Do not create or edit `config.json`; OpenHome manages it.
- Keep `# {{register capability}}` unchanged.
- Keep `resume_normal_flow()` on every exit path.
- Do not put Hermes API keys or provider keys in this Ability. Configure them inside the local Hermes install.

## APIs Required

No external API is called directly by this OpenHome Ability. Hermes may use whichever model provider and tools the user configured locally.
