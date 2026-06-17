# Camera Feed Template — OpenHome Ability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)
![Local](https://img.shields.io/badge/Category-Local-green?style=flat-square)

## What This Is
**This is a template ability** that lets your OpenHome agent look at a live RTSP camera feed and answer spoken questions about what it sees. It grabs a single frame from the camera on the DevKit, sends it to OpenAI's vision model (`gpt-4o`), and speaks back a natural description — and it remembers the conversation so follow-up questions work.

The cloud side (`main.py`) handles intent and conversation; the device side (`devkit_functions.py`) runs on the DevKit, captures the frame with `ffmpeg`, and calls OpenAI. The two sides talk through `send_devkit_capability_action()`.

> ⚠️ **Local abilities cannot be tested in the Live Editor.** They run on a connected DevKit device.

## What You Can Build
- **"What's happening?" room monitor** — describe the scene on demand
- **Doorway / entry watch** — "is anyone at the door?"
- **Object / people counter** — "how many people are standing?"
- **Multi-camera switching** — ask about a second camera in the same conversation
- **Accessibility describer** — narrate a live view for low-vision users
- **Read-the-sign helper** — "what's written on the wall?"

## Requirements
- An OpenHome DevKit (or local machine) running the device-side bridge.
- `ffmpeg` installed on the device (used to grab one frame over RTSP).
- `requests` on the device for the OpenAI call.
- One or two RTSP camera URLs.
- An OpenAI API key with access to `gpt-4o` vision.

## Setup Instructions

### 1. Configure the Camera URLs and API Key
Edit the constants at the top of `main.py`:
```python
RTSP_URL_1 = "rtsp://<user>:<pass>@<camera-ip>:554/<stream-path>"
RTSP_URL_2 = "rtsp://<user>:<pass>@<camera-ip>:554/<stream-path>"
OPENAI_API_KEY = "sk-REPLACE_WITH_YOUR_OPENAI_KEY"
```
- `RTSP_URL_1` is the default camera; `RTSP_URL_2` is the "other / second" camera.
- Replace the OpenAI key with your own (use a placeholder before submitting the template).

### 2. Get the Template
Add it to your agent from the OpenHome dashboard or [GitHub](https://github.com/OpenHome-dev/abilities), set trigger words, then power on the DevKit, connect it, and say a trigger word.

## Using This Template

### Template Trigger Words
This template uses generic triggers — **customize these** for your ability:
- "what do you see" / "check the camera" / "look at the camera"
- Configure your own trigger words in the OpenHome dashboard.

### Default Template Behavior
1. User asks a question about the camera
2. The LLM classifies the message (ask vs. exit, which camera, and a short acknowledgement)
3. The ability speaks the acknowledgement ("Looking for plants in the camera")
4. The DevKit grabs a frame and OpenAI describes it
5. The answer is spoken, and the exchange is added to the conversation history for follow-ups
6. The loop continues until the user exits

## How the Template Works

### Cloud Side (`main.py`)
1. `wait_for_complete_transcription()` captures the question
2. `_classify()` calls `text_to_text_response()` with `INTENT_PROMPT` and parses a JSON object:
   `{ "intent": "ask|exit", "camera": "camera_1|camera_2", "ack": "<short spoken line>" }`
3. The chosen RTSP URL and the labeled question (plus JSON history) are dispatched to the device:
```python
result = await self.capability_worker.send_devkit_capability_action(
    "describe_room",
    [url, OPENAI_API_KEY, labeled, json.dumps(history)],
    DEVICE_TIMEOUT,
)
```
4. `_read_result()` parses the device response and maps failure `reason` codes to friendly spoken messages
5. On success, the user message and answer are appended to `history` (capped at `HISTORY_MAX`)

### Device Side (`devkit_functions.py`)
1. `_grab_frame()` runs `ffmpeg` over RTSP (TCP transport) to capture **one** JPEG frame
2. The frame is base64-encoded into a data URL
3. Prior conversation history is prepended, then the frame + question is sent to OpenAI (`gpt-4o`, `temperature=0`)
4. The result is emitted as JSON on stdout:
   - `{"ok": true, "answer": "..."}` on success
   - `{"ok": false, "reason": "camera|openai|auth|config|empty"}` on failure
5. The `SYSTEM_PROMPT` instructs the model to describe **only** what's actually visible and to answer naturally for speech.

## Core Template Functions

### `send_devkit_capability_action()` (cloud → device)
Dispatches the `describe_room` action with the camera URL, API key, labeled prompt, and JSON history; waits up to `DEVICE_TIMEOUT` seconds.

### `describe_room()` (device-side bridge)
Grabs a frame and calls OpenAI vision. Returns a structured JSON result that the cloud side maps to a spoken answer or a specific error message.

## Template Usage Examples

> **User:** "what's happening?" → **AI:** "Looking at what the camera sees." → **AI:** *(describes the scene)*
>
> **User:** "how many plants are in the picture?" → **AI:** "Looking for plants in the camera." → **AI:** "I can see two potted plants on the windowsill."
>
> **User:** "what's on the other camera?" → **AI:** "Checking the other camera now." → **AI:** *(describes camera 2)*
>
> **User:** "okay that's all, thanks" → **AI:** "Okay, all done." *(ability exits)*

## Customizing the Template

### 1. Add More Cameras
Add more `RTSP_URL_*` constants and extend the camera selection logic in `_classify()` / `run()`.

### 2. Change the Vision Model or Detail
Edit `OPENAI_MODEL`, `max_tokens`, or the image `detail` in `devkit_functions.py`.

### 3. Tune the Personality
Edit `SYSTEM_PROMPT` (how answers are phrased) and `INTENT_PROMPT` (how intent and acknowledgements are produced).

### 4. Adjust History and Timeouts
`HISTORY_MAX` controls follow-up memory; `DEVICE_TIMEOUT`, `CAPTURE_TIMEOUT`, and `OPENAI_TIMEOUT` control how long each step waits.

## Best Practices
- **Acknowledge before fetching** — the spoken `ack` keeps the experience responsive while the frame is captured.
- **Never invent detail** — the system prompt forces the model to describe only what is visible.
- **Handle device-down gracefully** — `_read_result()` always returns a spoken message, even on failure.
- **Always call `resume_normal_flow()`** — the `finally` block guarantees control returns to the Agent.

## Troubleshooting

### "I can't reach that camera right now"
Check the RTSP URL, credentials, and that the camera is reachable from the DevKit. Look for `_grab_frame: ffmpeg failed` in the device logs.

### "The OpenAI key looks invalid"
The OpenAI call returned 401/403 — verify `OPENAI_API_KEY`.

### "I looked, but couldn't make out anything clear"
The frame was captured but the model returned an empty answer — try rephrasing or check the camera view.

## Links & Resources
- [Dashboard](https://app.openhome.com/dashboard)
- [Abilities Library](https://app.openhome.com/dashboard/abilities)
- [Developer Docs](https://docs.openhome.com)

## Final Reminder
⚠️ **This template is a starting point, not a finished product.** Replace the camera URLs and API key, and customize the prompts and camera logic for your specific use case.
