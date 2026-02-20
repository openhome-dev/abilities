# 🍅 Pomodoro Focus Timer

A professional, voice-driven productivity tool for OpenHome that manages structured focus sessions using the Pomodoro Technique with session tracking, smart breaks, and productivity analytics.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Complete User Guide](#complete-user-guide)
- [Mid-Session Commands](#mid-session-commands)
- [Data Persistence](#data-persistence)
- [Voice Flow Examples](#voice-flow-examples)
- [Technical Architecture](#technical-architecture)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

---

## 🎯 Overview

**Pomodoro Focus Timer** is a voice-first productivity ability that helps you maintain deep focus through structured work sessions. Unlike generic timers that just count down, this ability provides:

- **Intelligent Cycle Management**: Automatically handles focus → short break → focus → long break sequences
- **Session Tracking**: Logs every completed session with timestamps and duration
- **Productivity Analytics**: Daily, weekly, and streak tracking with natural language summaries
- **Mid-Session Commands**: Check time, extend sessions, or skip breaks without losing your flow
- **Persistent Preferences**: Your settings and history save across all sessions

---

## ✨ Features

### 🎯 Core Pomodoro Functionality
- ✅ Classic Pomodoro Cycle: 25 min focus → 5 min break → repeat 4 times → 15 min long break
- ✅ Fully Customizable: Change focus duration, break length, and number of cycles
- ✅ Quick Start Mode: Say "30 minutes" to immediately start a 30-minute focus session
- ✅ Silent During Focus: Stays quiet while you work (optional halfway check-in)
- ✅ Smart Alerts: Clear, encouraging notifications when sessions and breaks end

### 📊 Session Tracking & Stats
- ✅ Automatic Logging: Every completed session saved immediately
- ✅ Partial Session Tracking: Logs incomplete sessions if you stop early
- ✅ 90-Day History: Automatically maintains last 90 days of session data
- ✅ Natural Language Stats: "My stats" for daily/weekly summaries
- ✅ Streak Tracking: Monitor productivity patterns over time

### 🎙️ Mid-Session Commands
- ✅ "How much time left?" - Get remaining time in minutes and seconds
- ✅ "Add 5 minutes" - Extend current session or break
- ✅ "Skip break" - End break early and jump to next focus session
- ✅ "Stop" - Cancel with confirmation (logs partial session)

---

## 🚀 Installation

1. **Download Files**: Place all files in your OpenHome abilities directory
2. **Trigger Words**: Say "Pomodoro" to activate
3. **First Use**: Set preferences and start your first focus session

No API keys required - uses built-in OpenHome SDK only.

---
Tigger Word:
Focus Timer. 

## 📖 Complete User Guide

### Initial Activation

```
User: "Focus Timer"
App: "Pomodoro."
App: "Say my stats or start a focus session."
```

### Option 1: Check Stats
```
User: "My stats"
App: "You completed 4 focus sessions today — 100 minutes of focused work..."
```

### Option 2: Start Focus Session

**Step 1: Choose Cycles**
```
App: "How many cycles? Default is 4. Say yes to keep it or no to customize."
User: "Yes" → 4 cycles
User: "No" → "How many?" → "2" → 2 cycles
```

**Step 2: Configure Session**
```
App: "Default Pomodoro or customize? Say 'default' for 25/5/15..."

A) Default: "Default" → 25 min focus, 5 min break, 15 min long break
B) Customize: "Customize" → Set each duration individually
C) Quick Start: "30 minutes" → Immediate 30-min session
```

---

## 🎮 Mid-Session Commands

### Check Time Remaining
```
User: "How much time left?"
App: "13 minutes and 15 seconds remaining."
```
Works during focus sessions AND breaks.

### Add Time
```
User: "Add 10 minutes"
App: "Adding 10 minutes."
```
Extends current session or break. Works with: "add 5", "extend by 10", "add ten minutes"

### Skip Break
```
User: "Skip"
App: "Short break skipped."
[Immediately starts next focus session]
```
Only works during breaks.

### Stop/Cancel
```
User: "Stop"
App: "Do you want to cancel the session? Say yes to confirm."
User: "Yes"
App: "Session cancelled."
```
Always confirms. Logs partial session if confirmed.

### Command Summary Table

| Command | Focus | Break | Response |
|---------|-------|-------|----------|
| "How much time left?" | ✅ | ✅ | Shows remaining time |
| "Add 5 minutes" | ✅ | ✅ | Extends timer |
| "Skip" | ❌ | ✅ | Ends break, starts next session |
| "Stop" | ✅ | ✅ | Confirms then exits |

---

## 💾 Data Persistence

### pomodoro_prefs.json - User Preferences
```json
{
  "focus_minutes": 25,
  "short_break_minutes": 5,
  "long_break_minutes": 15,
  "sessions_per_cycle": 4,
  "halfway_checkin": true
}
```

### pomodoro_history.json - Session History
```json
[
  {
    "id": "sess_1708185600",
    "date": "2026-02-17",
    "started_at": "2026-02-17T09:00:00",
    "ended_at": "2026-02-17T09:25:00",
    "duration_minutes": 25,
    "completed": true,
    "session_number": 1
  }
]
```

- Logs sessions immediately when complete
- Automatically trims to last 90 days
- Tracks partial sessions if stopped early

---

## 🎬 Voice Flow Examples

### Quick 30-Minute Session
```
User: "Focus Timer"
App: "Pomodoro."
User: "Start"
App: "How many cycles?..."
User: "Yes"
App: "Default or customize?..."
User: "30 minutes"
App: "Starting a 30 minute focus session..."
[30 min silence]
App: "Nice work! Session 1 complete..."
User: "Done"
App: "Goodbye."
App: "Great session! 1 focus session, 30 minutes total..."
```

### Full Classic Pomodoro (4 Cycles)
```
[25 min focus] → [5 min break] → "Start"
[25 min focus] → [5 min break] → "Start"
[25 min focus] → [5 min break] → "Start"
[25 min focus] → [15 min LONG break]
App: "You completed a full cycle! Want to keep going?"
User: "No"
App: "Great session! 4 focus sessions, 100 minutes total..."
```

### Using Mid-Session Commands
```
[10 min into focus session]
User: "How much time left?"
App: "15 minutes remaining."

User: "Add 10 minutes"
App: "Adding 10 minutes."

[Session ends, break starts]
[2 min into break]
User: "Skip"
App: "Short break skipped."
[Next focus session starts immediately]
```

---

## 🏗️ Technical Architecture

### Stay-Alive Pattern
- Does NOT call `resume_normal_flow()` until user is done
- Timer alerts fire even after 25+ minutes
- Sessions logged immediately

### Mid-Session Listening
- Checks for commands every 5 seconds using `asyncio.wait_for()`
- User can speak anytime during session
- 0-5 second response delay is normal

### LLM Usage
- Parsing spoken numbers: "add five" → 5
- Generating stats summaries
- NOT used for timers (pure asyncio.sleep)

---

## 🐛 Troubleshooting

### Timer doesn't start
- Check OpenHome logs
- Restart device
- Re-trigger ability

### Commands not working
- Wait 0-5 seconds (commands checked every 5s)
- Speak clearly
- Commands ARE working, just slight delay

### Halfway check-in annoying
Edit `pomodoro_prefs.json`:
```json
{"halfway_checkin": false}
```

### Stats not showing
- Complete at least one session first
- Check if `pomodoro_history.json` exists
- Verify JSON is valid

---

## 👨‍💻 Development

### File Structure
```
pomodoro-focus-timer/
├── main.py                    # Core ability (650+ lines)
├── __init__.py                # Package init
├── README.md                  # This file
├── pomodoro_prefs.json       # Auto-generated
└── pomodoro_history.json     # Auto-generated
```

### Key Functions
- `run_main()` - Entry point
- `run_focus_cycle()` - Full Pomodoro cycle
- `run_focus_session()` - One focus session
- `run_break()` - One break
- `_handle_mid_session_command()` - Process commands
- `show_stats()` - Display analytics

---

## 🆚 Comparison to Generic Timer

| Feature | Voice Timer | Pomodoro Timer |
|---------|-------------|----------------|
| Purpose | Cooking, laundry | Deep work, studying |
| Concurrent | ✅ Multiple | ❌ One at a time |
| Persistence | ❌ None | ✅ History + prefs |
| Cycles | ❌ None | ✅ Auto breaks |
| Stats | ❌ None | ✅ Daily/weekly |
| Coaching | ❌ Fire & forget | ✅ Encouragement |

---

## 🎯 Quick Reference

**Trigger**: "Pomodoro"
**Mid-Session**: "How much time left?", "Add 5 minutes", "Skip", "Stop"
**Exit**: "Done", "Quit", "Goodbye"
**Defaults**: 25 min focus, 5 min short break, 15 min long break, 4 cycles

---

**Built with ❤️ for focused productivity**

Version 1.0.0 | February 2026
