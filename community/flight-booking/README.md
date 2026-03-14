# Flight Booking

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hassan1731996-lightgrey?style=flat-square)

Search and book flights entirely by voice using the Duffel API. Supports one-way and round-trip searches, reads back the top 3 options, collects passenger details, and creates a hold booking — no payment required at voice time.

## Features

- **Natural language search** — "Book me a flight from London to Dubai next Friday"
- **One-way & round-trip** — detects trip type automatically from your request
- **Top 3 results** — sorted by price, read back in a voice-friendly format
- **Full booking flow** — collects passenger name, date of birth, email, and phone
- **Hold booking** — creates a confirmed reservation without charging you. Pay later via email link
- **Booking history** — saves all booking references to `flight_booking_history.json`
- **City name resolution** — say "London" or "New York", not just airport codes

## Setup

1. Sign up for a free account at [duffel.com](https://duffel.com)
2. Create a test API token in the Developer settings
3. Open `main.py` and replace `duffel_test_YOUR_KEY_HERE` with your token
4. Upload to the Live Editor

## Trigger Words

`book a flight`, `search for flights`, `find me a flight`, `flight to`, `book flights`, `i need a flight`, `fly to`, `check flights`

## Example Conversation

> **User:** "Book me a flight from London to Dubai next Friday"
> **AI:** "Let me search for flights, one moment."
> **AI:** "Option 1: Emirates. Departs 2026-03-20 at 08:00, arrives at 18:00. Non-stop. USD 420.
>          Option 2: British Airways via Heathrow. Departs at 10:00, arrives at 22:00. 1 stop. USD 380.
>          Option 3: Flydubai. Departs at 14:00, arrives at 23:30. Non-stop. USD 310.
>          Which option — 1, 2, or 3? Or say none to search again."
> **User:** "Option 3"
> **AI:** "What's the passenger's first name?"
> **User:** "John"
> **AI:** "And the last name?"
> ...
> **AI:** "Booking Flydubai from LHR to DXB on 2026-03-20 for John Smith. Total USD 310. This creates a hold — you'll pay at checkout. Confirm?"
> **User:** "Yes"
> **AI:** "Done! Your booking reference is ORD-123456. Check your email for payment details."

## Storage

- `flight_booking_history.json` — persistent log of all booking references and details

## Notes

- Uses Duffel's **hold** booking type — no payment is processed by this ability
- Flights via Duffel's test environment use "Duffel Airways" (IATA: ZZ) for sandbox testing
- Switch to a live API token for real bookings (handle with care — hold bookings are real reservations)
