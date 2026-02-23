# Voice Unit Converter

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@samsonadmasu-lightgrey?style=flat-square)

## What It Does
A voice-powered unit converter that handles any conversion in natural language — cups to tablespoons, Fahrenheit to Celsius, ounces to grams, and more. Just ask and get the answer.

## Suggested Trigger Words
- "convert"
- "unit converter"
- "how many"
- "conversion"

## Setup
No setup required. No external APIs or keys needed.

## How It Works
1. User triggers the ability with a hotword
2. Ability asks what to convert
3. User asks a conversion in natural language
4. LLM processes the question and returns a short answer
5. Ability speaks the result and asks "Anything else?"
6. User can keep converting or say "stop" / "exit" / "done" to quit

## Key SDK Functions Used
- `speak()` — Text-to-speech output
- `user_response()` — Listen for user input
- `text_to_text_response()` — LLM text generation with system prompt
- `resume_normal_flow()` — Return to Personality

## Example Conversation
> **User:** "convert"
> **AI:** "Unit converter ready. What would you like to convert?"
> **User:** "How many tablespoons in a cup?"
> **AI:** "There are 16 tablespoons in a cup."
> **AI:** "Anything else?"
> **User:** "What's 200 grams in ounces?"
> **AI:** "200 grams is about 7.05 ounces."
> **AI:** "Anything else?"
> **User:** "done"
> **AI:** "Goodbye!"
