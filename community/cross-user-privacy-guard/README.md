# Cross User Privacy Guard

Hotword-triggered Skill that **deterministically refuses** cross-user
privacy queries before the Personality LLM gets a chance to leak from
its session memory.

## Why this exists

The companion BG daemon **Privacy And User Manager** owns the
*structural* privacy contract: all per-user notes live in
`user_<name>_notes.json` (NOT auto-injected), and only the active
user's bullets reach the prompt via the daemon-composed
`active_user_context.md`. So **across sessions, cross-user privacy is
structural** — Maya's prompt simply has no Freddie data in it.

But within a single conversation, OpenHome appends every user turn to
the Personality's conversation history. If Freddie said "remember I
like dark coffee" earlier and Maya now asks "tell me about Freddie",
the Personality answers from conversation history regardless of how
strongly the daemon's injected files refuse. The daemon can write
warnings; it can't delete prior turns.

This Skill closes that hole. Hotword phrases like *"tell me about
Freddie"*, *"what do you know about Maya"*, *"who is Bob"*, *"the
previous user"* trigger this Skill *instead of* the Personality. It
refuses programmatically via direct `speak()` and never lets the
Personality LLM see the turn — making session memory irrelevant.

## How it works

1. **Hotword match.** OpenHome routes any user message containing one
   of `config.json`'s `matching_hotwords` to this Skill instead of the
   Personality.
2. **Recover the trigger text** via a 3-source fallback (because
   `worker.current_transcript` is often empty when a Skill triggers):
   `agent_memory.full_message_history` → `recent_chat.md` → bail with
   a clarification prompt.
3. **Indirect-reference check** (`PREV_USER_PATTERNS`): if the trigger
   contains *"the previous user"*, *"the other user"*, *"the person
   before me"*, etc. → refuse immediately via direct `speak()`.
4. **Name extraction** (`QUERIED_NAME_PATTERNS`): pull the first
   non-blacklisted capitalized word after the hotword phrase. Patterns
   try the strongest framing first (`tell me about <Name>`,
   `what does <Name> like`) before falling back to the loose
   `about <Name>` form. The blacklist catches articles, pronouns, and
   common follow-on words like *"the weather"*.
5. **Three-way decision** based on the extracted name:
   - **No name extracted** (e.g. *"tell me about the weather"*) → the
     Skill composes a normal short reply via `text_to_text_response`
     and speaks it. The hotword fired but no cross-user query exists.
   - **Name is a self-token** (`me`/`myself`) **or matches the active
     user** → the Skill reads `active_user_context.md`, asks the LLM to
     summarize the active user's *public* notes from that context, and
     speaks the summary. (Self-queries on shared speaker still respect
     the daemon's withheld-on-shared-speaker rules — only public
     bullets reach the prompt.)
   - **Name differs from the active user** → refuse via direct
     `speak()` of the canonical sentence *"That's another user's
     private information — I can't share it with you."*
6. **Always `resume_normal_flow()`** in a `finally` block so the agent
   doesn't get stuck if anything raised.

This three-way design is important: a hotword-triggered Skill *takes*
the turn from the Personality, so it must produce some reply on every
path. Pure "passthrough" doesn't work — the Personality won't fire
after the Skill claims the turn.

## Hotwords (broad on purpose)

The hotword list is deliberately broad so it intercepts the common
cross-user query patterns even on phrasings Privacy And User Manager
hasn't seen before:

```
tell me about / tell me what you know about / what do you know about
what does / info about / info on / anything about
any info on / any news on / news on / who is
the previous user / the other user / the person before / anyone else
```

Many of these will fire on innocent queries (*"tell me about the
weather"*, *"who is the president"*). The Skill's name-extraction +
blacklist + active-user comparison ensures it falls through to the
Personality on those cases — only actual cross-user queries get
intercepted.

## Files written

None. The Skill is read-only — it speaks the refusal and exits. The
canonical privacy state lives in the daemon's files.

## Files read

- `active_user_context.md` (written by Privacy And User Manager) —
  for the current active user name.
- `recent_chat.md` (written by Privacy And User Manager) — message
  recovery fallback.

## Pairs with

- **[Privacy And User Manager](../privacy-and-user-manager/README.md)**
  (BG daemon) — required. It owns `active_user_context.md` and
  `user_<name>_notes.json`. This Skill reads the active user from that
  context. Both abilities must be assigned to the same agent for the
  privacy contract to hold. See that ability's README for the
  full system-overview diagram showing how this Skill fits in.

## Why the broad hotwords don't accidentally refuse normal questions

The Skill does NOT refuse just because the hotword matched. The
refusal path only fires when:

- An indirect-reference phrase fires (*"the previous user"* etc.), OR
- A specific name is extracted AND that name is NOT the active user
  AND not a self-token.

For *"tell me about the weather"*: hotword matches → name extraction
finds `the` → blacklisted → no other match → composes a normal weather
reply via `text_to_text_response` and speaks it.

For *"tell me about me"* / *"tell me about myself"*: matches → extracts
`me`/`myself` → recognized as self-token → composes a self-summary
reply from the active user's public notes and speaks it.

For *"tell me about Freddie"* with active user Maya: matches →
extracts `Freddie` → not blacklisted, not active, not self → refuse
with the canonical sentence.
