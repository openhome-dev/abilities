# Contact Memory (CRM Assistant)

![Community](https://img.shields.io/badge/OpenHome-Community-green?style=flat-square)

A voice‑driven personal CRM ability that remembers people you meet, lets you look them up, and keeps notes on your interactions. It stores data locally in a simple JSON file and uses on‑the‑fly LLM prompts to classify intent and extract details from speech.

## Trigger Words

Set these (or your own custom phrases) in the dashboard to activate the ability:

- "contact memory"
- "remember contact"
- "tell me about someone"
- "lookup a contact"
- "add a contact"
- "who do I know"
- "search contacts"

(Any natural language variation works—the backend uses intent classification.)

## Setup

No external APIs are required. The ability reads and writes a `contacts.json` file in its working directory. Data is normalized and canonicalized automatically.

## How It Works

1. **Activation:** The user triggers the ability with a hotword.
2. **Intent classification:** A small prompt asks the LLM whether the user wants to store, retrieve, lookup, search, add a note, or update a contact.
3. **Data extraction:** Depending on the intent, the ability runs additional prompts to pull names, emails, phone numbers, tags, and other fields from the spoken input.
4. **Matching:** When a name is provided, the code first tries simple key lookups and fallbacks to an LLM‑assisted matcher; if no match is found it can create a new contact.
5. **CRUD operations:** Contacts can be created, updated, queried by name/company/tag/date, and annotated with notes. Updates append system notes to record changes.
6. **Persistence:** All changes are saved to `contacts.json` via `capability_worker` helpers; the file is reloaded on each activation.
7. **Speech output:** Responses are synthesized with `speak()` after sanitizing email addresses and formatting dates/phones for speech.

Behind the scenes the class maintains a short session history that gets prepended to prompts to give the LLM context during multi‑turn conversations.

## Flow

```text
Ability triggered  →  Greeting
   ↓
Loop:
   • Capture user input
   • Exit on words like stop/quit/cancel
   • Classify intent and handle the request
   • Speak the result
   • Break if operating in quick mode
→ Resume normal Personality flow
```

## Key SDK Functions Used

- `speak()` – Read responses aloud.
- `user_response()` – Await next spoken utterance.
- `session_tasks.create()` – Run the main loop asynchronously.
- File helpers (`read_file`, `write_file`, `delete_file`, etc.) in `CapabilityWorker` for persistence.
- `resume_normal_flow()` – Cleanly hand control back to the main agent.

## Example Conversations

> **User:** "Remember I met Alice from Acme, her email is alice at acme dot com."
> 
> **AI:** "Saved Alice, role unknown at Acme, met at ."

> **User:** "Who is Alice?"
> 
> **AI:** "Alice. Works at Acme. Email: alice at acme dot com."

> **User:** "Add a note for Alice: she's moving to Seattle."
> 
> **AI:** "Added a note to Alice."

> **User:** "Search contacts by company Acme."
> 
> **AI:** "I found Alice, role unknown at Acme."

> **User:** "Update Alice's phone to 555‑1234."
> 
> **AI:** "Updated Alice's phone."

> **User:** "Who do I know in the last 7 days?"
> 
> **AI:** "I found 1 contact: Alice." 

Use the built‑in exit words (`stop`, `exit`, `quit`, `done`, `cancel`, `bye`, `goodbye`, `leave`, "that's all") to end the session.

---

This README replaces the generic loop template with detailed instructions and examples specific to the Contact Memory ability.