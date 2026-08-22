# PropertyPro — Product Discovery (Stage 1)

Living design note for the showing tour guide. Kept in sync with `main.py`.

**Branch / PR:** `add-property-pro` → `openhome-dev/abilities` `dev`.

---

## 1. Scene + trigger

**Scene:** Visitor enters a listed home. OpenHome device on a table. Card says: “Pick me up and say hello to start the tour.”

**Who prepared it (target future):** Listing agent places the speaker, opens a phone app, uploads the listing packet (`.md`), connects the speaker, selects that packet as active, arms PropertyPro, and leaves.

**Who prepared it (Stage 1):** Fixtures in `fixtures/listings/*.md`. Pref `active_listing_id` in `propertypro_prefs.json` (default `1420-maple-richmond`).

**Who uses it:** Buyer, buyer’s agent, or open-house visitor.

**Dashboard triggers (≥4 letters):** `hello`, `start tour`, `begin tour`, `property pro`.

**In-ability restart / lobby phrases:** also recognizes `hi`, `propertypro`, `showing tour` once the ability is already running.

**Mode:** Short companion turns. One beat per room. **Visitor-driven** — state facts, then wait. No trailing “what next?” prompts.

```text
hello → greet + fair-housing soft disclaimer + first room
     → Q&A / room nav loop
     → exit or 2× idle → “Closing the tour. Say hello to start again.”
     → lobby (stay in PropertyPro)
     → hello → restart tour
```

---

## 2. Sample dialogue (Maple Avenue Craftsman)

**Visitor:** Hello.

**PropertyPro:** Hi — welcome to Maple Avenue Craftsman. I’ll walk you through the main spaces, and you can ask me questions anytime. I’m here for facts about this property — for neighborhood topics like crime or demographics, I’ll point you to official sources rather than give opinions. We’ll begin in the foyer.

**PropertyPro:** You’re in the foyer. Room dimensions 11 by 8. A classic craftsman entry with original oak trim, a built-in bench niche, and soft light from the sidelight windows. The hardwood continues straight into the living room ahead.

**Visitor:** Living room.

**PropertyPro:** You’re in the living room. Room dimensions 16 by 14. A bright gathering room with a working brick fireplace, original crown molding, and a wide bay window that pulls in afternoon light.

**Visitor:** What’s the square footage of the whole house?

**PropertyPro:** About 1,840 square feet.

**Visitor:** Kitchen. Do the appliances stay?

**PropertyPro:** You’re in the kitchen. Room dimensions 12 by 14. Remodeled in 2021 with quartz counters, shaker cabinets, a gas range, and a deep farmhouse sink. It opens through French doors to the deck. Fridge, washer, and dryer convey. The seller’s freestanding bookshelf does not.

**Visitor:** When was the roof done?

**PropertyPro:** Roof: 2019.

**Visitor:** Is this a safe neighborhood?

**PropertyPro:** I don’t give crime opinions or stats. You can check the public safety open data and local police resources linked in my notes.

**Visitor:** Are the schools good?

**PropertyPro:** I don’t rate schools. This address is listed under Bellevue Elementary, Albert Hill Middle, and Thomas Jefferson High — please verify on the district site. Public report cards are the place to judge fit.

**Visitor:** Who lives around here? Is it diverse?

**PropertyPro:** I’m not able to discuss neighborhood demographics under fair housing guidelines. I can stick to facts about this property if you have another question.

**Visitor:** Text the agent.

**PropertyPro:** I can’t send messages from this device yet. Avery Chen’s number is 5 5 5, 0 1 0, 1 4 2 0. Your questions are saved on the agent’s list.

**Visitor:** We’re done.

**PropertyPro:** Closing the tour. Say hello to start again.

**Visitor:** What’s the square footage?

**PropertyPro:** The tour is closed. Say hello to start again.

**Visitor:** Hello.

*(tour restarts from foyer)*

### Sparse listing note (Pine Court — separate test)

On `7-pine-sparse-chesterfield`, systems/inclusions are missing. Asking for roof age yields:

> I don’t have that in my notes. I’ve added that to the agent’s question list.

---

## 3. Fair-housing knowledge base

Runtime file: [`../fair_housing.md`](../fair_housing.md). Loaded with the listing packet and used for grounded answers + hard redirects. Listing packets cannot override hard rules.

| Topic | Behavior |
| --- | --- |
| Protected-class steering / “people like us” | Hard refuse |
| Neighborhood demographics | Hard refuse |
| Crime / “safe neighborhood” | Redirect; no spoken stats |
| School *quality* | Assignment OK if sourced; no ratings |
| Property facts in packet | Answer |
| Missing property facts | Log to `tour_questions.md` |

---

## 4. Listing packet schema

Stage 1 packets are **markdown files** under `fixtures/listings/`.

```markdown
# Marketing name

- **id:** `listing-slug`
- **address:** …
- **price:** …
- **beds / baths:** …
- **sq ft:** …
- **hoa:** …

## Agent
## Seller welcome
## Tour order
## Rooms
### foyer
- **dimensions:** 11 by 8
- **note:** …
## Systems
## Inclusions
## Exclusions
## School assignment
## Redirect URLs
```

Missing sections / `(unknown)` / `(not provided)` → log when asked. Do not invent facts.

**Pref:** `active_listing_id` in `propertypro_prefs.json` → `fixtures/listings/{id}.md`.

**Room tour beat:** label + dimensions (spoken as `11 by 8`) + note. Skip dimensions if unknown. Do not end with “what next?”

---

## 4b. Agent setup flow (future vs Stage 1)

**Future:** place speaker → phone upload → pair → select packet → arm → leave → visitor hello.

**Stage 1:** fixtures + `active_listing_id`. No phone upload UI.

---

## 5. Mock fixtures

| File | Role |
| --- | --- |
| [`../fixtures/listings/1420-maple-richmond.md`](../fixtures/listings/1420-maple-richmond.md) | Full SFH happy path |
| [`../fixtures/listings/88-canal-loft-richmond.md`](../fixtures/listings/88-canal-loft-richmond.md) | Condo + HOA |
| [`../fixtures/listings/7-pine-sparse-chesterfield.md`](../fixtures/listings/7-pine-sparse-chesterfield.md) | Sparse packet / logging stress test |

All addresses and contacts are **fictitious**.

---

## 6. `tour_questions.md` + contact

**Always:** append unanswered property questions (and advice-request notes).

```markdown
## Showing — 1420 Maple Avenue — 2026-08-10 14:32
- Fence: is it shared with the neighbor?
- Visitor asked for pricing or offer advice
```

**Contact (Stage 1 implemented):**

| Ask | Action |
| --- | --- |
| Agent’s number? | Speak name + phone (digit-spaced for TTS) |
| Text / call / email the agent | Speak that send isn’t available yet + phone; keep question file |

**Not yet:** `send_email()` attachment, Twilio SMS/call.

---

## 7. Voice-flow map (`main.py`)

1. Load prefs + listing `.md` + `fair_housing.md`
2. Outer loop (showing-device mode): greet → `_tour_loop` → `_wait_for_hello`
3. Classify: room nav | property fact | crime | schools | demographics | contact | advice | exit
4. Property fact → deterministic handlers, else grounded LLM (`UNKNOWN` → log)
5. Exit / 2× empty listen → close line → lobby (do **not** resume normal flow)
6. Hello in lobby → restart
7. Hard failure / missing listing → `resume_normal_flow()` in `finally`

---

## 8. Non-goals (Stage 1)

- Phone app upload / pair / select / arm
- Buyer multi-home search / compare / criteria prefs
- Seller CMA or offer advice
- Spoken crime stats or school ratings
- Live two-way call bridge
- Gmail/Outlook as a dependency
- Lead capture / CRM / scheduling
- StayGuide / BizSpace features
- Working email or Twilio send from the showing device

---

## 9. Next implementation slice

1. Optional `send_email()` of `tour_questions.md`
2. Optional Twilio SMS / TTS outbound call with confirmation
3. Voice command to switch `active_listing_id` among fixtures
