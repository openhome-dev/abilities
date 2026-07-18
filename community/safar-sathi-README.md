# Safar Sathi — Setup Guide

A voice-triggered personal safety companion for the OpenHome DevKit.  
Say one word. Everything else is handled automatically.

---

## What happens when you trigger it

1. You say a trigger phrase (see below).
2. **Active mode**: DevKit speaks a calm reassurance. Recording starts.
3. **Passive/Duress mode**: Total silence. Recording starts. No indication at all.
4. Every 15–60 seconds, the background daemon sends your trusted contacts:
   - A Google Maps link with your last known location
   - A playable audio clip of what the microphone was picking up
5. When you say the deactivation phrase, contacts are notified you are safe.

> **On live GPS**: WhatsApp's Business API does not allow a server to
> programmatically trigger a Live Location share — that is a user-tapped
> feature only. Instead, Safar Sathi sends a fresh Google Maps coordinate
> link every cycle. This is the best achievable tracking from the DevKit
> alone. Accuracy is city-level (~1–5 km) based on your home network IP.

---

## 1. Required API Keys

Add these in the OpenHome Dashboard → **Settings → API Keys**:

| Key name | Where to get it |
|---|---|
| `twilio_account_sid` | [Twilio Console](https://console.twilio.com) → Account Info |
| `twilio_auth_token` | [Twilio Console](https://console.twilio.com) → Account Info |
| `twilio_whatsapp_number` | Twilio Console → Messaging → Sandbox number (e.g. `+14155238886`) |

---

## 2. Configure Trusted Contacts

Edit `trusted_contacts` inside your ability's `safar_sathi_state.json`
(see [contacts.md](contacts.md) for format and instructions).

---

## 3. Register Trigger Phrases on the OpenHome Dashboard

Go to **Dashboard → Abilities → Safar Sathi → Trigger Phrases** and add the following:

### Active Triggers → `main.py`
| Phrase | Notes |
|---|---|
| `safar sathi` | Primary invoke phrase |
| `help` | Short, fast panic phrase |
| `emergency` | Explicit emergency |

### Passive / Duress Triggers → `main.py`
These sound normal — safe to say even if someone dangerous is nearby.

| Phrase | Notes |
|---|---|
| `everything is fine` | Sounds like a reassurance; secretly activates |
| `turning off lights` | Sounds like a home routine |
| `going to sleep` | Sounds like a bedtime comment |

### Deactivation Triggers → `main.py`
| Mode | Phrase |
|---|---|
| Active | `I'm safe now` / `I am safe now` / `safe now` |
| Passive | `cancel alert` / `deactivate alert` / `stop alarm` |

---

## 4. Optional: Local Evidence Archival (OpenClaw)

Set `"use_openclaw_storage": true` in `safar_sathi_state.json`.  
Requires the OpenClaw desktop app to be running on the same computer.  
Audio chunks will be saved to `~/SafarSathi_Evidence/` on your hard drive.  
**This is a bonus layer — alerts fire via WhatsApp regardless of OpenClaw status.**

---

## 5. How the two files communicate

The OpenHome SDK does not allow direct calls between ability files.
`main.py` and `background.py` share state through a JSON file in user data storage:

```
main.py  ──writes──▶  safar_sathi_state.json  ◀──reads──  background.py
```

State schema:
```json
{
  "alert_active": true,
  "mode": "active",
  "trusted_contacts": [
    {"name": "Mom", "phone": "+923001234567"}
  ],
  "use_openclaw_storage": false
}
```

---

## 6. Known Limitations

| Feature | Reality |
|---|---|
| Live GPS | Not available via WhatsApp API — periodic Maps-link breadcrumbs are used instead |
| Live video | Not supported — audio recording + upload is the evidence channel |
| WhatsApp "Live Location" pin | User-tapped only, no server API exists to initiate it |
| Audio file expiry | Uploads to temp.sh expire after ~24 hours (fine for demos; use S3/Cloudinary for production) |
