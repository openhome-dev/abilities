# Outlook Daily Brief

OpenHome Ability that acts as a **daily orchestrator**: when you say a trigger phrase, it pulls your Outlook calendar, unread email, and local weather **in parallel**, then uses an LLM to turn everything into **one** natural-sounding ~60-second spoken summary. It’s not for one-off queries like “what’s on my calendar” — it’s the morning briefing that combines all three sources into a single cohesive readout.

Works with **Outlook.com** (consumer) and **Office 365** (enterprise). Uses Microsoft Graph (OAuth) for calendar and mail, and Open-Meteo (free, no key) for weather.

---

## What the code does

**1. Trigger and intent**  
The ability is invoked by phrases like “give me my brief”, “good morning”, “start my day”, or “what did I miss”. The code reads `self.worker.agent_memory.full_message_history` to get the user’s last message(s), then classifies intent:

- **Full brief** — “good morning”, “brief me”, “daily brief”, “start my day” → standard ~60s morning briefing.
- **Urgent / catch-up** — “what did I miss”, “catch me up” → same data but a shorter, urgency-focused script (~30–40s) that leads with what needs attention.

**2. Parallel fetch**  
Calendar, email, and weather are requested **at the same time** (each in a thread via `asyncio.to_thread`), with a per-call timeout (~5–6s). If one source fails, the others still run; the briefing uses whatever came back.

- **Calendar** — `GET /me/calendarview` for today (start/end in UTC). Returns subject, start, end, location. Scope: `Calendars.Read`.
- **Email** — `GET /me/mailFolders/inbox/messages` with `isRead eq false`, top 5, subject/from/receivedDateTime. Scope: `Mail.Read`.
- **Weather** — Open-Meteo forecast by lat/lon. Location comes from saved prefs or auto-detect (e.g. ip-api.com); result is stored so the next run reuses it.

**3. LLM synthesis**  
All fetched data (calendar, email, weather) is passed in one payload to `text_to_text_response()` with a **system prompt**. The LLM returns a single script to be read aloud — not three separate readouts. Different prompts are used for full brief vs “what did I miss” so the tone and length match the intent.

**4. Speak and follow-up loop**  
The script is spoken via the capability worker. Then the code waits for the user:

- **Repeat** — re-fetches data, re-synthesizes, and speaks again (or replays last script if fetch fails).
- **Change my city to [city]** — updates `location` in prefs, then “say repeat to hear your brief again”.
- **What did I miss / catch me up** — re-fetches and speaks the urgent-style brief.
- **Stop / done / quit / bye / etc.** — says goodbye and calls `resume_normal_flow()`.

Idle timeouts (no input for several cycles) trigger a short “I’m still here…” message and then exit. Every exit path calls `resume_normal_flow()`.

**5. Persistence**  
Preferences are stored in a namespaced file (e.g. `outlook_daily_brief_prefs.json`): `location`, `calendar_connected`, `email_connected`, `enabled_sections` (weather, calendar, email). Sections can be turned off; missing or failed sections are skipped in the brief without being announced.

**6. Errors**  
Each section fails on its own. If every fetch fails, the user hears: “I’m having trouble reaching some services right now. Let me try again in a moment.” No crash; the ability resumes normal flow.

---

## Setup: Client ID and Refresh Token

Configure `CLIENT_ID` and `REFRESH_TOKEN` in `main.py` (and keep `TENANT_ID = "consumers"` for personal Microsoft accounts).

**Use the `refresh_token` folder** for step-by-step setup:

1. **`refresh_token/README.md`** — Create an Entra app, add delegated permissions (`Calendars.Read`, `Mail.Read`), enable public client flow.
2. **`refresh_token/get_refresh_token.py`** — Set the same `CLIENT_ID`, run it, sign in at microsoft.com/devicelogin, then copy the printed **refresh token** into `main.py` as `REFRESH_TOKEN`.

Same `CLIENT_ID` goes in both the script and `main.py`; the script gives you the `REFRESH_TOKEN` to paste into `main.py`.
