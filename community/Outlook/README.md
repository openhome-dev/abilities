# Migration: Smart Hub (Google) to Outlook (Microsoft Graph)

## Overview

Smart Hub has been migrated from Google Calendar (via Composio) to Microsoft Outlook using the Microsoft Graph API.

This update replaces the underlying calendar and profile infrastructure while preserving the assistant’s conversational and session logic.

You will need an access token for this. Please look at the README.md in access_token for this please.

---

## Key Changes

### 1. Removed Composio Integration

- Removed `COMPOSIO_BASE_URL`
- Removed all `GOOGLECALENDAR_*` tool calls
- Removed Google Super profile calls
- Eliminated third-party middleware dependency

The system now communicates directly with Microsoft Graph.

---

### 2. Calendar Provider Switched

**Previous:** Google Calendar  
**Current:** Microsoft Outlook (Microsoft 365 via Graph API)

Calendar operations now use Microsoft Graph endpoints:

- `GET /me/calendarView`
- `POST /me/events`
- `PATCH /me/events/{id}`
- `DELETE /me/events/{id}`

All event read/write logic was adapted to match Graph’s event schema.

---

### 3. Authentication Updated

**Previous:** Composio API key authentication  
**Current:** Microsoft OAuth 2.0 (Delegated Permissions)

Authentication now uses Microsoft-issued bearer tokens. Please refer to the README.md in 'access_token' on instructions to obtain this token.

---

### 4. Timezone Handling Updated

Timezone handling was reworked to align with Outlook’s behavior:

- Calendar timezone now comes from Microsoft Graph instead of Google event metadata.
- All event creation and updates explicitly pass the user’s calendar timezone.
- DateTime parsing was adjusted to correctly handle:
  - Offset-aware vs offset-naive datetimes
  - ISO 8601 formats returned by Graph
- Rescheduling and conflict detection logic was updated to use consistent timezone-aware comparisons.

This ensures accurate time calculations and prevents comparison errors.

---

### 5. User Profile Source Updated

**Previous:** Google profile (via Composio)  
**Current:** Microsoft account profile (`GET /me`)

User name and email are now retrieved directly from Microsoft Graph.

---

## What Did Not Change

The following systems remain unchanged:

- Trigger intent classification
- Quick vs Full session modes
- Multi-turn event creation and modification flows
- Fuzzy event matching
- Conflict detection logic (core algorithm)
- Cascade rescheduling behavior
- Geo and weather logic
- Conversational response generation

Only the backend provider and time handling layer were replaced.

---

## Result

- Direct Microsoft Graph integration
- No third-party dependency layer
- Proper timezone-aware scheduling
- Cleaner architecture
- Enterprise-ready authentication
- Improved reliability and maintainability
