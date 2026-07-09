# Smart Home

Voice control for your MQTT smart-home devices. Say what you want — *"turn on the bedroom
light"*, *"set the lamp to 30 percent"*, *"make it blue"* — and an LLM figures out which
device you mean and what command to send it. Add any MQTT device from the dashboard; no code
changes needed. **Runs on the OpenHome DevKit.**

## How it works

1. You speak a request.
2. The ability reads your device list from `self.worker.mqtt_devices` and hands it, plus your
   request, to the LLM as a single prompt.
3. The LLM returns one JSON action — which device, and what to send it.
4. The ability publishes it over MQTT via `send_devkit_mqtt_action` and speaks a short confirmation.

The LLM is the orchestrator — there is **no per-device-type code**. To support a new device you
add it to the registry; to change behaviour you tune `ORCHESTRATOR_PROMPT`.

## Adding devices

Devices are configured in the **OpenHome DevKit → MQTT** section (saved to
`self.worker.mqtt_devices`). Each device is an object with four fields:

| Field | Required | What it is |
|---|---|---|
| `name` | yes | Friendly name, e.g. "Bedroom Light" |
| `topic` | yes | The device's MQTT topic (Tasmota `%topic%`), e.g. `tasmota` |
| `description` | yes (may be blank) | What the device is / does — helps the LLM disambiguate |
| `commands` | optional | The MQTT commands the device supports — the LLM's reference |

`description` and `commands` may be blank. When `commands` is empty the LLM infers a sensible
command from the name, description, and how that kind of device normally works over MQTT.

### Example — a Tasmota RGBCW bulb

```
name:        Bedroom Light
topic:       tasmota
description: RGBCW smart bulb — full RGB color plus tunable warm-to-cool white, dimmable. Controlled over MQTT (Tasmota).
commands:    HSBColor hue,sat,bri (0-360,0-100,0-100); Dimmer 0-100; CT 153-500 (warm→cool); Color R,G,B 0-255
```

With this entry:

| You say | Action sent |
|---|---|
| "turn on the bedroom light" | `turn_on` → `cmnd/tasmota/POWER ON` |
| "turn it off" | `turn_off` → `cmnd/tasmota/POWER OFF` |
| "make it blue" | `custom` `HSBColor` `240,100,100` |
| "dim to 30 percent" | `custom` `Dimmer` `30` |
| "warm white" | `custom` `CT` `450` |

## Actions

The ability emits one of three actions to the bridge:

- **`turn_on` / `turn_off`** — power. The bridge hard-codes `cmnd/<topic>/POWER ON|OFF`; no
  command/value needed.
- **`custom`** — everything else (brightness, color, temperature, modes). Carries an MQTT
  `command` + `value`, published as `cmnd/<topic>/<command> <value>`.

If the request is unclear or several devices match, the LLM asks one clarifying question, then
acts on your answer.

## Notes

- **Leading slash:** the DevKit bridge builds the topic as `cmnd/<topic><command>` with no
  separator, so a `custom` command must start with `/`. The ability adds it automatically — you
  can write `commands` with or without the slash; both work.
- **No state read-back:** the ability sends commands; it can't read a device's current state.
- **One device per request** (v1). Group commands like "turn off all lights" aren't handled yet.

## Files

- `main.py` — the ability (orchestrator prompt + control flow).
- `__init__.py` — package marker.

## Trigger phrases (suggested)

`smart home`, `my devices`, `home control`, `device control`
