# Ring Security — OpenHome Ability

---

## What This Ability Does

Ring Security connects your Ring account to OpenHome so you can monitor and control your Ring devices using natural voice commands.

It handles:

- Direct credential-based authentication with Ring (email + password + 2FA)
- Token refresh + local persistence
- Intent classification
- Deterministic device resolution + clarification
- Ring API interaction with retry-on-401
- Safe confirmation for destructive actions (like siren activation)
- Conversation lifecycle management (turn limits + idle exit)

This ability is structured for deterministic control, safe device actions, and fault-tolerant API interaction.

---

## Supported Commands

### Device Overview

- **List devices** — Enumerates all Ring devices on the account.
- **Device status** — Reports battery level and WiFi signal strength.
- **Help** — Explains what the ability can do.

### Activity & History

- **Check activity (single device)** — Summarizes motion and ring events.
- **Check activity (all devices)** — Aggregates recent events across devices (capped).
- **Last ring** — Reports when a doorbell was last pressed.
- **Motion history** — Returns motion events, optionally filtered by time window (e.g., “last 2 hours”).

### Controls

- **Floodlight on/off**
- **Activate siren** (confirmation required)
- **Turn off siren**
- **Enable/disable motion detection**
- **Test chime**
- **Set chime volume (0–10)**

Follow-up clarifications like:

> “Front door”
> “The backyard cam”

are resolved deterministically without re-running classification.

---

## Design Principles

### Intent Detection + Central Routing

All user input flows through `_classify()` which returns structured JSON.

{
  "intent": "list_devices | device_status | check_activity | activity_all | last_ring | motion_history | floodlight_on | floodlight_off | siren_on | siren_off | motion_toggle_on | motion_toggle_off | chime_test | chime_volume | help | unknown",
  "device_hint": "string | null",
  "hours": "number | null",
  "volume": "number | null"
}

The dispatcher routes strictly based on `intent`.
Handlers do not contain classification logic.

Before classification:

- Activation hotwords are stripped via `_strip_activation_phrase()`
- Exit words are checked deterministically
- Clarification flows are handled via `pending_action`

This reduces unnecessary LLM calls and keeps behavior predictable.

---

### Deterministic Device Resolution

Device selection is never delegated to the LLM.

All device matching flows through `_resolve_device()`:

- Exact match → resolved
- Single candidate → auto-selected
- Partial match (one result) → resolved
- Ambiguous match → user prompted
- No match → user prompted with valid options

Clarifications are stored in `pending_action` so follow-up responses bypass classification and route directly to the intended handler.

---

### Time Window Fallback Logic

For motion history:

1. The classifier may return `"hours"`.
2. If missing, `_extract_time_window()` performs regex-based extraction.

Examples supported:

- “last hour”
- “past 3 hours”
- “last day”

This dual-layer approach ensures time filtering works even if the classifier fails to extract a value.

---

### Single Ring API Wrapper

All Ring API calls go through:
_ring_request_with_retry()


Features:

- Automatic 401 → refresh token → retry once
- Timeout enforced
- Supports GET / POST / PUT / PATCH
- Handles 204 No Content responses
- No raw `requests` calls in handlers

#### Important: `force_null_body`

Some Ring PUT endpoints require:

- `Content-Type: application/json`
- A literal `"null"` request body

This is handled via:
force_null_body=True


Anyone extending the ability must use the API wrapper rather than issuing direct requests.

---

### Conversation Lifecycle

The conversation loop enforces:

- Maximum 20 turns per session
- Exit after 2 consecutive idle responses
- Deterministic exit words (stop, cancel, bye, etc.)

At completion, the ability always returns control via:
resume_normal_flow()


Handlers never call this directly.

---

## Authentication Model

This ability uses direct credential-based login against Ring’s token endpoint.

Endpoint used:
https://oauth.ring.com/oauth/token

Client ID used:
ring_official_android


Flow:

1. User enters email
2. User confirms email
3. User enters password
4. If required → 2FA code
5. access_token + refresh_token returned
6. Tokens stored locally

---

## Token Storage

Tokens are stored in:
ring_tokens.json


Stored fields:

- refresh_token
- access_token
- last_refresh

Behavior:

- Refresh attempted at session start
- 401 during API call → refresh + retry once
- Second 401 → reconnect required
- Delete-then-write persistence pattern
- Tokens are never logged

---

## Mock Mode

`mock_mode = True` by default.

Provides:

- Mock devices
- Mock history
- Mock health responses

This allows safe local testing without real Ring credentials.

Set `mock_mode = False` to enable real API interaction.

---

## Safety Features

- Siren activation requires explicit confirmation
- Device-type restrictions enforced (doorbells vs cameras vs chimes)
- Volume bounds enforced (0–10)
- Activity aggregation capped to prevent excessive scanning
- Defensive parsing for API responses

---

## Error Handling

### “Authentication failed”

- Re-enter credentials carefully.
- Ensure 2FA code is correct and current.
- If repeated failures occur, start a new session.

### “I need to reconnect to Ring”

- Refresh token likely expired or revoked.
- Start a new session to reauthenticate.

### “Ring's servers aren't responding”

- Network timeout occurred.
- Retry after a short delay.

### No devices found

- Account may not contain supported devices.
- API call may have failed — check logs.

### Floodlight or siren won’t activate

- Device may not support the feature.
- API may have rejected the command.

---

## Extending This Ability

To add a new feature:

1. Add intent to classifier schema.
2. Add routing logic in `_dispatch()`.
3. Implement `_handle_<feature>()`.
4. Use `_ring_request_with_retry()` only.
5. Respect device type restrictions.
6. Do not call `resume_normal_flow()` inside handlers.
7. If PUT requests behave unexpectedly, verify whether `force_null_body=True` is required.

Device clarification must always go through `_resolve_device()`.

---

## Suggested Trigger Words

Examples:

- "Ring"
- "Check my Ring"
- "Ring security"
- "Doorbell status"

Use Ring-specific trigger phrases to reduce collisions with other abilities.

---

This ability is designed to be:

- Deterministic where possible
- LLM-driven only at the intent layer
- Safe for device control
- Resilient to token expiry
- Easy to extend without breaking architecture
