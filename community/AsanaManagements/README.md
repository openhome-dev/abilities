https://www.loom.com/share/d45dfa37a3434cc2a17ed819afddde18
# Asana Project Manager - Complete Voice Assistant Guide

## 🎉 **Overview**

A complete voice-powered Asana integration for OpenHome that lets you manage tasks, projects, and team collaboration — all by voice.

### **Why This Ability?**

Asana is powerful for project management, but interacting with it requires clicking through menus and forms. This ability collapses complex workflows into simple voice commands:
- **"What's on my plate?"** → Instant task list with due dates
- **"Create a task: fix login bug by Friday"** → Creates task in seconds
- **"Move homepage to in progress"** → Updates status with one confirmation
- **"How's the website redesign project?"** → Full project overview

---

## ✅ **What It Can Do - All 6 Modes**

| Mode | Voice Trigger | What It Does |
|------|---------------|--------------|
| **1. My Tasks** | "What's on my plate?" | List your tasks (today, week, overdue, all) |
| **2. Create Task** | "Create a task: fix bug by Friday" | Create task with due date and project |
| **3. Search Task** | "Find the authentication task" | Search and show task details |
| **4. Update Task** | "Move user registration to in progress" | Update status, mark complete, change date |
| **5. Project Status** | "How's the website redesign project?" | Project overview by section |
| **6. Add Comment** | "Comment on API task: finished endpoint" | Add voice notes to tasks |

---

## 📋 **Table of Contents**

1. [Prerequisites](#prerequisites)
2. [Setup Guide](#setup-guide)
   - [Create Asana Account](#step-1-create-asana-account)
   - [Get Personal Access Token](#step-2-get-personal-access-token)
   - [Get Workspace GID](#step-3-get-workspace-gid)
   - [Test the API](#step-4-test-the-api)
   - [Create Test Data](#step-5-create-test-data)
3. [Installation](#installation)
4. [All 6 Modes - Complete Guide](#all-6-modes---complete-guide)
5. [Usage Examples](#usage-examples)
6. [Technical Details](#technical-details)
7. [Troubleshooting](#troubleshooting)
8. [API Reference](#api-reference)

---

## 📦 **Prerequisites**

### **What You Need:**
- ✅ Asana account (Free tier works perfectly!)
- ✅ PowerShell (for setup and testing)
- ✅ 15 minutes for initial setup

---

## 🔧 **Setup Guide**

### **Step 1: Create Asana Account**

If you don't have Asana:

1. Go to: https://asana.com/create-account
2. Sign up with email (free tier is fine)
3. Choose "Personal use" or "Work"
4. Complete the onboarding wizard
5. You'll be in your workspace!

**Your workspace URL will be:** `https://app.asana.com/0/home/1234567890`

---

### **Step 2: Get Personal Access Token**

This is your API key for authentication.

#### **2.1 Navigate to Developer Console**

1. Log in to Asana: https://app.asana.com
2. Click your **profile picture** (top right)
3. Click **"My Settings"**
4. Click **"Apps"** tab (left sidebar)
5. Scroll to the bottom
6. Click **"View developer console"** or **"Manage developer apps"**

Or go directly to: https://app.asana.com/0/my-apps

#### **2.2 Create Personal Access Token**

1. In the Developer Console, click on **"Personal access tokens"** tab
2. Click **"+ New access token"** button
3. Fill in:
   - **Token name:** `OpenHome Voice Assistant`
   - **Description:** (optional) `Voice control for Asana tasks`
4. Click **"Create token"**

#### **2.3 Copy Token**

⚠️ **CRITICAL:** You'll only see this token **ONCE**!

**Copy the entire token** - it looks like:
```
2/1213653512250486/1213654526340256:29a2d1a41b536ed209b9519712d65e90
```

**Save it somewhere safe!** (You'll need it in Step 6)

---

### **Step 3: Get Workspace GID**

We need your workspace ID for API calls.

#### **Method 1: Via PowerShell (Recommended)**

Open PowerShell and run (replace `YOUR_TOKEN`):

```powershell
$token = "YOUR_TOKEN_HERE"
$headers = @{
    "Authorization" = "Bearer $token"
}

$response = Invoke-RestMethod -Uri "https://app.asana.com/api/1.0/workspaces" -Headers $headers

$response.data | ForEach-Object {
    Write-Host "Workspace: $($_.name)"
    Write-Host "GID: $($_.gid)"
    Write-Host ""
}
```

**Expected Output:**
```
Workspace: My workspace
GID: 1213653512250498
```

**Save the GID!**

#### **Method 2: Via Browser (Alternative)**

1. Go to any Asana project
2. Look at the URL: `https://app.asana.com/0/1234567890123456/...`
3. The number after `/0/` is often your workspace GID

---

### **Step 4: Test the API**

Let's verify everything works!

#### **Test 1: Get Your User Info**

```powershell
$token = "YOUR_TOKEN"
$headers = @{"Authorization" = "Bearer $token"}

$user = Invoke-RestMethod -Uri "https://app.asana.com/api/1.0/users/me" -Headers $headers

Write-Host "✅ Connected as: $($user.data.name)"
Write-Host "Email: $($user.data.email)"
Write-Host "User GID: $($user.data.gid)"
```

**Expected Output:**
```
✅ Connected as: Your Name
Email: your@email.com
User GID: 1213654526340256
```

#### **Test 2: Get Your Tasks**

Replace `WORKSPACE_GID` with your workspace GID from Step 3:

```powershell
$token = "YOUR_TOKEN"
$workspaceGid = "YOUR_WORKSPACE_GID"
$headers = @{"Authorization" = "Bearer $token"}

$uri = "https://app.asana.com/api/1.0/tasks?assignee=me&workspace=$workspaceGid&completed_since=now&opt_fields=name,due_on"

$tasks = Invoke-RestMethod -Uri $uri -Headers $headers

Write-Host "✅ You have $($tasks.data.Count) tasks"
Write-Host ""

foreach ($task in $tasks.data) {
    Write-Host "- $($task.name) (Due: $($task.due_on))"
}
```

**Expected Output:**
```
✅ You have 3 tasks

- Fix login bug (Due: 2026-03-21)
- Review design mockups (Due: 2026-03-18)
- Update documentation (Due: )
```

✅ If you see your tasks, **API is working!**

---

### **Step 5: Create Test Data**

If you don't have tasks, let's create some test data for trying out the ability.

#### **5.1 Create Test Project**

```powershell
$token = "YOUR_TOKEN"
$workspaceGid = "YOUR_WORKSPACE_GID"
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

# Create project
$project = @{
    data = @{
        name = "Voice Assistant Testing"
        workspace = $workspaceGid
    }
} | ConvertTo-Json -Depth 3

$newProject = Invoke-RestMethod -Uri "https://app.asana.com/api/1.0/projects" -Method POST -Headers $headers -Body $project

$projectGid = $newProject.data.gid
Write-Host "✅ Created project: Voice Assistant Testing"
Write-Host "Project GID: $projectGid"
```

#### **5.2 Create Sections**

```powershell
$token = "YOUR_TOKEN"
$projectGid = "PROJECT_GID_FROM_ABOVE"
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

$sectionNames = @("To Do", "In Progress", "Review", "Done")

foreach ($sectionName in $sectionNames) {
    $section = @{
        data = @{
            name = $sectionName
        }
    } | ConvertTo-Json -Depth 3
    
    Invoke-RestMethod -Uri "https://app.asana.com/api/1.0/projects/$projectGid/sections" -Method POST -Headers $headers -Body $section
    Write-Host "✅ Created section: $sectionName"
}
```

#### **5.3 Create Test Tasks**

```powershell
$token = "YOUR_TOKEN"
$workspaceGid = "YOUR_WORKSPACE_GID"
$projectGid = "YOUR_PROJECT_GID"
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

# Task 1: Due today
$today = (Get-Date).ToString("yyyy-MM-dd")
$task1 = @{
    data = @{
        name = "Fix login bug"
        workspace = $workspaceGid
        projects = @($projectGid)
        due_on = $today
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Uri "https://app.asana.com/api/1.0/tasks" -Method POST -Headers $headers -Body $task1
Write-Host "✅ Created: Fix login bug (due today)"

# Task 2: Due tomorrow
$tomorrow = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
$task2 = @{
    data = @{
        name = "Review design mockups"
        workspace = $workspaceGid
        projects = @($projectGid)
        due_on = $tomorrow
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Uri "https://app.asana.com/api/1.0/tasks" -Method POST -Headers $headers -Body $task2
Write-Host "✅ Created: Review design mockups (due tomorrow)"

# Task 3: Due Friday
$friday = (Get-Date).AddDays((5 - (Get-Date).DayOfWeek.value__) % 7).ToString("yyyy-MM-dd")
$task3 = @{
    data = @{
        name = "Update API documentation"
        workspace = $workspaceGid
        projects = @($projectGid)
        due_on = $friday
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Uri "https://app.asana.com/api/1.0/tasks" -Method POST -Headers $headers -Body $task3
Write-Host "✅ Created: Update API documentation (due Friday)"

Write-Host ""
Write-Host "All test data created! You're ready to go!"
```

---

## 📥 **Installation**

### **Step 1: Update Credentials in Code**

Open `asana_main.py` and update lines 14-15:

```python
# CHANGE FROM:
PERSONAL_ACCESS_TOKEN: ClassVar[str] = ""
WORKSPACE_GID: ClassVar[str] = ""

# TO (use YOUR values):
PERSONAL_ACCESS_TOKEN: ClassVar[str] = "2/1213653512250486/1213654526340256:29a2d1a41b536ed209b9519712d65e90"
WORKSPACE_GID: ClassVar[str] = "1213653512250498"
```

### **Step 2: Copy Files to OpenHome**

Copy these files to your OpenHome abilities folder:
- `asana_main.py`
- `asana_config.json`
- `asana__init__.py`

### **Step 3: Restart OpenHome**

Restart the OpenHome service/application.

### **Step 4: Test**

Say: **"Asana"**

You should hear: **"Asana Ready. What would you like to do?"**

✅ If you hear that, installation is successful!

---

## 🎯 **All 6 Modes - Complete Guide**

---

### **Mode 1: My Tasks**

**What It Does:**
- Get tasks assigned to you
- Filter by: today, this week, overdue, or all
- Speaks task names with due dates

**Voice Triggers:**
- "What's on my plate?"
- "What tasks do I have today?"
- "What's due this week?"
- "Show me my overdue tasks"

**How It Works:**

**API Call:**
```
GET /tasks?assignee=me&workspace={workspace_gid}&completed_since=now
```

**Filter Logic:**

| User Says | Filter Applied |
|-----------|----------------|
| "today" / "due today" | Tasks due today only |
| "this week" / "due this week" | Tasks due within 7 days |
| "overdue" / "late" | Past due date |
| (anything else) | All incomplete tasks |

**Response Pattern:**
```
"You have 5 tasks on your plate. Fix login bug due today. 
Review design mockups due tomorrow. Update documentation due Friday. 
API integration due next Monday. Plus 1 more."
```

**Test Commands:**
```
User: "Asana"
App: "Asana Ready. What would you like to do?"

User: "What's on my plate?"
App: "You have 5 tasks on your plate. Fix login bug due today..."

User: "What's due today?"
App: "You have 2 tasks due today. Fix login bug. Deploy staging."

User: "Show me overdue tasks"
App: "You have 1 overdue task. Update client presentation."
```

---

### **Mode 2: Create Task**

**What It Does:**
- Create task with name, due date, and optional project
- LLM parses natural language
- Smart date parsing

**Voice Triggers:**
- "Create a task: fix login bug by Friday"
- "Add task: review design mockups"
- "New task for website project: update homepage by Monday"

**How It Works:**

**LLM Parsing:**
```
Input: "create a task: fix login bug by Friday"
Output: {
  "name": "fix login bug",
  "due_date": "Friday",
  "project": null
}
```

**Date Parsing:**

| User Says | Parsed To |
|-----------|-----------|
| "today" | Today's date |
| "tomorrow" | Tomorrow |
| "Friday" | This Friday (or next if today is Friday) |
| "next Monday" | Monday of next week |
| "this week" | This Sunday |
| (no date) | No due date |

**API Call:**
```json
POST /tasks
{
  "data": {
    "name": "fix login bug",
    "workspace": "{workspace_gid}",
    "due_on": "2026-03-21",
    "assignee": "me"
  }
}
```

**Response Pattern:**
```
"Done. I've created the task: fix login bug, due Friday."
```

**Test Commands:**
```
User: "Create a task: fix login bug by Friday"
App: "Creating a task..."
App: "Done. I've created the task: fix login bug, due Friday."

User: "Add task: call client about pricing"
App: "Done. I've created the task: call client about pricing."

User: "New task for website project: update homepage by Monday"
App: "Done. I've created the task: update homepage, due Monday, in the website project."
```

---

### **Mode 3: Search Task**

**What It Does:**
- Search tasks by name using Asana's typeahead API
- Show detailed task information
- Handle single/multiple results
- Cache results for follow-up

**Voice Triggers:**
- "Find the authentication task"
- "Look up the homepage redesign"
- "Search for API documentation"

**How It Works:**

**Search Flow:**
```
1. Extract search term: "find the authentication task" → "authentication"
2. API: GET /workspaces/{gid}/typeahead?resource_type=task&query=authentication
3. Get full details: GET /tasks/{task_gid}
4. Speak results
```

**Response Patterns:**

**Single Result:**
```
"I found the fix login bug task. It's in To Do. Due Friday. 
Assigned to you. In the Website Redesign project."
```

**Multiple Results:**
```
"I found 3 tasks. API documentation due Monday. API integration due Friday. 
API testing. Which one?"
```

**No Results:**
```
"I couldn't find any tasks matching quantum physics."
```

**Task Details Spoken:**

| Field | Example |
|-------|---------|
| Name | "I found the fix login bug task." |
| Status | "It's in To Do." / "It's completed." |
| Due Date | "Due Friday." |
| Assignee | "Assigned to you." |
| Project | "In the Website Redesign project." |

**Test Commands:**
```
User: "Find the login bug"
App: "Searching for that task..."
App: "I found the fix login bug task. It's in To Do. Due Friday..."

User: "Look up documentation"
App: "I found the update documentation task. It's not started. Due Wednesday."

User: "Search for homepage"
App: "I found the update homepage copy task. It's in In Progress..."
```

---

### **Mode 4: Update Task**

**What It Does:**
- Move task between sections (To Do → In Progress → Done)
- Mark task as complete
- Change due date
- **Requires confirmation for destructive actions**

**Voice Triggers:**

**Move:**
- "Move the user registration to in progress"
- "Move homepage to done"

**Complete:**
- "Mark the login bug as complete"
- "Complete the homepage task"

**Change Date:**
- "Change the due date of API docs to Monday"

**How It Works:**

**1. Move to Section:**

**API Calls:**
```
GET /tasks/{task_gid}  (get task details)
GET /projects/{project_gid}/sections  (get sections)
POST /sections/{section_gid}/addTask  (move task)
```

**Section Aliases:**

| User Says | Matches To |
|-----------|-----------|
| "todo" / "to-do" / "backlog" | To Do |
| "in progress" / "doing" / "working on" | In Progress |
| "done" / "complete" / "finished" | Done |

**Confirmation:**
```
App: "I'll move user registration to In Progress. Confirm?"
User: "Yes"
App: "Done. I've moved user registration to In Progress."
```

**2. Mark Complete:**

**API Call:**
```json
PUT /tasks/{task_gid}
{
  "data": {
    "completed": true
  }
}
```

**3. Change Due Date:**

**API Call:**
```json
PUT /tasks/{task_gid}
{
  "data": {
    "due_on": "2026-03-17"
  }
}
```

**Using Cached Tasks:**
```
User: "Find the login bug"
App: "I found the fix login bug task..."

User: "Move it to in progress"
App: "I'll move fix login bug to In Progress. Confirm?"
```

**Test Commands:**
```
User: "Move the homepage task to in progress"
App: "Updating task..."
App: "I'll move update homepage copy to In Progress. Confirm?"
User: "Yes"
App: "Done. I've moved update homepage copy to In Progress."

User: "Mark the login bug as complete"
App: "I'll mark fix login bug as complete. Confirm?"
User: "Yes"
App: "Done. I've marked fix login bug as complete."

User: "Change the API docs due date to Friday"
App: "Done. I've changed the due date of API documentation to Friday."
```

---

### **Mode 5: Project Status**

**What It Does:**
- Get project overview with task counts
- Breakdown by section
- Only counts incomplete tasks
- Speaks top 6 sections

**Voice Triggers:**
- "How's the website redesign project?"
- "What's the status of the mobile app?"
- "Show me the test project"

**How It Works:**

**API Flow:**
```
1. Find project: GET /projects?workspace={gid}
2. Get sections: GET /projects/{project_gid}/sections
3. Get tasks per section: GET /sections/{section_gid}/tasks
4. Count incomplete tasks
5. Speak summary
```

**Response Patterns:**

**Project with Tasks:**
```
"Here's the Website Redesign project. You have 8 open tasks. 
3 tasks in To Do. 4 tasks in In Progress. 1 task in Review."
```

**Empty Project:**
```
"The Website Redesign project has no open tasks. Everything is complete!"
```

**Single Task:**
```
"Here's the Mobile App project. You have 1 open task. 1 task in To Do."
```

**Test Commands:**
```
User: "How's the website redesign project?"
App: "Getting project status..."
App: "Here's the Website Redesign project. You have 8 tasks. 
      3 in To Do. 4 in In Progress. 1 in Review."

User: "Check the voice assistant testing"
App: "Here's the Voice Assistant Testing project. You have 3 tasks. 
      2 in To Do. 1 in In Progress."
```

---

### **Mode 6: Add Comment**

**What It Does:**
- Add comment/note to any task
- Uses cached task from search
- Adds "Voice note:" prefix
- No confirmation needed (quick note)

**Voice Triggers:**
- "Comment on the API task: I've finished the auth endpoint"
- "Add a note to login bug: this is blocking deployment"
- "Note on homepage: Sarah approved the design"

**How It Works:**

**LLM Parsing:**
```
Input: "comment on the API task: I've finished the auth endpoint"
Output: {
  "task_name": "API task",
  "comment": "I've finished the auth endpoint"
}
```

**API Call:**
```json
POST /tasks/{task_gid}/stories
{
  "data": {
    "text": "Voice note: I've finished the auth endpoint"
  }
}
```

**In Asana:**
```
You: Voice note: I've finished the auth endpoint
Just now
```

**Using Cached Tasks:**
```
User: "Find the API task"
App: "I found the API integration task..."

User: "Comment on it: finished the authentication endpoint"
App: "Done. I've added a comment to API integration."
```

**Test Commands:**
```
User: "Comment on the login bug: fixed and ready for review"
App: "Adding comment..."
App: "Done. I've added a comment to fix login bug."

User: "Find the homepage task"
App: "I found the update homepage task..."

User: "Add a note to it: client approved the design"
App: "Done. I've added a comment to update homepage."
```

---

## 🎯 **Usage Examples**

### **Complete Session Flow:**

```
User: "Asana"
App: "Asana Ready. What would you like to do?"

User: "What's on my plate?"
App: "You have 5 tasks on your plate. Fix login bug due today. 
      Review design mockups due tomorrow. Update documentation due Friday..." ✅ Mode 1

User: "Create a task: call client about pricing by Monday"
App: "Creating a task..."
App: "Done. I've created the task: call client about pricing, due Monday." ✅ Mode 2

User: "Find the API task"
App: "Searching for that task..."
App: "I found the API integration task. It's in To Do. Due next week..." ✅ Mode 3

User: "Move it to in progress"
App: "Updating task..."
App: "I'll move API integration to In Progress. Confirm?"
User: "Yes"
App: "Done. I've moved API integration to In Progress." ✅ Mode 4

User: "How's the website redesign project?"
App: "Getting project status..."
App: "Here's the Website Redesign project. You have 8 open tasks. 
      3 in To Do. 4 in In Progress. 1 in Review." ✅ Mode 5

User: "Comment on the API task: finished the authentication endpoint"
App: "Adding comment..."
App: "Done. I've added a comment to API integration." ✅ Mode 6

User: "Done"
App: "Goodbye."
```

---

## 🔧 **Technical Details**

### **Architecture**

**Authentication:**
- Personal Access Token (Bearer token)
- No expiration (unless manually revoked)
- Passed in Authorization header

**API Request Pattern:**
```python
async def asana_request(method, endpoint, data=None, params=None):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    # Make request
    # Handle errors
    # Return result
```

### **Key Endpoints Used**

**Tasks:**
```
GET  /tasks?assignee=me&workspace={gid}  # My tasks
POST /tasks                               # Create task
PUT  /tasks/{task_gid}                    # Update task
GET  /tasks/{task_gid}                    # Get task details
```

**Search:**
```
GET /workspaces/{gid}/typeahead?resource_type=task&query={term}
```

**Projects:**
```
GET /projects?workspace={gid}             # Get projects
GET /projects/{project_gid}/sections      # Get sections
GET /sections/{section_gid}/tasks         # Get tasks in section
POST /sections/{section_gid}/addTask      # Move task to section
```

**Comments:**
```
POST /tasks/{task_gid}/stories            # Add comment
```

### **Date Parsing Logic**

```python
def parse_due_date(text):
    if "today" in text:
        return datetime.now().strftime("%Y-%m-%d")
    elif "tomorrow" in text:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "friday" in text:
        # Calculate days until Friday
        days_ahead = (4 - datetime.now().weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7  # Next Friday
        return (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    # ... more patterns
```

### **Date Formatting for Speech**

```python
def format_due_date(date_str):
    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    today = datetime.now().date()
    
    if date_obj == today:
        return "today"
    elif date_obj == today + timedelta(days=1):
        return "tomorrow"
    elif (date_obj - today).days <= 7:
        return date_obj.strftime("%A")  # "Friday"
    else:
        return f"{date_obj.strftime('%B')} {date_obj.day}{ordinal_suffix}"
        # "March 15th"
```

### **LLM Parsing**

Used for extracting intent from natural language:
- Create task command → name, due date, project
- Update task command → action, task name, target
- Comment command → task name, comment text

**Example:**
```python
prompt = "Parse: 'create a task: fix login bug by Friday'"
response = LLM(prompt)
# {"name": "fix login bug", "due_date": "Friday"}
```

---

## 🐛 **Troubleshooting**

### **"401 Unauthorized" Error**

**Cause:** Invalid or expired access token  
**Fix:** 
1. Go to Asana → My Settings → Apps → Personal access tokens
2. Revoke old token
3. Create new token
4. Update `PERSONAL_ACCESS_TOKEN` in `asana_main.py`

### **"404 Not Found - workspace: Not a recognized ID"**

**Cause:** Wrong workspace GID  
**Fix:**
1. Verify your workspace GID:
```powershell
$token = "YOUR_TOKEN"
$headers = @{"Authorization" = "Bearer $token"}
Invoke-RestMethod -Uri "https://app.asana.com/api/1.0/workspaces" -Headers $headers
```
2. Update `WORKSPACE_GID` in `asana_main.py`

### **"I couldn't find any tasks"**

**Cause:** No tasks in workspace  
**Fix:** Create test data (see Step 5 in Setup)

### **Mode Detection Not Working**

**Cause:** Trigger words not matching  
**Fix:** Check `asana_config.json` and ensure trigger words are present

### **Section Not Found When Moving Tasks**

**Cause:** Task not in a project with sections  
**Fix:** 
1. Assign task to a project first
2. Ensure project has sections (To Do, In Progress, Done)

### **Comment Not Appearing**

**Cause:** Looking at wrong task  
**Fix:** 
1. Check task in Asana
2. Scroll down to activity/comments section
3. Look for "Voice note: ..." comment

---

## 📚 **API Reference**

### **Asana REST API v1.0**

**Base URL:** `https://app.asana.com/api/1.0/`

**Authentication:**
```
Authorization: Bearer {personal_access_token}
```

### **Core Objects**

#### **Workspace**
- Top-level container
- Required for most API calls
- Get via: `GET /workspaces`

#### **Task**
```json
{
  "gid": "1213654925686160",
  "name": "Fix login bug",
  "completed": false,
  "due_on": "2026-03-21",
  "assignee": {
    "gid": "1213654526340256",
    "name": "Your Name"
  },
  "projects": [
    {
      "gid": "1213654123456789",
      "name": "Website Redesign"
    }
  ]
}
```

#### **Project**
- Collection of tasks
- Has sections (columns)
- Example: "Website Redesign", "Q2 Planning"

#### **Section**
- Columns in a project
- Example: "To Do", "In Progress", "Done"

#### **Story (Comment)**
- Comments on tasks
- Activity log

### **Rate Limits**

**Free Tier:**
- 150 requests per minute
- 1,500 requests per hour

**Premium:**
- Higher limits

**Best Practices:**
- Cache results when possible
- Use typeahead search (faster)
- Batch related operations

---

## 🔐 **Security Notes**

### **Production Best Practices:**

1. **Never commit tokens to git**
   ```bash
   # Add to .gitignore
   *_prefs.json
   asana_main.py  # If it contains tokens
   ```

2. **Use environment variables**
   ```python
   import os
   PERSONAL_ACCESS_TOKEN = os.getenv("ASANA_TOKEN")
   WORKSPACE_GID = os.getenv("ASANA_WORKSPACE")
   ```

3. **Rotate tokens regularly**
   - Revoke old tokens
   - Create new ones every 90 days

4. **Minimum permissions**
   - Personal Access Tokens have full access to your account
   - Consider OAuth 2.0 for production (future enhancement)

---

## 📊 **Statistics**

**Implementation:**
- **~1,600 lines of code**
- **6 complete modes**
- **Personal Access Token authentication**
- **Natural language parsing**
- **Smart date parsing**
- **Section matching**
- **Task caching**
- **Error handling**

**API Calls per Mode:**

| Mode | API Calls |
|------|-----------|
| My Tasks | 1 |
| Create Task | 1-2 (project lookup optional) |
| Search Task | 2-6 (typeahead + details) |
| Update Task | 2-4 (find + update) |
| Project Status | 2-10 (project + sections + tasks) |
| Add Comment | 1-2 (find task + add comment) |

---

## 🎯 **Quick Reference Card**

### **Voice Commands Cheat Sheet:**

```
🔍 VIEW TASKS
"What's on my plate?"
"What's due today?"
"Show me overdue tasks"

➕ CREATE
"Create a task: [name] by [date]"
"Add task: [name]"

🔎 SEARCH
"Find the [task name]"
"Look up [task name]"

✏️ UPDATE
"Move [task] to [section]"
"Mark [task] as complete"
"Change [task] due date to [date]"

📊 PROJECT STATUS
"How's the [project name] project?"
"What's the status of [project]?"

💬 COMMENT
"Comment on [task]: [message]"
"Add a note to [task]: [message]"

❌ EXIT
"Done" or "Exit" or "Goodbye"
```

---

## 🎉 **You're Ready!**

**Test the complete flow:**
1. Say "Asana"
2. Try each mode
3. Verify in Asana web app

**Need help?**
- Check logs for detailed error messages
- Verify API credentials
- Ensure test data exists

---

## 📝 **Changelog**

**Version 1.0 (March 2026)**
- ✅ All 6 modes implemented
- ✅ Personal Access Token authentication
- ✅ Natural language date parsing
- ✅ Smart section matching
- ✅ Task caching for follow-ups
- ✅ Confirmation for destructive actions
- ✅ Production-ready

---

**Enjoy your voice-powered Asana project manager!** 🚀
