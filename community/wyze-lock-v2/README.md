# WyzeLockAbility

OpenHome ability that controls a Wyze Lock Bolt V2 via voice and optionally WhatsApp (Twilio).

- **`main.py`** — Skill ability. Triggered by hotwords spoken to the Personality. 
- **`background.py`** — Background daemon. Polls Twilio for inbound WhatsApp messages and dispatches the same lock/unlock actions. **Optional.** Skip this whole section if you don't want remote control.

Both share the same Wyze IoT3 client and the same intent rule: `"lock up"` locks, secret password unlocks.

---

## What you need to configure

### 1. Wyze credentials (required, edit both files)

Top of `main.py` and `background.py`:

| Constant | Where to get it |
|---|---|
| `EMAIL` | Your Wyze account email |
| `PASSWORD` | Your Wyze account password |
| `KEY_ID` | https://developer-api-console.wyze.com/#/apikey/view |
| `API_KEY` | Same page — generate an API key |
| `DEVICE_MAC` | Get your lock's MAC address from the Wyze app under Device Info. Format: `DX_LB2_<12 hex chars>` |

### 2. OpenHome dashboard — trigger phrases (required)

The unlock "password" is **the trigger word itself**, configured in the OpenHome ability dashboard. It is *not* stored anywhere in the code or in a file.

Create the ability as **Category: Skill**, then add **two** trigger phrases:

- One that locks: must contain the literal substring `lock up` (e.g. `"lock up"`, `"please lock up"`)
- One that unlocks: anything else you want as your password (e.g. `"open up"`, `"banana"`, `"abracadabra"`)

Dispatch logic in `main.py`:

```python
if "lock up" in text:    # locks
elif text:               # anything else unlocks
```

Pick a unique unlock phrase.

### 3. Twilio (optional — only for `background.py`)

Skip if you don't want WhatsApp control.

Top of `background.py`:

| Constant | Where to get it |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio Console home (`AC...`) |
| `TWILIO_AUTH_TOKEN` | Twilio Console home (click "Show") |
| `TWILIO_SANDBOX_WHATSAPP` | Console → Messaging → Try it out → WhatsApp. Format: `whatsapp:+14155238886` |
| `ALLOWED_WHATSAPP_SENDER` | Your own WhatsApp number in E.164. Format: `whatsapp:+15551234567` |

Then opt your phone into the sandbox: send `join <two-words>` from your WhatsApp to the sandbox number (the join phrase is shown in the Twilio console).

### 4. WhatsApp passwords — `lockpreferences.json` (optional — only for `background.py)

`background.py` reads two passwords from `lockpreferences.json` in the ability bundle:

```json
{
  "unlock_password": "open up",
  "lock_password": "lock up"
}
```

- A WhatsApp message containing `lock_password` (substring, case-insensitive) → locks
- A message containing `unlock_password` → unlocks
- Anything else → silently ignored (no reply — don't tip off anyone probing)

Edit the JSON, re-upload the ability, and the daemon picks up the new passwords on next session start. If the file is missing, malformed, or a field is empty, defaults (`"open up"` / `"lock up"`) are used and a fallback is logged.

**Security**: defense in depth is the allowlist (`ALLOWED_WHATSAPP_SENDER`) **plus** the password. Either alone is weak — sandbox numbers are public-ish and substrings are guessable — but together they're reasonable for a personal trial setup. Don't reuse a password you care about.

---

## Usage

### Voice (`main.py`)
Speak one of your configured trigger phrases. The ability will:
1. Capture the trigger via `wait_for_complete_transcription()`
2. Check current lock state (skip if already in target state)
3. Lock or unlock the Wyze
4. Speak confirmation: *"Door unlocked."* / *"Door locked."*

### WhatsApp (`background.py`, optional)
Text the Twilio sandbox number from your allowlisted WhatsApp:
- `lock up` → locks
- {json password} → unlocks

You'll get a confirmation reply (*"Door unlocked."* etc.). Polls every 10s while a session is active. **No session = no polling.**

---

## Limits / things to know

- **Twilio sandbox** expires after 72h of inactivity. Re-send the `join <code>` to renew. Production WhatsApp Business needed for permanent use.
- **Wyze IoT3 API** uses an undocumented signing scheme. If Wyze changes it, both files break the same way. Check https://github.com/SecKatie/ha-wyzeapi for the latest on Wyze API hacking. Code for WyzeLockClient was based on an unmerged PR giving support for the Wyze Lock Bolt v2. 
