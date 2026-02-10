# Contributing to OpenHome Abilities

Thanks for wanting to contribute! This guide will get you from idea to merged PR as smoothly as possible.

---

## The Two-Minute Version

1. Fork this repo
2. Copy `templates/basic-template/` to `community/your-ability-name/`
3. Build your Ability (edit `main.py` and `config.json`)
4. Test it in the [OpenHome Live Editor](https://app.openhome.com)
5. Open a Pull Request

That's it. We'll review it and get it merged.

---

## How the Repo Is Organized

```
official/        ← Maintained by OpenHome. Don't submit PRs here.
community/       ← Your contributions go here.
templates/       ← Starting points. Copy one to get going.
docs/            ← Guides and API reference.
```

**You submit to `community/` only.** The `official/` folder is maintained by the OpenHome team. Exceptional community Abilities can be [promoted to official](#promotion-path) over time.

---

## Step-by-Step Guide

### 1. Fork and Clone

```bash
git clone https://github.com/YOUR_USERNAME/abilities.git
cd abilities
```

### 2. Pick a Template

Choose the template closest to what you're building:

| Template | Use When |
|----------|----------|
| `templates/basic-template/` | Simple ask → respond → done |
| `templates/api-template/` | You're calling an external API |
| `templates/loop-template/` | Interactive / multi-turn conversation |

Copy it:

```bash
cp -r templates/basic-template community/your-ability-name
```

### 3. Set Up config.json

```json
{
  "unique_name": "your_ability_name",
  "matching_hotwords": ["trigger phrase one", "another trigger"]
}
```

**Tips for trigger words:**
- Use natural phrases someone would actually say ("tell me a joke", not "activate joke module")
- Include 2-5 variations
- Avoid single common words that might false-trigger ("play", "go", "start")

### 4. Build Your Ability

Edit `main.py`. Every Ability must:

- [ ] Extend `MatchingCapability`
- [ ] Have `register_capability()` that loads from `config.json` (use the exact pattern from templates)
- [ ] Have `call()` that sets up worker + capability_worker and launches async logic
- [ ] Call `self.capability_worker.resume_normal_flow()` on **every exit path**
- [ ] Handle errors with try/except
- [ ] Use `self.worker.editor_logging_handler` for logging (never `print()`)

### 5. Write Your README

Create `community/your-ability-name/README.md` using this format:

```markdown
# Your Ability Name

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@yourusername-lightgrey?style=flat-square)

## What It Does
One or two sentences explaining what this Ability does.

## Trigger Words
- "trigger phrase one"
- "another trigger"

## Setup
- Any API keys needed and where to get them
- Any other setup steps

## How It Works
Brief description of the conversation flow.

## Example Conversation
> **User:** "trigger phrase one"
> **AI:** "Response example..."
> **User:** "follow up"
> **AI:** "Another response..."
```

### 6. Test It

- Zip your Ability folder
- Go to [app.openhome.com](https://app.openhome.com) → Abilities → Add Custom Ability
- Upload and test in the Live Editor
- Make sure all exit paths work (say "stop", "exit", etc.)

### 7. Submit Your PR

```bash
git checkout -b add-your-ability-name
git add community/your-ability-name/
git commit -m "Add your-ability-name community ability"
git push origin add-your-ability-name
```

Open a Pull Request and fill out the PR template.

---

## Review Checklist

Every community PR is reviewed for:

### Must Pass (Hard Requirements)

- [ ] Files are in `community/your-ability-name/` (not in `official/`)
- [ ] `config.json` is present with `unique_name` and `matching_hotwords`
- [ ] `main.py` follows the SDK pattern (extends `MatchingCapability`, has `register_capability` + `call`)
- [ ] `README.md` is present with description, trigger words, and setup instructions
- [ ] `resume_normal_flow()` is called on every exit path
- [ ] No `print()` statements (use `editor_logging_handler`)
- [ ] No blocked imports (`redis`, `connection_manager`, `user_config`, `open()`)
- [ ] No `asyncio.sleep()` or `asyncio.create_task()` (use `session_tasks` helpers)
- [ ] No hardcoded API keys (use `"YOUR_API_KEY_HERE"` placeholders)
- [ ] Error handling on all API calls and external operations

### Nice to Have

- [ ] Spoken responses are short and natural (this is voice, not text)
- [ ] Exit/stop handling in any looping Ability
- [ ] Inline comments explaining non-obvious logic
- [ ] Follows patterns from `docs/patterns.md`

### What We Don't Review For

- Whether an external API will keep working forever
- Whether it's the "best" way to accomplish the task
- Future SDK compatibility (we'll help with migrations)

---

## What NOT to Do

| Don't | Do Instead |
|-------|-----------|
| Submit to `official/` | Submit to `community/` |
| Use `print()` | Use `self.worker.editor_logging_handler.info()` |
| Use `asyncio.sleep()` | Use `self.worker.session_tasks.sleep()` |
| Use `asyncio.create_task()` | Use `self.worker.session_tasks.create()` |
| Hardcode API keys | Use placeholders + document in README |
| Forget `resume_normal_flow()` | Call it on every exit path — loops, breaks, errors |
| Write long spoken responses | Keep it short — 1-2 sentences per speak() call |
| Import `redis`, `connection_manager`, etc. | Use CapabilityWorker APIs |

---

## Promotion Path

Community Abilities that stand out can be promoted to Official status:

| Criteria | Threshold |
|----------|-----------|
| Marketplace installs | 50+ |
| Stability | No critical bugs for 30+ days |
| Code quality | Clean, follows SDK patterns |
| Author responsiveness | Responds to issues |
| Usefulness | Fills a real gap |

When promoted:
- Ability moves from `community/` to `official/`
- Gets the 🔷 Official badge on Marketplace
- OpenHome takes over maintenance (author stays credited)
- Author recognized in release notes

---

## Getting Help

- **Stuck on code?** → Ask in [GitHub Discussions](../../discussions) or [Discord](https://discord.gg/openhome)
- **Found a bug in an Ability?** → [Open an issue](../../issues/new?template=bug-report.md)
- **Have an idea for an Ability?** → [Suggest it](../../issues/new?template=ability-idea.md)
- **SDK question?** → Check [docs/capability-worker-api.md](docs/capability-worker-api.md)

---

## License

By submitting a PR, you agree that your contribution is licensed under the [MIT License](LICENSE). Original authorship is always credited in your Ability's README and in CONTRIBUTORS.md.
