# WhatsApp Messenger

A voice-controlled WhatsApp messaging ability for OpenHome. Just say who you want to message and what to say — the ability handles the rest.

## Features

- **Voice-to-message** — say the recipient name and message in one natural sentence; the ability extracts both and sends
- **Contact lookup** — resolves names to numbers from a local contacts file at `~/.openclaw/wa-contacts.json`
- **Auto-learn contacts** — if a contact is unknown, asks for their number once and saves it automatically for next time
- **Non-Latin name support** — handles names spoken in any script (e.g. Urdu, Arabic) by romanizing before lookup
- **Smart fallbacks** — if recipient or message is unclear from voice, asks follow-up questions to fill in the gaps

## Requirements

- OpenClaw installed and running with WhatsApp channel connected
- WhatsApp linked via `openclaw channels login --channel whatsapp`
- OpenClaw gateway running (`openclaw gateway start`)
- DM policy set to `open` in `~/.openclaw/openclaw.json`:

```json
{
  "channels": {
    "whatsapp": {
      "dmPolicy": "open",
      "allowFrom": ["*"]
    }
  }
}
```

## Contacts File

Store contacts at `~/.openclaw/wa-contacts.json`:

```json
{
  "mom": "+11234567890",
  "ali": "+923001234567"
}
```

Unknown contacts are asked for once and saved automatically.

## Usage

Trigger the ability by voice, then say something like:

- *"Message Ali, I'll be there in 10 minutes"*
- *"Send a WhatsApp to Mom saying happy birthday"*
- *"Text plus 923001234567 are you free tonight"*
