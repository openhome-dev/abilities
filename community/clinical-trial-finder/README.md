# Clinical Trial Finder

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)

Find recruiting clinical trials by voice — no screen, no searching, no time spent on a database that wasn't built for people.

## What It Does

Clinical Trial Finder is a voice-first OpenHome ability that searches ClinicalTrials.gov by condition and location and reads results back in plain spoken English. It handles the full discovery workflow — finding trials, summarising eligibility, surfacing contact details, and saving trials to a personal watchlist that the background daemon monitors weekly for status changes.

Finding trials the traditional way is genuinely painful. The official database has 500,000+ studies and zero voice support. This ability is built for patients and caregivers, people exploring options after a new diagnosis, family members researching on someone else's behalf — anyone who's spent an hour on that website trying to find something relevant.

Just talk naturally:

- *"Find trials for Parkinson's near Houston"*
- *"Any studies for diabetes in Chicago?"*
- *"What are the requirements?"*
- *"How do I contact them?"*
- *"Save this one"*
- *"Show me more"*

## Suggested Trigger Words

- "Find clinical trials"
- "Clinical trial finder"
- "Find medical studies"
- "Research trials"

## Intents

The ability uses a single LLM router per turn to classify what the user wants:

| Intent | What it handles |
|---|---|
| `SEARCH` | Find recruiting trials for a condition and location ("find trials for Parkinson's near Houston") |
| `DETAILS` | Spoken summary of a specific trial ("tell me more about trial 2", "this one") |
| `ELIGIBILITY` | Who can join — age limits and key inclusion/exclusion criteria ("what are the requirements?", "who can join?") |
| `CONTACT` | Trial coordinator name, phone, and email ("how do I contact them?") |
| `SAVE` | Add the current trial to the watchlist ("save this one") |
| `MORE` | Next page of results ("show me more") |
| `EXIT` | End the session ("done", "stop") |

Common exit phrases are caught by a fast-path check before the LLM router runs, making exits instant and reliable.

## Features

- **Voice-first search** — one LLM call per turn decides the intent. Follow-up questions ("what are the requirements?", "how do I contact them?") resolve against the currently active trial without losing context.
- **Results filtered to RECRUITING** — every result returned is actionable. Completed, suspended, or not-yet-open trials are excluded.
- **Eligibility in plain English** — full eligibility text is distilled to two spoken sentences covering the age requirement and the most important criteria.
- **Contact details on demand** — coordinator name, phone number, and email spoken directly.
- **Pagination** — say "more" to move to the next page of results within the same search.
- **Mid-session re-search** — say a new condition at any point to start a fresh search without exiting.
- **Watchlist** — saved trials persist across sessions. The daemon monitors them weekly and alerts when status changes.
- **Background digest** — weekly reminder of how many recruiting trials are available for each of your saved conditions.
- **Location memory** — your first location search is saved as your preferred location and used automatically in future digests.
- **Graceful degradation** — API failures are logged silently. Missing contact details produce a short notice rather than breaking the session.

## Setup

No configuration required. The ability works out of the box — no API keys, no linked accounts.

### APIs Used

| Service | Auth required | Purpose |
|---|:---:|---|
| ClinicalTrials.gov v2 | None | Global trial search — 500,000+ studies |
| OpenHome Context Storage | OpenHome SDK | Persist watchlist, saved conditions, and preferred location |

## Example Conversations

### Finding trials for a condition

> **User:** "Find trials for Parkinson's near Houston"
>
> **Ability:** "Searching for recruiting trials for Parkinson's near Houston. One moment."
>
> **Ability:** "Found 5 results. Trial 1: A Phase 3 study of levodopa carbidopa intestinal gel, located in Houston, Texas and 4 other sites. Trial 2: Deep brain stimulation for early Parkinson's, located in Houston, Texas..."
>
> **Ability:** "Say a number to hear details, 'requirements' for eligibility, 'contact' for contact info, 'save' to add to your watchlist, 'more' for next page, or 'done' to exit."

---

### Drilling into eligibility

> **User:** "What are the requirements for trial 1?"
>
> **Ability:** "Participants must be between 30 and 80 years old. Key requirements are a confirmed Parkinson's diagnosis of at least 3 years and no prior deep brain stimulation surgery."

---

### Saving a trial

> **User:** "Save this one"
>
> **Ability:** "Saved. I'll alert you weekly if the status of that trial changes."

---

### Background alert

> **[Proactive alert from daemon]**
>
> **Ability:** "Trial update: A Phase 3 study of levodopa carbidopa intestinal gel — status changed from RECRUITING to COMPLETED."

---

### Exiting

> **User:** "Done" *(or "stop")*
>
> **Ability:** *(hands control back to OpenHome)*

## How It Works

1. **Trigger** — OpenHome routes the user's voice to this ability.
2. **Condition extraction** — the LLM extracts the condition and location from the trigger phrase. If no condition is detected, the ability asks before searching.
3. **Fast-path check** — obvious exit phrases are caught before any model call for instant exits.
4. **Search** — ClinicalTrials.gov is queried with the condition, location, and RECRUITING status filter. Up to 5 results are returned per page.
5. **Routing** — each follow-up turn is classified by a single LLM call, with the active trial and last search injected as context so follow-ups resolve naturally.
6. **Watchlist** — saved trials are stored in Context Storage. The background daemon polls each one weekly and fires a spoken alert on any status change.

## Persistence

All state lives under a single OpenHome Context Storage key (`clinical_trial_data`):

| Sub-attribute | Value | Used for |
|---|---|---|
| `watchlist` | List of saved trials | Weekly status monitoring and change alerts |
| `saved_conditions` | List of condition names | Weekly digest of recruiting trial counts |
| `preferred_location` | Location string from first search | Auto-applied to condition digests |

## Notes

- All API failures are logged with the `[ClinicalTrials]` prefix and the session continues — no spoken error noise.
- The daemon polls every 7 days. Status change alerts fire at most once per weekly cycle per trial.
- Results are limited to 5 per page to keep voice output concise. Say "more" to paginate.
