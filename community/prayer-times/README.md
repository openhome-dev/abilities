# Prayer Times

A voice-activated Islamic prayer times assistant with automatic reminders.

## What It Does

**Skill** — Ask about prayer times using natural voice commands:
- "When is the next prayer?" → Tells you the upcoming prayer and its time
- "What are today's prayer times?" → Lists all five daily prayers + sunrise
- "When is Fajr?" → Specific prayer time lookup
- "Set my location to Istanbul, Turkey" → Configure your city

**Background Daemon** — Automatic prayer time reminders:
- 5-minute advance reminder before each prayer
- Notification when prayer time arrives
- Resets daily, fetches fresh times each day

## Setup

1. Upload the ability to OpenHome
2. Set trigger words in the dashboard (suggested below)
3. Say a trigger phrase — the ability will ask for your city on first use
4. Background reminders start automatically

## Suggested Trigger Words

```
prayer times, next prayer, when is fajr, when is dhuhr,
when is asr, when is maghrib, when is isha, salah time,
namaz vakti, prayer schedule
```

## API

Uses [Aladhan Prayer Times API](https://aladhan.com/prayer-times-api) — **free, no API key required**.

Supports multiple calculation methods:
| # | Method |
|---|--------|
| 1 | University of Islamic Sciences, Karachi |
| 2 | Islamic Society of North America (ISNA) — default |
| 3 | Muslim World League (MWL) |
| 4 | Umm Al-Qura University, Makkah |
| 5 | Egyptian General Authority of Survey |
| 13 | Diyanet İşleri Başkanlığı (Turkey) |

Change method by saying: "Change calculation method to Diyanet"

## Data Storage

Stores configuration and cached times in `prayer_data.json`:
- City and country
- Calculation method preference
- Last fetched prayer times (refreshed daily)

## Technical Details

- **Type:** Skill + Background Daemon (combo)
- **API:** Aladhan (free, no auth)
- **Dependencies:** `requests` (standard library in OpenHome runtime)
- **Background check interval:** 30 seconds
- **Reminder window:** 5 minutes before prayer

## Author

Mahsum Aktas — [@mahsumaktas](https://github.com/mahsumaktas)
