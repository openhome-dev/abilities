# Traffic & Travel Time

Voice-powered traffic and travel time checker using Google Maps Routes API. Check live traffic, get travel times, plan departures, track mid-trip progress, and manage saved locations — all by voice. Auto-detects your approximate location via IP.

## Features

- **Quick Check** — "How long to work?" uses saved locations + live traffic
- **Custom Route** — "How long from Bole to Piassa?" parses origin/destination from voice
- **Commute Check** — "How's my commute?" auto-detects direction by time of day
- **Departure Planner** — "When should I leave to arrive by 6?" reverse-calculates leave time
- **Mid-Trip Status** — "How much is left?" re-checks remaining time on your last route
- **Save Locations** — "Save work as 456 Corporate Dr" persists up to 20 named locations
- **IP Geolocation** — auto-detects your city-level location as default origin
- **Traffic Severity** — clear / light / moderate / heavy / severe classifications
- **Session Tracking** — remembers your last origin/destination for follow-up queries
- **First-Run Onboarding** — guides user through home/work address setup

---

## Google Maps API Key Setup

You need a Google Maps API key to use this ability. Follow these steps:

### Step 1: Create a Google Cloud Project
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top → **New Project**
3. Give it a name (e.g. "OpenHome Traffic") → **Create**
4. Make sure the new project is selected in the dropdown

### Step 2: Enable Required APIs
1. Go to **APIs & Services** → **Library**
2. Search for and enable each of these:
   - **Routes API** (required — primary traffic data)
   - **Distance Matrix API** (recommended — fallback)
   - **Geocoding API** (recommended — address validation)

### Step 3: Create an API Key
1. Go to **APIs & Services** → **Credentials**
2. Click **+ CREATE CREDENTIALS** → **API Key**
3. Copy the key (starts with `AIza...`)
4. (Optional but recommended) Click **Restrict Key** → under **API restrictions**, select only the 3 APIs above

### Step 4: Set the Environment Variable
Set the `GOOGLE_MAPS_API_KEY` environment variable so the ability can read it:

**macOS / Linux (terminal):**
```bash
export GOOGLE_MAPS_API_KEY="AIzaSy..."
```

**To make it permanent, add to your shell profile:**
```bash
echo 'export GOOGLE_MAPS_API_KEY="AIzaSy..."' >> ~/.zshrc
source ~/.zshrc
```

**Windows (PowerShell):**
```powershell
$env:GOOGLE_MAPS_API_KEY = "AIzaSy..."
```

**Alternative: Voice Setup**
If no environment variable is set, the ability will ask you to paste or speak your API key on first use and store it in preferences.

### Cost
Google Maps provides **$200/month free credit** (~13,000–20,000 requests/month).

| API | Purpose | Cost per request |
|-----|---------|-----------------|
| Routes API (v2) | Primary — live traffic + route details | ~$0.01–0.015 |
| Distance Matrix API | Fallback — simpler duration data | ~$0.01 |
| Geocoding API | API key validation + address cleanup | ~$0.005 |

---

## Trigger Words (max 20)

```
traffic, check traffic, how long to get to, how far is,
how long from, from here to, distance from, drive time,
travel time, how's my commute, commute check,
when should I leave, what time should I leave, save location,
how much is left, how much longer, where am I,
how long to drive, route to, distance to
```

---

## Usage Examples

| Say this | What happens |
|----------|-------------|
| "Check traffic" | Asks what you'd like to check |
| "How long to work?" | Quick check to saved work address |
| "How long from Bole to Piassa?" | Custom route with real-time ETA |
| "How's my commute?" | Home→work (AM) or work→home (PM) |
| "When should I leave to arrive by 6?" | Calculates departure time |
| "How much is left?" | Re-checks remaining time on last route |
| "Where am I?" | Shows detected location from IP |
| "Save work as Bole, Addis Ababa" | Saves a named location |
| "Done" | Exits the ability |

---

## How It Works

1. **Trigger** — user says a trigger phrase, ability activates
2. **IP Geolocation** — detects approximate city from device IP via `ip-api.com`
3. **Intent Classification** — LLM classifies into one of 6 modes
4. **Origin Resolution** — tries: explicit name → saved place → IP location → ask user
5. **Google Maps API** — calls Routes API (primary) or Distance Matrix (fallback)
6. **Voice Response** — LLM generates natural spoken response with real data
7. **Follow-up Loop** — stays active for more queries until user says "done"

## Files

| File | Purpose |
|------|---------|
| `main.py` | All ability logic (~1,260 lines) |
| `config.json` | Unique name + 20 trigger words |
| `__init__.py` | Package marker (empty) |
| `README.md` | This file |

## Data Storage

Single persistent file: `traffic_prefs.json` stored per-user via OpenHome SDK. Contains API key, saved locations, and preferences. Uses delete-then-write pattern.

## Architecture

- **BYOK** (Bring Your Own Key) — user's own Google Maps API key via env var or voice setup
- **IP Geolocation** — `ip-api.com` for city-level lat/lon from device IP
- **Session Tracking** — remembers last origin, destination, and current location across turns
- **LLM Intent Classification** — routes to correct handler based on natural language
- **LLM Address Cleanup** — refines voice-captured addresses before API calls
- **LLM Voice Responses** — generates natural spoken traffic reports from real data
- **STT Noise Filtering** — detects and handles non-English fragments from speech-to-text
- **Trigger Leak Filtering** — catches trigger phrases leaking into user responses
- **`resume_normal_flow()`** on every exit path
