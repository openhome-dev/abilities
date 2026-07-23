# CRUSH 💘 — sibling to AWKWARD

Practice the talking stage, out loud. CRUSH is a voice-based social flight
simulator — the agent becomes Maheen, the crush you've been meaning to talk
to, in a distinct voice, and runs a live cafe scene. When you end it, the
agent flips back to Coach mode and delivers a scored debrief: your best
moment, your exact crack moment, and one named tactic for next time.

A sibling Ability to [AWKWARD](../Awkward) — same engine shape (persona +
escalation + dual-voice TTS + LLM-as-judge), trimmed to a single scenario with
no menu: trigger it and you're straight into the scene.

**Trigger word:** "love"

Maheen opens the scene with a fixed, curt Urdu line — "کیا مسئلہ ہے تمہیں؟"
("what's your problem?") — spoken through [Uplift AI](https://upliftai.org)'s
`dha-teen-girl` voice (burger-Urdu teen, dramatic), before any LLM generation.
From there it's up to you. Her voice falls back to an ElevenLabs preset, then
the Agent's default voice, if Uplift is ever unavailable — the demo can never
go silent on a voice failure.

Her difficulty is randomly rolled each time — 50/50 dry or full menace — so
no two runs feel the same.

**Setup:** no API keys required for the base build (OpenHome supplies the LLM
behind `text_to_text_response()` itself). Optional Uplift voice: declare an
API key named exactly `UPLIFT_VOICE_API` under **Ability Behavior → API
Keys**, value set under **Settings → API Keys** (free tier, 10 min/month). An
optional backup key `UPLIFT_VOICE_API_2` is tried automatically if the
primary hits its quota. Set `USE_UPLIFT_MAHEEN = False` at the top of
`main.py` to disable Uplift entirely and run on ElevenLabs only.

## Example Conversation

> **User:** "love"
> **AI (Coach):** "Scene starts now. You spot Maheen alone at a cafe near
> campus. You walk up. Go."
> **AI (Maheen, Uplift voice):** "کیا چاہیے تمہیں؟"
> **User:** "Hey, don't I know you from class?"
> **AI (Maheen, Uplift voice):** *(dry or menace, rolled at random)* "Maybe.
> Do you usually open with a maybe?"
> *(banter continues for a few exchanges)*
> **User:** "stop"
> **AI (Coach):** "Aaand scene! Calculating your rizz score, one sec... Your
> Rizz Score is 78 out of a hundred. Where you cracked: ... Your best moment:
> ... Coach's tip: ..."
