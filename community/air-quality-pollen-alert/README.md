# Air Quality & Pollen Alert

Smart air quality and pollen assistant for allergy and asthma sufferers. Tells you what matters for *your* conditions — not just an AQI number. Answers on-demand questions about outdoor safety, activity timing, and windows based on your city and health profile.

**No API keys required.** Uses Open-Meteo (free, global coverage).

---

## Trigger Phrases

| What you say | What happens |
|---|---|
| "set up air quality for Ottawa" | One-time setup — city included in the phrase |
| "how's the air quality today?" | Current AQI + pollen with personalized advice |
| "what's tomorrow's forecast?" | Today and tomorrow outlook |
| "is it safe to go for a run?" | Direct yes/no with best outdoor time window |
| "should I keep my windows closed?" | Pollen and AQI-based window advice |
| "what's the pollen count?" | Current pollen breakdown by type |
| "update air quality settings" | Change alert time or health conditions |

---

## Setup

Say the city in the trigger phrase — no follow-up questions:

> *"Set up air quality for Toronto"*

The ability extracts the city name, geocodes it, and saves it immediately. You can say "update air quality settings" to change alert time or health conditions.

---

## What You Get Instead of a Number

**Generic assistant:** *"Air quality is moderate — AQI 87."*

**This ability:** *"Air quality is moderate this morning at 87, but grass pollen is high at 78 grains per cubic meter. For your hay fever, staying indoors until mid-morning will help — the best window to be outside today is after 6pm when pollen drops significantly."*

The response is built around your conditions and pollen triggers — if grass doesn't bother you, you won't hear about it.

---

## On-Demand Questions

**Activity check:**
> *"Is it safe to run?"*
> "Not ideal right now — ozone is elevated at 68 μg/m³ which can affect asthma. If you want to run outside, this morning before 10am or after 6pm will be significantly better."

**Windows advice:**
> *"Should I keep my windows closed?"*
> "Yes, I'd keep them closed — tree pollen is high right now and that's one of your triggers. Open them in the evening after 7pm when pollen settles."

**Forecast:**
> *"Tomorrow's forecast?"*
> "Tomorrow's AQI is forecast at 145 — poor. Very high tree pollen expected. If you take an antihistamine, tonight before bed is the best time so it's fully working by morning."

---

## Data Source

| Source | Coverage | Key required |
|---|---|---|
| [Open-Meteo Air Quality](https://air-quality-api.open-meteo.com) | Global — hourly AQI, ozone, PM2.5, PM10 | None |
| [Open-Meteo Geocoding](https://geocoding-api.open-meteo.com) | Global city lookup | None |

Pollen data: grass (Poaceae), tree (birch proxy), weed (ragweed proxy) — grains/m³, hourly, 2-day forecast.
