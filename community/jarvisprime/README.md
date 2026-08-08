# Jarvis Prime

![Skill](https://img.shields.io/badge/Type-Skill-blue?style=flat-square)

## What It Does

Jarvis Prime is a proactive voice assistant ability: it remembers what matters
from your conversations, performs tasks in the background, and comes back when
it has something important to tell you.

- **Remembers** — quietly extracts commitments and facts you mention in
  passing and keeps the Agent aware of them (`context.md` memory).
- **Acts** — "find out X and get back to me" runs in the background while you
  keep talking; the answer interrupts when ready.
- **Watches** — "keep an eye on my site" polls until the condition fires, then
  speaks up. Watches survive across sessions.

## Trigger Words

- "jarvis"
- "hey jarvis"

## How to Use

1. Say a trigger word to open a session ("At your post.").
2. Ask for a background task, set a watch, or just talk.
3. Say "done" (or any exit word) to hand the conversation back — Jarvis keeps
   working in the background.
4. Ask the Agent "anything I'm forgetting?" any time — the memory is injected
   into the Agent itself.

## Setup

No API keys required. Built on OpenHome SDK primitives only
(`llm_search`, session tasks, key-value storage, file storage with `.md`
context injection).

## Folder structure (for contributors)

```
jarvisprime/
├── main.py        # the ability — the only file that gets deployed
├── __init__.py
├── README.md
└── dev/           # dev aids, never deployed
    ├── test_main.py   # off-platform logic tests: python dev/test_main.py
    └── demo_site.py   # killable localhost:8080 site for the watch demo
```

Planning docs (`*-PLAN*.md`, `JARVIS.md`, `TEAMMATE-BRIEF.md`, `reference/`)
are local-only and gitignored — they never enter commits or PRs.
