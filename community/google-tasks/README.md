# Google Tasks Assistant

Google Tasks Assistant is an OpenHome community ability for managing Google Tasks by voice. It uses the user's linked Google account to add, view, complete, delete, and rename tasks across their Google task lists.

## What It Does

- Adds tasks from a quick spoken request
- Supports step-by-step task creation for title, details, due date, and repeat notes
- Lets the user choose a task list when multiple Google task lists exist
- Reads incomplete tasks across all task lists
- Gives details about a selected task, including list name, due date, and notes
- Marks one or multiple tasks as complete
- Confirms completion when the selected task was chosen from a spoken list
- Deletes selected tasks
- Renames existing tasks
- Understands task references by name, number, or partial description
- Continues with follow-up actions through `Anything else?`

## Supported Requests

| Request type | Example | What happens |
|---|---|---|
| Add task | `Add grocery shopping` | Adds a task, asking for details if needed |
| Quick add | `Add call Ahmed tomorrow` | Parses title and due date from one sentence |
| Step-by-step add | `I need to remember something` | Asks for title, details, due date, and repeat notes |
| View tasks | `What's on my list?` | Reads incomplete tasks from all Google task lists |
| Task details | `Details on the second one` | Speaks list name, due date, and notes when available |
| Complete task | `Mark grocery shopping done` | Finds and completes the matching task |
| Complete multiple | `Complete birthday and holiday` | Matches multiple tasks and confirms the batch |
| Delete task | `Delete birthday reminder` | Removes the selected task |
| Rename task | `Rename grocery shopping to buy groceries` | Updates the task title |
| Exit | `No thanks` | Ends the session |

## Example Prompts

- "Add grocery shopping."
- "Add call Ahmed tomorrow."
- "I need to remember something."
- "Show my tasks."
- "What's on my list?"
- "Details on the second one."
- "Mark the first one done."
- "Complete birthday and holiday."
- "Delete grocery shopping."
- "Rename grocery shopping to buy groceries."
- "No thanks."

## Trigger Phrases

- `google tasks`
- `tasks`
- `todo`
- `to-do list`
- `add a task`
- `show my tasks`

## Account Linking Guide

This ability does not use a manual API key. It reads a Google OAuth token from OpenHome with:

```python
self.capability_worker.get_token("google")
```

Before using the ability, connect the Google account that owns the Google Tasks lists you want OpenHome to manage.

1. Open OpenHome.
2. Go to **Settings -> Linked Accounts**.
3. Choose **Google**.
4. Sign in to the Google account you want to use.
5. Approve the requested Google permissions.
6. Return to OpenHome and enable or install the Google Tasks ability.
7. Add trigger phrases such as `tasks`, `todo`, and `add a task`.
8. Start a conversation and say one of the trigger phrases.

If the Google account is not linked, the ability will say that the account is not connected and stop.

## Data Access

| Service | Authentication | Used for |
|---|---|---|
| Google Tasks API | Linked Google account | Creating, listing, completing, deleting, and renaming tasks |

The ability reads incomplete tasks from all task lists so it can match spoken references like "the second one" or "birthday." It only changes tasks when the user asks to add, complete, delete, or rename something.

## Voice Flow

1. User triggers the ability.
2. The ability waits for the complete trigger transcription.
3. It checks for a linked Google account.
4. It builds a Google Tasks API service from the OpenHome Google token.
5. It classifies the request as `ADD`, `VIEW`, `COMPLETE`, `DELETE`, `UPDATE`, `EXIT`, or `UNKNOWN`.
6. If the request is unclear, it asks what the user wants to do.
7. It fetches current incomplete tasks when needed for matching.
8. It performs the selected task action.
9. It asks `Anything else?` for follow-up task actions.
10. The ability calls `resume_normal_flow()` when the session ends.

## Flow Details

- **Add**: chooses a task list if needed, then supports quick add or step-by-step entry.
- **View**: summarizes incomplete tasks and can speak details for selected tasks.
- **Complete**: matches one or more tasks, confirms when needed, and marks them completed.
- **Delete**: matches a selected task and deletes it.
- **Update**: matches a selected task and renames it.
- **Exit**: ends the session with a short confirmation.

## Developer Credit

Developed by [@samsonadmasu](https://github.com/samsonadmasu).
