# Life Admin & Renewals Tracker

Never miss a renewal again. Track passports, MOTs, insurance, warranties, subscriptions — anything with an expiry date. Log once by voice, get proactive reminders automatically. No apps, no calendar entries, no forgetting.

## Trigger Phrases

- `"life admin"` / `"my renewals"` / `"renewals tracker"`
- `"what's due soon"` / `"what's expiring"` / `"anything coming up"`
- `"add a renewal"` / `"track my passport"` / `"track my MOT"`
- `"due soon"` / `"expiring soon"`
- `"mark as renewed"` / `"subscription costs"`

## What It Tracks

| Category | Examples |
|---|---|
| Document | Passport, driving licence, ID card, work permit |
| Vehicle | MOT, car insurance, road tax, service interval |
| Home | Boiler service, lease renewal, contents insurance |
| Subscription | Netflix, Spotify, gym, software — with optional cost |
| Warranty | Phone, laptop, washing machine |
| Other | Anything else with an expiry date |

## How It Works

**First time:** Quick setup — just your name.

**Adding an item (3 exchanges, never more):**
> User: "Add a renewal"
> AI: "What would you like to track?"
> User: "My passport"
> AI: "When does it expire?"
> User: "March 2027"
> AI: "Got it — Passport logged, expires in about 7 months. I'll remind you 90, 30, and 7 days before."

Natural date input always works: "next March", "in 3 years", "2027-03-15", "March 2027", "sometime next year".

If you mention the item AND date in your first sentence ("track my passport, expires March 2027"), setup is a single exchange.

**Checking what's due:**
> User: "What's due soon?"
> AI: "Your MOT in 8 days, your car insurance in 22 days, and your passport in about 4 months. Plus 2 more items further out."

Items sorted by urgency — most critical always spoken first.

**Renewing an item:**
> User: "Mark my MOT as renewed"
> AI: "When is the new expiry date?"
> User: "Year from now"
> AI: "Done — MOT updated. Next renewal in about a year."

Renewal chaining: the ability automatically asks for the next date and continues the tracking cycle.

**Checking subscription costs:**
> User: "Subscription costs"
> AI: "You have 4 subscriptions: Netflix £11 a month, Spotify £10 a month, gym £35 a month, Adobe £55 a month. That's £111 a month or £1,332 a year."

**Checking one item:**
> User: "What's the status on my passport?"
> AI: "Your Passport expires on 2027-03-15 — that's in about 7 months."

## Background Daemon — Automatic Reminders

Runs hourly. No action needed from you.

| Days to expiry | What happens |
|---|---|
| 90 days | First heads-up (fires once) |
| 30 days | Second alert (fires once) |
| ≤ 7 days | Daily urgent alert until renewed |
| Expired | Daily reminder until renewed |

Multiple urgencies are grouped into one message:
> "Urgent — 2 things need attention: your MOT tomorrow and your car insurance in 5 days."

## What Makes It Different from Alexa

| | Alexa | Life Admin Tracker |
|---|---|---|
| Remembers renewals across sessions | No | Yes — permanently |
| Proactive expiry alerts | No | Yes — automatic |
| Natural date input ("next March") | No | Yes — LLM extraction |
| Grouped urgency alerts | No | Yes |
| Subscription cost intelligence | No | Yes |
| Renewal chaining (auto-asks next date) | No | Yes |
| Multiple urgencies in one message | No | Yes |

## Setup

No API keys required. Runs entirely on the built-in LLM and persistent storage.

## Example Sessions

**Morning, 6 items tracked:**
> Background daemon: "Heads up — your MOT expires in 28 days and your home insurance in 3 months."

**Adding a subscription:**
> User: "Track my Spotify"
> AI: "When does it renew?"
> User: "Every month, next renewal is September"
> AI: "How much does Spotify cost? Say 'skip' to leave that out."
> User: "£10 a month"
> AI: "Got it — Spotify logged at £10/month, renewing in about a month. I'll remind you 90, 30, and 7 days before."

**Removing something:**
> User: "Remove Netflix"
> AI: "Removed Netflix."
