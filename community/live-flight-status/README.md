# Live Flight Status (AirLabs)

![Community](https://img.shields.io/badge/OpenHome-Community-blue?style=flat-square)

A voice-first flight tracker that pulls **live flight status** and **airport schedules** using the AirLabs API.
It’s designed for short spoken responses, supports “details” on demand, and remembers your last flight.

## Trigger Words

- "flight status"
- "track a flight"
- "check flight"
- "where is my flight"
- "flight checker"

## Setup

This ability uses the AirLabs API.

1. Create an AirLabs account and get an API key.
2. In `main.py`, paste your key into:
   `AIRLABS_API_KEY = "..."` for testing.
3. Before submitting to GitHub, revert it to:
   `AIRLABS_API_KEY = "REPLACE_WITH_YOUR_KEY"`

## How It Works (Voice Flow)

1. User triggers the ability
2. Ability asks for a flight (example: "A A 1919" or "Delta one three three five")
3. Ability calls AirLabs Flight API and speaks a short summary:
   - route (departure/arrival airport codes)
   - live status (scheduled / en-route / landed, etc.)
   - departure and arrival times in a voice-friendly format
4. User can say:
   - **"details"** → optional extra info (gates/terminal/aircraft if available)
   - **"sample flights"** → provides 3 sample arrivals/departures from an airport
   - **"repeat last"** → repeats the last spoken line
   - **"use last flight"** → checks the last saved flight again
   - **"stop / exit / quit / done"** → exits cleanly

## Key SDK Functions Used

- `speak()` — short TTS responses (voice-first)
- `wait_for_complete_transcription()` / `user_response()` — capture user speech
- File storage (`check_if_file_exists`, `read_file`, `write_file`, `delete_file`)
  - remembers last flight and last airport across sessions
- `resume_normal_flow()` — returns control to the main Personality

## Example Conversation

> **User:** "Flight status"  
> **AI:** "Tell me a flight, like A A six. Or say sample flights."  
> **User:** "Sample flights"  
> **AI:** "Say an airport code and arrivals or departures. Like A U S arrivals."  
> **User:** "A U S arrivals"  
> **AI:** "AA3154: CLT to AUS. Departs Feb 14 at 8 59 AM."  
> **User:** "AA3154"  
> **AI:** "Checking AA3154."  
> **AI:** "AA3154: CLT to AUS. Status scheduled. Departs Feb 14 at 8 59 AM. Arrives Feb 14 at 11 10 AM."  
> **User:** "Details"  
> **AI:** "Depart terminal 1, gate B12. Arrive terminal 2, gate C3."  
> **User:** "Stop"  
> **AI:** "Okay. Goodbye."
