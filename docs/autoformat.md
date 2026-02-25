# Code Formatting & Linting

This project uses a single script to keep Python code clean and consistent. Run it before you push — it saves reviewers time and keeps the codebase tidy.

## What It Does

`autoformat.sh` runs a standard toolchain in one go:

- **Black** — Code formatting
- **isort** — Import ordering
- **autoflake** — Removes unused imports and variables
- **flake8** — Style and lint checks
- **mypy** — Static type checking
- **validate_ability.py** — SDK compliance (only when you run on the whole repo)

## Quick Start

```bash
# Install dependencies once
pip install black isort autoflake flake8 mypy

# Check if everything passes (no file changes)
./autoformat.sh --check

# Fix what can be auto-fixed
./autoformat.sh --fix
```

## Modes

| Mode | What it does |
|------|--------------|
| `--check` | Reports issues but doesn't change any files. Use this in CI or before committing to see if you're clean. |
| `--fix` | Applies Black, isort, and autoflake fixes in place. flake8 and mypy still only report — you fix those by hand. |

## Targeting a Path

By default the script runs on the whole repo (`.`). You can target a specific folder:

```bash
./autoformat.sh --check community/my-ability
./autoformat.sh --fix community/my-ability
```

When you target a specific path, `validate_ability.py` is skipped. It only runs when you format the entire repo with `--fix .` or `--check .`.

## Config Files

Config lives in the repo root. You don't need to change anything unless you're tuning rules.

| File | Purpose |
|------|---------|
| `.flake8` | Line length, ignores, exclude paths |
| `mypy.ini` | Python version, type-check options |

These are picked up automatically by flake8 and mypy.

## On Windows

Use Git Bash or WSL:

```bash
./autoformat.sh --check
```

From PowerShell:

```powershell
bash autoformat.sh --check
```

## What If Something Fails?

- **Black / isort / autoflake** — Run `./autoformat.sh --fix` to apply automatic fixes.
- **flake8 / mypy** — These only report. Fix the reported issues in your editor and re-run.

`validate_ability.py` failures mean your Ability doesn't meet SDK rules. Check the output for specific errors; [CONTRIBUTING.md](../CONTRIBUTING.md) and [capability-worker.md](capability-worker.md) have the full requirements.
