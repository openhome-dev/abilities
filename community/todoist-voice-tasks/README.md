# Todoist Voice Tasks

![OpenHome Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)

Manage your [Todoist](https://todoist.com) tasks by voice through OpenHome. Add, update, complete, or delete tasks, and ask for your full list, overdue tasks, or today’s tasks—using natural language. No need to remember exact commands; the platform LLM interprets what you say and the ability calls the Todoist REST API.

---

## Overview

This ability connects OpenHome’s voice pipeline to your Todoist account. After you say a trigger phrase (e.g. “Open Todoist”), you can speak commands in plain language. The ability uses the **OpenHome platform LLM** to classify your intent and extract task text or references, then performs the action via the [Todoist API v1](https://developer.todoist.com/api/v1/). Voice input and LLM are provided by OpenHome; this ability does not implement speech-to-text or a separate LLM.

---

## Features

- **Add tasks** — e.g. “Add buy milk”, “Add call mom tomorrow at 9”
- **Update tasks** — change text or due date; e.g. “Update the first task to buy bread”, “Change call mom to call dad”
- **Complete tasks** — e.g. “Mark complete”, “Complete my first task”, “Done with the milk task”
- **Delete tasks** — e.g. “Delete the milk task”, “Remove my first task”
- **List all tasks** — e.g. “What are my tasks?”, “Show my list”, “List my tasks”

- **Due dates** — natural language when adding or updating (e.g. “tomorrow”, “next Friday”, “March 15”, “today at 5pm”). Uses Todoist’s [natural-language due dates](https://todoist.com/help/articles/introduction-to-due-dates-and-due-times-q7VobO).

---

## Prerequisites

- An [OpenHome](https://app.openhome.com) account and an Agent that supports abilities.
- A [Todoist](https://todoist.com) account and an API token.

---

## Setup

1. **Get your Todoist API token**  
   [Todoist → Settings → Integrations → API token](https://app.todoist.com/prefs/integrations). Copy the token.

2. **Configure the ability**  
   In `main.py`, set `API_KEY` to your token. For local testing use your real token; for PR/submission use the placeholder only:
   ```python
   API_KEY = "REPLACE_WITH_YOUR_KEY"  # Replace with your token; get it at https://app.todoist.com/prefs/integrations
   ```
   You can also configure the token via the OpenHome dashboard when you upload the ability, if your deployment supports it.

3. **Upload to OpenHome**  
   Zip the `todoist-voice-tasks` folder (including `main.py` and `__init__.py`) and upload the ability in the OpenHome dashboard.

4. **Trigger phrases**  
   Configure trigger phrases in the OpenHome dashboard. When the user says one of these phrases, the Todoist ability starts.

---

## Trigger Phrases (Matching Hotwords)

These phrases **start** the Todoist ability. After it’s running, any of the voice commands below are understood inside the ability.

| Purpose | Example phrases |
|--------|------------------|
| Open Todoist | “Open Todoist”, “Todoist”, “My tasks”, “My task list”, “Task list”, “Open my list” |
| Add-oriented | “Add to my list”, “Add task” |
| List-oriented | “What are my tasks?”, “What’s on my list?” |

| Delete-oriented | “Delete from my list”, “Remove from my list” |

Suggested trigger phrases:

- `open todoist`
- `todoist`
- `my tasks`
- `my task list`
- `task list`
- `open my list`
- `add to my list`
- `what are my tasks`
- `what's on my list`
- `add task`
- `what are my overdue tasks`
- `mark my top task complete`
- `delete from my list`
- `remove from my list`
- `complete the task`
- `complete a task`
- `mark task complete`

---

## How It Works

1. **Activation** — User says a trigger phrase from `matching_hotwords`. OpenHome routes to this ability and calls `call(worker)`.
2. **Greeting** — The ability speaks a short greeting and lists what you can do (add, update, complete, reopen, delete, list, overdue, today).
3. **Loop** — The ability listens with `user_response()` (platform voice → text). Each utterance is sent to the platform LLM via `text_to_text_response()` to get a structured intent (add, delete, update, complete, reopen, list, overdue, today, exit) plus optional `content`, `task_ref`, and `due`.
4. **Action** — The ability calls the Todoist API (GET/POST) and speaks a confirmation or error.
5. **Exit** — User says “stop”, “exit”, “done”, “bye”, etc. The ability says goodbye and calls `resume_normal_flow()` so control returns to the main Agent.

No custom speech-to-text or LLM client is used; everything goes through the OpenHome SDK.

---

## Voice Commands (After the Ability Is Open)

You can say any of the following in natural language. The LLM maps your words to an action.

| Intent | Examples |
|--------|----------|
| **Add** | “Add buy milk”, “Add task call mom tomorrow at 9”, “Add groceries for 25 Feb” |
| **Delete** | “Delete the milk task”, “Remove my first task”, “Delete banana” |
| **Update** | “Update the first task to buy bread”, “Change call mom to call dad”, “Set due 25 Feb” |
| **Complete** | “Mark complete”, “Complete my first task”, “Done with the milk task”, “Mark banana complete” |
| **List all** | “List my tasks”, “Show my list”, “What are my tasks?” |


---

## Due Dates

When adding or updating a task, you can say when it’s due in plain language. The LLM extracts a `due` phrase and the ability sends it to Todoist as `due_string`. Todoist supports expressions like:

- **Relative:** today, tomorrow, next week, next month, next Friday, in 5 days  
- **Absolute:** March 15, 25 Feb, Jan 27  
- **With time:** today at 5pm, tomorrow at 9am  

See [Todoist’s due date help](https://todoist.com/help/articles/introduction-to-due-dates-and-due-times-q7VobO) for full support.

---

## Task Resolution (Which Task to Act On)

For delete, update, complete, and reopen, you can refer to a task by:

- **“First”** — first active (or first completed, for reopen) task in the list  
- **“Last”** — last active (or last completed) task  
- **Phrase** — a word or phrase that appears in the task content (e.g. “milk”, “call mom”, “banana”)

The ability finds the matching task and performs the action on it.

---

## Example Conversation

| User | OpenHome (ability) |
|------|---------------------|
| “Open Todoist” | “Todoist here. You can add, update, complete, uncomplete, reopen, or delete tasks, or list all, overdue, or today. Say stop when done.” |
| “Add buy milk tomorrow at 9” | “Added task: buy milk. Due tomorrow at 9.” |
| “What are my overdue tasks?” | “You have 2 overdue: call dentist, submit report.” |
| “Complete the first one” | “Marked complete: call dentist.” |
| “Delete the milk task” | “Deleted: buy milk.” |
| “Stop” | “Goodbye!” |

---

## API and Token

- **API:** [Todoist REST API v1](https://developer.todoist.com/api/v1/) — same base URL and endpoints as the repo’s `test_todoist_local.py` (`https://api.todoist.com/api/v1`).
- **Token:** Free API token from [Todoist → Settings → Integrations](https://app.todoist.com/prefs/integrations). Stored in `main.py` as `API_KEY` (use placeholder `REPLACE_WITH_YOUR_KEY` when submitting a PR).

---

## File Structure

```
community/todoist-voice-tasks/
├── README.md       # This file
├── main.py         # Ability logic (MatchingCapability, Todoist API calls, LLM intent)
└── __init__.py     # Package marker
```

Trigger phrases and the ability's unique name are configured in the OpenHome dashboard.

---

## Technical Notes (Standards Compliance)

This ability follows the OpenHome community requirements (see repo `CONTRIBUTING.md` and job spec):

- **Registration:** Uses the `#{{register capability}}` tag; OpenHome provides the ability metadata and trigger words at runtime.
- **Exit:** `resume_normal_flow()` is called on every exit path (in a `finally` block).
- **Logging:** No `print()`; uses `editor_logging_handler` for logs.
- **Concurrency:** No `asyncio.sleep()` or `asyncio.create_task()`; uses platform `session_tasks` where needed.
- **API key:** Variable `API_KEY` in `main.py`; for PR submission use placeholder only with a comment linking to [Todoist Integrations](https://app.todoist.com/prefs/integrations).
