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

- `BACKEND_URL` in `main.py` — point at your Immersive backend.
- Optional API key: save it in OpenHome Settings → API Keys under `immersive_api_key`.
- No backend? The skill still runs end to end on demo data.

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
