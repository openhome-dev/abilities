# Alarm Background Template — OpenHome Ability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)
![Advanced](https://img.shields.io/badge/Level-Advanced-red?style=flat-square)

## What This Is
**This is an advanced template ability** that demonstrates OpenHome's "background mode" — a special ability type that runs continuously in the background to monitor conditions and trigger actions. This template shows how to build an alarm clock system that fires at scheduled times.

## ⚠️ Important: Background Mode Abilities

### What Makes This Different
**Normal abilities** are on-demand — they activate when triggered, do their job, then exit with `resume_normal_flow()`.

**Background abilities** run continuously in an infinite loop, checking conditions every few seconds. This template is one of the **only** ability types that doesn't call `resume_normal_flow()` because it's designed to never exit.

### Understanding the Architecture

From the official docs:
> **Abilities don't run in the background. They're on-demand** — your ability only exists while it's actively handling a conversation.

However, **Background mode is a special case**. When an ability is initialized with `background_daemon_mode=True`, it enters an infinite loop that runs for the lifetime of the session. This is used for:
- **Alarm systems** (like this template)
- **Periodic monitoring** (checking APIs every N seconds)
- **Event detection** (watching for conditions to trigger actions)

**Critical limitation:** The background loop stops when the Agent session ends. You cannot build:
- ❌ Truly "background" tasks that run 24/7
- ❌ Alarms that fire when the user isn't active
- ❌ Proactive notifications that interrupt the user

This template is best for **active session alarms** — alarms that fire while the user is already interacting with their Agent.

## What You Can Build

This background pattern can be adapted for:
- **Alarm clock** — Play audio at scheduled times (this template)
- **Timer system** — Countdown timers that fire audio alerts
- **Periodic reminders** — Check every N minutes and speak reminders
- **API monitoring** — Poll external APIs and alert on changes
- **Condition backgrounds** — Check file changes, system status, etc.

## How the Template Works

### Template Flow
1. Ability initializes with `background_daemon_mode=True`
2. Enters infinite `while True` loop
3. Every 20 seconds (configurable):
   - Logs "background watching" message
   - Reads last 10 messages from conversation history
   - Logs each message (role + content)
   - Sleeps for 20 seconds
4. Loop continues indefinitely (never calls `resume_normal_flow()`)

### Key Components

**1. Background Mode Initialization:**
```python
def call(self, worker: AgentWorker, background_daemon_mode: bool):
    self.worker = worker
    self.background_daemon_mode = background_daemon_mode  # ← Special flag
    self.capability_worker = CapabilityWorker(self)
    self.worker.session_tasks.create(self.first_function())
```
- `background_daemon_mode` parameter distinguishes this from normal abilities
- Creates infinite task with `session_tasks.create()`

**2. Infinite Watch Loop:**
```python
async def first_function(self):
    self.worker.editor_logging_handler.info("%s: Background Called" % time())
    
    while True:  # ← Never exits
        self.worker.editor_logging_handler.info("%s: Background watching" % time())
        
        # Do something (read history, check conditions, etc.)
        message_history = self.capability_worker.get_full_message_history()[-10:]
        for message in message_history:
            self.worker.editor_logging_handler.info(
                "Role: %s, Message: %s" % (message.get("role", ""), message.get("content", ""))
            )
        
        # Sleep before next check
        await self.worker.session_tasks.sleep(20.0)
    
    # ← NOTE: resume_normal_flow() is NEVER reached (intentional)
```

**3. Session Tasks Sleep:**
```python
await self.worker.session_tasks.sleep(20.0)
```
- **Never use** `asyncio.sleep()` — always use `session_tasks.sleep()`
- This ensures proper cancellation when the session ends

**4. Conversation History Access:**
```python
message_history = self.capability_worker.get_full_message_history()[-10:]
```
- Returns list of message dicts: `[{"role": "user", "content": "..."}, ...]`
- Scoped per-agent per-user
- Gets last 10 messages (adjust as needed)

## Production Alarm Implementation

The template includes a production-ready alarm background in the documents section. Here's how it works:

### Alarm Data Structure
```json
[
  {
    "id": "alarm_abc123",
    "status": "scheduled",
    "target_iso": "2024-03-15T08:00:00-05:00",
    "timezone": "America/Chicago",
    "human_time": "8:00 AM tomorrow",
    "created_at_epoch": 1710509200
  }
]
```

Stored in `alarms.json` (per-user storage).

### Alarm Background Flow
1. **Every 1 second:**
   - Read `alarms.json` safely (handles corruption)
   - Get current time in background's timezone
   - Find alarms with `status: "scheduled"` where `now >= target_iso`
2. **For each due alarm:**
   - Play `alarm.mp3` from ability directory
   - Mark alarm as `status: "triggered"` to prevent re-firing
   - Log alarm firing to `editor_logging_handler`
3. **Write back updated alarms** (delete + write pattern for JSON)

### Key Safety Features
- **Safe JSON reading** — Returns `[]` if file corrupted/missing
- **Timezone-aware** — Uses `ZoneInfo` for proper time handling
- **No repeat firing** — Marks alarms `triggered` after firing
- **Error resilient** — Try-catch around all operations, logs errors
- **Graceful degradation** — Failed audio playback doesn't crash background

## Building Your Own Background

### Pattern 1: Simple Timer
```python
async def first_function(self):
    # Set timer for 60 seconds from now
    target_time = time() + 60.0
    
    while True:
        now = time()
        
        if now >= target_time:
            await self.capability_worker.speak("Timer finished!")
            await self.capability_worker.play_from_audio_file("ding.mp3")
            break  # Exit after one-time timer
        
        await self.worker.session_tasks.sleep(1.0)
    
    self.capability_worker.resume_normal_flow()
```

### Pattern 2: Periodic Reminder
```python
async def first_function(self):
    reminder_interval = 300.0  # 5 minutes
    last_reminder = time()
    
    while True:
        now = time()
        
        if now - last_reminder >= reminder_interval:
            await self.capability_worker.speak("Reminder: Take a break!")
            last_reminder = now
        
        await self.worker.session_tasks.sleep(30.0)  # Check every 30 seconds
```

### Pattern 3: Condition Monitor
```python
async def first_function(self):
    while True:
        # Read some condition from file storage
        if await self.capability_worker.check_if_file_exists("alert_flag.txt", in_ability_directory=False):
            await self.capability_worker.speak("Alert condition detected!")
            await self.capability_worker.play_from_audio_file("alert.mp3")
            
            # Clear the flag
            await self.capability_worker.delete_file("alert_flag.txt", in_ability_directory=False)
        
        await self.worker.session_tasks.sleep(10.0)
```

### Pattern 4: API Polling
```python
import requests

async def first_function(self):
    last_value = None
    
    while True:
        try:
            # Poll external API
            response = requests.get("https://api.example.com/status", timeout=5)
            current_value = response.json().get("value")
            
            # Check if changed
            if last_value and current_value != last_value:
                await self.capability_worker.speak(f"Value changed to {current_value}")
            
            last_value = current_value
            
        except Exception as e:
            self.worker.editor_logging_handler.error(f"API poll failed: {e}")
        
        await self.worker.session_tasks.sleep(60.0)  # Poll every minute
```

## Adding Audio Files

The alarm background plays `alarm.mp3` from the ability directory:

```python
await self.capability_worker.play_from_audio_file("alarm.mp3")
```

**Setup:**
1. Place `alarm.mp3` in your ability's folder
2. Supported formats: `.mp3`, `.wav`, `.ogg`
3. Files are loaded from ability directory (not per-user storage)

**Audio file checklist:**
- [ ] File exists in ability folder
- [ ] Filename matches exactly (case-sensitive)
- [ ] File format is supported (.mp3 recommended)
- [ ] File is not corrupted

## Best Practices for Backgrounds

### 1. Always Use session_tasks.sleep()
```python
# ✅ GOOD — Proper cancellation support
await self.worker.session_tasks.sleep(20.0)

# ❌ BAD — Won't clean up properly when session ends
await asyncio.sleep(20.0)
```

### 2. Set Reasonable Sleep Intervals
```python
# ✅ GOOD — 1-30 second intervals for most use cases
await self.worker.session_tasks.sleep(5.0)

# ❌ BAD — Too frequent, wastes resources
await self.worker.session_tasks.sleep(0.1)

# ⚠️ CAUTION — Too infrequent, may miss events
await self.worker.session_tasks.sleep(300.0)
```

**Guidelines:**
- **Alarms/timers:** 1-2 seconds (needs precision)
- **Reminders:** 30-60 seconds (less critical timing)
- **API polling:** 60-300 seconds (respect rate limits)
- **File watching:** 5-10 seconds (balance between responsiveness and load)

### 3. Wrap Everything in Try-Catch
```python
while True:
    try:
        # Your background logic here
        ...
        
    except Exception as e:
        self.worker.editor_logging_handler.error(f"Background error: {e}")
        await self.worker.session_tasks.sleep(2.0)  # Brief pause before retry
```

### 4. Use editor_logging_handler (Not print)
```python
# ✅ GOOD — Structured logging
self.worker.editor_logging_handler.info("Background started")
self.worker.editor_logging_handler.error(f"Failed: {e}")

# ❌ BAD — Won't appear in logs
print("Background started")
```

### 5. Handle File Corruption Gracefully
```python
async def _read_data_safe(self):
    try:
        if not await self.capability_worker.check_if_file_exists("data.json", in_ability_directory=False):
            return {}
        
        raw = await self.capability_worker.read_file("data.json", in_ability_directory=False)
        return json.loads(raw)
        
    except json.JSONDecodeError:
        self.worker.editor_logging_handler.error("Corrupted JSON, returning defaults")
        return {}
    except Exception as e:
        self.worker.editor_logging_handler.error(f"Read failed: {e}")
        return {}
```

### 6. Use Timezone-Aware Datetime
```python
from datetime import datetime
from zoneinfo import ZoneInfo

# ✅ GOOD — Timezone-aware
tz_name = self.capability_worker.get_timezone()
tz = ZoneInfo(tz_name)
now = datetime.now(tz=tz)

# ❌ BAD — Naive datetime causes issues
now = datetime.now()  # No timezone!
```

### 7. Prevent Duplicate Actions
```python
# Track what's been processed to avoid re-firing
processed_ids = set()

while True:
    items = await self._get_items_to_process()
    
    for item in items:
        item_id = item["id"]
        
        if item_id in processed_ids:
            continue  # Skip already processed
        
        await self._process_item(item)
        processed_ids.add(item_id)
    
    await self.worker.session_tasks.sleep(10.0)
```

## Limitations of Background Mode

### What Backgrounds Cannot Do

From the official docs:
> **You can't set a timer that fires in 15 minutes to remind the user of a meeting. You can't poll an API every 5 minutes in the background. You can't have an ability proactively interrupt the user with a notification.**

**Why?** The background only exists while the Agent session is active. When the user stops talking or the session ends, the background stops.

### What This Means for Alarms

This alarm template will work **only while the user is actively using their Agent**:
- ✅ Set alarm for 5 minutes → alarm fires (if user stays active)
- ❌ Set alarm for tomorrow 8 AM → alarm won't fire (session ended)

### Workarounds

For true background alarms, you need:
1. **External system integration** — Use device's native alarm APIs
2. **Server-side scheduling** — Run background on always-on server
3. **Separate daemon** — Run independent background process

This template is best for:
- **Active session timers** (countdowns while user is present)
- **Immediate reminders** (fire in next few minutes)
- **Real-time monitoring** (while user is interacting)

## Troubleshooting

### Background Stops Running
**Problem:** Loop exits unexpectedly

**Causes:**
1. Exception not caught → crashes loop
2. Used `asyncio.sleep()` instead of `session_tasks.sleep()`
3. Session ended (user left)

**Solutions:**
- Wrap entire loop in try-catch
- Always use `self.worker.session_tasks.sleep()`
- Check logs for error messages

### Audio File Won't Play
**Problem:** `play_from_audio_file()` fails silently

**Solutions:**
1. Verify file exists in ability directory
2. Check filename matches exactly (case-sensitive)
3. Try different audio format (.mp3 vs .wav)
4. Check logs for error message

### Alarm Fires Multiple Times
**Problem:** Same alarm triggers repeatedly

**Cause:** Not marking alarm as triggered

**Solution:** Update status after firing:
```python
# After playing alarm
alarm["status"] = "triggered"
await self._save_alarms(alarms)  # Write back to file
```

### High CPU Usage
**Problem:** Background consumes too many resources

**Causes:**
1. Sleep interval too short
2. Doing expensive operations in loop
3. Not using async properly

**Solutions:**
- Increase sleep interval (5-30 seconds usually fine)
- Move expensive operations outside hot loop
- Use `await` for all IO operations

### JSON Corruption
**Problem:** `alarms.json` becomes invalid

**Cause:** Appending to JSON file (writes garbage)

**Solution:** Always delete-then-write:
```python
# Delete first
if await self.capability_worker.check_if_file_exists("alarms.json", in_ability_directory=False):
    await self.capability_worker.delete_file("alarms.json", in_ability_directory=False)

# Write fresh
await self.capability_worker.write_file(
    "alarms.json",
    json.dumps(data),
    False
)
```

## Security Considerations

### 🔒 Background-Specific Security

**1. Rate Limiting**
Prevent abuse by limiting background frequency:
```python
MIN_SLEEP = 1.0  # Minimum 1 second between checks

if sleep_duration < MIN_SLEEP:
    sleep_duration = MIN_SLEEP
```

**2. Resource Monitoring**
Log background activity to detect issues:
```python
loop_count = 0

while True:
    loop_count += 1
    
    if loop_count % 100 == 0:  # Every 100 loops
        self.worker.editor_logging_handler.info(f"background healthy: {loop_count} loops")
```

**3. Graceful Shutdown**
Allow background to clean up:
```python
try:
    while True:
        ...
except asyncio.CancelledError:
    self.worker.editor_logging_handler.info("Background cancelled, cleaning up...")
    # Clean up resources here
    raise
```

## Quick Start Checklist

### Understanding Backgrounds
- [ ] Read "What Makes This Different" section
- [ ] Understand background runs continuously (no `resume_normal_flow()`)
- [ ] Know limitations (session-scoped, not truly background)

### Building Your Background
- [ ] Define what condition to watch (file, time, API, etc.)
- [ ] Set appropriate sleep interval (1-30 seconds usually)
- [ ] Add try-catch around entire loop
- [ ] Use `session_tasks.sleep()`, not `asyncio.sleep()`
- [ ] Use `editor_logging_handler` for all logging
- [ ] Test with various failure scenarios

### For Alarm Systems
- [ ] Add `alarm.mp3` file to ability directory
- [ ] Implement safe JSON reading with default fallback
- [ ] Use timezone-aware datetime
- [ ] Mark processed items to prevent duplicates
- [ ] Use delete-then-write pattern for JSON updates

## Links & Resources

**OpenHome Documentation:**
- [Building Great Abilities](https://docs.openhome.com/Building_Great_OpenHome_Abilities) — Runtime model explained
- [How to Build an Ability](https://docs.openhome.com/how_to_build_an_ability) — CapabilityWorker reference
- [Dashboard](https://app.openhome.xyz/dashboard)
- [Discord Community](https://discord.com/channels/1197724389630824508)

**Python Libraries:**
- [zoneinfo](https://docs.python.org/3/library/zoneinfo.html) — Timezone handling
- [datetime](https://docs.python.org/3/library/datetime.html) — Date/time operations

## Support & Contribution

If you build something with background mode:
- 🎉 Share your implementation in Discord
- 💡 Contribute improvements to the template
- 🤝 Help others understand background limitations
- 📝 Document your use case

## Final Reminder

⚠️ **Background abilities are advanced — understand the limitations before building.**

**Key takeaways:**
- ✅ Backgrounds run continuously in infinite loops
- ✅ Great for active session monitoring (timers, reminders)
- ✅ Must use `session_tasks.sleep()`, never `asyncio.sleep()`
- ❌ **Not** truly background tasks
- ❌ **Cannot** fire when user isn't active
- ❌ **Never** call `resume_normal_flow()` (intentionally unreachable)

Use backgrounds for real-time monitoring during active sessions, not for long-term background tasks! ⏰🚀

---

