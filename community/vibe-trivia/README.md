# Vibe Trivia

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@pipinstallshan-lightgrey?style=flat-square)

## What It Does
A short, voice-first trivia game. You pick a category (or “random”), choose how many questions, answer A/B/C/D, and get a final score.

## Suggested Trigger Words
- "start vibe trivia"
- "trivia time"
- "quiz me"
- "play trivia"
- "start a quiz"

## Setup
- No API keys required.

## How It Works
1. The Ability asks for a category (or “random”).
2. It asks how many questions (default 3).
3. It generates multiple-choice questions using the built-in LLM.
4. It asks each question, grades your answer, and tracks score.
5. It stores your best score using per-user storage (optional).

## Example Conversation
> **User:** "start vibe trivia"
>
> **AI:** "Welcome to Vibe Trivia. Pick a category like movies, science, or history. Or say random."
>
> **User:** "science"
>
> **AI:** "How many questions would you like? You can say a number from 1 to 10."
>
> **User:** "3"
>
> **AI:** "Great. We'll do 3 questions on science. Ready to start?"
>
> **User:** "yes"
>
> **AI:** "Question 1 of 3… A: … B: … C: … D: …"
>
> **User:** "B"
>
> **AI:** "Correct."
