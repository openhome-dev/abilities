# First Aid Hero

**First Aid Hero** is an interactive, voice-guided emergency first-aid assistant built for OpenHome agents. It provides clear, practical, step-by-step physical instructions for life-threatening medical emergencies (Choking, Severe Bleeding, CPR, Burns) and dynamically generates custom protocols using LLM for any other medical situation.

---

## Features

- **Standard Triage Protocols:** Pre-programmed, immediate physical instructions for choking, severe bleeding, burns, and CPR.
- **Realistic Household Supplies:** Instructions assume no medical kit is on hand — focusing on everyday items like tap water, clean t-shirts, towels, or bare hands.
- **Dynamic Protocol Generation:** Leverages LLM to produce safe, structured first-aid steps for custom emergencies (e.g. snake bites, allergic reactions, cuts).
- **Mid-Flow Question Answering:** Ask any question during a step (e.g. *"what if he vomits?"*) and the agent answers directly without losing your place.
- **CPR Cadence Assistant:** Audio-guided 30-compression rhythmic counting cadence and rescue breath prompts.
- **Emergency Room & Hospital Recommender:** Suggests nearest local medical centers, transport tips, and regional emergency helpline numbers (e.g. 1122, 911, 999, 112).
- **Humane Voice Navigation:** Empathetic conversational navigation (`next`, `back`, `repeat`, `no` / pause, `exit`).

---

## Trigger Words

Activate First Aid Hero using any of the following phrases:
- `"first aid hero"`
- `"first aid"`
- `"medical emergency"`
- `"first aid guide"`
- `"emergency first aid"`
- `"start first aid"`

---

## Exit Words

Say any of the following words at any time to immediately stop execution and exit:
- `"exit"`
- `"stop"`
- `"quit"`
- `"cancel"`
- `"end"`
- `"bye"`
- `"goodbye"`

> **Note:** `"done"` is a *navigation* word — it advances to the next step, it does **not** exit.

---

## Usage Flow

1. Say **"first aid hero"** or **"medical emergency"**.
2. State the emergency (e.g., *"choking"*, *"bleeding"*, *"burns"*, *"CPR"*, or say *"something else"* to describe your situation).
3. Follow the spoken step-by-step guidance.
4. Say **"next"** or **"done"** when ready to advance, **"back"** to repeat the previous step, **"repeat"** to hear the current step again, or **"no"** / **"wait"** to pause.
5. Ask any question mid-step (e.g. *"how hard should I press?"*) and the agent answers without losing your place.
6. Say your city or area (e.g. *"I am in Shamsabad"*) at any time to get the nearest emergency hospital.

---

## Disclaimer

*First Aid Hero is designed as a bystander reference tool and does NOT replace professional emergency medical services (EMS). Always contact your local emergency service (e.g., 911, 112, 999, 1122) immediately during severe medical emergencies.*
