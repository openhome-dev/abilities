# Pet Care Assistant
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@megz2020-lightgrey?style=flat-square)

## What It Does
A comprehensive voice-first assistant for managing your pets' daily lives. Track feeding, medications, walks, weight changes, vet visits, and more — all through natural voice commands. Get emergency vet locations, weather safety alerts, and food recall notifications.

**Why This is an Ability (Not Just LLM Chat):**
- ✅ **Persists data** across sessions (pet profiles, activity logs)
- ✅ **Calls external APIs** for real-time info (weather, vets, recalls)
- ✅ **Tracks changes over time** (weight trends, medication schedules)
- ✅ **Multi-pet management** with automatic name resolution

## Suggested Trigger Words

### Activity Logging
- "I fed [pet name]"
- "I just fed [pet]"
- "[Pet] ate breakfast"
- "[Pet] got her medicine"
- "gave [pet] medication"
- "we walked for 30 minutes"
- "[Pet] weighs 48 pounds"
- "log pet activity"

### Quick Lookups
- "when did I last feed [pet]"
- "has [pet] had heartworm pill this month"
- "how many walks this week"
- "last vet visit"
- "check on [pet]"

### Emergency Vet Finder
- "emergency vet"
- "find a vet near me"
- "I need a vet"

### Weather Safety
- "is it safe outside for [pet]"
- "pet weather check"
- "can I walk my dog"
- "too hot for [pet]"

### Food Recalls
- "pet food recall"
- "is my dog food safe"
- "any food recalls"

### Profile Management
- "add a new pet"
- "update pet info"
- "change my vet"
- "remove pet"

## Setup

### Step 1: Add Ability to OpenHome
1. Go to your [OpenHome Dashboard](https://app.openhome.com/dashboard)
2. Navigate to **Abilities** section
3. Find **Pet Care Assistant** in the community library
4. Click **Add to Personality**

### Step 2: Configure API Key (Optional but Recommended)
The emergency vet finder requires a Google Places API key:

1. **Get Google Places API Key:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project (or select existing)
   - Enable **Places API (New)**
   - Go to **Credentials** → **Create Credentials** → **API Key**
   - Copy your API key

2. **Add Key to Code:**
   - Open `main.py` in the ability
   - Find line: `GOOGLE_PLACES_API_KEY = "your_google_places_api_key_here"`
   - Replace with: `GOOGLE_PLACES_API_KEY = "YOUR_ACTUAL_KEY_HERE"`

**Note:** If you skip this step, emergency vet search will fall back to showing your saved vet info instead.

### Step 3: First-Time Onboarding
On first activation, the ability will walk you through setup via voice:

1. Say any trigger phrase (e.g., "I fed my dog")
2. The assistant will detect it's your first time
3. Follow the voice prompts to add your first pet:
   - Pet's name
   - Species (dog, cat, etc.)
   - Breed
   - Age or birthday
   - Weight
   - Allergies (if any)
   - Medications (if any)
   - Regular vet info (optional)
   - Your location (for weather & vet search)

4. Add additional pets when prompted (optional)
5. Setup complete! You can now start logging activities.

## How It Works

### First-Time Users
1. Trigger the ability with any pet-related command
2. Guided voice onboarding collects pet profiles
3. Data saved to persistent JSON files
4. Ready to use immediately after setup

### Returning Users
1. Trigger phrase is analyzed by AI to determine intent
2. **Quick Mode:** If intent is clear (e.g., "I fed Luna"), executes and offers one follow-up
3. **Full Mode:** If vague (e.g., "pet care"), enters multi-turn conversation loop
4. Idle detection exits gracefully after 2 empty responses

### Data Storage
Two JSON files store all your data:
- `petcare_pets.json` — Pet profiles, vet info, user location
- `petcare_activity_log.json` — Activity entries (capped at 500, auto-trims oldest)

## Features Breakdown

### 1. Activity Logging
**What you can log:**
- **Feeding:** "I just fed Luna"
- **Medication:** "Luna got her flea medicine"
- **Walks:** "We walked for 30 minutes"
- **Weight:** "Luna weighs 48 pounds now"
- **Vet visits:** "Luna went to the vet today"
- **Grooming:** "Luna got a bath"
- **Other:** Any custom activity

**How it works:**
1. AI extracts pet name, activity type, and details from voice
2. Timestamps the entry automatically
3. Saves to activity log
4. Confirms with brief spoken response
5. Offers quick re-log: "Anything else to log?"

### 2. Quick Lookups
**Ask questions like:**
- "When did I last feed Luna?"
- "Has Max had his heartworm pill this month?"
- "How many walks this week?"

**How it works:**
1. AI searches activity log for relevant entries
2. LLM analyzes entries and answers in natural language
3. Provides context (e.g., "3 days ago", "this morning")

### 3. Weight Tracking
**Usage:**
- "Luna weighs 48 pounds now" (logs weight)
- "How much has Luna's weight changed?" (shows trend)

**How it works:**
1. Weight logs are tagged separately in activity log
2. Updates pet profile with current weight
3. AI summarizes weight history and trends
4. Alerts to significant changes (if pattern detected)

### 4. Emergency Vet Finder
**Usage:**
- "Find an emergency vet"
- "I need a vet near me"

**How it works:**
1. Shows your saved regular vet first (if configured)
2. Uses Google Places API to search nearby emergency vets
3. Prioritizes currently open locations
4. Speaks top 3 results with names, ratings, and open status
5. Offers addresses on request

**Fallback:** If no API key, shows only saved vet info.

### 5. Weather Safety Check
**Usage:**
- "Is it safe for Luna outside?"
- "Pet weather check"
- "Too hot for my dog?"

**How it works:**
1. Fetches current weather from Open-Meteo (free API)
2. AI analyzes temperature, wind, UV index for pet safety
3. Considers pet species, breed, and weight
4. Applies safety thresholds:
   - **>100°F:** Danger (heatstroke risk)
   - **>90°F:** Warning (hot pavement, bring water)
   - **<20°F:** Danger (too cold for more than a few minutes)
   - **<32°F:** Warning for short-haired breeds
   - **Wind >30mph:** Caution for small pets
   - **UV >7:** Caution for light-colored/short-haired dogs
5. Provides breed-specific advice

### 6. Food Recall Checker
**Usage:**
- "Any pet food recalls?"
- "Is my dog food safe?"

**How it works:**
1. Queries openFDA API for recent adverse event reports
2. Filters by your pets' species (dog/cat)
3. AI summarizes findings in 2-3 sentences
4. Mentions specific brands if found
5. No alarmist language — factual summary

### 7. Multi-Pet Support
**How it works:**
- If you have **one pet:** AI always uses that pet (no need to say name)
- If you have **multiple pets:**
  - Include name in command: "I fed Luna"
  - If name not mentioned, AI asks: "Which pet? Luna or Max?"
  - Fuzzy name matching handles typos/variations

## Example Conversations

### First-Time User Onboarding
> **User:** "I fed my dog"  
> **AI:** "Hi! I'm your pet care assistant. Let's get set up. What's your pet's name?"  
> **User:** "Luna"  
> **AI:** "Great! What kind of animal is Luna? Dog, cat, or something else?"  
> **User:** "Dog"  
> **AI:** "What breed is Luna?"  
> **User:** "Golden Retriever"  
> **AI:** "How old is Luna, or do you know their birthday?"  
> **User:** "She's 3 years old"  
> **AI:** "Roughly how much does Luna weigh?"  
> **User:** "65 pounds"  
> **AI:** "Does Luna have any allergies I should know about?"  
> **User:** "No allergies"  
> **AI:** "Is Luna on any medications?"  
> **User:** "Heartgard monthly"  
> **AI:** "Do you have a regular vet? If so, what's their name?"  
> **User:** "Dr. Smith at Austin Animal Hospital"  
> **AI:** "What's their phone number?"  
> **User:** "512-555-1234"  
> **AI:** "Last thing. What city are you in? This helps me check weather and find vets nearby."  
> **User:** "Austin, Texas"  
> **AI:** "All set! I've saved Luna's info. You can say things like 'I just fed Luna' to log activities, or 'find an emergency vet' if you ever need one. Do you have any other pets to add?"  
> **User:** "No"  
> **AI:** "Perfect! Take care of Luna!"

---

### Activity Logging
> **User:** "I just fed Luna"  
> **AI:** "Got it. Logged Luna's feeding at 8:30 AM. Anything else to log?"  
> **User:** "She got her flea medicine"  
> **AI:** "Got it. Logged Luna's medication at 8:31 AM. Anything else to log?"  
> **User:** "No"

---

### Quick Lookup
> **User:** "When did I last feed Luna?"  
> **AI:** "You fed Luna this morning at 8:30 AM."

---

> **User:** "Has Luna had her heartworm pill this month?"  
> **AI:** "Yes, Luna got her Heartgard on March 15th, about 2 weeks ago."

---

### Weight Tracking
> **User:** "Luna weighs 62 pounds now"  
> **AI:** "Got it. Logged Luna's weight at 8:45 AM. Anything else to log?"  
> **User:** "No thanks"

---

> **User:** "How much has Luna's weight changed?"  
> **AI:** "Luna is currently at 62 pounds. She's lost 3 pounds since your last recording in February. Her weight is trending down gradually."

---

### Emergency Vet Finder
> **User:** "Find an emergency vet"  
> **AI:** "Your regular vet is Dr. Smith at Austin Animal Hospital at 5, 1, 2, 5, 5, 5, 1, 2, 3, 4."  
> **AI:** "Let me find emergency vets near you."  
> **AI:** "I found 3 emergency vets near you. Austin Emergency Animal Hospital, open now, rated 4.5. North Austin Veterinary Emergency Center, open now, rated 4.3. Central Texas Veterinary Hospital, may be closed, rated 4.7. Want the address for any of them?"

---

### Weather Safety
> **User:** "Is it safe for Luna outside?"  
> **AI:** "Let me check the weather for you."  
> **AI:** "It's 95 degrees with high UV. It's warm for Luna, so keep walks short, stick to shaded areas, and bring water. Her Golden Retriever coat handles heat okay, but watch for panting."

---

### Food Recall Check
> **User:** "Any pet food recalls?"  
> **AI:** "Let me check for recent pet food alerts."  
> **AI:** "I found 2 recent adverse event reports in the FDA database for dogs. One involved Blue Buffalo brand and another mentioned Purina Pro Plan. These are general reports, not necessarily recalls. Want more details?"

---

### Multi-Pet Management
> **User:** "I fed my dog"  
> **AI:** "Which pet? Luna or Max?"  
> **User:** "Luna"  
> **AI:** "Got it. Logged Luna's feeding at 6:00 PM. Anything else to log?"

## Services & APIs Used

| Service | Purpose | Authentication | Cost |
|---------|---------|----------------|------|
| **Google Places API** | Emergency vet search | API key (user provides) | Pay-per-use (~$17/1000 requests) |
| **Open-Meteo** | Weather data | None | Free |
| **ip-api.com** | Auto-detect location | None | Free (up to 45 req/min) |
| **openFDA** | Pet food recalls | None | Free |
| **LLM (OpenHome)** | Intent classification, data extraction | Built-in | Free (included) |
| **File Storage** | Pet profiles & activity logs | Built-in | Free (included) |

**Note:** Only Google Places API requires setup. All other features work immediately.

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
      "medications": [
        {
          "name": "Heartgard",
          "frequency": "monthly"
        }
      ]
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

## Advanced Features

### Automatic Log Trimming
- Activity log capped at **500 entries**
- Oldest entries auto-deleted when limit reached
- Prevents file bloat and performance issues

### Idle Detection
- After 2 empty/silent responses, asks: "Still here if you need me. Otherwise I'll close."
- Waits for final confirmation before exiting
- Prevents hanging sessions

### Delete-Then-Write Pattern
- All JSON saves use delete-before-write
- Prevents file corruption from append operations
- Ensures data integrity

### Voice-Friendly Phone Numbers
- Phone numbers spoken digit-by-digit
- Example: "5125551234" → "5, 1, 2, 5, 5, 5, 1, 2, 3, 4"
- Easier for users to write down

### Fuzzy Name Matching
- Handles typos and variations
- "Lona" → matches "Luna"
- "max" → matches "Max"
- Partial matches supported

## Troubleshooting

### "I don't have any pets set up yet"
**Problem:** You triggered the ability but haven't completed onboarding.

**Solution:** The ability should automatically start onboarding. If not, say "add a new pet" to start setup.

---

### Emergency vet search returns no results
**Possible causes:**
1. No Google Places API key configured
2. Location not detected correctly
3. No emergency vets within 10-mile radius

**Solutions:**
1. Add API key in `main.py`
2. Say "update my location" to manually set city
3. Try "find a vet near me" (broader search)

---

### Weather check fails
**Possible causes:**
1. Location not configured
2. Open-Meteo API timeout

**Solutions:**
1. Say "update my location" to set your city
2. Try again in a moment (API may be temporarily down)

---

### "Which pet?" asked every time
**Problem:** You have multiple pets but aren't mentioning a name.

**Solution:** Include pet name in your command: "I fed Luna" instead of just "I fed my dog"

---

### Voice transcription errors
**Problem:** AI doesn't understand your speech correctly.

**Solutions:**
- Speak clearly and at moderate pace
- Use simple phrasing: "I fed Luna" vs "I gave Luna her dinner"
- Spell out breed names if unusual: "L-A-B-R-A-D-O-R"

---

### Activity log seems incomplete
**Problem:** Only recent 500 entries are kept.

**Explanation:** Log auto-trims to prevent file bloat. This is intentional for performance.

**Workaround:** For long-term tracking, export logs periodically (future feature).

## Privacy & Security

### Data Storage
- All data stored **locally** in JSON files on OpenHome server
- No data sent to third parties except APIs you've configured
- Files namespaced with `petcare_` prefix to avoid collisions

### API Data Sharing
- **Google Places:** Only location coordinates sent, no pet data
- **Open-Meteo:** Only location coordinates sent, no pet data
- **ip-api.com:** Only IP address (automatic), no pet data
- **openFDA:** Only pet species sent (dog/cat), no personal data

### Deleting Data
To completely remove all pet data:
1. Say "remove pet" for each pet
2. Say "clear activity log" to delete all logs
3. Or manually delete `petcare_pets.json` and `petcare_activity_log.json`

## Tips for Best Experience

### ✅ Do's
- **Be specific with names:** "I fed Luna" vs "I fed my dog"
- **Use natural language:** "Luna got her flea medicine" works great
- **Log immediately:** Best to log activities right after they happen
- **Check weather before walks:** "Is it safe outside for Luna?"
- **Update weight monthly:** Helps track health trends

### ❌ Don'ts
- **Don't use complex sentences:** Keep it simple for voice recognition
- **Don't forget to mention pet names:** Required with multiple pets
- **Don't expect perfect recall beyond 500 entries:** Log trimming is automatic
- **Don't rely solely on this for medical records:** Consult your vet's records

## Extending the Ability

Want to add custom features? Here are some ideas:

### Custom Activity Types
Modify `ACTIVITY_TYPES` in `main.py`:
```python
ACTIVITY_TYPES = {
    "feeding",
    "medication",
    "walk",
    "weight",
    "vet_visit",
    "grooming",
    "training",  # NEW
    "playtime",  # NEW
    "other",
}
```

### Medication Reminders
Add a scheduled task in `run()` to check medication schedules and speak reminders.

### Integration with Pet Cameras
Use `exec_local_command()` to trigger pet camera snapshots when logging activities.

### Export to CSV
Add a function to export activity log to CSV for spreadsheet analysis.

