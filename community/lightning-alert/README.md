# Lightning Alert

Real-time lightning and thunderstorm proximity monitor. Proactively alerts you when a storm is approaching your location and tells you how long you have to get inside. Alerts again when the storm has passed.

**No API keys required.** Location is auto-detected from your IP on first run.

---

## Trigger Phrases

| What you say | What happens |
|---|---|
| "any lightning nearby?" | Current storm status for your location |
| "is there a storm coming?" | Whether a storm is approaching |
| "how long until the storm?" | Minutes until the storm arrives |
| "is it safe to go outside?" | Whether conditions have cleared |
| "has the storm passed?" | Clear-check on current conditions |
| "use Chicago instead" | Switch monitoring to a different city |
| "warn me 2 hours ahead" | Adjust the advance warning threshold |
| "give me more notice" | Increase warning to 2 hours |

---

## Background Alerts

The daemon polls every 10 minutes and speaks proactively when:

- **Storm approaching** — a thunderstorm is forecast within your warning window (default: 90 minutes)
- **Storm cleared** — the storm has passed and conditions are safe again

Both alert types fire once per day maximum to avoid repeat interruptions during prolonged storms.

---

## Location Detection

On first run, your location is automatically detected from your IP address — no setup needed.

If your IP resolves to a cloud or VPN provider, the ability will ask for your city the next time you trigger it in the foreground. Your location is then saved permanently.

To change location at any time: *"use [city name] instead"* or *"set my location to [city]"*

---

## Warning Threshold

Default: alert when a storm is **90 minutes** away.

Adjust via voice:
- *"warn me 2 hours ahead"* → 120 minutes
- *"give me 30 minutes notice"* → 30 minutes
- *"warn me earlier"* → 60 minutes

Range: 15 – 240 minutes.

---

## Data Sources

| Source | Coverage | Key required |
|---|---|---|
| [Open-Meteo](https://open-meteo.com) | Global, 15-min granularity | None |
| [NOAA/NWS Alerts](https://www.weather.gov/documentation/services-web-api) | US only — official warnings | None |
| [ip-api.com](https://ip-api.com) | IP geolocation | None |
| [Nominatim](https://nominatim.openstreetmap.org) | City geocoding fallback | None |
