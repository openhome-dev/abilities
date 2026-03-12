https://www.loom.com/share/5aeb45f472794102ae31ccb6a9ac84bb
# Salesforce CRM Voice Assistant - Complete Guide

## 🎉 **Overview**

A complete voice-powered Salesforce CRM integration for OpenHome that lets you search contacts, manage opportunities, log notes, create tasks, view pipeline summaries, and update deal stages — all by voice.

### **Why This Ability?**

Salesforce is powerful but heavy. Updating a record means navigating to it, clicking Edit, changing a field, clicking Save. This ability collapses that to a sentence:
- **"Log a note on Acme: they want to move forward"** → Creates note instantly
- **"How's my pipeline?"** → Instant summary across all stages
- **"Move the Acme deal to Closed Won"** → Updates with one confirmation

---

## ✅ **What It Can Do - All 6 Modes**

| Mode | Voice Trigger | What It Does |
|------|---------------|--------------|
| **1. Search Contacts** | "Look up Sarah Chen" | Search by name/email, speak details |
| **2. Search Opportunities** | "How's the Acme deal?" | Search deals, speak stage/amount/date |
| **3. Log Note** | "Log a note on Acme..." | Creates completed Task as note |
| **4. Create Task** | "Create a task: send proposal by Friday" | Task with due date, priority, associations |
| **5. Pipeline Summary** | "How's my pipeline?" | GROUP BY aggregation, totals by stage |
| **6. Move Stage** | "Move Acme to Closed Won" | Update opportunity stage with confirmation |

---

## 📋 **Table of Contents**

1. [Prerequisites](#prerequisites)
2. [Setup Guide](#setup-guide)
   - [Create Salesforce Developer Account](#step-1-create-salesforce-developer-account)
   - [Create Connected App](#step-2-create-connected-app)
   - [Get OAuth Tokens](#step-3-get-oauth-tokens)
   - [Add Test Data](#step-4-add-test-data)
3. [Installation](#installation)
4. [All 6 Modes - Complete Guide](#all-6-modes---complete-guide)
5. [Usage Examples](#usage-examples)
6. [Technical Details](#technical-details)
7. [Troubleshooting](#troubleshooting)
8. [API Reference](#api-reference)

---

## 📦 **Prerequisites**

### **What You Need:**
- ✅ Salesforce account (Free Developer Edition works!)
- ✅ **Admin/Super Admin access** (required to create Connected Apps)
- ✅ PowerShell (for OAuth setup and testing)
- ✅ 30 minutes for initial setup

---

## 🔧 **Setup Guide**

### **Step 1: Create Salesforce Developer Account**

If you don't have Salesforce:

1. Go to: https://developer.salesforce.com/signup
2. Fill out the form (use real email)
3. Check your email and verify
4. You'll get a **Developer Edition** org (free forever)
5. Set your password and security question

**Your org URL will be:** `https://yourorg-dev-ed.develop.my.salesforce.com`

---

### **Step 2: Create Connected App**

This is where OAuth credentials come from.

#### **2.1 Navigate to Setup**

1. Log in to Salesforce
2. Click the **⚙️ gear icon** (top right)
3. Click **Setup**

#### **2.2 Open App Manager**

**In Classic View:**
1. Quick Find: `Apps`
2. Click **Apps** under **Create**
3. Scroll to **Connected Apps** section
4. Click **New** button

**In Lightning View:**
1. Quick Find: `App Manager`
2. Click **App Manager**
3. Click **New Connected App**

#### **2.3 Fill Basic Information**

| Field | Value |
|-------|-------|
| **Connected App Name** | `OpenHome Voice Assistant` |
| **API Name** | `OpenHome_Voice_Assistant` (auto-fills) |
| **Contact Email** | Your email |

#### **2.4 Enable OAuth Settings**

✅ **Check** "Enable OAuth Settings"

**Callback URL:**
```
https://login.salesforce.com/services/oauth2/success
```

**Selected OAuth Scopes** - Add these:
- ✅ **Manage user data via APIs (api)**
- ✅ **Perform requests at any time (refresh_token, offline_access)**

#### **2.5 Additional Settings**

✅ **Check** "Require Secret for Web Server Flow"  
✅ **Check** "Require Secret for Refresh Token Flow"  
❌ **Uncheck** "Require Proof Key for Code Exchange (PKCE)"

**Click "Save"**

#### **2.6 Wait for Propagation**

⚠️ **IMPORTANT:** After saving, wait **10 minutes** before proceeding.

> "Your Connected App may take 2-10 minutes to be available."

☕ Take a break!

---

### **Step 3: Get OAuth Tokens**

#### **3.1 Get Consumer Key & Secret**

After 10 minutes:

1. Go to **Setup** → Quick Find: `App Manager`
2. Find **OpenHome Voice Assistant**
3. Click the **dropdown arrow** (▼) → **View**
4. Copy **Consumer Key** (starts with `3MVG9...`)
5. Click **"Click to reveal"** → Copy **Consumer Secret**

**Save both values!**

#### **3.2 Get Authorization Code**

**Build the OAuth URL** (replace `YOUR_CONSUMER_KEY`):

```
https://login.salesforce.com/services/oauth2/authorize?response_type=code&client_id=YOUR_CONSUMER_KEY&redirect_uri=https://login.salesforce.com/services/oauth2/success&scope=api%20refresh_token
```

**Steps:**
1. Copy the complete URL (with your Consumer Key)
2. Paste into your browser
3. Log in to Salesforce (if needed)
4. Click **"Allow"**
5. You'll be redirected to: `https://login.salesforce.com/services/oauth2/success?code=aPrx...`
6. **Copy the code** from the URL (everything after `code=`)

**Example:**
```
URL: https://login.salesforce.com/services/oauth2/success?code=aPrxHJK9L3mN2p...
CODE: aPrxHJK9L3mN2p...
```

⏰ **Act fast!** Authorization codes expire in **90 seconds**.

#### **3.3 Exchange Code for Tokens**

**Open PowerShell** and run (replace the values):

```powershell
$body = @{
    grant_type = "authorization_code"
    code = "YOUR_AUTH_CODE"
    client_id = "YOUR_CONSUMER_KEY"
    client_secret = "YOUR_CONSUMER_SECRET"
    redirect_uri = "https://login.salesforce.com/services/oauth2/success"
}

$response = Invoke-RestMethod -Uri "https://login.salesforce.com/services/oauth2/token" -Method POST -Body $body -ContentType "application/x-www-form-urlencoded"

$response | ConvertTo-Json
```

**Expected Response:**
```json
{
  "access_token": "00D5g000007Xxxx!ARoAQP...",
  "refresh_token": "5Aep861W8Kh...",
  "instance_url": "https://yourorg.my.salesforce.com",
  "id": "https://login.salesforce.com/id/00D.../005...",
  "token_type": "Bearer",
  "issued_at": "1708300000000"
}
```

#### **3.4 Save These Values**

From the response, save:

1. ✅ **access_token** - Short-lived (2 hours)
2. ✅ **refresh_token** - Long-lived (doesn't expire unless revoked)
3. ✅ **instance_url** - Your unique Salesforce org URL

#### **3.5 Test the API**

Verify everything works:

```powershell
$headers = @{
    "Authorization" = "Bearer YOUR_ACCESS_TOKEN"
}

$uri = "YOUR_INSTANCE_URL/services/data/v62.0/query?q=SELECT+Id,Name+FROM+Account+LIMIT+5"

Invoke-RestMethod -Uri $uri -Headers $headers | ConvertTo-Json
```

✅ If you see account data, your API access is working!

---

### **Step 4: Add Test Data**

Your Developer Edition comes with sample data, but let's add clean test data.

#### **4.1 Delete Sample Data (Optional)**

**Empty the org:**

```powershell
$token = "YOUR_ACCESS_TOKEN"
$instance = "YOUR_INSTANCE_URL"
$headers = @{"Authorization" = "Bearer $token"}

# Get all opportunities
$uri = "$instance/services/data/v62.0/query?q=SELECT+Id,Name+FROM+Opportunity"
$result = Invoke-RestMethod -Uri $uri -Headers $headers

# Delete each one
foreach ($opp in $result.records) {
    $deleteUri = "$instance/services/data/v62.0/sobjects/Opportunity/$($opp.Id)"
    Invoke-RestMethod -Uri $deleteUri -Method DELETE -Headers $headers
}

Write-Host "Deleted! Now empty Recycle Bin in Salesforce UI."
```

Then in Salesforce:
1. App Launcher → **Recycle Bin**
2. Click **"Empty Recycle Bin"**

#### **4.2 Add Test Contacts**

**Via Web UI:**
1. Go to Salesforce → **Contacts** tab → **New**
2. Fill in:
   - First Name: Sarah
   - Last Name: Chen
   - Account: Edge Communications
   - Title: VP of Engineering
   - Email: sarah@edge.com
   - Phone: 555-1234
3. Click **Save**

**Via PowerShell:**

```powershell
$token = "YOUR_ACCESS_TOKEN"
$instance = "YOUR_INSTANCE_URL"
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

# Get account IDs
$accounts = Invoke-RestMethod -Uri "$instance/services/data/v62.0/query?q=SELECT+Id,Name+FROM+Account+LIMIT+5" -Headers $headers

$edgeId = ($accounts.records | Where-Object {$_.Name -like "*Edge*"}).Id

# Create contact
$contact = @{
    FirstName = "Sarah"
    LastName = "Chen"
    AccountId = $edgeId
    Title = "VP of Engineering"
    Email = "sarah@edge.com"
    Phone = "555-1234"
} | ConvertTo-Json

Invoke-RestMethod -Uri "$instance/services/data/v62.0/sobjects/Contact" -Method POST -Headers $headers -Body $contact

Write-Host "✅ Sarah Chen created!"
```

**Repeat for more contacts:**
- John Miller at Burlington Textiles
- Emily Davis at Pyramid Construction

#### **4.3 Add Test Opportunities**

**Via PowerShell:**

```powershell
# Create opportunity
$opp = @{
    Name = "Acme Enterprise Deal"
    AccountId = $edgeId
    StageName = "Prospecting"
    CloseDate = "2026-06-30"
    Amount = 500000
} | ConvertTo-Json

Invoke-RestMethod -Uri "$instance/services/data/v62.0/sobjects/Opportunity" -Method POST -Headers $headers -Body $opp

Write-Host "✅ Acme Enterprise Deal created!"
```

**Add 1-2 more opportunities for testing.**

---

## 📥 **Installation**

### **Step 1: Update Credentials in Code**

Open `salesforce_main.py` and update lines 18-22:

```python
CONSUMER_KEY: ClassVar[str] = "YOUR_CONSUMER_KEY"
CONSUMER_SECRET: ClassVar[str] = "YOUR_CONSUMER_SECRET"
INSTANCE_URL: ClassVar[str] = "YOUR_INSTANCE_URL"
INITIAL_ACCESS_TOKEN: ClassVar[str] = "YOUR_ACCESS_TOKEN"
INITIAL_REFRESH_TOKEN: ClassVar[str] = "YOUR_REFRESH_TOKEN"
```

### **Step 2: Copy Files to OpenHome**

Copy these files to your OpenHome abilities folder:
- `salesforce_main.py`
- `salesforce_config.json`
- `salesforce__init__.py`

### **Step 3: Restart OpenHome**

Restart the OpenHome service/application.

### **Step 4: Test**

Say: **"Salesforce"**

You should hear: **"Salesforce Ready. What would you like to do?"**

✅ If you hear that, installation is successful!

---

## 🎯 **All 6 Modes - Complete Guide**

---

### **Mode 1: Search Contacts**

**What It Does:**
- Search contacts by name or email
- Speak back: name, title, company, email, phone
- Handle single/multiple/zero results
- Smart disambiguation

**Voice Triggers:**
- "Look up Sarah Chen"
- "Find john@acme.com"
- "Who is the VP at Edge Communications"
- "Search for Emily"

**How It Works:**

1. **Email Search (Exact Match):**
```sql
SELECT Id, Name, Email, Phone, Title, Account.Name
FROM Contact
WHERE Email = 'sarah@edge.com'
LIMIT 5
```

2. **Name Search (Fuzzy Match via SOSL):**
```
FIND {Sarah Chen} IN NAME FIELDS
RETURNING Contact(Id, Name, Email, Phone, Title, Account.Name)
LIMIT 5
```

**Response Patterns:**

**Single Result:**
```
"I found Sarah Chen. She's the VP of Engineering at Edge Communications. 
Email sarah@edge.com, phone 555-1234."
```

**Multiple Results:**
```
"I found 3 contacts. Sarah Chen, VP Engineering at Edge Communications. 
Sarah Park, Director at Widget Co. Sarah Jones at TechCorp. Which one?"

User: "The first one"
App: [Shows full details for Sarah Chen]
```

**Zero Results:**
```
"I couldn't find any contacts matching that. Want me to search accounts instead?"
```

**Test Commands:**
```
"Salesforce"
"Look up Sarah Chen"
"Find john@edge.com"
"Search for Emily"
```

---

### **Mode 2: Search Opportunities**

**What It Does:**
- Search opportunities by name
- Speak: name, stage, amount, close date, account, owner
- Currency formatting ("50 thousand dollars")
- Date formatting ("March 31st")
- Single/multiple/zero results

**Voice Triggers:**
- "How's the Acme deal?"
- "What's the status of the Enterprise opportunity?"
- "Check the Widget Co deal"

**How It Works:**

```sql
SELECT Id, Name, StageName, Amount, CloseDate,
  Account.Name, Owner.FirstName, Owner.LastName
FROM Opportunity
WHERE Name LIKE '%Acme%'
  AND IsClosed = false
LIMIT 5
```

**Response Pattern:**
```
"The Acme Enterprise Deal opportunity is in Prospecting. 
It's worth 500 thousand dollars. Close date: June 30th. 
Account is Edge Communications. Owned by Haseeb."
```

**Currency Formatting:**
- $50,000 → "50 thousand dollars"
- $1,500,000 → "1.5 million dollars"
- $75,000 → "75 thousand dollars"

**Date Formatting:**
- 2026-03-15 → "March 15th"
- 2026-12-01 → "December 1st"

**Test Commands:**
```
"How's the Acme deal?"
"What's the status of the Enterprise opportunity?"
```

---

### **Mode 3: Log Note**

**What It Does:**
- Creates a completed Task as a note
- LLM parses target (contact/account/opportunity) and content
- Proper associations (WhoId/WhatId)
- No confirmation needed (speed!)

**Voice Triggers:**
- "Log a note on Acme: they want to move forward"
- "Add a note to Sarah Chen: she's interested in the demo"
- "Note for the Enterprise deal: discussed pricing"

**How It Works:**

1. **Parse Command:**
```
Input: "log a note on Acme: they want to move forward with enterprise"
Output: {
  "target": "Acme",
  "content": "they want to move forward with enterprise"
}
```

2. **Find Target:**
- Searches Contacts for "Acme"
- If not found, searches Accounts for "Acme"
- If not found, searches Opportunities for "Acme"

3. **Create Task:**
```json
POST /sobjects/Task
{
  "Subject": "Voice Note: they want to move forward with enterprise",
  "Description": "Captured via OpenHome voice: they want to move forward with enterprise",
  "Status": "Completed",
  "Priority": "Normal",
  "ActivityDate": "2026-03-05",
  "WhatId": "001XXXX..."  // Account ID
}
```

**Association Logic:**

| Target Type | Field Used |
|-------------|------------|
| Contact | `WhoId` |
| Account | `WhatId` |
| Opportunity | `WhatId` |

**Response:**
```
"Done. I've logged a note on Acme: they want to move forward with enterprise"
```

**Verification:**
1. Go to Salesforce → Accounts → Acme
2. Scroll to **Activity** timeline
3. See the completed Task with your note

**Test Commands:**
```
"Log a note on Edge Communications: they want to move forward"
"Add a note to Sarah Chen: she's interested in the demo"
```

---

### **Mode 4: Create Task**

**What It Does:**
- Create tasks with due date and priority
- Natural language date parsing
- Optional target (contact/account/opportunity)
- Smart defaults (tomorrow, Normal priority)

**Voice Triggers:**
- "Create a task: send proposal to Acme by Friday"
- "Remind me to follow up with Sarah tomorrow"
- "Task for the Enterprise deal: schedule demo, high priority"

**How It Works:**

1. **Parse Command:**
```
Input: "create a task: send proposal to Acme by Friday"
Output: {
  "subject": "send proposal to Acme",
  "due_date": "Friday",
  "priority": "Normal",
  "target": "Acme"
}
```

2. **Parse Due Date:**
```
"tomorrow" → 2026-03-06
"Friday" → 2026-03-07 (this Friday)
"next Monday" → 2026-03-10
"today" → 2026-03-05
(no date) → Tomorrow (default)
```

3. **Create Task:**
```json
POST /sobjects/Task
{
  "Subject": "send proposal to Acme",
  "Description": "Voice-created via OpenHome",
  "ActivityDate": "2026-03-07",
  "Status": "Not Started",
  "Priority": "Normal",
  "WhatId": "001XXXX..."
}
```

**Date Parsing:**

| User Says | Parsed To |
|-----------|-----------|
| "tomorrow" | Tomorrow |
| "today" | Today |
| "Friday" | This/Next Friday |
| "next Monday" | Next Monday |
| "Tuesday" | This/Next Tuesday |
| (no date) | Tomorrow (default) |

**Priority Levels:**

| User Says | Salesforce Value |
|-----------|------------------|
| "high priority" | High |
| "low priority" | Low |
| (nothing) | Normal (default) |

**Response:**
```
"Done. I've created a task: send proposal to Acme, due Friday, for Acme."
```

**Test Commands:**
```
"Create a task: send proposal to Acme by Friday"
"Remind me to follow up with Sarah tomorrow"
"Task for Enterprise: schedule demo, high priority"
```

---

### **Mode 5: Pipeline Summary**

**What It Does:**
- SOQL GROUP BY aggregation (server-side!)
- Total deal count and value
- Breakdown by stage with counts and values
- Sorted by value (highest first)
- Speaks top 6 stages

**Voice Triggers:**
- "How's my pipeline?"
- "What opportunities do I have open?"
- "Show my pipeline"
- "How many deals do I have?"

**How It Works:**

1. **Query Totals:**
```sql
SELECT COUNT(Id) cnt, SUM(Amount) total
FROM Opportunity
WHERE IsClosed = false
```

2. **Query Breakdown:**
```sql
SELECT StageName, COUNT(Id) cnt, SUM(Amount) total
FROM Opportunity
WHERE IsClosed = false
GROUP BY StageName
ORDER BY SUM(Amount) DESC
```

**Response:**
```
"Here's your pipeline. You have 3 open opportunities worth 1.1 million dollars total. 
2 deals in Prospecting worth 750 thousand dollars. 
1 deal in Qualification worth 350 thousand dollars."
```

**Key Advantage Over HubSpot:**

**HubSpot:** Must fetch ALL deals client-side, then aggregate in Python  
**Salesforce:** Single query, server-side aggregation with GROUP BY ✅

**Test Commands:**
```
"How's my pipeline?"
"What opportunities do I have open?"
```

---

### **Mode 6: Move Opportunity Stage**

**What It Does:**
- Update opportunity stage
- Smart stage matching with aliases
- **CONFIRMATION REQUIRED** (safety!)
- Shows current → target stage
- Speech recognition aliases ("closed one" → "closed won")

**Voice Triggers:**
- "Move the Acme deal to Qualification"
- "Update Enterprise to Closed Won"
- "Mark the Widget opportunity as Closed Lost"

**How It Works:**

1. **Parse Command:**
```
Input: "move the Acme deal to closed won"
Output: {
  "opportunity_name": "Acme",
  "target_stage": "closed won"
}
```

2. **Find Opportunity:**
```sql
SELECT Id, Name, StageName
FROM Opportunity
WHERE Name LIKE '%Acme%'
LIMIT 1
```

3. **Match Stage Name:**
```
User says: "closed won"
Matches to: "Closed Won" (exact)

User says: "won"
Alias matches to: "Closed Won"

User says: "qualification"
Matches to: "Qualification"
```

4. **Confirm:**
```
"I'll move the Acme Enterprise Deal from Prospecting to Closed Won. Confirm?"

User: "Yes"
```

5. **Update:**
```json
PATCH /sobjects/Opportunity/006XXX...
{
  "StageName": "Closed Won"
}
```

**Stage Aliases:**

| User Says | Matches To |
|-----------|-----------|
| "won" | Closed Won |
| "we won it" | Closed Won |
| "closed one" | Closed Won (STT fix) |
| "lost" | Closed Lost |
| "dead" | Closed Lost |
| "qualified" | Qualification |
| "proposal" | Proposal/Price Quote |
| "negotiation" | Negotiation/Review |
| "value prop" | Value Proposition |

**Response:**
```
"I'll move the Acme Enterprise Deal from Prospecting to Closed Won. Confirm?"
[User says "Yes"]
"Done. I've moved Acme Enterprise Deal to Closed Won."
```

**Test Commands:**
```
"Move the Acme deal to Qualification"
"Update Enterprise to Closed Won"
"Mark Acme as Closed Lost"
```

---

## 🎯 **Usage Examples**

### **Complete Session Flow:**

```
User: "Salesforce"
App: "Salesforce Ready. What would you like to do?"

User: "Look up Sarah Chen"
App: "Searching for contacts..."
App: "I found Sarah Chen. She's the VP of Engineering at Edge Communications. 
      Email sarah@edge.com, phone 555-1234."

User: "How's the Acme deal?"
App: "Searching for opportunities..."
App: "The Acme Enterprise Deal opportunity is in Prospecting. 
      It's worth 500 thousand dollars. Close date: June 30th. 
      Account is Edge Communications. Owned by Haseeb."

User: "Log a note on it: they want to move forward with the enterprise plan"
App: "Logging a note..."
App: "Done. I've logged a note on Acme Enterprise Deal: 
      they want to move forward with the enterprise plan"

User: "Create a task: send proposal by Friday, high priority"
App: "Creating a task..."
App: "Done. I've created a task: send proposal, due Friday, high priority."

User: "How's my pipeline?"
App: "Getting your pipeline summary..."
App: "Here's your pipeline. You have 2 open opportunities worth 1.1 million dollars total. 
      2 deals in Prospecting worth 1.1 million dollars."

User: "Move the Acme deal to Qualification"
App: "Updating opportunity stage..."
App: "I'll move the Acme Enterprise Deal from Prospecting to Qualification. Confirm?"

User: "Yes"
App: "Done. I've moved Acme Enterprise Deal to Qualification."

User: "Done"
App: "Goodbye."
```

---

## 🔧 **Technical Details**

### **Architecture**

**OAuth 2.0 Flow:**
1. User creates Connected App
2. Browser-based consent flow
3. Exchange authorization code for tokens
4. Auto-refresh every 2 hours
5. Refresh token reused (never expires unless revoked)

**Token Refresh:**
```python
# Checked before every API call
if token_age > 7200:  # 2 hours
    refresh_access_token()
```

**API Request Pattern:**
```python
async def sf_request(method, path, data=None):
    # 1. Check token age, refresh if needed
    # 2. Make request with Authorization header
    # 3. Handle 401 with one retry after refresh
    # 4. Return result
```

### **SOQL vs SOSL**

**SOQL (SQL-like queries):**
- Exact field matching
- Aggregation (COUNT, SUM, GROUP BY)
- Relationship traversal (Account.Name)
- Used for: opportunities, pipeline summary, exact email

**SOSL (Full-text search):**
- Fuzzy matching across multiple objects
- Better for partial names
- Used for: contact name search

### **URL Encoding**

Salesforce accepts minimal encoding:
```python
# Only encode spaces as +
encoded = soql.replace(" ", "+")
# Leave commas, quotes, parentheses unencoded
```

### **Association Logic**

**WhoId vs WhatId:**
- `WhoId` → Contacts and Leads (people)
- `WhatId` → Accounts, Opportunities, other objects (things)

**Example:**
```json
{
  "WhoId": "003XXX...",  // Sarah Chen (Contact)
  "WhatId": "001XXX..."  // Edge Communications (Account)
}
```

### **Date Parsing**

```python
def parse_due_date(text):
    if "tomorrow" in text:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "friday" in text:
        days_ahead = (4 - datetime.now().weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    # ... more patterns
```

### **Currency Formatting**

```python
def format_currency(amount):
    if amount >= 1000000:
        return f"{amount/1000000:.1f} million dollars"
    elif amount >= 1000:
        return f"{amount/1000:.0f} thousand dollars"
    else:
        return f"{amount} dollars"
```

---

## 🐛 **Troubleshooting**

### **"Invalid Client ID" Error**

**Cause:** Connected App not propagated yet  
**Fix:** Wait 10 minutes after creating Connected App

### **"401 Unauthorized" Error**

**Cause:** Access token expired  
**Fix:** Token auto-refreshes. If it persists, re-authenticate:

```powershell
# Refresh token manually
$body = @{
    grant_type = "refresh_token"
    refresh_token = "YOUR_REFRESH_TOKEN"
    client_id = "YOUR_CONSUMER_KEY"
    client_secret = "YOUR_CONSUMER_SECRET"
}

$response = Invoke-RestMethod -Uri "https://login.salesforce.com/services/oauth2/token" -Method POST -Body $body -ContentType "application/x-www-form-urlencoded"

# Update access_token in main.py
```

### **"MALFORMED_QUERY" Error**

**Cause:** URL encoding issue  
**Fix:** Already fixed in code (only encodes spaces as `+`)

### **Pipeline Shows Wrong Number of Opportunities**

**Cause:** Sample data in Developer Edition  
**Fix:** Delete all opportunities and recreate:

```powershell
# Get all opportunities
$uri = "$instance/services/data/v62.0/query?q=SELECT+Id+FROM+Opportunity"
$result = Invoke-RestMethod -Uri $uri -Headers @{"Authorization"="Bearer $token"}

# Delete each
foreach ($opp in $result.records) {
    Invoke-RestMethod -Uri "$instance/services/data/v62.0/sobjects/Opportunity/$($opp.Id)" -Method DELETE -Headers @{"Authorization"="Bearer $token"}
}

# Empty Recycle Bin in Salesforce UI
```

### **"I couldn't find any contacts/opportunities"**

**Cause:** No test data in org  
**Fix:** Add test data (see Step 4 in Setup)

### **Stage Name Not Matching**

**Cause:** Stage name different in your org  
**Fix:** Check available stages:

```powershell
$uri = "$instance/services/data/v62.0/query?q=SELECT+MasterLabel+FROM+OpportunityStage+WHERE+IsActive=true"
Invoke-RestMethod -Uri $uri -Headers @{"Authorization"="Bearer $token"}
```

Add custom aliases in `match_stage_name()` function.

---

## 📚 **API Reference**

### **Salesforce REST API v62.0**

**Base URL:** `https://{instance_url}/services/data/v62.0/`

**Authentication:**
```
Authorization: Bearer {access_token}
```

### **Core Endpoints Used**

#### **Query (SOQL)**
```
GET /query?q={SOQL_QUERY}

Example:
GET /query?q=SELECT+Id,Name+FROM+Contact+LIMIT+5
```

#### **Search (SOSL)**
```
GET /search?q={SOSL_QUERY}

Example:
GET /search?q=FIND+{Sarah}+IN+NAME+FIELDS+RETURNING+Contact(Id,Name)
```

#### **Create Record**
```
POST /sobjects/{Object}
Content-Type: application/json

Body: {field1: value1, field2: value2}

Example:
POST /sobjects/Task
{"Subject": "Follow up", "Status": "Not Started"}
```

#### **Update Record**
```
PATCH /sobjects/{Object}/{Id}
Content-Type: application/json

Body: {field1: new_value}

Example:
PATCH /sobjects/Opportunity/006XXX
{"StageName": "Closed Won"}
```

#### **Delete Record**
```
DELETE /sobjects/{Object}/{Id}

Example:
DELETE /sobjects/Opportunity/006XXX
```

### **Salesforce Objects**

#### **Contact**
```sql
SELECT Id, Name, Email, Phone, Title, Account.Name
FROM Contact
```

**Fields:**
- `Id` - Salesforce ID (18 chars)
- `Name` - Full name
- `Email` - Email address
- `Phone` - Phone number
- `Title` - Job title
- `AccountId` - Related Account ID
- `Account.Name` - Related Account name (relationship)

#### **Opportunity**
```sql
SELECT Id, Name, StageName, Amount, CloseDate, 
       Account.Name, Owner.FirstName, Owner.LastName
FROM Opportunity
```

**Fields:**
- `Id` - Salesforce ID
- `Name` - Opportunity name
- `StageName` - Current stage (human-readable)
- `Amount` - Deal value
- `CloseDate` - Expected close date (YYYY-MM-DD)
- `IsClosed` - Boolean (true if won or lost)
- `IsWon` - Boolean (true if won)
- `AccountId` - Related Account ID
- `OwnerId` - Owner user ID

**Standard Stages:**
- Prospecting
- Qualification
- Needs Analysis
- Value Proposition
- Id. Decision Makers
- Perception Analysis
- Proposal/Price Quote
- Negotiation/Review
- Closed Won
- Closed Lost

#### **Account**
```sql
SELECT Id, Name, Phone, Industry, BillingCity
FROM Account
```

**Fields:**
- `Id` - Salesforce ID
- `Name` - Company name
- `Phone` - Company phone
- `Industry` - Industry category
- `BillingCity`, `BillingState` - Address

#### **Task**
```sql
SELECT Id, Subject, Status, Priority, ActivityDate
FROM Task
```

**Fields:**
- `Id` - Salesforce ID
- `Subject` - Task title (max 255 chars)
- `Description` - Full description
- `Status` - Not Started, In Progress, Completed, Deferred
- `Priority` - High, Normal, Low
- `ActivityDate` - Due date (DATE only, no time)
- `WhoId` - Related Contact/Lead
- `WhatId` - Related Account/Opportunity

### **SOQL Operators**

```sql
-- Exact match
WHERE Email = 'sarah@acme.com'

-- Partial match
WHERE Name LIKE '%Sarah%'

-- NOT equal
WHERE StageName != 'Closed Won'

-- Boolean
WHERE IsClosed = false

-- IN list
WHERE StageName IN ('Prospecting', 'Qualification')

-- NOT IN list
WHERE StageName NOT IN ('Closed Won', 'Closed Lost')

-- Aggregation
SELECT COUNT(Id), SUM(Amount)
GROUP BY StageName

-- Order
ORDER BY Amount DESC

-- Limit
LIMIT 10
```

### **Rate Limits**

**Enterprise Edition:**
- 100,000 API calls per 24 hours (org-wide)
- 1,000 API calls per user license per 24 hours
- No per-second throttle

**Developer Edition:**
- 15,000 API calls per 24 hours

**Check Usage:**
```
GET /limits
```

---

## 🔐 **Security Notes**

### **Production Best Practices:**

1. **Never commit credentials to git**
   ```bash
   # Add to .gitignore
   *_prefs.json
   salesforce_main.py  # If it contains hardcoded tokens
   ```

2. **Use environment variables**
   ```python
   import os
   CONSUMER_KEY = os.getenv("SF_CONSUMER_KEY")
   CONSUMER_SECRET = os.getenv("SF_CONSUMER_SECRET")
   ```

3. **Rotate tokens regularly**
   - Revoke old Connected Apps
   - Create new ones every 90 days

4. **Use HTTPS only**
   - Never send tokens over HTTP
   - All Salesforce endpoints use HTTPS

5. **Minimum scopes**
   - Only request `api` and `refresh_token`
   - Don't request `full` access unless needed

### **Token Storage:**

**Current (V1):** Hardcoded in `main.py` - ⚠️ For testing only  
**Production (V2):** Encrypted storage with key rotation

---

## 📊 **Statistics**

**Implementation:**
- **~1,800 lines of code**
- **6 complete modes**
- **OAuth 2.0 with auto-refresh**
- **SOQL and SOSL queries**
- **Natural language parsing**
- **Date and currency formatting**
- **Smart disambiguation**
- **Error handling**

**API Calls per Mode:**
| Mode | API Calls |
|------|-----------|
| Search Contacts | 1 (SOSL) or 1 (SOQL) |
| Search Opportunities | 1 (SOQL) |
| Log Note | 1-3 (search) + 1 (create) |
| Create Task | 0-3 (search) + 1 (create) |
| Pipeline Summary | 2 (totals + breakdown) |
| Move Stage | 1 (search) + 1 (update) |

---

## 🎯 **Quick Reference Card**

### **Voice Commands Cheat Sheet:**

```
🔍 SEARCH
"Look up Sarah Chen"
"How's the Acme deal?"

📝 NOTES & TASKS
"Log a note on Acme: they want to move forward"
"Create a task: send proposal by Friday"

📊 PIPELINE
"How's my pipeline?"

🎯 UPDATES
"Move Acme to Closed Won"

❌ EXIT
"Done" or "Goodbye"
```

### **Quick Troubleshooting:**

| Issue | Fix |
|-------|-----|
| 401 error | Token expired, auto-refreshes |
| Can't find contact | Add test data |
| Wrong pipeline count | Delete sample data |
| Stage not matching | Check available stages in org |

---

## 🎉 **You're Ready!**

**Test the complete flow:**
1. Say "Salesforce"
2. Try each mode
3. Verify in Salesforce UI

**Need help?**
- Check logs for detailed error messages
- Verify API credentials
- Ensure test data exists
- Check Salesforce permissions

---

## 📝 **Changelog**

**Version 1.0 (March 2026)**
- ✅ All 6 modes implemented
- ✅ OAuth 2.0 with token refresh
- ✅ SOQL and SOSL queries
- ✅ Smart disambiguation
- ✅ Natural language parsing
- ✅ Error handling
- ✅ Production-ready

---

**Enjoy your voice-powered Salesforce CRM!** 🚀
