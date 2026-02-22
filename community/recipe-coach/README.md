# Recipe Coach

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hueymahl-lightgrey?style=flat-square)

## What It Does

A voice-guided cooking assistant that generates recipes on the fly and walks you through them step by step. Name a dish or ingredient — Recipe Coach builds a recipe, reads the ingredients, then guides you through each step at your own pace.

No API keys required. Uses the Personality's built-in LLM for recipe generation.

## Suggested Trigger Words

- "recipe coach"
- "help me cook"
- "walk me through a recipe"
- "teach me to cook"
- "cooking guide"

## Setup

No setup required. Recipe Coach uses the Personality's built-in LLM — no external APIs or keys needed. Just upload, set your trigger words, and go.

## How It Works

1. **Ask** — Recipe Coach asks what you'd like to cook
2. **Generate** — The LLM creates a complete recipe with ingredients and steps
3. **Ingredients** — Reads the ingredient list in small, easy-to-follow groups
4. **Confirm** — Asks if you're ready to start cooking
5. **Step-by-step** — Walks through each step one at a time, waiting for your command

### Voice Commands During Cooking

| Say | What Happens |
|-----|-------------|
| **"next"** / "continue" / "go ahead" | Move to the next step |
| **"repeat"** / "again" / "say that again" | Hear the current step again |
| **"stop"** / "done" / "exit" | Leave the recipe at any time |

## Example Conversation

> **User:** "Help me cook"
>
> **AI:** "Hey! I'm your recipe coach. What would you like to cook today?"
>
> **User:** "Chicken stir fry"
>
> **AI:** "Great choice. Let me put together a recipe for chicken stir fry."
>
> **AI:** "Here's what you'll need for Chicken Stir Fry, serving 4."
>
> **AI:** "1 pound boneless chicken breast, sliced thin. 2 tablespoons soy sauce. 1 tablespoon sesame oil."
>
> **AI:** "1 red bell pepper, sliced. 2 cups broccoli florets. 3 cloves garlic, minced."
>
> **AI:** "Got everything? Say yes when you're ready to start cooking."
>
> **User:** "Yes"
>
> **AI:** "Let's go. 5 steps total. Say next to move on, repeat to hear a step again, or stop to exit."
>
> **AI:** "Step 1. Heat the sesame oil in a large skillet or wok over high heat."
>
> **User:** "Next"
>
> **AI:** "Step 2. Add the chicken and cook for 5 minutes until golden brown, then set aside."
>
> **User:** "Repeat"
>
> **AI:** "Step 2. Add the chicken and cook for 5 minutes until golden brown, then set aside."
>
> **User:** "Next"
>
> *(continues through remaining steps...)*
>
> **AI:** "That's it! Chicken Stir Fry is done. Enjoy your meal!"
