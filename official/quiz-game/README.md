# Quiz Game

![Official](https://img.shields.io/badge/OpenHome-Official-blue?style=flat-square)

An AI-generated trivia quiz. The LLM creates multiple-choice questions, reads them aloud, evaluates your spoken answers (with fuzzy matching), and tracks your score.

## Trigger Words

- "start a quiz"
- "quiz me"
- "trivia game"
- "play a quiz"

## Setup

No setup required. No external APIs needed.

## How It Works

1. LLM generates 3 multiple-choice questions as structured JSON
2. Each question is read aloud with choices A-D
3. User speaks their answer
4. LLM evaluates if the answer is correct (handles synonyms and variations)
5. Score is tracked and announced at the end
6. Say "exit" or "stop" at any time to leave early

## Customization

Edit these constants at the top of `main.py`:

- `QUIZ_CATEGORY` — Change the topic (e.g., "Science", "History", "Pop Culture")
- `NUM_QUESTIONS` — Change how many questions per round

## Example Conversation

> **User:** "Start a quiz"
> **AI:** "Welcome to the Quiz! I'll ask you 3 questions on General Knowledge."
> **AI:** "What is the largest planet in our solar system? A. Mars B. Jupiter C. Saturn D. Earth"
> **User:** "Jupiter"
> **AI:** "That's correct!"
> ...
> **AI:** "You got 2 out of 3 correct! Thanks for playing!"
