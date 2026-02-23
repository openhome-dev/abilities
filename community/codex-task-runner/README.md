# Codex Task Runner

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@juyounglee-lightgrey?style=flat-square)

## What It Does
Runs a coding task through a remote webhook that executes `codex exec` headlessly, then reads back a short spoken result.

## Client / Server Example
- **Client:** OpenHome WebUI (or OpenHome runtime) running this ability.
- **Server:** any webhook server that exposes `POST /run` and returns the expected JSON.
- If OpenHome is remote, expose local server with a tunnel and set `WEBHOOK_URL` to that public `/run` URL.

## Configuration style (WebUI-friendly)
This ability is configured directly in `main.py` constants:

```python
WEBHOOK_URL = "https://<your-ngrok-domain>/run"
WEBHOOK_TOKEN = "<same-token-as-webhook-server>"
REQUEST_TIMEOUT_SECONDS = 180
```

Use the exact same `WEBHOOK_TOKEN` value on both sides.

## Suggested Trigger Words
- "run codex task"
- "ask codex to code"
- "execute coding task"

## Setup
1. Run any webhook server that accepts `POST /run` with bearer auth.
2. Run `ngrok http 8080` if OpenHome must call your local machine.
3. In this ability's `main.py`, replace `WEBHOOK_URL` and `WEBHOOK_TOKEN` placeholders.
4. Upload this Ability zip to OpenHome and set trigger words in the dashboard.

## Minimal Codex Webhook Example (crude)

```python
# NOTE: This example runs on a separate webhook server, not inside an OpenHome
# ability. It is not subject to OpenHome ability SDK restrictions.
import os
import subprocess
import uuid
from flask import Flask, jsonify, request

app = Flask(__name__)
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "YOUR_WEBHOOK_TOKEN_HERE")
RUNS_DIR = os.environ.get("RUNS_DIR", "./runs")
DEFAULT_WORKDIR = os.path.realpath(
    os.path.abspath(os.environ.get("CODEX_WORKDIR", "."))
)
CODEX_SANDBOX = os.environ.get("CODEX_SANDBOX", "workspace-write")
CODEX_TIMEOUT_SECONDS = int(os.environ.get("CODEX_TIMEOUT_SECONDS", "600"))


def _is_allowed_workdir(path: str) -> bool:
    target = os.path.realpath(os.path.abspath(path))
    try:
        common = os.path.commonpath([DEFAULT_WORKDIR, target])
    except ValueError:
        return False
    return common == DEFAULT_WORKDIR


@app.post("/run")
def run():
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {WEBHOOK_TOKEN}":
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    req = request.get_json(silent=True) or {}
    prompt = (req.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "prompt is required"}), 400

    target_workdir = req.get("workdir") or DEFAULT_WORKDIR
    if not _is_allowed_workdir(target_workdir):
        return jsonify({"ok": False, "error": "workdir not allowed"}), 403
    if not os.path.isdir(target_workdir):
        return jsonify({"ok": False, "error": "workdir not found"}), 400

    request_id = uuid.uuid4().hex[:12]
    run_dir = os.path.join(RUNS_DIR, request_id)
    os.makedirs(run_dir, exist_ok=True)

    artifact_path = os.path.join(run_dir, "final-message.txt")
    events_path = os.path.join(run_dir, "events.jsonl")
    stderr_path = os.path.join(run_dir, "stderr.log")

    cmd = [
        "codex",
        "exec",
        "-C",
        target_workdir,
        "--json",
        "-o",
        artifact_path,
        "--full-auto",
        "--sandbox",
        CODEX_SANDBOX,
        prompt,
    ]

    with open(events_path, "w", encoding="utf-8") as out, open(
        stderr_path, "w", encoding="utf-8"
    ) as err:
        result = subprocess.run(
            cmd,
            stdout=out,
            stderr=err,
            text=True,
            timeout=CODEX_TIMEOUT_SECONDS,
            check=False,
        )

    if result.returncode != 0:
        return jsonify({
            "ok": False,
            "error": f"codex failed with exit code {result.returncode}",
            "events_path": events_path,
            "request_id": request_id,
        }), 500

    summary = "Codex completed the task."
    if os.path.exists(artifact_path):
        with open(artifact_path, "r", encoding="utf-8") as f:
            summary = (f.read().strip() or summary)[:800]

    return jsonify({
        "ok": True,
        "summary": summary,
        "artifact_path": artifact_path,
        "events_path": events_path,
        "request_id": request_id,
    })
```

## Expected Webhook Response
The ability expects JSON with this shape:

```json
{
  "ok": true,
  "summary": "Codex completed the task and updated two files.",
  "artifact_path": "/absolute/path/to/final-message.txt",
  "events_path": "/absolute/path/to/events.jsonl",
  "request_id": "7fd8c0bf44c1"
}
```

For production deployments, prefer returning relative paths (or opaque IDs/URLs)
instead of absolute filesystem paths.

## How It Works
1. Ask user for a coding task.
2. Check required constants (`WEBHOOK_URL`, `WEBHOOK_TOKEN`).
3. Confirm before executing.
4. Send task to webhook as JSON (`{"prompt": "..."}`) with bearer auth.
5. Speak returned summary and optional artifact path.
6. Return to normal Personality flow.

## Quick test flow
1. Trigger with a phrase like **"run codex task"**.
2. Give a short task prompt.
3. Say **yes** on confirmation.
4. Verify spoken summary and webhook artifact path.

## Logs
- Ability logs are emitted with `editor_logging_handler` in OpenHome Live Editor logs.
- Look for `[CodexTaskRunner]` entries.
- On successful webhook calls, logs include `request_id` so you can match server-side logs.

## Token hygiene
For demo use, static token constants are fine. After testing, rotate the token on both webhook and ability.

## Example Conversation
> **User:** "run codex task"
> **AI:** "Tell me the coding task you want Codex to run."
> **User:** "Add basic tests for the validator script and run them."
> **AI:** "Got it. Want me to run Codex on that now?"
> **User:** "Yes"
> **AI:** "Codex added tests and confirmed they pass."
