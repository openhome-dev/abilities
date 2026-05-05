# Private Notes Spec

## Goal

`private-notes` is a voice-first personal note-taking agent for OpenHome.

- save a note
- read one or more notes
- search notes by topic
- overwrite a specific note
- delete one or more notes

---

## Core Principles

1. Notes are private user data stored in JSON.
2. The LLM picks which tool to call. Python executes it.
3. Tool execution is id-based, not title-based.
4. Voice responses are short and natural.
5. Titles and confirmations should sound like a person helping, not a tool exposing internals.
6. No open-ended agent loop. Capped at 4 turns.

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
    write/read/search/delete -> execute in Python, history += user: result, continue
```

One system prompt. One conversation via `history`. `finish` is a tool like any other. The LLM selects the note ids for destructive actions; Python builds the spoken confirmation question so safety copy stays consistent.

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

Malformed storage is treated as unsafe. The ability refuses to change notes if `private_notes.json` is not valid JSON or does not match the expected notebook shape.

---

## Tools

### `write_note`

```json
{"name": "write_note", "arguments": {"note_id": null, "title": "string", "content": "string"}}
```

- `note_id = null` creates a new note (no confirmation needed).
- `note_id = <uuid>` overwrites an existing note. Python asks the confirmation prompt.
- Empty note content is rejected without writing.
- Titles are normalized before saving by trimming quotes and whitespace, but Python does not rewrite semantic phrasing.
- If `note_id` does not exist, Python returns an error result instead of crashing the ability.

### `read_notes`

```json
{"name": "read_notes", "arguments": {"note_ids": ["uuid"]}}
```

- `note_ids` is always an array, even for one note.
- Readback capped to 3 notes.
- Returns raw note data (title, content, updated_at). LLM formats for speech via `finish`.
- If no ids match, Python returns an error result instead of an empty successful read.

### `search_notes`

```json
{"name": "search_notes", "arguments": {"query": "string"}}
```

- Searches title and content in Python.
- Used when the user asks for notes about a topic and the note index alone is not enough.
- Returns up to 3 matching notes, sorted by most recently updated.
- If no notes match, Python returns an error result instead of exposing unrelated note contents.

### `delete_notes`

```json
{"name": "delete_notes", "arguments": {"note_ids": ["uuid"]}}
```

- `note_ids` is always an array, even for one note.
- Python asks a count-based confirmation prompt like `Delete 2 matching private notes`. Always confirmed before deleting.
- Confirmation prompts can stay short because the SDK confirmation loop appends its own yes/no instruction.
- If no ids match, Python returns an error result and does not ask for confirmation.

### `ask_followup`

```json
{"name": "ask_followup", "arguments": {"question": "string"}}
```

- Used when the request is ambiguous.
- Not used after a tool result. The next step after a tool result is `finish`.
- Not used for delete or overwrite confirmation. For destructive actions, the LLM calls the mutation tool and Python asks the confirmation question.

### `finish`

```json
{"name": "finish", "arguments": {"response": "string"}}
```

- Spoken response to the user. Ends the loop.
- If the previous tool result has `ok: false`, the response should say nothing changed and briefly explain why.

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
2. Overwrite requires confirmation (Python builds the prompt and uses the SDK confirmation loop).
3. Delete requires confirmation (Python builds the prompt and uses the SDK confirmation loop).
4. Full note bodies are not included in the initial LLM prompt; Python returns note content only for selected reads/searches.
5. Generated titles are normalized at the Python boundary before saving, but semantic title quality belongs to the LLM contract.
6. JSON saves safely overwrite by deleting any existing file before writing because `write_file()` appends to existing files.
7. Malformed stored note data is not overwritten by a new empty notebook.
8. The loop is capped at 4 turns.

---

## Validation

```
python3 -m py_compile community/private-notes/main.py
python3 validate_ability.py community/private-notes
```
