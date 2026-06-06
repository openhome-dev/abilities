# Clinical Trial Finder

Voice-first search for recruiting clinical trials. Search ClinicalTrials.gov by condition and location, drill into eligibility and contact details, save trials to a personal watchlist, and get proactive alerts when a saved trial's status changes.

**No API keys required.**

---

## Trigger Phrases

| What you say | What happens |
|---|---|
| "find clinical trials for Parkinson's" | Search recruiting trials for Parkinson's |
| "any trials near me for diabetes?" | Search trials filtered to your location |
| "find medical studies for breast cancer in Boston" | Search with explicit location |
| "tell me more about trial 2" | Spoken summary of result #2 |
| "what are the requirements?" | Eligibility criteria summary |
| "how do I contact them?" | Contact name, phone, and email |
| "save this trial" | Add to your watchlist |
| "show me more" | Next page of results |
| "search for trials for lupus" | New search within the session |

---

## Within a Session

After results are listed, you can:
- Say **"1", "2", "3"** etc. to focus on a specific trial
- Say **"requirements"** or **"who can join"** for eligibility details
- Say **"contact"** for the trial coordinator's contact info
- Say **"save"** to add the current trial to your watchlist
- Say **"more"** to see the next page of results
- Say **"done"** or **"stop"** to exit

---

## Background Alerts

The daemon runs a weekly check and speaks proactively when:

- **Status change** — a saved trial moves from RECRUITING to COMPLETED, SUSPENDED, etc.
- **Weekly digest** — a reminder of how many recruiting trials are currently available for each of your saved conditions

Both alert types fire once per weekly cycle.

---

## Watchlist

Saved trials persist across sessions. The daemon monitors them weekly and alerts you to any changes. Your preferred location (set automatically from your first location search) is used to filter condition digests.

---

## Data Source

| Source | Coverage | Key required |
|---|---|---|
| [ClinicalTrials.gov](https://clinicaltrials.gov) | Global — 500,000+ studies | None |

Results are filtered to **RECRUITING** status only so every result is actionable.
