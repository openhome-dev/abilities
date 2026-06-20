# Air Quality & Pollen Alert

Proactive air quality and pollen monitor for allergy and asthma sufferers. Tells you what matters for *your* conditions — not just an AQI number. Fires a personalized morning briefing, warns you the evening before a bad day so you can take preventive medication, and answers on-demand questions about outdoor safety, activity timing, and windows.

**No API keys required.** Uses Open-Meteo (free, global coverage).

---

## Trigger Phrases

| What you say | What happens |
|---|---|
| "set up air quality alerts" | One-time setup: city, morning time, health conditions, pollen triggers |
| "how's the air quality today?" | Current AQI + pollen with personalized advice |
| "what's tomorrow's forecast?" | Today and tomorrow outlook |
| "is it safe to go for a run?" | Direct yes/no with best outdoor time window |
| "should I keep my windows closed?" | Pollen and AQI-based window advice |
| "what's the pollen count?" | Current pollen breakdown by type |

---

## Setup

One-time voice setup — no app, no typing:

1. **City** — "What city are you in?"
2. **Morning alert time** — "What time should I brief you?"
3. **Health conditions** — asthma, hay fever, COPD, or general
4. **Pollen triggers** — grass, tree, weed, or all

After setup the daemon monitors automatically. You can update any setting by saying "update my air quality settings."

---

## What You Get Instead of a Number

**Alexa:** *"Air quality is moderate — AQI 87."*

**This ability:** *"Air quality is moderate this morning at 87, but grass pollen is high at 78 grains per cubic meter. For your hay fever, staying indoors until mid-morning will help — the best window to be outside today is after 6pm when pollen drops significantly."*

The response is built around your conditions and pollen triggers — if grass doesn't bother you, you won't hear about it.

---

## Background Daemon

Two proactive alert windows per day:

### Morning Alert (at your set time)
Fires when AQI or pollen is above your threshold. Includes:
- Overall AQI and label
- Condition-specific concern (ozone for asthma, pollen type for hay fever)
- Best outdoor time window based on the hourly forecast
- Actionable recommendation

**Example — bad day for hay fever:**
> *"Morning heads up. Air quality is moderate but grass pollen is very high today — 210 grains per cubic meter. If grass triggers your hay fever, your morning walk is better saved for after 7pm when it drops. Consider taking your antihistamine before you head out."*

### Evening Prep Alert (at 8pm)
Fires the night before a bad day — uniquely allows you to take preventive medication before bed so it's working by morning.

**Example:**
> *"Quick heads up for tomorrow — air quality is forecast at 145, poor, with very high tree pollen. If you take an antihistamine, tonight before bed is the best time to take it so it's fully working by morning."*

The evening alert only fires if tomorrow's forecast crosses your threshold.

---

## On-Demand Questions

**Activity check:**
> *"Is it safe to run?"*
> "Not ideal right now — ozone is elevated at 68 μg/m³ which can affect asthma. If you want to run outside, this morning before 10am or after 6pm will be significantly better."

**Windows advice:**
> *"Should I keep my windows closed?"*
> "Yes, I'd keep them closed — tree pollen is high right now and that's one of your triggers. Open them in the evening after 7pm when pollen settles."

---

## Data Source

| Source | Coverage | Key required |
|---|---|---|
| [Open-Meteo Air Quality](https://air-quality-api.open-meteo.com) | Global — hourly AQI, ozone, PM2.5, PM10 | None |
| [Open-Meteo Geocoding](https://geocoding-api.open-meteo.com) | Global city lookup | None |

Pollen data: grass (Poaceae), tree (birch proxy), weed (ragweed proxy) — grains/m³, hourly, 2-day forecast.
