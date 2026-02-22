# Pet Care Assistant
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@megz2020-lightgrey?style=flat-square)

## What It Does

A voice-first assistant for managing your pets' daily lives. Track feeding, medications, walks, weight changes, and vet visits. Get emergency vet locations, weather safety alerts, food recall notifications, and set reminders — all through natural voice commands.

**Why This is an Ability (Not Just LLM Chat):**
- **Persists data** across sessions (pet profiles, activity logs, reminders)
- **Calls external APIs** for real-time info (weather, vets, recalls)
- **Tracks changes over time** (weight trends, medication schedules)
- **Multi-pet management** with automatic name resolution

---

## Architecture

All logic lives in a single `main.py` file, following the OpenHome Ability pattern.

```
                    User Voice Input
                          |
                    OpenHome STT
                          |
                    ┌─────▼──────────────────────────────────────────┐
                    │                   main.py                      │
                    │                                                 │
                    │  ┌─────────────────────────────────────────┐   │
                    │  │       PetCareAssistantCapability         │   │
                    │  │  - call() → session_tasks.create(run())  │   │
                    │  │  - run() → intent router                 │   │
                    │  │  - _handle_log / _handle_weather / etc.  │   │
                    │  └─────────────────────────────────────────┘   │
                    │                                                 │
                    │  Helper classes (inlined):                      │
                    │  ┌─────────────┐  ┌─────────────────────────┐  │
                    │  │ LLMService  │  │     PetDataService       │  │
                    │  │ - classify  │  │ - load/save JSON         │  │
                    │  │   intent    │  │ - resolve pet name       │  │
                    │  │ - extract   │  │ - fuzzy match            │  │
                    │  │   values    │  └─────────────────────────┘  │
                    │  │ - is_exit   │                                │
                    │  └─────────────┘  ┌─────────────────────────┐  │
                    │                   │   ActivityLogService     │  │
                    │  ┌─────────────┐  │ - add entry             │  │
                    │  │ExternalAPI  │  │ - filter/query          │  │
                    │  │Service      │  │ - enforce size limit    │  │
                    │  │ - weather   │  └─────────────────────────┘  │
                    │  │ - vet search│                                │
                    │  │ - recalls   │                                │
                    │  │ - geocoding │                                │
                    │  └─────────────┘                                │
                    └─────────────────────────────────────────────────┘
                                        │
              ┌─────────────────────────┼──────────────────────────┐
              ▼                         ▼                          ▼
    google.serper.dev/maps     api.open-meteo.com           api.fda.gov
    google.serper.dev/news     geocoding-api.open-meteo.com ip-api.com

    Persistent Storage (JSON files on OpenHome server):
    ┌──────────────────────┐  ┌────────────────────────┐  ┌──────────────────────┐
    │ petcare_pets.json    │  │petcare_activity_log    │  │petcare_reminders     │
    │                      │  │.json                   │  │.json                 │
    │ - Pet profiles       │  │                        │  │                      │
    │ - Vet info           │  │ - Activity entries     │  │ - Reminder entries   │
    │ - Location (lat/lon) │  │ - Capped at 500        │  │ - due_at timestamp   │
    └──────────────────────┘  └────────────────────────┘  └──────────────────────┘
```

### Data Flow

1. User speaks → OpenHome STT converts to text
2. `main.py` checks for exit intent (3-tier fast check, then LLM fallback)
3. `LLMService.classify_intent_async()` identifies the mode (log, lookup, vet, weather, etc.)
4. `main.py` routes to the appropriate handler (`_handle_log`, `_handle_weather`, etc.)
5. Handlers call `ExternalAPIService` for live data (non-blocking via `asyncio.to_thread`)
6. Results are saved via `PetDataService` (backup-write-delete pattern for data safety)
7. OpenHome TTS speaks the response

---

## Suggested Trigger Words

### Activity Logging
- "I fed [pet name]"
- "[Pet] got her medicine"
- "we walked for 30 minutes"
- "[Pet] weighs 48 pounds"
- "log pet activity"

### Quick Lookups
- "when did I last feed [pet]"
- "has [pet] had heartworm pill this month"
- "how many walks this week"
- "last vet visit"

### Emergency Vet Finder
- "emergency vet"
- "find a vet near me"
- "I need a vet"

### Weather Safety
- "is it safe outside for [pet]"
- "can I walk my dog"
- "too hot for [pet]"

### Food Recalls
- "pet food recall"
- "is my dog food safe"
- "any food recalls"

### Reminders
- "remind me to feed Luna in 2 hours"
- "set a reminder for Max's medication at 8 PM"
- "what reminders do I have"
- "delete reminder"

### Profile Management
- "add a new pet"
- "update pet info"
- "change my vet"
- "remove pet"
- "start over" / "reset everything" / "delete everything"

---

## Setup

### Step 1: Add Ability to OpenHome
1. Go to your OpenHome Dashboard
2. Navigate to **Abilities** section
3. Find **Pet Care Assistant** in the community library
4. Click **Add to Personality**

### Step 2: Configure Serper API Key (Optional but Recommended)
The emergency vet finder and food recall news headlines require a Serper API key.

1. Go to [serper.dev](https://serper.dev) and sign up
2. Copy your API key (2,500 free queries included)
3. At the top of `main.py`, find:
   ```python
   SERPER_API_KEY = "your_serper_api_key_here"
   ```
4. Replace with your actual key

**Note:** Without the key, emergency vet search shows only your saved vet, and news headlines are skipped. Weather checks and FDA recall data work without a key.

### Step 3: First-Time Onboarding
On first activation, the assistant walks you through setup via voice:
1. Say any trigger phrase (e.g., "I fed my dog")
2. Follow the voice prompts to add your first pet (name, species, breed, age, weight, allergies, medications, vet, location)
3. Add additional pets when prompted (optional)

---

## Features

### 1. Activity Logging
Log feeding, medication, walks, weight, vet visits, grooming, or any custom activity.

**Example:**
> **User:** "I just fed Luna"
> **AI:** "Got it. Logged Luna's feeding at 8:30 AM. Anything else to log?"

### 2. Quick Lookups
Ask questions about your pet's history — the AI searches the activity log and answers in natural language.

**Example:**
> **User:** "When did I last feed Luna?"
> **AI:** "You fed Luna this morning at 8:30 AM."

### 3. Weight Tracking
Weight entries are stored separately and summarized with trends.

**Example:**
> **User:** "How much has Luna's weight changed?"
> **AI:** "Luna is at 62 pounds. She's lost 3 pounds since February, trending down gradually."

### 4. Emergency Vet Finder
Shows your saved regular vet first, then searches nearby emergency vets via Serper Maps API.

- Prioritizes currently open locations
- Reads vet **names first** (short, interruptible), then asks which one you want details for
- Speaks phone number digit-by-digit (easy to write down)

**Example:**
> **User:** "Find an emergency vet"
> **AI:** "Your regular vet is Dr. Smith at 5, 1, 2, ..."
> **AI:** "I found 3 nearby vets: Austin Vet Emergency, BluePearl Pet Hospital, VCA Animal Hospital. Which one do you want the number for?"
> **User:** "Austin Vet"
> **AI:** "Austin Vet Emergency, open now, rated 4.5. Number: 5, 1, 2, ..."

### 5. Weather Safety Check
Fetches current conditions from Open-Meteo (free, no key required) and assesses safety for your specific pet's breed.

Safety thresholds applied:
- **>100°F:** Danger (heatstroke risk, stay indoors)
- **>90°F:** Warning (hot pavement, bring water)
- **<20°F:** Danger (too cold for more than a few minutes)
- **<32°F:** Warning for short-haired breeds
- **Wind >30 mph:** Caution for small pets
- **UV >7:** Caution for light-colored/short-haired dogs

### 6. Food Recall Checker
Runs openFDA adverse event queries and Serper News searches **in parallel** for performance.

**Example:**
> **User:** "Any pet food recalls?"
> **AI:** "Let me check for recent pet food alerts."
> **AI:** "I found 2 recent FDA adverse event reports for dogs, involving Acme Dog Food. These are general reports, not necessarily recalls."

### 7. Reminders
Set time-based reminders using natural language — no external service needed (Python `datetime` only).

**Supported time formats:**
- "in 2 hours" / "in 30 minutes"
- "at 6 PM" / "at 18:00"
- "tomorrow at 8 AM"

**Example:**
> **User:** "Remind me to give Luna her medication in 2 hours"
> **AI:** "Got it. I'll remind you Thursday at 10:30 AM: Reminder for Luna: medication."

Reminders are announced at startup if they're due or overdue.

### 8. Reset / Start Over
Wipe all data and start fresh with a new onboarding session.

> **User:** "Start over" / "Reset everything" / "Delete everything"
> **AI:** "This will delete all pets, activity logs, and reminders — a completely fresh start. Say yes to confirm."

### 9. Multi-Pet Support
- One pet: AI always uses it (no need to say name)
- Multiple pets: AI asks "Which pet? Luna or Max?" if the name isn't mentioned
- Fuzzy name matching handles typos and abbreviations

---

## Services & APIs

| Service | Purpose | Authentication | Cost |
|---------|---------|----------------|------|
| **Serper Maps** | Emergency vet search | API key (user provides) | 2,500 free, then pay-per-use |
| **Serper News** | Food recall headlines | Same key | Same |
| **Open-Meteo** | Weather data | None | Free |
| **ip-api.com** | Auto-detect location from IP | None | Free (45 req/min) |
| **openFDA** | Pet food adverse events | None | Free |
| **OpenHome LLM** | Intent classification, data extraction | Built-in | Free (included) |
| **OpenHome File Storage** | Pet profiles, activity logs, reminders | Built-in | Free (included) |

---

## Data Model

### Pet Profile (`petcare_pets.json`)
```json
{
  "pets": [
    {
      "id": "pet_a1b2c3",
      "name": "Luna",
      "species": "dog",
      "breed": "Golden Retriever",
      "birthday": "2021-03-15",
      "weight_lbs": 65,
      "allergies": [],
      "medications": [{ "name": "Heartgard", "frequency": "monthly" }]
    }
  ],
  "vet_name": "Dr. Smith",
  "vet_phone": "5125551234",
  "user_location": "Austin, Texas",
  "user_lat": 30.2672,
  "user_lon": -97.7431
}
```

### Activity Log (`petcare_activity_log.json`)
```json
[
  {
    "id": "log_d4e5f6",
    "pet_id": "pet_a1b2c3",
    "pet_name": "Luna",
    "type": "feeding",
    "details": "breakfast",
    "timestamp": "2024-03-15T08:30:00"
  },
  {
    "id": "log_g7h8i9",
    "pet_id": "pet_a1b2c3",
    "pet_name": "Luna",
    "type": "weight",
    "details": "65 lbs",
    "value": 65,
    "timestamp": "2024-03-15T09:00:00"
  }
]
```

### Reminders (`petcare_reminders.json`)
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "pet_name": "Luna",
    "activity": "medication",
    "message": "Reminder for Luna: medication.",
    "due_at": "2024-03-15T18:00:00",
    "created_at": "2024-03-15T10:00:00"
  }
]
```

---

## Technical Notes

### Single-File Architecture
All logic — including helper classes (`ActivityLogService`, `PetDataService`, `LLMService`, `ExternalAPIService`) — is inlined directly into `main.py`. This follows the OpenHome platform requirement that only `main.py` is loaded; sibling module imports are not supported.

### Parallel LLM Extraction
Onboarding collects all raw user answers first (Phase 1), then extracts all values in a single `asyncio.gather()` call (Phase 2). This reduces onboarding from ~30 seconds to ~3-4 seconds.

### Non-blocking API Calls
All external HTTP calls use `asyncio.to_thread(requests.get/post, ...)` to avoid blocking the event loop. This allows exit commands to be detected between API calls.

### Backup-Write-Delete Safety
All JSON saves use a backup-before-write pattern:
1. Copy existing file to `*.backup`
2. Write new data
3. Delete backup on success (backup retained on failure for manual recovery)

### Exit Detection (4 tiers)
1. **Force-exit phrases** — "exit petcare", "close petcare" (instant, phrase match)
2. **Exit commands** — "stop", "quit", "exit", "cancel" (word-boundary match)
3. **Exit responses** — "no", "done", "bye", "no thanks" (prefix match)
4. **LLM fallback** — short ambiguous inputs (≤4 words) sent to LLM classifier

### Voice-Friendly Phone Numbers
Numbers are spoken digit-by-digit: `5125551234` → "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"

---

## Troubleshooting

**"I don't have any pets set up yet"**
Say "add a new pet" to start setup manually.

**Emergency vet search returns no results**
1. No Serper API key configured — add one in `main.py`
2. Location not detected — say "update my location" to set your city

**Weather check fails**
Say "update my location" to set your city, then try again.

**"Which pet?" asked every time**
Include the pet name in your command: "I fed Luna" not "I fed my dog".

**Reminder not announced**
Reminders fire at ability startup. If the ability wasn't running when the reminder was due, it will announce on next startup.

---

## Privacy & Security

- All data stored **locally** in JSON files on your OpenHome server
- No personal data sent to third parties — only coordinates to weather/vet APIs, IP to ip-api.com, and species to FDA
- Delete all data by saying "start over" and confirming, or manually removing the three `petcare_*.json` files
