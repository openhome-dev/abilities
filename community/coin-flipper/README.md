# Coin Flipper & Decision Maker

![Community](https://img.shields.io/badge/OpenHome-Community-green?style=flat-square)

A versatile decision-making assistant designed to help you choose between options or test your luck. Unlike simple randomizers, this ability features **Smart Memory** (context awareness) to repeat actions instantly and understands a wide range of natural language commands.

## Trigger Words

Based on the dashboard configuration:

- "Coin toss"
- "Help me decide"
- "Pick for me"
- "Flip coin"
- "Coin tossing"

## Setup

No setup required. No external APIs needed.
The ability uses Python's standard `random` library for logic and supports a 1% "Easter Egg" chance.

## How It Works

1. **Activation:** User triggers the Ability with a hotword (e.g., "Help me decide").
2. **Intent Detection:** The AI asks what to do. It scans the user's response against a rich vocabulary list:
   - *Decision commands:* "decide", "choice", "pick", "select", "option", "solve".
   - *Coin commands:* "flip", "toss", "throw", "heads", "tails", "play".
   - *Exit commands:* "bye", "enough", "that's all", "finish", "no thanks".
3. **Execution:**
   - **Flip Mode:** Randomly selects Heads or Tails (with a 1% chance to land on the Edge).
   - **Decide Mode:** Asks for Option 1 and Option 2, then picks a winner.
4. **Smart Repeat:** If the user says "Again", "One more time", or "Repeat", the AI remembers the last mode. If it was a decision, it re-rolls between the previously saved options without asking for them again.
5. **Exit:** The interaction ends when the user uses any natural closing phrase.

## Key SDK Functions Used

- `speak()` — Text-to-speech output for results and prompts.
- `run_io_loop()` — Handles the core interaction: speaking a prompt and immediately opening the microphone to capture user intent.
- `resume_normal_flow()` — Cleanly exits the ability loop and returns control to the main Personality.

## Example Conversation

> **User:** "Help me decide"
> **AI:** "I am ready. I can help you pick an option, or just toss a coin. What would you like to do?"
>
> **User:** "Pick for me"
> **AI:** "Okay, I will help you decide. Tell me the choices. What is the first option?"
>
> **User:** "Order Pizza"
> **AI:** "And what is the second option?"
>
> **User:** "Make a Salad"
> **AI:** "That is hard... But I choose... Order Pizza!"
>
> **User:** "Do it again"
> **AI:** *[Smart Memory Triggered]* "Choosing again between Order Pizza and Make a Salad... The winner is Make a Salad!"
>
> **User:** "Just flip a coin now"
> **AI:** "Tossing the coin high in the air... It is Heads!"
>
> **User:** "That's all, thanks"
> **AI:** "Okay. See you later!"