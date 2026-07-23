# Immersive Feedback (Skill)

Voice skill for the Immersive home-maintenance agent: rate a completed provider
job by voice so the ranking backend can personalize future provider matches.

## Trigger words

- "rate my service"
- "job finished"
- "leave feedback"

## Flow

1. Loads rateable jobs — backend first (`GET /requests?status=booked`), then the
   shared local file `immersive_requests.json` (jobs the provider skill marked
   `booked`), then a built-in demo job so the skill is testable without a backend.
2. If several jobs are rateable, asks which one by provider or category.
3. Collects a 1–5 rating by voice — words work too ("great" → 4, "terrible" → 1),
   mapped by a strict LLM classifier.
4. Asks for an optional short comment (say "skip" to pass).
5. Confirms, then POSTs `/feedback` with request id, provider, rating, and comment,
   and marks the job `rated` in `immersive_requests.json` so it isn't offered again.
6. Every exit path ends with `resume_normal_flow()` (guaranteed via `try/finally`).

## Configuration

- Save your deployed backend URL in OpenHome Settings → API Keys under
  `immersive_backend_url` (and optionally an auth key under `immersive_api_key`).
- No backend? The skill still runs end to end on the shared file / demo data.

## Backend & API contract

The marketplace backend is a small Flask app hosted **in its own repository** (it is
not an OpenHome ability, so it lives outside this repo):

> Backend repo: `<ADD_BACKEND_REPO_URL_HERE>`

Skills read its base URL from the `immersive_backend_url` API key and auto-detect an
optional `/api` route prefix. This skill calls two endpoints:

**`GET /requests?status=booked`** — list booked jobs awaiting a rating.

```jsonc
{ "ok": true, "requests": [
    { "id": "a1b2c3d4", "category": "plumbing", "status": "booked",
      "booked_provider": "Ahmed Plumbing Services" } ] }
```

**`POST /feedback`** — submit a rating; the backend updates the provider's
running-average score and reliability.

```jsonc
// request body
{ "request_id": "a1b2c3d4", "provider": "Ahmed Plumbing Services",
  "rating": 5, "comment": "fast and tidy" }
// response
{ "ok": true }
```

## Shared-state contract

Lifecycle: intake creates requests (`open`) → provider skill books one (`booked`)
→ this skill rates it (`rated`).

```json
{
  "requests": [
    {
      "id": "demo-1",
      "category": "plumbing",
      "status": "rated",
      "booked_provider": "Rapid Plumbing Co",
      "feedback": {"rating": 5, "comment": "fast and tidy"}
    }
  ]
}
```
