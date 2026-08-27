# Sleep Quality Tracker

A personal sleep coach that learns your patterns over time. Log your sleep each morning, track evening habits, and get personalised insights drawn from your own data — not generic advice.

## Trigger Phrases

- `"how did I sleep"`
- `"sleep check-in"`
- `"log my sleep"`
- `"sleep report"`
- `"sleep patterns"`
- `"tips for tonight"`
- `"evening habits"`
- `"sleep history"`

## How It Works

**First time:** Setup takes 30 seconds — your name and sleep goal. From there, say "how did I sleep" every morning.

**Morning check-in (3 questions, under 60 seconds):**
1. How many hours did you sleep?
2. Quality from 1 to 10?
3. Anything to note? (optional)

The ability extracts hours from natural speech — "went to bed around midnight, up at seven" works just as well as "seven hours."

**Evening habits (optional, 4 yes/no questions):**
Caffeine after 3pm, exercise, stress level, screen time before bed. These get correlated with your next-morning quality rating to surface personal patterns.

**Reports (after 5+ nights):**
Not generic advice — actual correlations from your data. "On nights you exercised AND skipped caffeine after 3pm, your quality averaged 8.1 — that's 1.8 points above your baseline."

**Sleep debt tracker:**
Every check-in and report tells you how many hours ahead or behind you are against your personal goal this week.

## Background Daemon

| Time | Action |
|---|---|
| 7:00 – 8:00 AM | Morning nudge if sleep not yet logged |
| 9:00 – 10:00 PM | Evening habit nudge if habits not yet logged |
| Sunday 8:00 – 9:00 AM | Weekly pattern summary |

## What Makes It Different from Alexa

| | Alexa | Sleep Quality Tracker |
|---|---|---|
| Remembers last night | No | Yes — every night |
| Personalised correlations | No | Yes — from your own data |
| Sleep debt tracking | No | Yes — cumulative vs your goal |
| Gets smarter over time | No | Yes — week 3 is different from week 1 |
| Proactive morning prompt | Basic alarm | Conversational check-in |
| Evening habit coaching | None | Habit-aware, correlation-driven |

## Setup

No API keys required. All pattern analysis uses the built-in LLM.

## Example Sessions

**First morning:**
> User: "how did I sleep"
> AI: "Morning Hassan! How many hours did you sleep?"
> User: "went to bed at midnight, up at half six"
> AI: "And how do you feel — 1 to 10?"
> User: "about a 6, a bit groggy"
> AI: "Anything to note? Say 'nothing' to skip."
> User: "nothing"
> AI: "Logged — 6.5 hours, 6 out of 10. 1 night tracked so far."

**After 2 weeks:**
> User: "sleep report"
> AI: "Here's your sleep picture for the last 14 nights, Hassan. Average 7.1 hours, quality 6.8 out of 10. Best night: 2026-08-02 — 8.5h, rated 9. Worst night: 2026-07-28 — 5.5h, rated 4. You're 3.5 hours in sleep debt against your 8-hour goal this week. Based on your data: on nights you exercised and skipped caffeine after 3pm, you averaged 8.2 out of 10 — that's 1.4 points above your baseline. The pattern holds across 6 nights."

**Evening:**
> User: "evening habits"
> AI: "Quick habit check, Hassan. Caffeine after 3pm today?"
> User: "no"
> AI: "Any exercise today?"
> User: "yeah, went for a run"
> AI: "How stressed are you feeling tonight?"
> User: "pretty calm"
> AI: "Screen time in the last hour?"
> User: "yeah been on my phone"
> AI: "Logged. I'll compare this with how you sleep tonight. Sleep well!"
