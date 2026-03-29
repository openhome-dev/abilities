# Private Notes Spec

## Goal

`private-notes` is a voice-first personal note-taking agent for OpenHome.

- save a note
- read one or more notes
- overwrite a specific note
- delete one or more notes

---

## Core Principles

1. Notes are private user data stored in JSON.
2. The LLM picks which tool to call. Python executes it.
3. Tool execution is id-based, not title-based.
4. Voice responses are short and natural.
5. No open-ended agent loop. Capped at 4 turns.

---

## Architecture

A uniform tool loop with one system prompt and conversation history:

```text
history = [user: initial context]

while turns remain:
    tool_call = LLM(history, SYSTEM_PROMPT)
    history += assistant: tool_call

    finish       -> speak response, stop
    ask_followup -> speak question, history += user: answer, continue
    write/read/delete -> execute in Python, history += user: result, continue
```

One system prompt. One conversation via `history`. `finish` is a tool like any other. The LLM writes confirmation messages for destructive actions.

---

## Data Model

### Note

```json
{
  "id": "uuid",
  "title": "string",
  "content": "string",
  "created_at": "ISO timestamp",
  "updated_at": "ISO timestamp"
}
```

### Store

```json
{
  "schema_version": 2,
  "notes": [Note]
}
```

Persistent storage lives in `private_notes.json`.

---

## Tools

### `write_note`

```json
{"name": "write_note", "arguments": {"note_id": null, "title": "string", "content": "string", "confirmation": "string or null"}}
```

- `note_id = null` creates a new note (no confirmation needed).
- `note_id = <uuid>` overwrites an existing note. LLM provides the `confirmation` prompt.
- If `note_id` does not exist, Python returns an error result instead of crashing the ability.

### `read_notes`

```json
{"name": "read_notes", "arguments": {"note_ids": ["uuid"]}}
```

- Readback capped to 3 notes.
- Returns raw note data (title, content, updated_at). LLM formats for speech via `finish`.

### `delete_notes`

```json
{"name": "delete_notes", "arguments": {"note_ids": ["uuid"], "confirmation": "string"}}
```

- LLM provides the `confirmation` prompt. Always confirmed before deleting.

### `ask_followup`

```json
{"name": "ask_followup", "arguments": {"question": "string"}}
```

- Used when the request is ambiguous.

### `finish`

```json
{"name": "finish", "arguments": {"response": "string"}}
```

- Spoken response to the user. Ends the loop.

---

## Context

The first message in history contains:

1. Current local time (captured once for caching)
2. User request
3. Minimal note index: id, title, updated_at for each note (sorted by recency)

Subsequent turns append tool results and follow-up answers as history entries. The LLM resolves "my latest note" to the first id in the index.

---

## Safety Rules

1. Python executes all note mutations, not the LLM.
2. Overwrite requires confirmation (LLM writes the prompt).
3. Delete requires confirmation (LLM writes the prompt).
4. JSON saves safely overwrite by deleting any existing file before writing because `write_file()` appends to existing files.
5. The loop is capped at 4 turns.

---

## Validation

```
python3 -m py_compile community/private-notes/main.py
python3 validate_ability.py community/private-notes
```
