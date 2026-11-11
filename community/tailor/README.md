# Tailor

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hassan1731996-lightgrey?style=flat-square)

## What It Does
Your assistant learns how you like it to talk. Say "too long", "just give me the number" or "stop asking if I want more", and Tailor turns that into a short style rule. The main Agent follows the rule from then on. You can ask what it has learned, why it does something, and change or remove any rule by voice.

Other assistants give you a fixed list of personalities to pick from. Tailor learns yours from what you actually say, shows you what it learned, and lets you edit it.

## Suggested Trigger Words
- "tailor"
- "how do you talk to me"
- "what have you learned about how I like you to talk"
- "my style rules"
- "why do you talk like that"

Learning needs no trigger. The background part runs whenever your session is connected.

## Setup
- No API keys, accounts or external services.
- Works in the Live Editor and on any device.

## How It Works
Tailor has two parts.

**Background learner (`background.py`).** Every 90 seconds it looks at new messages in the conversation. It only considers a message from you that comes right after an assistant reply. It also needs one of two signals:
- **Explicit feedback.** You say something like "too long", "shorter", "you already said that", "skip the intro" or "in metric".
- **A repeated question.** You ask nearly the same question again because the reply missed it.

Most messages never reach the LLM. At most three a poll do. The LLM then decides whether the message is really feedback on style, and writes one short rule. A rule can apply everywhere, or to one topic ("for recipes, give only the steps").

- **Explicit feedback** becomes a rule straight away.
- **A repeated question** becomes a rule only after it happens twice.
- **Same rule again:** feedback that matches an existing rule reinforces it.
- **Opposite rule:** feedback that contradicts a rule replaces it.

Rules are saved in Context Storage and written to `tailor_style.md`. OpenHome injects that file into the main Agent's prompt within about 60 to 90 seconds, so you should hear a change within a couple of minutes.

**Voice skill (`main.py`).**

| You say | Tailor does |
|---|---|
| "How do you talk to me?" | Says how many rules it has learned, then reads them one at a time. Say "next" or "done". |
| "Why do you do that?" | Says when it picked the rule up and what happened, for example "about a week ago: you asked for shorter weather answers." It also says how many times the rule has come up. |
| "Forget that one" | Confirms, then removes it. You can answer the confirmation with a change instead ("no, keep it short only for news"). |
| "Change it to three sentences" | Rewrites the rule after you confirm. |
| "Always use metric" | Adds a rule you asked for yourself. Rules you add by voice never expire. |
| "Pause learning" / "resume learning" | Stops or restarts learning. The rules you already have stay in effect. |
| "Reset my rules" | Forgets everything after you confirm. |

Say "done", "that's all" or "goodbye" at any point to leave. Two silent turns also end the session.

### Limits
- **At most 8 rules.** The injected file stays under 180 words. If the list is full, a new learned rule replaces the learned rule you reinforced least recently. Rules you added by voice are never dropped this way.
- **Learned rules expire.** A learned rule that isn't reinforced for 30 days is dropped. A one-off repeated question that never comes up again is forgotten after 14 days.
- **Rules shape the main Agent's own replies.** Other skills that speak fixed scripts won't change.
- **Not instant.** The background checks every 90 seconds, and the Agent picks up the file within another 60 to 90 seconds.
- **Not while Tailor is open.** Learning pauses during a Tailor session, so talking about your rules isn't mistaken for feedback.

### Safety and privacy
- **Style only.** A rule must fit one of these categories: length, structure, follow-up questions, confirmations, formality, humor, jargon, units, number format, depth, or phrases to avoid. Anything that tries to change what the assistant is, what it may do, safety, tools or purchases is refused twice: once by the prompt, and again by a check in code.
- **Conversation text is untrusted data.** It is fenced off in prompts with random markers, so a message can't reprogram Tailor.
- **No transcripts are stored.** Each rule keeps only a paraphrase of at most 12 words saying why it exists.
- **Logs never contain what you said.** They record intents, counts and rule ids only.
- **It writes only its own data:**
  - the `tailor_state` and `tailor_busy` keys in Context Storage
  - the `tailor_style.md` file

  It never writes the platform's `user_profile.md` or `user_summary.md`.

### What it reuses instead of asking
- **Your OpenHome memory.** When you open Tailor it reads `user_profile.md` and `user_summary.md` once, read-only. That gives it your first name, so it can greet you without asking. It also picks up up to two notes the platform has already made about how you like to be spoken to, such as "you like short, direct answers", and mentions them after your rules. The Agent already sees those notes, so Tailor doesn't copy them into rules.
- **The live conversation.** Learning uses the session's own message history, so there's nothing to set up and no separate log.

### How it differs from existing abilities
- **Memory Mirror** audits and corrects facts the assistant believes about you. Tailor changes how the assistant talks. They work well together.
- **Conversation Insights Coach** coaches your speaking habits. Tailor tunes the assistant's speaking habits.
- **Jarvis Prime**, **Social Memory** and **Decision Journal** remember things you mention. Tailor remembers how you want to be spoken to.

## Example Conversation
> **User:** "What's the weather tomorrow?"
> **AI:** "Tomorrow in Leeds looks mild, with a high of fourteen and a low of eight. There's a gentle breeze from the west and a small chance of showers in the late afternoon, so you might want..."
> **User:** "Too long. Just the high and whether it rains."
>
> *(a couple of minutes later)*
>
> **User:** "And Saturday?"
> **AI:** "High of twelve, rain likely after lunch."
>
> **User:** "Tailor."
> **AI:** "Sam, I've learned one thing about how you like me to talk. Rule one: for weather, give only the high and the rain chance. That's all. You can ask why, or tell me to change one."
> **User:** "Why?"
> **AI:** "I picked that up today: you asked for a shorter weather answer. Keep it, change it, or forget it?"
> **User:** "That's all."
> **AI:** "Okay. Ask me anytime."
