# Pet Care Assistant

![Community](https://img.shields.io/badge/OpenHome-Community-green?style=flat-square)

A voice-first ability that helps users track and manage their pets' daily lives. Stores pet profiles, logs activities (feeding, medication, walks, weight), answers questions about those logs, finds emergency vets, warns about dangerous weather, and checks for pet food recalls.

**Why this needs to be an Ability:** The LLM already handles general pet care knowledge (breed info, training tips, nutrition advice). This ability exists because it does things the LLM cannot do alone: persist data across sessions, call external APIs for real-time information, and track activity over time.

## Features

| Feature | Examples |
|---|---|
| **Guided Onboarding** | First-time users set up pet profiles step-by-step via voice |
| **Activity Logging** | "I just fed Luna", "Luna got her flea medicine", "We walked for 30 minutes" |
| **Quick Lookup** | "When did I last feed Luna?", "Has Max had his heartworm pill this month?" |
| **Weight Tracking** | "Luna weighs 48 pounds now", "How much has Luna's weight changed?" |
| **Emergency Vet Finder** | "Find an emergency vet", "I need a vet near me" |
| **Weather Safety** | "Is it safe for Luna outside?", "Pet weather check" |
| **Food Recall Check** | "Any pet food recalls?", "Is my dog food safe?" |
| **Profile Editing** | "Add a new pet", "Change my vet info", "Update Luna's weight" |
| **Multi-Pet Support** | Manages multiple pets, resolves by name when ambiguous |

## Services Used

| Service | API | Auth | Cost |
|---|---|---|---|
| Emergency Vet Finder | Google Places API (Text Search) | User provides Google API key | Pay-per-use (user's billing) |
| Weather Safety | Open-Meteo | None needed | Free |
| Location Detection | ip-api.com | None needed | Free |
| Food Recalls | openFDA API | None needed | Free |
| All other features | LLM + File Storage (built-in) | None needed | Free |

If Google Places API key is not configured, the emergency vet feature gracefully falls back to showing the user's saved vet info. All other features work with zero external accounts.

## Setup

1. Add the ability to your OpenHome Personality
2. (Optional) Set your Google Places API key in `main.py` for emergency vet search
3. On first activation, the ability walks you through setting up pet profiles via voice

## Suggested Trigger Words

Activity logging: "I fed", "I just fed", "ate", "got her medicine", "gave medication", "we walked", "went for a walk", "weighs", "log pet activity"

Lookups: "when did I last feed", "has had", "how many walks", "last vet visit", "check on"

Emergency vet: "emergency vet", "find a vet", "vet near me", "I need a vet"

Weather: "is it safe outside", "pet weather", "can I walk", "too hot for", "too cold for"

Food recalls: "pet food recall", "food recall check", "is my dog food safe", "is my cat food safe", "any food recalls"

Profile: "add a pet", "update pet info", "change my vet", "pet profile"

## Data Model

Two persistent JSON files using the delete-then-write pattern:

- **petcare_profiles.json** — Pet profiles, user location, vet info
- **petcare_activity_log.json** — Activity entries (feeding, medication, walk, weight, vet_visit, grooming, other), capped at 500 entries

## How It Works

1. **First-time users** go through guided voice onboarding (name, species, breed, age, weight, allergies, medications, vet, location)
2. **Returning users** — trigger context is classified by the LLM to determine the mode (log, lookup, weather, vet, recall, edit)
3. **Quick Mode** — if the trigger has a clear intent, the ability answers and offers one follow-up before exiting
4. **Full Mode** — if the trigger is vague, enters a multi-turn conversation loop with idle detection

## Architecture

- **LLM as intent router** — classifies voice input into structured JSON for mode routing
- **LLM as data extractor** — extracts clean values from messy voice transcription
- **Multi-pet context** — resolves pet names automatically; asks when ambiguous
- **Delete + write pattern** — prevents JSON corruption from append behavior
- **Namespaced files** — `petcare_` prefix avoids collisions with other abilities
- **try/finally** — guarantees `resume_normal_flow()` on every exit path
- **Exit-first checking** — exit words checked before LLM call to save resources
- **Filler speech** — "Let me check" before API calls that take > 1 second
- **Log size management** — caps at 500 entries, trims oldest automatically
- **Phone numbers spoken digit by digit** — for voice-friendly output

## Key SDK Methods Used

| SDK Method | Purpose |
|---|---|
| `speak()` | Voice output to user |
| `user_response()` | Listen for voice input |
| `run_io_loop()` | Speak + listen in one call (onboarding) |
| `text_to_text_response()` | LLM intent classification and data extraction |
| `run_confirmation_loop()` | Yes/no confirmation for destructive actions |
| `check_if_file_exists()` | First-run detection |
| `read_file()` / `write_file()` / `delete_file()` | Persistent JSON storage |
| `resume_normal_flow()` | Return to Personality (in try/finally) |
| `editor_logging_handler` | All logging (no print statements) |
