# Dev Standup Assistant

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@yourusername-lightgrey?style=flat-square)

## What It Does
The Dev Standup Assistant helps developers capture their daily standup naturally using voice, remember it by date, and retrieve or recap it later in a meeting-ready format.  
Unlike a normal LLM conversation, it persistently stores updates and lets you ask follow-up questions about your standup anytime.

## Suggested Trigger Words
- "standup"
- "new standup"
- "daily standup"
- "start standup"

## Setup
No external APIs or keys are required.

Steps:
1. Add the Ability to your OpenHome environment.
2. Paste the provided `main.py` into the ability folder.
3. Enable the ability in the dashboard.
4. Add trigger words (e.g., "standup").
5. Run in OpenHome Live Test.

All data is stored locally in:
- `dev_standup_db.json` (persistent memory)
- `latest_standup.md` (latest recap export)

## How It Works
The assistant focuses on natural interaction instead of rigid forms.

1. User starts a standup and speaks freely.
2. The assistant stores the raw update for the current date.
3. A smart follow-up question helps fill missing context.
4. The assistant generates a meeting-ready recap.
5. Later, users can:
   - hear today's summary
   - update today's standup
   - ask specific questions (e.g., blockers or projects)
   - retrieve past standups by date 
   - say help to hear options

The LLM performs intelligent retrieval at query time instead of forcing structured inputs.

## Example Conversation

> **User:** "standup"  
> **AI:** "Standup assistant ready. What would you like to do?"

> **User:** "new standup"  
> **AI:** "Okay — tell me your standup in one go."

> **User:** "Fixed webhook verification, debugging mobile login, planning integration tests next."  
> **AI:** "Any blockers today?"

> **User:** "Waiting on staging credentials."  
> **AI:** "Saved. You can say read today or recap today."

> **User:** "recap today"  
> **AI:** "Today you focused on backend fixes and mobile debugging, with integration tests planned next. You're currently waiting on staging credentials."

> **User:** "what are my blockers today?"  
> **AI:** "You're waiting on staging credentials."