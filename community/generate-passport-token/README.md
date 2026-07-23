# Generate Passport Token

A voice-driven OpenHome Ability, entirely in Urdu, that walks a citizen through applying for a passport token at a kiosk — full name, age, date of birth, CNIC, email, address, province/city/district/domicile, and branch — then submits it to a backend and reads back the token number.

## Suggested Trigger Words

- "generate passport token"
- "passport token"
- "get a passport token"

## Setup

This Ability calls an external Flask backend and needs three values configured before it will run. Add these under **OpenHome Settings → API Keys** (names must match exactly):

| API Key name | What it is |
|---|---|
| `passport_api_base_url` | Base URL of the Flask backend (e.g. its ngrok URL) |
| `passport_admin_cnic` | CNIC of the kiosk's service/admin account |
| `passport_admin_password` | Password of the kiosk's service/admin account |

Nothing is hardcoded in source — the ability fetches all three at runtime and will tell the citizen the system isn't set up yet (and log the missing key) if any are absent, rather than crashing.

The citizen never provides the kiosk's own login — they never have an account. The ability signs in automatically with the service account above purely to talk to the backend on their behalf.

## How It Works

1. Citizen says a trigger phrase.
2. The agent greets them in Urdu and explains they can say a stop phrase at any time.
3. It automatically signs in to the backend (silently, using the service account — no login questions asked of the citizen).
4. It collects, one at a time: full name, age, date of birth, CNIC, email (optional), address, province, city, district, domicile, and branch — using numbered choices for anything with a fixed list, and an LLM cleanup pass for free-form spoken answers.
5. If the applicant is under 18, it also asks for both parents' CNIC.
6. It submits everything to the backend and reads back the token number, telling the citizen whether the confirmation email was also sent.

## Stopping / Exiting

Say any of these at any point to cancel the process: **"روک دیں"**, **"روکیں"**, **"بند کریں"**, **"کینسل"**, **"چھوڑ دیں"**, **"رہنے دیں"**, or the English equivalents **"stop"**, **"cancel"**, **"exit"**, **"quit"**, **"goodbye"**, **"bye"**, **"done"**. The check happens before any field is processed or sent anywhere, so it works mid-flow at any question.

## Notes

- All spoken content is in Urdu; free-form fields (name, address) are transliterated to English right before being sent to the backend, so what the citizen hears never changes.
- Numbers, dates, and CNICs are accepted as spoken digits, spoken number words (English, Urdu, or roman-Urdu), or typed input.
- If the backend is unreachable or times out, the citizen is told the system is temporarily unavailable rather than seeing a raw error.

## Built with

- OpenHome SDK
- CapabilityWorker for voice I/O and API Keys
- Built-in LLM via `text_to_text_response`
- An external Flask backend (source not included in this ability)
