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

- `BACKEND_URL` in `main.py` — point at your Immersive backend.
- Optional API key: save it in OpenHome Settings → API Keys under `immersive_api_key`.
- No backend? The skill still runs end to end on demo data.

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
