# CapabilityWorker 

The `CapabilityWorker` is the core SDK class for all I/O inside an Ability. Access it via `self.capability_worker` after initializing in `call()`.

---

## Speaking (Text-to-Speech)

### `speak(text)`

Converts text to speech using the Personality's default voice.

```python
await self.capability_worker.speak("Hello! How can I help?")
```

### `text_to_speech(text, voice_id)`

Converts text to speech using a **specific Voice ID**. Use when your Ability needs its own voice.

```python
await self.capability_worker.text_to_speech("Welcome!", "pNInz6obpgDQGcFmaJgB")
```

See the [Voice ID catalog](https://github.com/openhome-dev/abilities#voice-id-reference) for available voices.

---

## Listening (User Input)

### `user_response()`

Waits for the user's next input. Returns a string.

```python
user_input = await self.capability_worker.user_response()
```

### `wait_for_complete_transcription()`

Waits until the user has completely finished speaking. Use when you need the full utterance without premature cutoff.

```python
full_input = await self.capability_worker.wait_for_complete_transcription()
```

---

## Combined Speak + Listen

### `run_io_loop(text)`

Speaks the text, then waits for a response. Returns the user's reply.

```python
answer = await self.capability_worker.run_io_loop("What's your name?")
```

### `run_confirmation_loop(text)`

Asks a yes/no question. Loops until the user confirms. Returns `True` or `False`.

```python
confirmed = await self.capability_worker.run_confirmation_loop("Should I continue?")
```

---

## Text Generation (LLM)

### `text_to_text_response(prompt_text, history=[], system_prompt="")`

Generates a text response using the configured LLM. **This is synchronous (no await).**

```python
response = self.capability_worker.text_to_text_response(
    "Explain quantum computing in one sentence."
)
```

With conversation history:

```python
history = [
    {"role": "user", "content": "Tell me about dogs"},
    {"role": "assistant", "content": "Dogs are loyal companions..."},
]
response = self.capability_worker.text_to_text_response(
    "What breeds are best for apartments?",
    history=history,
)
```

With a system prompt:

```python
response = self.capability_worker.text_to_text_response(
    "The user asked about cooking pasta",
    system_prompt="You are a professional Italian chef. Keep responses under 2 sentences.",
)
```

---

## Audio Playback

### `play_audio(file_content)`

Plays audio from bytes or a file-like object.

```python
import requests
resp = requests.get("https://example.com/sound.mp3")
await self.capability_worker.play_audio(resp.content)
```

### `play_from_audio_file(file_name)`

Plays an audio file from the Ability's folder.

```python
await self.capability_worker.play_from_audio_file("alert.mp3")
```

---

## Audio Streaming

For longer audio or real-time streaming:

```python
await self.capability_worker.stream_init()
await self.capability_worker.send_audio_data_in_stream(audio_bytes, chunk_size=4096)
await self.capability_worker.stream_end()
```

---

## WebSocket Communication

### `send_data_over_websocket(data_type, data)`

Sends structured data over WebSocket. Used for music mode, DevKit actions, and custom events.

```python
await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})
```

### `send_devkit_action(action)`

Sends a hardware action to the DevKit.

```python
await self.capability_worker.send_devkit_action("led-on")
```

---

## Flow Control

### `resume_normal_flow()`

**You MUST call this when your Ability is done.** Returns control to the Personality.

```python
self.capability_worker.resume_normal_flow()
```

If you forget this, the Personality will be stuck and unresponsive.

---

## AgentWorker Reference

Access via `self.worker`:

### Logging

```python
self.worker.editor_logging_handler.info("Something happened")
self.worker.editor_logging_handler.error("Something broke")
self.worker.editor_logging_handler.warning("Something looks off")
```

**Never use `print()`.** Always use the logging handler.

### Session Tasks

```python
self.worker.session_tasks.create(some_coroutine())   # Instead of asyncio.create_task()
await self.worker.session_tasks.sleep(2.0)            # Instead of asyncio.sleep()
```

### Music Mode

```python
self.worker.music_mode_event.set()    # Enter music mode
self.worker.music_mode_event.clear()  # Exit music mode
```
