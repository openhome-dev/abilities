# Immersive Diagnosis (Skill)

Voice intake for the Immersive home-maintenance agent. Diagnoses a home problem
through guided troubleshooting playbooks, applies safety triage (never advises
unsafe electrical/gas/structural DIY), and — when a professional is needed —
creates a service request the other Immersive skills act on.

## Trigger words

- "home help"
- "diagnose my home"
- "ac not cooling"

## Flow

1. Asks what's wrong, then runs the matching playbook (a dedicated AC-not-cooling
   flow, or a generic safety → describe → location → duration → tried triage).
2. Continuously scans for safety red flags (burning, smoke, sparking, gas, flooding);
   on any flag it stops DIY guidance and offers an emergency technician.
3. On resolution it stops; on escalation it builds a structured service request and,
   after confirmation, creates it.
4. Every exit path ends with `resume_normal_flow()` (guaranteed via `try/finally`).

## Configuration

- Save your deployed backend URL in OpenHome Settings → API Keys under
  `immersive_backend_url` (and optionally an auth key under `immersive_api_key`).
- No backend? The skill still runs end to end and persists the request to the shared
  local file `immersive_requests.json`.

## Backend & API contract

The marketplace backend is a small Flask app hosted **in its own repository** (it is
not an OpenHome ability, so it lives outside this repo):

> Backend repo: `<ADD_BACKEND_REPO_URL_HERE>`

Skills read its base URL from the `immersive_backend_url` API key and auto-detect an
optional `/api` route prefix. This skill calls one endpoint:

**`POST /requests`** — create a service request; the backend has matching providers
quote automatically.

```jsonc
// request body
{ "category": "hvac", "description": "AC not cooling in the bedroom", "urgency": "soon" }

// response
{ "ok": true, "request": {
    "id": "a1b2c3d4", "category": "hvac", "description": "AC not cooling in the bedroom",
    "urgency": "soon", "status": "open", "created_at": "2026-07-23 12:00:00",
    "booked_provider": null, "feedback": null } }
```

## Shared-state contract

Abilities can't call each other, so lifecycle skills communicate through the backend
(primary) and the shared file `immersive_requests.json` (fallback). Lifecycle:
this skill creates requests (`open`) → the provider skill books one (`booked`) →
the feedback skill rates it (`rated`).
