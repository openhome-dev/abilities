# Earthquake & Seismic Monitor

Fetches recent earthquake data from the USGS Earthquake API for any location. Uses Nominatim geocoding to convert city names to coordinates. No API key required.

## Triggers

- "earthquake"
- "seismic activity"
- "earthquake monitor"
- "recent earthquakes"
- "earthquake alert"

## Features

- Checks for earthquakes within 500km of any location
- Reports magnitude 2.5+ events from the past 7 days
- LLM-generated natural language summaries
- Uses the free USGS GeoJSON API

## Setup

No API keys required. Uses the publicly available USGS Earthquake API and Nominatim geocoding.

## Example Usage

> "Any earthquakes near Los Angeles?"
> "Check seismic activity in Tokyo"

## How It Works

1. User specifies a location
2. Geocodes the location using Nominatim
3. Queries USGS for magnitude 2.5+ earthquakes within 500km in the past 7 days
4. LLM summarizes the results in natural language
5. Single-shot pattern — speaks result and exits

## API Reference

- USGS Earthquake API: https://earthquake.usgs.gov/fdsnws/event/1/
- Nominatim Geocoding: https://nominatim.openstreetmap.org/
