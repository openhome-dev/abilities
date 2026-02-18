# Spaceflight Tracker

## What It Does
Provides real-time information about the International Space Station's location and lists all astronauts currently in space using the Open Notify API.

## Suggested Trigger Words
- "tell me where the space station is"
- "tell me who is in space right now"

## Setup
**No API Keys Required** — This ability uses the free Open Notify API (http://api.open-notify.org).

The ability automatically fetches:
1. Current ISS coordinates (latitude/longitude with geographic context)
2. Names of all astronauts currently in space

## How It Works
1. User triggers the ability with a space-related query
2. AI fetches real-time data from Open Notify API:
   - ISS position with latitude/longitude coordinates
   - Complete list of astronauts in space
3. AI contextualizes the location (e.g., "over the Pacific Ocean")
4. AI formats the information in a natural, conversational way
5. AI speaks the formatted response

**Smart Features:**
- **Geographic Context**: Converts coordinates to recognizable locations
- **Natural Language**: Formats technical data for easy listening
- **Robust Error Handling**: Gracefully handles API failures
- **JSONP Support**: Properly parses callback-wrapped responses

## Example Conversation
> **User:** "tell me where the space station is"  
> **AI:** "The International Space Station is currently at 23.45 degrees North latitude and 87.32 degrees East longitude, passing over the Bay of Bengal near India."

---

> **User:** "tell me who is in space right now"  
> **AI:** "There are currently 7 people in space: Jasmin Moghbeli, Andreas Mogensen, Satoshi Furukawa, Konstantin Borisov, Oleg Kononenko, Nikolai Chub, and Loral O'Hara."

---

> **User:** "tell me where the space station is"  
> **AI:** "The International Space Station is currently at 51.23 degrees North latitude and 12.45 degrees West longitude, passing over the Atlantic Ocean west of Ireland. There are currently 7 people aboard."

## Technical Details
- **ISS Location API**: `http://api.open-notify.org/iss-now.json`
- **Astronauts API**: `http://api.open-notify.org/astros.json`
- **Update Frequency**: Real-time on each query
- **Response Format**: Natural language with contextual details

## Notes
The ability combines both ISS location and astronaut data when available to provide comprehensive space information in a single response. If either API endpoint fails, it gracefully provides whatever information is accessible.
