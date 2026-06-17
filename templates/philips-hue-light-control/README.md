# Philips Hue Light Control
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)
![Local](https://img.shields.io/badge/Category-Local-green?style=flat-square)

Control your Philips Hue bulb with your voice — no Hue Bridge, no internet required.

---

## How it works

When you trigger the ability, it connects to your bulb over Bluetooth and holds that connection open for the entire session. Every command you speak goes directly over the live connection, so responses are instant — there's no reconnect delay between commands.

Once connected, the ability reads what your specific bulb actually supports (on/off, brightness, colour temperature, colour) and only offers the controls that work with your hardware. A basic white bulb won't be offered colour commands, for example.

The ability understands natural language, so casual phrasing like "cozy vibe", "not so harsh", or "crank it up" all work, not just exact phrases.

When you exit, the connection is closed cleanly and you hear a goodbye.

---

## Connecting to your bulb

**First time:** the ability scans for nearby Hue bulbs and connects to the first one it finds. You'll hear spoken progress:
- "Scanning for your bulb."
- "Found it, connecting."
- "Connected to the bulb. What would you like to do?"

**After that:** it remembers your bulb and connects directly — no scanning, so startup is faster.

**If the remembered bulb is unavailable** (switched off, out of range, or replaced): it falls back to scanning and connects to any nearby Hue bulb.

---

## What you can do

### Turn the light on or off
- "turn it on" / "lights on" / "light it up"
- "turn it off" / "kill the lights" / "shut it off"

### Adjust brightness
Say a percentage, a descriptive word, or a specific level:
- "full" / "max" — 100%
- "bright" / "high" — ~86%
- "half" / "fifty percent" — 50%
- "dim" / "not so bright" — ~24%
- "brightness 75" — 75%
- "crank it up", "a little dimmer", "tone it down" — also understood

Spoken numbers work too: "brightness fifty", "ten percent", "one hundred".

### Change colour temperature (white light)
- "warmer" / "cozy" / "candle" — warmest setting
- "cooler" / "daylight" — coolest setting
- "reading light" — balanced mid-tone
- "4000 kelvin" — Kelvin values are converted automatically
- "temperature 350" — specific mired value

### Change colour (RGB bulbs only)
- "make it red" / "go blue" / "something orange"
- "set colour to purple"
- "255, 100, 50" — custom RGB values
- Named colours: red, green, blue, white, yellow, orange, pink, cyan, purple, violet, magenta

### Check status
- "what's the status" / "is it on" / "how bright is it"

### Exit
- "stop" / "bye" / "I'm done" / "that's all"

The connection closes cleanly and you hear "Disconnected from the bulb. Goodbye."

---

## Notes

- Works with one bulb at a time.
- BLE range is typically 10–15 metres through walls.
- **Your bulb must be in pairing mode** before first use. Here's when it is:
  - **Brand new bulb** — already in pairing mode by default.
  - **Factory reset bulb** — automatically enters pairing mode after a reset.
  - **Bulb already added to the Hue app** — once a bulb has been added to the Hue app at least once, it stays in a paired state and is ready to control over BLE.