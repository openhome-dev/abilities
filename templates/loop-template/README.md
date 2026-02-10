# Loop Template

For interactive Abilities with ongoing multi-turn conversations.

**Greet → Loop (Listen → Process → Respond) → Exit on command**

## When to Use This

- Games (quizzes, trivia, word games)
- Coaches (fitness, meditation, language)
- Creative tools (sound generator, story builder)
- Anything where the user interacts multiple times before finishing

## How to Customize

1. Copy this folder to `community/your-ability-name/`
2. Replace the processing logic inside the `while True` loop
3. Add your own exit words if needed (or keep the defaults)
4. Add state tracking — add instance variables to the class for anything you need to remember between turns
5. Upload to OpenHome and set your trigger words in the dashboard

## Flow

```
Ability triggered by hotword
    → Speaks a greeting
    → LOOP:
        → Waits for user input
        → Checks for exit command → breaks if found
        → Processes input (LLM, API, audio, etc.)
        → Speaks response
        → Back to top of loop
    → Resumes normal Personality flow
```

## Tips

- Always check for exit words early in the loop
- Skip empty inputs with `if not user_input: continue`
- Keep spoken responses short — the user is waiting to speak again
- Add instance variables (e.g., `self.score = 0`) for state tracking
- Use `self.worker.session_tasks.sleep()` if you need delays, never `asyncio.sleep()`
