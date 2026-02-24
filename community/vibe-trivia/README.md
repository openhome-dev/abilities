# Vibe-trivia Ability

A voice-first trivia game with category selection, multi-question rounds, answer grading, and persistent best-score tracking.

---

## Features

- Category-based trivia (or random/general knowledge mode)
- Configurable question count (1-10; defaults to 3 when unclear)
- Multiple-choice question flow (A/B/C/D)
- Flexible answer parsing:
  - letter answers (`A`, `B`, etc.)
  - spoken option text matching
  - LLM fallback grading for ambiguous answers
- Trigger-echo protection for cleaner first-turn behavior
- Exit word handling (`stop`, `exit`, `quit`, etc.)
- Persistent best score storage across sessions

---

## Requirements

- Python 3.8+
- OpenHome runtime (`src.agent`, `src.main`)
- No external API keys required

---

## Installation

1. Place this folder under `community/vibe-trivia/`.
2. Ensure `config.json` exists alongside `main.py` with `unique_name` and `matching_hotwords`.
3. Install/enable the Ability in the OpenHome dashboard and set trigger words if needed.

---

## How It Works

### Activation

The ability is activated via configured hotwords (for example: `start vibe trivia`, `trivia time`, `quiz me`).

### Conversation Flow

```
User triggers ability
        │
        ▼
Ask category (or random)
        │
        ▼
Ask number of questions (1-10)
        │
        ▼
Confirm start
        │
        ▼
Generate quiz questions via LLM (JSON array)
        │
        ▼
Ask each question, grade answer, keep score
        │
        ▼
Read final score + update best score file
        │
        ▼
resume_normal_flow()
```

### Question Generation and Grading

- Questions are generated with `text_to_text_response()` using a strict JSON prompt.
- Returned JSON is cleaned and validated before use.
- Answer grading order:
  1. detect direct letter (`A/B/C/D`)
  2. match spoken answer text to options
  3. fallback LLM yes/no grading if needed

---

## APIs Used

### OpenHome LLM (built-in)

- Used for question generation and ambiguous answer judging.
- No external API integration and no hardcoded keys in this Ability.

### OpenHome File Storage (built-in)

- Best score persisted in `vibe_trivia_best_score.json`.
- Uses:
  - `check_if_file_exists(...)`
  - `read_file(...)`
  - `write_file(...)`

---

## Trigger Words

Recommended triggers (from `config.json`):

- `start vibe trivia`
- `vibe trivia`
- `trivia time`
- `quiz me`
- `play trivia`
- `start a quiz`

---

## Persistence

Best score is stored per user in:

- `vibe_trivia_best_score.json`

The ability compares current score percentage vs previous best and announces whether a new best score was achieved.

---

## Exit Words

Users can end at any time with:

> `stop`, `exit`, `quit`, `cancel`, `done`, `bye`, `goodbye`

---

## Logging

Logs are written via `worker.editor_logging_handler` with `[VibeTrivia]` prefixes for:

- generation/parse failures
- retry attempts
- persistence read/write errors

---

## Notes

- Designed for short spoken prompts and robust STT handling.
- Uses `session_tasks` patterns and calls `resume_normal_flow()` on exit paths.
