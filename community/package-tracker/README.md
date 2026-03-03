# Package Tracker

![Community](https://img.shields.io/badge/OpenHome-Community-blue?style=flat-square)

A voice-first package tracker that checks delivery status via direct carrier APIs — FedEx, UPS, USPS, and DHL. Add tracking numbers by voice, check status on all your packages at once, or ask about a specific one by nickname.

> **Tested & working:** FedEx sandbox. UPS and DHL require the developer to apply for API access separately (see notes below).

## Trigger Words

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

---

### FedEx ✅ Tested in sandbox

1. Go to [developer.fedex.com](https://developer.fedex.com) → My Apps → create an app with the **Track API** scope.
2. Copy your API key and secret key into `main.py`:

```python
FEDEX_API_KEY    = "your_api_key"
FEDEX_SECRET_KEY = "your_secret_key"
FEDEX_USE_SANDBOX = True   # set False for production
```

Sandbox test tracking numbers:
| Number | Expected status |
|---|---|
| `122816215025810` | Delivered |
| `231300687629630` | Out for delivery |
| `039813852990618` | In transit |
| `843119172384577` | Held |
| `076288115212522` | Returned |
| `070358180009382` | Cancelled |

---

### UPS ⚠️ Developer must apply for access

UPS requires account verification (including card details) before issuing API credentials. The verification flow may return an "invalid user" error depending on your account setup. Apply at [developer.ups.com](https://developer.ups.com) → Add App → Track product.

Once you have credentials:

```python
UPS_CLIENT_ID     = "your_client_id"
UPS_CLIENT_SECRET = "your_client_secret"
UPS_USE_CIE = True   # set False for production
```

CIE test tracking numbers: `1ZCIETST0111111114`, `1ZCIETST0422222228`

---

### USPS

Register at [registration.shippingapis.com](https://registration.shippingapis.com/).

```python
USPS_USER_ID = "your_user_id"
```

USPS has no sandbox — the same endpoint handles all requests.

---

### DHL ⚠️ Developer must apply for access

DHL API access requests go through a manual review and may be cancelled or delayed. Apply at [developer.dhl.com](https://developer.dhl.com) → Shipment Tracking - Unified.

Once approved:

```python
DHL_API_KEY = "your_api_key"
```

---

## How It Works

1. User triggers the ability with a hotword (e.g., "track a package")
2. The ability detects intent: **add**, **status all**, **status one**, **list**, or **remove**
3. Saved packages are loaded from `pkgtracker_packages.json`
4. Delivered packages older than 2 days are auto-cleaned on startup
5. The appropriate handler runs, calls the carrier API directly, and speaks a brief update
6. Status is saved back to persistent storage after every check

When adding a package, the ability auto-detects the carrier from the tracking number format. If detection is confident and that carrier is configured, it asks the user to confirm. If the detected carrier isn't configured, it says so immediately rather than wasting the user's time.

## Example Conversation

> **User:** "Track a package"
> **AI:** "Package tracker. Are you adding a new tracking number?"
> **User:** "Yes"
> **AI:** "Please say your tracking number now, or type it in the chat."
> **User:** "1 2 2 8 1 6 2 1 5 0 2 5 8 1 0"
> **AI:** "I got: one, two, two, eight... Say yes to confirm, or no to enter it again."
> **User:** "Yes"
> **AI:** "This looks like a FedEx tracking number. Is that right?"
> **User:** "Yes"
> **AI:** "What should I call this package?"
> **User:** "Birthday gift"
> **AI:** "Checking with FedEx now."
> **AI:** "Got it. I'm now tracking your Birthday gift via FedEx. Your package was delivered."

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
