# PropertyPro — Voice Showing Tour Guide

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@adigitaltati-green?style=flat-square)
![Status](https://img.shields.io/badge/Status-Stage%201-blue?style=flat-square)

A voice-enabled residential showing companion for OpenHome. A visitor walks into a listed home, picks up the device on the table, and says **hello** to start a short room-by-room tour — with fair-housing-safe answers and unanswered questions saved for the listing agent.

Part of **Suite B** (Specialized Property Guides), alongside StayGuide and BizSpace.

---

## Scene

**Visitor path:**

1. Buyer/renter walks in, reads the note, says **hello**, tours with the speaker.
2. PropertyPro answers from the active listing packet and logs unknowns to `tour_questions.md`.
3. When the tour ends (idle or “done”), the device stays in PropertyPro: *“Closing the tour. Say hello to start again.”*

**Agent setup — target (future app):**

1. Place the speaker + note in the home.
2. Phone app: upload listing packet → connect speaker → select packet → start assistant → leave.

**Agent setup — Stage 1 stand-in:**

1. Ability ships with markdown fixtures under `fixtures/listings/`.
2. Default active listing is `1420-maple-richmond` (`propertypro_prefs.json` → `active_listing_id`).

---

## Trigger Words

Dashboard triggers must be **at least 4 letters** (OpenHome platform rule). Recommended:

| Phrase | What it does |
| --- | --- |
| `"hello"` | Start the showing tour |
| `"start tour"` / `"begin tour"` | Same as hello |
| `"property pro"` | Same as hello |

**In-tour / lobby phrases** (work after the ability is already running; not all are valid dashboard triggers):

| Phrase | What it does |
| --- | --- |
| `"hi"` / `"hello"` / `"start tour"` | Restart the tour from the first room (or leave the closed-tour lobby) |
| room names (`"kitchen"`, `"living room"`, …) | Jump to that room |
| `"next"` / `"go back"` | Move along the tour order |
| `"what's the agent's number"` | Speak listing-agent name + phone |
| `"text the agent"` / `"call the agent"` / `"email …"` | Stage 1: explain send isn’t wired yet; speak the agent’s number; questions stay on the list |
| `"done"` / `"goodbye"` / `"end tour"` | Close this tour session → lobby |

---

## What It Answers (and what it won't)

**From the listing packet (safe):** beds/baths, sq ft, price, HOA fee, inclusions/exclusions, systems updates, room notes + dimensions, school *assignment* (name only, no ratings), agent contact.

**Redirect (fair housing / customary practice):**

- Crime / “is this neighborhood safe?” → point to official sources; do **not** recite crime stats or opinions.
- School *quality* → assignment if known + public evaluation guidance; no “good/bad” rankings.
- Who lives here / protected-class suitability → hard refuse (no steering, no demographics).

**Missing facts:** *“I don’t have that in my notes. I’ve added that to the agent’s question list.”* → append `tour_questions.md`.

A `fair_housing.md` knowledge base ships with the ability. This is product guardrails, not legal advice to consumers or brokers.

---

## Stage 1 features

- [x] Hello → greet → room tour → visitor-driven Q&A
- [x] Richer room notes + dimensions from markdown listing packets
- [x] Fair-housing redirects / hard refusals
- [x] Unanswered questions → `tour_questions.md`
- [x] Closed-tour **lobby** (stay in PropertyPro; say hello to start again)
- [x] Three mock listing fixtures
- [x] `knowledge_gaps.json` for product/schema failures
- [ ] Email `tour_questions.md` via `send_email()`
- [ ] Twilio SMS / outbound TTS call

**Out of scope for Stage 1:** buyer search portal, seller CMA / pricing advice, live crime APIs spoken aloud, two-way call bridge, CRM / lead capture, phone-app upload.

---

## Mock listing (testing)

| ID | Property | Why it exists |
| --- | --- | --- |
| `1420-maple-richmond` | Full craftsman SFH | Happy-path tour with systems + inclusions |

Packet lives under [`fixtures/listings/`](fixtures/listings/). There's no voice command to
switch which listing is active -- it's read once from `propertypro_prefs.json` at startup
-- so only the one listing an install actually tours is included here.

---

## Setup

### 1. Install the ability

Push or install PropertyPro and set dashboard triggers to at least:

`hello`, `start tour`, `begin tour`, `property pro`

### 2. Active listing

The only listing shipped is `1420-maple-richmond`, set as `active_listing_id` in `propertypro_prefs.json` on first run. Add more fixtures under `fixtures/listings/` and edit that file to tour a different one -- there's no voice command for it yet.

### 3. Contact / delivery (Stage 1)

Email and Twilio sends are **not** wired yet. Contact asks speak the listing agent’s phone (TTS-friendly) and keep `tour_questions.md` updated.

---

## Example conversation

**Visitor:** “Hello.”

**PropertyPro:** “Hi — welcome to Maple Avenue Craftsman. I’ll walk you through the main spaces, and you can ask me questions anytime. I’m here for facts about this property — for neighborhood topics like crime or demographics, I’ll point you to official sources rather than give opinions. We’ll begin in the foyer.”

**PropertyPro:** “You’re in the foyer. Room dimensions 11 by 8. A classic craftsman entry with original oak trim, a built-in bench niche, and soft light from the sidelight windows. The hardwood continues straight into the living room ahead.”

**Visitor:** “What’s the square footage?”

**PropertyPro:** “About 1,840 square feet.”

**Visitor:** “Is this a safe neighborhood?”

**PropertyPro:** “I don’t give crime opinions or stats. You can check the public safety open data and local police resources linked in my notes.”

**Visitor:** “Text the agent.”

**PropertyPro:** “I can’t send messages from this device yet. Avery Chen’s number is 5 5 5, 0 1 0, 1 4 2 0. Your questions are saved on the agent’s list.”

**Visitor:** “We’re done.”

**PropertyPro:** “Closing the tour. Say hello to start again.”

**Visitor:** “What’s the price?”

**PropertyPro:** “The tour is closed. Say hello to start again.”

---

## Project layout

```
community/property-pro/
├── README.md
├── main.py
├── fair_housing.md
└── fixtures/listings/*.md
```

Runtime files, written by the ability, not committed: `propertypro_prefs.json`, `tour_questions.md`, `knowledge_gaps.json`

---

## Related

- Suite A sibling: [`community/town-hall`](../town-hall/) — voice flow, prefs, gap logging patterns
- OpenHome email template (future): [`templates/send-email`](../../templates/send-email/)
- Twilio SMS / outbound call (future): [`community/Twilio-SMS`](../Twilio-SMS/)

---

## Status

Stage 1 is implemented and live-testable: hello → room beats → Q&A → fair-housing redirects → question logging → lobby until hello. Default listing: Maple Avenue Craftsman. Email/Twilio still deferred.
