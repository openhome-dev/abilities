# Plant Care Reminder

A voice-first plant tracking and care reminder system. Track your plants, log watering, get species-specific care tips, and see which plants need attention.

## Triggers

- "plant care"
- "water my plants"
- "plant reminder"
- "gardening"
- "plant tracker"

## Features

- Add plants with name, species, and location
- Automatic watering interval suggestions based on species
- Log watering events and track schedules
- Check which plants are overdue for watering
- LLM-generated species-specific care tips
- Remove plants with voice confirmation
- Persistent storage across sessions

## Setup

No API keys required. Plant data is stored in `plant_care_data.json` using the platform file helpers.

## Example Usage

> "I got a new monstera for the living room"
> "I just watered my monstera"
> "What plants need watering?"
> "How do I care for my fiddle leaf fig?"
> "Remove my succulent"

## Data Format

Plant data is stored as JSON:
```json
{
  "plants": [
    {
      "id": "uuid",
      "name": "Monstera",
      "species": "Monstera deliciosa",
      "location": "living room",
      "last_watered": "2026-02-20",
      "water_interval_days": 7,
      "last_fertilized": "",
      "notes": ""
    }
  ]
}
```
