# OpenHome · Ability Templates

> **Seven core templates. Three ability types. Unlimited possibilities.**

This directory contains the official starter templates for building OpenHome abilities. Each folder is a minimal, working boilerplate that demonstrates a core architectural pattern. They are **not** polished user experiences — they are the scaffolding you build on top of.

---

## What is OpenHome?

OpenHome is a jailbroken smart speaker that runs AI agents capable of triggering Python **abilities** that escape the cloud sandbox. These abilities can:

- Control your desktop terminal
- Send commands to **OpenClaw** (2,800+ community skills)
- Process ambient audio in the background
- Accumulate intelligence over time
- Send data off-platform, fire emails, set alarms
- Run 24/7 — **no wake word required**

Gone are the days of “wake words” and dumb speakers. This is AGI-like smart intelligence: background processing, cloud connectivity, desktop
control, filesystem access, hybrid local-and-cloud LLMs. And local, all running on a device that
sits on your desk

The LLM at the core can access your filesystem, control OpenClaw, invoke built-in abilities, and run background daemons.

---

## Three Ability Types

Every ability you build falls into one of three categories:

| Type | Trigger | Lifecycle | Entry File |
|---|---|---|---|
| **Skill** | User hotword or brain routing | Runs once, exits | `main.py` |
| **Background Daemon** | Automatic on session start | Runs continuously in a loop | `background.py` |
| **Local** | User | Runs on DevKit hardware | DevKit SDK |

**Skill** is the workhorse. A user says a hotword (or the brain's routing LLM invokes it), the ability runs, does its thing, and hands control back via `resume_normal_flow()`.

**Background Daemon** starts automatically when a user connects and runs in a `while True` loop for the entire session. No hotword needed. It can monitor conversations, poll APIs, watch for time-based events, and interrupt the main flow when something fires. Daemons can be standalone (`background.py` only) or combined with a Skill (`main.py` + `background.py`) coordinating through shared file storage.

**Local** abilities are triggered by the user and run directly on DevKit hardware (e.g. Raspberry Pi), bypassing the cloud sandbox entirely. They can use unrestricted Python packages, GPIO pins, BLE, and local models. **Local abilities cannot be tested in the Live Editor** — they must be run on a connected DevKit device.

---

## Template Directory

```
templates/
│
├── basic-template/        ← Start here. Minimal Skill skeleton.
├── api-template/          ← Call an external REST API from a Skill.
├── loop-template/         ← Long-running looped Skill (ambient observer).
│
├── SendEmail/             ← Fire-and-forget SDK method call.
├── Local/                 ← LLM as translator; execute on local machine.
├── OpenClaw/              ← Escape the sandbox via OpenClaw.
├── PhilipsHueLightControl/← Local + persistent BLE daemon. Real hardware example.
├── devkit_led_lights_control/ ← Local + onboard NeoPixel LED ring control.
│
├── Background/            ← Standalone background daemon.
├── Alarm/                 ← Combined Skill + Daemon (main.py + background.py).
│
└── ReadWriteFile/         ← Shared file storage / IPC between Skill & Daemon.
```

---

## The Templates

### 🟢 Start Here

---

#### [`basic-template`](./templates/basic-template) — Minimal Skill Skeleton
**Type:** Skill · **Complexity:** Minimal

The absolute minimum scaffolding for a working Skill. Shows correct `CapabilityWorker` initialization inside `call()`, the `first_function()` entry point, and the mandatory `resume_normal_flow()` exit. Copy this as the starting point for any new Skill.

**Key SDK methods:** `speak()`, `resume_normal_flow()`

---

#### [`api-template`](./templates/api-template) — Generic API-Calling Skill
**Type:** Skill · **Complexity:** Minimal

Extends `basic-template` with an outbound HTTP request to an external REST API. Demonstrates the request/response cycle within the ability lifecycle — fetch data, process it, speak the result, exit cleanly. The `CapabilityWorker` reference in `call()` is correctly wired.

**Key SDK methods:** `text_to_text_response()`, `speak()`, `resume_normal_flow()`

---

### 🔵 The Seven Core Templates

These seven templates cover a deliberate progression from simplest to most complex. Each teaches a distinct architectural pattern.

---

#### [`SendEmail`](./templates/SendEmail) — Fire-and-Forget
**Type:** Skill · **Pattern:** Fire-and-forget · **Complexity:** Minimal

When triggered by a hotword, sends a hardcoded email via SMTP. No conversation, no user input — just trigger → send → speak result → exit. Teaches the most fundamental ability lifecycle and the critical `resume_normal_flow()` pattern.

**Key SDK methods:** `send_email()`, `speak()`, `resume_normal_flow()`

**Critical pattern — `resume_normal_flow()`:**
Every Skill **must** call this when done. It hands control back to the agent's normal conversation. Forget it, and the speaker goes permanently silent.

> Everything is hardcoded intentionally. A production ability would collect recipients, compose with the user, confirm before sending, and handle errors gracefully.

**Build on top:** voice-composed email, daily digest emailer daemon, contact book integration (`"Send an email to Mom"`), meeting follow-up drafter.

---

#### [`Local`](./templates/Local) — LLM as Translator (Mac Terminal)
**Type:** Skill · **Pattern:** LLM-as-translator · **Complexity:** Medium

You say `"list all my Python files"` and the speaker translates that into a real terminal command (`find . -name "*.py"`), runs it on your local machine, and reads back the result in plain English. Two LLM calls bookend the local execution — one translates speech → command, another translates raw output → human speech.

**Key SDK methods:** `wait_for_complete_transcription()`, `text_to_text_response()`, `exec_local_command()`

**Key pattern — `exec_local_command()`:**
Abilities run in OpenHome's cloud sandbox, not on your local machine. `exec_local_command()` bridges that gap via WebSocket to whatever device is connected (Mac, Pi, etc.).

> ⚠️ No command validation or safety filtering is included. A production version must guard against destructive commands (`rm -rf`) and handle long-running processes with timeouts.

**Build on top:** git voice control, dev environment manager, file organizer, system health monitor daemon.

---

#### [`OpenClaw`](./templates/OpenClaw) — Sandbox Escape
**Type:** Skill · **Pattern:** Sandbox escape · **Complexity:** Minimal

Forwards the user's raw speech directly to OpenClaw — a desktop AI agent with 2,800+ community skills. OpenClaw processes it on your local machine and returns the result. The speaker becomes a voice interface for your entire desktop.

OpenHome abilities run in a restricted cloud sandbox — no arbitrary Python packages, no local network calls, limited filesystem access. OpenClaw is the escape hatch.

**Key SDK methods:** `wait_for_complete_transcription()`, `exec_local_command()`, `speak()`

```python
user_inquiry = await self.capability_worker.wait_for_complete_transcription()
await self.capability_worker.speak("Sending inquiry to OpenClaw")
response = await self.capability_worker.exec_local_command(user_inquiry)
await self.capability_worker.speak(response["data"])
self.capability_worker.resume_normal_flow()
```

> No routing logic, error handling, or timeout handling is included. A real implementation would parse the response structure and handle unmatched skills gracefully.

**Build on top:** smart home hub via HomeAssistant, code execution, app control (`"Open Spotify"`), multi-agent orchestration for complex workflows.

---

#### [`PhilipsHueLightControl`](./templates/PhilipsHueLightControl) — Voice-Controlled Hue Bulb
**Type:** Local · **Pattern:** Persistent BLE connection · **Complexity:** Advanced

Control a Philips Hue bulb directly over Bluetooth — no Hue Bridge, no internet. When triggered, the ability connects to the bulb and holds the connection open for the entire session, so every voice command is instant with no reconnect delay between commands. It reads what the specific bulb actually supports (on/off, brightness, colour temperature, colour) and only offers controls that work with that hardware — a basic white bulb is never offered colour commands. Natural-language phrasing like "cozy vibe", "not so harsh", or "crank it up" is understood, not just exact phrases.

**Key SDK methods:** `send_devkit_capability_action()`, `text_to_text_response()`, `user_response()`, `speak()`, `resume_normal_flow()`

> ⚠️ This is a **Local** ability — it cannot be tested in the Live Editor. It must run on a connected DevKit device with a working Bluetooth stack and a Hue bulb in range.

**Build on top:** other BLE devices (LIFX, Govee), multi-bulb scenes, presence-based auto-on daemon, sunset-fade routines, smart-plug control.

---

#### [`devkit_led_lights_control`](./templates/devkit_led_lights_control) — Voice-Controlled NeoPixel Ring
**Type:** Local · **Pattern:** On-device hardware control · **Complexity:** Advanced

Control the DevKit's onboard NeoPixel LED ring with your voice — no extra hardware. Say "make it red", "do a candle flicker", "rainbow for 30 seconds", or "switch to music mode", and the ring responds immediately. Twenty-plus built-in effects (solid, rainbow, breathe, chase, fire, sparkle, comet, gradient, strobe, wave, police, candle, music-reactive) are routed by an LLM that understands casual phrasing. Effects run continuously by default until the user changes them or exits.

**Key SDK methods:** `send_devkit_capability_action()`, `send_devkit_action()`, `text_to_text_response()`, `user_response()`, `speak()`, `resume_normal_flow()`

> ⚠️ This is a **Local** ability — it cannot be tested in the Live Editor. It must run on a connected DevKit device with the onboard NeoPixel ring.

**Build on top:** notification ring (flash on events), build/oncall status indicator, Pomodoro phase colours, sleep-wake sunrise routines, music visualisers with custom palettes.

---

#### [`Background`](./templates/Background) + [`Alarm`](./templates/Alarm) — Background Daemon
**Type:** Background Daemon · **Pattern:** Poll loop · **Complexity:** Medium

**`Background`** is the standalone daemon template. It starts automatically when a user connects and runs in an infinite loop — in this template, reading conversation history and logging it every 20 seconds. This is the most architecturally significant pattern in the system: before daemons, every ability was reactive. Now they can be proactive.

**`Alarm`** is the combined template: `main.py` (Skill) + `background.py` (Daemon) working together. The Skill parses `"set an alarm for 3pm"` and writes to `alarms.json`. The Daemon polls that file every 15 seconds and fires `send_interrupt_signal()` + `play_from_audio_file("alarm.mp3")` when the target time hits. They coordinate through shared files, not direct function calls.

**Key SDK methods:** `get_full_message_history()`, `send_interrupt_signal()`, `session_tasks.sleep()`, `play_from_audio_file()`

**Critical rules for daemons:**

| Rule | Why |
|---|---|
| Use `session_tasks.sleep()`, **not** `asyncio.sleep()` | Ensures proper cleanup when the session ends |
| **No** `resume_normal_flow()` | Daemons are independent threads — they don't own the conversation |
| Call `send_interrupt_signal()` before speaking | Prevents audio overlap; stops system from transcribing daemon output as user input |
| `delete` then `write` for JSON | `write_file()` appends — always delete the file first, then write the full object |

**Build on top:** meeting summarizer, user profiler / RAG context accumulator, Pomodoro timer, baby monitor, smart home scheduler.

---

#### [`loop-template`](./templates/loop-template) — Ambient Observer (Log My Life)
**Type:** Skill (long-running) · **Pattern:** Ambient observer · **Complexity:** Advanced

The most ambitious template. Activates and silently records everything around the speaker. Every 90 seconds: capture audio → transcribe via Deepgram with speaker diarization → LLM extracts decisions, action items, key moments, people mentioned, ideas discussed → repeat. Say `"stop logging"` to get a spoken summary and post results to an external dashboard.

Demonstrates nearly every advanced SDK pattern: raw audio recording, external API calls, LLM analysis with cumulative context, chunked processing, voice exit detection while recording, and full session lifecycle management.

**Key SDK methods:** `start_audio_recording()`, `stop_audio_recording()`, `get_audio_recording()`, `text_to_text_response()`, `play_from_audio_file()`

**Key patterns:**

- **Cumulative audio buffer:** `get_audio_recording()` returns ALL audio since `start_audio_recording()` — not just the latest chunk. Track `previous_audio_size`, slice only the new PCM bytes, and rebuild a valid WAV header before sending to the transcription API.
- **Listening while waiting:** `wait_for_interval_or_exit()` races a `user_response()` listener against a `session_tasks.sleep()` timer. Exit phrase detected = break the loop. Timer fires = chunk interval complete. This is how you detect voice commands without blocking your processing loop.

> ⚠️ API keys are hardcoded and the dashboard URL points to a specific deployment. A production implementation needs a secrets manager and an explicit user consent flow before recording begins.

**Build on top:** ambient meeting assistant, language learning observer, therapy session noter (with consent), podcast producer, family memory book.

---

### 🟡 Utility Pattern

---

#### [`ReadWriteFile`](./templates/ReadWriteFile) — Shared File Storage / IPC
**Type:** Skill · **Complexity:** Minimal

Demonstrates how Skills and Daemons coordinate through shared file storage — the primary IPC mechanism between `main.py` and `background.py`. Used by the `Alarm` template.

**Critical rule:** Always **delete** the file before writing a JSON object. `write_file()` appends — calling it twice will corrupt your JSON.

```python
# Correct pattern
self.capability_worker.delete_file("state.json")
self.capability_worker.write_file("state.json", json.dumps(data))
```

---

## Quick Reference

| Template | Type | Key SDK Methods |
|---|---|---|
| `basic-template` | Skill | `speak()`, `resume_normal_flow()` |
| `api-template` | Skill | `text_to_text_response()`, `resume_normal_flow()` |
| `SendEmail` | Skill | `send_email()`, `speak()`, `resume_normal_flow()` |
| `Local` | Skill | `text_to_text_response()`, `exec_local_command()` |
| `OpenClaw` | Skill | `exec_local_command()`, `speak()` |
| `PhilipsHueLightControl` | Local | `send_devkit_capability_action()`, `text_to_text_response()`, `speak()` |
| `devkit_led_lights_control` | Local | `send_devkit_capability_action()`, `send_devkit_action()`, `text_to_text_response()` |
| `Background` | Background Daemon | `get_full_message_history()`, `session_tasks.sleep()` |
| `Alarm` | Skill + Daemon | `send_interrupt_signal()`, `play_from_audio_file()`, `session_tasks.sleep()` |
| `loop-template` | Skill (long-running) | `start_audio_recording()`, `get_audio_recording()`, `text_to_text_response()` |
| `ReadWriteFile` | Utility / IPC | `read_file()`, `delete_file()`, `write_file()` |

---

## Getting Started

1. **Pick a template** — start with `basic-template` if you're new, or whichever pattern matches what you want to build.
2. **Copy the folder** and rename it to your ability name.
3. **Replace hardcoded values** — API keys, emails, URLs — with user-collected input or environment config.
4. **Add guardrails** — error handling, confirmation steps, and safety checks appropriate for your use case.
5. **Coordinating a Skill + Daemon?** Use the `ReadWriteFile` pattern to pass state between `main.py` and `background.py` via shared JSON files.

For full SDK documentation, see the [OpenHome Developer Docs](https://docs.openhome.com).

---
