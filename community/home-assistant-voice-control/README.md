# Home Assistant Voice Control

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@YoFoSolo-lightgrey?style=flat-square)

## What It Does

Voice-controlled interface for Home Assistant. Speak natural commands to control lights, switches, covers, sirens, media players, check sensor states, and add items to your shopping list. Uses LLM-based intent classification with fuzzy entity name matching — no exact names needed.

## Suggested Trigger Words

- "smart home"
- "home assistant"
- "control my home"
- "home control"

## Setup

1. **Home Assistant** must be accessible via REST API on your local network
2. Generate a **Long-Lived Access Token** in Home Assistant:
   - Go to your HA instance → Profile (bottom-left user icon) → Long-Lived Access Tokens → Create Token
3. Open `main.py` and replace `YOUR_HOME_ASSISTANT_TOKEN_HERE` with your token
4. Update `HA_URL` if your Home Assistant is not at `http://192.168.68.60:8123`

## How It Works

1. On trigger, fetches all entity states from the HA REST API
2. Filters to actionable domains (lights, switches, covers, sensors, sirens, media players, todo lists)
3. Greets you with device count
4. Enters a conversation loop — speak commands naturally
5. LLM classifies your intent and fuzzy-matches entity names from the full list
6. Executes the action via HA REST API and speaks the result
7. Dangerous actions (gate, sirens) require voice confirmation before execution
8. Say "done", "stop", or "goodbye" to exit

## Supported Commands

| Voice Command | What Happens |
|---|---|
| "Turn on/off the [device]" | Toggles lights, switches, etc. |
| "Toggle the [device]" | Toggles device state |
| "Open/close the gate" | Controls covers (with confirmation) |
| "Is there motion at [camera]?" | Reads binary sensor state |
| "What's the [sensor] reading?" | Reports sensor value |
| "Sound/stop the siren" | Controls sirens (with confirmation) |
| "Add milk to the shopping list" | Adds item to HA todo list |

## Example Conversation

> **User:** "Smart home"
> **AI:** "Home Assistant connected. I found 24 devices across 5 categories. What would you like to do?"
> **User:** "Turn on the floodlight"
> **AI:** "Turning on Camera 1 Floodlight."
> **User:** "Is there motion at the front door?"
> **AI:** "No motion detected at the front door."
> **User:** "Open the gate"
> **AI:** "Are you sure you want to open the gate?"
> **User:** "Yes"
> **AI:** "Opening the driveway gate."
> **User:** "Add cat food to the shopping list"
> **AI:** "Added cat food to your shopping list."
> **User:** "Done"
> **AI:** "Home Assistant control ended. Have a good one."
