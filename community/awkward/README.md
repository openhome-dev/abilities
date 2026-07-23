# AWKWARD 🎭 — The Social Flight Simulator

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@MMEHDI0606-lightgrey?style=flat-square)

## What It Does

Practice the conversations you dread — out loud. AWKWARD is a voice-based
social flight simulator where the agent *becomes* the other person, in a
distinct voice, and runs a structured, escalating scene. When the scene ends,
the agent flips back to Coach mode and delivers a scored debrief: your best
moment, your exact crack moment, and one named tactic for next time.

The current build ships as a single, fully fleshed-out scenario — **The
Auntie**, the shaadi-season interrogation — with Rukhsana Auntie voiced
through [Uplift AI](https://upliftai.org)'s native Urdu voice models, on top
of a scenario-agnostic engine (rounds, persona escalation, dual-voice TTS,
LLM-as-judge scoring). Adding a new scenario back in (Crush, Interview, or
anything else) is one dictionary entry in the `SCENARIOS` registry — the
engine (`run_scene` / `character_reply` / `judge`) never special-cases a pack
by name.

## Suggested Trigger Words

- "washroom"

(Any trigger word works — the Ability doesn't inspect which one fired. Set
whatever fits your Agent's personality in the dashboard.)

## Setup

- **No API keys required for the base build.** OpenHome supplies the LLM
  behind `text_to_text_response()` itself.
- **Optional — Uplift AI Urdu voice for Auntie:** sign up for a free API key
  at [platform.upliftai.org](https://platform.upliftai.org) (free tier: 10
  minutes of TTS/month). In the dashboard, declare an API key named exactly
  `UPLIFT_VOICE_API` under **Ability Behavior → API Keys**, then set its
  value under **Settings → API Keys**. A second key, `UPLIFT_VOICE_API_2`,
  can optionally be added as a backup if the primary key hits its quota
  mid-conversation — the Ability tries it automatically before falling back
  to the default ElevenLabs voice. If neither key is set, or Uplift's API is
  unreachable, Auntie automatically falls back to her ElevenLabs preset voice
  with zero configuration needed — the demo can never die on a voice failure.
- Set `USE_UPLIFT_AUNTIE = False` at the top of `main.py` to disable the
  Uplift layer entirely and run Auntie on ElevenLabs only.

## How It Works

1. Trigger the Ability. It opens directly into the Auntie scene (no menu —
   this build is scoped to a single scenario for now).
2. Auntie speaks first each round (`character_opens=True`), escalating
   through five rounds: greeting, career interrogation, comparison to more
   successful relatives, the rishta (marriage proposal) offensive, and a
   loving finale callback.
3. Her opening line is a fixed, verbatim Urdu greeting spoken through the
   Uplift voice; every subsequent line is LLM-generated in character, mixing
   natural Urdu and English the way an Islamabad auntie really talks.
4. Say an exit word ("bas", "stop", "enough", etc.) anytime to end the scene
   early and go straight to the debrief.
5. The engine hands the full transcript to an LLM-as-judge with a strict
   JSON output contract (score, verdict, best moment, crack moment, a named
   tactic) — parsed with a hardcoded fallback if the model ever returns
   malformed JSON, so a debrief can never fail to speak.

## Example Conversation

> **User:** "washroom"
> **AI (Auntie, Urdu voice):** "السلام علیکم بیٹا، کہاں جا رہے ہو؟"
> **User:** "Bas auntie, kaam se busy hoon."
> **AI (Auntie):** "Haw hai, itna kaam? Chalo baitho, mujhe sub batao..."
> *(the interrogation escalates through career, comparison, and marriage)*
> **User:** "bas"
> **AI (Coach):** "Okay, she's gone to get biryani. Calculating your Auntie
> Survival Rating, one sec... Your Auntie Survival Rating is 72 out of a
> hundred. Where you cracked: ... Your best moment: ... Coach's tip: ..."
