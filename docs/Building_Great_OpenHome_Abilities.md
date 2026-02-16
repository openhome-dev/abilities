# Building Great OpenHome Abilities

*Voice UX, Architecture Patterns, and Real-World Examples*

---

## What Makes a Good Ability

Every OpenHome Personality is powered by an LLM out of the box. That means your Personality can already handle a lot natively — no Ability needed:

- Unit conversions, math, and calculations
- Translations, writing help, and grammar checks
- Trivia, general knowledge, definitions, and explanations

> **If the LLM can already answer it in conversation, it's not adding value as an Ability.**

It's also worth knowing that every Personality has a **Description Prompt** in its settings — this is the system-level LLM instruction that defines how your Personality behaves, its tone, its role, and its boundaries. If what you want is a behavioral change — like "always respond in Spanish" or "act as a fitness coach" or "never discuss politics" — that belongs in the Personality's prompt configuration, not in a standalone Ability. Abilities are for when the LLM needs to *do* something it can't do with just a prompt: call an API, play audio, persist data, control a device.

A good Ability brings in something the LLM can't do on its own:

- Calling a 3rd party API — weather, stocks, news, smart home devices
- Playing audio or music
- Accessing real-time data the LLM doesn't have (calendar, email, Slack)
- Multi-step voice workflows — guided meditation, games with scoring, cooking timers
- Controlling hardware or IoT devices
- Persisting user data across sessions — journals, trackers, saved preferences

**The key question:** "Does this need something external or experiential that an LLM can't provide from its own knowledge?" If yes — great Ability.

| ✔ Build an Ability For | ✘ Don't Build an Ability For |
|---|---|
| Live weather from an API | "What's the capital of France?" |
| Calendar integration (read/create/modify events) | Converting units or doing math |
| Smart home device control | Translating a phrase |
| Interactive quiz with scoring + persistence | Answering trivia from general knowledge |
| Daily journal that saves entries across sessions | Summarizing text the user just said |

> *The best Abilities make the Personality feel like it can actually do things in the real world — not just talk about them.*

---

## How Ability Runtime Works

Before you start building, it helps to understand what actually happens under the hood when your Ability runs. This saves you from building something that the platform can't support — like background timers or proactive notifications.

### On-Demand, Stateless by Design

Abilities don't run in the background. They're on-demand — your Ability only exists while it's actively handling a conversation. Here's what that means in practice:

- **Your Ability starts** when the user says a trigger word and the platform calls your `call()` method.
- **Your Ability lives** as long as your async method is running. All your instance variables (`self.whatever`), your conversation history list, your API data — it all lives in memory on that instance.
- **Your Ability dies** the moment you call `resume_normal_flow()`. The instance is gone. Every variable, every list, every dict you built up during the session — vanished.

This is the thing that trips people up. You can't set a timer that fires in 15 minutes to remind the user of a meeting. You can't poll an API every 5 minutes in the background. You can't have an Ability proactively interrupt the user with a notification. The Ability only exists while the user is actively talking to it.

```python
# This is your Ability's entire lifespan:
def call(self, worker):
    self.worker = worker
    self.capability_worker = CapabilityWorker(self.worker)
    self.my_data = {}  # ← exists now
    self.worker.session_tasks.create(self.run())  # ← starts your logic

async def run(self):
    self.my_data["name"] = "Chris"  # ← lives in memory
    await self.capability_worker.speak("Hey Chris!")
    # ... do stuff ...
    self.capability_worker.resume_normal_flow()
    # ← self.my_data is gone. Instance is gone. Everything is gone.
```

### What You Can't Do (Yet)

Because of the on-demand architecture, these aren't possible right now:

- **Background polling** — no checking email every 5 minutes
- **Proactive notifications** — no "hey, your meeting starts in 10 minutes" interrupts
- **Scheduled tasks** — no timers, no cron-style execution
- **Cross-ability communication** — one Ability can't directly talk to another while they're running
- **Chaining Abilities** — your Ability can't call another Ability directly. You must call `resume_normal_flow()` first to hand control back to the Personality, and then the user's next utterance can trigger a different Ability. You can stack complex logic inside a single Ability, but you can't orchestrate across multiple Abilities in one session.

This might change as the platform evolves, but for now, design your Abilities around the trigger → respond → exit pattern. The user initiates, your Ability responds, then it's done.

### What You Can Do

Within a session, you have full control:

- **Maintain state in memory** — dictionaries, lists, counters, anything on `self`. It all works fine as long as the session is alive.
- **Build conversation history** — keep a list of `{"role": "user", "content": "..."}` dicts and pass it to `text_to_text_response()` on every turn. The LLM will have full context of the conversation so far.
- **Rebuild context every turn** — your system prompt can be dynamic. Rebuild it with fresh data on every LLM call so the response is always contextual.
- **Read the Main Flow's conversation history** — `self.worker.agent_memory.full_message_history` gives you what happened before your Ability was triggered.
- **Persist data across sessions** — using the file storage API (see the Persistence & Memory section below).

The mental model is: your Ability is a focused, self-contained session. It boots up, does its job with full capabilities, then exits cleanly. If you need something to survive between sessions, write it to a file.

### How Conversation History Works

There are two layers of conversation history to understand:

**The Personality's conversation history** is what the user sees in their chat. It includes everything spoken aloud — both by the Personality and by your Ability (via `speak()`). This history is **scoped per-Personality per-user** — each Personality maintains a separate history with each user, so a calendar Ability triggered from one Personality won't see the history from a different Personality. If the user deletes a Personality's history from the dashboard, `agent_memory.full_message_history` is also cleared — your Ability will see an empty history on the next activation.

**Your Ability's internal history** is a list you maintain yourself and pass to `text_to_text_response()`. This gives the LLM context across multiple turns within your Ability. It only exists in memory while your Ability is running — it's gone when you call `resume_normal_flow()`.

```python
# Your Ability maintains its own history list
self.history = []
self.history.append({"role": "user", "content": user_input})
response = self.capability_worker.text_to_text_response(
    user_input, history=self.history, system_prompt=self.system_prompt
)
self.history.append({"role": "assistant", "content": response})
```

One important detail: there's currently no way to inject data directly into the Personality's system prompt after your Ability finishes. When `resume_normal_flow()` fires, the Ability is done. But anything your Ability said via `speak()` does become part of the Personality's conversation history, so the Personality's LLM can reference it in later turns. For anything more structured, use file storage to persist data that your Ability can read on its next activation.

There's also no way to silently inject text into the conversation history — the only way to add to it is through `speak()`, which means the agent has to actually say it out loud. You can't write hidden context or metadata into the history behind the scenes. Conversation history is managed by a separate module tied to the normal conversation flow, so your Ability can contribute to it by speaking, but can't manipulate it directly.

---

## Choosing Good Trigger Words

Trigger words are how users activate your Ability. When someone says a phrase that matches one of your trigger words, the platform routes them from the normal Personality conversation into your Ability. Getting these right matters — too narrow and users can't find your Ability, too broad and it fires when it shouldn't.

### Think About How People Actually Talk

This sounds obvious, but it's the most common mistake. Developers pick trigger words based on how they'd *type* a command, not how someone would *say* it to a speaker across the room. Voice commands are informal, varied, and often indirect.

For a calendar Ability, users won't say "invoke calendar management system." They'll say things like "what's on my calendar," "do I have a 3pm," "schedule a meeting," or "am I free Tuesday." Your trigger words need to match that natural language.

### Balance Coverage Against False Positives

The goal is covering ~80% of how people will naturally phrase their request without accidentally triggering on unrelated conversation. Some words are safe as single-word triggers because they almost always mean one thing ("calendar", "reschedule"). Others are dangerous as single words because they have multiple meanings ("book" could mean a reading book, "free" could mean no cost, "cancel" could mean a subscription).

For risky words, use **phrase-level triggers** instead of single words. "book a time" and "book me" are much safer than bare "book."

### Example: Calendar Ability Triggers

Here's the set we settled on for our calendar Ability after testing against real voice patterns. It covers the major intent categories (viewing, creating, modifying, cancelling, availability) while avoiding common false positives:

```
calendar, schedule, meeting, meetings, appointment, appointments,
reschedule, agenda, new event, move event, book a time, book time,
book me, am I free, free on, free at, available on, availability,
cancel, how busy am, what's my day look like today,
what does my day look like, what am I doing today,
what is on my day today, what's on my day, call with
```

A few things to notice about this list:

- **Plural forms included** — "meeting" and "meetings", "appointment" and "appointments." People use both.
- **Phrase triggers for ambiguous words** — "book a time" and "book me" instead of bare "book." "am I free" and "free on" instead of bare "free."
- **Natural full-sentence triggers** — "what's my day look like today" and "what am I doing today" catch the indirect queries that don't contain any calendar-specific keyword.
- **"cancel" left as a single word** — it has some collision risk with other Abilities, but calendar cancellations are common enough that missing them hurts more than the occasional false trigger. You can disambiguate at the Ability logic level.

### Language and Syntax Considerations

Trigger words are **language-specific and syntax-dependent**. The list above is tuned for English speakers. If your Ability supports other languages, you'll need separate trigger word sets for each. Even within English, phrasing varies by region — "what's in my diary" (UK) vs "what's on my calendar" (US).

Trigger words can be edited anytime in the **Installed Abilities** section of the dashboard, so you can refine them as you learn how your users actually talk.

---

## How Abilities Work With the Main Flow

This is the architectural context that most developers miss. Your Ability doesn't run in isolation — it's called from the Personality's Main Flow when a user says a trigger word. Understanding this handoff is critical.

### The Lifecycle

1. User is in the Main Flow having a normal conversation with their Personality.
2. User says something that matches a trigger word (e.g., "what's on my calendar").
3. Main Flow activates your Ability and calls your `call()` method.
4. Your Ability takes over: speaks, listens, does its thing.
5. Your Ability calls `resume_normal_flow()` and the user is back in the Main Flow.

This means two important things. First, you can read the conversation history that happened before your Ability was triggered — the Main Flow's history is available through `self.worker.agent_memory.full_message_history`. Second, you must always hand control back with `resume_normal_flow()` or the Personality goes silent.

### Reading Trigger Context

Here's a pattern that makes a big difference. When your Ability activates, the user was already mid-conversation with the Personality. That conversation history is still there — you can read it to understand exactly what the user was asking about when they triggered your Ability.

Let's say you're building a calendar Ability. Without reading the trigger context, every activation would feel the same — maybe you always give a full schedule readout. But with the trigger context, you can respond to what the user actually said:

**User says "what's on my calendar today?"** → your Ability reads that from history → gives today's schedule, no extra fluff.

**User says "create a meeting with Sarah at 3"** → your Ability reads that → starts creating the event right away, no menus or prompts.

The core pattern: read the trigger message from conversation history, classify the intent with the LLM, then route to the right handler.

```python
trigger_context = self.get_trigger_context()  # reads last 5 user messages
intent = self.classify_trigger_intent(trigger_context)  # LLM classifies
if intent['mode'] == 'quick': await self.handle_quick_intent()
else: await self.boot_full()  # full briefing mode
```

> *The key insight: don't make every activation feel the same. Read the conversation history to understand what the user actually wants, then give them exactly that.*

### Quick Mode vs Full Mode

Let's say you're building an Ability that manages your calendar. A user might trigger it in very different ways — sometimes they just want a quick answer ("do I have a 3pm?"), and sometimes they want to sit down and go through their whole day ("catch me up on my schedule"). These are fundamentally different interactions, and they should feel different.

This is the pattern we use in our internal calendar Ability (called Smart Hub — it manages calendar, email, and Slack through voice). When the Ability activates, it classifies the trigger intent and decides which mode to run in:

| Mode | What the User Said | What Happens |
|---|---|---|
| **Quick** | "What's on my calendar?" or "Create a meeting at 3" | Answer the specific question → "Anything else?" → 4-5 sec silence → exit back to Personality |
| **Full** | "Catch me up" or "run through my day" | Full spoken briefing → open Q&A loop (ask follow-ups, modify events) → 2-3 idle cycles → sign off |

The difference is huge from the user's perspective. Without this pattern, every calendar trigger gives you a full 45-second briefing — even if you just wanted to know whether your 3pm was still on. Quick mode answers the question and gets out of the way. Full mode settles in for a longer session where the user can ask follow-ups, reschedule meetings, and add invites.

This pattern applies to any Ability that can handle both simple queries and deeper interactions. A music Ability might have quick mode ("play something chill") and full mode ("let's build a playlist"). A smart home Ability might have quick mode ("turn off the lights") and full mode ("set up my evening routine"). The trigger classification tells you which experience the user expects.

---

## Design for Voice, Not Text

This is probably the most important section. You're building voice-first experiences — your user is listening, not reading. What looks good in a chat UI often sounds terrible when spoken aloud. These are the guidelines we've found make the biggest difference, based on what we learned building the calendar Ability.

### 1. Keep It Short

Aim for 1–2 sentences per `speak()` call. If you have a lot of information, give the headline first and offer to go deeper. People can't rewind or skim a voice response — if it's too long, they just stop listening.

🔴 **Bad:** "The weather in Austin is currently 72 degrees Fahrenheit with partly cloudy skies, humidity at 45%, wind from the southeast at 8 miles per hour, and a UV index of 6 which is high so wear sunscreen."

🟢 **Good:** "It's 72 and partly cloudy in Austin. Want more details?"

This is what we call progressive disclosure — give the key fact first, then offer more. In the calendar Ability: "You have 3 meetings today. The next one is at 2 PM with Sarah. Want the full list?" The user gets the important bit right away and can choose to hear more.

### 2. Spell Out Ambiguous Stuff

Text-to-speech will mangle email addresses, URLs, and certain number formats. Format them for the ear, not the eye:

- Say "at" instead of "@" and "dot" instead of "." for emails
- Read phone numbers digit by digit
- Say "10 AM" not "10:00"

In the calendar Ability, when reading back an email address for a meeting invite, we clean it up for speech:

```python
email_spoken = email.replace("@", " at ").replace(".", " dot ")
```

### 3. Confirm Before Doing Something Major

If your Ability is about to do something that can't easily be undone — sending an email, cancelling a meeting, deleting data — it's a good idea to read back what you're about to do and get a quick confirmation. This doesn't need to be formal; just a natural check. In our calendar Ability, we do this before cancelling events or adding attendees:

```
"Cancel 'Team Standup'? Say yes to confirm."
"I'll add chris at openhome dot com to 'Design Review'. Sound good?"
```

For lower-stakes actions — like reading out a schedule or looking up information — you can skip the confirmation and just do it. Use your judgment on what warrants the extra step. The SDK has `run_confirmation_loop()` built in if you want a simple yes/no, or you can build your own with pending states (see the Multi-Turn section below).

### 4. Expect Messy Input

Voice transcription isn't perfect. Users say "um", trail off mid-sentence, or repeat themselves. Your Ability should handle this gracefully rather than failing. One approach that works well is using the LLM to extract the clean data from noisy transcription. In the calendar Ability, when a user is naming a new meeting, the raw transcription might look like this:

```python
# User said: "um, meeting with Carlos. I think I need to add a new event."
# LLM extracts just: "Meeting with Carlos"
```

If you can't parse what the user said, ask a follow-up instead of failing silently. A quick "I didn't catch that, could you say it again?" feels much better than silence or an error.

### 5. Handle Exits Gracefully

If your Ability has any kind of loop, give users a way out. People will say "done", "stop", "bye", or just trail off. It's worth checking for exit words before processing input so you don't accidentally treat "I'm done" as a query:

```python
EXIT_WORDS = ["done", "exit", "stop", "quit", "bye", "goodbye",
              "nothing else", "all good", "nope", "no thanks", "i'm good"]
```

### 6. Fill the Silence

If your API call takes more than a second or two, let the user know something is happening. Dead silence during processing feels like the conversation froze. A quick filler line goes a long way — it doesn't need to be fancy, just enough so the user knows the Ability is still working:

```python
await self.capability_worker.speak("I'm on it, give me a sec.")
await self.capability_worker.speak("Standby, checking into that.")
await self.capability_worker.speak("One sec, pulling that up.")
await self.capability_worker.speak("Let me look into that for you.")
```

In the calendar Ability, we have a pool of filler lines that rotate based on time of day — "One sec, pulling up your day" in the morning, "Let me see what's left tonight" in the evening. You don't need to go that far, but even a simple "Hang on" before a slow API call makes the experience feel alive instead of frozen.

```python
# Speak filler BEFORE the slow call, not after
await self.capability_worker.speak("One sec, checking that for you.")
data = requests.get(url, timeout=10)  # User hears filler, not silence
```

### 7. Read It Out Loud

Before you submit, try reading your `speak()` strings out loud. If it sounds robotic, too long, or awkward when spoken — rewrite it. Your user can't scan, skim, or go back and re-read.

> *A decent test: if you wouldn't say it to someone standing next to you, it probably doesn't belong in a speak() call.*

---

## Multi-Turn Conversation Patterns

A lot of Abilities need to collect information across multiple back-and-forth exchanges. Think about a calendar Ability where the user says "create a meeting" but doesn't give you a title or time. You can't just fail — you need to ask follow-up questions and remember what you're waiting for between turns.

This is the "pending state" pattern. It's one of the most useful patterns for any Ability that does more than a single request-response cycle.

### The Pending State Pattern

Track what information you're waiting for using a dictionary on your class:

```python
self.pending_create = None  # Tracks create flow

# User says "create a meeting" (no title or time given)
self.pending_create = {"waiting_for": "title"}
await self.capability_worker.speak("What should I call this meeting?")

# Next turn: user says "team standup"
self.pending_create = {"title": "Team Standup", "waiting_for": "time"}
await self.capability_worker.speak("Got it, 'Team Standup'. What time?")

# Next turn: user says "9 AM"
# We now have everything — create the event
self.pending_create = None  # Clear pending state
```

The key insight: at the top of every loop iteration, check your pending states before doing anything else. If there's a pending create, route the input to the create handler. If there's a pending invite, route to the invite handler.

### Always Allow Cancellation

At any point in a multi-turn flow, the user should be able to say "never mind" or "cancel" and bail out. In the calendar Ability, we check for cancel phrases at the top of every pending handler:

```python
if any(phrase in lower for phrase in ["never mind", "cancel", "forget it"]):
    self.pending_create = None
    return "Okay, I've cancelled that."
```

### Confirmation Before Execution

For actions that are hard to undo, consider adding a confirmation step to your pending flow. In the calendar Ability, the pending state moves through stages before executing: waiting_for "event" → waiting_for "confirm" → execute. This gives the user a chance to catch mistakes before they happen, which matters more in voice than text since there's no undo button.

---

## Using the LLM as a Router

One of the most powerful patterns in OpenHome is using the LLM to classify user intent and route to different handlers. Instead of trying to match exact keywords or regex patterns (which break constantly with voice input), you ask the LLM to classify the input and return structured JSON.

In the calendar Ability, we use this at two levels. First, when the Ability activates, we classify what triggered it — does the user want to read their schedule, create an event, invite someone? Then inside the session loop, we classify each follow-up message to decide if it's a new calendar action or just a conversational question.

### The Pattern

```python
def classify_intent(self, user_input: str) -> dict:
    prompt = (
        "Classify this user input. Return ONLY valid JSON.\n"
        '{"intent": "read|create|modify|cancel", "details": {...}}\n'
        f"User: {user_input}"
    )
    raw = self.capability_worker.text_to_text_response(prompt)  # No await!
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return {"intent": "unknown"}
```

Always strip markdown fences from LLM output before parsing JSON. LLMs love wrapping JSON in ` ```json ` blocks.

### Inject Context Into Your Prompts

The more context you give the LLM, the more natural its responses sound. In the calendar Ability, the system prompt includes the user's name, location, local time, and the day of the week — so the LLM can say things like "Busy afternoon ahead" instead of generic responses:

```python
system_prompt = f"""You are a concise voice assistant for calendar management.
USER: {user_name} | LOCATION: {city} | TIME: {current_time}
Rules: Keep responses to 2-4 sentences max. Be conversational."""
```

The more context you inject into the system prompt, the more natural and useful the responses will be.

---

## Working with External APIs

Most Abilities involve calling an external API. Here's the practical guidance beyond "just use requests".

### Always Set Timeouts

Without a timeout, a slow API hangs the voice interaction indefinitely. The user hears nothing and thinks the system crashed.

```python
response = requests.get(url, timeout=10)
```

### Wrap Long Calls in asyncio.to_thread()

The requests library is blocking. For API calls that might take more than a second or two, wrap them:

```python
resp = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
```

### Validate Everything

APIs return unexpected things. Check status codes, handle empty responses, and validate JSON structure before accessing nested keys. In the calendar Ability, every API call checks for success before trying to use the data:

```python
if resp.status_code == 404:
    return None
if data.get("successful") and data.get("data"):
    return data["data"]
else:
    self.log_err(f"API error: {json.dumps(data)[:300]}")
    return None
```

### API Key Management

Include placeholder constants with clear comments:

```python
# Replace with your own API key from https://example.com/api
API_KEY = "your_api_key_here"
```

---

## Persistence & Memory

As we covered in the runtime section, everything in your Ability's memory disappears when the session ends. For a lot of Abilities, that's fine — a weather check doesn't need to remember anything. But for anything that should feel like it "knows" the user over time, you need persistence.

This is what the file storage API is for. It lets you save data that survives across sessions, so the next time the user triggers your Ability, you can pick up where you left off.

### Why This Matters

Without persistence, every session is a blank slate. The user has to re-explain their preferences, re-enter their name, re-configure everything. That feels broken for anything meant to be used regularly.

With persistence, you can build Abilities that:

- **Remember the user's name and preferences** — so the second session feels like a continuation, not a restart
- **Track progress over time** — quiz scores, journal entries, workout logs, habit streaks
- **Detect first-run vs returning user** — show an onboarding flow the first time, skip it after that
- **Share data between Abilities** — files are stored at the user level, not per-Ability, so an onboarding Ability can save preferences that a completely different Ability reads later

### The File Storage API

Four methods, all on `self.capability_worker`:

| Method | What It Does |
|---|---|
| `await check_if_file_exists(filename, temp)` | Returns `True`/`False`. Use before reading to avoid errors. |
| `await write_file(filename, content, temp)` | Writes content to file. **Appends** if the file already exists. |
| `await read_file(filename, temp)` | Returns the file content as a string. |
| `await delete_file(filename, temp)` | Deletes the file. |

The `temp` flag controls persistence:
- `temp=False` — **Persistent.** Data lives on the server and survives across sessions. Use for anything the user would expect to be remembered.
- `temp=True` — **Session-only.** Auto-deleted when the session ends. Use for caching API responses or temporary working data.

Allowed file types: `.txt`, `.csv`, `.json`, `.md`, `.log`, `.yaml`, `.yml`

### The JSON Gotcha

`write_file` **appends** to existing files. This is great for logs and text files, but it will corrupt JSON:

```python
# ⚠️ BAD — this produces: {"name":"Chris"}{"name":"Mike"} (invalid JSON)
await self.capability_worker.write_file("prefs.json", json.dumps(new_prefs), False)

# ✅ GOOD — delete first, then write fresh
await self.capability_worker.delete_file("prefs.json", False)
await self.capability_worker.write_file("prefs.json", json.dumps(new_prefs), False)
```

Always delete then write for JSON files. For `.txt` or `.log` files where you're appending lines, the default behavior works perfectly.

### Pattern: First-Run Detection

This is one of the most useful persistence patterns. Check if a file exists to determine whether the user has used your Ability before:

```python
async def boot(self):
    if await self.capability_worker.check_if_file_exists("user_prefs.json", False):
        # Returning user — load their preferences
        raw = await self.capability_worker.read_file("user_prefs.json", False)
        self.user_prefs = json.loads(raw)
        await self.capability_worker.speak(f"Welcome back, {self.user_prefs['name']}.")
    else:
        # First run — collect preferences
        self.user_prefs = await self.run_onboarding()
        await self.capability_worker.delete_file("user_prefs.json", False)
        await self.capability_worker.write_file(
            "user_prefs.json", json.dumps(self.user_prefs), False
        )
```

### Pattern: Activity Logging

For journals, workout trackers, or anything that accumulates entries over time, the append behavior of `write_file` is exactly what you want:

```python
entry = f"\n{timestamp}: {user_input}"
await self.capability_worker.write_file("journal.txt", entry, False)
```

Each session just appends new entries. No need to read-modify-write.

### Pattern: Session Cache

Use `temp=True` for data you only need during the current session — like caching an API response so you don't re-fetch it every time the user asks a follow-up:

```python
# Cache the calendar data for this session
await self.capability_worker.write_file(
    "cal_cache.json", json.dumps(calendar_data), True  # temp=True
)
```

### Important: Files Are User-Level, Not Ability-Level

Files are scoped to the user, not to your specific Ability. This means if your Ability writes a file called `prefs.json`, any other Ability running for that same user can read it. This is powerful for sharing context — but it also means you should namespace your filenames to avoid collisions:

```python
# Good — namespaced to your ability
"smarthub_prefs.json"
"quiz_scores.json"

# Risky — generic name might collide with another ability
"data.json"
"config.json"
```

---

## Smart Exit Behavior

How your Ability exits matters as much as how it enters. The exit should feel natural, not abrupt or lingering.

### Quick Mode Exit

Answer the question, offer a brief follow-up window, then leave without fanfare. The calendar Ability's quick mode says "Let me know if you have any other questions about your calendar," waits 4–5 seconds for a response, and if the user says nothing (or says "thanks"), it exits silently back to the Personality. No sign-off message needed — the user barely noticed the handoff.

### Full Session Exit

For longer sessions where the user has been going back and forth for a while, a proper sign-off feels right. The calendar Ability detects exit words and generates a contextual goodbye through the LLM, so it feels natural rather than robotic.

### Idle Detection

For full sessions, keep track of how many consecutive empty responses you get. One idle cycle is normal — maybe they're thinking. Two in a row, offer to sign off. The calendar Ability does it like this:

```python
idle_count += 1
if idle_count >= 2:
    await self.capability_worker.speak(
        "I'm still here if you need anything. Otherwise I'll sign off."
    )
```

One idle cycle = keep going. Two = offer to leave. This feels natural and not pushy.

### Don't Forget resume_normal_flow()

No matter how your Ability exits, `resume_normal_flow()` needs to be called. This is the #1 bug we see in Abilities. Walk through every path your code can take — happy path, break statements, except blocks, timeouts, user exits — and make sure each one calls it.

---

## Code Quality Checklist

Before submitting an Ability, run through this list:

| | Check |
|---|---|
| ☐ | `resume_normal_flow()` called on EVERY exit path (happy path, breaks, except blocks, timeouts, user exit) |
| ☐ | No `print()` statements — using `editor_logging_handler` for all logging |
| ☐ | No raw `asyncio.sleep()` or `asyncio.create_task()` — using `session_tasks` |
| ☐ | All API calls wrapped in try/except with spoken error messages |
| ☐ | All `requests` calls include `timeout=10` or similar |
| ☐ | Exit word detection in any looping Ability |
| ☐ | `speak()` strings are short (1–2 sentences) and sound natural read aloud |
| ☐ | `text_to_text_response()` used without `await` (it's the only synchronous SDK method) |
| ☐ | JSON persistence uses delete + write pattern (never append to JSON files) |
| ☐ | `check_if_file_exists()` called before `read_file()` to avoid errors |
| ☐ | File names are namespaced to your Ability (e.g., `smarthub_prefs.json` not `data.json`) |
| ☐ | Destructive or high-stakes actions (send, delete, cancel) use confirmation before executing |
| ☐ | Multi-turn flows allow cancellation at any point ("never mind", "cancel") |
| ☐ | Filler speech ("One sec") plays before any API call that takes > 1 second |
| ☐ | API keys are placeholder constants with comments, not hardcoded real keys |
| ☐ | No blocked imports (redis, connection_manager, user_config, open()) |

---

## Putting It All Together

The anatomy of a great Ability:

1. It does something the LLM can't do on its own — calls an API, plays audio, controls a device, or persists data. If it can be handled with a Personality prompt, it doesn't need to be an Ability.
2. It understands the runtime model — on-demand, stateless, no background processing. Design around trigger → respond → exit.
3. Its trigger words match how people actually talk — natural phrases, plural forms, phrase-level triggers for ambiguous words, tested against false positives.
4. It reads the trigger context to understand what the user actually wanted, not just that a trigger word was said.
5. It's designed for voice first — short responses, spoken error handling, filler speech during loading, confirmation loops, exit detection.
6. It handles multi-turn flows gracefully — pending states, cancellation at any point, clear follow-up questions for missing info.
7. It uses the LLM as a router — classify intent with JSON output, inject context into system prompts, strip markdown fences.
8. It persists what matters — file storage for cross-session memory, first-run detection, user preferences, activity logs.
9. It exits cleanly — quick mode exits silently, full mode signs off, `resume_normal_flow()` fires on every path.
10. It's clean and portable — no hardcoded keys, no blocked imports, proper error handling with spoken errors.

> *Build Abilities that make the Personality feel like it can reach out and touch the real world. That's the whole point.*

Questions? Drop them in **#dev-help** on Discord.
