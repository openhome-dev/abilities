# Dad Joke Teller

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)

A voice ability that tells dad jokes on demand. Uses the free [icanhazdadjoke.com](https://icanhazdadjoke.com/) API — no API key required.

## What It Does

- Greets the user and asks if they want a joke
- Fetches random dad jokes from icanhazdadjoke.com
- Tells the joke via text-to-speech
- Loops — user can request more jokes or say "stop" to exit
- Handles ambiguous input via LLM (e.g., "I'm good" → exit)

## Suggested Trigger Words

- "dad joke"
- "tell me a joke"
- "joke time"
- "dad jokes"
- "make me laugh"

## Setup

No setup required. The ability uses icanhazdadjoke.com, which is free and does not require an API key.

## How It Works

1. User triggers the Ability with a hotword
2. Dad Joke Teller greets and asks if they want a joke
3. User says yes or asks for another
4. Ability fetches a joke from the API and speaks it
5. Asks "Want another? Say stop when you're done."
6. Repeats until user says stop, exit, done, etc.

## Key SDK Functions Used

- `speak()` — Text-to-speech output
- `user_response()` — Listen for user input
- `text_to_text_response()` — LLM intent classification for ambiguous input
- `resume_normal_flow()` — Return to Personality

## Example Conversation

> **User:** "Tell me a joke"
> **AI:** "Welcome to Dad Joke Time. Want a joke? Say stop when you're done."
> **User:** "Yes"
> **AI:** "Why don't scientists trust atoms? Because they make up everything. Want another? Say stop when you're done."
> **User:** "Another"
> **AI:** [next joke]
> **User:** "Stop"
> **AI:** "Alright, no more jokes. Talk to you later."
