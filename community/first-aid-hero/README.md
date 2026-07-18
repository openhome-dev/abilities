# 🚑 First Aid Hero

A hands-free, voice-first emergency first-aid guide built on OpenHome. It delivers calm, step-by-step medical instructions during critical emergencies — no screen, no hands needed. At the end of every session it assesses severity and recommends the nearest appropriate hospital in your city.

All steps and prompts are designed in short, simple, plain English to be clear under extreme pressure.

**Release:** v7 &nbsp;|&nbsp; **Capability ID:** 7197 &nbsp;|&nbsp; **Voice:** Daniel (ElevenLabs — deep, calm, authoritative British male)

---

## Triggers

Say any of these phrases to activate:

```
emergency first aid
first aid hero
cpr guide
choking emergency
bleeding emergency
first aid help
```

---

## Emergencies Supported (Simplified Instructions)

| Emergency | Severity | Step Details Spoken |
|---|---|---|
| **Choking** | 🔴 CRITICAL | 1. Ask: can you cough? If yes, tell them to keep coughing.<br>2. Stand behind them. Wrap arms around waist.<br>3. Place fist just above belly button, thumb side in.<br>4. Grab fist with other hand. Push in and up — hard and fast.<br>5. Do 5 thrusts. Repeat until object is out or they collapse. |
| **Severe Bleeding** | 🔴 CRITICAL | 1. Find where blood is coming from.<br>2. Press clean cloth firmly onto wound.<br>3. Keep pressing. Do not remove cloth to check.<br>4. If blood leaks through, add another cloth on top.<br>5. If it doesn't stop after 10 mins, press harder until help arrives. |
| **Burns** | 🟠 HIGH | 1. Run cool water over burn for 10 minutes.<br>2. Do not use ice, butter, toothpaste, or creams.<br>3. Remove rings, bracelets, or tight clothing near the area before it swells.<br>4. Cover loosely with cling film or clean plastic bag.<br>5. Watch for dizziness, pale skin, or fast breathing (shock). |
| **CPR** | 🔴 CRITICAL | 1. Lay flat on back on the floor.<br>2. Heel of one hand on center of chest. Other hand on top.<br>3. Push down hard and fast at 120 bpm (Voice counts 1 to 30).<br>4. Give 2 slow rescue breaths. Repeat cycle. |
| **Custom** (LLM) | Assess-based | Generates safe, brief physical actions dynamically (e.g. stroke, poisoning). |

---

## How It Works

1. **Direct Triage** — Skips greetings and asks: *"First Aid Hero on. What is the emergency? Say: choking, bleeding, CPR, burns, or describe it."*
2. **Location Capture** — Asks: *"What city are you in? I will find the nearest hospital."*
3. **Walkthrough & Navigation** — Navigate steps completely hands-free:
   - `next` / `go ahead` — Move to the next step
   - `back` / `previous` — Return to the previous step
   - `repeat` / `again` — Replay the current step
   - `done` / `resolved` — Emergency resolved, triggers hospital recommendation
   - `stop` / `exit` / `quit` — Force-exit (hospital recommendation still spoken)
4. **CPR Voice Metronome** — Counts 1 to 30 at 120 bpm tempo, then prompts for 2 rescue breaths. Loops until you say `done` or `revived`.
5. **Severity Assessment** — Classifies the emergency as CRITICAL, HIGH, or MODERATE.
6. **Nearest Hospital Recommendation** — Based on your city and emergency type, the agent recommends the ideal department, real hospital names, emergency helpline, and transport tip.
7. **Natural Response Pacing** — Waits 2.5 seconds after you stop speaking before responding, avoiding cutting you off.

---

## Example Session

```
You:   "first aid help"
Agent: "First Aid Hero on. Call emergency services now if you haven't. What is the emergency? Say: choking, bleeding, CPR, burns, or describe it."

You:   "choking"
Agent: "What city are you in? I will find the nearest hospital."

You:   "Lahore"
Agent: "Choking guide. After each step, say: next, back, repeat, or done."
       "Step 1: Ask the person: can you cough? If yes, tell them to keep coughing hard. Say next, back, or done."

You:   "next"
Agent: "Step 2: Stand behind them. Put your arms around their waist. Say next, back, or done."

You:   "done"
Agent: "Good. Help is on the way."
       "This is critical. Go to the emergency room immediately. Do not wait."
       "Go to the Cardiac Intensive Care Unit. Nearest hospitals in Lahore: Services Hospital Lahore or Lahore General Hospital. Call 1122 for an ambulance. Keep the patient still and do not give food or water."
```

---

## Running Tests

```bash
python -X utf8 test_runner.py
```

22 test cases — all passing. Covers choking, bleeding, burns, CPR, custom LLM emergencies, severity levels, hospital recommendation, and all edge cases.
