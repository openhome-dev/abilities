import json
import time
from datetime import datetime, timedelta
from typing import ClassVar, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class SalesforceCRMCapability(MatchingCapability):
    # {{register capability}}
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    PREFS_FILENAME: ClassVar[str] = "salesforce_crm_prefs.json"
    PERSIST: ClassVar[bool] = False

    # OAuth Credentials - REPLACE THESE WITH YOUR VALUES
    CONSUMER_KEY: ClassVar[str] = "xxxx"
    CONSUMER_SECRET: ClassVar[str] = "xxxxx"
    INSTANCE_URL: ClassVar[str] = "https://orgfarm-e79624af49-dev-ed.develop.my.salesforce.com"
    INITIAL_ACCESS_TOKEN: ClassVar[str] = "xxx"
    INITIAL_REFRESH_TOKEN: ClassVar[str] = "xxxx"

    # OAuth endpoints
    AUTH_URL: ClassVar[str] = "https://login.salesforce.com/services/oauth2/authorize"
    TOKEN_URL: ClassVar[str] = "https://login.salesforce.com/services/oauth2/token"

    # API version
    API_VERSION: ClassVar[str] = "v62.0"

    # Token expiry (2 hours in seconds)
    TOKEN_EXPIRY_SECONDS: ClassVar[int] = 7200

    # Cache refresh interval (30 minutes)
    CACHE_REFRESH_MINUTES: ClassVar[int] = 30

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_main())

    # --- MAIN ENTRY POINT ---
    async def run_main(self):
        try:
            # Step 1: Say "Salesforce Ready"
            await self.capability_worker.speak("Salesforce Ready.")
            await self.worker.session_tasks.sleep(0.5)

            # Step 2: Ensure authenticated
            if not await self.ensure_authenticated():
                await self.capability_worker.speak(
                    "I couldn't connect to Salesforce. "
                    "Please check your setup and try again."
                )
                return

            # Cache opportunity stages
            await self.cache_opportunity_stages()

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

                if mode == "disambiguate":
                    await self.handle_disambiguation(command)
                elif mode == "search_contact":
                    await self.search_contacts(command)
                elif mode == "search_opportunity":
                    await self.search_opportunities(command)
                elif mode == "log_note":
                    await self.log_note(command)
                elif mode == "create_task":
                    await self.create_task(command)
                elif mode == "pipeline_summary":
                    await self.pipeline_summary()
                elif mode == "move_stage":
                    await self.move_opportunity_stage(command)
                else:
                    await self.capability_worker.speak(
                        "I'm not sure what you want me to do. "
                        "Try 'look up a contact', 'check an opportunity', "
                        "'log a note', 'create a task', or 'show my pipeline'."
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Salesforce CRM error: {e}"
            )
            await self.capability_worker.speak("Something went wrong.")
        finally:
            self.capability_worker.resume_normal_flow()

    def is_exit(self, text: str) -> bool:
        """Check if user wants to exit."""
        exit_words = ["exit", "quit", "done", "goodbye", "bye", "stop"]
        return any(word in text.lower() for word in exit_words)

    # --- MODE DETECTION ---
    async def detect_mode(self, command: str) -> str:
        """Detect which mode based on user command."""
        cmd_lower = command.lower()

        # Check for disambiguation first (follow-up to multiple results)
        if self.is_disambiguation(cmd_lower):
            return "disambiguate"

        # Log Note - check FIRST (most specific)
        if any(word in cmd_lower for word in [
            "log note", "add note", "note on", "note for"
        ]):
            return "log_note"

        # Create Task
        if any(word in cmd_lower for word in [
            "create task", "create a task", "add task", "add a task",
            "remind me", "task for", "new task", "follow up with"
        ]):
            return "create_task"

        # Pipeline Summary - check for various patterns
        if any(word in cmd_lower for word in [
            "pipeline", "my pipeline", "open opportunities", "open opps",
            "what opportunities do i have", "show my opportunities",
            "how many opportunities", "what deals do i have"
        ]):
            return "pipeline_summary"

        # Move Stage - check BEFORE search
        if any(word in cmd_lower for word in [
            "move", "update opp", "update opportunity", "change stage",
            "mark as", "closed won", "closed lost"
        ]):
            return "move_stage"

        # Search Opportunity
        if any(word in cmd_lower for word in [
            "opportunity", "opp", "deal", "how's the", "how is the",
            "what's the status", "check the"
        ]):
            return "search_opportunity"

        # Search Contact - broad match (check LAST)
        if any(word in cmd_lower for word in [
            "look up", "find contact", "who is", "search contact",
            "find", "search"
        ]):
            return "search_contact"

        return "unknown"

    def is_disambiguation(self, text: str) -> bool:
        """Check if user is selecting from multiple results."""
        disambiguation_patterns = [
            "first one", "the first", "first", "1", "number one", "number 1",
            "second one", "the second", "second", "2", "number two", "number 2",
            "third one", "the third", "third", "3", "number three", "number 3",
            "fourth one", "the fourth", "fourth", "4", "number four", "number 4",
            "fifth one", "the fifth", "fifth", "5", "number five", "number 5"
        ]
        return any(pattern in text for pattern in disambiguation_patterns)

    # --- MODE 1: SEARCH CONTACTS (FULLY IMPLEMENTED) ---
    async def search_contacts(self, query: str):
        """Search for contacts by name or email using SOQL/SOSL."""
        await self.capability_worker.speak("Searching for contacts...")

        # Load preferences
        prefs = await self.get_preferences()

        if not prefs.get("access_token") or not prefs.get("instance_url"):
            await self.capability_worker.speak(
                "Salesforce not connected. Please set up OAuth first."
            )
            return

        # Extract search term from query using LLM
        search_term = await self.extract_search_term(query)

        if not search_term:
            await self.capability_worker.speak(
                "I didn't catch who you're looking for. Try again?"
            )
            return

        self.worker.editor_logging_handler.info(
            f"Searching for contact: {search_term}"
        )

        # Determine search strategy
        if "@" in search_term:
            # Email search - use SOQL exact match
            contacts = await self.search_contacts_by_email(
                search_term, prefs
            )
        else:
            # Name search - use SOSL for fuzzy matching
            contacts = await self.search_contacts_by_name(
                search_term, prefs
            )

        if not contacts:
            await self.capability_worker.speak(
                f"I couldn't find any contacts matching {search_term}. "
                "Want me to search accounts instead?"
            )
            return

        if len(contacts) == 1:
            # Single result - speak full details
            await self.speak_contact_details(contacts[0])
        else:
            # Multiple results - list them and ask which one
            await self.speak_multiple_contacts(contacts)

        # Cache results for follow-up
        await self.cache_recent_result("contact", contacts, prefs)

    async def handle_disambiguation(self, command: str):
        """Handle user selecting from multiple results."""
        prefs = await self.get_preferences()
        recent = prefs.get("recent_results", {})

        if not recent or not recent.get("items"):
            await self.capability_worker.speak(
                "I don't have any recent results to choose from. "
                "Try searching for something first."
            )
            return

        # Extract which number they want
        selection = self.parse_selection(command)

        if selection is None:
            await self.capability_worker.speak(
                "I didn't catch which one you want. Try 'the first one' or 'number two'."
            )
            return

        items = recent.get("items", [])

        # Check if selection is valid
        if selection < 1 or selection > len(items):
            await self.capability_worker.speak(
                f"I only have {len(items)} results. Try a number between 1 and {len(items)}."
            )
            return

        # Get the selected item (convert to 0-indexed)
        selected_item = items[selection - 1]
        result_type = recent.get("type")

        # Show full details based on type
        if result_type == "contact":
            await self.speak_contact_details(selected_item)
        elif result_type == "opportunity":
            await self.speak_opportunity_details(selected_item)
        else:
            await self.capability_worker.speak(
                "I'm not sure what type of result that was."
            )

    def parse_selection(self, command: str) -> Optional[int]:
        """Parse which item user selected from command."""
        cmd_lower = command.lower()

        # Number mapping
        number_words = {
            "first": 1, "1": 1, "one": 1, "number one": 1, "number 1": 1,
            "second": 2, "2": 2, "two": 2, "number two": 2, "number 2": 2,
            "third": 3, "3": 3, "three": 3, "number three": 3, "number 3": 3,
            "fourth": 4, "4": 4, "four": 4, "number four": 4, "number 4": 4,
            "fifth": 5, "5": 5, "five": 5, "number five": 5, "number 5": 5
        }

        for word, number in number_words.items():
            if word in cmd_lower:
                return number

        return None

    async def extract_search_term(self, query: str) -> str:
        """Extract the name or email from the query using LLM."""
        prompt = (
            f"Extract the person's name or email from this query: '{query}'\n"
            "Return ONLY the name or email, nothing else.\n"
            "Examples:\n"
            "Query: 'look up Sarah Chen' → Sarah Chen\n"
            "Query: 'find john@acme.com' → john@acme.com\n"
            "Query: 'who is the CFO at Acme' → CFO Acme\n"
        )

        response = self.capability_worker.text_to_text_response(prompt).strip()

        # Clean up response
        response = response.replace('"', '').replace("'", '').strip()

        return response

    async def search_contacts_by_email(
        self,
        email: str,
        prefs: dict
    ) -> List[dict]:
        """Search contacts by exact email match using SOQL."""
        # Escape for SOQL injection prevention
        email_escaped = self.escape_soql(email)

        # Build SOQL query
        soql = (
            f"SELECT Id, Name, Email, Phone, Title, Account.Name "
            f"FROM Contact "
            f"WHERE Email = '{email_escaped}' "
            f"LIMIT 5"
        )

        return await self.execute_soql_query(soql, prefs)

    async def search_contacts_by_name(
        self,
        name: str,
        prefs: dict
    ) -> List[dict]:
        """Search contacts by name using SOSL for fuzzy matching."""
        # Escape for SOSL
        name_escaped = self.escape_soql(name)

        # Build SOSL query
        sosl = (
            f"FIND {{{name_escaped}}} IN NAME FIELDS "
            f"RETURNING Contact(Id, Name, Email, Phone, Title, Account.Name) "
            f"LIMIT 5"
        )

        # Execute SOSL search
        result = await self.execute_sosl_search(sosl, prefs)

        # Extract contacts from SOSL result
        if result and "searchRecords" in result:
            return result["searchRecords"]

        return []

    async def execute_soql_query(
        self,
        soql: str,
        prefs: dict
    ) -> List[dict]:
        """Execute a SOQL query and return records."""
        # Use the existing sf_query method
        records = await self.sf_query(soql)

        if records:
            self.worker.editor_logging_handler.info(
                f"SOQL query returned {len(records)} records"
            )
            return records

        return []

    async def execute_sosl_search(
        self,
        sosl: str,
        prefs: dict
    ) -> Optional[dict]:
        """Execute a SOSL search and return results."""
        # Manually URL encode the query
        # Replace spaces with + and special chars
        sosl_encoded = sosl.replace(" ", "+").replace("{", "%7B").replace("}", "%7D")

        # Make API request
        path = f"search?q={sosl_encoded}"
        result = await self.sf_request("GET", path)

        if result:
            self.worker.editor_logging_handler.info(
                "SOSL search completed"
            )

        return result

    async def speak_contact_details(self, contact: dict):
        """Speak full details of a single contact."""
        # Extract fields
        name = contact.get("Name", "Unknown")
        email = contact.get("Email", "no email on file")
        phone = contact.get("Phone", "no phone on file")
        title = contact.get("Title", "")

        # Account.Name is a nested object
        account_name = ""
        if "Account" in contact and contact["Account"]:
            account_name = contact["Account"].get("Name", "")

        # Build response
        response = f"I found {name}."

        if title:
            response += f" They're the {title}"
            if account_name:
                response += f" at {account_name}."
            else:
                response += "."
        elif account_name:
            response += f" They're at {account_name}."

        response += f" Email: {email}."

        if phone != "no phone on file":
            response += f" Phone: {phone}."

        await self.capability_worker.speak(response)

    async def speak_multiple_contacts(self, contacts: List[dict]):
        """Speak a list of contacts and ask which one."""
        count = len(contacts)

        response = f"I found {count} contacts. "

        # List first 3
        for i, contact in enumerate(contacts[:3]):
            name = contact.get("Name", "Unknown")

            # Get company if available
            company = ""
            if "Account" in contact and contact["Account"]:
                company = contact["Account"].get("Name", "")

            if company:
                response += f"{name} at {company}. "
            else:
                response += f"{name}. "

        if count > 3:
            response += f"And {count - 3} more. "

        response += "Which one?"

        await self.capability_worker.speak(response)

    async def cache_recent_result(
        self,
        result_type: str,
        items: List[dict],
        prefs: dict
    ):
        """Cache search results for follow-up references."""
        prefs["recent_results"] = {
            "type": result_type,
            "items": items,
            "cached_at": datetime.utcnow().isoformat()
        }

        await self.save_preferences(prefs)

    # --- MODE 2: SEARCH OPPORTUNITIES (FULLY IMPLEMENTED) ---
    async def search_opportunities(self, query: str):
        """Search for opportunities by name."""
        await self.capability_worker.speak("Searching for opportunities...")

        prefs = await self.get_preferences()

        # Extract opportunity name using LLM
        opp_name = await self.extract_opportunity_name(query)

        if not opp_name:
            await self.capability_worker.speak(
                "I didn't catch which opportunity you're looking for. Try again?"
            )
            return

        self.worker.editor_logging_handler.info(
            f"Searching for opportunity: {opp_name}"
        )

        # Search opportunities
        opportunities = await self.search_opportunities_by_name(opp_name, prefs)

        if not opportunities:
            await self.capability_worker.speak(
                f"I couldn't find any opportunities matching {opp_name}."
            )
            return

        if len(opportunities) == 1:
            # Single result - speak full details
            await self.speak_opportunity_details(opportunities[0])
        else:
            # Multiple results - list and ask which one
            await self.speak_multiple_opportunities(opportunities)

        # Cache results for follow-up
        await self.cache_recent_result("opportunity", opportunities, prefs)

    async def extract_opportunity_name(self, query: str) -> str:
        """Extract opportunity name from query using LLM."""
        prompt = (
            f"Extract the opportunity or deal name from this query: '{query}'\n"
            "Return ONLY the opportunity name, nothing else.\n"
            "Examples:\n"
            "Query: 'how's the Acme deal' → Acme\n"
            "Query: 'what's the status of Project Phoenix' → Project Phoenix\n"
            "Query: 'check the Widget Co opportunity' → Widget Co\n"
        )

        response = self.capability_worker.text_to_text_response(prompt).strip()

        # Clean up response
        response = response.replace('"', '').replace("'", '').strip()

        return response

    async def search_opportunities_by_name(
        self,
        name: str,
        prefs: dict
    ) -> List[dict]:
        """Search opportunities by name using SOQL."""
        # Escape for SOQL
        name_escaped = self.escape_soql(name)

        # Build SOQL query
        soql = (
            f"SELECT Id, Name, StageName, Amount, CloseDate, "
            f"Account.Name, Owner.FirstName, Owner.LastName "
            f"FROM Opportunity "
            f"WHERE Name LIKE '%{name_escaped}%' "
            f"AND IsClosed = false "
            f"LIMIT 5"
        )

        return await self.execute_soql_query(soql, prefs)

    async def speak_opportunity_details(self, opportunity: dict):
        """Speak full details of a single opportunity."""
        # Extract fields
        name = opportunity.get("Name", "Unknown opportunity")
        stage = opportunity.get("StageName", "unknown stage")
        amount = opportunity.get("Amount")
        close_date = opportunity.get("CloseDate", "")

        # Get account name
        account = opportunity.get("Account", {})
        account_name = account.get("Name", "") if account else ""

        # Get owner name
        owner = opportunity.get("Owner", {})
        owner_first = owner.get("FirstName", "") if owner else ""
        owner_last = owner.get("LastName", "") if owner else ""
        owner_name = f"{owner_first} {owner_last}".strip()

        # Format amount
        amount_text = self.format_currency(amount) if amount else "no amount set"

        # Format close date
        close_date_text = self.format_date(close_date) if close_date else ""

        # Build response
        response = f"The {name} opportunity is in {stage}."

        if amount_text:
            response += f" It's worth {amount_text}."

        if close_date_text:
            response += f" Close date: {close_date_text}."

        if account_name:
            response += f" Account is {account_name}."

        if owner_name:
            response += f" Owned by {owner_name}."

        await self.capability_worker.speak(response)

    async def speak_multiple_opportunities(self, opportunities: List[dict]):
        """Speak a list of opportunities and ask which one."""
        count = len(opportunities)

        response = f"I found {count} opportunities. "

        # List first 3
        for i, opp in enumerate(opportunities[:3]):
            name = opp.get("Name", "Unknown")
            stage = opp.get("StageName", "unknown stage")

            response += f"{name} in {stage}. "

        if count > 3:
            response += f"And {count - 3} more. "

        response += "Which one?"

        await self.capability_worker.speak(response)

    def format_currency(self, amount) -> str:
        """Format amount as currency for speaking."""
        if not amount:
            return ""

        try:
            amount_float = float(amount)
            amount_int = int(amount_float)

            if amount_int >= 1000000:
                # Millions
                millions = amount_int / 1000000
                if millions == int(millions):
                    return f"{int(millions)} million dollars"
                else:
                    return f"{millions:.1f} million dollars"
            elif amount_int >= 1000:
                # Thousands
                thousands = amount_int / 1000
                if thousands == int(thousands):
                    return f"{int(thousands)} thousand dollars"
                else:
                    return f"{thousands:.1f} thousand dollars"
            else:
                return f"{amount_int} dollars"

        except Exception:
            return ""

    def format_date(self, date_str: str) -> str:
        """Format date for speaking."""
        if not date_str:
            return ""

        try:
            # Parse date (format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            date_part = date_str.split("T")[0]
            year, month, day = date_part.split("-")

            # Month names
            months = [
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"
            ]
            month_name = months[int(month) - 1]

            # Add ordinal suffix to day
            day_int = int(day)
            if 10 <= day_int % 100 <= 20:
                suffix = "th"
            else:
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(day_int % 10, "th")

            return f"{month_name} {day_int}{suffix}"

        except Exception:
            return date_str

    # --- MODE 3: LOG NOTE (FULLY IMPLEMENTED) ---
    async def log_note(self, command: str):
        """Log a note via creating a completed Task."""
        await self.capability_worker.speak("Logging a note...")

        prefs = await self.get_preferences()

        # Parse command to extract target and note content
        parsed = await self.parse_note_command(command)

        if not parsed:
            await self.capability_worker.speak(
                "I didn't catch what you want to log. Try again?"
            )
            return

        target_name = parsed.get("target")
        note_content = parsed.get("content")

        if not target_name or not note_content:
            await self.capability_worker.speak(
                "I need both who to log the note on and what the note says."
            )
            return

        self.worker.editor_logging_handler.info(
            f"Logging note on '{target_name}': {note_content}"
        )

        # Find the target record (contact, account, or opportunity)
        target_record = await self.find_note_target(target_name, prefs)

        if not target_record:
            await self.capability_worker.speak(
                f"I couldn't find {target_name}. "
                "Make sure they exist in your Salesforce."
            )
            return

        # Create the note (as a completed Task)
        success = await self.create_note_task(
            note_content,
            target_record,
            prefs
        )

        if success:
            await self.capability_worker.speak(
                f"Done. I've logged a note on {target_record['name']}: {note_content}"
            )
        else:
            await self.capability_worker.speak(
                "I had trouble creating the note. Please try again."
            )

    async def parse_note_command(self, command: str) -> Optional[dict]:
        """Parse note command using LLM."""
        prompt = (
            f"Parse this note command: '{command}'\n"
            "Extract the target (person/company name) and the note content.\n"
            "Return ONLY valid JSON with 'target' and 'content' fields.\n\n"
            "Examples:\n"
            "Input: 'log a note on Acme: they want to move forward'\n"
            "Output: {{\"target\": \"Acme\", \"content\": \"they want to move forward\"}}\n\n"
            "Input: 'add a note to Sarah Chen: she's interested in the enterprise plan'\n"
            "Output: {{\"target\": \"Sarah Chen\", \"content\": \"she's interested in the enterprise plan\"}}\n\n"
            "Input: 'note for TechCorp: follow up about pricing'\n"
            "Output: {{\"target\": \"TechCorp\", \"content\": \"follow up about pricing\"}}\n"
        )

        response = self.capability_worker.text_to_text_response(prompt).strip()

        # Clean markdown fences if present
        response = response.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(response)
            return parsed
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Failed to parse note command: {e}"
            )
            return None

    async def find_note_target(
        self,
        target_name: str,
        prefs: dict
    ) -> Optional[dict]:
        """Find target record for the note (contact, account, or opportunity)."""
        # Try contact first
        contact = await self.search_contact_by_name_single(target_name, prefs)
        if contact:
            return {
                "type": "contact",
                "id": contact.get("Id"),
                "name": contact.get("Name", "Unknown")
            }

        # Try account
        account = await self.search_account_by_name(target_name, prefs)
        if account:
            return {
                "type": "account",
                "id": account.get("Id"),
                "name": account.get("Name", "Unknown")
            }

        # Try opportunity
        opportunity = await self.search_opportunity_by_name_single(target_name, prefs)
        if opportunity:
            return {
                "type": "opportunity",
                "id": opportunity.get("Id"),
                "name": opportunity.get("Name", "Unknown")
            }

        return None

    async def search_contact_by_name_single(
        self,
        name: str,
        prefs: dict
    ) -> Optional[dict]:
        """Search for a contact by name (returns first match)."""
        contacts = await self.search_contacts_by_name(name, prefs)
        return contacts[0] if contacts else None

    async def search_account_by_name(
        self,
        name: str,
        prefs: dict
    ) -> Optional[dict]:
        """Search for an account by name (returns first match)."""
        name_escaped = self.escape_soql(name)

        soql = (
            f"SELECT Id, Name "
            f"FROM Account "
            f"WHERE Name LIKE '%{name_escaped}%' "
            f"LIMIT 1"
        )

        accounts = await self.execute_soql_query(soql, prefs)
        return accounts[0] if accounts else None

    async def search_opportunity_by_name_single(
        self,
        name: str,
        prefs: dict
    ) -> Optional[dict]:
        """Search for an opportunity by name (returns first match)."""
        opps = await self.search_opportunities_by_name(name, prefs)
        return opps[0] if opps else None

    async def create_note_task(
        self,
        note_content: str,
        target_record: dict,
        prefs: dict
    ) -> bool:
        """Create a completed Task as a note."""
        # Build subject (max 255 chars)
        subject = f"Voice Note: {note_content[:50]}"
        if len(note_content) > 50:
            subject += "..."

        # Build task data
        task_data = {
            "Subject": subject,
            "Description": f"Captured via OpenHome voice: {note_content}",
            "Status": "Completed",
            "Priority": "Normal",
            "ActivityDate": datetime.now().strftime("%Y-%m-%d")
        }

        # Add association based on target type
        target_type = target_record["type"]
        target_id = target_record["id"]

        if target_type == "contact":
            # WhoId for contacts/leads
            task_data["WhoId"] = target_id
        elif target_type == "account":
            # WhatId for accounts
            task_data["WhatId"] = target_id
        elif target_type == "opportunity":
            # WhatId for opportunities
            task_data["WhatId"] = target_id

        # Create task via API
        result = await self.sf_request(
            "POST",
            "sobjects/Task",
            task_data
        )

        if result and result.get("success"):
            self.worker.editor_logging_handler.info(
                f"Note task created: {result.get('id')}"
            )
            return True

        return False

    # --- MODE 4: CREATE TASK (FULLY IMPLEMENTED) ---
    async def create_task(self, command: str):
        """Create a task with due date and priority."""
        await self.capability_worker.speak("Creating a task...")

        prefs = await self.get_preferences()

        # Parse command to extract task details
        parsed = await self.parse_task_command(command)

        if not parsed:
            await self.capability_worker.speak(
                "I didn't catch the task details. Try again?"
            )
            return

        subject = parsed.get("subject")
        due_date_text = parsed.get("due_date")
        priority = parsed.get("priority", "Normal")
        target_name = parsed.get("target")

        if not subject:
            await self.capability_worker.speak(
                "I need at least a task subject."
            )
            return

        self.worker.editor_logging_handler.info(
            f"Creating task: {subject} (due: {due_date_text}, priority: {priority})"
        )

        # Parse due date
        due_date = self.parse_due_date(due_date_text)

        # Find target if specified
        target_record = None
        if target_name:
            target_record = await self.find_note_target(target_name, prefs)

        # Create the task
        success = await self.create_task_record(
            subject,
            due_date,
            priority,
            target_record,
            prefs
        )

        if success:
            # Build response
            response = f"Done. I've created a task: {subject}"

            if due_date_text:
                response += f", due {due_date_text}"

            if priority and priority != "Normal":
                response += f", {priority.lower()} priority"

            if target_record:
                response += f", for {target_record['name']}"

            response += "."

            await self.capability_worker.speak(response)
        else:
            await self.capability_worker.speak(
                "I had trouble creating the task. Please try again."
            )

    async def parse_task_command(self, command: str) -> Optional[dict]:
        """Parse task command using LLM."""
        prompt = (
            f"Parse this task command: '{command}'\n"
            "Extract: subject, due_date (text like 'Friday' or 'tomorrow'), "
            "priority (High/Normal/Low), and target (person/company).\n"
            "Return ONLY valid JSON.\n\n"
            "Examples:\n"
            "Input: 'create a task: send proposal to Acme by Friday'\n"
            "Output: {{\"subject\": \"send proposal to Acme\", \"due_date\": \"Friday\", "
            "\"priority\": \"Normal\", \"target\": \"Acme\"}}\n\n"
            "Input: 'remind me to follow up with Sarah next Monday'\n"
            "Output: {{\"subject\": \"follow up with Sarah\", \"due_date\": \"next Monday\", "
            "\"priority\": \"Normal\", \"target\": \"Sarah\"}}\n\n"
            "Input: 'task for Widget Co: schedule a demo, high priority'\n"
            "Output: {{\"subject\": \"schedule a demo\", \"due_date\": null, "
            "\"priority\": \"High\", \"target\": \"Widget Co\"}}\n"
        )

        response = self.capability_worker.text_to_text_response(prompt).strip()

        # Clean markdown fences
        response = response.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(response)
            return parsed
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Failed to parse task command: {e}"
            )
            return None

    def parse_due_date(self, date_text: Optional[str]) -> str:
        """Parse natural language date to YYYY-MM-DD format."""
        if not date_text:
            # Default to tomorrow
            tomorrow = datetime.now() + timedelta(days=1)
            return tomorrow.strftime("%Y-%m-%d")

        date_lower = date_text.lower()
        now = datetime.now()

        # Handle common cases
        if "tomorrow" in date_lower:
            target = now + timedelta(days=1)

        elif "today" in date_lower:
            target = now

        elif "monday" in date_lower:
            # Next Monday
            days_ahead = 0 - now.weekday()  # Monday is 0
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in date_lower:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)

        elif "tuesday" in date_lower:
            days_ahead = 1 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in date_lower:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)

        elif "wednesday" in date_lower:
            days_ahead = 2 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in date_lower:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)

        elif "thursday" in date_lower:
            days_ahead = 3 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in date_lower:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)

        elif "friday" in date_lower:
            days_ahead = 4 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in date_lower:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)

        elif "saturday" in date_lower:
            days_ahead = 5 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in date_lower:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)

        elif "sunday" in date_lower:
            days_ahead = 6 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in date_lower:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)

        else:
            # Default to tomorrow
            target = now + timedelta(days=1)

        return target.strftime("%Y-%m-%d")

    async def create_task_record(
        self,
        subject: str,
        due_date: str,
        priority: str,
        target_record: Optional[dict],
        prefs: dict
    ) -> bool:
        """Create a task in Salesforce."""
        # Build task data
        task_data = {
            "Subject": subject,
            "Description": "Voice-created via OpenHome",
            "ActivityDate": due_date,
            "Status": "Not Started",
            "Priority": priority
        }

        # Add association if target specified
        if target_record:
            target_type = target_record["type"]
            target_id = target_record["id"]

            if target_type == "contact":
                # WhoId for contacts
                task_data["WhoId"] = target_id
            elif target_type == "account":
                # WhatId for accounts
                task_data["WhatId"] = target_id
            elif target_type == "opportunity":
                # WhatId for opportunities
                task_data["WhatId"] = target_id

        # Create task via API
        result = await self.sf_request(
            "POST",
            "sobjects/Task",
            task_data
        )

        if result and result.get("success"):
            self.worker.editor_logging_handler.info(
                f"Task created: {result.get('id')}"
            )
            return True

        return False

    # --- MODE 5: PIPELINE SUMMARY (FULLY IMPLEMENTED) ---
    async def pipeline_summary(self):
        """Get summary of open opportunities by stage."""
        await self.capability_worker.speak("Getting your pipeline summary...")

        prefs = await self.get_preferences()

        # Fetch pipeline summary using SOQL GROUP BY
        summary = await self.fetch_pipeline_summary(prefs)

        if not summary:
            await self.capability_worker.speak(
                "You don't have any open opportunities in your pipeline right now."
            )
            return

        # Calculate totals
        total_deals = summary.get("total_count", 0)
        total_value = summary.get("total_amount", 0)
        stage_breakdown = summary.get("stages", [])

        if total_deals == 0:
            await self.capability_worker.speak(
                "You don't have any open opportunities in your pipeline right now."
            )
            return

        # Build and speak response
        await self.speak_pipeline_summary(
            total_deals,
            total_value,
            stage_breakdown
        )

    async def fetch_pipeline_summary(self, prefs: dict) -> Optional[dict]:
        """Fetch pipeline summary using SOQL GROUP BY."""
        # Note: This shows ALL open opportunities in the org
        # Salesforce Developer Edition comes with sample data
        # In production, you'd want to filter by OwnerId

        # Query 1: Get totals
        total_soql = (
            "SELECT COUNT(Id) cnt, SUM(Amount) total "
            "FROM Opportunity "
            "WHERE IsClosed = false"
        )

        self.worker.editor_logging_handler.info(
            f"Running total query: {total_soql}"
        )

        total_result = await self.execute_soql_query(total_soql, prefs)

        if not total_result or len(total_result) == 0:
            return None

        total_record = total_result[0]
        total_count = total_record.get("cnt", 0)
        total_amount = total_record.get("total", 0)

        self.worker.editor_logging_handler.info(
            f"Total query result: {total_count} opportunities, ${total_amount}"
        )

        # Query 2: Get breakdown by stage
        stage_soql = (
            "SELECT StageName, COUNT(Id) cnt, SUM(Amount) total "
            "FROM Opportunity "
            "WHERE IsClosed = false "
            "GROUP BY StageName "
            "ORDER BY SUM(Amount) DESC"
        )

        self.worker.editor_logging_handler.info(
            f"Running stage query: {stage_soql}"
        )

        stage_result = await self.execute_soql_query(stage_soql, prefs)

        if not stage_result:
            stage_result = []

        # Log each stage
        for stage in stage_result:
            self.worker.editor_logging_handler.info(
                f"Stage: {stage.get('StageName')}, "
                f"Count: {stage.get('cnt')}, "
                f"Total: ${stage.get('total')}"
            )

        self.worker.editor_logging_handler.info(
            f"Pipeline summary: {total_count} opportunities, "
            f"{len(stage_result)} stages"
        )

        return {
            "total_count": total_count,
            "total_amount": total_amount,
            "stages": stage_result
        }

    async def speak_pipeline_summary(
        self,
        total_deals: int,
        total_value: float,
        stage_breakdown: List[dict]
    ):
        """Speak the pipeline summary."""
        # Format total value
        total_text = self.format_currency(total_value) if total_value else "no value"

        # Start with overview
        if total_deals == 1:
            response = "Here's your pipeline. You have 1 open opportunity"
        else:
            response = f"Here's your pipeline. You have {total_deals} open opportunities"

        if total_text != "no value":
            response += f" worth {total_text} total"

        response += ". "

        # Speak top 6 stages by value (already sorted DESC)
        stages_to_speak = stage_breakdown[:6]

        for stage_data in stages_to_speak:
            stage_name = stage_data.get("StageName", "Unknown stage")
            count = stage_data.get("cnt", 0)
            stage_value = stage_data.get("total", 0)

            # Build stage summary
            if count == 1:
                response += f"1 deal in {stage_name}"
            else:
                response += f"{count} deals in {stage_name}"

            if stage_value:
                stage_value_text = self.format_currency(stage_value)
                if stage_value_text:
                    response += f" worth {stage_value_text}"

            response += ". "

        # If more than 6 stages, mention remaining
        if len(stage_breakdown) > 6:
            remaining = len(stage_breakdown) - 6
            response += f"Plus {remaining} more stages."

        await self.capability_worker.speak(response)

    # --- MODE 6: MOVE OPPORTUNITY STAGE (FULLY IMPLEMENTED) ---
    async def move_opportunity_stage(self, command: str):
        """Move an opportunity to a different stage with confirmation."""
        await self.capability_worker.speak("Updating opportunity stage...")

        prefs = await self.get_preferences()

        # Parse command to extract opportunity name and target stage
        parsed = await self.parse_move_stage_command(command)

        if not parsed:
            await self.capability_worker.speak(
                "I didn't catch which opportunity or stage. Try again?"
            )
            return

        opp_name = parsed.get("opportunity_name")
        target_stage_text = parsed.get("target_stage")

        if not opp_name or not target_stage_text:
            await self.capability_worker.speak(
                "I need both the opportunity name and the target stage."
            )
            return

        self.worker.editor_logging_handler.info(
            f"Moving opportunity '{opp_name}' to '{target_stage_text}'"
        )

        # Find the opportunity
        opportunity = await self.search_opportunity_by_name_single(opp_name, prefs)

        if not opportunity:
            await self.capability_worker.speak(
                f"I couldn't find an opportunity matching {opp_name}."
            )
            return

        # Get current and target stages
        current_stage = opportunity.get("StageName", "unknown")
        opp_display_name = opportunity.get("Name", "the opportunity")
        opp_id = opportunity.get("Id")

        # Get available stages from cache
        stages = prefs.get("opportunity_stages", [])

        # Match target stage
        target_stage = self.match_stage_name(target_stage_text, stages)

        if not target_stage:
            # Couldn't match - list available stages
            if stages:
                stage_names = ", ".join([s.get("label", "") for s in stages])
                await self.capability_worker.speak(
                    f"I'm not sure which stage you mean. "
                    f"Available stages are: {stage_names}. Which one?"
                )
            else:
                await self.capability_worker.speak(
                    "I don't have your pipeline stages cached. "
                    "Please try again."
                )
            return

        target_stage_name = target_stage.get("label", target_stage_text)

        # CRITICAL: Confirm before updating
        await self.capability_worker.speak(
            f"I'll move the {opp_display_name} opportunity "
            f"from {current_stage} to {target_stage_name}. Confirm?"
        )

        confirmation = await self.capability_worker.run_io_loop(
            "Say yes to confirm or no to cancel."
        )

        if not confirmation or not self.is_yes(confirmation):
            await self.capability_worker.speak(
                "Cancelled. The opportunity was not updated."
            )
            return

        # Update the opportunity
        success = await self.update_opportunity_stage(
            opp_id,
            target_stage_name,
            prefs
        )

        if success:
            await self.capability_worker.speak(
                f"Done. I've moved {opp_display_name} to {target_stage_name}."
            )
        else:
            await self.capability_worker.speak(
                "I had trouble updating the opportunity. Please try again."
            )

    async def parse_move_stage_command(self, command: str) -> Optional[dict]:
        """Parse move stage command using LLM."""
        prompt = (
            f"Parse this opportunity stage update command: '{command}'\n"
            "Extract the opportunity name and the target stage.\n"
            "Return ONLY valid JSON.\n\n"
            "Examples:\n"
            "Input: 'move the Acme deal to contract sent'\n"
            "Output: {{\"opportunity_name\": \"Acme\", \"target_stage\": \"contract sent\"}}\n\n"
            "Input: 'update Widget Co to closed won'\n"
            "Output: {{\"opportunity_name\": \"Widget Co\", \"target_stage\": \"closed won\"}}\n\n"
            "Input: 'mark AK as closed lost'\n"
            "Output: {{\"opportunity_name\": \"AK\", \"target_stage\": \"closed lost\"}}\n\n"
            "Input: 'change TechCorp to qualification'\n"
            "Output: {{\"opportunity_name\": \"TechCorp\", \"target_stage\": \"qualification\"}}\n"
        )

        response = self.capability_worker.text_to_text_response(prompt).strip()

        # Clean markdown fences
        response = response.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(response)
            return parsed
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Failed to parse move stage command: {e}"
            )
            return None

    def match_stage_name(
        self,
        target_text: str,
        stages: List[dict]
    ) -> Optional[dict]:
        """Match natural language stage name to actual stage."""
        target_lower = target_text.lower().strip()

        # Direct match
        for stage in stages:
            label = stage.get("label", "").lower()
            if label == target_lower:
                return stage

        # Common aliases
        aliases = {
            "won": "closed won",
            "we won it": "closed won",
            "closed one": "closed won",  # Speech recognition
            "lost": "closed lost",
            "dead": "closed lost",
            "we lost it": "closed lost",
            "prospecting": "prospecting",
            "qualification": "qualification",
            "qualified": "qualification",
            "needs analysis": "needs analysis",
            "value proposition": "value proposition",
            "value prop": "value proposition",
            "id decision": "id. decision makers",
            "decision makers": "id. decision makers",
            "perception": "perception analysis",
            "proposal": "proposal/price quote",
            "price quote": "proposal/price quote",
            "negotiation": "negotiation/review",
            "review": "negotiation/review"
        }

        # Check aliases
        if target_lower in aliases:
            canonical = aliases[target_lower]
            for stage in stages:
                if stage.get("label", "").lower() == canonical:
                    return stage

        # Partial match
        for stage in stages:
            label = stage.get("label", "").lower()
            if target_lower in label or label in target_lower:
                return stage

        return None

    async def update_opportunity_stage(
        self,
        opp_id: str,
        stage_name: str,
        prefs: dict
    ) -> bool:
        """Update opportunity stage via API."""
        update_data = {
            "StageName": stage_name
        }

        result = await self.sf_request(
            "PATCH",
            f"sobjects/Opportunity/{opp_id}",
            update_data
        )

        if result is not None:
            self.worker.editor_logging_handler.info(
                f"Opportunity stage updated: {opp_id} → {stage_name}"
            )
            return True

        return False

    def is_yes(self, text: str) -> bool:
        """Check if user said yes."""
        yes_words = [
            "yes", "yeah", "yep", "sure", "confirm", "ok", "okay",
            "yup", "correct", "right", "affirmative", "go ahead"
        ]
        return any(word in text.lower() for word in yes_words)

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

    # --- OAUTH & TOKEN MANAGEMENT ---
    async def ensure_authenticated(self) -> bool:
        """Ensure we have valid authentication. Returns True if ready."""
        prefs = await self.get_preferences()

        # Initialize with hardcoded credentials if not present
        if not prefs.get("access_token"):
            prefs["access_token"] = self.INITIAL_ACCESS_TOKEN
            prefs["refresh_token"] = self.INITIAL_REFRESH_TOKEN
            prefs["instance_url"] = self.INSTANCE_URL
            prefs["consumer_key"] = self.CONSUMER_KEY
            prefs["consumer_secret"] = self.CONSUMER_SECRET
            prefs["token_issued_at"] = int(time.time() * 1000)

            await self.save_preferences(prefs)

            self.worker.editor_logging_handler.info(
                "Initialized Salesforce with hardcoded credentials"
            )

        # Ensure token is fresh
        return await self.refresh_access_token_if_needed(prefs)

    async def setup_salesforce(self) -> bool:
        """First-time setup: guide user through Connected App creation."""
        await self.capability_worker.speak(
            "Let's connect your Salesforce account. You'll need admin access "
            "to create a Connected App. I'll walk you through it."
        )

        await self.worker.session_tasks.sleep(0.5)
        await self.capability_worker.speak(
            "Open Salesforce. Click the gear icon in the top right and go to Setup. "
            "In the Quick Find box, type App Manager and click it. "
            "Then click New Connected App in the top right."
        )

        await self.worker.session_tasks.sleep(0.5)
        await self.capability_worker.speak(
            "Name it OpenHome Voice. Fill in your email under Contact Email. "
            "Scroll down to API and check Enable OAuth Settings. "
            "For the Callback URL, enter https://login.salesforce.com. "
            "Under Selected OAuth Scopes, add Access and manage your data "
            "and Perform requests on your behalf at any time. Click Save."
        )

        await self.worker.session_tasks.sleep(0.5)
        await self.capability_worker.speak(
            "It can take 2 to 10 minutes for the app to be ready. "
            "Once it is, go back to App Manager, find OpenHome Voice, "
            "click the dropdown arrow, and click View. "
            "Copy the Consumer Key first."
        )

        # Get Consumer Key
        consumer_key = await self.capability_worker.run_io_loop(
            "Paste or read me your Consumer Key."
        )

        if not consumer_key or len(consumer_key.strip()) < 20:
            await self.capability_worker.speak(
                "I didn't catch a valid Consumer Key. Let's try again later."
            )
            return False

        consumer_key = consumer_key.strip()

        # Get Consumer Secret
        await self.capability_worker.speak(
            "Great. Now copy the Consumer Secret."
        )

        consumer_secret = await self.capability_worker.run_io_loop(
            "Paste or read me your Consumer Secret."
        )

        if not consumer_secret or len(consumer_secret.strip()) < 20:
            await self.capability_worker.speak(
                "I didn't catch a valid Consumer Secret. Let's try again later."
            )
            return False

        consumer_secret = consumer_secret.strip()

        # Save credentials
        prefs = await self.get_preferences()
        prefs["consumer_key"] = consumer_key
        prefs["consumer_secret"] = consumer_secret
        await self.save_preferences(prefs)

        await self.capability_worker.speak("Got it. Saved your credentials.")

        # Now complete OAuth flow
        return await self.complete_oauth_flow(prefs)

    async def complete_oauth_flow(self, prefs: dict) -> bool:
        """Complete OAuth authorization flow to get tokens."""
        prefs.get("consumer_key")

        await self.capability_worker.speak(
            "I need your authorization. Open a browser and go to this URL. "
            "I'll spell it out slowly."
        )

        # For voice, we can't easily share URLs
        # In production, this would need a better UX (QR code, SMS, etc.)
        await self.capability_worker.speak(
            "Actually, this needs to be done via a web interface. "
            "For now, I'll need you to manually configure the tokens. "
            "This is a limitation of voice-only OAuth."
        )

        return False

    async def refresh_access_token_if_needed(self, prefs: dict) -> bool:
        """Check if access token is stale and refresh if needed."""
        # Check token age
        token_issued = prefs.get("token_issued_at", 0)
        current_time = int(time.time() * 1000)  # milliseconds
        age_seconds = (current_time - token_issued) / 1000

        # Refresh if older than 1.5 hours (conservative)
        if age_seconds > 5400:  # 90 minutes
            self.worker.editor_logging_handler.info(
                f"Token age: {age_seconds}s, refreshing..."
            )
            return await self.refresh_access_token(prefs)

        return True

    async def refresh_access_token(self, prefs: dict) -> bool:
        """Refresh the access token using refresh token."""
        refresh_token = prefs.get("refresh_token")
        consumer_key = prefs.get("consumer_key")
        consumer_secret = prefs.get("consumer_secret")

        if not all([refresh_token, consumer_key, consumer_secret]):
            self.worker.editor_logging_handler.error(
                "Missing credentials for token refresh"
            )
            return False

        try:
            # Make refresh request
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": consumer_key,
                "client_secret": consumer_secret
            }

            response = requests.post(
                self.TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10
            )

            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"Token refresh failed: {response.status_code} - {response.text}"
                )
                return False

            token_data = response.json()

            # Update stored tokens
            prefs["access_token"] = token_data["access_token"]
            prefs["instance_url"] = token_data["instance_url"]
            prefs["token_issued_at"] = int(time.time() * 1000)

            await self.save_preferences(prefs)

            self.worker.editor_logging_handler.info(
                "Access token refreshed successfully"
            )

            return True

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Token refresh error: {e}"
            )
            return False

    # --- API HELPERS ---
    async def sf_request(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None
    ) -> Optional[dict]:
        """Make Salesforce API request with auto token refresh."""
        prefs = await self.get_preferences()

        # Ensure token is fresh
        if not await self.refresh_access_token_if_needed(prefs):
            self.worker.editor_logging_handler.error(
                "Failed to refresh token before request"
            )
            return None

        # Reload prefs in case they were updated
        prefs = await self.get_preferences()

        instance_url = prefs.get("instance_url")
        access_token = prefs.get("access_token")

        if not instance_url or not access_token:
            self.worker.editor_logging_handler.error(
                "Missing instance_url or access_token"
            )
            return None

        # Build full URL
        if path.startswith("http"):
            url = path
        else:
            # Remove leading slash if present
            path = path.lstrip("/")
            url = f"{instance_url}/services/data/{self.API_VERSION}/{path}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        try:
            # Make request
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(
                    url, headers=headers, json=data, timeout=10
                )
            elif method == "PATCH":
                response = requests.patch(
                    url, headers=headers, json=data, timeout=10
                )
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, timeout=10)
            else:
                return None

            # Handle 401 with one retry after refresh
            if response.status_code == 401:
                self.worker.editor_logging_handler.warning(
                    "Got 401, attempting token refresh and retry"
                )

                if await self.refresh_access_token(prefs):
                    # Reload prefs and retry
                    prefs = await self.get_preferences()
                    access_token = prefs.get("access_token")
                    headers["Authorization"] = f"Bearer {access_token}"

                    if method == "GET":
                        response = requests.get(url, headers=headers, timeout=10)
                    elif method == "POST":
                        response = requests.post(
                            url, headers=headers, json=data, timeout=10
                        )
                    elif method == "PATCH":
                        response = requests.patch(
                            url, headers=headers, json=data, timeout=10
                        )
                    elif method == "DELETE":
                        response = requests.delete(url, headers=headers, timeout=10)

            # Log errors
            if response.status_code >= 400:
                self.worker.editor_logging_handler.error(
                    f"Salesforce API error: {response.status_code} - {response.text}"
                )

                if response.status_code == 401:
                    return None
                elif response.status_code == 403:
                    return None
                elif response.status_code == 404:
                    return None
                else:
                    return None

            # Parse JSON response
            if response.content:
                return response.json()
            else:
                return {}

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Salesforce API request error: {e}"
            )
            return None

    async def sf_query(self, soql: str) -> Optional[List[dict]]:
        """Execute SOQL query and return records."""
        # Manually URL-encode the query
        # Note: Salesforce accepts unencoded commas and quotes in query params
        # Only encode spaces as +
        encoded_query = soql.replace(" ", "+")

        result = await self.sf_request("GET", f"query?q={encoded_query}")

        if result and "records" in result:
            return result["records"]

        return None

    def escape_soql(self, text: str) -> str:
        """Escape single quotes for SOQL injection prevention."""
        return text.replace("'", "\\'")

    async def cache_opportunity_stages(self) -> bool:
        """Cache opportunity stages from Salesforce."""
        prefs = await self.get_preferences()

        # Check if cache is fresh
        cache_updated = prefs.get("stages_cache_updated")
        if cache_updated:
            cache_time = datetime.fromisoformat(cache_updated)
            age_minutes = (datetime.utcnow() - cache_time).total_seconds() / 60

            if age_minutes < self.CACHE_REFRESH_MINUTES:
                # Cache is fresh
                return True

        # Fetch stages
        soql = """
            SELECT MasterLabel, IsActive, IsClosed, IsWon, SortOrder
            FROM OpportunityStage
            WHERE IsActive = true
            ORDER BY SortOrder
        """

        records = await self.sf_query(soql)

        if not records:
            self.worker.editor_logging_handler.error(
                "Failed to fetch opportunity stages"
            )
            return False

        # Store stages
        stages = [
            {
                "label": r.get("MasterLabel"),
                "sort": r.get("SortOrder"),
                "closed": r.get("IsClosed"),
                "won": r.get("IsWon")
            }
            for r in records
        ]

        prefs["opportunity_stages"] = stages
        prefs["stages_cache_updated"] = datetime.utcnow().isoformat()
        await self.save_preferences(prefs)

        self.worker.editor_logging_handler.info(
            f"Cached {len(stages)} opportunity stages"
        )

        return True
