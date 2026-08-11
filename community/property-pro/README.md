# PropertyPro — Voice Showing Tour Guide

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@ileana--pr-lightgrey?style=flat-square)
![Status](https://img.shields.io/badge/Status-Early-yellow?style=flat-square)

A voice-enabled residential showing companion for OpenHome. A visitor walks into a listed home, picks up the device on the table, and says **hello** to start a short room-by-room tour — with fair-housing-safe answers and unanswered questions saved for the listing agent.

Part of **Suite B** (Specialized Property Guides), alongside StayGuide and BizSpace.

---

## Scene

**Visitor path (Stage 1 and beyond):**

1. Buyer/renter walks in, reads the note, says **hello**, tours with the speaker.
2. PropertyPro answers from the active listing packet; logs gaps; optional contact/email.

**Agent setup — target (future app):**

1. Place the speaker + note in the home.
2. Phone app: upload listing packet → connect speaker → select packet → start assistant → leave.

**Agent setup — Stage 1 stand-in:**

1. Load a markdown packet (`fixtures/listings/…` or storage) and set `active_listing_id`.
2. Same visitor path from hello onward.

---

## Trigger Words

| Phrase | What it does |
| --- | --- |
| `"hello"` / `"hi"` | Start (or resume) the showing tour |
| `"start tour"` / `"begin tour"` | Same as hello |
| `"next room"` / `"go back"` | Move through the room path |
| `"text the agent"` / `"call the agent"` | On-the-spot contact (Twilio when configured) |
| `"email my questions"` / `"send questions to the agent"` | Email `tour_questions.md` to the listing agent |
| `"what's the agent's number"` | Speak listing-agent contact from the packet |

Exact trigger list will be finalized in Dashboard config when `main.py` lands.

---

## What It Answers (and what it won't)

**From the listing packet (safe):** beds/baths, sq ft, price, HOA fee, inclusions, systems updates, room notes, school *assignment* (name only, no ratings), agent contact.

**Redirect (fair housing / customary practice):**

- Crime / “is this neighborhood safe?” → point to official sources; do **not** recite crime stats or opinions.
- School *quality* → assignment if known + public evaluation links; no “good/bad” rankings.
- Who lives here / protected-class suitability → hard refuse (no steering, no demographics).

**Missing facts:** *“I don’t have that in my notes — I’ll add it for the listing agent.”* → append `tour_questions.md`.

A `fair_housing.md` knowledge base ships with the ability so the model stays on the right side of FHA / steering rules. This is product guardrails, not legal advice to consumers or brokers.

---

## Planned Features (Stage 1)

- [ ] Hello → greet → room tour → Q&A → exit voice flow
- [ ] Listing packet grounded answers
- [ ] Fair-housing KB (redirects + hard refusals)
- [ ] Unanswered questions → `tour_questions.md`
- [ ] Optional email of that file via `CapabilityWorker.send_email()`
- [ ] Optional on-the-spot Twilio SMS / TTS outbound call (with confirmation)
- [ ] Three mock listing fixtures for testing (see below)
- [ ] `knowledge_gaps.json` for product/schema gaps

**Out of scope for Stage 1:** buyer search portal, seller CMA / pricing advice, live crime APIs spoken aloud, two-way call bridge, CRM / lead capture.

---

## Mock listings (testing)

Fictitious packets used while building and demoing:

| ID | Property | Why it exists |
| --- | --- | --- |
| `1420-maple-richmond` | Full craftsman SFH | Happy-path tour with systems + inclusions |
| `88-canal-loft-richmond` | Condo + HOA | Fees, inclusions, partial school data |
| `7-pine-sparse-chesterfield` | Thin ranch packet | Forces question logging + contact demos |

Listing packets are markdown under [`fixtures/listings/`](fixtures/listings/). Index: [`fixtures/LISTINGS.md`](fixtures/LISTINGS.md). Design detail: [`notes/PRODUCT_DISCOVERY.md`](notes/PRODUCT_DISCOVERY.md).

---

## Setup (preview)

### 1. Install the ability

Add PropertyPro in the OpenHome Dashboard and set the trigger phrases above.

### 2. Load a listing packet

Point the ability at the active listing (pref `active_listing_id`). Stage 1 packets are **markdown** files under `fixtures/listings/` (or a user-uploaded `.md` packet). MLS sync comes later.

### 3. Optional delivery

| Channel | Requirement |
| --- | --- |
| Email questions list | SMTP config + `agent_email` on the listing packet (`send_email()`) |
| Text / call agent | Twilio prefs (same pattern as community Twilio-SMS) + agent phone on packet |

Without those, PropertyPro still speaks the agent’s number and always writes `tour_questions.md`.

---

## Example conversation

**Visitor:** “Hello.”

**PropertyPro:** “Hi — welcome to Maple Avenue Craftsman. I’ll walk you through the main spaces, and you can ask questions anytime. I’m here for facts about this property — for neighborhood topics like crime or demographics, I’ll point you to official sources rather than give opinions. We’ll begin in the foyer.”

**Visitor:** “Okay.”

**PropertyPro:** “You’re in the foyer — room dimensions 11 by 8. Original craftsman woodwork, opens into the living room.”

**Visitor:** “What’s the square footage?”

**PropertyPro:** “About 1,840 square feet.”

**Visitor:** “Is this a safe neighborhood?”

**PropertyPro:** “I don’t give crime opinions. You can check the city’s public safety open data and local police resources — I’ve got those links in my notes for this market.”

**Visitor:** “When was the roof done?” *(on a sparse listing)*

**PropertyPro:** “I don’t have the roof age in my notes. I’ve added that to the agent’s question list.”

**Visitor:** “Text the agent.”

**PropertyPro:** “I’ll text Avery Chen with three questions from today’s showing at 1420 Maple. Send it?”

---

## Project layout (target)

```
community/property-pro/
├── README.md
├── fair_housing.md
├── fixtures/LISTINGS.md
├── fixtures/listings/*.md    ← listing packets (markdown)
├── notes/PRODUCT_DISCOVERY.md
├── main.py                   ← MatchingCapability (todo)
└── .openhome.json            ← ability manifest (todo)
```

---

## Related

- Suite A sibling: [`community/town-hall`](../town-hall/) — civic briefing patterns (voice flow, prefs, gap logging) we reuse here
- OpenHome email template: [`templates/send-email`](../../templates/send-email/)
- Twilio SMS / outbound call: [`community/Twilio-SMS`](../Twilio-SMS/)

---

## Status

Discovery scaffold in progress: README, `fair_housing.md`, markdown listing fixtures, and `notes/PRODUCT_DISCOVERY.md` are in place. Next: `main.py` for hello → tour → Q&A on the Maple fixture.
