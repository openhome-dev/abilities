# File Read/Write Template — OpenHome Ability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)

## What This Is
**This is a template ability** that demonstrates OpenHome's persistent file storage system. Learn how to save data that persists across sessions — the foundation for building abilities that "remember" information.

## Why This Matters
Every OpenHome Agent already has an LLM out of the box that can handle conversational tasks. **The file storage API exists because the LLM can't persist data on its own.** This template shows you how to build abilities that:

- Remember user preferences across sessions
- Track activity over time (journals, habit trackers, logs)
- Store structured data (JSON configs, saved lists)
- Detect first-time vs returning users

**Key insight:** Without file storage, every session is a blank slate. With it, your ability can feel like it "knows" the user.

## No Setup Required
This template uses OpenHome's built-in file storage — no external services, API keys, or configuration needed.

## Understanding the Runtime Model

### On-Demand, Stateless by Design
Before you start building, understand how abilities actually work:

**Your ability only exists while it's running.** When the user triggers your ability:
1. Your `call()` method is invoked
2. Your ability takes over the conversation
3. All instance variables (`self.whatever`) live in memory
4. When you call `resume_normal_flow()`, the instance is destroyed
5. **Everything in memory is gone**

```python
def call(self, worker):
    self.my_data = {}  # ← exists now
    self.worker.session_tasks.create(self.perform_action())

async def perform_action(self):
    self.my_data["name"] = "Chris"  # ← lives in memory
    await self.capability_worker.speak("Got it!")
    self.capability_worker.resume_normal_flow()
    # ← self.my_data is gone. Instance is gone.

## Core File Operations

The template demonstrates all 4 essential file operations:

### 1. Check If File Exists
```python
exists = await self.capability_worker.check_if_file_exists("temp_data.txt", in_ability_directory=False)
```

**Parameters:**
- `filename` (str): Name of the file to check
- `is_public` (bool): `False` for private files (user-specific), `True` for shared files

**Returns:** `bool` — `True` if file exists, `False` otherwise

**Use cases:**
- Determine whether to create or append to file
- Check if user has saved data before
- Verify file before attempting to read

---

### 2. Write to File
```python
await self.capability_worker.write_file("temp_data.txt", "content here", in_ability_directory=False)
```

**Parameters:**
- `filename` (str): Name of the file
- `content` (str): Text content to write
- `is_public` (bool): `False` for private, `True` for shared

**Important Notes:**
- **Overwrites** existing content by default
- To append, read first, then write combined content (see template example)
- Content is a string — use `json.dumps()` for complex data

**Template's append pattern:**
```python
if await self.capability_worker.check_if_file_exists("temp_data.txt", in_ability_directory=False):
    # File exists — append new line
    await self.capability_worker.write_file(
        "temp_data.txt", 
        "\n%s: %s" % (time(), user_response),  # Newline prepended
        False
    )
else:
    # File doesn't exist — create new
    await self.capability_worker.write_file(
        "temp_data.txt",
        "%s: %s" % (time(), user_response),  # No newline
        False
    )
```

---

### 3. Read from File
```python
file_data = await self.capability_worker.read_file("temp_data.txt", in_ability_directory=False)
```

**Parameters:**
- `filename` (str): Name of the file to read
- `is_public` (bool): `False` for private, `True` for shared

**Returns:** `str` — Entire file content as a string

**Important Notes:**
- Returns entire file content at once
- Parse the string to extract specific data
- Returns empty string if file doesn't exist (no error)

**Template's parsing example:**
```python
file_data = await self.capability_worker.read_file("temp_data.txt", in_ability_directory=False)
# File contains lines like: "1234567890.123: Some text here"

# Extract last line
last_line = file_data.split("\n")[-1]

# Extract text after timestamp
last_written_text = last_line.split(":")[1]
```

---

### 4. Delete File
```python
await self.capability_worker.delete_file("temp_data.txt", in_ability_directory=False)
```

**Parameters:**
- `filename` (str): Name of the file to delete
- `is_public` (bool): `False` for private, `True` for shared

**Returns:** None

**Important Notes:**
- **Permanent deletion** — no recovery
- No error if file doesn't exist
- Use with confirmation prompts for user data

**Example with confirmation:**
```python
confirmed = await self.capability_worker.run_confirmation_loop(
    "Delete all your notes? This can't be undone."
)
if confirmed:
    await self.capability_worker.delete_file("notes.txt", in_ability_directory=False)
    await self.capability_worker.speak("All notes deleted.")
```

## Template Code Walkthrough

### Key Components Explained

**1. Initialize Workers:**
```python
def call(self, worker: AgentWorker):
    self.worker = worker
    self.capability_worker = CapabilityWorker(self.worker)
    self.worker.session_tasks.create(self.perform_action())
```
- Sets up the ability infrastructure
- Creates async task for main logic

**2. Get Voice Input:**
```python
user_response = await self.capability_worker.wait_for_complete_transcription()
```
- Waits for full user utterance
- Returns complete transcribed text

**3. Check File Exists:**
```python
if await self.capability_worker.check_if_file_exists("temp_data.txt", in_ability_directory=False):
    # File exists — append
else:
    # File doesn't exist — create
```
- Determines whether to create or append
- `False` = private file (user-specific)

**4. Write with Timestamp:**
```python
await self.capability_worker.write_file(
    "temp_data.txt",
    "\n%s: %s" % (time(), user_response),
    False
)
```
- Appends newline + timestamp + user input
- `time()` provides Unix timestamp

**5. Read and Parse:**
```python
file_data = await self.capability_worker.read_file("temp_data.txt", in_ability_directory=False)
last_written_line = file_data.split("\n")[-1].split(":")[1]
```
- Reads entire file
- Splits by newlines to get last entry
- Splits by colon to extract text after timestamp

**6. Speak Result:**
```python
await self.capability_worker.speak("Last Written Line: %s" % last_written_line)
```
- Confirms what was written

**7. Resume Normal Flow:**
```python
self.capability_worker.resume_normal_flow()
```
- Returns control to main assistant
- **Critical:** Always call this before exiting

## Private vs Public Files

### Private Files (`is_public=False`)
- **Scope:** User-specific, isolated per user
- **Use for:** Personal notes, user preferences, private data
- **Example:** Todo lists, journal entries, saved settings

```python
await self.capability_worker.write_file("my_notes.txt", "Private note", in_ability_directory=False)
```

### Public Files (`is_public=True`)
- **Scope:** Shared across all users of this ability
- **Use for:** Shared resources, leaderboards, collaborative data
- **Example:** Community wish lists, group polls, shared calendars

```python
await self.capability_worker.write_file("community_board.txt", "Public message", in_ability_directory=True)
```

**Security Note:** Public files are readable/writable by all users. Don't store sensitive data!

## Best Practices

### 1. Use JSON for Structured Data
```python
import json

# Good: Structured, easy to query
data = {
    "tasks": [
        {"id": 1, "text": "Buy milk", "done": False},
        {"id": 2, "text": "Call dentist", "done": True}
    ]
}
await self.capability_worker.write_file(
    "tasks.json",
    json.dumps(data),
    in_ability_directory=False
)

# Avoid: Plain text requires manual parsing
await self.capability_worker.write_file("tasks.txt", "Buy milk\nCall dentist", in_ability_directory=False)
```

### 2. Always Use Try-Except for JSON Parsing
```python
import json

try:
    data = await self.capability_worker.read_file("settings.json", in_ability_directory=False)
    settings = json.loads(data)
except json.JSONDecodeError:
    # Corrupted file — reset to defaults
    settings = {"default": "value"}
    await self.capability_worker.write_file(
        "settings.json",
        json.dumps(settings),
        False
    )
```

### 3. Add Confirmation for Deletions
```python
if "delete all" in user_response.lower():
    confirmed = await self.capability_worker.run_confirmation_loop(
        "Delete all your notes? This can't be undone. Say yes to confirm."
    )
    if confirmed:
        await self.capability_worker.delete_file("notes.txt", in_ability_directory=False)
        await self.capability_worker.speak("All notes deleted.")
    else:
        await self.capability_worker.speak("Cancelled. Your notes are safe.")
```

### 4. Use Timestamps for Tracking
```python
from time import time
from datetime import datetime

# Unix timestamp (seconds since epoch)
timestamp = time()  # e.g., 1709650800.123

# Human-readable timestamp
readable = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # "2024-03-15 14:30:00"

# Use in files
entry = f"{readable}: {user_input}"
```

### 5. Limit File Size
```python
# Read existing data
data = await self.capability_worker.read_file("log.txt", in_ability_directory=False)
lines = data.split("\n")

# Keep only last 100 entries
if len(lines) > 100:
    lines = lines[-100:]

# Write back trimmed data
await self.capability_worker.write_file(
    "log.txt",
    "\n".join(lines),
    in_ability_directory=False
)
```

### 6. Namespace Your Files
```python
# Good: Unique names prevent conflicts with other abilities
await self.capability_worker.write_file("myability_notes.txt", data, in_ability_directory=False)
await self.capability_worker.write_file("myability_settings.json", settings, in_ability_directory=False)

# Avoid: Generic names might conflict
await self.capability_worker.write_file("notes.txt", data, in_ability_directory=False)  # Risk of collision
```

## Common Patterns

### Pattern 1: Append to Log
```python
async def append_log(self, entry: str):
    log_file = "activity_log.txt"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp}: {entry}"
    
    if await self.capability_worker.check_if_file_exists(log_file, in_ability_directory=False):
        # Read, append, write
        existing = await self.capability_worker.read_file(log_file, in_ability_directory=False)
        new_content = existing + f"\n{line}"
    else:
        # First entry
        new_content = line
    
    await self.capability_worker.write_file(log_file, new_content, in_ability_directory=False)
```

### Pattern 2: Read Last N Lines
```python
async def get_recent_entries(self, filename: str, count: int = 5):
    if not await self.capability_worker.check_if_file_exists(filename, in_ability_directory=False):
        return []
    
    data = await self.capability_worker.read_file(filename, in_ability_directory=False)
    lines = [line for line in data.split("\n") if line.strip()]
    return lines[-count:]  # Last N lines
```

### Pattern 3: Update JSON Field
```python
async def update_settings(self, key: str, value):
    settings_file = "settings.json"
    
    # Load existing settings
    if await self.capability_worker.check_if_file_exists(settings_file, in_ability_directory=False):
        data = await self.capability_worker.read_file(settings_file, in_ability_directory=False)
        settings = json.loads(data)
    else:
        settings = {}
    
    # Update field
    settings[key] = value
    
    # Save back
    await self.capability_worker.write_file(
        settings_file,
        json.dumps(settings, indent=2),
        False
    )
```

### Pattern 4: Search in File
```python
async def search_notes(self, query: str):
    notes_file = "notes.txt"
    
    if not await self.capability_worker.check_if_file_exists(notes_file, in_ability_directory=False):
        return []
    
    data = await self.capability_worker.read_file(notes_file, in_ability_directory=False)
    lines = data.split("\n")
    
    # Search for query (case-insensitive)
    matches = [line for line in lines if query.lower() in line.lower()]
    return matches
```

## Troubleshooting

### File Not Persisting Across Sessions
**Problem:** Data disappears after ability restarts

**Cause:** Using `is_public=True` when you meant `is_public=False`, or vice versa

**Solution:** Verify the correct `is_public` parameter:
```python
# Private file (user-specific, persists)
await self.capability_worker.write_file("notes.txt", data, in_ability_directory=False)

# Public file (shared, persists)
await self.capability_worker.write_file("shared.txt", data, in_ability_directory=True)
```

### JSON Parsing Errors
**Problem:** `json.JSONDecodeError` when reading file

**Cause:** File content is not valid JSON

**Solution:** Always wrap JSON operations in try-except:
```python
try:
    data = await self.capability_worker.read_file("settings.json", in_ability_directory=False)
    settings = json.loads(data)
except (json.JSONDecodeError, Exception):
    # Reset to default on error
    settings = {"default": "settings"}
```

### Appending Creates Duplicates
**Problem:** Multiple copies of same data

**Cause:** Not checking if entry already exists before appending

**Solution:** Check before appending:
```python
existing = await self.capability_worker.read_file("list.txt", in_ability_directory=False)
if new_item not in existing:
    await self.capability_worker.write_file("list.txt", existing + f"\n{new_item}", in_ability_directory=False)
```

### File Size Growing Too Large
**Problem:** File becomes too big, slows down reads

**Solution:** Implement log rotation:
```python
lines = data.split("\n")
if len(lines) > MAX_LINES:
    # Archive old data (optional)
    archive = "\n".join(lines[:-MAX_LINES])
    await self.capability_worker.write_file("archive.txt", archive, in_ability_directory=False)
    
    # Keep only recent
    recent = "\n".join(lines[-MAX_LINES:])
    await self.capability_worker.write_file("log.txt", recent, in_ability_directory=False)
```

## Quick Start Checklist

### Understanding the Template
- [ ] Read through the template code
- [ ] Understand the 4 file operations (check, write, read, delete)
- [ ] Test the template as-is to see it work
- [ ] Check the log file it creates

### Building Your Ability
- [ ] Define what data you need to store
- [ ] Choose private vs public files
- [ ] Design your file structure (plain text vs JSON)
- [ ] Implement your custom logic
- [ ] Add error handling (try-except)
- [ ] Test with various inputs
- [ ] Add confirmation for destructive operations

## Final Reminder

⚠️ **This template demonstrates file operations, not a complete ability.**

Use it to learn how to:
- ✅ Store user data persistently
- ✅ Read and parse saved data
- ✅ Update existing files
- ✅ Delete data when requested

Then build something useful with these tools! 🚀

---
