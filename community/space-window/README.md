# Space Window

A sky-watching ability that tells you exactly what's happening above your location tonight — ISS passes, aurora activity, and rocket launches — and proactively alerts you before anything good happens so you never miss it.

Say "space window" once, set your city, and it handles the rest: ISS alerts 10 minutes before a visible pass, aurora alerts when the Kp index spikes high enough for your latitude, and launch countdowns 24 hours and 1 hour before liftoff.

## Setup

1. Get a free API key at [n2yo.com](https://www.n2yo.com/login/register/) (required for ISS pass tracking)
2. In OpenHome, go to **Settings → API Keys** and add your key as `n2yo_api_key`
3. Say "space window" and tell it your city — that's it

> **Note:** Aurora and launch alerts work without any API key. Only ISS pass tracking requires N2YO.

## Trigger Phrases

- `space window` / `sky tonight` / `what's up tonight`
- `ISS tonight` / `ISS passing` / `when's the ISS` / `spot the station`
- `aurora tonight` / `northern lights` / `aurora forecast`
- `any launches` / `rocket launches` / `launch tonight`
- `space events` / `sky events` / `night sky`
- `set my location` / `change my location`

## Features

**Proactive Alerts**
- ISS: alerts ~10 minutes before any visible pass — rise time, direction, peak elevation, duration
- Aurora: alerts when Kp index exceeds your latitude's visibility threshold (auto-set, adjustable)
- Launches: alerts 24 hours before and 1 hour before any confirmed rocket launch
- Morning brief: daily 9am summary of what's happening in the sky today

**Interactive Queries**
- TONIGHT: full sky summary — ISS passes, aurora status, and any launches in the next 24 hours
- ISS: next 2 days of visible passes with times, compass directions, elevation, and quality rating
- AURORA: current Kp index, whether it's high enough to see aurora at your latitude, and your threshold
- LAUNCHES: upcoming confirmed launches in the next 7 days with rocket name, site, and countdown
- SETUP: set or change your city — used for all location-aware features
- ALERTS: toggle ISS / aurora / launch alerts on or off, adjust minimum elevation threshold, set aurora Kp threshold

**Smart Details**
- ISS passes rated by quality: great (≥60°), good (≥40°), fair (≥30°) — only alerts on passes worth going outside for
- Aurora threshold auto-calculated from your latitude — higher latitudes need lower Kp
- Launch alerts use 40-minute poll overlap window so no pass falls through between cycles
- All times shown in your local timezone
- 80+ cities in the built-in map; LLM fallback for anything else
- Aurora and launch monitoring require zero API keys — always active once location is set

## Example Conversation

> **You:** space window
>
> **Assistant:** First tell me where you are — say 'set my location' and your city name.
>
> **You:** set my location to London
>
> **Assistant:** Set to London. I'll alert you before ISS passes, when aurora picks up, and before rocket launches. At your latitude, aurora becomes visible around Kp 6 or higher — I'll watch for that.

---

> **You:** what's up tonight
>
> **Assistant:** Checking tonight's sky for London... ISS passes at 9:47pm — great pass, 52 degrees max, rises NW, sets SE, 4 minutes, plus 1 more pass tonight. Aurora quiet — Kp at 2.1, you'd need 6 or above to see it. SpaceX Falcon 9 launches at 3:15am from Cape Canaveral in 8 hours.

---

> **You:** when's the ISS
>
> **Assistant:** ISS passes London 2 times in the next 2 days. 9:47pm — great pass, peaks 52 degrees, rises NW, sets SE, 4 minutes visible. 11:23pm — fair pass, peaks 28 degrees, rises N, sets NE, 2 minutes visible.

---

> **You:** aurora tonight
>
> **Assistant:** Aurora is quiet — Kp is 2.4 right now. At your latitude you'd need 6 or above, so you're 4 points away. I'll alert you if it spikes.

---

> **[Background alert, proactive]**
>
> **Assistant:** ISS passes London in 9 minutes. Rises northwest at 9:47, peaks 52 degrees — great pass, 4 minutes visible. Head outside now.

---

> **[Background alert, aurora]**
>
> **Assistant:** Aurora alert — Kp index just hit 7, which is high enough to see northern lights from London. Look north, away from city lights. Activity can fade fast.

## Notes

- ISS pass quality depends on your sky being dark and the ISS being in sunlight — the N2YO API only returns visual passes that meet both conditions
- Aurora visibility also depends on cloud cover and light pollution — Kp threshold is a necessary but not sufficient condition
- The background daemon runs every 30 minutes — ISS alerts use a 40-minute look-ahead window so nothing falls between polls
- Supports southern hemisphere aurora (southern lights) — threshold logic uses absolute latitude
