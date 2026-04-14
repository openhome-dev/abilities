# Airthings Air Quality

Check the indoor air quality readings from your [Airthings](https://www.airthings.com/) devices by voice.

Reads CO2, VOC, radon, PM2.5, temperature, humidity, and pressure from any Airthings device on your account and speaks a plain-English summary — flagging anything that exceeds health guidelines.

## Features

- **Auto-setup** — edit the file once to add your credentials; they are saved to persistent file storage so the file never needs to be touched again
- **Multi-device support** — lists all devices and lets you pick one (or say "all")
- **Health threshold flagging** — CO2, VOC, PM2.5, radon, and humidity are pre-checked against WHO/EPA/EU guidelines before being passed to the LLM
- **Fahrenheit support** — temperature is automatically converted from Celsius for users in US/America timezones
- **Stale data warning** — if a device hasn't synced in over an hour, you'll be told the readings may be outdated
- **Multi-device fetching** — readings for multiple devices are fetched sequentially, one after the other

## Setup

### 1. Create an API client

1. Log in to [dashboard.airthings.com](https://dashboard.airthings.com).
2. Go to **Integrations → API Integration**.
3. Create a new client and copy the **Client ID** and **Client Secret**.

### 2. Add your credentials

Open `main.py` and replace the placeholders near the top of the file:

```python
AIRTHINGS_CLIENT_ID = "YOUR_CLIENT_ID_HERE"
AIRTHINGS_CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"
```

That's the only edit you'll ever need to make. On first run the ability saves your credentials to persistent file storage and reads from there from then on.

> **Important:** If you skip this step the ability will tell you it isn't set up yet and stop. You must replace both placeholder values with your real credentials before using it.

### 3. Set trigger phrases in the OpenHome dashboard

Suggested phrases:
- "check air quality"
- "how's the air in here"
- "airthings reading"
- "check my Airthings"

## Usage

**Single device:**
> "Hey, check the air quality."

The ability reads the device immediately and speaks a summary.

**Multiple devices:**
> "Hey, check the air quality."
> *"I found 3 devices: Living Room, Bedroom, Basement. Which one would you like, or say 'all' for all of them?"*
> "Living room."

## Health Thresholds

Values that exceed these guidelines are flagged `[HIGH]` or `[LOW]` in the LLM prompt so they're called out in the spoken response.

| Sensor | Threshold | Source |
|--------|-----------|--------|
| CO2 | > 1000 ppm | WHO guideline |
| VOC | > 250 ppb | General indoor air quality guideline |
| PM2.5 | > 12 µg/m³ | EPA annual standard |
| Radon | > 100 Bq/m³ | EU Radon Directive reference level |
| Humidity | < 30% or > 60% | Comfort / mold prevention range |

## Supported Sensors

| Sensor | Unit |
|--------|------|
| CO2 | ppm |
| VOC | ppb |
| PM1 / PM2.5 | µg/m³ |
| Radon (short-term avg) | Bq/m³ |
| Temperature | °C (or °F for US timezones) |
| Humidity | % |
| Pressure | hPa |

Not all Airthings models include every sensor — only values your device actually provides are reported. Unknown sensor keys returned by the API are included as-is so newer Airthings hardware works without a code update.

## Requirements

- Python `requests` library (standard in OpenHome)
- An Airthings account with at least one registered device
