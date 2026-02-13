# Contributing to OpenHome Abilities

Thanks for wanting to contribute! This guide will get you from idea to merged PR as smoothly as possible.

---

## The Two-Minute Version

1. Fork this repo
2. Copy `templates/basic-template/` to `community/your-ability-name/`
3. Build your Ability (edit `main.py`) and README.md
4. Test it in the [OpenHome Live Editor](https://app.openhome.com/dashboard/abilities)
5. Open a Pull Request **against `dev`**

That's it. We'll review it and get it merged.

---

## Branching & Merging Strategy

We use a **simplified Git Flow** model. All contributions follow this flow:

```
ability/your-ability-name  →  dev  →  main
```

| Branch | Purpose | Who Merges |
|--------|---------|------------|
| `main` | Stable, production-ready. Always deployable. | Maintainers only |
| `dev` | Integration and testing. All PRs target this branch. | Maintainers after review |
| `ability/*` or `add-*` | Your working branch for a single Ability or change. | You push; maintainers merge to `dev` |

**Rules:**

- **Never open a PR directly to `main`.** All PRs must target `dev`.
- `dev` is merged to `main` by maintainers after validation and testing.
- Keep your ability branch up to date with `dev` before opening a PR (rebase or merge).

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

Fork the repository on GitHub, then clone your fork:

```bash
git clone https://github.com/YOUR_USERNAME/abilities.git
cd abilities
```

Set up the upstream remote to stay in sync with the original repo:

```bash
git remote add upstream https://github.com/OpenHome-dev/abilities.git
```

Then make sure you have the `dev` branch locally and start from it:

```bash
git fetch upstream
git checkout dev
git pull upstream dev
```

> **Why upstream?** This ensures you're always branching from the latest `dev` on the original repo, not a potentially stale `dev` on your fork.

### 2. Create Your Ability Branch

Branch off `dev` — not `main`:

```bash
git checkout -b add-your-ability-name dev
```

Use a descriptive branch name like `add-dad-jokes`, `add-pomodoro-timer`, or `fix-weather-error-handling`.

### 3. Pick a Template

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

### 4. Build Your Ability

Edit `main.py`. Every Ability must:

- [ ] Extend `MatchingCapability`
- [ ] Have `register_capability()` (copy the boilerplate exactly from the template)
- [ ] Have `call()` that sets up worker + capability_worker and launches async logic
- [ ] Call `self.capability_worker.resume_normal_flow()` on **every exit path**
- [ ] Handle errors with try/except
- [ ] Use `self.worker.editor_logging_handler` for logging (never `print()`)

> **Note:** Trigger words are configured in the OpenHome dashboard, not in code. The `register_capability` boilerplate reads a platform-managed `config.json` at runtime — you never create or edit that file.

#### 📚 Resources

- **[CapabilityWorker Reference](docs/capability-worker.md)** — All available functions for ability creation (`speak`, `user_response`, `run_io_loop`, file helpers, audio helpers, etc.)

#### 🚫 Blocked Imports & Keywords (Quick Reference)

| Blocked | Why | Use Instead |
|---|---|---|
| `print()` | Bypasses structured logging | `self.worker.editor_logging_handler` |
| `open()` (raw) | Unmanaged filesystem access | `self.capability_worker.read_file()` / `write_file()` |
| `redis` | Direct datastore coupling | Platform-provided helpers |
| `connection_manager` | Breaks isolation & multi-tenant safety | `CapabilityWorker` APIs |
| `user_config` | Can leak/mutate global state | `CapabilityWorker` / `worker` APIs |
| `exec()` | Insecure dynamic code execution | ❌ Not allowed |
| `pickle/dill/shelve/marshal` | Insecure deserialization | ❌ Not allowed |

> **Full list →** [docs.openhome.com — Blocked Imports and Keywords](https://docs.openhome.com/how_to_build_an_ability#blocked-imports-and-keywords)

### 5. Write Your README

Create `community/your-ability-name/README.md` using this format:

```markdown
# Your Ability Name

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@yourusername-lightgrey?style=flat-square)

## What It Does
One or two sentences explaining what this Ability does.

## Suggested Trigger Words
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
- Set trigger words in the dashboard
- Make sure all exit paths work (say "stop", "exit", etc.)

### 7. Sync with `dev` Before Submitting

Before you push, make sure your branch is current with the latest `dev` from upstream:

```bash
git fetch upstream
git rebase upstream/dev
```

If you prefer merge over rebase:

```bash
git fetch upstream
git merge upstream/dev
```

Resolve any conflicts, then continue.

### 8. Submit Your PR

```bash
git add community/your-ability-name/
git commit -m "Add your-ability-name community ability"
git push origin add-your-ability-name
```

Open a Pull Request on GitHub:

- **Base branch: `dev`** (not `main`)
- **Compare branch: `add-your-ability-name`**
- Fill out the PR template completely

> ⚠️ PRs targeting `main` will be closed and you'll be asked to re-open against `dev`.

---

## What Happens After You Open a PR

1. **Automated checks run** — `validate-ability`, `path-check`, `security-scan`, and linting must all pass.
2. **A maintainer reviews** — typically within 3–5 business days.
3. **Feedback round** — you may be asked to make changes. Push additional commits to the same branch; the PR updates automatically.
4. **Merge to `dev`** — once approved, a maintainer squash-merges your PR into `dev`.
5. **Promotion to `main`** — periodically, the maintainer team validates `dev` and merges it into `main`. Your Ability becomes available on the Marketplace at that point.

You don't need to do anything after step 4. The `dev → main` promotion is handled by maintainers.

---

## Review Checklist

Every community PR is reviewed for:

### Must Pass (Hard Requirements)

- [ ] PR targets the **`dev` branch** (not `main`)
- [ ] Files are in `community/your-ability-name/` (not in `official/`)
- [ ] `main.py` follows the SDK pattern (extends `MatchingCapability`, has `register_capability` + `call`)
- [ ] `README.md` is present with description, suggested trigger words, and setup instructions
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
| Open a PR to `main` | Target `dev` — always |
| Branch off `main` | Branch off `dev` |
| Submit to `official/` | Submit to `community/` |
| Use `print()` | Use `self.worker.editor_logging_handler.info()` |
| Use `asyncio.sleep()` | Use `self.worker.session_tasks.sleep()` |
| Use `asyncio.create_task()` | Use `self.worker.session_tasks.create()` |
| Hardcode API keys | Use placeholders + document in README |
| Forget `resume_normal_flow()` | Call it on every exit path — loops, breaks, errors |
| Write long spoken responses | Keep it short — 1-2 sentences per speak() call |
| Import `redis`, `connection_manager`, etc. | Use CapabilityWorker APIs |
| Push directly to `dev` or `main` | Push to your ability branch, open a PR |

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

- **Stuck on code?** → Ask in [Discord](https://discord.gg/openhome)
- **Found a bug in an Ability?** → [Open an issue](../../issues/new?template=bug-report.md)
- **Have an idea for an Ability?** → [Suggest it](../../issues/new?template=ability-idea.md)
- **SDK question?** → Check [docs/capability-worker-api.md](docs/capability-worker-api.md)

---

## License

By submitting a PR, you agree that your contribution is licensed under the [MIT License](LICENSE). Original authorship is always credited in your Ability's README and in CONTRIBUTORS.md.
