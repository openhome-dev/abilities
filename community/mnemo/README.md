# Mnemo

**Voice-first study companion. Named for memory, built on the Feynman technique.**

Mnemo is a hands-free study buddy with two modes: it can quiz you on any topic and reveal answers with progressive detail, or you can teach a concept back to it while it probes your understanding Feynman-style. It remembers your weak spots across sessions and can email you a session recap.

---

## What it does

### 🎯 Quiz Mode
Say **"quiz me on gravity"** (or any topic). Mnemo generates 5 questions with mixed difficulty, judges your answers leniently, reveals the correct answer when you're wrong, and offers to explain deeper. It tracks your weak spots.

### 🧠 Teach Mode (Feynman)
Say **"teach me photosynthesis"**. Mnemo asks you to explain the concept like the listener is 12. It then scores your clarity (out of 10), identifies conceptual gaps, and probes you with follow-up questions targeting those gaps.

### 💾 Persistent memory
Across sessions, Mnemo remembers your weak spots and can bring them up next time. Say **"drill my weak spots"** to focus a quiz on prior struggles.

### 📧 Email recap (optional)
At the end of a session, Mnemo can email you a recap with your score and weak spots for later review. Requires Gmail SMTP setup (see below).

---

## Trigger Words

Set these in the OpenHome dashboard:
- `mnemo`
- `quiz me`
- `teach me`
- `study time`

Smart entry also parses your full utterance — so `"quiz me on gravity"` or `"teach me the water cycle"` skips the mode picker and goes straight into the flow.

---

## Setup

### Basic setup (no email)
1. Copy the ability into `community/mnemo/` in the abilities repo.
2. Install it from the OpenHome dashboard.
3. Attach it to any personality/agent.
4. Speak or type a trigger word — that's it.

### Email recap (optional)
Nothing is hardcoded in `main.py` — the email recap reads its credentials at runtime from OpenHome's secure API Key store:

1. Enable 2-Step Verification on your Google account: https://myaccount.google.com/security
2. Generate an app password: https://myaccount.google.com/apppasswords
3. In the OpenHome Dashboard, go to **Settings -> API Keys** and add two keys (names must match exactly):
   - `mnemo_sender_email` — your Gmail address
   - `mnemo_sender_password` — the 16-character app password
4. Save. Now Mnemo will offer to email a recap at the end of each session.

If you leave these unset, Mnemo simply skips the email step — everything else still works.

---

## Example conversation

```
User: quiz me on gravity
Mnemo: Aight, five questions on gravity. Let's cook.
Mnemo: Question 1. What is gravity?
User: I don't know
Mnemo: No worries. The answer is: Gravity is a force that attracts objects toward each other.
Mnemo: Want more detail, want me to repeat, or should we keep going?
User: more
Mnemo: Basically, when you drop an apple, gravity is what pulls it toward Earth. It's the same force keeping planets in orbit around the Sun.
Mnemo: Want more detail, want me to repeat, or should we keep going?
User: keep going
Mnemo: Question 2. ...
```

---

## Features

- **Smart entry** — parses `"quiz me on X"` / `"teach me about X"` to skip mode picker
- **Two modes** — Quiz Me (Mnemo asks) and Teach Me (Feynman-style, you explain)
- **Answer reveal with detail loop** — after wrong answers, offers deeper explanation on repeat
- **Weak-spot persistence** — remembers what you struggled with across sessions
- **Graceful exit** — say `"stop"` at any point to bail out cleanly
- **Chill senpai tone** — casual, encouraging, family-friendly
- **Robust fallbacks** — LLM failures, JSON parse errors, empty inputs all handled cleanly
- **Optional email recap** — Gmail SMTP integration for session summaries

---

## Files

- `main.py` — full ability code
- `config.json` — unique name + trigger hotwords
- `__init__.py` — module marker
- `README.md` — this file

---

## Credits

Built during the OpenHome × ALGORYC 1-Day Hackathon.
Named for **Mnemosyne** (Greek muse of memory) and **Richard Feynman** (the "teach it simply" scientist).
