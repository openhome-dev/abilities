# Watcher Template — Background Monitoring Ability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)
![Advanced](https://img.shields.io/badge/Level-Advanced-red?style=flat-square)

## What This Is
**This is a background ability template** that runs continuously in an endless loop. Unlike normal abilities that respond once and exit, watcher abilities stay active throughout the agent session, monitoring conditions and triggering actions automatically.

## Key Characteristics

### Background Execution
- **Runs automatically** — Watcher abilities are auto-triggered when your agent starts
- **Endless loop** — The `while True` keeps the ability running continuously
- **Background operation** — Runs silently alongside the normal conversation flow
- **All CapabilityWorker functions available** — Full SDK access within the watcher

### What Makes Watchers Different

| Normal Ability | Watcher Ability |
|----------------|-----------------|
| User triggers with voice command | Auto-starts when agent initializes |
| Speak → Listen → Respond → Exit | Continuous loop: Monitor → Act → Sleep → Repeat |
| Calls `resume_normal_flow()` to exit | `resume_normal_flow()` never reached (intentional) |
| Session-specific | Background for entire agent session |

## Template Features

This basic watcher template demonstrates:

1. **Continuous monitoring** — Endless `while True` loop
2. **Message history access** — Reads last 10 messages from normal conversation
3. **Logging** — Records activity via `editor_logging_handler`
4. **Sleep intervals** — 20-second pause between checks
5. **Commented examples** — Audio playback and speech capabilities

## How It Works

### Template Flow
```
Agent Starts
    ↓
Watcher Auto-Triggers
    ↓
Enter while True Loop
    ↓
┌─────────────────────┐
│ Log "watching"      │
│ Get last 10 messages│
│ Log each message    │
│ Sleep 20 seconds    │
└─────────┬───────────┘
          │
          └─→ Repeat Forever
```

### Code Walkthrough

**1. Watcher Mode Initialization:**
```python
def call(self, worker: AgentWorker, watcher_mode: bool):
    self.worker = worker
    self.watcher_mode = watcher_mode  # ← Background mode flag
    self.capability_worker = CapabilityWorker(self)
    self.worker.session_tasks.create(self.first_function())
```
- `watcher_mode=True` indicates this is a background ability
- Auto-creates async task that runs in background

**2. Endless Loop:**
```python
async def first_function(self):
    self.worker.editor_logging_handler.info("%s: Watcher Called" % time())
    
    while True:  # ← Never exits
        self.worker.editor_logging_handler.info("%s: watcher watching" % time())
        
        # Your monitoring logic here
        ...
        
        await self.worker.session_tasks.sleep(20.0)  # ← Sleep before next check
```
- Loop runs indefinitely (no break condition)
- Checks conditions every 20 seconds
- Never calls `resume_normal_flow()` — this is intentional

**3. Access Message History:**
```python
message_history = self.capability_worker.get_full_message_history()[-10:]
```
- Returns last **50 messages** by default (template uses last 10)
- Each message is a dict with `role` and `content`
- Provides context from normal conversation flow

**4. Log Activity:**
```python
for message in message_history:
    self.worker.editor_logging_handler.info(
        "Role: %s, Message: %s" % (message.get("role", ""), message.get("content", ""))
    )
```
- Always use `editor_logging_handler` (not `print`)
- Logs are visible in dashboard/logs

**5. Sleep Between Checks:**
```python
await self.worker.session_tasks.sleep(20.0)
```
- **Critical:** Use `session_tasks.sleep()`, NEVER `asyncio.sleep()`
- 20 seconds is template default (adjust to your needs)

**6. Commented Examples:**
```python
# await self.capability_worker.speak("watching")
# await self.capability_worker.play_from_audio_file("alarm.mp3")
```
- Shows how to trigger audio/speech from watcher
- Uncomment to test capabilities

## Message History Structure

### What You Get
```python
message_history = self.capability_worker.get_full_message_history()
```

**Returns:** List of up to **50 messages** (most recent)

**Message Format:**
```python
{
    "role": "user",      # or "assistant"
    "content": "What's the weather today?"
}
```

### Example Usage

**Monitor for specific keywords:**
```python
message_history = self.capability_worker.get_full_message_history()[-10:]

for message in message_history:
    if message.get("role") == "user":
        content = message.get("content", "").lower()
        
        if "urgent" in content:
            await self.capability_worker.speak("I noticed you said something urgent!")
            await self.capability_worker.play_from_audio_file("alert.mp3")
            break  # Only alert once
```

**Track conversation patterns:**
```python
user_messages = [
    msg for msg in message_history 
    if msg.get("role") == "user"
]

if len(user_messages) > 5:
    # User has been very active
    self.worker.editor_logging_handler.info("High conversation activity detected")
```

## Audio Playback in Watchers

### Play Files from Ability Directory
```python
await self.capability_worker.play_from_audio_file("alarm.mp3")
```

**Setup:**
1. Place audio file in your ability's folder (e.g., `alarm.mp3`)
2. Supported formats: `.mp3`, `.wav`, `.ogg`
3. Call from anywhere in the watcher loop

**Example watcher with audio alerts:**
```python
async def first_function(self):
    alert_count = 0
    
    while True:
        message_history = self.capability_worker.get_full_message_history()[-10:]
        
        # Check for alert conditions
        for message in message_history:
            if "emergency" in message.get("content", "").lower():
                await self.capability_worker.play_from_audio_file("emergency.mp3")
                alert_count += 1
                break
        
        self.worker.editor_logging_handler.info(f"Alerts fired: {alert_count}")
        await self.worker.session_tasks.sleep(10.0)
```

### Speak from Watcher
```python
await self.capability_worker.speak("I'm monitoring in the background!")
```

**Use cases:**
- Periodic reminders
- Alert announcements
- Status updates

**Example periodic reminder:**
```python
async def first_function(self):
    reminder_interval = 300  # 5 minutes
    last_reminder = time()
    
    while True:
        now = time()
        
        if now - last_reminder >= reminder_interval:
            await self.capability_worker.speak("Reminder: Take a break and stretch!")
            last_reminder = now
        
        await self.worker.session_tasks.sleep(30.0)
```

## All CapabilityWorker Functions Available

Watchers have **full SDK access**. You can use:

### Conversation Functions
```python
await self.capability_worker.speak("Message")
await self.capability_worker.user_response()
message_history = self.capability_worker.get_full_message_history()
```

### Text Generation
```python
response = self.capability_worker.text_to_text_response("Analyze this...")
```

### File Operations
```python
await self.capability_worker.write_file("log.txt", data, False)
data = await self.capability_worker.read_file("config.json", False)
exists = await self.capability_worker.check_if_file_exists("data.txt", False)
await self.capability_worker.delete_file("temp.txt", False)
```

### Audio
```python
await self.capability_worker.play_from_audio_file("sound.mp3")
await self.capability_worker.play_audio(audio_bytes)
```

### Device Actions
```python
await self.capability_worker.send_devkit_action("led_on")
await self.capability_worker.send_notification_to_ios("Title", "Body")
```

**Example watcher using multiple SDK functions:**
```python
async def first_function(self):
    while True:
        # Check for new data file
        if await self.capability_worker.check_if_file_exists("trigger.txt", False):
            # Read trigger data
            data = await self.capability_worker.read_file("trigger.txt", False)
            
            # Use LLM to analyze
            analysis = self.capability_worker.text_to_text_response(
                f"Summarize this in one sentence: {data}"
            )
            
            # Speak the summary
            await self.capability_worker.speak(f"Alert: {analysis}")
            
            # Play sound
            await self.capability_worker.play_from_audio_file("notification.mp3")
            
            # Clean up trigger file
            await self.capability_worker.delete_file("trigger.txt", False)
        
        await self.worker.session_tasks.sleep(10.0)
```

## Common Watcher Patterns

### Pattern 1: Keyword Monitor
Watch conversation for specific words/phrases:

```python
async def first_function(self):
    keywords = ["help", "urgent", "emergency", "important"]
    
    while True:
        message_history = self.capability_worker.get_full_message_history()[-5:]
        
        for message in message_history:
            if message.get("role") == "user":
                content = message.get("content", "").lower()
                
                if any(keyword in content for keyword in keywords):
                    await self.capability_worker.speak("I noticed you need attention!")
                    await self.capability_worker.play_from_audio_file("alert.mp3")
        
        await self.worker.session_tasks.sleep(15.0)
```

### Pattern 2: Activity Timer
Detect user inactivity and prompt:

```python
async def first_function(self):
    last_user_message_time = time()
    inactivity_threshold = 300  # 5 minutes
    
    while True:
        message_history = self.capability_worker.get_full_message_history()[-1:]
        
        if message_history and message_history[0].get("role") == "user":
            last_user_message_time = time()
        
        now = time()
        if now - last_user_message_time > inactivity_threshold:
            await self.capability_worker.speak("Still here if you need anything!")
            last_user_message_time = now  # Reset to avoid spam
        
        await self.worker.session_tasks.sleep(60.0)
```

### Pattern 3: File Watcher
Monitor for new files and process them:

```python
async def first_function(self):
    processed_files = set()
    
    while True:
        # Check for new data file
        if await self.capability_worker.check_if_file_exists("inbox.txt", False):
            content = await self.capability_worker.read_file("inbox.txt", False)
            
            # Create unique ID for this content
            content_hash = hash(content)
            
            if content_hash not in processed_files:
                # Process new content
                await self.capability_worker.speak(f"New data received: {content[:50]}")
                await self.capability_worker.play_from_audio_file("notification.mp3")
                
                processed_files.add(content_hash)
                
                # Archive processed data
                await self.capability_worker.write_file(
                    "processed.txt",
                    f"\n{content}",
                    False
                )
        
        await self.worker.session_tasks.sleep(5.0)
```

### Pattern 4: Sentiment Monitor
Track conversation tone and alert if negative:

```python
async def first_function(self):
    while True:
        message_history = self.capability_worker.get_full_message_history()[-10:]
        
        # Combine recent messages
        recent_conversation = "\n".join([
            msg.get("content", "") 
            for msg in message_history 
            if msg.get("role") == "user"
        ])
        
        # Analyze sentiment
        if recent_conversation:
            sentiment_prompt = f"""Analyze sentiment of this conversation: {recent_conversation}
            
            Return only: "positive", "neutral", or "negative"
            """
            
            sentiment = self.capability_worker.text_to_text_response(sentiment_prompt).lower().strip()
            
            if "negative" in sentiment:
                self.worker.editor_logging_handler.warning("Negative sentiment detected")
                # Could trigger supportive response
        
        await self.worker.session_tasks.sleep(30.0)
```

## Best Practices

### 1. Always Use session_tasks.sleep()
```python
# ✅ CORRECT
await self.worker.session_tasks.sleep(20.0)

# ❌ WRONG — Won't clean up properly
await asyncio.sleep(20.0)
```

### 2. Set Appropriate Sleep Intervals
```python
# ✅ GOOD — Reasonable intervals
await self.worker.session_tasks.sleep(5.0)   # Quick monitoring
await self.worker.session_tasks.sleep(30.0)  # Moderate checks
await self.worker.session_tasks.sleep(60.0)  # Periodic polling

# ❌ BAD — Too frequent, wastes resources
await self.worker.session_tasks.sleep(0.1)

# ⚠️ CAUTION — Too infrequent, may miss events
await self.worker.session_tasks.sleep(600.0)
```

**Guidelines:**
- **Real-time monitoring:** 1-5 seconds
- **Keyword watching:** 10-20 seconds
- **Periodic reminders:** 30-60 seconds
- **Activity tracking:** 30-120 seconds

### 3. Use editor_logging_handler (Not print)
```python
# ✅ CORRECT
self.worker.editor_logging_handler.info("Watcher started")
self.worker.editor_logging_handler.warning("Unusual activity")
self.worker.editor_logging_handler.error(f"Error: {e}")

# ❌ WRONG — Won't appear in logs
print("Watcher started")
```

### 4. Wrap Loop in Try-Catch
```python
async def first_function(self):
    while True:
        try:
            # Your monitoring logic
            ...
            
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Watcher error: {e}")
            await self.worker.session_tasks.sleep(5.0)  # Brief pause before retry
```

### 5. Limit Message History Access
```python
# ✅ GOOD — Get only what you need
message_history = self.capability_worker.get_full_message_history()[-10:]

# ⚠️ CAREFUL — Full history (50 messages) may be overkill
message_history = self.capability_worker.get_full_message_history()
```

### 6. Avoid Duplicate Actions
```python
# Track what's been processed
processed_message_ids = set()

while True:
    message_history = self.capability_worker.get_full_message_history()[-10:]
    
    for message in message_history:
        msg_id = hash(f"{message.get('role')}{message.get('content')}")
        
        if msg_id not in processed_message_ids:
            # Process new message
            ...
            processed_message_ids.add(msg_id)
    
    await self.worker.session_tasks.sleep(10.0)
```

### 7. Keep Processing Lightweight
```python
# ✅ GOOD — Quick checks
if "keyword" in content:
    do_something()

# ❌ BAD — Heavy processing in hot loop
for message in message_history:
    # Don't call slow APIs or heavy computation repeatedly
    result = expensive_api_call(message)  # This slows everything down
```

## What You Can Build

Examples of watcher abilities:

- **Conversation monitors** — Track keywords, sentiment, activity
- **Periodic reminders** — "Take a break" every 30 minutes
- **File processors** — Watch for new files and auto-process
- **Alert systems** — Detect conditions and play audio alerts
- **Activity trackers** — Log user engagement patterns
- **Sentiment analyzers** — Monitor conversation tone
- **Notification triggers** — Send iOS notifications on events
- **Data aggregators** — Collect and summarize conversation data

## Troubleshooting

### Watcher Stops Running
**Problem:** Loop exits unexpectedly

**Solutions:**
- Add try-catch around entire loop
- Check logs for error messages
- Verify using `session_tasks.sleep()` not `asyncio.sleep()`

### Audio File Won't Play
**Problem:** `play_from_audio_file()` fails

**Solutions:**
- Verify file exists in ability directory
- Check filename matches exactly (case-sensitive)
- Try different format (.mp3 vs .wav)

### High CPU Usage
**Problem:** Watcher consumes too many resources

**Solutions:**
- Increase sleep interval
- Reduce message history size (use [-5:] instead of [-50:])
- Avoid heavy processing in loop

### Message History Empty
**Problem:** `get_full_message_history()` returns empty list

**Explanation:** Normal — no messages yet in conversation

**Solution:** Check if list is empty before processing:
```python
message_history = self.capability_worker.get_full_message_history()
if not message_history:
    await self.worker.session_tasks.sleep(20.0)
    continue
```

## Limitations

### What Watchers Cannot Do

**No Cross-Session Persistence:**
- Watcher stops when agent session ends
- Cannot fire events after user logs out
- Not suitable for true background tasks (24/7 monitoring)

**No Proactive Interruption:**
- Cannot interrupt user mid-conversation
- Actions happen during natural pauses
- Must respect conversation flow

**Resource Constraints:**
- Should not run expensive operations continuously
- Sleep intervals prevent excessive resource use
- Keep processing lightweight

## Security Considerations

### Rate Limiting
Prevent abuse by limiting frequency:
```python
MIN_SLEEP = 5.0  # Minimum 5 seconds between checks

await self.worker.session_tasks.sleep(max(MIN_SLEEP, custom_interval))
```

### Sensitive Data
Don't log sensitive information:
```python
# ❌ BAD — Logs sensitive content
self.worker.editor_logging_handler.info(f"Message: {message.get('content')}")

# ✅ GOOD — Log only metadata
self.worker.editor_logging_handler.info(f"Message count: {len(message_history)}")
```

## Quick Start Checklist

### Understanding Watchers
- [ ] Understand watchers run automatically in background
- [ ] Know `while True` never exits (intentional)
- [ ] Recognize `resume_normal_flow()` is unreachable
- [ ] Understand session-scoped nature (not 24/7)

### Building Your Watcher
- [ ] Define what to monitor (messages, files, time, etc.)
- [ ] Set appropriate sleep interval (10-60 seconds typical)
- [ ] Add try-catch around entire loop
- [ ] Use `session_tasks.sleep()`, not `asyncio.sleep()`
- [ ] Use `editor_logging_handler` for all logging
- [ ] Test with various scenarios

### Adding Features
- [ ] Access message history with `get_full_message_history()`
- [ ] Play audio files from ability directory
- [ ] Speak updates with `speak()`
- [ ] Write logs to files with file operations
- [ ] Track processed items to avoid duplicates

## Links & Resources

**OpenHome Documentation:**
- [Building Great Abilities](https://docs.openhome.com/Building_Great_OpenHome_Abilities)
- [How to Build an Ability](https://docs.openhome.com/how_to_build_an_ability)
- [Dashboard](https://app.openhome.xyz/dashboard)
- [Discord Community](https://discord.com/channels/1197724389630824508)

## Support & Contribution

If you build something with watcher mode:
- 🎉 Share your implementation
- 💡 Contribute improvements
- 🤝 Help others understand watchers
- 📝 Document your use case

## Final Reminder

⚠️ **Key Takeaways:**
- ✅ Watchers run automatically in endless loops
- ✅ Access full conversation history (last 50 messages)
- ✅ Play audio and use all CapabilityWorker functions
- ✅ Background monitoring during active agent sessions
- ❌ Not truly 24/7 background tasks (session-scoped)
- ❌ Never calls `resume_normal_flow()` (by design)

Use watchers for real-time monitoring, periodic checks, and automated responses during active sessions! 🔄🚀
