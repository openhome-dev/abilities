# Traffic & Travel Time

Voice-powered traffic and travel time checker using Google Maps Routes API. Check live traffic, get travel times, plan departures, track mid-trip progress, and manage saved locations — all by voice. Auto-detects your approximate location via IP.

## What It Does

| Mode | Example Voice Commands | Description |
|---|---|---|
| **Quick Check** | "How long to work?" / "Traffic to airport" | Saved destination + live traffic |
| **Custom Route** | "How long from Bole to Piassa?" / "From downtown to the beach" | Origin + destination from voice |
| **Commute** | "How's my commute?" / "Commute check" | Home↔work shortcut, auto-detects AM/PM direction |
| **Departure Planner** | "When should I leave to arrive by 6?" | Reverse-calculates leave time for arrival target |
| **Mid-Trip Status** | "How much is left?" / "How much longer?" | Re-checks remaining time on last route |
| **Save Location** | "Save work as Bole, Addis Ababa" | Persists up to 20 named locations |

## Quick Start

### Prerequisites

You need a Google Maps API key. This is a one-time setup (~5 minutes).

### Step 1: Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. **Create a new project** (or use an existing one), e.g., "OpenHome Traffic"
3. **Enable the required APIs**:
   - Go to **APIs & Services → Library**
   - Search and enable each:
     - **Routes API** (required — primary traffic data)
     - **Distance Matrix API** (recommended — fallback)
     - **Geocoding API** (recommended — address validation)
4. **Create an API key**:
   - Go to **APIs & Services → Credentials**
   - Click **+ CREATE CREDENTIALS → API Key**
   - Copy the key (starts with `AIza...`)
   - (Optional) Click **Restrict Key** → select only the 3 APIs above

### Step 2: Configure the Ability

There are two ways to provide your API key:

**Option A: Pre-fill in code (recommended for testing)**

Open `main.py` and replace the placeholder at line 33:

```python
GOOGLE_MAPS_API_KEY = "AIzaSy..."
```

This skips the voice key collection — the ability starts working immediately after onboarding.

**Option B: Voice-guided setup**

Leave the placeholder as-is. On first use, the ability will ask you to paste or speak your API key and store it in preferences.

### Step 3: Upload to OpenHome

1. Go to the **Customize Ability** page
2. Upload all 3 files: `main.py`, `__init__.py`, `README.md`
3. Fill in:
   - **Unique Name**: `traffic_travel_time`
   - **Description**: Voice-powered traffic and travel time checker
   - **Hotwords**: traffic, check traffic, how long to get to, how far is, how long from, from here to, distance from, drive time, travel time, how's my commute, commute check, when should I leave, what time should I leave, save location, how much is left, how much longer, where am I, how long to drive, route to, distance to
4. Click **Start Live Test**

### Step 4: First-Run Onboarding

1. Say **"check traffic"** to trigger the ability
2. If no API key is pre-filled, it asks you to paste/speak your key
3. It validates the key with a test geocode request
4. It asks for your **home address** and **work address** (voice + confirmation)
5. You're set — all future queries work instantly

### Cost

Google Maps provides **$200/month free credit** (~13,000–20,000 requests/month).

| API | Purpose | Cost per request |
|-----|---------|-----------------|
| Routes API (v2) | Primary — live traffic + route details | ~$0.01–0.015 |
| Distance Matrix API | Fallback — simpler duration data | ~$0.01 |
| Geocoding API | API key validation + address cleanup | ~$0.005 |

## Testing Guide

### Full Test Checklist

**First-Run & Setup:**

| # | Say | Expected |
|---|---|---|
| 1 | "check traffic" | Triggers API key setup (if not pre-filled), then onboarding |
| 2 | (provide home address when asked) | Confirms and saves home |
| 3 | (provide work address when asked) | Confirms and saves work |
| 4 | "check traffic" again | Should NOT re-do setup — goes straight to traffic check |

**Quick Check (saved locations):**

| # | Say | Expected |
|---|---|---|
| 5 | "how long to work?" | Live traffic ETA to saved work address |
| 6 | "traffic to home" | Live traffic ETA to saved home address |
| 7 | "how long to airport?" | Asks for address (not saved yet), then gives ETA |

**Custom Route:**

| # | Say | Expected |
|---|---|---|
| 8 | "how long from Bole to Piassa?" | Parses both, confirms, gives ETA with traffic |
| 9 | "from downtown to the beach" | Parses origin/destination from natural language |
| 10 | "distance from home to work" | Resolves saved locations, gives distance + time |

**Commute:**

| # | Say | Expected |
|---|---|---|
| 11 | "how's my commute?" (morning) | Home → work with live traffic |
| 12 | "commute check" (afternoon) | Work → home with live traffic |

**Departure Planner:**

| # | Say | Expected |
|---|---|---|
| 13 | "when should I leave to arrive by 6?" | Asks destination if needed, calculates leave time |
| 14 | "what time should I leave for work?" | Uses saved work, gives departure recommendation |

**Mid-Trip Status:**

| # | Say | Expected |
|---|---|---|
| 15 | (after any route check) "how much is left?" | Re-checks remaining time on last route |
| 16 | "how much longer?" | Same — uses last origin/destination |
| 17 | "how much is left?" (no prior trip) | "I don't have an active trip to check..." |

**Save Locations:**

| # | Say | Expected |
|---|---|---|
| 18 | "save gym as 123 Fitness Ave" | Confirms address, saves location |
| 19 | "how long to gym?" | Uses newly saved location |

**Follow-up & Exit:**

| # | Say | Expected |
|---|---|---|
| 20 | (after any check, wait for "Need another traffic check?") | Ability stays active |
| 21 | "how long to home?" | Works in follow-up without re-triggering |
| 22 | "done" or "stop" | Exits ability cleanly |

**Error Scenarios:**

| # | Say/Do | Expected |
|---|---|---|
| 23 | Use invalid API key | "Your Google Maps API key didn't work..." |
| 24 | Ask for unsaved location | Asks for address or shows saved list |
| 25 | Say gibberish / noise | "I didn't catch that clearly. Try again?" |

## How It Works

### Architecture

```
Voice trigger → run() → load prefs → check API key
  → If no key → handle_api_key_setup() (voice-guided)
  → If no home/work → handle_onboarding() (voice-guided)
  → Auto-detect location from IP (ip-api.com)
  → Classify intent via LLM → Route to handler
  → Execute handler → Speak result (LLM-generated)
  → Follow-up loop ("Need another traffic check?")
  → User says "done" → resume_normal_flow()
```

### Key Technical Details

- **Routes API primary, Distance Matrix fallback**: If Routes API fails, falls back to Distance Matrix automatically
- **IP geolocation**: Auto-detects city-level lat/lon from device IP via `ip-api.com` (free, no key needed)
- **Smart origin resolution**: Tries explicit name → saved place → IP location → ask user
- **LLM address cleanup**: Refines voice-captured addresses (STT errors) before API calls
- **LLM voice responses**: Generates natural spoken traffic reports from real API data
- **Traffic severity**: Classifies as clear/light/moderate/heavy/severe based on traffic vs. baseline ratio
- **Session tracking**: Remembers last origin, destination, and current location for follow-ups
- **STT noise filtering**: Detects non-English fragments and very short gibberish
- **Trigger leak filtering**: Catches trigger phrases leaking into user responses
- **Persistence**: All prefs stored via `capability_worker.write_file()` — no raw `open()` calls

## Important Notes

- **BYOK pattern**: Users provide their own Google Maps API key — no shared keys
- **$200/month free credit**: Enough for ~13,000–20,000 requests/month for personal use
- **IP location accuracy**: City-level only, may be inaccurate on VPNs or cloud-hosted connections
- **Commute direction**: Auto-detects AM (home→work) or PM (work→home) based on current hour
- **API key restriction**: Recommended to restrict your key to only Routes, Distance Matrix, and Geocoding APIs

## Files

| File | Purpose |
|------|---------|
| `main.py` | All ability logic (~1,260 lines) |
| `__init__.py` | Package marker (empty) |
| `README.md` | This file |
| OpenHome dashboard | Unique name + 20 trigger words (platform-managed) |

## API Reference

- [Google Maps Routes API](https://developers.google.com/maps/documentation/routes)
- [Google Maps Distance Matrix API](https://developers.google.com/maps/documentation/distance-matrix)
- [Google Maps Geocoding API](https://developers.google.com/maps/documentation/geocoding)

## Trigger Words

traffic, check traffic, how long to get to, how far is, how long from, from here to, distance from, drive time, travel time, how's my commute, commute check, when should I leave, what time should I leave, save location, how much is left, how much longer, where am I, how long to drive, route to, distance to
