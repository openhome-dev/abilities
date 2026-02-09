# Basic Template

The simplest Ability pattern. Use this when you need a quick one-shot interaction:

**Speak → Listen → Respond → Exit**

## When to Use This

- Simple Q&A Abilities
- One-turn conversations
- Quick utility tasks

## How to Customize

1. Copy this folder to `community/your-ability-name/`
2. Rename the class in `main.py`
3. Update `config.json` with your ability name and trigger words
4. Replace the logic in `run()` with your own
5. That's it!

## Flow

```
Ability triggered by hotword
    → Speaks a greeting
    → Waits for user input
    → Sends input to LLM
    → Speaks the response
    → Returns to normal Personality flow
```
