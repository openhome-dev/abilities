# Privacy And User Manager

Single Background Daemon that owns **Bluetooth-aware speaking style** +
**multi-user identity & isolation** for an OpenHome agent. Three
responsibilities live in one process — Bluetooth scanning, recent-chat
mirroring, and per-user state — so they share state and timing without
needing inter-daemon coordination.

## System overview — how the pieces fit together

This daemon is the *core* of a small two-ability system. It pairs with
one companion Skill — **Cross User Privacy Guard** — to fully cover
the multi-user privacy contract. The daemon owns continuous state; the
Skill closes a same-session leak that injected rules can't reach
alone (LLM session memory). Both abilities should be assigned to the
same agent.

```
                                  ┌──────────────────────────────────┐
                                  │   OpenHome Personality (LLM)     │
                                  │   reads every .md in storage     │
                                  └──────────────────────────────────┘
                                                ▲
                                                │ auto-injected each turn
        ┌───────────────────────────────────────┼──────────────────────────────────────┐
        │                                       │                                      │
        │ ┌─ files written ────────────────┐    │     ┌─ files NOT auto-injected ──┐   │
        │ │  personal_audio_context.md     │ ───┘     │  user_<name>_notes.json    │   │
        │ │  active_user_context.md        │  ◄──┐    │  pum_settings.json         │   │
        │ │  bluetooth_diagnostic.md       │     │    │  pum_cursor.md             │   │
        │ │  recent_chat.md                │     │    └────────────────────────────┘   │
        │ └────────────────────────────────┘     │              ▲                      │
        │                                        │              │ JSON read/write      │
        │  ┌────────────────────────────────┐    │              │                      │
        │  │   Privacy And User Manager     │────┴──────────────┘                      │
        │  │   (Background Daemon — one     │                                          │
        │  │    process, polls every 3 s)   │                                          │
        │  └────────────────────────────────┘                                          │
        └────────────────────────────────────────────────────────────────────────────┘
                                                ▲                          ▲
                                                │ reads active_user_context │ reads
                                                │                          │
                                ┌───────────────┴────────────┐   ┌─────────┴──────────┐
                                │  Cross User Privacy Guard  │   │  Memory Inspector  │
                                │  (Skill — hotword-driven,  │   │  Reset User Data v2│
                                │   intercepts + speak()s    │   │  BT Diag Readout   │
                                │   refusal directly)        │   │  Voice Recognition │
                                └────────────────────────────┘   └────────────────────┘
```

### Why a daemon AND a Skill

The daemon owns **continuous state** (Bluetooth scans, audio-mode
files, per-user JSON, cross-session privacy). The Skill owns
**hotword-driven turn interception** for cross-user queries that the
daemon can't catch — because LLM session memory inside the agent's
conversation history can recall a previous user's notes regardless of
what the daemon's injected files say. The Skill bypasses the
Personality LLM entirely on those turns and speaks a refusal directly,
so session memory becomes irrelevant. See
**[Cross User Privacy Guard](../cross-user-privacy-guard/README.md)**
for that ability's design.

### Privacy guarantees and where they come from

| Guarantee | Source | Mechanism |
| --- | --- | --- |
| Cross-session cross-user isolation | daemon | All per-user data in `user_<name>_notes.json` (NOT auto-injected). Only the active user's bullets reach the prompt via `active_user_context.md`. |
| Sensitive specifics withheld on shared speaker | daemon | Tier 2 (private) bullets are spliced into `active_user_context.md` ONLY when audio mode is ACTIVE; otherwise the section reads `Withheld — shared speaker mode.` |
| Same-session cross-user isolation (by name) | Skill | Hotwords like `"do you have info on"` route the turn to the Skill, which reads the active user, refuses if the queried name differs, bypassing the Personality LLM. |
| Same-session cross-user isolation (paraphrased) | daemon prompt rules | `active_user_context.md` includes a verbatim refusal sentence + a 120 s "USER SWITCH JUST OCCURRED" banner so the Personality follows the cross-user rule on phrasings the Skill misses. Best-effort, not deterministic. |
| Audio-mode disclosure on first greet | daemon | "Conversation-opening directive" block at the top of `personal_audio_context.md` instructs the Personality to mention the audio mode on its first reply; sticky in first-greet phrasing until the daemon observes the user's first message. |
| User can disable audio-mode announcement | daemon | Verbal `"stop announcing audio mode"` writes `pum_settings.json {announce_audio_mode: false}`; the directive becomes a no-op telling the Personality not to mention audio mode. |

### Deploying the whole system on an agent

The OpenHome dashboard (or `openhome-cli assign --agent <id>
--capabilities <id1>,<id2>,...`) needs to attach BOTH:

1. **Privacy And User Manager** — `category: background_daemon`
2. **Cross User Privacy Guard** — `category: skill`

The other read-only skills (Memory Inspector, Reset User Data v2,
Bluetooth Diagnostic Readout, Voice Recognition) are optional but
useful — they all interoperate via the same context files this daemon
writes.

## What it does

### 1. Bluetooth-aware speaking style
Scans `system_profiler SPBluetoothDataType -json` every 3s via Local
Link's `exec_local_command`. Classifies each device with its
`device_minorType` field (primary signal) plus A2DP/HFP service
advertisement (secondary) and a legacy keyword fallback:

| `device_minorType` | Treated as |
| --- | --- |
| Headphones / Headset / Earbuds / HeadsetMicrophone | private (ACTIVE when connected) |
| Speaker / Speakers / Loudspeaker | public-audio (does NOT flip ACTIVE) |
| anything else with A2DP/HFP | audio, public |

Custom-named AirPods like `FreLia27` are still classified correctly
because the classifier looks at `device_minorType`, not the name.

Writes:
- **`personal_audio_context.md`** — current mode + a
  "Conversation-opening directive" block at the top. The Personality
  reads the directive on its next reply and announces the audio mode
  naturally on the user's first message. The directive is **sticky in
  first-greet mode until the daemon observes the user's first
  message** — that way the announcement actually fires even if the
  daemon scans the file several times before the user speaks. After
  the first message the directive transitions to steady-state
  phrasing; on later state changes it flips to transition phrasing
  ("you just connected …, can I speak more freely?" / "private audio
  disconnected, I'll keep things private from now on"). This is the
  reliable substitute for BG-daemon `send_interrupt_signal()` +
  `speak()`, which is unreliable on this build.
- **`bluetooth_diagnostic.md`** — pure developer telemetry, no privacy
  framing, so the persona will recite it. Pair with the existing
  **Bluetooth Diagnostic Readout** skill (`"read bluetooth
  diagnostic"`) for a `speak()`-direct readout.

#### Disabling the audio-mode announcement

Some users find the audio-mode greeting noisy. Toggle it off
verbally — no hotword needed, the daemon's prefilter catches it
deterministically:

| Say | Effect |
| --- | --- |
| "stop announcing audio mode" / "don't tell me about audio mode" / "disable bluetooth announcement" / "mute audio mode" | Sets `announce_audio_mode: false` in `pum_settings.json`. The directive in `personal_audio_context.md` becomes a no-op that explicitly tells the Personality NOT to mention audio mode unless asked. |
| "start announcing audio mode" / "resume audio announcement" / "enable bluetooth notification" | Re-enables. |

The audio-mode **rules** (disclosure decisions on private vs. shared)
keep working when announcements are disabled — only the proactive
greeting line is suppressed. The setting persists across sessions; to
reset, run **Reset User Data v2** or delete `pum_settings.json`
manually.

### 2. Recent chat mirror
Mirrors the last 10 user/assistant turns of
`agent_memory.full_message_history` into **`recent_chat.md`**. Used by
this daemon and other capabilities as a fallback when
`worker.current_transcript` is empty (it usually is on this build) and
`agent_memory` is stale.

### 3. Multi-user identity & two-tier privacy
Polls the latest user message every 3s via a 3-source fallback chain
(`agent_memory` → `recent_chat.md` → `pum_cursor.md` for dedupe). A
regex prefilter (`IDENTIFY_SIGNAL`, `REMEMBER_SIGNAL`) skips most chat
without an LLM call. Anything that passes goes to a JSON-classification
LLM call.

**Storage — single per-user JSON, structurally cross-user-private:**

| File | Auto-injected? | Contents |
| --- | --- | --- |
| `user_<name>_notes.json` | **no** (`.json` is stored only) | Both tiers: `public_items[]` (interests, hobbies, food preferences) and `private_items[]` (PINs, addresses, phone numbers, financials, medical specifics) |

OpenHome auto-injects every `.md` file in the agent's storage into the
Personality prompt. So if Freddie's notes were in
`user_freddie_public.md`, they'd reach Maya's prompt too — silent
cross-user leakage. By keeping ALL per-user data in JSON (which is
NOT auto-injected) and only splicing the **active** user's items into
`active_user_context.md`, cross-user privacy becomes structural rather
than rule-policed.

Migration: if the agent's storage already contains older
`user_<name>_public.md`, `user_<name>_info.md`, or
`user_<name>_private.json` files (e.g. from a previous community
ability that used the older two-file layout), they are read once on
first lookup, their bullets folded into the consolidated JSON, then
DELETED so they stop leaking via auto-injection.

Sensitivity defaults to `sensitive` when the LLM is ambiguous. A regex
post-check upgrades obvious tokens (PIN-like 4+ digit runs near
"pin/passcode", `$<digits>`, full street addresses, phone-number
patterns) to sensitive even if the LLM called them public.

**`active_user_context.md`** is recomposed on every active-user change,
audio-mode flip, or new note. It always includes Tier 1 public notes;
it splices in Tier 2 private bullets **only when audio mode is
ACTIVE**. On INACTIVE/UNKNOWN it emits `Withheld — shared speaker
mode.` So on a shared speaker the sensitive bytes literally are not in
the Personality's prompt — leakage is structurally impossible, not just
rule-policed.

## Files written / read

| File | Type | Auto-injected? | Purpose |
| --- | --- | --- | --- |
| `personal_audio_context.md` | own | yes | Audio mode + conversation-opening directive + audio-mode rules |
| `bluetooth_diagnostic.md` | own | yes | Pure debug telemetry (no privacy framing — persona will recite) |
| `recent_chat.md` | own | yes | Last 10 turns — fallback message recovery for daemon and skills |
| `active_user_context.md` | own | yes | Current user + behavioral rules + Tier 1 public + (only in ACTIVE) Tier 2 private |
| `user_<name>_notes.json` | own | no | All per-user data (public + private items). Cross-user-private by construction — not auto-injected. |
| `pum_cursor.md` | own | yes | Last-processed message hash, dedupe across loop ticks |
| `pum_settings.json` | own | no | User-toggleable preferences (currently: `announce_audio_mode`) |

## Files this daemon does NOT touch

- `enrolled_speakers.json` (Voice Recognition's domain)
- `user_profile.md`, `user_summary.md` (OpenHome's reserved memory files)

## Tunables (top of main.py)

- `POLL_INTERVAL = 3.0` — scan/mirror cadence.
- `HISTORY_SIZE = 10` — turns mirrored into recent_chat.md.
- `IDENTIFY_SIGNAL` / `REMEMBER_SIGNAL` — prefilter regexes.
- `NAME_BLACKLIST` — words that look like names but aren't.
- `_looks_obviously_sensitive` — defense-in-depth post-check.

## Deploy notes

Two abilities to attach to the same agent:

1. **Privacy And User Manager** (this folder) — `category: background_daemon`
2. **[Cross User Privacy Guard](../cross-user-privacy-guard/)** — `category: skill`

If the agent already has another BG daemon attached that writes the
same context files (`personal_audio_context.md`,
`active_user_context.md`, `recent_chat.md`), unattach it first — only
one BG daemon fires reliably per agent, and shared file state would
race.

Bluetooth detection requires **Local Link** running on the user's
machine (it's what routes `system_profiler` calls back to the local
shell). Without Local Link, the daemon falls back gracefully to
INACTIVE / shared-speaker mode and the agent announces this on first
greet. The privacy story stays intact under that fallback because
shared-speaker mode is the more conservative behavior.

## Verification (run locally — Bluetooth scan needs Local Link)

1. **First greet, headphones connected:** AirPods on → open chat → first
   reply should mention "I see you're on private audio…" and offer to
   speak more freely.
2. **First greet, speaker only:** AirPods off → open chat → first reply
   should mention "shared speaker, I'll keep private things private."
3. **Transition:** mid-session, plug/unplug AirPods → within ~90s the
   next reply should mention the flip.
4. **User identification:** say "I'm Freddie" → `active_user_context.md`
   should now show `Current user: Freddie`.
5. **Sensitive note on private audio:** while AirPods on, say "remember
   my bank pin is 4321" → `user_freddie_notes.json` should contain the
   bullet under `private_items` (not under `public_items`). The
   **Private info** section of `active_user_context.md` should be
   populated.
6. **Sensitive note on speaker:** switch to speaker, ask "what do you
   know about me" — agent should NOT mention the PIN; the **Private
   info** section of `active_user_context.md` should read `Withheld —
   shared speaker mode.`
7. **Cross-user isolation:** say "I'm Maya"; ask "tell me about
   Freddie" — agent (via the Cross User Privacy Guard Skill) should
   refuse with *"That's another user's private information — I can't
   share it with you."*
8. **Reset between test users:** delete `user_<name>_notes.json` and
   `active_user_context.md` from the agent's storage to start clean.

## Why a single BG daemon (not three)

The three responsibilities — Bluetooth scanning, chat-history
mirroring, and per-user state — could in principle live in separate
daemons. They share state in practice (audio mode gates Tier 2
disclosure; user-switch detection needs the chat mirror; the cursor
file dedupes both audio and user-state writes), so splitting them adds
file-coordination overhead without reducing complexity. And on
OpenHome, only one BG daemon fires reliably per agent in testing, so a
single-process design is the more robust route.
