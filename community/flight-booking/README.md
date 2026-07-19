# Flight Booking

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hassan1731996-lightgrey?style=flat-square)

Search and book flights entirely by voice using the Duffel API. Supports one-way and round-trip searches, reads back the top 3 options, collects passenger details, and creates a hold booking — no payment required at voice time.

## Features

- **Natural language search** — "Book me a flight from London to Dubai next Friday"
- **One-way & round-trip** — detects trip type automatically from your request
- **Top 3 results** — sorted by price, read back with 12-hour times
- **Full booking flow** — name + DOB in one prompt, email + phone in one prompt (grouped for speed)
- **Hold booking** — creates a confirmed reservation without charging you. Pay later via the airline
- **Cancel at any point** — say "never mind" or "cancel" at any step to exit cleanly
- **Change at confirmation** — say "change the date" or "wrong name" after the summary to correct before booking
- **Booking history** — saves all booking references to `flight_booking_history.json`
- **City name resolution** — say "London" or "New York", not just airport codes

## Setup

1. Sign up for a free account at [duffel.com](https://duffel.com)
2. Create a test API token in the Developer settings
3. Open `main.py` and replace `duffel_test_YOUR_KEY_HERE` with your token
4. Upload to the Live Editor

> **Important:** Never commit your real API key to a public repo. The placeholder is intentional.

## Trigger Words

`book a flight`, `search for flights`, `find me a flight`, `flight to`, `book flights`, `i need a flight`, `fly to`, `check flights`

## Example Conversation

> **User:** "Book me a flight from London to Dubai next Friday"
> **AI:** "Searching one-way economy flights from London to Dubai on March 20th. One moment."
> **AI:** "I found three options. Option 1: Emirates. Departs at 8:00 AM, arrives at 6:00 PM. Non-stop. USD 420. Option 2: British Airways. Departs at 10:00 AM, arrives at 10:00 PM. 1 stop. USD 380. Option 3: Flydubai. Departs at 2:00 PM, arrives at 11:30 PM. Non-stop. USD 310. Which option — 1, 2, or 3? Or say none to change something."
> **User:** "Option 3"
> **AI:** "Great choice. I'll need a few details for the booking. What's the passenger's full name and date of birth?"
> **User:** "John Smith, born March 5th 1990"
> **AI:** "What's your title? Mister, Missus, Miss, Ms, or Doctor?"
> **User:** "Mister"
> **AI:** "And what's the email address and phone number, including country code?"
> **User:** "john@example.com, plus 44 7700 900 123"
> **AI:** "Booking Flydubai from London to Dubai on March 20th for John Smith. Total USD 310. This holds the seat — payment must be completed before the airline's deadline. Say confirm to book, cancel to stop, or tell me what you'd like to change."
> **User:** "Confirm"
> **AI:** "Done! Your booking reference is O, R, D, 1, 2, 3. You must complete payment by April 1st to confirm your seat."

## Storage

- `flight_booking_history.json` — persistent log of all booking references and route details

## Known Limitations

| Limitation | Detail |
|---|---|
| Sandbox flights | Test API keys only return fictional "Duffel Airways" flights. Switch to a live key for real airlines. |
| Hold bookings only | This ability creates a hold (pay-later) reservation. Immediate payment is not supported by design. |
| Hold availability | Not all airlines support hold bookings. The ability filters to holdable offers only; if none are available on a route, all offers are shown (but booking may require payment outside this ability). |
| 1 adult passenger | Multi-passenger booking is a planned v2 feature. |
| Regional coverage | Best coverage for major international routes. Some domestic or low-cost carriers in certain regions may not appear. See [duffel.com/airlines](https://duffel.com/airlines) for the full list. |

## Notes

- Uses Duffel's **hold** booking type — no payment is processed by this ability
- Switch to a live API token for real bookings (hold bookings are real reservations with the airline)
- The ability retries automatically on Duffel 429/5xx errors before surfacing a failure to the user
