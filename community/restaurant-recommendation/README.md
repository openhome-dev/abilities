# Restaurant Finder Ability

An OpenHome voice assistant ability that helps users find nearby restaurants using the Foursquare Places API.

## What It Does

When triggered, the ability asks the user what kind of food they're looking for and where. It searches Foursquare and reads back a summary of the top 3 results. The user can then ask for more details on a specific restaurant (address, phone number, hours), search for something else, or exit.

## How to Use

Trigger the ability by saying something food-related, like:
- "I'm looking for sushi in downtown Chicago"
- "Find me a pizza place near Hollywood"
- "Recommend a ramen restaurant in New York"

After receiving recommendations, you can:
- Ask for details on a specific result ("tell me more about the first one")
- Search for something different ("find me Italian food instead")
- Exit by saying "done", "stop", "bye", "no thanks", or "nothing"

## Setup

1. Get a free API key from [Foursquare Developer Console](https://foursquare.com/developers)
2. Replace `your_foursquare_api_key_here` in `main.py` with your key
