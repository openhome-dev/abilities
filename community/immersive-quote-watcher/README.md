# Immersive Quote Watcher (Background Daemon)

Auto-starts with every agent session. Every 30 seconds it polls the Immersive
backend for open service requests that have received provider quotes, and
announces each one exactly once:

> "Good news, you have 3 quotes for the plumbing job. Say check my quotes to compare."

## Demo safety

- Waits 20 seconds after session start so it never talks over the greeting.
- Completely silent when `immersive_backend_url` isn't configured or the
  backend is down — it can only add to the demo, never break it.
- Announces each request once per session (tracked in memory).

## Configuration

Same as the other Immersive skills: save your deployed backend URL in
OpenHome Settings → API Keys under `immersive_backend_url` (and optionally an
auth key under `immersive_api_key`).

## Backend & API contract

The marketplace backend is a small Flask app hosted **in its own repository** (it is
not an OpenHome ability, so it lives outside this repo):

> Backend repo: https://github.com/AliZain330/immersive-backend

The daemon reads its base URL from the `immersive_backend_url` API key and
auto-detects an optional `/api` route prefix. It polls one endpoint:

**`GET /requests?status=open`** — it announces any request whose `quote_count`
is 1 or more, once per session.

```jsonc
{ "ok": true, "requests": [
    { "id": "a1b2c3d4", "category": "plumbing", "status": "open",
      "quote_count": 3 } ] }
```
