import json
import re
import time
from datetime import datetime, timedelta
from typing import ClassVar, Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class AsanaProjectManagerCapability(MatchingCapability):
    #{{register capability}}
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    PREFS_FILENAME: ClassVar[str] = "asana_prefs.json"
    PERSIST: ClassVar[bool] = False

    # Asana Credentials - REPLACE THESE WITH YOUR VALUES
    PERSONAL_ACCESS_TOKEN: ClassVar[str] = "xxxxx"
    WORKSPACE_GID: ClassVar[str] = "xxxx"
    
    # API Configuration
    API_BASE_URL: ClassVar[str] = "https://app.asana.com/api/1.0"
    API_VERSION: ClassVar[str] = "1.0"

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_main())

    # --- MAIN ENTRY POINT ---
    async def run_main(self):
        try:
            # Step 1: Initialize credentials
            await self.initialize_credentials()
            
            # Step 2: Say "Asana Ready"
            await self.capability_worker.speak("Asana Ready.")
            await self.worker.session_tasks.sleep(0.5)
            
            # Step 3: Loop for multiple commands
            while True:
                # Wait for user command
                command = await self.capability_worker.run_io_loop(
                    "What would you like to do?"
                )
                
                if not command:
                    await self.capability_worker.speak("No command received.")
                    continue
                
                # Check for exit
                if self.is_exit(command):
                    await self.capability_worker.speak("Goodbye.")
                    break
                
                # Step 4: Detect mode and route
                mode = await self.detect_mode(command)
                
                if mode == "my_tasks":
                    await self.my_tasks(command)
                elif mode == "create_task":
                    await self.create_task(command)
                elif mode == "search_task":
                    await self.search_task(command)
                elif mode == "update_task":
                    await self.update_task(command)
                elif mode == "project_status":
                    await self.project_status(command)
                elif mode == "add_comment":
                    await self.add_comment(command)
                else:
                    await self.capability_worker.speak(
                        "I'm not sure what you want me to do. "
                        "Try 'what's on my plate', 'create a task', "
                        "or 'how's my project'."
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Asana error: {e}"
            )
            await self.capability_worker.speak("Something went wrong.")
        finally:
            self.capability_worker.resume_normal_flow()
    
    async def initialize_credentials(self):
        """Initialize Asana credentials from preferences."""
        prefs = await self.get_preferences()
        
        # ALWAYS overwrite with class constants (force refresh)
        prefs["access_token"] = self.PERSONAL_ACCESS_TOKEN
        prefs["workspace_gid"] = self.WORKSPACE_GID
        
        await self.save_preferences(prefs)
        
        self.worker.editor_logging_handler.info(
            f"Initialized Asana credentials - Workspace: {self.WORKSPACE_GID}"
        )
    
    def is_exit(self, text: str) -> bool:
        """Check if user wants to exit."""
        exit_words = ["exit", "quit", "done", "goodbye", "bye", "stop"]
        return any(word in text.lower() for word in exit_words)

    # --- MODE DETECTION ---
    async def detect_mode(self, command: str) -> str:
        """Detect which mode based on user command."""
        cmd_lower = command.lower()
        
        # Add Comment - most specific
        if any(word in cmd_lower for word in [
            "comment on", "add a note", "add comment", "note on"
        ]):
            return "add_comment"
        
        # Create Task
        if any(word in cmd_lower for word in [
            "create task", "add task", "new task", "create a task"
        ]):
            return "create_task"
        
        # Update Task
        if any(word in cmd_lower for word in [
            "move", "update", "mark as", "change", "assign", "complete"
        ]):
            return "update_task"
        
        # Project Status
        if any(word in cmd_lower for word in [
            "how's the", "status of", "show me the", "project"
        ]):
            return "project_status"
        
        # Search Task
        if any(word in cmd_lower for word in [
            "find the", "look up", "search for"
        ]):
            return "search_task"
        
        # My Tasks - broad match (check last)
        # Match common task-related phrases
        if any(word in cmd_lower for word in [
            "my tasks", "on my plate", "what do i have",
            "what's due", "my todo", "what tasks", "what task",
            "show me", "overdue", "late", "today", "this week",
            "due task", "task do i"
        ]):
            return "my_tasks"
        
        return "unknown"

    # --- MODE 1: MY TASKS (FULLY IMPLEMENTED) ---
    async def my_tasks(self, query: str):
        """Get tasks assigned to the user with optional filtering."""
        await self.capability_worker.speak("Getting your tasks...")
        
        prefs = await self.get_preferences()
        
        # Determine filter from query
        filter_type = self.extract_task_filter(query)
        
        self.worker.editor_logging_handler.info(
            f"Fetching tasks with filter: {filter_type}"
        )
        
        # Fetch tasks
        tasks = await self.fetch_my_tasks(filter_type, prefs)
        
        if not tasks:
            await self.capability_worker.speak(
                "You don't have any tasks matching that filter."
            )
            return
        
        # Speak task summary
        await self.speak_task_summary(tasks, filter_type)
    
    def extract_task_filter(self, query: str) -> str:
        """Extract time filter from query."""
        query_lower = query.lower()
        
        self.worker.editor_logging_handler.info(
            f"Extracting filter from query: '{query_lower}'"
        )
        
        # Be very specific with filters - check for exact phrases
        if "today" in query_lower:
            return "today"
        elif "this week" in query_lower or "week" in query_lower:
            return "week"
        elif "overdue" in query_lower or " late" in query_lower or "past due" in query_lower:
            # Note: space before "late" to avoid matching "plate"
            return "overdue"
        else:
            # Default: all incomplete tasks
            return "all"
    
    async def fetch_my_tasks(
        self,
        filter_type: str,
        prefs: dict
    ) -> List[dict]:
        """Fetch tasks assigned to me with optional filtering."""
        workspace_gid = prefs.get("workspace_gid")
        
        # Build query parameters
        params = {
            "assignee": "me",
            "workspace": workspace_gid,
            "completed_since": "now",  # Only incomplete tasks
            "opt_fields": "name,due_on,due_at,completed,notes,projects.name"
        }
        
        # Fetch tasks
        result = await self.asana_request("GET", "tasks", params=params)
        
        if not result or "data" not in result:
            return []
        
        tasks = result["data"]
        
        # Apply filters
        if filter_type == "today":
            today = datetime.now().date()
            tasks = [
                t for t in tasks 
                if t.get("due_on") == today.strftime("%Y-%m-%d")
            ]
        elif filter_type == "week":
            today = datetime.now().date()
            week_end = today + timedelta(days=7)
            tasks = [
                t for t in tasks
                if t.get("due_on") and 
                datetime.strptime(t["due_on"], "%Y-%m-%d").date() <= week_end
            ]
        elif filter_type == "overdue":
            today = datetime.now().date()
            tasks = [
                t for t in tasks
                if t.get("due_on") and 
                datetime.strptime(t["due_on"], "%Y-%m-%d").date() < today
            ]
        
        self.worker.editor_logging_handler.info(
            f"Found {len(tasks)} tasks with filter '{filter_type}'"
        )
        
        return tasks
    
    async def speak_task_summary(self, tasks: List[dict], filter_type: str):
        """Speak a summary of tasks."""
        count = len(tasks)
        
        # Build opening based on filter
        if filter_type == "today":
            opening = f"You have {count} task" if count == 1 else f"You have {count} tasks"
            opening += " due today. "
        elif filter_type == "week":
            opening = f"You have {count} task" if count == 1 else f"You have {count} tasks"
            opening += " due this week. "
        elif filter_type == "overdue":
            opening = f"You have {count} overdue task. " if count == 1 else f"You have {count} overdue tasks. "
        else:
            opening = f"You have {count} task on your plate. " if count == 1 else f"You have {count} tasks on your plate. "
        
        response = opening
        
        # List first 5 tasks with due dates
        tasks_to_speak = tasks[:5]
        
        for task in tasks_to_speak:
            name = task.get("name", "Untitled task")
            due_date = task.get("due_on", "")
            
            response += f"{name}"
            
            if due_date:
                formatted_date = self.format_due_date(due_date)
                response += f" due {formatted_date}"
            
            response += ". "
        
        # If more than 5, mention the rest
        if count > 5:
            remaining = count - 5
            response += f"Plus {remaining} more."
        
        await self.capability_worker.speak(response)
    
    def format_due_date(self, date_str: str) -> str:
        """Format date for speaking."""
        if not date_str:
            return ""
        
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            today = datetime.now().date()
            
            # Check if today
            if date_obj == today:
                return "today"
            
            # Check if tomorrow
            if date_obj == today + timedelta(days=1):
                return "tomorrow"
            
            # Check if this week
            days_until = (date_obj - today).days
            if 0 < days_until <= 7:
                day_name = date_obj.strftime("%A")
                return day_name
            
            # Otherwise, format as "March 15th"
            day = date_obj.day
            month = date_obj.strftime("%B")
            
            # Add ordinal suffix
            if 10 <= day % 100 <= 20:
                suffix = "th"
            else:
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
            
            return f"{month} {day}{suffix}"
        
        except Exception:
            return date_str

    # --- MODE 2: CREATE TASK (FULLY IMPLEMENTED) ---
    async def create_task(self, command: str):
        """Create a new task with name, due date, and optional project."""
        await self.capability_worker.speak("Creating a task...")
        
        prefs = await self.get_preferences()
        
        # Parse command to extract task details
        parsed = await self.parse_create_task_command(command)
        
        if not parsed or not parsed.get("name"):
            await self.capability_worker.speak(
                "I didn't catch the task name. Try again?"
            )
            return
        
        task_name = parsed.get("name")
        due_date_text = parsed.get("due_date")
        project_name = parsed.get("project")
        assignee = parsed.get("assignee", "me")
        notes = parsed.get("notes", "")
        
        self.worker.editor_logging_handler.info(
            f"Creating task: '{task_name}' due '{due_date_text}'"
        )
        
        # Parse due date
        due_date = None
        if due_date_text:
            due_date = self.parse_due_date(due_date_text)
        
        # Find project if mentioned
        project_gid = None
        if project_name:
            project = await self.find_project_by_name(project_name, prefs)
            if project:
                project_gid = project.get("gid")
        
        # Create the task
        success = await self.create_task_api(
            task_name,
            due_date,
            project_gid,
            assignee,
            notes,
            prefs
        )
        
        if success:
            response = f"Done. I've created the task: {task_name}"
            if due_date:
                formatted_date = self.format_due_date(due_date)
                response += f", due {formatted_date}"
            if project_name:
                response += f", in the {project_name} project"
            response += "."
            
            await self.capability_worker.speak(response)
        else:
            await self.capability_worker.speak(
                "I had trouble creating the task. Please try again."
            )
    
    async def parse_create_task_command(self, command: str) -> Optional[dict]:
        """Parse create task command using LLM."""
        prompt = (
            f"Parse this task creation command: '{command}'\n"
            "Extract the task name, due date (if mentioned), project name (if mentioned), "
            "assignee (if mentioned), and any notes.\n"
            "Return ONLY valid JSON.\n\n"
            "Examples:\n"
            "Input: 'create a task: fix login bug by Friday'\n"
            'Output: {{"name": "fix login bug", "due_date": "Friday", "project": null, "assignee": "me", "notes": ""}}\n\n'
            "Input: 'add task: review mockups, assign to Sarah, due tomorrow'\n"
            'Output: {{"name": "review mockups", "due_date": "tomorrow", "project": null, "assignee": "Sarah", "notes": ""}}\n\n'
            "Input: 'new task for website project: update homepage copy by Monday'\n"
            'Output: {{"name": "update homepage copy", "due_date": "Monday", "project": "website", "assignee": "me", "notes": ""}}\n\n'
            "Input: 'create a task: call client about pricing'\n"
            'Output: {{"name": "call client about pricing", "due_date": null, "project": null, "assignee": "me", "notes": ""}}\n'
        )
        
        response = self.capability_worker.text_to_text_response(prompt).strip()
        
        # Clean markdown fences
        response = response.replace("```json", "").replace("```", "").strip()
        
        try:
            parsed = json.loads(response)
            return parsed
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Failed to parse create task command: {e}"
            )
            return None
    
    def parse_due_date(self, date_text: str) -> Optional[str]:
        """Parse natural language due date to YYYY-MM-DD format."""
        if not date_text:
            return None
        
        date_lower = date_text.lower().strip()
        today = datetime.now().date()
        
        # Today
        if date_lower in ["today"]:
            return today.strftime("%Y-%m-%d")
        
        # Tomorrow
        if date_lower in ["tomorrow"]:
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Days of week
        weekdays = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6
        }
        
        for day_name, day_num in weekdays.items():
            if day_name in date_lower:
                # Calculate days until that weekday
                current_day = today.weekday()
                days_ahead = (day_num - current_day) % 7
                
                # If it's the same day, assume next week
                if days_ahead == 0:
                    days_ahead = 7
                
                # Check if "next" is mentioned
                if "next" in date_lower:
                    days_ahead += 7
                
                target_date = today + timedelta(days=days_ahead)
                return target_date.strftime("%Y-%m-%d")
        
        # This week / next week
        if "this week" in date_lower:
            # End of this week (Sunday)
            days_until_sunday = (6 - today.weekday()) % 7
            if days_until_sunday == 0:
                days_until_sunday = 7
            return (today + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")
        
        if "next week" in date_lower:
            # Next Monday
            days_until_monday = (7 - today.weekday()) % 7 + 7
            return (today + timedelta(days=days_until_monday)).strftime("%Y-%m-%d")
        
        # Default: no due date
        return None
    
    async def find_project_by_name(
        self,
        project_name: str,
        prefs: dict
    ) -> Optional[dict]:
        """Find project by name."""
        workspace_gid = prefs.get("workspace_gid")
        
        # Get all projects
        params = {
            "workspace": workspace_gid,
            "opt_fields": "name,gid"
        }
        
        result = await self.asana_request("GET", "projects", params=params)
        
        if not result or "data" not in result:
            return None
        
        projects = result["data"]
        
        # Fuzzy match
        project_lower = project_name.lower()
        
        for project in projects:
            name = project.get("name", "").lower()
            if project_lower in name or name in project_lower:
                self.worker.editor_logging_handler.info(
                    f"Found project: {project.get('name')} ({project.get('gid')})"
                )
                return project
        
        return None
    
    async def create_task_api(
        self,
        name: str,
        due_date: Optional[str],
        project_gid: Optional[str],
        assignee: str,
        notes: str,
        prefs: dict
    ) -> bool:
        """Create task via API."""
        workspace_gid = prefs.get("workspace_gid")
        
        # Build task data
        task_data = {
            "data": {
                "name": name,
                "workspace": workspace_gid
            }
        }
        
        # Add optional fields
        if due_date:
            task_data["data"]["due_on"] = due_date
        
        if project_gid:
            task_data["data"]["projects"] = [project_gid]
        
        if assignee == "me":
            task_data["data"]["assignee"] = "me"
        
        if notes:
            task_data["data"]["notes"] = notes
        
        # Make API call
        result = await self.asana_request("POST", "tasks", data=task_data)
        
        if result and "data" in result:
            task_gid = result["data"].get("gid")
            self.worker.editor_logging_handler.info(
                f"Task created: {name} (GID: {task_gid})"
            )
            return True
        
        return False
    # --- MODE 3: SEARCH TASK (FULLY IMPLEMENTED) ---
    async def search_task(self, query: str):
        """Search for a task by name."""
        await self.capability_worker.speak("Searching for that task...")
        
        prefs = await self.get_preferences()
        
        # Extract search query from command
        search_term = await self.extract_search_term(query)
        
        if not search_term:
            await self.capability_worker.speak(
                "I didn't catch what task to search for. Try again?"
            )
            return
        
        self.worker.editor_logging_handler.info(
            f"Searching for task: '{search_term}'"
        )
        
        # Search tasks
        tasks = await self.search_tasks_by_name(search_term, prefs)
        
        if not tasks:
            await self.capability_worker.speak(
                f"I couldn't find any tasks matching {search_term}."
            )
            return
        
        # Handle results
        if len(tasks) == 1:
            # Single result - speak details
            task = tasks[0]
            await self.speak_task_details(task)
            
            # Cache for follow-up actions
            prefs["recent_task"] = task
            await self.save_preferences(prefs)
        else:
            # Multiple results - list them and ask which one
            await self.speak_multiple_tasks(tasks)
            
            # Cache for disambiguation
            prefs["recent_tasks"] = tasks
            await self.save_preferences(prefs)
    
    async def extract_search_term(self, query: str) -> Optional[str]:
        """Extract the search term from query."""
        query_lower = query.lower()
        
        # Remove common prefixes
        prefixes = [
            "find the ", "find ", "look up the ", "look up ",
            "search for the ", "search for ", "search ",
            "show me the ", "show me "
        ]
        
        search_term = query_lower
        for prefix in prefixes:
            if search_term.startswith(prefix):
                search_term = search_term[len(prefix):]
                break
        
        # Remove "task" suffix
        search_term = search_term.replace(" task", "").strip()
        
        return search_term if search_term else None
    
    async def search_tasks_by_name(
        self,
        search_term: str,
        prefs: dict
    ) -> List[dict]:
        """Search tasks by name using typeahead API."""
        workspace_gid = prefs.get("workspace_gid")
        
        # Use typeahead search
        params = {
            "resource_type": "task",
            "query": search_term,
            "count": 5
        }
        
        endpoint = f"workspaces/{workspace_gid}/typeahead"
        result = await self.asana_request("GET", endpoint, params=params)
        
        if not result or "data" not in result:
            return []
        
        # Get full task details for each result
        tasks = []
        for item in result["data"]:
            task_gid = item.get("gid")
            if task_gid:
                task = await self.get_task_details(task_gid)
                if task:
                    tasks.append(task)
        
        self.worker.editor_logging_handler.info(
            f"Found {len(tasks)} tasks matching '{search_term}'"
        )
        
        return tasks
    
    async def get_task_details(self, task_gid: str) -> Optional[dict]:
        """Get full task details by GID."""
        params = {
            "opt_fields": "name,completed,due_on,assignee.name,projects.name,notes,memberships.section.name"
        }
        
        result = await self.asana_request(
            "GET",
            f"tasks/{task_gid}",
            params=params
        )
        
        if result and "data" in result:
            return result["data"]
        
        return None
    
    async def speak_task_details(self, task: dict):
        """Speak detailed information about a task."""
        name = task.get("name", "Untitled task")
        completed = task.get("completed", False)
        due_date = task.get("due_on", "")
        assignee = task.get("assignee", {})
        projects = task.get("projects", [])
        notes = task.get("notes", "")
        
        # Start with name
        response = f"I found the {name} task. "
        
        # Status
        if completed:
            response += "It's completed. "
        else:
            # Try to get section (status)
            memberships = task.get("memberships", [])
            if memberships:
                section = memberships[0].get("section", {})
                section_name = section.get("name", "")
                if section_name and section_name.lower() not in ["untitled section", "(no section)"]:
                    response += f"It's in {section_name}. "
                else:
                    response += "It's not started. "
            else:
                response += "It's not started. "
        
        # Due date
        if due_date:
            formatted_date = self.format_due_date(due_date)
            response += f"Due {formatted_date}. "
        
        # Assignee
        if assignee:
            assignee_name = assignee.get("name", "")
            if assignee_name:
                response += f"Assigned to {assignee_name}. "
        
        # Project
        if projects:
            project_name = projects[0].get("name", "")
            if project_name:
                response += f"In the {project_name} project. "
        
        # Notes (first 50 chars)
        if notes and not completed:
            notes_preview = notes[:50]
            if len(notes) > 50:
                notes_preview += "..."
            response += f"Notes: {notes_preview}"
        
        await self.capability_worker.speak(response)
    
    async def speak_multiple_tasks(self, tasks: List[dict]):
        """Speak summary when multiple tasks found."""
        count = len(tasks)
        
        response = f"I found {count} tasks. "
        
        # List first 3
        for i, task in enumerate(tasks[:3], 1):
            name = task.get("name", "Untitled")
            due_date = task.get("due_on", "")
            
            response += f"{name}"
            
            if due_date:
                formatted_date = self.format_due_date(due_date)
                response += f" due {formatted_date}"
            
            response += ". "
        
        if count > 3:
            response += f"Plus {count - 3} more. "
        
        response += "Which one?"
        
        await self.capability_worker.speak(response)
    # --- MODE 4: UPDATE TASK (FULLY IMPLEMENTED) ---
    async def update_task(self, command: str):
        """Update a task (move section, mark complete, change due date, assign)."""
        await self.capability_worker.speak("Updating task...")
        
        prefs = await self.get_preferences()
        
        # Parse command to extract update details
        parsed = await self.parse_update_task_command(command)
        
        if not parsed:
            await self.capability_worker.speak(
                "I didn't catch what to update. Try again?"
            )
            return
        
        task_name = parsed.get("task_name")
        action = parsed.get("action")  # "move", "complete", "change_date", "assign"
        target = parsed.get("target")  # section name, date, assignee name
        
        self.worker.editor_logging_handler.info(
            f"Update action: {action}, task: {task_name}, target: {target}"
        )
        
        # Find the task
        task = None
        
        # Check if we have a cached recent task from search
        if not task_name or task_name == "it":
            cached_task = prefs.get("recent_task")
            if cached_task:
                task = cached_task
                task_name = task.get("name", "the task")
        
        # Otherwise search for it
        if not task:
            if not task_name:
                await self.capability_worker.speak(
                    "Which task do you want to update?"
                )
                return
            
            tasks = await self.search_tasks_by_name(task_name, prefs)
            
            if not tasks:
                await self.capability_worker.speak(
                    f"I couldn't find a task matching {task_name}."
                )
                return
            
            if len(tasks) > 1:
                await self.capability_worker.speak(
                    f"I found {len(tasks)} tasks. Which one do you mean?"
                )
                return
            
            task = tasks[0]
        
        task_gid = task.get("gid")
        task_display_name = task.get("name", "the task")
        
        # Handle different update actions
        if action == "move":
            await self.move_task_to_section(
                task_gid,
                task_display_name,
                target,
                prefs
            )
        elif action == "complete":
            await self.mark_task_complete(
                task_gid,
                task_display_name,
                prefs
            )
        elif action == "change_date":
            await self.change_task_due_date(
                task_gid,
                task_display_name,
                target,
                prefs
            )
        elif action == "assign":
            await self.assign_task(
                task_gid,
                task_display_name,
                target,
                prefs
            )
        else:
            await self.capability_worker.speak(
                "I'm not sure what update you want to make."
            )
    
    async def parse_update_task_command(self, command: str) -> Optional[dict]:
        """Parse update task command using LLM."""
        prompt = (
            f"Parse this task update command: '{command}'\n"
            "Determine the action (move, complete, change_date, assign) and extract "
            "the task name and target (section, date, or assignee).\n"
            "Return ONLY valid JSON.\n\n"
            "Examples:\n"
            "Input: 'move the user registration to in progress'\n"
            'Output: {{"action": "move", "task_name": "user registration", "target": "in progress"}}\n\n'
            "Input: 'mark the login bug as complete'\n"
            'Output: {{"action": "complete", "task_name": "login bug", "target": null}}\n\n'
            "Input: 'change the due date of API docs to Monday'\n"
            'Output: {{"action": "change_date", "task_name": "API docs", "target": "Monday"}}\n\n'
            "Input: 'assign the design task to Sarah'\n"
            'Output: {{"action": "assign", "task_name": "design task", "target": "Sarah"}}\n\n'
            "Input: 'move it to done'\n"
            'Output: {{"action": "move", "task_name": "it", "target": "done"}}\n\n'
            "Input: 'complete the homepage task'\n"
            'Output: {{"action": "complete", "task_name": "homepage task", "target": null}}\n'
        )
        
        response = self.capability_worker.text_to_text_response(prompt).strip()
        
        # Clean markdown fences
        response = response.replace("```json", "").replace("```", "").strip()
        
        try:
            parsed = json.loads(response)
            return parsed
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Failed to parse update task command: {e}"
            )
            return None
    
    async def move_task_to_section(
        self,
        task_gid: str,
        task_name: str,
        section_name: str,
        prefs: dict
    ):
        """Move task to a different section with confirmation."""
        if not section_name:
            await self.capability_worker.speak(
                "Which section do you want to move it to?"
            )
            return
        
        # Get task's current project and sections
        task_details = await self.get_task_details(task_gid)
        
        if not task_details:
            await self.capability_worker.speak(
                "I had trouble getting task details."
            )
            return
        
        projects = task_details.get("projects", [])
        
        if not projects:
            await self.capability_worker.speak(
                f"{task_name} is not in any project, so I can't move it to a section."
            )
            return
        
        project_gid = projects[0].get("gid")
        
        # Get sections in the project
        sections = await self.get_project_sections(project_gid)
        
        if not sections:
            await self.capability_worker.speak(
                "I couldn't find any sections in that project."
            )
            return
        
        # Match section name
        target_section = self.match_section_name(section_name, sections)
        
        if not target_section:
            section_names = ", ".join([s.get("name", "") for s in sections])
            await self.capability_worker.speak(
                f"I couldn't find a section matching {section_name}. "
                f"Available sections are: {section_names}."
            )
            return
        
        section_display_name = target_section.get("name")
        section_gid = target_section.get("gid")
        
        # CRITICAL: Confirm before moving
        await self.capability_worker.speak(
            f"I'll move {task_name} to {section_display_name}. Confirm?"
        )
        
        confirmation = await self.capability_worker.run_io_loop(
            "Say yes to confirm or no to cancel."
        )
        
        if not confirmation or not self.is_yes(confirmation):
            await self.capability_worker.speak(
                "Cancelled. The task was not moved."
            )
            return
        
        # Move the task
        success = await self.add_task_to_section(task_gid, section_gid)
        
        if success:
            await self.capability_worker.speak(
                f"Done. I've moved {task_name} to {section_display_name}."
            )
        else:
            await self.capability_worker.speak(
                "I had trouble moving the task. Please try again."
            )
    
    async def mark_task_complete(
        self,
        task_gid: str,
        task_name: str,
        prefs: dict
    ):
        """Mark task as complete with confirmation."""
        # CRITICAL: Confirm before completing
        await self.capability_worker.speak(
            f"I'll mark {task_name} as complete. Confirm?"
        )
        
        confirmation = await self.capability_worker.run_io_loop(
            "Say yes to confirm or no to cancel."
        )
        
        if not confirmation or not self.is_yes(confirmation):
            await self.capability_worker.speak(
                "Cancelled. The task was not completed."
            )
            return
        
        # Update task
        update_data = {
            "data": {
                "completed": True
            }
        }
        
        result = await self.asana_request(
            "PUT",
            f"tasks/{task_gid}",
            data=update_data
        )
        
        if result:
            await self.capability_worker.speak(
                f"Done. I've marked {task_name} as complete."
            )
        else:
            await self.capability_worker.speak(
                "I had trouble completing the task. Please try again."
            )
    
    async def change_task_due_date(
        self,
        task_gid: str,
        task_name: str,
        new_date_text: str,
        prefs: dict
    ):
        """Change task due date."""
        if not new_date_text:
            await self.capability_worker.speak(
                "What's the new due date?"
            )
            return
        
        # Parse date
        new_date = self.parse_due_date(new_date_text)
        
        if not new_date:
            await self.capability_worker.speak(
                f"I didn't understand the date {new_date_text}."
            )
            return
        
        formatted_date = self.format_due_date(new_date)
        
        # Update task
        update_data = {
            "data": {
                "due_on": new_date
            }
        }
        
        result = await self.asana_request(
            "PUT",
            f"tasks/{task_gid}",
            data=update_data
        )
        
        if result:
            await self.capability_worker.speak(
                f"Done. I've changed the due date of {task_name} to {formatted_date}."
            )
        else:
            await self.capability_worker.speak(
                "I had trouble changing the due date. Please try again."
            )
    
    async def assign_task(
        self,
        task_gid: str,
        task_name: str,
        assignee_name: str,
        prefs: dict
    ):
        """Assign task to someone."""
        await self.capability_worker.speak(
            f"Assigning tasks to other users is not yet implemented. "
            f"You can do this in the Asana app."
        )
    
    async def get_project_sections(self, project_gid: str) -> List[dict]:
        """Get all sections in a project."""
        endpoint = f"projects/{project_gid}/sections"
        
        result = await self.asana_request("GET", endpoint)
        
        if result and "data" in result:
            return result["data"]
        
        return []
    
    def match_section_name(
        self,
        target_text: str,
        sections: List[dict]
    ) -> Optional[dict]:
        """Match natural language section name to actual section."""
        target_lower = target_text.lower().strip()
        
        # Direct match
        for section in sections:
            name = section.get("name", "").lower()
            if name == target_lower:
                return section
        
        # Common aliases
        aliases = {
            "todo": "to do",
            "to-do": "to do",
            "backlog": "to do",
            "in progress": "in progress",
            "in-progress": "in progress",
            "doing": "in progress",
            "working on": "in progress",
            "done": "done",
            "complete": "done",
            "completed": "done",
            "finished": "done"
        }
        
        # Check aliases
        if target_lower in aliases:
            canonical = aliases[target_lower]
            for section in sections:
                if section.get("name", "").lower() == canonical:
                    return section
        
        # Partial match
        for section in sections:
            name = section.get("name", "").lower()
            if target_lower in name or name in target_lower:
                return section
        
        return None
    
    async def add_task_to_section(
        self,
        task_gid: str,
        section_gid: str
    ) -> bool:
        """Add task to a section."""
        endpoint = f"sections/{section_gid}/addTask"
        
        data = {
            "data": {
                "task": task_gid
            }
        }
        
        result = await self.asana_request("POST", endpoint, data=data)
        
        if result:
            self.worker.editor_logging_handler.info(
                f"Task {task_gid} moved to section {section_gid}"
            )
            return True
        
        return False
    
    def is_yes(self, text: str) -> bool:
        """Check if user said yes."""
        yes_words = [
            "yes", "yeah", "yep", "sure", "confirm", "ok", "okay",
            "yup", "correct", "right", "affirmative", "go ahead", "do it"
        ]
        return any(word in text.lower() for word in yes_words)
    # --- MODE 5: PROJECT STATUS (FULLY IMPLEMENTED) ---
    async def project_status(self, query: str):
        """Get status summary of a project (tasks by section)."""
        await self.capability_worker.speak("Getting project status...")
        
        prefs = await self.get_preferences()
        
        # Extract project name from query
        project_name = await self.extract_project_name(query)
        
        if not project_name:
            await self.capability_worker.speak(
                "Which project do you want to check?"
            )
            return
        
        self.worker.editor_logging_handler.info(
            f"Getting status for project: '{project_name}'"
        )
        
        # Find project
        project = await self.find_project_by_name(project_name, prefs)
        
        if not project:
            await self.capability_worker.speak(
                f"I couldn't find a project matching {project_name}."
            )
            return
        
        project_gid = project.get("gid")
        project_display_name = project.get("name")
        
        # Get sections in project
        sections = await self.get_project_sections(project_gid)
        
        if not sections:
            await self.capability_worker.speak(
                f"The {project_display_name} project doesn't have any sections."
            )
            return
        
        # Get tasks for each section
        section_summaries = []
        total_tasks = 0
        
        for section in sections:
            section_gid = section.get("gid")
            section_name = section.get("name")
            
            # Skip default sections
            if section_name.lower() in ["untitled section", "(no section)"]:
                continue
            
            # Get tasks in this section
            tasks = await self.get_section_tasks(section_gid)
            
            # Count incomplete tasks
            incomplete_tasks = [t for t in tasks if not t.get("completed", False)]
            count = len(incomplete_tasks)
            
            if count > 0:
                section_summaries.append({
                    "name": section_name,
                    "count": count
                })
                total_tasks += count
        
        # Speak summary
        await self.speak_project_summary(
            project_display_name,
            total_tasks,
            section_summaries
        )
    
    async def extract_project_name(self, query: str) -> Optional[str]:
        """Extract project name from query."""
        query_lower = query.lower()
        
        # Remove common prefixes
        prefixes = [
            "how's the ", "how is the ", "status of the ", "status of ",
            "show me the ", "show me ", "what's the status of the ",
            "what's the status of ", "check the ", "check "
        ]
        
        project_name = query_lower
        for prefix in prefixes:
            if project_name.startswith(prefix):
                project_name = project_name[len(prefix):]
                break
        
        # Remove "project" suffix
        project_name = project_name.replace(" project", "").strip()
        
        return project_name if project_name else None
    
    async def get_section_tasks(self, section_gid: str) -> List[dict]:
        """Get all tasks in a section."""
        params = {
            "opt_fields": "name,completed"
        }
        
        endpoint = f"sections/{section_gid}/tasks"
        result = await self.asana_request("GET", endpoint, params=params)
        
        if result and "data" in result:
            return result["data"]
        
        return []
    
    async def speak_project_summary(
        self,
        project_name: str,
        total_tasks: int,
        section_summaries: List[dict]
    ):
        """Speak project status summary."""
        if total_tasks == 0:
            await self.capability_worker.speak(
                f"The {project_name} project has no open tasks. Everything is complete!"
            )
            return
        
        # Start with overview
        if total_tasks == 1:
            response = f"Here's the {project_name} project. You have 1 open task. "
        else:
            response = f"Here's the {project_name} project. You have {total_tasks} open tasks. "
        
        # List section breakdowns (max 6 sections)
        sections_to_speak = section_summaries[:6]
        
        for section in sections_to_speak:
            name = section["name"]
            count = section["count"]
            
            if count == 1:
                response += f"1 task in {name}. "
            else:
                response += f"{count} tasks in {name}. "
        
        # If more than 6 sections, mention the rest
        if len(section_summaries) > 6:
            remaining = len(section_summaries) - 6
            response += f"Plus tasks in {remaining} more sections."
        
        await self.capability_worker.speak(response)
    # --- MODE 6: ADD COMMENT (FULLY IMPLEMENTED) ---
    async def add_comment(self, command: str):
        """Add a comment to a task."""
        await self.capability_worker.speak("Adding comment...")
        
        prefs = await self.get_preferences()
        
        # Parse command to extract task and comment
        parsed = await self.parse_comment_command(command)
        
        if not parsed:
            await self.capability_worker.speak(
                "I didn't catch the task or comment. Try again?"
            )
            return
        
        task_name = parsed.get("task_name")
        comment_text = parsed.get("comment")
        
        if not comment_text:
            await self.capability_worker.speak(
                "What comment do you want to add?"
            )
            return
        
        self.worker.editor_logging_handler.info(
            f"Adding comment to task: '{task_name}' - '{comment_text}'"
        )
        
        # Find the task
        task = None
        
        # Check if we have a cached recent task from search
        if not task_name or task_name == "it":
            cached_task = prefs.get("recent_task")
            if cached_task:
                task = cached_task
                task_name = task.get("name", "the task")
        
        # Otherwise search for it
        if not task:
            if not task_name:
                await self.capability_worker.speak(
                    "Which task do you want to comment on?"
                )
                return
            
            tasks = await self.search_tasks_by_name(task_name, prefs)
            
            if not tasks:
                await self.capability_worker.speak(
                    f"I couldn't find a task matching {task_name}."
                )
                return
            
            if len(tasks) > 1:
                await self.capability_worker.speak(
                    f"I found {len(tasks)} tasks. Which one do you mean?"
                )
                return
            
            task = tasks[0]
        
        task_gid = task.get("gid")
        task_display_name = task.get("name", "the task")
        
        # Add the comment
        success = await self.add_comment_to_task(
            task_gid,
            comment_text
        )
        
        if success:
            await self.capability_worker.speak(
                f"Done. I've added a comment to {task_display_name}."
            )
        else:
            await self.capability_worker.speak(
                "I had trouble adding the comment. Please try again."
            )
    
    async def parse_comment_command(self, command: str) -> Optional[dict]:
        """Parse comment command using LLM."""
        prompt = (
            f"Parse this comment command: '{command}'\n"
            "Extract the task name and the comment text.\n"
            "Return ONLY valid JSON.\n\n"
            "Examples:\n"
            "Input: 'comment on the API task: I've finished the auth endpoint'\n"
            '{"task_name": "API task", "comment": "I\'ve finished the auth endpoint"}\n\n'
            "Input: 'add a note to login bug: this is blocking deployment'\n"
            '{"task_name": "login bug", "comment": "this is blocking deployment"}\n\n'
            "Input: 'comment on it: approved by client'\n"
            '{"task_name": "it", "comment": "approved by client"}\n\n'
            "Input: 'note on homepage: needs review from Sarah'\n"
            '{"task_name": "homepage", "comment": "needs review from Sarah"}\n'
        )
        
        response = self.capability_worker.text_to_text_response(prompt).strip()
        
        # Clean markdown fences
        response = response.replace("```json", "").replace("```", "").strip()
        
        try:
            parsed = json.loads(response)
            return parsed
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Failed to parse comment command: {e}"
            )
            return None
    
    async def add_comment_to_task(
        self,
        task_gid: str,
        comment_text: str
    ) -> bool:
        """Add a comment (story) to a task."""
        # Add "Voice note: " prefix
        full_comment = f"Voice note: {comment_text}"
        
        data = {
            "data": {
                "text": full_comment
            }
        }
        
        endpoint = f"tasks/{task_gid}/stories"
        result = await self.asana_request("POST", endpoint, data=data)
        
        if result and "data" in result:
            story_gid = result["data"].get("gid")
            self.worker.editor_logging_handler.info(
                f"Comment added to task {task_gid}: {comment_text}"
            )
            return True
        
        return False

    # --- API HELPERS ---
    async def asana_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None
    ) -> Optional[dict]:
        """Make Asana API request."""
        prefs = await self.get_preferences()
        
        access_token = prefs.get("access_token")
        
        if not access_token:
            self.worker.editor_logging_handler.error(
                "No access token found"
            )
            return None
        
        # Build URL
        url = f"{self.API_BASE_URL}/{endpoint}"
        
        # Build headers
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        try:
            # Make request
            if method == "GET":
                response = requests.get(
                    url, headers=headers, params=params, timeout=10
                )
            elif method == "POST":
                response = requests.post(
                    url, headers=headers, json=data, params=params, timeout=10
                )
            elif method == "PUT":
                response = requests.put(
                    url, headers=headers, json=data, params=params, timeout=10
                )
            elif method == "DELETE":
                response = requests.delete(
                    url, headers=headers, params=params, timeout=10
                )
            else:
                return None
            
            # Check for errors
            if response.status_code != 200 and response.status_code != 201:
                self.worker.editor_logging_handler.error(
                    f"Asana API error: {response.status_code} - {response.text}"
                )
                return None
            
            return response.json()
            
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Asana API request error: {e}"
            )
            return None

    # --- PERSISTENCE ---
    async def get_preferences(self) -> dict:
        if await self.capability_worker.check_if_file_exists(
            self.PREFS_FILENAME, self.PERSIST
        ):
            raw = await self.capability_worker.read_file(
                self.PREFS_FILENAME, self.PERSIST
            )
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}

    async def save_preferences(self, prefs: dict):
        if await self.capability_worker.check_if_file_exists(
            self.PREFS_FILENAME, self.PERSIST
        ):
            await self.capability_worker.delete_file(
                self.PREFS_FILENAME, self.PERSIST
            )
        await self.capability_worker.write_file(
            self.PREFS_FILENAME, json.dumps(prefs, indent=2), self.PERSIST
        )
