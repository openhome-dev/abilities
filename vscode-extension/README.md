# OpenHome Abilities — VS Code extension

Manage your OpenHome agents and abilities from a sidebar. The account and
ability features talk to the OpenHome API **directly** (no Python needed) — voice
calls and the local devkit bridge use the [`openhome` CLI](../cli) when present.

## What it does

Adds an **OpenHome** icon to the activity bar with four sections:

| Section | Actions | Backend |
| --- | --- | --- |
| **Account** | Sign in (API key), open dashboard, list agents | Direct API |
| **Abilities** | List · per-item: Enable / Disable / Set triggers / Delete | Direct API |
| **Abilities** | Create / Sync / Push (work on local folders) | CLI |
| **Voice** | Voice call, Chat (open in a terminal — need mic/TTY) | CLI |
| **Local Bridge (Devkit)** | Start / Stop / Status / Logs, with a green/red dot | CLI |

Credentials are stored in VS Code's encrypted **SecretStorage**. If you already
have a `~/.openhome/config.json` or an `OPENHOME_API_KEY` in a workspace `.env`,
the extension picks it up automatically — same resolution order as the CLI.

## Install

Grab the packaged extension and install it like any other:

```bash
code --install-extension openhome-abilities-<version>.vsix
```

…or in VS Code: **Extensions → ⋯ → Install from VSIX…**

Then click the **OpenHome** icon in the activity bar and hit **Sign In**.

### Optional: voice + devkit

Those features shell out to the Python CLI. If it isn't installed, the extension
offers a one-click **Install CLI** (`pip install openhome-client`). If it lives in
a virtualenv, the extension auto-detects `.venv/bin/openhome`; otherwise set the
full path in **Settings → OpenHome → Cli Path**.

## Settings

- `openhome.cliPath` — command for the CLI (default: `openhome`; auto-detects a repo `.venv`).
- `openhome.cwd` — working directory for CLI commands (default: first workspace folder).

## Develop

```bash
cd vscode-extension
npm install
npm run compile        # or: npm run watch
```

Press **F5** to launch an Extension Development Host.

## Package

```bash
npm run package        # produces openhome-abilities-<version>.vsix
```

## Roadmap

- Live socket connection driving the Devkit green/red indicator in real time.
- Native create/push/sync (zip upload) so the CLI becomes optional for everything.
- Streaming call transcripts into a panel.
