# Food & Water Log

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@samsonadmasu-lightgrey?style=flat-square)

## What It Does

A voice-powered food and water intake tracker that persists across sessions. Log meals and water hands-free, review today's intake, get weekly summaries — all saved to persistent storage so your data survives between conversations. The LLM classifies natural speech so you can say things like "I had eggs for breakfast" or "drank 2 glasses of water" naturally.

**Why this needs to be an Ability:** The LLM can't persist data across sessions on its own. This Ability uses the File Storage API to save and recall your food and water log over time — something the Personality alone cannot do.

## Suggested Trigger Words

- "food log"
- "water log"
- "log my food"
- "log my water"
- "what did I eat"
- "track my food"
- "track my water"
- "food tracker"
- "meal log"
- "hydration"

## Setup

No API keys or external services required. Uses only the built-in LLM and persistent file storage.

## How It Works

1. User triggers the ability with a hotword (e.g., "food log")
2. Ability loads persistent data from `oh_food_water_log.json`
3. Returning users see today's summary; first-time users get a welcome prompt
4. User speaks naturally — the LLM classifies intent and extracts data
5. Entries are saved to persistent storage immediately
6. User can log more, read back entries, get summaries, or say "done" to exit

### Supported Commands (via natural language)

| Intent | Example Phrases |
|---|---|
| Log food | "I had eggs and toast", "pizza for lunch", "coffee and a bagel" |
| Log water | "drank a glass of water", "2 glasses of water", "had some water" |
| Read today's food | "what did I eat today", "show my meals" |
| Read today's water | "how much water did I drink", "water count" |
| Read full log | "read my log", "what did I have today" |
| Weekly summary | "weekly summary", "how was my week" |
| Clear today | "clear today" (with voice confirmation) |

## Example Conversation

> **User:** "food log"
> **AI:** "Food and water log is open. Tell me what you ate or drank, or ask what you've had today."
> **User:** "I had eggs and toast for breakfast"
> **AI:** "Logged eggs and toast for breakfast. That's 1 meal today."
> **User:** "drank 2 glasses of water"
> **AI:** "Logged 2 glasses of water. Total today: 2 glasses."
> **User:** "coffee and a muffin"
> **AI:** "Logged coffee and a muffin. That's 2 meals today."
> **User:** "what did I eat today"
> **AI:** "Today's food: eggs and toast for breakfast, coffee and a muffin. 2 entries total."
> **User:** "how much water"
> **AI:** "You've had 2 glasses of water today."
> **User:** "done"
> **AI:** "Log closed. Stay hydrated!"

**Next session:**
> **User:** "food log"
> **AI:** "Welcome back! Today you've logged 2 meals and 2 glasses of water. What would you like to add?"

## Key SDK Functions Used

| SDK Method | Purpose |
|---|---|
| `speak()` | Voice output to user |
| `user_response()` | Listen for voice input |
| `text_to_text_response()` | LLM intent classification with system prompt |
| `run_confirmation_loop()` | Yes/no confirmation before clearing entries |
| `check_if_file_exists()` | First-run detection |
| `read_file()` | Load persistent log data |
| `write_file()` | Save log data (with delete-first pattern for JSON) |
| `delete_file()` | Clear old JSON before writing updated data |
| `resume_normal_flow()` | Return to Personality (in try/finally) |
| `editor_logging_handler` | All logging (no print statements) |

## Architecture

- **LLM as intent router** — classifies natural speech into structured JSON intents
- **Persistent file storage** — `oh_food_water_log.json` survives across sessions
- **Delete + write pattern** — prevents JSON corruption from append behavior
- **Namespaced file** — prefixed with `oh_` to avoid collisions with other abilities
- **First-run vs returning user** — greeting adapts based on existing data
- **Idle detection** — 2 consecutive empty inputs triggers graceful exit offer
- **Voice confirmation** — clearing entries requires spoken yes/no
- **try/finally** — guarantees `resume_normal_flow()` on every exit path
