
# Agent Memory & Context Injection

The `MemorySnapshotCapabilityBackground` runs as a background daemon and continuously updates Agent context.

## Overview

- The background reads user-level persistent files and injects every `.md` file into the Agent prompt.
- This makes `.md` files the primary path for ambient context injection.
- The Profile UI exposes persistent memory files (`user_profile.md`, `user_summary.md`) as editable content.

## Background Cycle

The background runs sequentially every ~60-90 seconds:

1. `save_user_summary()` updates `user_summary.md`.
2. `save_user_profile()` updates `user_profile.md`.
3. `update_agent_prompt()` scans persistent storage (`temp=False`) and injects all `.md` files into the live Agent prompt.

Latency from file write to Agent behavior change is typically 60-90 seconds.

## Context Injection Rule

If an ability writes a persistent `.md` file, the Agent will see it on the next background cycle.

- `.md`: injected into Agent prompt
- `.json`, `.txt`, `.log`, `.csv`, `.yaml`, `.yml`: stored only, **not injected**

**Example:**
```python
# This content will appear in Agent's system prompt within 60-90 seconds
await self.capability_worker.write_file(
    "audio_emotion.md",
    "## Current Audio Emotion\nUser sounds stressed (detected at 3:24 PM)",
    False  # temp=False → persistent storage
)
```

---

## Required Write Pattern for Replaceable Context Files

`write_file()` appends by default. For context files that represent current state, always delete then write:

```python
async def write_context_file(self, filename: str, content: str):
    exists = await self.capability_worker.check_if_file_exists(filename, False)
    if exists:
        await self.capability_worker.delete_file(filename, False)
    await self.capability_worker.write_file(filename, content, False)
```

### When to Use This Pattern

Use delete-then-write for:
- `audio_emotion.md` — Current emotion state
- `upcoming_schedule.md` — Next few events
- `home_state.md` — Current smart home status
- Any file representing **current state** vs **historical log**

### When NOT to Use This Pattern

Don't delete for append-only logs:
- `activity_log.txt` — Historical activity entries
- `conversation_notes.md` — Cumulative conversation insights

---

## Reserved Files

Do not write these from custom abilities:

- `user_profile.md`
- `user_summary.md`

These are owned by the memory background.

## Naming and Size Guidance

### Namespace Your Files
```python
# ✅ GOOD — Clear, namespaced
"audio_emotion.md"
"smart_home_state.md"
"upcoming_schedule.md"

# ❌ BAD — Generic, collision risk
"context.md"
"state.md"
"data.md"
```

### Keep Files Concise
- **Target:** Under 200 words per `.md` file
- **Reason:** Large context bloats Agent prompt and slows responses
- **Best practice:** Write current state, not long history logs

### Example: Good vs Bad

**❌ BAD — Too verbose**
```markdown
## Audio Emotion History
At 3:24 PM, detected stress in user's voice with 87% confidence based on pitch analysis...
At 3:26 PM, detected calm state with 92% confidence...
At 3:28 PM, detected excitement with 78% confidence...
[continues for 50+ entries]
```

**✅ GOOD — Concise, current state**
```markdown
## Current Audio Emotion
**Stressed** (detected 2 minutes ago)
Consider offering relaxation techniques.
```

---

## Stale Context Cleanup

For ephemeral daemon context, clear stale `.md` state at daemon startup before first processing cycle:

```python
async def first_function(self):
    """Daemon startup: clear stale context from previous session."""
    # Remove old emotion state to prevent stale context injection
    exists = await self.capability_worker.check_if_file_exists("audio_emotion.md", False)
    if exists:
        await self.capability_worker.delete_file("audio_emotion.md", False)
    
    # Now start fresh monitoring
    while True:
        # ... your daemon logic
        await self.worker.session_tasks.sleep(10.0)
```

**Why this matters:** Prevents old context from being injected after reconnect, which can confuse the Agent with outdated state.

---

## Dual-Path Response Model

For abilities that need both ambient awareness AND urgent intervention:

### Ambient Path
Write `.md` files for watcher-based prompt injection (takes 60-90 seconds):

```python
# Update context that Agent will see passively
await self.write_context_file(
    "audio_emotion.md",
    "## Current Audio Emotion\n**Stressed** (detected just now)"
)
```

### Urgent Path
Call `send_interrupt_signal()` first, then `speak()` for **immediate intervention**:

```python
# Immediate response when urgent action needed
await self.capability_worker.send_interrupt_signal()
await self.capability_worker.speak("You seem stressed. Want a quick breather?")
```

### When to Use Each Path

| Scenario | Path | Example |
|----------|------|---------|
| Passive context ("user is in kitchen") | Ambient `.md` | Write `location.md`, Agent references it naturally in conversation |
| Urgent alert ("smoke detected!") | Interrupt + speak | `send_interrupt_signal()` then `speak("Smoke alarm!")` |
| Background state ("3 upcoming meetings") | Ambient `.md` | Write `schedule.md`, Agent can mention proactively if relevant |
| Critical warning ("medication overdue") | Interrupt + speak | Immediate spoken alert |

---

## Profile Tab: Editable Persistent Memory Files

In **Dashboard → Profile**, persistent memory files are now visible and editable:

- `user_profile.md`
- `user_summary.md`

### How It Works
1. These files are part of the **same persistent memory system** consumed by the watcher
2. Changes made in Profile are reflected in **Agent context** after the next watcher cycle (60-90 seconds)
3. Users can manually edit their profile/summary to correct or enhance Agent's understanding

### Use Case Example
User notices Agent has wrong information about their preferences:
1. Goes to Dashboard → Profile
2. Edits `user_profile.md` to correct info
3. Within 60-90 seconds, Agent's responses reflect the correction

---

## Complete Example: Audio Emotion Daemon

Here's a complete example showing all best practices:

```python
import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
from time import time

class AudioEmotionDaemon(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    watcher_mode: bool = False
    
    #{{register capability}}

    async def write_context_file(self, filename: str, content: str):
        """Safe write pattern for replaceable .md context files."""
        exists = await self.capability_worker.check_if_file_exists(filename, False)
        if exists:
            await self.capability_worker.delete_file(filename, False)
        await self.capability_worker.write_file(filename, content, False)

    async def first_function(self):
        self.worker.editor_logging_handler.info("Audio Emotion Daemon started")
        
        # CLEANUP: Clear stale context from previous session
        exists = await self.capability_worker.check_if_file_exists("audio_emotion.md", False)
        if exists:
            await self.capability_worker.delete_file("audio_emotion.md", False)
        
        while True:
            try:
                # Analyze audio emotion (your logic here)
                emotion = self.detect_emotion()  # Returns: "stressed", "calm", "excited", etc.
                confidence = 0.87
                
                # AMBIENT PATH: Write to .md for Agent context
                context = f"""## Current Audio Emotion
**{emotion.title()}** (confidence: {int(confidence * 100)}%)
Detected {int(time())} seconds ago.
"""
                await self.write_context_file("audio_emotion.md", context)
                
                # URGENT PATH: If stress detected, interrupt immediately
                if emotion == "stressed" and confidence > 0.85:
                    await self.capability_worker.send_interrupt_signal()
                    await self.capability_worker.speak(
                        "You seem stressed. Want to take a quick break?"
                    )
                
            except Exception as e:
                self.worker.editor_logging_handler.error(f"Emotion detection error: {e}")
            
            await self.worker.session_tasks.sleep(10.0)  # Check every 10 seconds

    def call(self, worker: AgentWorker, watcher_mode: bool):
        self.worker = worker
        self.watcher_mode = watcher_mode
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.first_function())
```

---

## Best Practices Summary

### ✅ Do's
- **Do** write `.md` files for ambient context injection
- **Do** use delete-then-write pattern for state files
- **Do** namespace filenames (`audio_emotion.md`, not `context.md`)
- **Do** keep `.md` files under 200 words
- **Do** clear stale `.md` files at daemon startup
- **Do** use dual-path: `.md` for ambient, `send_interrupt_signal()` for urgent
- **Do** write current state, not full history

### ❌ Don'ts
- **Don't** write `user_profile.md` or `user_summary.md` (reserved)
- **Don't** append to state files (use delete-then-write)
- **Don't** write verbose historical logs to `.md` (use `.txt` instead)
- **Don't** expect instant context updates (allow 60-90 seconds)
- **Don't** use generic filenames that might collide
- **Don't** forget to clean up stale context on daemon restart

---

## Troubleshooting

### Agent doesn't reflect my .md file changes
**Possible causes:**
1. File not in persistent storage (`temp=True` instead of `temp=False`)
2. Watcher cycle hasn't run yet (wait 60-90 seconds)
3. File is not `.md` extension (only `.md` files are injected)

**Solutions:**
- Verify: `await write_file(filename, content, False)` (last param is `False`)
- Wait at least 90 seconds before testing
- Ensure filename ends with `.md`

### Context file keeps growing indefinitely
**Cause:** Using append behavior instead of delete-then-write

**Solution:** Use the delete-then-write pattern:
```python
await self.capability_worker.delete_file("state.md", False)
await self.capability_worker.write_file("state.md", content, False)
```

### Old context appears after reconnect
**Cause:** Stale `.md` file from previous session

**Solution:** Clear at daemon startup:
```python
async def first_function(self):
    # Clear stale context
    if await self.capability_worker.check_if_file_exists("my_state.md", False):
        await self.capability_worker.delete_file("my_state.md", False)
    
    # Now start fresh
    while True:
        ...
```

---

## Related Documentation

- [Building Great OpenHome Abilities](https://docs.openhome.com/Building_Great_OpenHome_Abilities) — Runtime model and best practices
- [SDK Reference](https://docs.openhome.com/OpenHome_SDK_Reference) — Complete CapabilityWorker API
- [File Storage Guide](https://docs.openhome.com/OpenHome_SDK_Reference#8-file-storage-persistent-+-temporary) — Persistent vs temp storage

---

## Questions?

Ask in [Discord #dev-help](https://discord.gg/openhome) or [open a discussion](https://github.com/openhome-dev/abilities/discussions).

---
