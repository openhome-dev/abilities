# OpenHome DevKit LED Lights Control - Template
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)
![Local](https://img.shields.io/badge/Category-Local-green?style=flat-square)

## What This Is
**This is a template ability** that controls the onboard NeoPixel LED ring on an OpenHome DevKit using natural-language voice commands.

## What You Can Build
- Ambient mood lighting controller
- Notification ring (flash on incoming events)
- Build / oncall status indicator
- Music visualiser with custom palettes
- Sleep-wake routines with sunrise-sunset fades
- Pomodoro timer with phase-coloured transitions

## Template Trigger Words
This template uses generic triggers — **customize these** for your specific ability:
- "control the lights" / "lights control" / "change the lights"
- Configure your own trigger words in the OpenHome dashboard

## Requirements
- An OpenHome DevKit (Raspberry Pi) with the onboard NeoPixel ring
- NeoPixel ring: 24 pixels on GPIO 12, driven via PWM/DMA
- `rpi-ws281x` (declared in `requirements.txt`)
- DevKit-side bridge functions in `devkit_functions.py` (shipped with this template)

> ⚠️ **Local abilities cannot be tested in the Live Editor.** They must run on a connected DevKit device.

## Setup Instructions
1. Get the template from the OpenHome dashboard or [GitHub](https://github.com/OpenHome-dev/abilities) and add it to your agent.
2. Configure trigger words in the dashboard.
3. Power on the DevKit, connect it to your agent, and say a trigger word.

## Using This Template

### Default Template Behavior
1. User speaks a request
2. LLM routes the request to one of the registered NeoPixel commands and returns a JSON object
3. The ability speaks the response and dispatches the command to the DevKit
4. Effects run continuously by default until the user changes them or exits

### Testing the Template
> **User:** "make it red" → **AI:** "Going red." *(ring turns red)*
>
> **User:** "now do a candle flicker" → **AI:** "Lighting a warm candle." *(ring flickers)*
>
> **User:** "stop" → **AI:** "Closing lights control." *(ring resets, ability exits)*

## Core Template Functions

### `send_devkit_capability_action()` (cloud → device)
Dispatches a NeoPixel command from `main.py` to a function registered in `devkit_functions.py`.

```python
await self.capability_worker.send_devkit_capability_action(
    "neopixel_solid", ["ff0000", "180"], 8
)
```

### `send_devkit_action()` (lifecycle toggles)
Used for the system-level toggles that surround the ability lifecycle.

```python
await self.capability_worker.send_devkit_action("automatic_leds_off")
# ... ability runs ...
await self.capability_worker.send_devkit_action("automatic_leds_on")
```

### DevKit-side bridge (`devkit_functions.py`)
Implements every `neopixel_*` function the LLM can route to. Long-running effects supersede previous ones cleanly when a new command arrives. The file also exposes general DevKit utilities (GPIO, system stats, camera, network, services) — useful when extending this template into a broader hardware-control ability.

## How the Template Works
1. Voice input is sent to the LLM with a system prompt enumerating every available NeoPixel function
2. The LLM returns `{ "function_name", "args", "spoken_response" }`
3. The spoken response is queued in parallel with the bridge call so the user hears confirmation while the ring is already changing
4. If a duration was given, a session task drops a soft fallback gradient onto the ring when the effect ends
5. The loop continues until the user says an exit phrase ("stop", "bye", "thanks", "I'm done")

## Customizing the Template

### 1. Add or Remove Commands
Edit the `NEOPIXEL_COMMANDS` dict at the top of `main.py`. The system prompt is generated from this dict automatically.

### 2. Change the Fallback Look
Edit `FALLBACK_FUNCTION` and `FALLBACK_ARGS` to change what users see between timed effects.

### 3. Adjust the Default Duration
By default, effects run continuously (`999999` seconds). To make effects time-limited by default, edit rule 5 in `SYSTEM_PROMPT`.

## Best Practices
- **Speak and dispatch in parallel** — keep `session_tasks.create(self.capability_worker.speak(...))` so confirmation and effect happen together.
- **Always restore automatic LED behaviour on exit** — the `finally` block calls `neopixel_off`, `automatic_leds_on`, and `resume_normal_flow()`. Local abilities holding hardware must clean up.
- **Use the command counter for stale tasks** — `_command_counter` supersedes pending fallback timers when a newer command arrives. Capture the counter at task start and bail if it has advanced.

## Troubleshooting

### LED Ring Doesn't Respond
Check the DevKit is connected, `automatic_leds_off` is being sent, and review `[Lights] bridge result:` in the editor logs.

### "Stop" Turns Lights Off Instead of Exiting
The LLM has misrouted "stop" to `neopixel_off`. Re-emphasise rule 14 in `SYSTEM_PROMPT` and add the failing phrasing to the explicit examples list.

## Links & Resources
- [Dashboard](https://app.openhome.com/dashboard)
- [Abilities Library](https://app.openhome.com/dashboard/abilities)
- [Developer Docs](https://docs.openhome.com)

## Final Reminder

⚠️ **This template is a starting point, not a finished product.** Customize the routing rules, fallback look, and command set for your specific use case.
