# Private Notes

`Private Notes` is a voice-first note-taking agent for OpenHome. It stores notes in persistent `private_notes.json`, so note contents stay out of the Personality prompt and are only spoken when the user explicitly asks.

## What It Does

- saves a new note
- reads one or more notes
- searches notes by topic without putting every note body in the initial LLM prompt
- overwrites a specific note after confirmation
- deletes one or more notes after confirmation

The ability uses a single LLM tool loop with conversation history. Python owns all note reads and writes.

## Example Phrases

- `take a note`
- `note this down: call Sarah after lunch`
- `read my notes`
- `read my last note`
- `what did I write about passports?`
- `update my grocery note`
- `delete my last note`
- `delete my notes`

## Storage

- File: `private_notes.json`
- Persistence: `temp=False`
- JSON saves safely overwrite by deleting any existing file before writing because `write_file()` appends by default
- malformed note storage is not overwritten; the ability stops before changing notes
- No `.md` files are written, so the Memory Watcher does not inject note contents into the Personality prompt

## Voice UX

- if no request is captured, the ability asks what the user wants to do
- reads are capped to the 3 most recent matches to avoid long voice dumps
- overwrite and delete actions always require confirmation
- destructive confirmations use the SDK confirmation loop, with Python building short prompts like `Overwrite note titled Travel Prep` or `Delete 2 matching private notes`
- note titles are expected to be clean noun phrases from the LLM; Python only trims surrounding quotes and whitespace
- final responses stay short, warm, and conversational

## Suggested Trigger Words

Configure these in the OpenHome dashboard:

- `private note`
- `private notes`
- `take a note`
- `note this down`
- `write this down`
- `read my notes`
- `delete my notes`
