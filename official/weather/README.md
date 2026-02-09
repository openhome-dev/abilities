# Weather

![Official](https://img.shields.io/badge/OpenHome-Official-blue?style=flat-square)

Fetches current weather for any city using free APIs. No API key required.

## Trigger Words

- "what's the weather"
- "weather report"
- "check the weather"
- "how's the weather"

## Setup

No setup required. Uses free Open-Meteo API and Nominatim geocoding.

## How It Works

1. User triggers the Ability
2. Asks which city to check
3. Geocodes the city name to coordinates (Nominatim)
4. Fetches current temperature and wind speed (Open-Meteo)
5. Speaks a short weather report

## APIs Used

- [Nominatim](https://nominatim.openstreetmap.org/) — Free geocoding (OpenStreetMap)
- [Open-Meteo](https://open-meteo.com/) — Free weather data, no API key needed

## Example Conversation

> **User:** "What's the weather"
> **AI:** "Which city would you like the weather for?"
> **User:** "San Francisco"
> **AI:** "The current temperature in San Francisco is 15.2 degrees Celsius with wind speeds of 12 kilometers per hour."
