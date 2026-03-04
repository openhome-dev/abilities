# Coding Agent Runner

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@juyounglee-lightgrey?style=flat-square)

## What It Does
Runs a coding task through a remote webhook that invokes Claude Code or Codex headlessly, then reads back a short spoken result.

## Trigger Words
- "run coding task"
- "run a coding agent"
- "execute coding task"

## Setup
1. Run any webhook server that accepts `POST /run` with bearer auth (see example below).
2. In `main.py`, replace `WEBHOOK_URL` and `WEBHOOK_TOKEN` placeholders. Use the same token on both sides.
3. Upload this ability to OpenHome and set trigger words in the dashboard.

If OpenHome can't reach your server directly, use a tunnel (e.g. `ngrok http 8080`).

## Webhook Contract

The ability sends:
```
POST /run
Authorization: Bearer <token>
{"prompt": "Add tests for the validator script"}
```

And expects back:
```json
{"ok": true, "summary": "Added tests and they pass."}
```

Optional response fields: `artifact_path`, `request_id`.

## Minimal Webhook Server

The webhook just needs to run Claude Code or Codex and return the output. Swap the command to match your agent.

> **Safety note:** Both examples use autonomous execution flags. Only run in a
> sandboxed environment or a directory you're comfortable modifying.

```python
# Runs on a separate server, not inside OpenHome.
import subprocess
from flask import Flask, jsonify, request

app = Flask(__name__)
TOKEN   = "your-secret-token"
AGENT   = "claude"                                  # "claude" or "codex"
WORKDIR = "/path/to/your/project"                   # sandbox / working directory

def agent_cmd(prompt):
    if AGENT == "codex":
        return ["codex", "exec", "--full-auto", prompt]
    return ["claude", "-p", prompt, "--allowedTools", "Bash,Read,Write,Edit"]

@app.post("/run")
def run():
    if request.headers.get("Authorization") != f"Bearer {TOKEN}":
        return jsonify(ok=False, error="unauthorized"), 401

    prompt = (request.get_json(silent=True) or {}).get("prompt", "").strip()
    if not prompt:
        return jsonify(ok=False, error="prompt required"), 400

    result = subprocess.run(
        agent_cmd(prompt),
        capture_output=True, text=True, timeout=600, check=False,
        cwd=WORKDIR,
    )
    if result.returncode != 0:
        return jsonify(ok=False, error=f"exit code {result.returncode}"), 500

    return jsonify(ok=True, summary=result.stdout.strip() or "Done.")
```

## Example Conversation
> **User:** "run coding task"
> **AI:** "Tell me the coding task you'd like to run."
> **User:** "Add basic tests for the validator script and run them."
> **AI:** "Got it. Want me to run that now?"
> **User:** "Yes"
> **AI:** "Tests were added and they all pass."

## Logs
Look for `[CodingAgentRunner]` entries in OpenHome Live Editor logs.

## Token Hygiene
For demos, static tokens are fine. After testing, rotate on both sides.
