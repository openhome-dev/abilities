# Designing OpenHome Abilities
### A Manifesto for Voice-First Ambient Intelligence

> *Build for the room. Build for the moment. Build for the silence between the words.*

---

## Table of Contents

1. [Philosophy](#1-philosophy)
2. [Design Frameworks](#2-design-frameworks)
3. [Voice-First Design Rules](#3-voice-first-design-rules)
4. [Sound Design — Audio as Interface](#4-sound-design--audio-as-interface)
5. [Trigger Word Design](#5-trigger-word-design)
6. [The Ability Lifecycle](#6-the-ability-lifecycle)
7. [Ability Ideas by Location](#7-ability-ideas-by-location)
8. [Ability Ideas by User](#8-ability-ideas-by-user)
9. [Ability Ideas by Use Case](#9-ability-ideas-by-use-case)
10. [3rd-Party API Integration](#10-3rd-party-api-integration)
11. [The OpenClaw Bridge](#11-the-openhome--openclaw-bridge)
12. [Combining Frameworks](#12-combining-frameworks)
13. [The Sci-Fi Frontier](#13-the-sci-fi-frontier)
14. [Quality Checklist](#14-quality-checklist)
15. [The Brainstorm Catalog — 170+ Ideas](#15-the-brainstorm-catalog--170-ideas)

---

## 1. Philosophy

### The Core Premise

You are not building an app. You are building **a presence in a room.**

A smart speaker is a microphone, a speaker, and a brain that never sleeps. The best ability is the one the user forgets is running — until it does something so well-timed they think: *"How did it know?"*

> **It knew because it was there. Listening. Learning. Waiting.**

### The Three Modes of Operation

| Mode | What It Does | Key Principle |
|---|---|---|
| **Listening** | Captures ambient audio, transcribes speech, identifies speakers, extracts meaning | The user may not even be talking to the device |
| **Speaking** | Interjects, responds, narrates, coaches, entertains | Voice is expensive — every word is a second the user can't skip. Silence is often better. |
| **Logging** | Writes to persistent backends, companion apps, dashboards — silently | Accumulates intelligence over hours, days, weeks. The most powerful layer. |

### When Something Should Be an Ability

If the LLM can handle it with a Personality prompt alone, it doesn't need to be an Ability. Abilities exist for things the LLM **can't** do on its own:

- Call an external API
- Play or generate audio
- Control a physical device
- Persist data across sessions
- Run multi-step workflows with branching logic
- Access real-time data (weather, scores, stocks, calendars)

> **Ask yourself:** *"Does this require reaching outside the LLM?"* If yes, it's an Ability. If the LLM can answer from its training data and a good prompt, it's just a Personality feature.

---

## 2. Design Frameworks

### The Three Ability Archetypes

| Archetype | Behavior | Examples |
|---|---|---|
| **The Responder** | Mostly silent. User initiates. Speaker answers. Done. Get in, get out. | Weather, timer, WiFi password, quick lookup |
| **The Companion** | Active participant in ongoing back-and-forth. Has personality, memory, opinions. | Debate coach, recipe walkthrough, brainstorm partner, bedtime story |
| **The Observer** | Mostly or entirely silent. Listens, transcribes, analyzes, logs. Surfaces insights later. | Life logger, meeting transcriber, sleep tracker, dream decoder |

> **The Observer archetype is the most underused and the most powerful. The less it speaks, the better. Silence is the feature.**

### Ten Design Frameworks

**1. The Invisible Worker**
Does labor you'd never bother doing yourself — not because it's hard, but because it's tedious. Checks your flight every 30 minutes. Compares your electric bill. Notices you haven't called your mom in two weeks. The user never says "do this." It just gets done.
> *Ability type: **Background Daemon***

**2. The Information Funnel**
You have 47 apps, 12 subscriptions, 6 dashboards. You check 3 of them. The speaker sits on top of ALL via APIs and compresses everything into one spoken sentence at the right moment. Not another app — the app that replaces checking all the other apps.
> *Ability type: **Brain Skill** or **Skill***

**3. Surprise Artifact Generation**
The speaker never tells you it's building something. It listens, logs, processes, and one day a document appears. Design by asking: *"What would blow someone's mind if it just appeared after 30, 60, 90 days?"* Work backward from the surprise.
> *Ability type: **Background Daemon***

**4. The Emotional Radar**
Voice carries more data than text — speed, pitch, volume, pauses, word choice. If the user sounds exhausted, shorten every response. If excited, match energy. Same ability, different behavior based on how the user **sounds**, not just what they **say**.
> *Ability type: **Skill** or **Background Daemon***

**5. The Daily Ritual Anchor**
Attach abilities to moments users already have (morning coffee, bedtime wind-down), not new moments you're asking them to create. *"Every morning when I say good morning"* is a ritual. Force them to remember and it dies in a week.
> *Ability type: **Skill** or **Brain Skill***

**6. The Compound Intelligence Loop**
Day 1 the speaker is dumb. Day 30 it's eerily good. Day 90 it's indispensable. Value is a function of time, not a single interaction. This is the moat — no new app can compete with 90 days of context.
> *Ability type: **Background Daemon***

**7. The Proxy Agent**
The speaker doesn't just inform — it acts on your behalf. Books the Uber. Reorders coffee. Sends the message. Move past "tells me things" into "does things for me." Information without action is just noise.
> *Ability type: **Brain Skill** via OpenClaw Bridge*

**8. The Social Multiplier**
A speaker in a room with multiple people is fundamentally different from a phone in one hand. Design abilities that are better with 2+ people. Games, decision makers, debate moderators, trivia nights. The speaker becomes the social infrastructure of the room.
> *Ability type: **Skill***

**9. The Context Mesh**
A calendar event alone is data. A calendar event + weather + traffic + the fact you mentioned dreading this meeting = intelligence. The most powerful abilities weave multiple data sources into one contextual insight.
> *Ability type: **Brain Skill***

**10. The Graceful Silence Principle**
For every ability, define the silence rules **first**. When does it intentionally say nothing? When does it log instead of speak? The best abilities speak 20% of the time they could. The other 80% they're listening, logging, processing, and waiting.
> *Applies to all ability types — especially **Background Daemon***

---

## 3. Voice-First Design Rules

### Keep It Short
- 1–2 sentences per `speak()` call
- Give the headline first, offer to go deeper
- Progressive disclosure: *"You have 3 meetings. Next one's at 2 with Sarah. Want the full list?"*

> If you wouldn't say it to someone standing next to you, it doesn't belong in a `speak()` call.

### Fill the Silence
- If an API call takes more than 1 second, say something **first**
- *"One sec, pulling that up." / "Hang on, checking." / "Let me look into that."*
- Dead silence during processing feels like the conversation froze

> Speak filler **before** the slow call, not after. The user hears words while the API loads.

### Confirm Before Acting
- Destructive or high-stakes actions need a voice confirmation
- *"Cancel Team Standup? Say yes to confirm."*
- Low-stakes lookups can skip confirmation — just do it

### Expect Messy Input
- Transcription isn't perfect. Users say "um", trail off, repeat themselves
- Use the LLM to extract clean data from noisy transcription
- If you can't parse it, ask again: *"I didn't catch that — could you say it again?"*

> Never fail silently. A confused response is better than no response.

### Handle Exits
- If your ability loops, give users a way out
- Check for exit words: `"done"`, `"stop"`, `"bye"`, `"nothing else"`, `"I'm good"`
- One idle cycle = keep going. Two = offer to leave.

> `resume_normal_flow()` on **every** exit path — happy path, breaks, except blocks, timeouts.

### Spell It Out
- TTS will mangle emails, URLs, and number formats
- Say "at" not "@", "dot" not "."
- Read phone numbers digit by digit. Say "10 AM" not "10:00"

### Silence Is a Feature
- Not every moment needs a response
- The user said something interesting? Log it. Don't acknowledge it.
- The user paused for 5 seconds? That's not a prompt for you to fill.
- Voice is serial — never list more than 3 items without asking.

---

## 4. Sound Design — Audio as Interface

Voice abilities aren't just speech — they're audio experiences. A well-placed sound effect communicates faster than words. The difference between a toy and a product is sound design.

### Sound Effect Types

| Type | When to Use | Example |
|---|---|---|
| **Confirmation Tones** | Action completes successfully. Low-stakes. | "Lights off" → [soft click] — no words needed |
| **Transition Sounds** | Switching modes or states. Under 1 second. | Entering ability → [whoosh] signals mode change |
| **Intro Music/Themes** | Companion and game abilities. 2–4 sec. | Trivia → [game show sting] = instant mode recognition |
| **Feedback Beeps** | Correct/wrong, milestones, timers | Correct → [bright pip], wrong → [low tone] |
| **Ambient Audio** | Atmosphere under speech. -20dB below voice. | Focus mode → [lo-fi beats], sleep → [rain sounds] |
| **Alert/Interrupt** | Background Daemon abilities breaking through | Timer done → [escalating soft alarm] |

### Sound Design Principles

**Less Is More** — A single well-chosen tone beats a symphony of effects. If every action has a sound, nothing stands out. Sound inflation kills meaning.

**Consistency Builds Trust** — Same action = same sound, every time. Users learn the audio language: *"I heard the ding, so I know it worked."*

**Time of Day Awareness:**
- Morning: bright, warm, energizing
- Evening: soft, muted, calm
- Late night: minimal, whisper-quiet, or absent

> The same ability should sound different at 7 AM vs 11 PM. Time-of-day gating on alert sounds is mandatory.

**Sound as Progressive Disclosure:**
- First interaction: sound + full speech confirmation
- After 5 uses: sound + abbreviated speech
- After 20 uses: sound only — user knows what it means

> Let sound gradually replace words as the user learns. This is how you train subconscious familiarity.

### Sound Anti-Patterns

- Sound effect on every `speak()` call — becomes noise
- Long intro music that delays the first useful word
- Loud alert sounds at 2 AM — time-of-day gating is mandatory
- Sounds that mimic real-world alarms (fire alarm, car horn) — causes panic
- Musical loops that don't fade when speech starts — mixing matters
- Different sounds for the same action — breaks learned association

---

## 5. Trigger Word Design

### Think in Speech, Not Text
Users won't say *"invoke calendar management system."* They'll say *"what's on my calendar"*, *"do I have a 3pm"*, *"am I free Tuesday."*

> Test triggers by saying them out loud across a room. If it feels unnatural to say, nobody will say it.

### Balance Coverage vs. False Positives

| Trigger Risk | Examples | Strategy |
|---|---|---|
| Safe single words | "calendar", "reschedule", "weather" | Unambiguous — use freely |
| Dangerous single words | "book", "free", "cancel" | Multiple meanings — use phrase-level triggers |
| Phrase-level triggers | "book a time", "am I free", "free on" | Much safer than bare words |
| Full sentence triggers | "what's my day look like today" | Catches indirect queries without keywords |

### Trigger Word Checklist
- Include plural forms: `"meeting"` AND `"meetings"`
- Include regional variants: `"what's in my diary"` (UK) vs `"what's on my calendar"` (US)
- Include indirect phrasings: `"what's my day look like"` has no calendar keyword
- Include natural full sentences: `"what am I doing today"`

### Reading Trigger Context
When your ability fires, the user was mid-conversation. Read that history to classify intent:
- *"What's on my calendar today?"* → give today's schedule
- *"Create a meeting with Sarah at 3"* → start creating immediately, no menus

> Pattern: read trigger from history → classify intent with LLM → route to handler. Don't treat every activation the same.

---

## 6. The Ability Lifecycle

### Ability Categories

When creating an ability in the OpenHome dashboard, you select a **Category** that tells the platform how the ability should behave:

| Category | Behavior |
|---|---|
| **Skill** | Standard ability where the user directly interacts with it in normal conversation. Triggered by hotwords, runs a flow, exits. This is the original ability pattern. |
| **Brain Skill** | The Personality's brain decides to trigger it in the background. Used when the brain can't fully respond to a user's question and needs more information, or when the brain needs to delegate an action. Examples: fetching weather for a location, running smart home actions. |
| **Background Daemon** | Background thread that starts automatically when the call begins and runs continuously for the entire session. Used for monitoring, polling, alarms, note-taking, and ambient intelligence. Works even when the Personality is in sleep mode. |
| **Local** | High-level Python packages written to run directly on Raspberry Pi hardware, allowing many restricted modules since they execute on the device itself. *Under development — not yet released.* |

> **Note:** Brain Skills templates are still being finalized. Brain Skills are triggered automatically by the Personality's brain when it needs to fill a knowledge gap or delegate an action the user requested.

### Ability File Structure

Regardless of which category you select in the dashboard, every ability is built from one or two files:

| Type | Files | Description |
|---|---|---|
| **Standard Interactive** | `main.py` only | User triggers with hotwords, runs, exits with `resume_normal_flow()`. The original pattern. |
| **Standalone Background Daemon** | `background.py` only | Starts automatically on session start. Runs in background for monitoring, logging, note-taking. Works even when Personality is in sleep mode. |
| **Interactive Combined** | `main.py` + `background.py` | Interactive handles user requests. Background daemon runs alongside. They coordinate through shared file storage. |

**Example — Interactive Combined (Alarm Ability):**
```
AlarmAbility/
├── main.py        # Interactive — set an alarm
├── background.py     # Background — fire the alarm
└── alarm.mp3      # Supporting files
```

Trigger words and the ability's unique name are configured in the OpenHome dashboard.

> ⚠️ The background file **must** be named exactly `background.py`. No other filename will be detected by the platform.

### Critical Differences: main.py vs background.py

These are the most common sources of bugs when writing background daemons. Pay close attention.

| Aspect | `main.py` | `background.py` |
|---|---|---|
| `call()` signature | `call(self, worker)` | `call(self, worker, background_daemon_mode)` |
| `CapabilityWorker` init | `CapabilityWorker(self)` | `CapabilityWorker(self)` |
| Triggered by | User hotwords | Automatically on session start |
| Lifecycle | Runs once, then exits | Continuous `while True` loop |
| `resume_normal_flow()` | **REQUIRED** on every exit path | **NOT needed** (independent thread) |
| Works in sleep mode | No — requires active session | **Yes** — runs even when Personality is asleep |
| Multiple instances | One at a time | Multiple daemons supported |

### New SDK Methods

| Method | Returns | Async | Description |
|---|---|---|---|
| `get_timezone()` | `str` | No | User's timezone (e.g. `"America/Chicago"`). Use for alarms, calendars, time-aware logic. |
| `get_full_message_history()` | `list` | No | Full conversation transcript. Background daemons use this to monitor the live conversation. |
| `send_interrupt_signal()` | — | Yes | Stops current Personality output. Call before `speak()` or `play_audio()` from a background daemon. |

```python
# Get user timezone (synchronous)
tz = self.capability_worker.get_timezone()

# Get conversation history (synchronous)
history = self.capability_worker.get_full_message_history()

# Interrupt before speaking from a background daemon (async)
await self.capability_worker.send_interrupt_signal()
await self.capability_worker.speak("Your alarm is going off!")
```

### background Code Template

Copy this as your starting point for any `background.py`. Note the `call()` signature has an extra `background_daemon_mode` parameter, but the `CapabilityWorker` constructor is the same as `main.py`.

```python
import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
from time import time

class YourCapabilityBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    #{{register capability}}

    async def background_loop(self):
        self.worker.editor_logging_handler.info(
            "%s: background started" % time()
        )
        while True:
            # --- your background logic here ---
            self.worker.editor_logging_handler.info(
                "%s: background cycle" % time()
            )
            await self.worker.session_tasks.sleep(20.0)

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.background_loop())
```

### How the Main Flow Works

1. User is in **Main Flow** having a normal conversation
2. User says something matching a trigger word
3. Main Flow calls the ability's `call()` method
4. The ability takes over: speaks, listens, does its thing
5. The ability calls `resume_normal_flow()` → user is back in Main Flow

### Key Implications
- You can read conversation history from **before** your trigger fired
- Anything you say via `speak()` enters the Personality's conversation history
- You **cannot** silently inject text — the agent has to say it out loud
- You **must** always hand control back or the Personality goes silent

> **The #1 bug in abilities:** forgetting to call `resume_normal_flow()` on an exit path. Walk through every code path.

### Quick Mode vs. Full Mode

| Phrasing | Mode | Behavior |
|---|---|---|
| `"Play jazz"` | Quick | Just do it, no conversation |
| `"Help me build a playlist"` | Full | Enter an interactive loop |
| `"Turn off the lights"` | Quick | Execute immediately |
| `"Set up my evening routine"` | Full | Multi-step conversation |

Classify at trigger time — the user's phrasing tells you which experience they expect.

### Background Ability Patterns

**The Life Logger Pattern** *(Background Daemon)*
- Listens quietly in the background over extended periods
- Uses speaker diarization to identify who's talking
- Every 90 seconds, processes a new chunk of transcription
- LLM extracts: action items, goals, topics, decisions, notable quotes
- Dashboard updates in real-time — user can see it thinking

**The Ambient Profiler Pattern** *(Background Daemon)*
- background ability silently builds and updates `user.md` every day
- `user.md` appended to Main Flow personality prompt
- Main Flow always knows what's happening in your life without you telling it
- Speaker diarization enables per-speaker memory in multi-person households

> This is the most powerful pattern: your speaker knows your life context because it was there yesterday, and the day before, and the day before that.

**The Background Scheduler Pattern** *(Background Daemon + Skill)*
- `"Set an alarm for 7 AM"` → Skill writes alarm time, Background Daemon polls and fires
- Same for: reminders, daily briefings, scheduled check-ins, recurring reports

**Coordination Pattern: main.py + background.py**

The primary way the interactive and background components communicate is through shared persistent file storage. Both files read and write to the same user-scoped files.

| Step | Component | Action |
|---|---|---|
| 1 | User | Says *"set an alarm for 3pm Thursday"* |
| 2 | `main.py` | LLM parses time, writes alarm to `alarms.json` |
| 3 | `main.py` | Confirms to user, calls `resume_normal_flow()` |
| 4 | `background.py` | Polls `alarms.json` every ~15 seconds (running since session start) |
| 5 | `background.py` | Target time hits → `send_interrupt_signal()` |
| 6 | `background.py` | Plays `alarm.mp3`, speaks notification |
| 7 | `background.py` | Updates alarm status to `"triggered"` in `alarms.json` |

**Sample `alarms.json`:**
```json
[
  {
    "id": "alarm_1772046000778",
    "created_at_epoch": 1772046000,
    "timezone": "America/Los_Angeles",
    "target_iso": "2026-02-26T00:06:00-08:00",
    "human_time": "12:01 AM on Thursday, Feb 26, 2026",
    "source_text": "Can you set an alarm for me?",
    "status": "scheduled"
  }
]
```

### The ability.md Pattern
Every Brain Skill ships with an `ability.md` file containing YAML frontmatter (`name` + `description`) and markdown instructions. The `description` field is the **only** field the system reads to decide when to trigger.

```yaml
---
name: portfolio-pulse
description: >
  Invoked when the user asks about their investment portfolio, stock 
  performance, market movements, or how their finances are doing.
  Do NOT invoke for general finance questions the LLM can answer itself.
---
```

> **Bad description = never triggers or triggers incorrectly.** This is the single most important field for Brain Skill abilities.

### Templates and Resources

| Resource | Location |
|---|---|
| Alarm Ability (Interactive Combined) | https://github.com/openhome-dev/abilities/tree/dev/templates/Alarm |
| Standalone Background Daemon | https://github.com/openhome-dev/abilities/tree/dev/templates/Background |
| SDK Reference (updated) | `OpenHome_SDK_Reference` in project docs |
| Building Great Abilities (updated) | `Building_Great_OpenHome_Abilities` in project docs |
| Questions / Support | `#dev-help` on Discord |

> The alarm template is the best reference for the Interactive Combined pattern. Study both `main.py` and `background.py` to understand how they coordinate.

---

## 7. Ability Ideas by Location

### Nightstand / Bedroom
| Ability | Type | Description |
|---|---|---|
| Morning Manifest | Brain Skill | One sentence: the one thing on your calendar that matters most |
| Lights Out Debrief | Skill | Voice-dump everything on your mind; organized into actionable items by morning |
| Tomorrow's Weather Whisper | Brain Skill | Only speaks if weather demands action: *"You'll want a coat"* |
| Bedtime Story Engine | Skill | Serialized adventure for kids, remembers where it left off |
| Midnight Worry Jar | Skill | Captures anxious 2 AM thoughts, reframes as calm to-dos by breakfast |
| Gratitude Fade-Out | Skill | One good thing from today, ambient tone, silence. 15-second ritual. |
| Morning Body Check | Background Daemon | *"How are you feeling?"* every morning. One word. Patterns after a month. |
| Dream Catcher | Background Daemon | Transcribes sleep-talking, builds dream journal with recurring themes |
| Sleep Debt Tracker | Background Daemon | Logs bed/wake times, weekly report on target gap |
| Power Nap Coach | Skill | Optimal wake point, transition sounds, prevents deep sleep |

### Living Room (Couple / Family)
| Ability | Type | Description |
|---|---|---|
| Settle It | Skill | Game-show ruling with sound effects for trivial disagreements |
| Movie Matchmaker | Skill | Each secretly states mood, speaker threads the needle |
| Dinner Decider | Brain Skill | One confident suggestion based on recent meals, preferences, and season |
| Couple's Trivia | Skill | Pub quiz for two, running all-time scoreboard across weeks |
| The Argument Cooldown | Background Daemon | Detects heated voices, waits for pause, interjects with something disarming |
| Weekend Planner | Brain Skill | Friday evening, single activity pitch based on weather + interests + local events |
| Guest Mode | Background Daemon | Unfamiliar voices → suppresses personal notifications, switches to party behaviors |
| Anniversary Vault | Background Daemon | Silently captures inside jokes, laughter, heartfelt moments. Compiles for anniversary. |
| Background Narrator | Skill | Narrates mundane activities in nature documentary or sports broadcast style |

### Kitchen
| Ability | Type | Description |
|---|---|---|
| Recipe Walkthrough | Skill | Hands-free, pace-adaptive step-by-step with "next" and "repeat" |
| Grocery List Builder | Background Daemon | Overhears *"we're out of milk"* and silently adds to list |
| Cooking Timer Orchestrator | Skill | Multiple named timers running simultaneously |
| Kitchen Radio DJ | Skill | Plays music + gives brief news/weather during natural breaks |
| Sous Chef Advisor | Skill | *"Can I substitute X for Y?"* Quick one-shot answers |

### Conference Room
| Ability | Type | Description |
|---|---|---|
| Decision Logger | Background Daemon | Extracts only decisions from discussion noise into a clean list |
| Action Item Extractor | Background Daemon | Detects task assignments: owner + task + deadline |
| Meeting Recap | Background Daemon | 5-sentence executive summary within 60 seconds of meeting end |
| Who Talked Most | Background Daemon | Speaking time per person via diarization |
| Pre-Meeting Briefer | Brain Skill | 15-second recap of last meeting's decisions and outstanding items |
| Follow-Up Drafter | Brain Skill | Drafts post-meeting email with summary + action items + next steps |
| Agenda Enforcer | Background Daemon | Gentle chime when group drifts off-topic or overspends time |

### Home Office
| Ability | Type | Description |
|---|---|---|
| Focus Guardian | Background Daemon | Blocks interruptions during deep work, only surfaces urgent items |
| Standup Generator | Brain Skill | Summarizes what you worked on yesterday from ambient context |
| Meeting Prep Briefer | Brain Skill | Before each call, reads attendee context and last interaction notes |
| End-of-Day Wrap | Background Daemon | *"Here's what you did today"* summary from overheard context |

### College Dorm
| Ability | Type | Description |
|---|---|---|
| Study Pomodoro Coach | Skill | 25 min focus, break with fun fact, weekly study hours log |
| Exam Countdown | Background Daemon | Daily casual drop: how many days until next exam |
| Cram Session Quiz Master | Skill | Infinite rapid-fire quiz adapting to weak spots |
| Budget Buddy | Background Daemon | Logs every spending mention, Sunday weekly total with categories |
| Wake Up Enforcer | Skill | Adapts aggression to class importance. Reads assignments if you keep snoozing. |

### Car / Commute
| Ability | Type | Description |
|---|---|---|
| Commute Debrief | Skill | Processes the day on the drive home, captures what went well |
| Hands-Free Messenger | Skill | *"Tell Sarah I'm 10 minutes out"* with zero screen interaction |
| Traffic Aware ETA | Background Daemon | Proactively updates ETA as conditions change without being asked |
| Errand Optimizer | Brain Skill | Knows your to-do list + route, suggests optimal stop order |

---

## 8. Ability Ideas by User

### Kids (Ages 5–12)
| Ability | Type | Description |
|---|---|---|
| Homework Helper | Skill | Walks through problems step by step without giving the answer |
| Would You Rather | Skill | Endless escalating scenarios, remembers which ones got biggest laughs |
| Animal Expert | Skill | Any animal → 3 mind-blowing facts → *"want another or pick a new animal?"* |
| Story Builder | Skill | Collaborative choose-your-own-adventure with AI as wildcard narrator |
| Spelling Bee Coach | Skill | Gives word, uses in sentence, tracks mastery across sessions |
| Mystery Detective | Skill | Short mystery scene, kid asks yes/no questions to solve the case |

### Kids Games (Ages 8–10)
| Ability | Type | Description |
|---|---|---|
| Boss Battle Trivia | Skill | Correct answers deal damage to bosses. Wrong = boss attacks. Loot drops. |
| Monster Collector | Skill | Correct answers catch randomly generated monsters. Common to legendary rarity. |
| Speed Round | Skill | 3-second timer, dramatic streak counter, sports-commentator scoring |
| Dungeon Crawler | Skill | Persistent character, levels up across days, permadeath = real stakes |
| Conspiracy Board | Background Daemon | One new clue per day. Solve the week-long mystery. |

### Parents
| Ability | Type | Description |
|---|---|---|
| Baby Sleep Tracker | Background Daemon | Logs sleep/wake cycles from ambient audio, surfaces patterns |
| Toddler Vocabulary Tracker | Background Daemon | Maps language development against milestones, flags potential delays |
| Family Calendar Sync | Skill | *"Does anyone have anything Thursday?"* checks all family calendars |
| Bedtime Routine Manager | Skill | Guides kids through brush teeth → story → lights out sequence |

### Elderly Users
| Ability | Type | Description |
|---|---|---|
| Medication Reminder | Background Daemon | Gentle, persistent, logs whether confirmation was given |
| Cognitive Wellness Check | Background Daemon | Tracks word-finding difficulty and repetition over months |
| Family Connection | Skill | *"Call your daughter"* with simplified voice dialing |
| Daily Companion | Brain Skill | Morning greeting, weather, news headlines, gentle check-in. Combats isolation. |

### Professionals
| Ability | Type | Description |
|---|---|---|
| Executive Brief | Brain Skill | Morning synthesis of calendar, market moves, key emails, team updates |
| Sales Call Scorer | Background Daemon | Post-call analysis of talk ratio, question quality, objection handling |
| Client Meeting Debrief | Brain Skill | After client leaves: *"What did we learn? What do we owe them?"* |

---

## 9. Ability Ideas by Use Case

### Health & Wellness
| Ability | Type | Description |
|---|---|---|
| Mood Logger | Background Daemon | Daily one-word check-in. Monthly patterns. Seasonal insights. |
| Guided Meditation Selector | Brain Skill | Picks meditation from API based on time, mood, stress level |
| Breathing Exercise Coach | Skill | Guided box breathing, 4-7-8, Wim Hof with voice timing |
| Symptom Tracker | Background Daemon | Logs mentions of how you feel. *"You've mentioned headaches 4 times this week."* |
| Voice Health Scanner | Background Daemon | Detects micro-changes in pitch, pace, breathiness → early illness detection |

### Productivity
| Ability | Type | Description |
|---|---|---|
| Inbox Zero Coach | Skill | Reads email subjects, you triage by voice: "delete, reply later, urgent" |
| Voice-to-Task | Skill | *"Remind me to call the plumber Thursday"* → creates task in Todoist/Asana |
| Weekly Review | Brain Skill | Friday afternoon: what you accomplished, what carried over, what's next week |
| Voice Notes to Structured Docs | Skill | Rambling voice input → organized markdown/PDF output |

### Finance
| Ability | Type | Description |
|---|---|---|
| Portfolio Pulse | Brain Skill | Morning one-liner: how your investments moved overnight |
| Spending Tracker | Background Daemon | Logs every mentioned purchase. Sunday summary with categories. |
| Trending Stocks | Brain Skill | What retail traders are buzzing about. Top movers. Unusual volume. |
| Bank Balance Reality Check | Skill | *"Can I afford that?"* → pulls actual balance + upcoming bills |

### Entertainment
| Ability | Type | Description |
|---|---|---|
| Song of the Day | Brain Skill | Summarizes mood + events, sends to Suno API, generates unique song about YOUR day |
| Movie/Show Recommender | Brain Skill | Learns taste over weeks, factors in mood, who's in the room, time of day |
| Live Sports Companion | Background Daemon | Score updates, key plays, proactive alerts when it gets close |
| Spotify Time Machine | Skill | *"What was I listening to a year ago today?"* → nostalgia playlist |

### Shopping & Logistics
| Ability | Type | Description |
|---|---|---|
| Price Watcher | Background Daemon | *"Watch that TV on Amazon"* → monitors → announces when price drops |
| Grocery Auto-Order | Background Daemon | List builds passively from kitchen mentions → sends order for confirmation |
| Package Tracker | Brain Skill | *"Where's my stuff?"* → consolidates all deliveries, proactive delay alerts |
| Gift Idea Collector | Background Daemon | Logs when family mentions wanting something. Surfaces list before holidays. |

### Smart Home & IoT
| Ability | Type | Description |
|---|---|---|
| Scene Controller | Skill | *"Movie time"* → dims lights, sets thermostat, closes blinds, starts media |
| Morning Routine | Skill | *"Good morning"* triggers lights, coffee, weather, calendar in sequence |
| Security Check | Skill | *"Is the house locked up?"* → checks all locks, cameras, alarm status |

---

## 10. 3rd-Party API Integration

| Category | APIs | What They Enable | Best Ability Type |
|---|---|---|---|
| **Music & Audio** | Suno, ElevenLabs, Spotify, Podcast APIs | Song generation, voice cloning, playback, discovery | Skill, Brain Skill |
| **Finance** | Plaid, Alpha Vantage, Polygon.io, CoinGecko | Bank data, stock prices, portfolio tracking, crypto alerts | Brain Skill, Background Daemon |
| **Calendar & Productivity** | Google Calendar, Todoist, Notion, Gmail | Event CRUD, task creation, notes, email triage | Skill, Brain Skill |
| **Communication** | Twilio, Slack, Telegram, SendGrid | SMS, calls, WhatsApp, channel messages, email delivery | Skill |
| **Media & Content** | TMDB, YouTube, NewsAPI, Goodreads | Movie data, video search, news feeds, book recommendations | Skill, Brain Skill |
| **Location & Travel** | FlightAware, Google Places, Uber/Lyft, Ticketmaster | Flight tracking, local discovery, rides, concert alerts | Brain Skill, Background Daemon |
| **Smart Home** | Philips Hue, Nest, SmartThings, IFTTT | Lights, thermostat, unified control, webhook triggers | Skill, Local |
| **Health** | Apple Health, Nutritionix, Headspace, Fitbit | Steps, calories, meditation, sleep scores | Background Daemon |
| **AI & Generation** | OpenAI, DALL-E, Whisper, ElevenLabs SFX | Specialized LLM calls, images, transcription, sound effects | Any type |
| **Niche** | Astrology APIs, Spoonacular, SportRadar, GitHub | Horoscopes, recipes, live sports, repo management | Skill, Brain Skill |

> The most powerful abilities don't call one API — they weave 2–3 together. A morning briefing that hits calendar + weather + news + email and synthesizes into one paragraph is 10x more valuable than four separate lookups.

---

## 11. The OpenHome + OpenClaw Bridge

### What OpenClaw Is
OpenClaw is a locally-running desktop AI agent with **2,868+ community-built skills**. It operates on the user's machine — reads files, runs CLIs, accesses the local network. Its public registry (ClawHub) has skills for smart home, finance, communication, media, code, shopping, transit, and health.

### Why It Matters
OpenHome is sandboxed. OpenClaw can touch the local machine. The bridge between them creates a voice agent with desktop-level agency.

> OpenHome doesn't need to build 500 API integrations. It builds **one bridge ability** and inherits an entire ecosystem of 2,868 skills.

### What the Bridge Unlocks

| Category | Skills Available | Voice Bridge Example | Ability Type |
|---|---|---|---|
| Smart Home | 56 (Hue, IKEA, Nest, Tesla, Govee, Roborock) | *"Turn off the living room lights"* | Skill |
| Communication | 132 (WhatsApp, Slack, Telegram, email) | *"Tell Mom I'll be there at 6"* | Skill |
| Media | 80 (Spotify, Plex, Jellyfin) | *"Play discover weekly on living room speaker"* | Skill |
| Productivity | 135 (Google Workspace, GitHub, Notion) | *"What PRs need my review?"* | Brain Skill |
| Shopping | 51 (Amazon, grocery, price tracking) | *"Order everything on my grocery list"* | Skill |

### Flagship Bridge Abilities

| Ability | Type | Description |
|---|---|---|
| Smart Home Scene Controller | Skill | *"Movie time"* → OpenClaw orchestrates Hue + Nest + media |
| Send Message by Voice | Skill | *"Tell Mom I'll be there at 6"* → OpenClaw sends WhatsApp |
| Voice-Triggered Email Triage | Brain Skill | *"Any urgent emails?"* → OpenClaw scans Gmail → OpenHome reads top 3 |
| Tesla Voice Control | Skill | *"Warm up the car"* → OpenClaw → Tesla API |
| GitHub Standup | Brain Skill | *"What did I push yesterday?"* → OpenClaw queries git log |
| Voice Clone Creator | Skill | *"Clone my voice"* → record → OpenClaw processes → new Voice ID |
| Meeting Notes to Vault | Background Daemon | Conference room capture → OpenClaw writes to Obsidian |
| Document Generator | Brain Skill | *"Write up that proposal"* → OpenHome history → OpenClaw generates PDF |

### Security
- **Permission levels:** read-only (safe) → write (needs confirmation) → financial/messaging (explicit voice confirmation)
- OpenHome sends structured requests, never raw code
- OpenClaw's registry found 396 malicious skills out of 5,705 — **vetting is essential**

---

## 12. Combining Frameworks

| Combination | What It Creates | Example | Ability Type |
|---|---|---|---|
| Observer + Surprise Artifact | Passive intelligence producing documents you didn't ask for | Anniversary Vault, Dream Dictionary | Background Daemon |
| Proxy Agent + OpenClaw Bridge | Voice commands that execute real-world actions | *"Send WhatsApp"*, *"Book Uber"*, *"Order groceries"* | Brain Skill |
| Daily Ritual + Compound Loop | Habits that get smarter every day | Morning briefing that learns what you care about | Skill + Brain Skill |
| Social Multiplier + Emotional Radar | Group experiences adapting to room energy | Party trivia that adjusts difficulty to the crowd | Skill |
| Information Funnel + Context Mesh | One spoken sentence synthesizing 5+ sources | Calendar + weather + traffic + mood = one paragraph | Brain Skill |
| Invisible Worker + Graceful Silence | Background intelligence speaking only when it matters | Flight tracker that only alerts on delays | Background Daemon |

> The most magical abilities combine 2–3 frameworks. Pick your primary framework, then ask: *"What second framework would make this 10x better?"*

---

## 13. The Sci-Fi Frontier

Ideas that sound impossible but are technically buildable today with ambient audio + speaker diarization + LLM extraction + longitudinal logging. No new hardware required.

| Ability | Type | What It Does |
|---|---|---|
| **Relationship Autopsy** | Background Daemon | Detects shifts in communication patterns — shorter responses, fewer laughs, more interruptions — before either person consciously notices |
| **Voice Health Scanner** | Background Daemon | Vocal cord micro-changes detect illness 24–48 hours before symptoms appear |
| **Cognitive Decline Watchdog** | Background Daemon | Tracks word-finding difficulty and repetition over months for elderly users. Could catch early dementia signs. |
| **Emotional Forecast** | Brain Skill | Predicts how your day will go based on morning voice, sleep data, and historical patterns |
| **Personality Drift Monitor** | Background Daemon | Tracks how your language, interests, and opinions evolve over years. Produces a "who you're becoming" report. |
| **Argument Predictor** | Background Daemon | Recognizes conversational precursors to fights and subtly intervenes before escalation |
| **Dream Decoder Network** | Background Daemon | Cross-references sleep-talking with waking conversations. Maps subconscious patterns. |

> **The insight:** Your voice is a biomarker. Your speech patterns are a psychological fingerprint. A device that listens every day for a year knows things about you that you don't know about yourself.

---

## 14. Quality Checklist

Run through this before shipping any ability:

**All Types**
- [ ] No `print()` — use `editor_logging_handler` for all logging
- [ ] No raw `asyncio` — use `session_tasks`
- [ ] All API calls wrapped in `try/except` with spoken error messages
- [ ] All requests include `timeout=10` or similar
- [ ] `speak()` strings are 1–2 sentences and sound natural read aloud
- [ ] Destructive actions use a confirmation loop before executing
- [ ] Multi-turn flows allow cancellation at any point (`"never mind"`, `"cancel"`)
- [ ] Filler speech plays before any API call that takes more than 1 second
- [ ] API keys are placeholder constants, not hardcoded real keys
- [ ] No blocked imports (`redis`, `connection_manager`, `user_config`, `open`)
- [ ] File names namespaced to your ability (e.g., `smarthub_prefs.json` not `data.json`)
- [ ] Tested by reading all `speak()` strings out loud

**Skill & Brain Skill only**
- [ ] `resume_normal_flow()` called on **every** exit path (happy path, breaks, except blocks, timeouts)
- [ ] Exit word detection in any looping ability (`"done"`, `"stop"`, `"bye"`)

**Brain Skill only**
- [ ] `ability.md` description is specific, tested, and includes explicit exclusions
- [ ] Tested against real conversation samples the ability should and should not catch

**Background Daemon only**
- [ ] `background.py` is named exactly `background.py` — no other filename is detected by the platform
- [ ] `call()` signature includes the `background_daemon_mode` parameter
- [ ] `session_tasks.sleep()` used for poll interval — **never** `asyncio.sleep()`
- [ ] Poll interval is 10–30 seconds (15–30 seconds for alarms)
- [ ] Main loop is a `while True` — required for sleep mode support
- [ ] No `resume_normal_flow()` anywhere in the daemon
- [ ] `send_interrupt_signal()` called before any `speak()` or `play_audio()` from the daemon
- [ ] JSON writes use delete-then-write, **never** append
- [ ] Missing JSON files handled gracefully with `check_if_file_exists()` before reading
- [ ] Logging is generous — `editor_logging_handler` is your only window into silent daemons
- [ ] Tested that the background survives Personality sleep mode

---

## 15. The Brainstorm Catalog — 170+ Ideas

### Daily Life & Routines

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Daily Song Generator | Living Room | Brain Skill | 20s Woman | Hype song via Suno API summarizing biggest wins today |
| Morning Motivation | Nightstand | Skill | Entrepreneur | Reads yesterday's goals, asks *"what's the one thing today?"* |
| Outfit Advisor | Bedroom | Brain Skill | Professional | Checks weather + calendar formality, suggests what to wear |
| Commute Launcher | Entryway | Skill | Office Worker | Traffic + ETA + podcast queue triggered by *"I'm leaving"* |
| Arrival Debrief | Living Room | Brain Skill | Parent | Welcome home + what happened while you were gone |
| Evening Wind-Down | Living Room | Skill | Couple | Dims lights, plays ambient music, asks *"how was today?"* |
| Weekend Kickoff | Living Room | Brain Skill | Family | Friday 6PM: 3 weekend activities from weather + interests |
| Bedtime Closer | Nightstand | Skill | Anyone | Locks doors, sets alarm, gives tomorrow's first event |
| Caffeine Tracker | Kitchen | Background Daemon | Coffee Addict | Logs every coffee mention, warns after #3, tracks sleep impact |
| Habit Streak | Any Room | Background Daemon | Self-Improver | Tracks daily habits by voice check-in, announces streak count |
| Dog Walk Tracker | Entryway | Background Daemon | Pet Owner | Logs walk times, flags if too long since last, weather-aware |

### Work & Productivity

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Standup Bot | Home Office | Brain Skill | Developer | Reads git log + calendar, generates standup update |
| Email Sniper | Home Office | Skill | Executive | Reads top 5 subjects, you say keep/archive/urgent each |
| Focus Lock | Home Office | Skill | Writer | Blocks all interactions for set time, plays white noise |
| Decision Journal | Home Office | Background Daemon | Founder | Logs decisions with reasoning, reviews outcomes 30 days later |
| Client Prep | Home Office | Brain Skill | Salesperson | Before each call: CRM notes, last email, deal stage |
| Idea Capture | Any Room | Skill | Creative | *"Save that idea"* → logs timestamped thought by project |
| Pitch Practice | Living Room | Skill | Startup Founder | Times pitch, feedback on pace, filler words, clarity |
| Code Review Reader | Home Office | Skill | Developer | Reads PR comments aloud via GitHub API |
| Sprint Closer | Home Office | Brain Skill | PM | End of sprint: completed vs planned, generates retro points |

### Finance & Money

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Spending Alarm | Kitchen | Background Daemon | Overspender | Alert when daily spending exceeds budget via Plaid |
| Bill Countdown | Living Room | Brain Skill | Budgeter | Monday morning: *"3 bills due this week totaling $340"* |
| Impulse Blocker | Living Room | Brain Skill | Shopper | *"Sleep on it. I'll ask again tomorrow."* Delays purchases. |
| Side Hustle Tracker | Home Office | Background Daemon | Gig Worker | Logs income mentions, generates monthly P&L |
| Subscription Audit | Living Room | Brain Skill | Anyone | Monthly: 8 subscriptions, $47/mo. Here's the breakdown. |
| Savings Goal | Living Room | Brain Skill | Saver | *"You're $340 away from your vacation fund goal."* |
| Crypto Morning Brief | Home Office | Brain Skill | Trader | Portfolio value, biggest movers, whale activity overnight |

### Health & Wellness

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Stretch Break | Home Office | Background Daemon | Desk Worker | Every 90 min: guides 2-minute desk stretch with audio cues |
| Breathing Coach | Bedroom | Skill | Anxious Person | Guided breathing with tone-based inhale/exhale pacing |
| Calorie Estimator | Kitchen | Skill | Dieter | Describe meal, Nutritionix API estimates calories |
| Symptom Log | Bedroom | Background Daemon | Chronic Illness | Voice-log symptoms daily, weekly report for doctor |
| Allergy Alert | Kitchen | Background Daemon | Allergy Sufferer | Checks pollen API, warns before you go outside |
| Mental Health Check | Bedroom | Brain Skill | Anyone | Weekly structured check-in, monthly patterns, resources offered |

### Relationships & Social

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Date Night Planner | Living Room | Skill | Couple | Suggests restaurant + activity from budget, prefs, location |
| Love Language Tracker | Living Room | Background Daemon | Couple | Notes acts of service, affirmation, gifts. Shows balance. |
| Friend Tracker | Living Room | Background Daemon | Social Person | *"You haven't seen Jake in 6 weeks. Want to text him?"* |
| Party DJ | Living Room | Skill | Host | Guests shout requests, AI builds and manages playlist |
| Gift Brain | Any Room | Background Daemon | Thoughtful Person | Year-round logging of *"I wish I had..."* per family member |
| Anniversary Countdown | Bedroom | Background Daemon | Partner | *"12 days away. Last year you went to Chez Louis."* |

### Kids & Family

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Chore Quest | Living Room | Skill | Family | Gamified chore assignment, XP points, weekly champion |
| Vocabulary Builder | Kid's Room | Skill | Student (8) | Word of the day with examples, quizzed next day |
| Math Duel | Living Room | Skill | Siblings | Head-to-head mental math, per-player difficulty, scoring |
| Joke of the Day | Kitchen | Skill | Family | One joke at breakfast. Kids submit their own. Weekly best-of. |
| Talent Show Host | Living Room | Skill | Family | MC's family talent show with intros, applause, scoring |

### Entertainment & Games

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Murder Mystery | Living Room | Skill | Dinner Party | Assigns roles, distributes clues by voice, runs whodunit |
| Rap Battle Coach | Bedroom | Skill | Teen | Gives topic, you freestyle, AI judges with beat backing |
| Sports Bar Mode | Living Room | Background Daemon | Sports Fan | Live scores with crowd noise, highlight alerts, stat callouts |
| DnD Dungeon Master | Living Room | Skill | Gamers | Full campaign narration with ambient music, NPC voices |
| Escape Room | Living Room | Skill | Couple | Voice-only puzzle room with timer, hints, themed scenarios |
| Debate Tournament | Living Room | Skill | Friends | Assigned topics, timed arguments, AI judges winner |

### Smart Home & Environment

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Room Mood Setter | Living Room | Skill | Anyone | *"Cozy mode"* → warm lights, fireplace sounds, thermostat up |
| Leaving House Check | Entryway | Skill | Forgetful | *"Lights off, thermostat down, doors locked. You're good."* |
| Energy Coach | Living Room | Background Daemon | Homeowner | *"AC running 6 hours, 68° outside. Open a window?"* |
| Guest Welcome | Entryway | Background Daemon | Host | Detects doorbell, plays welcome, adjusts to guest mode |
| Thermostat Negotiator | Living Room | Brain Skill | Couple | Splits the difference between preferred temperatures fairly |

### Creative & Maker

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Beat Maker | Bedroom | Skill | Teen | Describe a vibe, AI generates beat via audio API for freestyle |
| Sound Effect Studio | Any Room | Skill | Creator | *"Spaceship landing sound"* → ElevenLabs SFX API |
| Writing Prompt | Home Office | Brain Skill | Writer | Daily creative prompt tailored to genre and current project |
| Remix My Day | Bedroom | Background Daemon | Producer | Transcript of your day → generates lo-fi ambient track from it |
| Mood Playlist | Living Room | Brain Skill | Anyone | Detects mood from voice, generates Spotify playlist to match |

### Background / Always-On

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Life Logger | Any Room | Background Daemon | Reflective | Always-on ambient capture, daily summaries to dashboard |
| Baby Monitor Plus | Nursery | Background Daemon | New Parent | Detects crying, unusual silence, sleep breathing. Alerts phone. |
| Meeting Scribe | Conference | Background Daemon | Team | Auto-starts when 3+ voices heard, writes notes until silence |
| Daily To-Do Compiler | Any Room | Background Daemon | Busy Person | Catches all *"I need to..."* mentions → to-do list by evening |
| Gratitude Harvester | Any Room | Background Daemon | Anyone | Catches positive statements all day, weekly gratitude list |
| Dream Recorder | Bedroom | Background Daemon | Dreamer | Captures sleep-talking, builds journal without lifting a finger |
| Profanity Jar | Living Room | Background Daemon | Family | Beeps on bad words. Running tally. Weekly fine announcement. |

### Niche & Weird

| Ability | Location | Type | User | Description |
|---|---|---|---|---|
| Wine Pairing | Kitchen | Skill | Foodie | Describe dinner, AI suggests wine from sommelier API |
| Dad Joke Engine | Kitchen | Skill | Dad | Endless supply, progressively worse, groan-tracking scoreboard |
| Plant Care | Any Room | Skill | Plant Parent | *"How often water my fiddle leaf fig?"* + scheduled reminders |
| Hot Take Generator | Living Room | Skill | Friends | Spicy opinion generated, group debates, AI judges |
| Life Narrator | Any Room | Skill | Anyone | Morgan Freeman mode: narrates what you're doing in real-time |
| Compliment Machine | Bathroom | Background Daemon | Anyone | Daily compliment on detection. Silly but surprisingly powerful. |
| Random Fact Cannon | Kitchen | Skill | Family | Fires obscure fact at random meal times. Greatest-hits list. |

---

## Closing Thought

> *The best Ability does something the LLM can't, at a moment the user didn't expect, with information accumulated over time, delivered in fewer words than they'd use themselves.*
>
> Build for the room. Build for the moment. Build for the silence between the words.
>
> Then let the speaker do what it does best: **be there.**

---
