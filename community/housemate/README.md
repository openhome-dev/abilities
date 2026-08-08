# HouseMate

Multilingual voice home assistant for OpenHome.

## Features

- Email named contacts (`dad`, `security`, `doctor`) via Gmail SMTP
- **SOS** one-shot alert emails to security + dad
- Islamabad **time**, **weather** (Open-Meteo), **prayer times** (Aladhan)
- **Daily brief** (time + weather + prayer + memory schedule + reminders)
- Reminders (background daemon)
- Schedule **memory** (`.md` injection — no Google Calendar)
- Voice-updatable contacts (`housemate_contacts.json`)
- Walk-home check-ins
- Optional **companion dashboard** (`companion/`)

## Triggers

`housemate`, `send email`, `sos`, `emergency`, `weather`, `prayer times`, `daily brief`, `brief me`, `remind me`, `what time is it`, `my schedule`, `remember that`, `book a doctor`, `I'm walking home`

## Setup

### Email SMTP

Dashboard → Settings → API Keys:

- `housemate_smtp_email`
- `housemate_smtp_password` (Gmail app password)
- optional `housemate_smtp_host` = `smtp.gmail.com`

Edit default contacts in `main.py` (`DEFAULT_CONTACTS`) or say “change dad’s email…”.

### Companion dashboard (optional)

```bash
pip install flask flask-cors
python companion/app.py
```

Set `DASHBOARD_URL` in `main.py` to your server URL (no trailing slash).

## License

MIT
