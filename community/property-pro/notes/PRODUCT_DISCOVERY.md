# PropertyPro — Product Discovery (Stage 1)

Living design note for the showing tour guide. Implementation should follow this cut line before growing scope.

**Git base:** `add-property-pro` from `origin/dev` (includes merged town-hall #358).

---

## 1. Scene + trigger

**Scene:** Visitor enters a listed home. OpenHome device on a table. Card says: “Pick me up and say hello to start the tour.”

**Who prepared it (target future):** Listing agent places the speaker, opens a phone app, uploads the listing packet (`.md`), connects the speaker, selects that packet as active, arms PropertyPro, and leaves.

**Who prepared it (Stage 1):** Demo/dev loads a fixture from `fixtures/listings/*.md` (or a hand-authored packet in storage) and sets `active_listing_id`. Same visitor experience after hello.

**Who uses it:** Buyer, buyer’s agent, or open-house visitor.

**Triggers (planned):** `hello`, `hi`, `start tour`, `begin tour`, plus in-tour control / contact phrases.

**Mode:** Short companion turns. One beat per room. **Visitor-driven** — state facts, then wait. No trailing “what next?” prompts.

```text
hello → greet + fair-housing soft disclaimer
     → room path (from packet)
     → Q&A loop (packet | redirect | refuse | log)
     → exit (confirm questions saved)
     → optional email / on-demand SMS-call
```

---

## 2. Sample dialogue (Maple Avenue Craftsman)

**Visitor:** Hello.

**PropertyPro:** Hi — welcome to Maple Avenue Craftsman. I’ll walk you through the main spaces, and you can ask me questions anytime. I’m here for facts about this property — for neighborhood topics like crime or demographics, I’ll point you to official sources rather than give opinions. We’ll begin in the foyer.

**Visitor:** Okay.

**PropertyPro:** You’re in the foyer — room dimensions 11 by 8. Original craftsman woodwork, opens into the living room.

**Visitor:** Living room.

**PropertyPro:** You’re in the living room — room dimensions 16 by 14, working fireplace.

**Visitor:** What’s the square footage of the whole house?

**PropertyPro:** About 1,840 square feet.

**Visitor:** Kitchen. Do the appliances stay?

**PropertyPro:** You’re in the kitchen — room dimensions 12 by 14. Updated in 2021, quartz counters, gas range. Fridge, washer, and dryer convey. The seller’s freestanding bookshelf does not.

**Visitor:** When was the roof done?

**PropertyPro:** Roof was replaced in 2019.

**Visitor:** Is this a safe neighborhood?

**PropertyPro:** I don’t give crime opinions or stats. You can check Richmond’s public safety open data and local police resources — links are in my market notes.

**Visitor:** No thanks. Are the schools good?

**PropertyPro:** I don’t rate schools. This address is listed under Bellevue Elementary, Albert Hill Middle, and Thomas Jefferson High — please verify on the district site. Public report cards are the place to judge fit.

**Visitor:** Who lives around here? Is it diverse?

**PropertyPro:** I’m not able to discuss neighborhood demographics under fair housing guidelines. I can stick to facts about this property if you have another question.

**Visitor:** What’s the water heater age? *(switch to Pine Court sparse packet in other tests)*

On Maple (full packet): Water heater was replaced in 2018.

On Pine (sparse): I don’t have the water heater age in my notes. I’ve added that to the agent’s question list.

**Visitor:** Text the agent.

**PropertyPro:** I’ll text Avery Chen with your open questions from today’s showing at 1420 Maple. Send it?

**Visitor:** Yes.

**PropertyPro:** Sent.

**Visitor:** We’re done.

**PropertyPro:** That’s the main tour. I’ve saved two questions for the listing agent. Thanks for visiting — say hello anytime if you want to walk through again.

---

## 3. Fair-housing knowledge base

Runtime file: [`../fair_housing.md`](../fair_housing.md) (injected as ability context). Listing packets cannot override hard rules.

Summary:

| Topic | Behavior |
| --- | --- |
| Protected-class steering / “good for people like us” | Hard refuse |
| Neighborhood demographics (race, religion, etc.) | Hard refuse |
| Crime / “safe neighborhood” | Redirect to official sources; no spoken stats or vibes |
| School *quality* | Assignment OK if sourced; no ratings; point to public evaluation |
| Property facts in packet | Answer |
| Missing property facts | Log to `tour_questions.md` |

Product policy: even with HUD Apr 2026 clarification on school/crime *data*, Stage 1 keeps the safer customary practice — redirect crime; no school quality opinions.

---

## 4. Listing packet schema

Stage 1 packets are **markdown files**. Rationale: easy for agents to edit, matches OpenHome ambient `.md` injection, no parse layer required for the first slice.

Suggested sections (see fixtures for full examples):

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

Missing sections / `(unknown)` / `(not provided)` → log to `tour_questions.md` when asked. Do not invent facts.

Active listing pref (planned): `active_listing_id` → load `fixtures/listings/{id}.md` (or a user-uploaded packet path).

**Room tour beat rule:** for each room in tour order, speak label + dimensions when present (`room dimensions 11 by 8` — never `11x8` for TTS). Then the short note. If dimensions are unknown/missing, skip that clause. **Do not** end with “what would you like?” — wait for the visitor.

---

## 4b. Agent setup flow (future vs Stage 1)

**Future (ideal):**

1. Place speaker + “say hello” note  
2. Phone app → upload listing packet document  
3. Connect / pair speaker  
4. Select uploaded doc as active listing packet  
5. Start assistant → leave property  
6. Visitor: hello → tour  

**Stage 1:** fixtures or hand-authored `.md` + `active_listing_id` pref. No phone upload UI in this ability PR.

---

## 5. Mock fixtures

| File | Role |
| --- | --- |
| [`../fixtures/listings/1420-maple-richmond.md`](../fixtures/listings/1420-maple-richmond.md) | Full SFH happy path |
| [`../fixtures/listings/88-canal-loft-richmond.md`](../fixtures/listings/88-canal-loft-richmond.md) | Condo + HOA |
| [`../fixtures/listings/7-pine-sparse-chesterfield.md`](../fixtures/listings/7-pine-sparse-chesterfield.md) | Sparse packet / logging + contact stress test |

All addresses and agent contacts are **fictitious**.

---

## 6. `tour_questions.md` + delivery

**Always:** append unanswered property questions (and optional “please send me X links” follow-ups).

```markdown
## Showing — 1420 Maple Avenue — 2026-08-10 14:32
- Fence: is it shared with the neighbor?
- Visitor asked agent to send public-safety open-data links
```

**Email (optional):** `CapabilityWorker.send_email()` with `tour_questions.md` attached to `agent.email` when SMTP prefs exist. End of tour or on “email my questions.”

**On-the-spot (optional):**

| Ask | Action |
| --- | --- |
| Agent’s number? | Speak name + phone (TTS-friendly) |
| Text the agent | Twilio SMS after confirmation |
| Call the agent | Twilio outbound TTS summary (not a live bridge) |
| Email now | Immediate `send_email()` |

If Twilio/SMTP missing: speak contact + keep the file. Never pretend a send succeeded.

---

## 7. Voice-flow map (for `main.py` later)

1. Load prefs + `active_listing_id` → listing `.md` packet + `fair_housing.md`
2. Classify: start tour | room nav | property Q | fair-housing topic | contact | exit
3. Property Q → answer from packet or append `tour_questions.md`
4. Fair-housing topic → redirect/refuse snippets from KB
5. Contact → confirm → Twilio / email / speak fallback
6. Exit → summarize N saved questions → optional auto-email → `resume_normal_flow()`
7. Schema/product gaps → `knowledge_gaps.json`

Reuse Town Hall patterns: `MatchingCapability`, short spoken turns, persistent files, gap logging.

---

## 8. Non-goals (Stage 1)

- Phone app: upload packet, pair speaker, select active listing, arm assistant
- Buyer multi-home search / compare / criteria prefs
- Seller CMA or “should I buy / is it overpriced” advice
- Spoken crime stats or school ratings
- Live two-way call bridge (visitor ↔ agent)
- Gmail/Outlook inbox as a dependency
- Lead capture / CRM / showing scheduling
- StayGuide guest ops; BizSpace commercial zoning
- `main.py` until this note + fixtures feel right

---

## 9. Next implementation slice

1. Confirm this note + fixtures + `fair_housing.md`
2. Scaffold `main.py` + `.openhome.json` with hello → tour → Q&A on Maple fixture only
3. Add question logging, then email, then Twilio
