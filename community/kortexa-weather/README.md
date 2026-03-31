# Weather Display

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@kortexa--ai-lightgrey?style=flat-square)

## What It Does
Shows current weather on [Window](https://github.com/kortexa-ai/openhome-porch) as a rich card with temperature, conditions, humidity, wind, and UV index. Automatically detects your location via IP geolocation — no setup needed.

Uses [Open-Meteo](https://open-meteo.com/) (free, no API key) for weather data and [json-render](https://github.com/vercel-labs/json-render) for the visual display.

## Suggested Trigger Words
- "weather"
- "what's the weather"

## Requirements
- [Porch](https://github.com/kortexa-ai/openhome-porch) running on your Mac (for geolocation + Window)
- [Window](https://github.com/kortexa-ai/openhome-porch) companion app

## How It Works
1. Say the trigger word
2. Porch runs `curl ipinfo.io/json` on your Mac to get your location
3. Fetches weather from Open-Meteo using your lat/lon
4. Opens Window and renders a weather card via json-render
5. Speaks a brief summary

Automatically uses Fahrenheit for US locations, Celsius everywhere else.

## Example Conversation
> **User:** "weather"
> **AI:** "Checking the weather."
> *(Window opens with a weather card showing 72°F, Partly cloudy, humidity, wind, UV)*
> **AI:** "It's 72 degrees and partly cloudy in Portland. Feels like 70. Humidity 55 percent."

## Graceful Degradation
If Porch or Window aren't running, the ability still speaks the weather (or reports that it couldn't connect). No crashes.

## Logs
Look for `[Weather]` entries in OpenHome Live Editor logs.
