# DevKit Stats Template — OpenHome Ability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)
![Local](https://img.shields.io/badge/Category-Local-green?style=flat-square)

## What This Is
**This is a template ability** that reports live telemetry from an OpenHome DevKit by voice — CPU, memory, temperature, uptime, Wi-Fi, disk, overall health, or a full snapshot. You ask in plain language; the LLM routes your request to exactly one telemetry function, the DevKit reads the metric locally, and the agent speaks a concise answer.

The cloud side (`main.py`) handles intent routing and the conversation loop; the device side (`devkit_functions.py`) runs on the DevKit and reads real system values from `/proc`, `/sys`, and standard tools. The two sides talk through `send_devkit_capability_action()`.

> ⚠️ **Local abilities cannot be tested in the Live Editor.** They run on a connected DevKit device.

## What You Can Build
- **Voice system monitor** — "what's my CPU?", "how hot is it?"
- **Health check assistant** — "is anything wrong?" → flags high temp, low memory, full disk
- **Uptime / status reporter** — "how long has it been running?"
- **Network status check** — "am I on Wi-Fi?" / "what network am I on?"
- **One-shot snapshot** — "give me everything" → a spoken summary of all key metrics
- **Foundation for hardware dashboards** — extend the registry with your own metrics

## Available Metrics
| Function | Reports |
|----------|---------|
| `get_cpu` | CPU usage (used / free percent) |
| `get_memory` | Memory used / total / available (GB) |
| `get_temperature` | Device temperature (°C) and a status word |
| `get_uptime` | How long the device has been running |
| `get_wifi` | Wi-Fi connection and SSID |
| `get_disk` | Disk used percent and free space |
| `get_health` | Overall health — flags high temp, low memory, full disk |
| `get_all_stats` | A spoken snapshot of all key metrics |

## Requirements
- An OpenHome DevKit (Linux device) running the device-side bridge.
- A Linux environment exposing `/proc/stat`, `/proc/meminfo`, `/proc/uptime`, and `/sys/class/thermal/thermal_zone0/temp`.
- `iwgetid` available for Wi-Fi SSID lookup (optional — degrades gracefully).
- No API keys and no external services — everything is read locally on the device.

## Setup Instructions
1. Get the template from the OpenHome dashboard or [GitHub](https://github.com/OpenHome-dev/abilities) and add it to your agent.
2. Configure trigger words in the dashboard.
3. Power on the DevKit, connect it to your agent, and say a trigger word.

## Using This Template

### Template Trigger Words
This template uses generic triggers — **customize these** for your ability:
- "device stats" / "system status" / "check the DevKit"
- Configure your own trigger words in the OpenHome dashboard.

### Default Template Behavior
1. User asks about device status
2. The LLM routes the request to one telemetry function (or `none` / `exit`)
3. On the first turn, an unmatched request defaults to `get_all_stats`
4. The DevKit reads the metric and returns a structured result
5. The agent speaks the result, then asks if you want anything else
6. The loop continues until you say an exit phrase ("stop", "done", "thanks", "bye", …)

## How the Template Works

### Cloud Side (`main.py`)
1. The conversation runs in a loop; the first turn uses `wait_for_complete_transcription()`, later turns use `user_response()`
2. `_route_to_devkit_function()` calls `text_to_text_response()` with a strict routing `SYSTEM_PROMPT` that returns a single JSON object:
   `{"function_name": "<name | none | exit>"}`
3. The chosen function is dispatched to the device:
```python
result = await self.capability_worker.send_devkit_capability_action(
    function_name=function_name,
    args=[],
    timeout=8,
)
```
4. `_spoken_response_from_result()` validates the result and returns the device's `spoken_response`
5. Unsupported requests get a helpful prompt; the loop ends cleanly on `exit`

### Device Side (`devkit_functions.py`)
Each function reads a real metric and emits a structured JSON payload on stdout:
```json
{ "success": true, "metric": "cpu", "spoken_response": "CPU is 12 percent used and 88 percent free.", "data": { ... }, "error": null }
```
- **CPU** — samples `/proc/stat` twice and computes usage over the interval
- **Memory** — parses `MemTotal` / `MemAvailable` from `/proc/meminfo`
- **Temperature** — reads `/sys/class/thermal/thermal_zone0/temp` and maps it to a status word
- **Uptime** — reads `/proc/uptime` and formats days/hours/minutes
- **Wi-Fi** — runs `iwgetid -r` for the SSID
- **Disk** — uses `shutil.disk_usage("/")`
- **Health** — combines temp, memory, and disk into a list of issues
- **All stats** — gathers everything into one spoken snapshot

A central dispatcher (`main()` + `FUNCTION_REGISTRY`) routes the function name and emits a structured error for missing/unknown functions, bad arguments, or unexpected failures.

## Core Template Functions

### `send_devkit_capability_action()` (cloud → device)
Dispatches a telemetry function name (with empty `args`) to the device and waits up to 8 seconds for the JSON result.

### `FUNCTION_REGISTRY` (device-side bridge)
Maps each metric name to its reader function. This is the extension point — add a new reader and register it here, then add it to `AVAILABLE_STATS` and the routing rules in `main.py`.

## Template Usage Examples

> **User:** "what's my CPU at?" → **AI:** "CPU is 12 percent used and 88 percent free."
>
> **User:** "how hot is it?" → **AI:** "DevKit temperature is 47.2 degrees Celsius and running cool."
>
> **User:** "is anything wrong?" → **AI:** "The DevKit looks healthy."
>
> **User:** "give me everything" → **AI:** "DevKit snapshot: temperature is 47.2 degrees Celsius, CPU is 12 percent used, memory has 5.1 gigabytes available, disk is 38 percent used, Wi-Fi is connected to HomeNet."
>
> **User:** "that's all, thanks" → **AI:** "Exiting DevKit stats." *(ability exits)*

## Customizing the Template

### 1. Add a New Metric
Write a reader in `devkit_functions.py` that calls `_emit_success` / `_emit_error`, register it in `FUNCTION_REGISTRY`, then add it to `AVAILABLE_STATS` and the routing rules in `SYSTEM_PROMPT`.

### 2. Change Thresholds
Edit `_temperature_status()` bands and the health checks in `get_health()` (temperature ≥ 75 °C, memory < 200 MB, disk ≥ 90%).

### 3. Tune Routing and Conversation
Adjust `SYSTEM_PROMPT` routing rules, the conversation history window (`[-12:]`), or the `send_devkit_capability_action` timeout.

## Best Practices
- **Keep spoken responses short** — each function returns a one-line `spoken_response` built for voice.
- **Degrade gracefully** — readers return structured errors instead of crashing when a value is unavailable.
- **Route by intent, not keywords alone** — the LLM prompt maps natural phrasing to one function.
- **Always call `resume_normal_flow()`** — the `finally` block guarantees control returns to the Agent.

## Troubleshooting

### "I couldn't reach the DevKit"
The device call returned no dict / failed — confirm the DevKit is connected and the bridge is running.

### A Metric Says "unavailable"
The underlying file or command couldn't be read on this device (e.g. no `iwgetid`, or a different thermal zone path). Check the device logs for the metric's error code.

### Requests Get Routed to the Wrong Stat
Refine the routing rules in `SYSTEM_PROMPT` and add the failing phrasing to the relevant rule.

## Links & Resources
- [Dashboard](https://app.openhome.com/dashboard)
- [Abilities Library](https://app.openhome.com/dashboard/abilities)
- [Developer Docs](https://docs.openhome.com)

## Final Reminder
⚠️ **This template is a starting point, not a finished product.** Customize the metrics, thresholds, and routing rules for your specific use case.
