# Immersive Provider (Skill)

Voice skill for the Immersive home-maintenance agent: compare provider quotes on an
open service request and book one, entirely by voice.

## Trigger words

Set in the OpenHome dashboard (suggestions, mirrored in `config.json`):

- "check my quotes"
- "compare providers"
- "book a provider"

## Flow

1. Loads open requests — backend first (`GET /requests?status=open`), then the shared
   local file `immersive_requests.json` (written by the intake skill), then a built-in
   demo request so the skill is testable without any backend.
2. If several requests are open, asks which one by category.
3. Fetches quotes (`GET /requests/{id}/quotes`, demo quotes as fallback) and ranks
   them with a deterministic quality-first score: rating 45%, reliability 25%,
   price 15% (floored so cheap can't beat great), availability 15%.
4. Speaks a two-sentence recap (top pick + runner-up), then loops: the user can ask
   for details, hear the comparison again, book a quote, or stop.
5. Booking requires an explicit yes; on confirm it POSTs `/quotes/{id}/accept` and
   marks the request `booked` in `immersive_requests.json` so the feedback skill can
   find it later.
6. Every exit path ends with `resume_normal_flow()` (guaranteed via `try/finally`).

## Configuration

- Save your deployed backend URL in OpenHome Settings → API Keys under
  `immersive_backend_url` (and optionally an auth key under `immersive_api_key`).
- No backend? The skill still runs end to end on the shared file / demo data.

## Backend & API contract

The marketplace backend is a small Flask app hosted **in its own repository** (it is
not an OpenHome ability, so it lives outside this repo):

> Backend repo: https://github.com/AliZain330/immersive-backend

Skills read its base URL from the `immersive_backend_url` API key and auto-detect an
optional `/api` route prefix. This skill calls three endpoints:

**`GET /requests?status=open`** — list open requests.

```jsonc
{ "ok": true, "requests": [
    { "id": "a1b2c3d4", "category": "plumbing", "description": "leaking pipe",
      "status": "open", "booked_provider": null, "quote_count": 3 } ] }
```

**`GET /requests/{id}/quotes`** — quotes for a request.

```jsonc
{ "ok": true, "quotes": [
    { "id": "q1", "request_id": "a1b2c3d4", "provider": "Ahmed Plumbing Services",
      "price": 3500, "rating": 4.8, "reliability": 0.96,
      "availability": "today at 5 PM", "status": "offered" } ] }
```

**`POST /quotes/{id}/accept`** — book a quote (declines the rest).

```jsonc
// request body
{ "request_id": "a1b2c3d4" }
// response
{ "ok": true, "quote": { "id": "q1", "provider": "Ahmed Plumbing Services",
    "status": "accepted" } }
```

## Shared-state contract

Abilities can't call each other, so lifecycle skills communicate through
`immersive_requests.json`. Lifecycle: intake creates requests (`open`) → this
skill books one (`booked`) → the feedback skill rates it (`rated`).

```json
{
  "requests": [
    {
      "id": "demo-1",
      "category": "plumbing",
      "description": "leaking pipe under the kitchen sink",
      "status": "open" | "booked" | "rated",
      "booked_provider": "Rapid Plumbing Co",
      "feedback": {"rating": 5, "comment": "set by the feedback skill"}
    }
  ]
}
```
