# Nest Thermostat

Voice control your Google Nest Thermostat through OpenHome. Check the temperature, set targets, change modes, toggle eco mode, and control the fan — all by voice.

---

## What It Does

| Voice Command | What Happens |
|---|---|
| "What's the temperature?" | Reads current temp, humidity, mode, and HVAC status |
| "Set it to 72" | Sets the target temperature |
| "Turn it up" / "Turn it down" | Adjusts setpoint by 2 degrees |
| "Switch to heat" / "Turn on the AC" | Changes thermostat mode |
| "Turn on eco mode" | Enables energy-saving eco mode |
| "Turn off eco mode" | Restores previous mode |
| "Turn on the fan" | Runs fan for 15 minutes (default) |
| "Run the fan for an hour" | Runs fan with timer |
| "Turn off the fan" | Stops fan |

---

## Supported Devices

- Nest Thermostat (2020)
- Nest Thermostat E
- Nest Learning Thermostat (all generations)

**Not supported:** Nest Protect, Nest Secure, Nest Temperature Sensors, legacy Nest accounts, Google Workspace accounts.

---

## Setup

This ability uses the [Google Smart Device Management (SDM) API](https://developers.google.com/nest/device-access). Setup requires a **one-time $5 fee** to Google for Device Access registration.

### Prerequisites

1. A Google account with a Nest thermostat set up in the Google Home app
2. A consumer Gmail account (Google Workspace accounts are not supported)

### Step 1 — Register for Device Access ($5)

Go to [console.nest.google.com/device-access](https://console.nest.google.com/device-access), accept the Terms of Service, and pay the one-time fee. This is a Google requirement — not refundable.

### Step 2 — Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Enable the **Smart Device Management API** under APIs & Services → Library

### Step 3 — Create OAuth 2.0 Credentials

1. Go to APIs & Services → Credentials → Create Credentials → OAuth client ID
2. Application type: **Web application**
3. Add `https://www.google.com` as an Authorized Redirect URI
4. Copy your **Client ID** and **Client Secret**

### Step 4 — Set OAuth Consent Screen to Production

Go to APIs & Services → OAuth consent screen → set Publishing Status to **Production**. This prevents your login token from expiring after 7 days. No Google review is required for personal use.

### Step 5 — Create a Device Access Project

1. Go back to [console.nest.google.com/device-access](https://console.nest.google.com/device-access)
2. Create a new project, enter your OAuth Client ID
3. Skip Pub/Sub events
4. Copy your **Device Access Project ID** (a UUID)

### Step 6 — Activate in OpenHome

Say "thermostat" or "what's the temperature" — the ability will walk you through connecting your account, authorizing access, and discovering your thermostat automatically.

---

## Trigger Words

```
nest, thermostat, temperature, how warm, how cold,
set it to, set the temperature, turn up, turn down,
switch to heat, switch to cool, turn on the heat,
turn on the AC, turn off the thermostat, eco mode,
turn on eco, turn off eco, turn on the fan, fan on,
fan off, is the heat on, is the AC on
```

---

## Credentials Stored

This ability stores credentials in `nest_thermostat_prefs.json` on your device:

- OAuth Client ID and Client Secret
- Access token and refresh token
- Device Access Project ID
- Thermostat device ID and configuration

Credentials are never transmitted to OpenHome servers — they stay on your device.

---

## Notes

- **All API temperatures are Celsius.** The ability converts to Fahrenheit automatically based on your thermostat's settings.
- **Eco mode blocks temperature changes.** If eco mode is on, you'll be asked to turn it off before setting a temperature.
- **Fan control** requires a thermostat model that supports it. The ability checks automatically.
- **Multiple thermostats:** V1 controls your first thermostat. Multi-thermostat support is planned for V2.

---

## Development (Mock Mode)

For development without a real device, set `MOCK_MODE = True` at the top of `main.py`. All API calls will use simulated data. The mock state is mutable — setting a temperature updates the mock so subsequent reads reflect the change.

---

## Author

Community contribution. See [CONTRIBUTING.md](../../CONTRIBUTING.md) for details.
