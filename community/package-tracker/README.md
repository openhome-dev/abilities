# Package Tracker

![Community](https://img.shields.io/badge/OpenHome-Community-blue?style=flat-square)

A voice-first package tracker that checks delivery status via direct carrier APIs — FedEx, UPS, USPS, and DHL. Add tracking numbers by voice, check status on all your packages at once, or ask about a specific one by nickname.

## Suggested Trigger Words

**Add tracking:**
- "track a package"
- "track this package"
- "add a tracking number"
- "new tracking"
- "track my order"

**Check status:**
- "any packages coming"
- "package update"
- "package status"
- "where's my package"
- "check my packages"
- "delivery update"

**List / Manage:**
- "how many packages"
- "list my packages"
- "what am I tracking"
- "stop tracking"
- "remove package"

## Setup

Configure the carriers you have credentials for. At least one is required.

**FedEx** (sandbox credentials available at developer.fedex.com):
```python
FEDEX_API_KEY    = "your_key"
FEDEX_SECRET_KEY = "your_secret"
FEDEX_USE_SANDBOX = True   # set False for production
```

**UPS** (CIE test credentials at developer.ups.com):
```python
UPS_CLIENT_ID     = "your_client_id"
UPS_CLIENT_SECRET = "your_secret"
UPS_USE_CIE = True   # set False for production
```

**USPS** (register at registration.shippingapis.com):
```python
USPS_USER_ID = "your_user_id"
```

**DHL** (API key at developer.dhl.com → Shipment Tracking - Unified):
```python
DHL_API_KEY = "your_api_key"
```

## How It Works

1. User triggers the ability with a hotword (e.g., "track a package")
2. The ability detects intent: **add**, **status all**, **status one**, **list**, or **remove**
3. Saved packages are loaded from `pkgtracker_packages.json`
4. Delivered packages older than 2 days are auto-cleaned on startup
5. The appropriate handler runs, calls the carrier API directly, and speaks a brief update
6. Status is saved back to persistent storage after every check

## Key SDK Methods Used

| SDK Method | Purpose |
|---|---|
| `speak()` | Short voice responses |
| `run_io_loop()` | Ask + listen in one step |
| `run_confirmation_loop()` | Yes/no confirmations |
| `text_to_text_response()` | Intent classification, nickname extraction |
| `check_if_file_exists()` / `read_file()` / `write_file()` | Persistent storage |
| `resume_normal_flow()` | Return to Personality — guaranteed via try/finally |
| `editor_logging_handler` | All logging (no print statements) |
