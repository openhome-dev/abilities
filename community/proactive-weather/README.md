# Proactive Weather

A weather ability for OpenHome with two components: a reactive flow for on-demand 
weather queries, and a background daemon that monitors conditions and proactively 
alerts you to severe weather.

No API key required. Uses Open-Meteo (weather data) and Nominatim (geocoding), 
both free with no authentication needed.

## Installation

1. Upload the ability folder to OpenHome
2. Set trigger words in the dashboard (e.g. "what's the weather", "weather")
3. Select **Skill** as the ability category

## Usage

**Reactive:** Say a trigger phrase to get current conditions and today's forecast. 
On first use the ability asks for your city and saves it for future sessions.

**Proactive:** The background daemon starts automatically on session connect. If 
severe weather is detected (thunderstorms, heavy rain, hail, etc.), it interrupts 
the conversation with an alert. Each alert type fires once per session.

**Personality awareness:** After fetching weather, `local_weather.md` is written 
to persistent storage. The Memory Watcher picks it up within ~60-90 seconds and 
injects it into the Personality's system prompt so it can naturally reference 
weather conditions without being asked.
