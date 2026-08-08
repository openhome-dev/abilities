# Agentic Form Filler

Fills out a web form for you by voice. You describe what you want (e.g. register for a hackathon, file a bug report, submit feedback), the Ability figures out which form and gathers the missing fields through conversation, then opens the form in a browser on your computer and fills it in automatically.

## Suggested Trigger Words

- "fill out a form"
- "form filler"
- "register for the hackathon"

## How it works

1. You say what you want to do; the LLM asks for any missing fields (team name, email, idea, bug title, priority, etc.) one at a time.
2. Once every required field for a form is collected, it launches a local browser (via [Playwright](https://playwright.dev/)) pointed at the matching form.
3. The collected data is written to a local `data.json` and injected into the form's inputs by matching each field's `id`/`name`/`placeholder`, then the submit/next button is clicked.

Supported forms: `hackathon_registration.html` (Team, Email, Idea), `bug_report.html` (Title, Priority, Description), `feedback_survey.html` (Name, Rating, Comments).

## Setup

This Ability drives a browser on **your own machine**, not the DevKit or the cloud sandbox — it requires OpenHome's [Local Link](https://docs.openhome.com) bridge running locally.

- Install Playwright on the machine that runs `local_runner.py`: `pip install playwright && playwright install chromium`.
- The three form HTML files (`hackathon_registration.html`, `bug_report.html`, `feedback_survey.html`) must exist locally, in the same directory `local_runner.py` runs from.
- No API keys required.

## Files

- `main.py` — the Ability: collects form data by voice, hands off to the local runner.
- `local_runner.py` — runs locally via Local Link; launches the browser and fills the form.

## Known limitations

- Field matching is done by substring match against each input's `id`/`name`/`placeholder`, so unusually labeled form fields may be filled incorrectly or skipped.
- Forms and their required fields are hardcoded in the system prompt; adding a new form means editing `main.py`.
