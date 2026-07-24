# Sports Score Alert

Proactive sports daemon that watches your followed teams and interrupts you when something actually happens — game starts, your team scores, comeback in progress, final result. Not when you remember to ask.

Covers NFL, NBA, MLB, NHL, Premier League, La Liga, Bundesliga, MLS, and more — with cricket support via a free CricAPI key.

---

## Trigger Phrases

| What you say | What happens |
|---|---|
| "follow Pakistan cricket" | Add a team — setup league + optional API key for cricket |
| "follow Manchester United Premier League" | Add a soccer team with league |
| "follow the Lakers" | Add an NBA team |
| "what's the score?" | Live score for your followed teams right now |
| "who do they play next?" | Next scheduled game |
| "what was the result?" | Most recent completed game |
| "unfollow Manchester United" | Remove a team from alerts |

---

## Setup

Say "follow" and any team name. The ability handles the rest:

- **Soccer** — asks which league (Premier League, La Liga, Bundesliga, MLS, etc.)
- **Cricket** — asks for a free CricAPI key if not already saved (100 req/day free at cricapi.com)
- **US sports (NFL, NBA, MLB, NHL)** — detected automatically, no key needed

You can follow multiple teams. Say "follow the Lakers" then "follow Man United" in the same session.

---

## What Makes This Different From Alexa

| | Alexa | This Ability |
|---|---|---|
| Score updates | On-demand only | Proactive interrupt the moment your team scores |
| Pre-match | None | Alert 30 minutes before kickoff |
| Alert content | "Lakers lead 98-91" | "Lakers on a 12-2 run — 98-91 with 4 minutes left" |
| Comeback detection | None | Special alert when the gap closes 10+ points/runs/goals |
| Final result | Only when asked | Fires the moment the game ends |
| Cricket | Not available | Full international + domestic coverage |
| Poll intelligence | N/A | 60s live · 5 min pre-game · 30 min idle |

---

## Background Daemon

The daemon runs continuously and watches all your followed teams. Smart polling avoids wasted API calls:

- **60 seconds** — when any followed team has an active game
- **5 minutes** — when a game starts within 2 hours  
- **30 minutes** — no games happening

### Alert Types

| Event | Example spoken alert |
|---|---|
| Pre-match (30 min out) | "Pakistan play India in 30 minutes — T20 World Cup semifinal, get ready." |
| Game start | "Underway at Old Trafford — Manchester United vs Arsenal in the Premier League." |
| Score update | "Goal! United score in the 87th minute — 2-1 up with three minutes to go." |
| Comeback | "Comeback alert — Arsenal have scored twice in 6 minutes. Level at 2-2." |
| Halftime | "Halftime — United lead 1-0 after a tight first half." |
| Final result | "Full time — Manchester United win 2-1 at Old Trafford. Three points." |

All alerts are LLM-composed and include match context — not just a score.

---

## Data Sources

| Source | Coverage | Key required |
|---|---|---|
| [ESPN Unofficial API](https://site.api.espn.com) | NFL, NBA, MLB, NHL, global soccer | None |
| [CricAPI](https://cricapi.com) | International + domestic cricket (PSL, IPL, BBL, etc.) | Free (100 req/day) |

### Getting a CricAPI Key

1. Sign up at [cricapi.com](https://cricapi.com)
2. Copy your API key from the dashboard
3. Say "follow cricket" — the ability will prompt you to paste it once

The key is stored securely in OpenHome's key store and never hardcoded.

---

## Supported Leagues (Soccer)

Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, UEFA Champions League, and any other ESPN-covered competition.
