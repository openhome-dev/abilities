# MTA Next Train

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@chadnewbry-lightgrey?style=flat-square)

Live New York City subway arrivals for OpenHome. Ask for your next train using a saved default station, or ask for a specific line and station on demand.

## What It Does

- Reads live subway arrivals from `SubwayInfo.nyc` with no API key required
- Saves one default station so the shortest prompt can be "when's my next train?"
- Handles explicit station requests like "next Q train at Union Square"
- Supports simple direction filters like "northbound" or "downtown"
- Lets the user change their default station by voice

## Trigger Words

- `next train`
- `next subway`
- `when's my next train`
- `subway arrivals`
- `mta`
- `mta next train`

## Setup

This ability uses `SubwayInfo.nyc` and does not require an API key.

Install the ability in OpenHome, then set a default station once:

- "set my default station to Astor Place"
- "use 14 street union square as my default station"

Then the main demo becomes:

- "when's my next train?"

## Example Voice Commands

- "When's my next train?"
- "Next Q train at Union Square"
- "When is the next northbound 6 at Astor Place?"
- "Set my default station to Fulton Street"
- "Change my default station to Jay Street MetroTech"

## Technical Notes

- Station search and live arrivals come from `SubwayInfo.nyc`
- No API key or account setup is required
- The local test harness includes fixture-based end-to-end checks plus an optional live mode
