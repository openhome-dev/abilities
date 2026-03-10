# OpenHome Ability SDK — Complete Reference

> **This is the single source of truth for everything available inside an Ability.**
> If a method or property isn't listed here, it either doesn't exist or hasn't been documented yet.
> Found something missing? Let us know on Discord.

---

## Quick Orientation

Inside any Ability, you have access to two objects:

| Object | What it is | Access via |
|--------|-----------|------------|
| `self.capability_worker` | **The SDK** — all I/O, speech, audio, LLM, files, and flow control | `CapabilityWorker(self)` |
| `self.worker` | **The Agent** — logging, session management, memory, user connection info | Passed into `call()` |

### Runtime Entry Points (`main.py` vs `background.py`)

| Runtime | Required file | `call()` signature | Lifecycle |
|---|---|---|---|
| Interactive Skill / Brain Skill | `main.py` | `call(self, worker)` | Triggered on demand, exits with `resume_normal_flow()` |
| Background Daemon | `background.py` | `call(self, worker, background_daemon_mode)` | Auto-starts on session begin, runs continuously |

`background.py` must be named exactly `background.py` to be detected as a background daemon.

---

## Table of Contents

1. [Speaking / TTS](#1-speaking--tts)
2. [Listening / User Input](#2-listening--user-input)
3. [Combined Speak + Listen](#3-combined-speak--listen)
4. [LLM / Text Generation](#4-llm--text-generation)
5. [Audio Playback](#5-audio-playback)
6. [Audio Recording](#6-audio-recording)
7. [Audio Streaming](#7-audio-streaming)
8. [File Storage (Persistent + Temporary)](#8-file-storage-persistent--temporary)
9. [Ability Context Storage (Key-Value)](#9-ability-context-storage-key-value)
10. [WebSocket Communication](#10-websocket-communication)
11. [Flow Control](#11-flow-control)
12. [Logging](#12-logging)
13. [Session Tasks](#13-session-tasks)
14. [User Connection Info](#14-user-connection-info)
15. [Conversation Memory & History](#15-conversation-memory--history)
16. [Music Mode](#16-music-mode)
17. [Common Patterns](#17-common-patterns)
18. [Appendix: What You CAN'T Do (Yet)](#18-appendix-what-you-cant-do-yet)
19. [Appendix: Blocked Imports](#19-appendix-blocked-imports)

---

## 1. Speaking / TTS

### `speak(text)`
Converts text to speech using the Agent's default voice. Streams audio to the user.

```python
await self.capability_worker.speak("Hello! How can I help?")
```

- **Async:** Yes (`await`)
- **Voice:** Uses whatever voice is configured on the Agent
- **Tip:** Keep it to 1-2 sentences. This is voice, not text.

---

### `text_to_speech(text, voice_id)`
Converts text to speech using a **specific Voice ID** (e.g., from ElevenLabs). Use when your Ability needs its own distinct voice.

```python
await self.capability_worker.text_to_speech("Welcome aboard.", "pNInz6obpgDQGcFmaJgB")
```

- **Async:** Yes (`await`)
- **Voice:** Overrides the Agent's default
- **See:** [Voice ID catalog](#voice-id-quick-reference) at the bottom of this doc

---

## 2. Listening / User Input

### `user_response()`
Waits for the user's next spoken or typed input. Returns it as a string.

```python
user_input = await self.capability_worker.user_response()
```

- **Async:** Yes (`await`)
- **Returns:** `str` — the transcribed user input
- **Tip:** Always check for empty strings (`if not user_input: continue`)

---

### `wait_for_complete_transcription()`
Waits until the user has **completely finished speaking** before returning the final transcription.

```python
full_input = await self.capability_worker.wait_for_complete_transcription()
```

- **Async:** Yes (`await`)
- **Returns:** `str` — the final transcribed input
- **When to use:**
  - Long-form input (descriptions, dictation, storytelling)
  - Cases where partial STT results may break your logic
  - Flows that need the entire spoken sentence before processing
  - The first step of an ability when capturing the trigger sentence

#### Capturing the full trigger sentence

When a trigger word starts an ability immediately, this method still returns the full spoken sentence, including both the trigger phrase and the actual request.

Example trigger word: `remind`  
User says: `remind me to call Alex tomorrow at 6 PM`

```python
import re

async def first_function(self):
    full_input = await self.capability_worker.wait_for_complete_transcription()
    reminder_text = re.sub(r"^\s*remind\b", "", full_input, flags=re.IGNORECASE).strip()
    await self.capability_worker.speak(f"Creating reminder: {reminder_text}")
```

In this flow:

- The ability is triggered by `remind`
- `wait_for_complete_transcription()` returns:
  `remind me to call Alex tomorrow at 6 PM`
- The extracted request becomes:
  `me to call Alex tomorrow at 6 PM`

---

## 3. Combined Speak + Listen

### `run_io_loop(text)`
Speaks the text, then waits for the user's response. Returns the user's reply. A convenience wrapper around `speak()` + `user_response()`.

```python
answer = await self.capability_worker.run_io_loop("What's your favorite color?")
```

- **Async:** Yes (`await`)
- **Returns:** `str` — user's reply

> **Note:** Uses the Agent's default voice (not a custom voice ID)

---

### `run_confirmation_loop(text)`
Speaks the text (appends "Please respond with 'yes' or 'no'"), then loops until the user clearly says yes or no.

```python
confirmed = await self.capability_worker.run_confirmation_loop("Should I send this email?")
if confirmed:
    # send it
```

- **Async:** Yes (`await`)
- **Returns:** `bool` — `True` for yes, `False` for no

---

## 4. LLM / Text Generation

### `text_to_text_response(prompt_text, history=[], system_prompt="")`

Generates a text response using the configured LLM.

```python
response = self.capability_worker.text_to_text_response(
    "What's the capital of France?",
    history=[
        {"role": "user", "content": "Let's do geography trivia"},
        {"role": "assistant", "content": "Great, I'll ask you questions!"}
    ],
    system_prompt="You are a geography quiz host. Keep answers under 1 sentence."
)
```

- **⚠️ THIS IS THE ONLY SYNCHRONOUS METHOD. Do NOT use `await`.**
- **Returns:** `str` — the LLM's response
- **Parameters:**
  - `prompt_text` (str): The current prompt/question
  - `history` (list): Optional conversation history for multi-turn context. Each item: `{"role": "user"|"assistant", "content": "..."}`
  - `system_prompt` (str): Optional system prompt to control LLM behavior
- **Tip:** LLMs often wrap JSON in markdown fences. Always strip them:
  ```python
  clean = response.replace("```json", "").replace("```", "").strip()
  ```

---

## 5. Audio Playback

### `play_audio(file_content)`
Plays audio directly from bytes or a file-like object.

```python
import requests
audio = requests.get("https://example.com/song.mp3")
await self.capability_worker.play_audio(audio.content)
```

- **Async:** Yes (`await`)
- **Input:** `bytes` or file-like object
- **Tip:** For anything longer than a TTS clip, use [Music Mode](#16-music-mode)

---

### `play_from_audio_file(file_name)`
Plays an audio file stored in the Ability's directory (same folder as `main.py`).

```python
await self.capability_worker.play_from_audio_file("notification.mp3")
```

- **Async:** Yes (`await`)
- **Input:** Filename (string) — must be in the same folder as your `main.py`

---

## 6. Audio Recording

Record audio from the user's microphone during a session.

### `start_audio_recording()`
Begins recording audio from the user's mic.

```python
self.capability_worker.start_audio_recording()
```

### `stop_audio_recording()`
Stops the current audio recording.

```python
self.capability_worker.stop_audio_recording()
```

### `get_audio_recording()`
Returns the recorded audio as a `.wav` file.

```python
wav_data = self.capability_worker.get_audio_recording()
```

- **Returns:** `.wav` file data

### `get_audio_recording_length()`
Returns the length/duration of the current recording.

```python
length = self.capability_worker.get_audio_recording_length()
```

### `flush_audio_recording()`
Clears the current recording buffer/file so the next recording starts fresh.

```python
self.capability_worker.flush_audio_recording()
```

- **Async:** No (synchronous)

### Recording Example

```python
async def record_voice_note(self):
    await self.capability_worker.speak("I'll record a voice note. Start speaking.")
    self.capability_worker.start_audio_recording()

    await self.worker.session_tasks.sleep(10)  # Record for 10 seconds

    self.capability_worker.stop_audio_recording()

    duration = self.capability_worker.get_audio_recording_length()
    wav_file = self.capability_worker.get_audio_recording()

    await self.capability_worker.speak(f"Got it. Recorded {duration} of audio.")
    self.capability_worker.resume_normal_flow()
```

---

## 7. Audio Streaming

For streaming audio in chunks rather than loading it all into memory at once.

### `stream_init()`
Initializes an audio streaming session.

```python
await self.capability_worker.stream_init()
```

### `send_audio_data_in_stream(file_content, chunk_size=4096)`
Streams audio data in chunks. Handles mono conversion and resampling automatically.

```python
await self.capability_worker.send_audio_data_in_stream(audio_bytes, chunk_size=4096)
```

- **Input:** `bytes`, file-like object, or `httpx.Response`
- **chunk_size:** Bytes per chunk (default: 4096)

### `stream_end()`
Ends the streaming session and cleans up.

```python
await self.capability_worker.stream_end()
```

### Streaming Example

```python
async def stream_long_audio(self):
    await self.capability_worker.stream_init()
    response = requests.get("https://example.com/long-audio.mp3")
    await self.capability_worker.send_audio_data_in_stream(response.content)
    await self.capability_worker.stream_end()
```

---

## 8. File Storage (Persistent + Temporary)

OpenHome provides a server-side file storage system that allows Abilities to persist data across sessions. For structured dictionary state, you can also use [Ability Context Storage (Key-Value)](#9-ability-context-storage-key-value).

### How It Works

| Flag | Scope | Persistence | Use Case |
|------|-------|-------------|----------|
| `temp=False` | **User-level, global** | Survives disconnects and new sessions forever | User preferences, saved data, history, onboarding state |
| `temp=True` | **Session-level** | Deleted when session ends | Scratch data, cached API responses, temp processing |

**Key concept: Storage is scoped at the user level globally — NOT per-ability.** Any Ability can read/write to the same files for a given user. This means an onboarding Ability can write `user_prefs.json` and a completely separate Smart Hub Ability can read it.

**Allowed file types:** `.txt`, `.csv`, `.json`, `.md`, `.log`, `.yaml`, `.yml`

### `check_if_file_exists(filename, temp)`

```python
exists = await self.capability_worker.check_if_file_exists("user_prefs.json", False)
```

- **Async:** Yes (`await`)
- **Returns:** `bool`
- **Always call this before reading** — don't assume a file exists on first run

### `write_file(filename, content, temp, mode="a+")`

```python
await self.capability_worker.write_file("user_prefs.json", '{"theme": "dark"}', False, mode="w")
```

- **Async:** Yes (`await`)
- **Modes:** `mode="a+"` (default, append) or `mode="w"` (overwrite)
- **Default behavior (`a+`):** Appends to existing file; creates file if it doesn't exist
- This is fine for `.txt` and `.log` files (append new lines)
- For JSON, prefer `mode="w"` or delete first, then write

### `read_file(filename, temp)`

```python
data = await self.capability_worker.read_file("user_prefs.json", False)
```

- **Async:** Yes (`await`)
- **Returns:** `str` — full file contents

### `delete_file(filename, temp)`

```python
await self.capability_worker.delete_file("user_prefs.json", False)
```

- **Async:** Yes (`await`)

### `get_user_data_file_names()`

Returns all filenames currently stored in user-level data storage (`temp=False` scope).

```python
files = await self.capability_worker.get_user_data_file_names()
```

- **Async:** Yes (`await`)
- **Returns:** `list[str]`

---

### ⚠️ The JSON Rule: Always Delete + Write

Because `write_file` defaults to **append mode** (`a+`), writing JSON to an existing file can produce invalid JSON (`{"a":1}{"a":1,"b":2}`). Always delete first, then write the complete object (or use `mode="w"`):

```python
# ✅ CORRECT — delete + write
async def save_json(self, filename, data):
    if await self.capability_worker.check_if_file_exists(filename, False):
        await self.capability_worker.delete_file(filename, False)
    await self.capability_worker.write_file(filename, json.dumps(data), False)

# ❌ WRONG — appending to JSON
await self.capability_worker.write_file("prefs.json", json.dumps(new_data), False)
# Result: {"old":"data"}{"new":"data"}  ← broken JSON
```

---

### ⚠️ The `.md` Context Injection Rule

The memory background scans user-level persistent storage and injects every `.md` file into the live Agent prompt.

- Use `.md` only for context you want the Agent to read.
- Use `.json`/`.txt`/`.log` for storage that should not affect prompt behavior.
- For replaceable context files, use delete-then-write (do not append stale states).
- Do not write background-owned files: `user_profile.md`, `user_summary.md`.

```python
context = "## Emotional State\n- Current: focused (confidence: 0.81)\n"
if await self.capability_worker.check_if_file_exists("audio_emotion.md", False):
    await self.capability_worker.delete_file("audio_emotion.md", False)
await self.capability_worker.write_file("audio_emotion.md", context, False)
```

---

### When to Use Each Storage Scope

**Use `temp=False` (persistent) for:**
- User preferences and settings
- Onboarding data ("has this user done setup?")
- Learned context (name, location, timezone)
- Conversation summaries
- Agent ambient context (`*.md` files injected by background)
- Accumulated data (journals, logs, scores, history)
- Any data that should survive a disconnect

**Use `temp=True` (session-only) for:**
- Cached API responses
- Intermediate processing data
- Temporary state that doesn't need to survive a disconnect

---

### Cross-Ability Data Sharing

Since storage is user-level (not per-ability), use consistent file names across abilities to share data:

```python
# Onboarding Ability saves user context:
await self.capability_worker.write_file("user_context.json", json.dumps({
    "name": "Chris",
    "city": "Austin",
    "timezone": "America/Chicago"
}), False)

# A completely separate Ability reads it later:
if await self.capability_worker.check_if_file_exists("user_context.json", False):
    raw = await self.capability_worker.read_file("user_context.json", False)
    context = json.loads(raw)
    name = context.get("name", "there")
    await self.capability_worker.speak(f"Welcome back, {name}.")
```

---

### Complete Example: Persistent User Preferences

```python
PREFS_FILE = "user_prefs.json"

async def load_or_create_prefs(self) -> dict:
    """Load persistent user preferences, or create defaults if first run."""
    if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
        raw = await self.capability_worker.read_file(PREFS_FILE, False)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self.worker.editor_logging_handler.error("Corrupt prefs file, resetting.")
            await self.capability_worker.delete_file(PREFS_FILE, False)
    return {}

async def save_prefs(self, prefs: dict):
    """Save user preferences persistently."""
    if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
        await self.capability_worker.delete_file(PREFS_FILE, False)
    await self.capability_worker.write_file(PREFS_FILE, json.dumps(prefs), False)
```

### Complete Example: First Run Detection

```python
async def boot(self):
    prefs = await self.load_or_create_prefs()

    if prefs.get("onboarded"):
        name = prefs.get("user_name", "there")
        await self.capability_worker.speak(f"Welcome back, {name}.")
        await self.run_main_loop(prefs)
    else:
        prefs = await self.run_onboarding()
        prefs["onboarded"] = True
        await self.save_prefs(prefs)
        await self.run_main_loop(prefs)

    self.capability_worker.resume_normal_flow()
```

### Complete Example: Activity Logging (Append-Friendly)

For `.txt` and `.log` files, appending works perfectly:

```python
from time import time

async def log_activity(self, event: str):
    """Append a timestamped event to a persistent activity log."""
    entry = "\n%s: %s" % (time(), event)
    await self.capability_worker.write_file("activity.log", entry, False)

async def get_recent_activity(self) -> str:
    """Read the full activity log."""
    if await self.capability_worker.check_if_file_exists("activity.log", False):
        return await self.capability_worker.read_file("activity.log", False)
    return ""
```

### Complete Example: Session-Only Cache

```python
async def cache_api_response(self, key: str, data: str):
    """Cache data for current session only — cleaned up on disconnect."""
    await self.capability_worker.write_file(f"cache_{key}.json", data, True)

async def get_cached(self, key: str) -> str | None:
    """Read cached data from current session."""
    fname = f"cache_{key}.json"
    if await self.capability_worker.check_if_file_exists(fname, True):
        return await self.capability_worker.read_file(fname, True)
    return None
```

---

## 9. Ability Context Storage (Key-Value)

`CapabilityWorker` includes a key-value context store for structured user/session state.

- Each key stores a JSON object (`dict`) as the value.
- These methods are synchronous (`do not await`).
- Great for conversation memory, user preferences, cart/session state, multi-step workflows, feature flags, and API cache metadata.

### `create_key(key: str, value: dict)`

Creates a new key-value pair.

```python
result = self.capability_worker.create_key(
    key="user_preferences",
    value={
        "language": "en",
        "theme": "dark",
        "notifications": True
    }
)
```

- **Async:** No (synchronous)
- **Parameters:**
  - `key` (str): Unique key
  - `value` (dict): JSON object to store

> **Note:** If the key already exists, the backend may return an error.

### `update_key(key: str, value: dict)`

Updates an existing key.

```python
result = self.capability_worker.update_key(
    key="user_preferences",
    value={
        "language": "en",
        "theme": "light",
        "notifications": False
    }
)
```

- **Async:** No (synchronous)
- **Parameters:** same as `create_key`

### `delete_key(key: str)`

Deletes a key-value pair permanently.

```python
result = self.capability_worker.delete_key("user_preferences")
```

- **Async:** No (synchronous)
- **Parameters:**
  - `key` (str): Key to delete

### `get_all_keys()`

Returns all stored key-value pairs.

```python
all_context = self.capability_worker.get_all_keys()
```

- **Async:** No (synchronous)
- **Returns:** Backend response containing all keys/values

### `get_single_key(key: str)`

Returns one key's stored value.

```python
preferences = self.capability_worker.get_single_key("user_preferences")
```

- **Async:** No (synchronous)
- **Parameters:**
  - `key` (str): Key to retrieve

### Example: Multi-Step Conversation State

```python
# 1) Create state
self.capability_worker.create_key(
    key="conversation_1234",
    value={
        "last_intent": "book_flight",
        "destination": "Dubai",
        "travel_date": "2026-04-01",
        "step": "awaiting_confirmation"
    }
)

# 2) Update state
self.capability_worker.update_key(
    key="conversation_1234",
    value={
        "last_intent": "book_flight",
        "destination": "Dubai",
        "travel_date": "2026-04-01",
        "step": "confirmed"
    }
)

# 3) Read state
context = self.capability_worker.get_single_key("conversation_1234")
```

### Best Practices

1. Use descriptive keys (for example `user_123_preferences`, `conversation_456_state`, `cart_session_789`).
2. Always store structured JSON objects, not raw strings.
3. Handle missing keys safely before update:

```python
existing = self.capability_worker.get_single_key("user_preferences")
if existing:
    self.capability_worker.update_key("user_preferences", updated_value)
else:
    self.capability_worker.create_key("user_preferences", updated_value)
```

---

## 10. WebSocket Communication

### `send_data_over_websocket(data_type, data)`
Sends structured data over WebSocket. Used for custom events (music mode, DevKit actions, etc.).

```python
await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})
```

- **Async:** Yes (`await`)
- **Parameters:**
  - `data_type` (str): Event type identifier
  - `data` (dict): Payload

---

### `send_devkit_action(action)`
Sends a hardware action to a connected DevKit device.

```python
await self.capability_worker.send_devkit_action("led_on")
```

- **Async:** Yes (`await`)

---

## 11. Flow Control

### `resume_normal_flow()`

**⚠️ CRITICAL FOR `main.py` SKILLS:** You MUST call this when an interactive skill is done. It hands control back to the Agent. Without it, the Agent goes silent and the user has to restart the conversation.

```python
self.capability_worker.resume_normal_flow()
```

- **Async:** No (synchronous)
- **When to call:** On EVERY exit path:
  - End of your main logic (happy path)
  - After a `break` in a loop
  - Inside `except` blocks (error fallback)
  - After timeout
  - After user says "exit"/"stop"/"quit"

**Checklist before shipping any Ability:**
- [ ] Called after the main flow completes?
- [ ] Called after every `break` statement?
- [ ] Called in every `except` block that ends the ability?
- [ ] Called after timeout logic?
- [ ] Called after user exit detection?

**Do not call this in `background.py` daemon loops.** Background daemons are independent threads and should keep running until session end.

### `send_interrupt_signal()`

Sends an interrupt event to stop the current assistant output (speech/audio) and switch back to user input.

```python
interrupt_signal = await self.capability_worker.send_interrupt_signal()
```

- **Async:** Yes (`await`)
- **Use case:** Manual cutoffs when your Ability needs to immediately stop ongoing output and listen for fresh input
- **Background daemon rule:** Call this before daemon `speak()`, `play_audio()`, or `play_from_audio_file()` to avoid audio overlap.

---

## 12. Logging

### `editor_logging_handler`

**Always use this. Never use `print()`.**

```python
self.worker.editor_logging_handler.info("Something happened")
self.worker.editor_logging_handler.error("Something broke")
self.worker.editor_logging_handler.warning("Something suspicious")
self.worker.editor_logging_handler.debug("Debugging")
```

- **Tip:** Log before and after API calls so you can see what's happening in the Live Editor:
  ```python
  self.worker.editor_logging_handler.info(f"Calling weather API for {city}...")
  response = requests.get(url, timeout=10)
  self.worker.editor_logging_handler.info(f"Weather API returned: {response.status_code}")
  ```

---

## 13. Session Tasks

OpenHome's managed task system. Ensures async work gets properly cancelled when sessions end. Raw `asyncio` tasks can outlive a session — if the user hangs up or switches abilities, your task keeps running as a ghost process. `session_tasks` ensures everything gets cleaned up properly.

### `session_tasks.create(coroutine)`
Launches an async task within the agent's managed lifecycle.

```python
self.worker.session_tasks.create(self.my_async_method())
```

- **Use instead of:** `asyncio.create_task()` (which can leak tasks)

### `session_tasks.sleep(seconds)`
Pauses execution for the specified duration.

```python
await self.worker.session_tasks.sleep(5.0)
```

- **Use instead of:** `asyncio.sleep()` (which can't be cleanly cancelled)
- **Daemon best practice:** Background `background.py` loops should always use this for polling intervals.

---

## 14. User Connection Info

### `get_timezone()`
Returns the timezone for the active user/session when available.

```python
timezone = self.capability_worker.get_timezone()
```

- **Async:** No (synchronous)
- **Returns:** Timezone string (for example `America/Chicago`) or empty/`None` when unavailable
- **Use case:** Time-aware scheduling, local date/time formatting, reminders
- **Common daemon use:** Alarm/reminder checks aligned to the user's local timezone

### `user_socket.client.host`
The user's public IP address at connection time.

```python
user_ip = self.worker.user_socket.client.host
self.worker.editor_logging_handler.info(f"User connected from: {user_ip}")
```

- **Use case:** IP-based geolocation, timezone detection, personalization
- **Tip:** Cloud/datacenter IPs won't give you useful location data. Check the ISP name for keywords like "amazon", "aws", "google cloud" before using for geolocation.

### Example: IP Geolocation

```python
import requests

def get_user_location(self):
    """Get user's city and timezone from their IP address."""
    try:
        ip = self.worker.user_socket.client.host
        resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                # Check for cloud/datacenter IPs
                isp = data.get("isp", "").lower()
                cloud_indicators = ["amazon", "aws", "google", "microsoft", "azure", "digitalocean"]
                if any(c in isp for c in cloud_indicators):
                    self.worker.editor_logging_handler.warning("Cloud IP detected, location may be inaccurate")
                    return None
                return {
                    "city": data.get("city"),
                    "region": data.get("regionName"),
                    "country": data.get("country"),
                    "timezone": data.get("timezone"),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                }
    except Exception as e:
        self.worker.editor_logging_handler.error(f"Geolocation error: {e}")
    return None
```

---

## 15. Conversation Memory & History

### `get_full_message_history()`
Access the full conversation message history from the current session through `CapabilityWorker`.

```python
history = self.capability_worker.get_full_message_history()
self.worker.editor_logging_handler.info(f"Messages so far: {len(history)}")
```

- **Returns:** The complete message history for the active session
- **Use case:** Building context-aware abilities that know what was said before the ability was triggered
- **Common daemon use:** Live conversation monitoring for note-taking, summarization, and event detection

### `update_personality_agent_prompt(prompt_addition)`
Append additional instructions/context to the active Agent personality prompt.

```python
self.capability_worker.update_personality_agent_prompt(
    "The user prefers concise answers and metric units."
)
```

- **Async:** No (synchronous)
- **Use case:** Persist behavior/context updates into the Agent's prompt for later turns

### Maintaining History in a Looping Ability

The `text_to_text_response` method accepts a `history` parameter. Use it to maintain multi-turn conversation context:

```python
self.history = []

async def main_loop(self):
    system = "You are a helpful cooking assistant. Keep answers under 2 sentences."
    while True:
        user_input = await self.capability_worker.user_response()
        if "exit" in user_input.lower():
            break
        self.history.append({"role": "user", "content": user_input})
        response = self.capability_worker.text_to_text_response(  # No await!
            user_input,
            history=self.history,
            system_prompt=system
        )
        self.history.append({"role": "assistant", "content": response})
        await self.capability_worker.speak(response)
    self.capability_worker.resume_normal_flow()
```

### Passing Context Back After `resume_normal_flow()`

After an Ability finishes, you can carry context forward in a few ways. When `resume_normal_flow()` fires, direct execution returns to the Agent.

**What you CAN do:**

1. **Save to conversation history** — Anything spoken during the Ability (via `speak()`) becomes part of the conversation history, which the Agent's LLM can see in subsequent turns.
2. **Update the Agent prompt** — Use `update_personality_agent_prompt(prompt_addition)` to append durable instructions/context to the Agent's personality prompt.
3. **Use file storage** — Write data to persistent files (see [File Storage](#8-file-storage-persistent--temporary)) that other Abilities can read later. The Agent itself won't read these files directly, but your Abilities can share data through them.
4. **Memory feature** — OpenHome has a new memory feature that can persist user context. (Details TBD as this feature evolves.)

**What you CANNOT do (yet):**
- Silently inject hidden conversation-history entries without speaking them
- Inject arbitrary structured runtime objects directly into the Agent's LLM context without using prompt/history/file mechanisms

---

## 16. Music Mode

When playing audio that's longer than a TTS utterance (music, sound effects, long recordings), you need to signal the system to stop listening and not interrupt.

### Full Pattern

```python
async def play_track(self, audio_bytes):
    # 1. Enter music mode (system stops listening, won't interrupt)
    self.worker.music_mode_event.set()
    await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})

    # 2. Play the audio
    await self.capability_worker.play_audio(audio_bytes)

    # 3. Exit music mode (system resumes listening)
    await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
    self.worker.music_mode_event.clear()
```

**What happens if you skip Music Mode:** The system may try to transcribe the audio playback as user speech, or interrupt the playback thinking the user is talking.

---

## 17. Common Patterns

### LLM as Intent Router

Use the LLM to classify user intent and route to different actions:

```python
def classify_intent(self, user_input: str) -> dict:
    prompt = (
        "Classify this user input. Return ONLY valid JSON.\n"
        '{"intent": "weather|timer|music|chat", "confidence": 0.0-1.0}\n\n'
        f"User: {user_input}"
    )
    raw = self.capability_worker.text_to_text_response(prompt)  # No await!
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return {"intent": "chat", "confidence": 0.0}
```

### Error Handling for Voice

Always speak errors to the user and always resume:

```python
async def do_something(self):
    try:
        response = requests.get("https://api.example.com/data", timeout=10)
        if response.status_code == 200:
            data = response.json()
            await self.capability_worker.speak(f"Here's what I found: {data['result']}")
        else:
            await self.capability_worker.speak("Sorry, I couldn't get that information right now.")
    except Exception as e:
        self.worker.editor_logging_handler.error(f"API error: {e}")
        await self.capability_worker.speak("Something went wrong. Let me hand you back.")
    self.capability_worker.resume_normal_flow()  # ALWAYS called
```

### Using a Custom Voice

```python
ABILITY_VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # Deep, American, male narration voice

async def speak(self, text: str):
    await self.capability_worker.text_to_speech(text, ABILITY_VOICE_ID)
```

---

## Voice ID Quick Reference

Use with `text_to_speech(text, voice_id)` to give your Ability its own voice.

| Voice ID | Accent | Gender | Tone | Good For |
|----------|--------|--------|------|----------|
| `21m00Tcm4TlvDq8ikWAM` | American | Female | Calm | Narration |
| `EXAVITQu4vr4xnSDxMaL` | American | Female | Soft | News |
| `XrExE9yKIg1WjnnlVkGX` | American | Female | Warm | Audiobook |
| `pMsXgVXv3BLzUgSXRplE` | American | Female | Pleasant | Interactive |
| `ThT5KcBeYPX3keUQqHPh` | British | Female | Pleasant | Children |
| `ErXwobaYiN019PkySvjV` | American | Male | Well-rounded | Narration |
| `GBv7mTt0atIp3Br8iCZE` | American | Male | Calm | Meditation |
| `TxGEqnHWrfWFTfGW9XjX` | American | Male | Deep | Narration |
| `pNInz6obpgDQGcFmaJgB` | American | Male | Deep | Narration |
| `onwK4e9ZLuTAKqWW03F9` | British | Male | Deep | News |
| `D38z5RcWu1voky8WS1ja` | Irish | Male | Sailor | Games |
| `IKne3meq5aSn9XLyUdCD` | Australian | Male | Casual | Conversation |

Full catalog with 40+ voices available in the [OpenHome Dashboard](https://app.openhome.com/dashboard/home).

---

## 18. Appendix: What You CAN'T Do (Yet)

Being explicit about limitations saves developers hours of guessing:

| You might want to... | Status |
|----------------------|--------|
| Directly replace the full Agent system prompt from an Ability | ⚠️ Not supported — use `update_personality_agent_prompt(prompt_addition)` to append instructions |
| Pass structured data back to the Agent after `resume_normal_flow()` | ❌ Not possible — use conversation history, prompt updates, or file storage as workarounds |
| Access other Abilities from within an Ability | ❌ Not supported |
| Run background tasks for the active session | ✅ Supported via `background.py` background daemons |
| Keep tasks alive after the session ends | ❌ Not supported — session tasks are cancelled on session end |
| Access a database directly (Redis, SQL, etc.) | ❌ Blocked — use File Storage API instead |
| Use `print()` | ❌ Blocked — use `editor_logging_handler` |
| Use `asyncio.sleep()` or `asyncio.create_task()` | ❌ Blocked — use `session_tasks` |
| Use `open()` for raw file access | ❌ Blocked — use File Storage API |
| Import `redis`, `connection_manager`, `user_config` | ❌ Blocked |

---

## 19. Appendix: Blocked Imports

These will cause your Ability to be rejected by the sandbox:

| Import | Why | Use Instead |
|--------|-----|-------------|
| `redis` | Direct datastore coupling | File Storage API |
| `RedisHandler` | Bypasses platform abstractions | File Storage API |
| `connection_manager` | Breaks isolation | CapabilityWorker APIs |
| `user_config` | Can leak global state | File Storage API |

Also avoid: `exec()`, `eval()`, `pickle`, `dill`, `shelve`, `marshal`, hardcoded secrets, MD5, ECB cipher mode.

---

*Last updated: March 2026*  
*Found an undocumented method? Report it on [Discord](https://discord.gg/openhome) so we can add it here.*
