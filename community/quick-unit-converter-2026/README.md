# Quick Unit Converter 2026

A high-precision, zero-fluff unit converter designed for voice-first environments like a kitchen. It eliminates conversational "filler" to provide instant, accurate mathematical results.

## Features
* **Zero-Fluff Interaction:** Uses a custom logic filter to strip out LLM chatter (like "Alrighty!" or "Great question!").
* **Voice-First Design:** Specifically prompts the LLM to use the word "point" for decimals to ensure clear Text-to-Speech delivery.
* **Kitchen Ready:** Designed for users with their hands full who need quick numbers (Cups to Ounces, Fahrenheit to Celsius, etc.).

## Suggested Trigger Words
* "Convert"
* "Unit Converter"
* "How many"

## SDK Usage
* `capability_worker.text_to_speech`: Used with Voice ID `29vD33N1CtxCmqQRPOHJ` for a professional news-style delivery.
* `capability_worker.user_response`: Captures natural language conversion requests.
* `capability_worker.text_to_text_response`: Processes the mathematical logic.
* `capability_worker.resume_normal_flow`: Ensures the agent returns to standard conversation after the conversion loop.
