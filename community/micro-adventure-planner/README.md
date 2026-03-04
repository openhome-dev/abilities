# Micro Adventure Planner

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@contributor-lightgrey?style=flat-square)

## What It Does
Micro Adventure Planner creates short nearby plans based on mood, budget, weather, air quality, and city. It also finds restaurants, landmarks, estimates travel time and budget, and gives packing tips.

It can focus on:
- 🎯 Activities and events
- 🏨 Hotels and lodging
- 🚌 Transportation options
- 🍕 Food and restaurants *(new)*
- 🏛️ Sights and landmarks *(new)*

This ability is **planning only** — it does **not** perform booking or checkout.

## Suggested Trigger Words
- "Plan a micro adventure"
- "Find restaurants in Cairo"
- "Show sights and landmarks in Dahab"
- "Find me a quiet indoor plan"
- "Plan something cheap tonight"
- "Find hotels in Dahab"
- "Show transport options"
- "Travel tips for Dahab"
- "Save this plan"
- "Show my trip history"

## Features
- First-run city detection with IP and persistent home city
- Multi-turn planning and refinement (cheaper, indoor/outdoor, mood-based)
- Data fetch for weather, air quality, and discovery signals
- Focus-aware search: activities, lodging, transport, food, sights, or mixed
- Explainable top 3 options with reasons
- Optional Google Calendar handoff link (no direct booking)
- 🍕 **Food & restaurant discovery** via Serper with smart fallbacks
- 🏛️ **Sights & attractions search** for landmarks, museums, and historic sites
- 💾 **Itinerary saving** — bookmark plans for later recall
- 📜 **Trip history** — review your past saved adventures
- 🧳 **Travel tips** — packing advice, currency, language, and daily budget estimates
- 📏 **Travel distance & duration** — estimated driving time via OSRM
- 💰 **Budget estimation** — rough daily cost via LLM
- 🌍 **Currency & language info** — fetched from RestCountries API

## Setup
Set API keys as module constants in `main.py`, or configure them in prefs (`micro_adventure_prefs.json`).

```json
{
  "home_city": "Berlin",
  "api_key_serper": "YOUR_KEY",
  "api_key_ticketmaster": "YOUR_KEY",
  "default_budget": "medium",
  "default_vibe": "balanced",
  "default_indoor": "any"
}
```

### APIs Used
| API | Key Required | Purpose |
|-----|:---:|---------|
| Open-Meteo Geocoding | No | City → lat/lon |
| Open-Meteo Forecast | No | Weather context |
| Open-Meteo Air Quality | No | AQI context |
| OSRM Routing | No | Travel distance & duration |
| RestCountries | No | Currency & language info |
| Serper.dev | Optional | Activity, food, sights discovery |
| Ticketmaster | Optional | Event enrichment |

If optional keys are missing, the ability still works using built-in fallback candidates.

## How It Works
1. Loads/saves preferences and default city.
2. Captures planning constraints (mood, budget, indoor/outdoor, time, focus).
3. Fetches weather + AQI + discovery data.
4. Normalizes and scores candidates by budget, environment, and requested focus.
5. Speaks top 3 options with rationale.
6. Lets user refine, save itinerary, get travel tips, or add to calendar.

## Example Conversation
> **User:** "Find restaurants in Cairo."
>
> **AI:** "Planning food options in Cairo. First, local street food tour..."
>
> **User:** "Show sights and landmarks in Dahab."
>
> **AI:** "Planning sights in Dahab. First, top landmark and viewpoint..."
>
> **User:** "Save this plan."
>
> **AI:** "Saved your Dahab itinerary. You now have 2 saved trips."
>
> **User:** "Travel tips for Dahab."
>
> **AI:** "Pack light clothes, it's 32 degrees. Local currency is Egyptian Pound. About 520 km from Cairo, roughly 6 hours by car."
>
> **User:** "Show my trip history."
>
> **AI:** "You have 2 saved trips. First, Dahab with top landmark and local museum..."
