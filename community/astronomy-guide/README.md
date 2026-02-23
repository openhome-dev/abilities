# Astronomy & Stargazing Guide

Provides stargazing information including moon phase, sunrise/sunset times, and planet visibility. Uses the IPGeolocation Astronomy API and NASA APOD.

## Triggers

- "stargazing"
- "astronomy"
- "what's in the sky"
- "moon phase"
- "planets tonight"
- "night sky"

## Features

- Moon phase and illumination percentage
- Sunrise, sunset, moonrise, and moonset times
- LLM-enriched planet visibility predictions
- NASA Astronomy Picture of the Day description
- Follow-up questions about specific celestial objects

## Setup

For full functionality, set these environment variables:

1. **IPGeolocation API** (free, 1000 req/day):
   - Register at https://ipgeolocation.io/
   - `export IPGEO_API_KEY=your_key_here`

2. **NASA API** (optional, uses DEMO_KEY by default):
   - Register at https://api.nasa.gov/
   - `export NASA_API_KEY=your_key_here`

The ability works without API keys using LLM knowledge alone, but results are more accurate with the astronomy API.

## Example Usage

> "What's in the sky tonight?"
> "What's the moon phase?"
> "Tell me about Mars tonight"
> "When does the sun set?"
