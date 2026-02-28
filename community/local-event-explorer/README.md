# Local Event Explorer

The **Local Event Explorer** is an OpenHome community ability that helps users discover concerts, sports, comedy, and festivals in their area. It leverages the **Ticketmaster Discovery API** as its primary source, falling back to **SeatGeek** if needed.

## Features
- **Smart Geolocation**: Uses your IP to guess your city or asks you to set a default home city (saved persistently).
- **Time Parsing**: Ask for events "tonight", "tomorrow", or "this weekend".
- **Interactive Drill-Down**: You can ask for more details on specific events ("tell me about the second one").
- **Add to Calendar**: Generates Google Calendar links for events you want to save.

## Setup Instructions
To use this ability, you need to provide an API key. This prevents rate-limiting issues across the OpenHome network.

### 1. Get API Keys
1. **Ticketmaster** (Primary): Go to the [Ticketmaster Developer Portal](https://developer.ticketmaster.com/) and create a free account to get an API Key.
2. **SeatGeek** (Fallback): Go to the [SeatGeek Platform](https://seatgeek.com/account/develop) and register an app to get a Client ID.

### 2. Configure Your Keys
Add your keys to the OpenHome Settings UI or place them directly in the preferences file `data/event_explorer_prefs.json`:
```json
{
  "api_key_ticketmaster": "YOUR_KEY_HERE",
  "api_key_seatgeek": "YOUR_KEY_HERE"
}
```

## Example Prompts
- "Open Event Explorer."
- "Are there any concerts tonight?"
- "Find comedy shows this weekend."
- "Search for Taylor Swift in New Orleans."
- "Tell me more about the first event."
- "Add that to my calendar."
