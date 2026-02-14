# Voice Journal

A persistent voice journal ability for OpenHome. Dictate journal entries by voice, review past entries, search by topic, and manage your journal — all hands-free. Showcases the persistent file storage API.

## Features

- **Add entries** — dictate thoughts, LLM cleans up transcription, reads back for confirmation before saving
- **Conversational journaling** — say "let's talk" to enter a multi-turn Q&A mode where the LLM asks follow-up questions, then merges the exchange into one rich entry
- **Guided prompts** — say "prompt me" when you don't know what to write and get a rotating journal prompt for inspiration
- **Edit entries** — say "edit an entry" to pick an entry by number, re-dictate it, and replace it in your journal (timestamp preserved)
- **Read entries** — today's, recent (last 5), or all with progressive disclosure and LLM summaries
- **Search entries** — LLM-powered semantic search across your journal
- **Delete entries** — clear your journal with confirmation safeguard
- **Help command** — say "help" anytime for a command reminder
- **Persistent storage** — entries and preferences survive across sessions
- **First-run onboarding** — asks your name (LLM-extracted), explains commands
- **Returning user greeting** — welcomes you back with synced entry count
- **Inline entries** — say "add to journal: had a great day" to save in one shot
- **Voice-friendly formatting** — timestamps read as "On January 15 at 2:30 PM"
- **Idle detection** — auto-exits after 2 consecutive empty responses

## Trigger Words

`journal`, `diary`, `write in my journal`, `journal entry`, `open my journal`, `add to journal`, `read my journal`, `voice journal`, `dear diary`, `daily journal`, `edit my journal`, `edit journal entry`, `change journal entry`, `let's talk journal`, `journal prompt`

## Voice Commands

| Command | Keywords |
|---------|----------|
| Add entry | write, add, new, record, save, log, note, jot |
| Read entries | read, review, hear, listen, show, tell me, entries |
| Search | search, find, look for, about, mention |
| Edit entry | edit, change, modify, update, fix, correct, revise |
| Delete all | delete, remove, clear, erase, wipe |
| Help | help, commands, options, what can |
| Exit | stop, done, bye, goodbye, cancel, leave, nah, nothing else |

### Add Entry Sub-commands

When prompted "What's on your mind?", you can also say:

| Trigger | Effect |
|---------|--------|
| "prompt me", "inspire me", "give me a prompt" | Get a random journaling prompt for inspiration |
| "let's talk", "ask me questions", "deep dive" | Start a conversational journaling session (3 rounds of Q&A merged into one entry) |

## Storage

- `voice_journal_entries.txt` — append-only log, one entry per line as `YYYY-MM-DD HH:MM | <text>`
- `voice_journal_prefs.json` — user name and entry count (uses delete+write pattern for JSON safety)

Entry count is synced with the actual file on each boot to prevent drift.

## Quick Start

1. Install to your OpenHome Personality
2. Say "open my journal"
3. Complete the onboarding (first time only)
4. Say "add an entry" to start journaling
5. Say "prompt me" for inspiration or "let's talk" for deeper reflection
6. Say "edit an entry" to fix a past entry
7. Say "read my journal" to hear past entries
8. Say "done" to exit

## Testing

```bash
cd voice-journal
python3 -m unittest test_voice_journal -v
```

78 tests cover: intent classification (including edit keywords), inline extraction, entry formatting, onboarding, returning user boot, add/read/search/edit/delete flows, guided prompts, conversational journaling, clean-confirm-save helper, exit/idle handling, help, resume_normal_flow guarantees, edge cases (corrupted prefs, missing files, max turns).
