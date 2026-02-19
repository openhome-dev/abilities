# N8N Commander Ability

A voice-driven automation bridge that turns your OpenHome speaker into a universal voice remote for your entire software stack. Say what you want done — "post to Slack," "create a task," "log this to the spreadsheet" — and the ability routes the request to the right n8n webhook, which triggers a pre-built automation workflow.

One ability, unlimited integrations. n8n has 400+ built-in service integrations.

## Features

- Trigger any n8n webhook workflow by voice
- Two-pass intent classification (keyword prefilter + LLM)
- Fire-and-forget workflows (quick confirmations)
- Round-trip response workflows (n8n returns data, ability speaks it back)
- Confirmation loop for sensitive actions
- Optional webhook authentication via custom headers
- Optional Twilio SMS for long responses and URLs
- Voice-optimized output formatting
- Multi-turn conversation loop with follow-up support

## Requirements

- Python 3.8+
- `requests` library
- An n8n instance (Cloud at [n8n.io](https://n8n.io) or self-hosted) with webhook workflows

## Installation

1. Copy the ability folder into your agent's abilities directory.

2. Create your `n8n_commander_prefs.json` preferences file (see `n8n_commander_prefs_example.json` for the full template). The ability will create a default empty prefs file on first run if none exists.

3. Register the ability with your agent:

```python
N8nCommanderCapability.register_capability()
```

## How It Works

```
User speaks trigger phrase
    |
OpenHome triggers N8N Commander ability
    |
Ability listens -> captures user intent via voice
    |
Two-pass classification:
  1. Keyword prefilter (scan trigger_phrases)
  2. LLM classifies: which workflow? what parameters?
    |
HTTP POST -> n8n webhook URL (with JSON payload)
    |
n8n workflow runs (Slack post, Jira ticket, Sheets row, etc.)
    |
If expects_response: speak back the result
If fire-and-forget: speak confirmation
    |
Loop: "Anything else?" or exit
```

## Setting Up n8n Workflows

### Step 1: Create a Workflow in n8n

1. Open n8n (Cloud at app.n8n.cloud or self-hosted)
2. Click "New Workflow"
3. Add a **Webhook** node as the trigger
4. Set HTTP Method to **POST**
5. Note the **Production URL** — this goes in your prefs file

### Step 2: Configure the Webhook Node

- **Fire-and-forget** workflows: Set Respond to "Immediately"
- **Response** workflows: Set Respond to "When Last Node Finishes"

### Step 3: Add Action Nodes

After the Webhook node, add whatever n8n nodes you need (Slack, Google Sheets, Jira, Gmail, Home Assistant, etc.)

### Step 4: Activate and Test

Activate the workflow, then test with curl:

```bash
curl -X POST "https://your-instance.app.n8n.cloud/webhook/your-path" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello from OpenHome!", "params": {}}'
```

### Step 5: Add to Preferences

Paste the webhook URL into your `n8n_commander_prefs.json` under the appropriate workflow entry.

## Webhook Payload Format

Every webhook call sends this JSON structure:

```json
{
  "workflow_id": "slack",
  "action": "Post to Slack",
  "message": "the deploy is done",
  "params": {"channel": "#general"},
  "raw_utterance": "tell the team the deploy is done",
  "timestamp": "2026-02-19T09:00:00Z",
  "source": "openhome_voice"
}
```

## Webhook Response Format (for expects_response workflows)

n8n should return:

```json
{
  "success": true,
  "spoken_response": "Your task was created. Ticket ID is MAIN-4527."
}
```

The `spoken_response` field controls what the ability says back. If omitted, the ability falls back to "Done. The workflow ran successfully."

## Configuration

### Preferences File Fields

| Field | Purpose |
|---|---|
| `n8n_base_url` | Base URL of your n8n instance |
| `workflows` | Dictionary of named workflows |
| `webhook_url` | The full production webhook URL from n8n |
| `description` | Human-readable — the LLM uses this to match intent |
| `default_params` | Pre-filled values merged with LLM-extracted params |
| `trigger_phrases` | Keyword hints for faster routing |
| `confirm_before_send` | If true, asks for confirmation before firing |
| `expects_response` | If true, waits for n8n's JSON response |
| `webhook_auth` | Optional header-based authentication |
| `phone_number` | Optional phone number for Twilio SMS |

### Webhook Authentication (Optional)

Add to your prefs file:

```json
{
  "webhook_auth": {
    "type": "header",
    "header_name": "X-OpenHome-Key",
    "header_value": "your-secret-key-here"
  }
}
```

Then set the same header auth in your n8n Webhook node.

### Twilio SMS (Optional)

For long responses that are better sent as text:

```json
{
  "phone_number": "+15125551234",
  "twilio_account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "twilio_auth_token": "your_auth_token_here",
  "twilio_from_number": "+18005551234"
}
```

## Exit Words

Users can end the session at any time by saying:

> exit, stop, quit, done, cancel, bye, goodbye, never mind

## Error Handling

| Error | Spoken Response |
|---|---|
| No workflows configured | "You haven't configured any workflows yet..." |
| Webhook returns 404 | "That workflow's webhook isn't responding..." |
| Webhook returns 401 | "The webhook requires authentication..." |
| Webhook returns 500 | "Something went wrong inside the n8n workflow..." |
| Request timeout | "The workflow is taking too long..." |
| Network error | "I can't reach your n8n instance..." |
| Can't classify intent | "I'm not sure which workflow to use. Your options are..." |

## Logging

The ability logs to `worker.editor_logging_handler` with the prefix `[N8nCommander]`. Check these logs to debug intent classification, webhook calls, and response handling.

## License

Refer to your agent framework's license. n8n usage is subject to their [terms of service](https://n8n.io/legal).
