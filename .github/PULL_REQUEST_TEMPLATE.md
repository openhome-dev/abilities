## What does this Ability do?

<!-- One or two sentences -->

## Suggested Trigger Words

<!-- List the hotwords you recommend for activating this Ability (users set these in the dashboard) -->
- 
- 

## Type

- [ ] New community Ability
- [ ] Improvement to existing Ability
- [ ] Bug fix
- [ ] Documentation update

## External APIs

<!-- Does this Ability call any external APIs? List them and note if an API key is required. -->

- [ ] No external APIs
- [ ] Uses external API(s): <!-- list them -->

## Testing

- [ ] Tested in OpenHome Live Editor
- [ ] All exit paths tested (said "stop", "exit", etc.)
- [ ] Error scenarios tested (API down, bad input, etc.)

## Checklist

- [ ] Files are in `community/my-ability-name/`
- [ ] `main.py` follows SDK pattern (extends `MatchingCapability`, has `register_capability` + `call`)
- [ ] `README.md` included with description, suggested triggers, and setup
- [ ] `resume_normal_flow()` called on every exit path
- [ ] No `print()` — using `editor_logging_handler`
- [ ] No hardcoded API keys — using placeholders
- [ ] No blocked imports (`redis`, `connection_manager`, `user_config`)
- [ ] No `asyncio.sleep()` or `asyncio.create_task()` — using `session_tasks`
- [ ] Error handling on all external calls

## Anything else?

<!-- Optional: screenshots, demo video, conversation flow diagram, etc. -->
