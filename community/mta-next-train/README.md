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

- `mta next train`
- `next subway`
- `subway arrivals`
- `nyc mta`

## Setup

This ability uses `SubwayInfo.nyc` and does not require an API key.
