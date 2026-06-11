# Spelling Bee Coach

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@rawqubit-lightgrey?style=flat-square)

## What It Does

An interactive voice spelling practice coach with three difficulty levels, spaced repetition for tricky words, and persistent progress tracking across sessions. Words you get wrong come back more often. Words you master get retired.

## Suggested Trigger Words

- "spelling bee"
- "practice spelling"
- "spell words"
- "spelling practice"
- "quiz me on spelling"
- "vocabulary practice"

## Setup

No API keys required. Uses the built-in LLM for definitions and spelling extraction.

## How It Works

1. Choose difficulty: **Easy**, **Medium**, or **Hard**
2. Hear a word + its definition + example sentence
3. Spell it out loud, letter by letter
4. LLM extracts letters from your voice (handles "double-u", "ay", "see", etc.)
5. Get instant feedback — correct answer or hear the correct spelling
6. **Spaced repetition** — wrong answers resurface 40% of the time
7. Progress updates every 5 words
8. Session summary with accuracy and words to practice

## Features

| Feature | Description |
|---------|-------------|
| 3 difficulty levels | 20 words each: easy, medium, hard |
| LLM word generation | Fresh words generated once you master the built-in list |
| Spaced repetition | Weak words resurface more often |
| Mastery tracking | Words "mastered" after 3 correct answers in a row |
| LLM spelling extraction | Handles phonetic letter names from voice |
| Definitions | Each word comes with a definition and example |
| Persistent progress | Track total accuracy and mastered words across sessions |

## Example Conversation

> **User:** "Spelling bee"
> **AI:** "Welcome back! You've practiced 23 words with 78% accuracy. 15 words mastered."
> **AI:** "What difficulty? Easy, medium, or hard?"
> **User:** "Hard"
> **AI:** "Your word is: silhouette. A silhouette is a dark outline of something against a lighter background. 'The silhouette of the mountains was visible at sunset.' Spell silhouette."
> **User:** "S, I, L, H, O, U, E, T, T, E"
> **AI:** "Correct! Nailed it!"
> **AI:** "Your word is: bureaucracy..."
> **User:** "B, U, R, E, A, U, C, R, A, S, Y"
> **AI:** "Not quite. The correct spelling is: B, U, R, E, A, U, C, R, A, C, Y. We'll practice that one again."
> **User:** "Done"
> **AI:** "Session over! You got 4 out of 5 — 80%. Words to practice: bureaucracy. Total mastered: 16."

## Data Files

- `spelling_bee_progress.json` — mastered words, weak words, per-word correct streaks, accuracy stats
