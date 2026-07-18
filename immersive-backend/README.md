# Immersive Backend + Live Dashboard

Single-file Flask app: the real data layer for the Immersive skills, plus a live
ops dashboard at `/` (dark theme, polls every 2 seconds).

## Deploy on Replit (5 minutes)

1. Create a new Python Repl, paste `main.py` and `requirements.txt`.
2. Run it. Replit gives you a public URL like `https://immersive-backend.<user>.repl.co`.
3. In OpenHome → Settings → API Keys, save that URL under the name
   **`immersive_backend_url`** (no trailing slash). All three abilities pick it
   up automatically — no code change needed.
4. Open the Replit URL in a browser tab during the demo: requests, bookings, and
   live provider scores update as you talk.

## Endpoints

| Method | Path | Used by |
|---|---|---|
| POST | `/requests` | intake skill (creates request, providers auto-quote) |
| GET | `/requests?status=open\|booked\|rated` | provider + feedback skills, daemon |
| GET | `/requests/{id}/quotes` | provider skill (live provider scores) |
| POST | `/quotes/{id}/accept` | provider skill (books, declines the rest) |
| POST | `/feedback` | feedback skill (updates provider running average + reliability) |
| GET | `/api/state` | dashboard |
| POST | `/api/reset` | demo helper: back to seed data |
| GET | `/health` | daemon connectivity check |

## Real data flow

intake POSTs a request → matching providers quote (price from their base rate)
→ provider skill ranks live scores and books → feedback skill rates → the
provider's rating (running average over jobs) and reliability move → next
booking sees the updated leaderboard. State persists to `immersive_db.json`
across restarts.
