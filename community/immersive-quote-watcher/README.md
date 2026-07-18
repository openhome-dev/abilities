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
