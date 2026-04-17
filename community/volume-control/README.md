# Volume Control

Control your Mac's volume with voice commands via OpenHome LocalLink.

## Requirements

- **LocalLink client** running on your Mac (`~/openhome/start-locallink.sh`)
- Uses `exec_local_command()` to run `osascript` volume commands locally

## Trigger Words

- "volume"
- "turn up"
- "turn down"
- "louder"
- "quieter"
- "mute"
- "unmute"
- "raise volume"
- "lower volume"
- "volume control"

## Commands

- **"raise" / "louder" / "turn up"** — increase volume by 10%
- **"lower" / "quieter" / "turn down"** — decrease volume by 10%
- **"mute" / "silent"** — set to 0
- **"max" / "full"** — set to 100
- **"set to 50"** — set to a specific percentage
