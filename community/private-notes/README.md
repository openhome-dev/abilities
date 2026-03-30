# Private Notes Ability

A voice-first note-taking Ability for OpenHome that keeps notes private by design. Notes are stored as `.json` (not `.md`), so the Memory Watcher never picks them up and the Personality never surfaces them unprompted.

## Trigger Words

```
note, notes, take a note, note this down, read my notes,
delete my notes, my notes, edit my note, update my note,
change my note, fix my note
```

These can be edited anytime in the **Installed Abilities** section of the dashboard.

## Commands

### Create a Note

Say "take a note" followed by the content, or just "take a note" and dictate when prompted. Raw voice input is cleaned up by the LLM (filler words removed, punctuation fixed) before saving.

**Examples:**
- "Take a note buy milk tomorrow" — saves immediately, no follow-up prompt
- "Take a note" → "Buy milk tomorrow" — prompts you, then saves
- "Note this down I need to call mom" — saves immediately

### Read Notes

Say "read my notes" with an optional filter. Notes are read back with friendly relative timestamps ("3 minutes ago", "Yesterday", "Tuesday"). If there are more than 10 notes, the Ability pauses and asks whether to continue. Compound filtering is supported.
**Filters:**
- `all` (default) — "Read my notes"
- `last` — "Read my last note"
- `today` — "Read my notes from today"
- `keyword` — "Read my notes about milk", "Read my notes on groceries"

### Edit a Note

Say "edit my note" with an optional filter to identify which note. The Ability reads back the current content and asks what it should say instead. The replacement is cleaned through the same dictation cleanup. Defaults to editing the most recent note if no filter is given. When multiple notes match a keyword, the most recent match is edited.

**Examples:**
- "Edit my last note"
- "Update the note about milk"
- "Change my note from 5 minutes ago"
- "Fix the note about groceries"

### Delete Notes

Say "delete my notes" with a filter. All deletions require voice confirmation ("Say yes to confirm") before executing.

**Filters:**
- `all` — "Delete all my notes" (warns it can't be undone)
- `last` — "Delete my last note"
- `today` — "Delete my notes from today"
- `keyword` — "Delete the note about milk", "Remove the note about the meeting"
- `time` — "Delete the note from 5 minutes ago"

## Architecture

### Intent Classification

The Ability uses a two-tier classification system:

1. **Fast path** — keyword matching handles common, unambiguous phrases ("read my notes", "take a note buy milk") with zero LLM latency. Filters like "about X", "on X", "from X", "last", and "today" are parsed directly from the utterance.
2. **Slow path** — an LLM call classifies ambiguous inputs and extracts structured intent as JSON. Only used when the fast path doesn't match.

### Trigger Context Retrieval

The live transcription triggers the Ability, but the STT system doesn't finalize the transcription into conversation history until after the Ability produces audio output. To handle this:

1. The last user message in history is snapshotted as "stale" on startup.
2. A short filler ("One sec.") is spoken, which forces STT finalization.
3. History is polled until a new message appears that differs from the stale snapshot.

### Storage

Notes are stored in `private_notes.json` using the persistent file storage API (`temp=False`). The `.json` extension ensures the Memory Watcher ignores the file, keeping notes private from the Personality's system prompt.

Each note is a JSON object:

```json
{
  "id": "note_1774727982040",
  "content": "Buy a liter of milk",
  "created_at_iso": "2026-03-26T14:33:02.040000",
  "created_at_epoch": 1774727982,
  "timezone": "America/Los_Angeles",
  "human_time": "02:33 PM on Thursday, Mar 26, 2026",
  "edited_at_iso": "2026-03-26T15:01:00.000000"
}
```

The `edited_at_iso` field is only present on notes that have been edited.

JSON files are always saved using the delete-then-write pattern to avoid a `write_file` append corruption issue.