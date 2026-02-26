# Language Phrase Helper

A voice-first travel phrase translator for the OpenHome platform. Say a phrase and a target language, and get back a translation with phonetic pronunciation and cultural tips.

## Triggers

- "translate"
- "how do you say"
- "language helper"
- "phrase translator"
- "say in"

## Features

- Translates phrases to any language using the LLM
- Provides phonetic pronunciation guides
- Includes cultural tips when relevant
- Remembers your target language across turns ("now say thank you" keeps the same language)
- Multi-turn conversation loop

## Setup

No API keys required. This ability uses the built-in LLM for translation.

## Example Usage

> "How do you say thank you in Japanese"
> "Now say good morning"
> "Switch to French — where is the train station?"

## How It Works

1. User says a phrase and target language
2. LLM extracts the language and phrase from natural speech
3. LLM generates translation, phonetic guide, and cultural tip
4. Speaks the result and waits for the next phrase
5. Say "stop" or "done" to exit
