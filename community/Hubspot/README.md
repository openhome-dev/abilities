https://www.loom.com/share/dc6f140be89b417f9a0e91c4b4b20ecf
# HubSpot CRM Ability - Voice-Powered CRM Assistant

Transform your HubSpot into a voice-first CRM. Search contacts, check deals, log notes, create tasks, and update your pipeline—all by voice, no laptop required.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Why This Ability?](#why-this-ability)
- [Prerequisites](#prerequisites)
- [Setup Guide](#setup-guide)
- [The 6 Modes](#the-6-modes)
- [Usage Examples](#usage-examples)
- [Technical Architecture](#technical-architecture)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)
- [File Structure](#file-structure)

---

## 🎯 Overview

This OpenHome ability gives you voice control over your HubSpot CRM through 6 powerful modes:

1. **Search Contacts** - Find contact details instantly
2. **Search Deals** - Check deal status and values
3. **Log Note** - Capture insights while they're fresh
4. **Create Task** - Set reminders with natural dates
5. **Pipeline Summary** - Get instant pipeline overview
6. **Move Deal Stage** - Update deal stages by voice

**Your CRM, at the speed of speech.**

---

## 💡 Why This Ability?

The LLM has **zero access** to your HubSpot account. It can't search contacts, look up deals, or log any activity. This ability bridges voice → HubSpot CRM API → your actual CRM data.

**Without it:** The LLM can only talk about sales concepts hypothetically.  
**With it:** You can interact with your real pipeline, contacts, and deals by voice.

**Perfect for:**
- Sales reps between meetings
- Founders juggling multiple roles
- Account managers managing dozens of accounts
- Anyone who lives in HubSpot but isn't always at their desk

---

## ✅ Prerequisites

1. **HubSpot Account** (Free or paid)
2. **Super Admin Access** (required to create Private Apps)
3. **OpenHome installed** with abilities enabled

---

## 🔧 Setup Guide

### Step 1: Create a HubSpot Private App

1. Go to your **HubSpot account**
2. Click **Settings** ⚙️ (top right)
3. Navigate to **Integrations** → **Private Apps**
4. Click **"Create a private app"**

### Step 2: Configure the App

**Basic Info:**
- **App name**: `OpenHome Voice Assistant`
- **Description**: `Voice-powered CRM assistant for OpenHome`

**Scopes Tab** - Enable these permissions:

✅ **Contacts:**
- `crm.objects.contacts.read` - Read contacts
- `crm.objects.contacts.write` - Create/update contacts

✅ **Companies:**
- `crm.objects.companies.read` - Read companies

✅ **Deals:**
- `crm.objects.deals.read` - Read deals
- `crm.objects.deals.write` - Create/update deals
- `crm.schemas.deals.read` - Read deal pipelines/stages

✅ **Owners:**
- `crm.objects.owners.read` - Read users/owners

✅ **Engagements:**
- `sales-email-read` - Read notes and tasks

### Step 3: Get Your Access Token

1. Click **"Create app"**
2. Review permissions → **"Continue creating"**
3. Click **"Show token"**
4. **Copy the token** (format: `pat-na2-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
5. ⚠️ **Save it immediately** - you won't see it again!

### Step 4: Install the Ability

1. Copy these files to your OpenHome abilities folder:
   - `main.py`
   - `__init__.py`
   - `README.md`
2. Set the ability's unique name and trigger words in the OpenHome dashboard.

3. Open `main.py` and replace the placeholder token on **line 20**:
   ```python
   API_TOKEN: ClassVar[str] = "YOUR_TOKEN_HERE"
   ```
   
   With your actual token:
   ```python
   API_TOKEN: ClassVar[str] = "pat-na2-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
   ```

3. Restart OpenHome

### Step 5: Verify Setup

Test the connection:

```bash
# PowerShell
Invoke-RestMethod -Uri "https://api.hubapi.com/account-info/v3/details" `
  -Headers @{"Authorization"="Bearer YOUR_TOKEN_HERE"}
```

**Expected Response:**
```json
{
  "portalId": 12345678,
  "timeZone": "US/Eastern",
  "currency": "USD"
}
```

✅ If you see this, you're ready to go!

---

## 🎯 The 6 Modes

### Mode 1: Search Contacts

**What it does:**
- Searches HubSpot contacts by name or email
- Speaks back: name, company, email, phone, lifecycle stage
- Caches result for follow-up commands

**Voice Triggers:**
- "Look up Sarah Chen"
- "Find the contact at Acme"
- "Who is john@acme.com"
- "Search for Ali"

**Example:**
```
User: "Look up Sarah Chen"
App: "I found Sarah Chen. She's at Acme Corp, email sarah@acme.com, 
      phone 555-1234. She's currently a qualified lead."
```

**Features:**
- ✅ Smart filtering (single name, full name, email)
- ✅ Handles multiple results ("I found 3 contacts...")
- ✅ Lifecycle stage formatting (machine → human readable)

---

### Mode 2: Search Deals

**What it does:**
- Searches deals by name
- Fetches pipeline stage names (auto-caches for 30 min)
- Speaks back: deal name, stage, amount, close date, owner

**Voice Triggers:**
- "How's the Acme deal?"
- "What's the status of Project Phoenix?"
- "Check the Widget Co deal"

**Example:**
```
User: "How's the Acme deal?"
App: "The Acme Corp deal is in Contract Sent. It's worth fifteen thousand 
      dollars. Close date: March 15th. It's owned by Jake."
```

**Features:**
- ✅ Stage ID → Label mapping (e.g., `contractsent` → "Contract Sent")
- ✅ Currency formatting ($15,000 → "fifteen thousand dollars")
- ✅ Date formatting (2026-03-15 → "March 15th")
- ✅ Owner resolution (ID → first name)

---

### Mode 3: Log Note

**What it does:**
- Creates a note in HubSpot
- Associates with contact or company
- No confirmation needed (speed is the point!)

**Voice Triggers:**
- "Log a note on Acme: they want to move forward"
- "Add a note to Sarah Chen: interested in enterprise plan"
- "Note for TechCorp: follow up about pricing"

**Example:**
```
User: "Log a note on Acme: they want to move forward with the enterprise plan"
App: "Done. I've logged a note on Acme Corp: they want to move forward 
      with the enterprise plan"
```

**Features:**
- ✅ LLM parsing (extracts target + content)
- ✅ Smart target search (tries contact, then company)
- ✅ Instant logging (appears in HubSpot timeline immediately)

---

### Mode 4: Create Task

**What it does:**
- Creates a task in HubSpot
- Parses natural language dates
- Associates with contact, company, or deal

**Voice Triggers:**
- "Create a task: send proposal to Acme by Friday"
- "Remind me to follow up with Sarah next Monday"
- "Task for Widget Co: schedule a demo, high priority"

**Example:**
```
User: "Create a task: send proposal to Acme by Friday"
App: "Done. I've created a task: send proposal to Acme, due Friday, 
      medium priority, associated with Acme."
```

**Date Parsing:**
| User Says | Parsed To | Time |
|-----------|-----------|------|
| "tomorrow" | Tomorrow | 9:00 AM |
| "today" | Today | 5:00 PM |
| "Friday" | This/Next Friday | 5:00 PM |
| "next Monday" | Next Monday | 9:00 AM |
| (no date) | Tomorrow | 9:00 AM |

**Priority Levels:**
- HIGH - "high priority"
- MEDIUM - (default)
- LOW - "low priority"

---

### Mode 5: Pipeline Summary

**What it does:**
- Fetches all open deals
- Groups by pipeline stage
- Calculates totals per stage
- Speaks concise summary

**Voice Triggers:**
- "How's my pipeline?"
- "Give me a pipeline summary"
- "What deals do I have open?"

**Example:**
```
User: "How's my pipeline?"
App: "Here's your pipeline. You have 12 open deals worth 187 thousand dollars 
      total. 3 deals in Appointment Scheduled worth 45 thousand dollars. 
      4 deals in Qualified to Buy worth 62 thousand dollars..."
```

**Features:**
- ✅ Pagination support (handles 100+ deals)
- ✅ Sorts by deal count (most active stages first)
- ✅ Speaks top 6 stages only (voice-friendly)
- ✅ Null-safe (treats missing amounts as $0)

---

### Mode 6: Move Deal Stage

**What it does:**
- Updates deal pipeline stage
- **Requires confirmation** (destructive action)
- Supports fuzzy matching and aliases

**Voice Triggers:**
- "Move the Acme deal to contract sent"
- "Update Widget Co to closed won"
- "Mark Acme as closed lost"

**Example:**
```
User: "Move the Acme deal to closed won"
App: "I'll move the Acme deal from Contract Sent to Closed Won. Confirm?"
User: "Yes"
App: "Done. I've moved Acme to Closed Won."
```

**Stage Aliases:**
| User Says | Interpreted As |
|-----------|----------------|
| "won" or "one" | Closed Won |
| "lost" | Closed Lost |
| "contract" | Contract Sent |
| "presentation" or "demo" | Presentation Scheduled |
| "appointment" | Appointment Scheduled |
| "qualified" | Qualified to Buy |

**Speech Recognition Fix:**
- Handles "closed **one**" → "Closed Won" (common STT error)

---

## 🗣️ Usage Examples

### Full Session Example

```
User: "CRM"
App: "HubSpot Ready. What would you like to do?"

User: "Look up Sarah Chen"
App: "I found Sarah Chen. She's at Acme Corp, email sarah@acme.com..."
App: "What would you like to do?"

User: "Log a note on her: interested in demo"
App: "Done. I've logged a note on Sarah Chen: interested in demo"
App: "What would you like to do?"

User: "Create a task: send demo link by tomorrow"
App: "Done. I've created a task: send demo link, due tomorrow..."
App: "What would you like to do?"

User: "How's my pipeline?"
App: "Here's your pipeline. You have 8 open deals worth 250 thousand..."
App: "What would you like to do?"

User: "Done"
App: "Goodbye."
```

### Quick Actions

**Morning Pipeline Check:**
```
"CRM" → "How's my pipeline?" → "Done"
```

**Pre-Meeting Prep:**
```
"CRM" → "Look up Sarah Chen" → "Done"
```

**Post-Meeting Follow-up:**
```
"CRM" → "Log a note on Acme: they're ready to sign" → 
"Create a task: send contract by Friday" → "Done"
```

---

## 🏗️ Technical Architecture

### API Integration

**Base URL:** `https://api.hubapi.com`  
**Auth:** Bearer token (Private App)  
**Rate Limits:** 100 requests/10 seconds

### Key Components

**1. Mode Detection**
- Priority-based keyword matching
- Specific modes checked before generic ones
- Example: "move deal" checked before "deal"

**2. LLM Integration**
- Uses `text_to_text_response()` for parsing
- Extracts structured data from natural language
- Examples: contact names, deal names, task details

**3. Caching System**
- **Pipelines:** 30-minute TTL
- **Owners:** 30-minute TTL
- **Recent Results:** Session-based (for follow-up)

**4. Data Flow**

```
Voice Input → STT → Mode Detection → Route to Handler
                                            ↓
                                    API Call to HubSpot
                                            ↓
                                    Process Response
                                            ↓
                                    Format for Voice
                                            ↓
                                    TTS → Voice Output
```

### File Structure

```
hubspot_ability/
├── main.py              # Core capability (700+ lines)
├── __init__.py          # Package initialization
└── README.md           # This file
```

Trigger words and the ability's unique name are managed in the OpenHome dashboard.

### Preferences File

**Location:** `hubspot_crm_prefs.json` (auto-created)

**Structure:**
```json
{
  "pipelines": [...],
  "pipeline_cache_updated": "2026-02-26T14:00:00Z",
  "owners": [...],
  "owners_cache_updated": "2026-02-26T14:00:00Z",
  "recent_results": {
    "type": "contact",
    "items": [...]
  }
}
```

---

## 🔌 API Reference

### Endpoints Used

| Endpoint | Method | Mode | Purpose |
|----------|--------|------|---------|
| `/account-info/v3/details` | GET | Setup | Validate token |
| `/crm/v3/objects/contacts/search` | POST | 1, 3, 4 | Search contacts |
| `/crm/v3/objects/companies/search` | POST | 3, 4 | Search companies |
| `/crm/v3/objects/deals/search` | POST | 2, 5, 6 | Search deals |
| `/crm/v3/pipelines/deals` | GET | 2, 5, 6 | Get pipeline stages |
| `/crm/v3/owners` | GET | 2 | Get team members |
| `/crm/v3/objects/notes` | POST | 3 | Create note |
| `/crm/v3/objects/tasks` | POST | 4 | Create task |
| `/crm/v3/objects/deals/{id}` | PATCH | 6 | Update deal stage |

### Association Type IDs

**Notes:**
- Note → Contact: `202`
- Note → Company: `190`
- Note → Deal: `214`

**Tasks:**
- Task → Contact: `204`
- Task → Company: `192`
- Task → Deal: `216`

### Search Operators

| Operator | Use Case | Example |
|----------|----------|---------|
| `EQ` | Exact match | Email search |
| `CONTAINS_TOKEN` | Word match | Name search |
| `NOT_IN` | Exclusion | Open deals (not won/lost) |

---

## 🐛 Troubleshooting

### "Token validation failed"

**Cause:** Invalid or revoked token

**Fix:**
1. Go to HubSpot → Settings → Integrations → Private Apps
2. Find your app
3. Click "Rotate token" or create new app
4. Update token in `main.py` line 20

---

### "I couldn't find [contact/company/deal]"

**Cause:** Record doesn't exist in HubSpot

**Fix:**
1. Go to HubSpot web UI
2. Verify the contact/company/deal exists
3. Check spelling matches exactly
4. Try searching in HubSpot first

---

### "No digits found in 'two minutes'"

**Cause:** Word number parsing (already fixed in current version)

**Fix:** Update to latest `main.py` - supports word numbers

---

### Mode detection wrong (e.g., "move deal" → searches instead)

**Cause:** Old version of code

**Fix:** Use latest `main.py` with corrected detection order

---

### "Speech recognition hearing 'one' instead of 'won'"

**Already Fixed:** Code includes alias `"one"` → `"closed won"`

---

### Pipeline cache is stale

**Cause:** Cache older than 30 minutes

**Fix:** Automatic refresh - just wait or restart ability

---

## 🔍 Verification

### Check Created Notes

1. Go to HubSpot → **Contacts** or **Companies**
2. Click the record (e.g., Acme)
3. Scroll to **Activity Timeline**
4. Look for notes with today's timestamp

### Check Created Tasks

1. Go to HubSpot → **Tasks**
2. Filter by "Not Started"
3. Look for tasks with subject matching your voice input

### Check Deal Updates

1. Go to HubSpot → **Deals**
2. Click the deal
3. Check current stage matches what you said

---

## 📊 Quick Reference Card

| Mode | Trigger | Example |
|------|---------|---------|
| **1** | "look up" | "Look up Sarah Chen" |
| **2** | "how's the [deal]" | "How's the Acme deal?" |
| **3** | "log note" | "Log a note on Acme: ..." |
| **4** | "create task" | "Create a task: send proposal by Friday" |
| **5** | "pipeline" | "How's my pipeline?" |
| **6** | "move" or "update" | "Move Acme to closed won" |
| **Exit** | "done" | "Done" |

---

## 🎓 Tips & Best Practices

1. **Say "CRM" to activate** - Don't try commands without activating first
2. **Be specific with names** - Use full names when possible
3. **Natural dates work** - "tomorrow", "Friday", "next Monday"
4. **Confirmation is mandatory** - Mode 6 always asks before updating
5. **Say "Done" to exit** - Clean exit back to normal personality
6. **Check HubSpot to verify** - Always verify critical updates in web UI

---

## 🚀 Future Enhancements (V2 Ideas)

- ✨ Create contacts by voice
- ✨ Create deals by voice
- ✨ Log calls and meetings
- ✨ Custom property access
- ✨ Multi-pipeline support
- ✨ Batch operations

---

## 📝 License & Credits

**Built for:** OpenHome Abilities Platform  
**API:** HubSpot CRM API v3  
**Author:** Your Team  
**Version:** 1.0.0  
**Last Updated:** February 2026

---

## 💬 Support

**Issues?** Check the troubleshooting section above.

**Feature requests?** Document them for V2 planning.

**Questions?** Review the mode examples and API reference.

---

**🎉 You're all set! Say "CRM" and start managing your pipeline by voice.**
