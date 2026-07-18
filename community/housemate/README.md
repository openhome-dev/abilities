# HouseMate

Multilingual voice home assistant for OpenHome. Email contacts, Islamabad time, reminders, schedule memory (replaces calendar), doctor plans, and walk-home check-ins.

## What it does

- Send email to named contacts (`dad`, `security`, `doctor`) via Gmail SMTP app password
- Tell current time in Islamabad (`Asia/Karachi`)
- Set / list / clear voice reminders (background daemon)
- Remember schedule plans in Agent memory (`.md` + JSON) — no Google Calendar required
- Book doctor visits into memory + reminder + optional email
- Wikipedia / LLM lookups and general home Q&A
- Walk-home safety check-in mode
- Replies in the same language you speak (English, Urdu, Roman Urdu, mixed, …)

## Trigger phrases

- `housemate`
- `hey housemate`
- `send email` / `email dad` / `email security` / `email doctor`
- `remind me` / `set a reminder`
- `what time is it` / `current time` / `time in islamabad`
- `my schedule` / `what's planned` / `remember that`
- `book a doctor`
- `look up`
- `I'm walking home`

## Setup

### 1. Contacts

Edit the `CONTACTS` dict at the top of `main.py` with your household emails.

### 2. Email (SMTP)

Create a Gmail [App Password](https://myaccount.google.com/apppasswords), then in OpenHome:

1. Dashboard → **Settings → API Keys**
2. Add:
   - `housemate_smtp_email` = your Gmail address
   - `housemate_smtp_password` = the 16-character app password (no spaces)
   - optional `housemate_smtp_host` = `smtp.gmail.com`

Do **not** hardcode secrets in source.

### 3. Install

Upload / install this Ability, assign it to an Agent, enable it, then say **housemate**.

## Files

| File | Role |
|------|------|
| `main.py` | Interactive skill |
| `background.py` | Reminder + walk-home watcher |
| `config.json` | Triggers / metadata |
| `__init__.py` | Package marker |

## Notes

- After a successful send, HouseMate speaks a plain confirmation (no LLM rewrite) so the Agent cannot falsely say “I can’t send email.”
- Schedule memory writes `housemate_schedule.md` for Agent context injection.

## License

MIT
