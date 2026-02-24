# Air Quality & UV Index Checker

Fetches real-time air quality data from the World Air Quality Index (WAQI) API. Reports AQI levels, individual pollutants, and health advice.

## Triggers

- "air quality"
- "air pollution"
- "aqi"
- "uv index"
- "is the air safe"
- "pollution levels"

## Features

- Real-time AQI for any city worldwide
- Individual pollutant levels (PM2.5, PM10, O3, NO2, CO, SO2)
- Health advice based on AQI ranges
- Option to check multiple cities in one session

## Setup

Requires a free WAQI API token:

1. Register at https://aqicn.org/data-platform/token/
2. Set the environment variable: `export WAQI_API_TOKEN=your_token_here`

## Example Usage

> "What's the air quality in Beijing?"
> "Is the air safe to go outside?"
> "Check pollution in New York"

## AQI Ranges

| AQI | Level | Health Implication |
|-----|-------|--------------------|
| 0-50 | Good | Enjoy outdoor activities |
| 51-100 | Moderate | Acceptable for most |
| 101-150 | Unhealthy for Sensitive Groups | Reduce prolonged outdoor exertion |
| 151-200 | Unhealthy | Everyone may experience effects |
| 201-300 | Very Unhealthy | Avoid outdoor activities |
| 301+ | Hazardous | Stay indoors |
