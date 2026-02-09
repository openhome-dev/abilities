# Patterns Cookbook

Common patterns for building Abilities. Copy and adapt these to your needs.

---

## Pattern 1: Simple One-Shot

Ask → respond → done. The simplest pattern.

```python
async def run(self):
    await self.capability_worker.speak("What would you like to know?")
    user_input = await self.capability_worker.user_response()
    response = self.capability_worker.text_to_text_response(f"Answer briefly: {user_input}")
    await self.capability_worker.speak(response)
    self.capability_worker.resume_normal_flow()
```

---

## Pattern 2: Conversation Loop with Exit

Interactive back-and-forth until the user says "stop".

```python
EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye"}

async def run(self):
    await self.capability_worker.speak("I'm ready. Say stop when you're done.")
    while True:
        user_input = await self.capability_worker.user_response()
        if not user_input:
            continue
        if any(w in user_input.lower() for w in EXIT_WORDS):
            await self.capability_worker.speak("Goodbye!")
            break
        response = self.capability_worker.text_to_text_response(f"Respond briefly: {user_input}")
        await self.capability_worker.speak(response)
    self.capability_worker.resume_normal_flow()
```

---

## Pattern 3: External API Call

Fetch data from an API and speak the result.

```python
import requests

async def run(self):
    await self.capability_worker.speak("Let me look that up.")
    try:
        resp = requests.get("https://api.example.com/data", params={"q": "query"})
        if resp.status_code == 200:
            data = resp.json()
            summary = self.capability_worker.text_to_text_response(
                f"Summarize for voice in one sentence: {data}"
            )
            await self.capability_worker.speak(summary)
        else:
            await self.capability_worker.speak("Sorry, I couldn't get that data.")
    except Exception as e:
        self.worker.editor_logging_handler.error(f"API error: {e}")
        await self.capability_worker.speak("Something went wrong.")
    self.capability_worker.resume_normal_flow()
```

---

## Pattern 4: Yes/No Confirmation

Use the built-in confirmation loop.

```python
async def run(self):
    confirmed = await self.capability_worker.run_confirmation_loop(
        "Would you like me to set a timer for 5 minutes?"
    )
    if confirmed:
        await self.capability_worker.speak("Timer set!")
    else:
        await self.capability_worker.speak("No problem.")
    self.capability_worker.resume_normal_flow()
```

---

## Pattern 5: LLM as Intent Router

Use the LLM to classify what the user wants, then branch.

```python
import json

def classify_intent(self, user_input: str) -> dict:
    prompt = (
        f"Classify this input into one of: CREATE, MODIFY, EXIT, CHAT.\n"
        f"Return ONLY JSON: {{\"intent\": \"string\", \"confidence\": float}}\n"
        f"Input: {user_input}"
    )
    raw = self.capability_worker.text_to_text_response(prompt)
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except:
        return {"intent": "CHAT", "confidence": 0.0}

async def run(self):
    await self.capability_worker.speak("What would you like to do?")
    user_input = await self.capability_worker.user_response()
    intent = self.classify_intent(user_input)

    if intent["intent"] == "CREATE":
        await self.capability_worker.speak("Creating...")
    elif intent["intent"] == "MODIFY":
        await self.capability_worker.speak("Modifying...")
    else:
        await self.capability_worker.speak("Got it.")
    self.capability_worker.resume_normal_flow()
```

---

## Pattern 6: Music / Audio Playback

Download and play audio with music mode signaling.

```python
import requests

async def run(self):
    self.worker.music_mode_event.set()
    await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})

    resp = requests.get("https://example.com/song.mp3")
    await self.capability_worker.play_audio(resp.content)

    await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
    self.worker.music_mode_event.clear()
    self.capability_worker.resume_normal_flow()
```

---

## Pattern 7: Custom Voice

Use a specific ElevenLabs voice instead of the Personality's default.

```python
VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # Deep American male

async def speak_custom(self, text: str):
    await self.capability_worker.text_to_speech(text, VOICE_ID)

async def run(self):
    await self.speak_custom("Hello from a custom voice!")
    self.capability_worker.resume_normal_flow()
```

---

## Pattern 8: Conversation History

Pass conversation history to the LLM for context-aware responses.

```python
async def run(self):
    history = []
    await self.capability_worker.speak("Let's chat. Say stop to end.")

    while True:
        user_input = await self.capability_worker.user_response()
        if "stop" in user_input.lower():
            break

        history.append({"role": "user", "content": user_input})
        response = self.capability_worker.text_to_text_response(
            user_input, history=history, system_prompt="You are a helpful assistant."
        )
        history.append({"role": "assistant", "content": response})
        await self.capability_worker.speak(response)

    self.capability_worker.resume_normal_flow()
```

---

## Anti-Patterns (Don't Do This)

```python
# ❌ Don't use print
print("hello")
# ✅ Use the logger
self.worker.editor_logging_handler.info("hello")

# ❌ Don't use asyncio.sleep
await asyncio.sleep(5)
# ✅ Use session tasks
await self.worker.session_tasks.sleep(5)

# ❌ Don't forget resume_normal_flow
async def run(self):
    await self.capability_worker.speak("Done!")
    # Personality is now stuck!
# ✅ Always call it
async def run(self):
    await self.capability_worker.speak("Done!")
    self.capability_worker.resume_normal_flow()
```
