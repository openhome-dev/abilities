# Micro Adventure Planner

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@contributor-lightgrey?style=flat-square)

## What It Does

Micro Adventure Planner is a voice-first trip-planning assistant. Tell it where you want to go (or just a vibe) and it builds a full plan with weather, air quality, activities, events, budget estimates, flight prices, and more — then optionally posts the whole thing to a **Notion** page.

It handles both **local outings** ("I wanna go eat") and **travel plans** ("one week in Spain"), with smart origin-aware context ("Badr, Cairo, Egypt → Barcelona").

It can focus on:
- 🎯 Activities and events
- 🏨 Hotels and lodging
- 🚌 Transportation options
- 🍕 Food and restaurants
- 🏛️ Sights and landmarks

This ability is **planning only** — it does **not** perform booking or checkout.

## Suggested Trigger Words
- "Plan a micro adventure"
- "One week in Barcelona"
- "Find restaurants in Cairo"
- "Show sights and landmarks in Dahab"
- "Find me a quiet indoor plan"
- "Plan something cheap tonight"
- "I wanna go eat" *(local outing — uses home city)*
- "Recommend a city for a romantic weekend"
- "Post to Notion" / "Save to Notion"
- "Travel tips for Dahab"
- "Save this plan"
- "Show my trip history"

## Features

### Core Planning
- **LLM-first intent classification** — all voice input is classified by the LLM with built-in STT noise tolerance (handles garbled words like "no shin" → Notion)
- **First-run city detection** via IP geolocation with full origin context (city, region, country)
- **Multi-turn planning and refinement** — cheaper, indoor/outdoor, mood-based, different focus
- **Smart city recommendation** — "recommend a city" triggers LLM-powered destination suggestions based on vibe, budget, and season
- **Local outing detection** — "I wanna go eat" / "let's play paddle" automatically routes to home-city plans without needing a destination
- **Duration extraction** — "one week in Rome", "3 days in Tokyo", "weekend trip" all parsed correctly

### Data & Discovery
- **Weather & air quality** — real-time from Open-Meteo
- **Activity/food/sights search** — Serper Google Search + Places API
- **Event enrichment** — Ticketmaster upcoming events for the destination
- **Flight price snippets** — real price ranges fetched from Google via Serper (origin → destination)
- **Travel distance & duration** — estimated driving time via OSRM
- **Currency & language info** — fetched from RestCountries API

### Budget & Cost
- **Country-aware budget estimates** — LLM generates destination-specific daily costs (accommodation, meals, transport, activities) instead of generic ranges
- **Budget tiers** — low / medium / high with contextual recommendations

### Notion Integration
- **Full Notion page export** — posts your plan as a rich Notion page with:
  - Origin → Destination header (e.g. "Badr, Egypt → Spain")
  - Weather & air quality callout
  - Country-aware daily budget breakdown
  - Getting There section with flight price ranges
  - Top activity/food/sight options with descriptions
  - Upcoming Events from Ticketmaster with clickable links
  - Travel tips (packing, currency, language)
- **STT-resilient Notion detection** — fuzzy phonetic matching catches garbled voice commands ("no shin", "noshon", "motion" → Notion)

### History & Extras
- 💾 **Itinerary saving** — bookmark plans for later recall
- 📜 **Trip history** — review your past saved adventures
- 🧳 **Travel tips** — packing advice, currency, language, and daily budget estimates
- 📅 **Calendar handoff** — Google Calendar link generation (no direct booking)

## Setup

Set API keys as module constants in `main.py`, or configure them in the prefs file (`micro_adventure_prefs.json`).

```json
{
  "home_city": "Cairo",
  "home_country_code": "EG",
  "home_country_name": "Egypt",
  "home_region_name": "Cairo",
  "api_key_serper": "YOUR_SERPER_KEY",
  "api_key_ticketmaster": "YOUR_TICKETMASTER_KEY",
  "notion_api_key": "YOUR_NOTION_KEY",
  "notion_database_id": "YOUR_NOTION_DB_ID",
  "default_budget": "medium",
  "default_vibe": "balanced",
  "default_indoor": "any"
}
```

> **Note:** `home_city`, `home_country_code`, `home_country_name`, and `home_region_name` are auto-detected from IP on first run. You only need to set them manually if IP detection doesn't work.

### APIs Used

| API | Key Required | Purpose |
|-----|:---:|---------|
| Open-Meteo Geocoding | No | City → lat/lon |
| Open-Meteo Forecast | No | Weather context |
| Open-Meteo Air Quality | No | AQI context |
| OSRM Routing | No | Travel distance & duration |
| RestCountries | No | Currency & language info |
| ip-api.com | No | IP-based home city/country detection |
| Serper.dev | Optional | Activity, food, sights discovery + flight prices |
| Ticketmaster | Optional | Event enrichment |
| Notion API | Optional | Page export |

If optional keys are missing, the ability still works using built-in fallback candidates (Serper/Ticketmaster) or skips the feature (Notion, flight prices).

## How It Works

1. **First run:** Detects home city, region, and country from IP. Asks user to confirm.
2. **Voice input:** Every message goes through LLM-first intent classification (with STT noise tolerance).
3. **Planning:** Captures constraints — mood, budget, indoor/outdoor, time, focus, destination.
4. **Data fetch:** Parallel async calls for weather, AQI, Serper activities, Ticketmaster events, and flight prices.
5. **Scoring:** Normalises and ranks candidates by budget, environment, and requested focus.
6. **Presentation:** Speaks top 3 options with rationale. Offers brief or detailed format.
7. **Post-plan:** User can refine, save itinerary, post to Notion, get travel tips, or add to calendar.

## Example Conversation

> **User:** "One week in Spain"
>
> **AI:** "Nice! Before I build the full plan — you said one week, is that right?"
>
> **User:** "Yes"
>
> **AI:** "Planning your week in Spain from Badr, Egypt. Let me check weather, events, and flights..."
>
> *(fetches weather, AQI, Serper activities, Ticketmaster events, flight prices in parallel)*
>
> **AI:** "Here's what I found for Spain. First, La Sagrada Familia tour... Second, tapas food crawl in Barcelona... Third, Park Güell and Gothic Quarter walk..."
>
> **User:** "Post to Notion"
>
> **AI:** "Posted to Notion."
>
> *(Creates a rich Notion page with weather, budget breakdown for Spain, flight prices from Egypt, top options, upcoming events, and travel tips)*

---

> **User:** "I wanna go eat"
>
> **AI:** "Planning food options near you..."
>
> *(Uses home city, finds local restaurants via Serper)*

---

> **User:** "Travel tips for Dahab"
>
> **AI:** "Pack light clothes, it's 32 degrees. Local currency is Egyptian Pound. About 520 km from Cairo, roughly 6 hours by car."

## Architecture

- **LLM-first classification** — no regex/keyword fast-paths for intent detection (except city-set). The LLM handles all noisy STT input directly.
- **Fuzzy Notion fallback** — a phonetic regex safety net catches badly garbled "Notion" commands if the LLM misses them.
- **Parallel async data fetching** — weather, AQI, activities, events, and flight prices are all fetched concurrently via `asyncio.gather`.
- **Country-aware LLM budget** — budget estimates are generated per-destination by the LLM, not hardcoded ranges.
