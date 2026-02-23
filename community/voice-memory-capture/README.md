# Voice Memory Capture

**Voice Memory Capture** is a fully offline, private voice-based personal memory bank for OpenHome.

Users can instantly save anything they say ("remember that my dentist appointment is March 15th", "don't forget to buy dog food") and later retrieve it naturally ("what did I save about dentist?", "recap my memories", "how many days until dentist?").

All data lives locally in `voice_memory_entries.json`. No APIs, no cloud, no accounts — just voice, LLM classification, and file persistence.

### Core Features (per spec)
- **Save mode** — "remember that...", "save this...", "don't forget..."  
  → LLM extracts summary/category/keywords → saves to JSON → confirms short
- **Recall mode** — "what did I save about...", "do I have anything on..."  
  → LLM ranks top 3 matches → speaks with days-ago context
- **List mode** — "list everything", "recap my memories", "summarize my memories"  
  → Progressive disclosure: only abstract summary (count + category breakdown)  
  → "You have 7 saved memories. 3 reminders, 2 people, 1 thing, 1 place. Want me to go through them?"
- **Delete mode** — "delete my wife's birthday", "forget that note"  
  → LLM identifies entry → explicit confirmation ("Delete '...' ? Say yes") → remove from JSON
- **Date calculations** — "how many days until...", "days left before..."  
  → Accurate countdown using real current date (code-calculated)
- 100-entry limit with friendly warning
- Save-more & search-again loops with exit word detection ("stop", "done", etc.)
- Filler speech before LLM calls ("One sec...")
- Delete-then-write JSON persistence (never append)

### Why This Ability Matters
People get brilliant ideas or reminders while driving, cooking, walking, or in the shower — moments when they can't type or open an app.  
This gives zero-friction voice capture + smart retrieval — completely private and always available.

### Setup & Usage
No configuration needed.  
Trigger phrases activate the ability automatically.

Examples:
- Save: "Remember that dentist is March 15th" → "Got it. I saved: Dentist appointment is March 15th."
- Recall: "What did I save about dentist?" → "I found this: 10 days ago you saved: Dentist appointment is March 15th."
- List: "Recap my memories" → "You have 5 saved memories. 2 reminders, 2 people, 1 thing. Want me to go through them?"
- Delete: "Delete dentist appointment" → "Delete 'Dentist appointment is March 15th'? Say yes to confirm."

### Technical Notes
- File: `voice_memory_entries.json` (namespaced)
- Persistence: delete-then-write pattern
- LLM usage: classification, matching, summary extraction only
- Days-ago: calculated in code (not LLM)
- No external dependencies or APIs

### Demo Video
https://www.loom.com/share/d5cd8e60659540dc89885eaa34e6a485

### Status
Fully tested live: save → recall → list (summary only) → delete → calculate days → loops/exits correctly.

Ready for review & 30-day evaluation.
