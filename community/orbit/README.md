# Orbit — ISS Tracker

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@milliyin-coder--lightgrey?style=flat-square)

## What It Does

Real-time voice tracking of the International Space Station. Ask where the ISS is right now, who is on board, when it will pass over your city, how fast it goes, or anything about life in space. Live data from space, spoken back to you.

## Suggested Trigger Words

- "orbit"
- "space station"
- "ISS"
- "where is the space station"
- "who is in space"
- "astronauts"
- "when will I see the ISS"
- "space station pass"
- "ISS location"
- "who is on the ISS"

Configure additional phrases in the OpenHome dashboard for this ability.

## Setup

### API Requirements

This ability uses **free APIs** — no payment or subscription required.

| Feature | API | Key Required |
|---------|-----|------------|
| ISS Location | N2YO | ✅ Free API key |
| ISS Crew | SpaceDevs | ❌ No key |
| Pass Predictions | Open Notify | ❌ No key (deprecated, uses fallback) |
| City Geocoding | OpenStreetMap (Nominatim) | ❌ No key |

### N2YO API Key (Required for Live Location)

1. Go to [n2yo.com/api](https://www.n2yo.com/api/)
2. Click **Sign Up** and create a free account
3. Copy your **API Key**
4. Add it in your **OpenHome Settings → API Keys** as `n2yo_api_key` (name must match exactly)

If no key is configured, or N2YO is unreachable, location queries fall back to cached demo data instead of failing — the ability never crashes on a missing or bad key.

## What You Can Ask

| Question | What You'll Hear |
|----------|-----------------|
| "Where is the space station?" | Current location, speed, altitude, and whether it's in Earth's shadow |
| "Who is up there?" | Number of people in space + names of ISS crew |
| "When will I see it from [city]?" | Next pass time, duration, and where to look |
| "How fast does it go?" | Speed in mph and orbit time |
| "How many orbits today?" | Orbits since midnight + sunrise/sunset count |
| "How big is the space station?" | Size, weight, and comparison |
| "Tell me about solar panels" | Power generation facts |
| "What's inside the ISS?" | Living space, bathrooms, gym, Cupola |
| "How old is the space station?" | Years and days since first launch |
| "What did they eat today?" | Random space food fact |
| "Is anyone sleeping right now?" | Sleep status based on GMT time |
| "What time is it in space?" | Current GMT time + crew schedule |
| "What else can I ask?" | Full list of capabilities |
| "Repeat that" | Replays the last response |
| "Are you there?" | Wake confirmation |
| "Check again" | Re-runs last city pass query |

**Exit words:** "done", "stop", "quit", "exit", "goodbye", "bye", "orbit out", "over"

## How It Works

After triggering the ability, it fetches live ISS data from N2YO (real latitude, longitude, velocity) and maps coordinates to a human region without extra network calls. Crew data comes from SpaceDevs' astronaut database, filtered for ISS personnel. Pass predictions use Open Notify's `iss-pass.json` with a realistic synthetic fallback when the API is unavailable. City geocoding uses OpenStreetMap's Nominatim service. Exit words such as "done" or "orbit out" end the session.

## Data Sources

- **N2YO** — Real-time satellite tracking (position, velocity, altitude, eclipse status)
- **SpaceDevs** — Current astronauts in space with agency filtering
- **OpenStreetMap (Nominatim)** — City geocoding for pass predictions
- **Open Notify** — ISS pass times (deprecated, fallback active)

## Example Conversation

> **User:** "Where is the space station?"
> **Orbit:** "The space station is over the Pacific Ocean, west of Central America. It is moving at 17,134 miles per hour, 250 miles above Earth."

> **User:** "Who is up there?"
> **Orbit:** "There are 10 people in space right now. On the ISS: Jessica Meir, Sergey Kud-Sverchkov, Anna Kikina, and 7 others."

> **User:** "When will I see it from New York?"
> **Orbit:** "The ISS will pass over New York on July 19 at 08:15 PM. Visible for 4 minutes. Look west, about 20 degrees above the horizon. It will look like a bright star moving fast."

> **User:** "How fast does it go?"
> **Orbit:** "The space station travels at 5 miles per second. That is 17,500 miles per hour, fast enough to circle Earth in 90 minutes."

> **User:** "Done"
> **Orbit:** "Orbit out."
