# Basic Advisor

![Official](https://img.shields.io/badge/OpenHome-Official-blue?style=flat-square)

A simple daily life advisor that listens to your problem, generates advice using the LLM, and asks for your feedback.

## Trigger Words

- "give me advice"
- "help me out"
- "I need advice"
- "daily advisor"

## Setup

No setup required. No external APIs needed.

## How It Works

1. User triggers the Ability with a hotword
2. Advisor introduces itself and asks for a problem
3. User describes their problem
4. LLM generates a 1-2 sentence solution
5. Advisor speaks the solution and asks for feedback
6. User responds, advisor thanks them and exits

## Key SDK Functions Used

- `speak()` — Text-to-speech output
- `user_response()` — Listen for user input
- `text_to_text_response()` — LLM text generation
- `run_io_loop()` — Speak + listen in one call
- `resume_normal_flow()` — Return to Personality

## Example Conversation

> **User:** "Give me advice"
> **AI:** "Hi! I'm your daily life advisor. Tell me about a problem you're facing."
> **User:** "I can't sleep at night"
> **AI:** "Try establishing a consistent bedtime routine and avoid screens an hour before sleep. Are you satisfied with the advice?"
> **User:** "Yes, thanks"
> **AI:** "Thank you for using the daily life advisor. Goodbye!"
