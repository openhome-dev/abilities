# Philips Hue Control


## What It Does
Controls Philips Hue lights over the local Hue Bridge API using natural voice commands.  
Supports turning lights on/off, brightness, color, white temperature, scene activation, status checks, and all-lights commands.

## Suggested Trigger Words
- "hue lights"
- "turn on the lights"
- "turn off the lights"
- "control the lights"
- "light control"

## Setup
- Have a Philips Hue Bridge and lights configured in the official Hue app.
- Ensure OpenHome runtime and Hue Bridge are on the same local network.
- First run may ask for the bridge IP and pairing button press.
- Press the physical button on the Hue Bridge when prompted to complete pairing.

## How It Works
After trigger, the ability checks bridge connection, pairs if needed, then enters a command loop.  
It classifies voice intent, resolves room/light/scene names, calls Hue local API endpoints, speaks confirmation, and resumes normal flow on exit.

## Example Conversation
> **User:** "Hue lights"  
> **AI:** "Let me find your Hue Bridge."  
> **User:** "Turn on the living room"  
> **AI:** "Living room on."  
> **User:** "Set bedroom to 50 percent"  
> **AI:** "Bedroom at 50 percent."  
> **User:** "Stop"  
> **AI:** "Lights staying as they are. See you."
