# Universal Voice Interpreter

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-Umar_Faizan-lightgrey?style=flat-square)

## What It Does
A dynamic, two-way translation bridge for multi-lingual households or hosting. It initiates a continuous conversational loop that alternates between any two target languages, acting as a fluid, near-zero-latency interpreter.

## Suggested Trigger Words
- "start translation"
- "start interpreter"
- "act as my translator"

## Setup
No external API keys are required. This ability uses the core OpenHome LLM routing capabilities.

## How It Works
1. The user speaks the trigger phrase.
2. The agent asks which two languages to translate between.
3. The user responds (e.g., "English and French").
4. A continuous loop starts. The agent listens, automatically detects which of the two languages was spoken, translates it to the other language, and speaks it out loud.
5. **IMPORTANT:** The loop continues indefinitely in order to provide a seamless interpreter experience. To stop the loop and exit back to the normal OpenHome agent, the user must explicitly say **"Stop translation"** or **"Exit"**.

## Example Conversation (English & French Scenario)

Imagine a scenario where two people are in a room and don't speak each other's language. Person One speaks English, and Person Two speaks French. The OpenHome DevKit speaker is sitting on the table between them.

> **Person One:** "Start translation."
> 
> **DevKit Speaker:** "Translation mode starting. What two languages would you like to translate between?"
> 
> **Person One:** "English and French."
> 
> **DevKit Speaker:** "Perfect. I am now acting as an interpreter for English and French. You can begin speaking. Say 'Stop translation' at any time to exit."
> 
> **Person Two (in French):** "Bonjour, enchanté de vous rencontrer. Quel temps fait-il aujourd'hui?"
> 
> **DevKit Speaker (in English):** "Hello, nice to meet you. What is the weather like today?"
> 
> **Person One (in English):** "It is very sunny and warm outside!"
> 
> **DevKit Speaker (in French):** "Il fait très beau et chaud dehors!"
> 
> *(The loop continues seamlessly back and forth)*
> 
> **Person Two (in French):** "Parfait ! Allons nous promener."
> 
> **DevKit Speaker (in English):** "Perfect! Let's go for a walk."
> 
> **Person One:** "Stop translation."
> 
> **DevKit Speaker:** "Translation mode deactivated. Returning you to the normal agent."
