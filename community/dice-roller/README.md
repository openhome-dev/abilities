# Dice Roller

## Overview
A voice-activated tabletop dice roller with dramatic flair. Supports all standard RPG dice (D4, D6, D8, D10, D12, D20, D100) and multi-die notation like "2d6" or "3d8". Reacts to critical hits and critical fails with LLM-generated commentary.

## Core Features
- **Trigger Words:** "Roll a die," "Roll dice," "Roll a d20," "Roll d20," "Dice roll," "Roll the dice," "Nat 20"
- **All Standard Dice:** D4, D6, D8, D10, D12, D20, D100
- **Multi-Die Support:** Parses notation like "2d6", "3d20" (capped at 10 dice)
- **Critical Reactions:** Special dramatic LLM reactions for natural 20 and natural 1 on D20
- **Contextual Reactions:** Encouraging for high rolls, sympathetic for low rolls

## Technical Implementation
Uses Python's `random.randint()` for fair rolls. Parses die notation from natural language using string splitting. LLM reactions via `text_to_text_response()` with context-aware prompts based on roll result. Loops until user says an exit word.

## How Users Interact
Say a trigger phrase to start. Tell ARI what to roll ("d20", "2d6", "d100") or just say "roll" for the default D20. ARI announces the result with a dramatic reaction. Say "roll again" to keep going or "stop" to exit.

## Dependencies
- No external APIs or setup required
- Uses only Python standard library (`random`, `json`, `os`)
