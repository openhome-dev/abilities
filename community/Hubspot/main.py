import json
from datetime import datetime, timedelta
from typing import ClassVar, Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class HubspotAbility1Capability(MatchingCapability):
    # {{register capability}}
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    PREFS_FILENAME: ClassVar[str] = "hubspot_crm_prefs.json"
    PERSIST: ClassVar[bool] = False

    BASE_URL: ClassVar[str] = "https://api.hubapi.com"

    # Your HubSpot API token
    API_TOKEN: ClassVar[str] = "xxxxx"

    # Association Type IDs (HUBSPOT_DEFINED)
    ASSOCIATION_TYPES: ClassVar[Dict[str, int]] = {
        "note_to_contact": 202,
        "note_to_company": 190,
        "note_to_deal": 214,
        "task_to_contact": 204,
        "task_to_company": 192,
        "task_to_deal": 216,
    }

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_main())

    # --- MAIN ENTRY POINT ---
    async def run_main(self):
        try:
            # Step 1: Say "HubSpot Ready"
            await self.capability_worker.speak("HubSpot Ready.")
            await self.worker.session_tasks.sleep(0.5)

            # Step 2: Loop for multiple commands
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

                # Step 3: Detect mode and route
                mode = await self.detect_mode(command)

                if mode == "search_contact":
                    await self.search_contacts(command)
                elif mode == "search_deal":
                    await self.search_deals(command)
                elif mode == "log_note":
                    await self.log_note(command)
                elif mode == "create_task":
                    await self.create_task(command)
                elif mode == "pipeline_summary":
                    await self.pipeline_summary()
                elif mode == "move_deal":
                    await self.move_deal_stage(command)
                else:
                    await self.capability_worker.speak(
                        "I'm not sure what you want me to do. "
                        "Try 'look up a contact', 'check a deal', "
                        "'log a note', 'create a task', or 'show my pipeline'."
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"HubSpot CRM error: {e}")
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

        # Log Note - check FIRST (most specific)
        if any(word in cmd_lower for word in [
            "log note", "add note", "note on", "note for"
        ]):
            return "log_note"

        # Create Task - check for various task patterns
        if any(word in cmd_lower for word in [
            "create task", "create a task", "add task", "add a task",
            "remind me", "task for", "new task"
        ]):
            return "create_task"

        # Pipeline Summary
        if any(word in cmd_lower for word in [
            "pipeline", "my pipeline", "open deals"
        ]):
            return "pipeline_summary"

        # Move Deal - check BEFORE search deal (more specific)
        if any(word in cmd_lower for word in [
            "move", "update deal", "change stage", "mark", "closed won",
            "closed lost", "mark as", "change to", "update to"
        ]):
            return "move_deal"

        # Search Deal - check for deal-specific keywords
        if any(word in cmd_lower for word in [
            "deal", "how's the", "how is the", "what's the status",
            "check the", "find deal", "deal status"
        ]):
            return "search_deal"

        # Search Contact - broad match (check LAST as fallback)
        if any(word in cmd_lower for word in [
            "look up", "find contact", "who is", "search contact", "find", "search"
        ]):
            return "search_contact"

        return "unknown"

    # --- MODE 1: SEARCH CONTACTS (FULLY IMPLEMENTED) ---
    async def search_contacts(self, query: str):
        """Search for contacts by name or email."""
        await self.capability_worker.speak("Searching for contacts...")

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

        # Build search filters
        filters = self.build_contact_filters(search_term)

        # Make API call
        search_data = {
            "filterGroups": filters,
            "properties": [
                "firstname", "lastname", "email", "phone",
                "company", "lifecyclestage", "hubspot_owner_id"
            ],
            "limit": 5
        }

        result = self._make_request(
            "POST",
            "/crm/v3/objects/contacts/search",
            self.API_TOKEN,
            search_data
        )

        if not result:
            await self.capability_worker.speak(
                "I had trouble connecting to HubSpot. Please try again."
            )
            return

        # Process results
        contacts = result.get("results", [])

        self.worker.editor_logging_handler.info(
            f"Found {len(contacts)} contacts"
        )

        if len(contacts) == 0:
            await self.capability_worker.speak(
                f"I couldn't find any contacts matching {search_term}. "
                "Want me to search for something else?"
            )
            return

        if len(contacts) == 1:
            # Single result - speak full details
            await self.speak_contact_details(contacts[0])
        else:
            # Multiple results - list them and ask which one
            await self.speak_multiple_contacts(contacts)

    async def extract_search_term(self, query: str) -> str:
        """Extract the name or email from the query using LLM."""
        prompt = (
            f"Extract the person's name or email from this query: '{query}'\n"
            "Return ONLY the name or email, nothing else.\n"
            "Examples:\n"
            "Query: 'look up Sarah Chen' → Sarah Chen\n"
            "Query: 'find john@acme.com' → john@acme.com\n"
            "Query: 'who is the contact at Acme' → Acme\n"
        )

        response = self.capability_worker.text_to_text_response(prompt).strip()

        # Clean up response (remove quotes, extra spaces)
        response = response.replace('"', '').replace("'", '').strip()

        return response

    def build_contact_filters(self, search_term: str) -> List[dict]:
        """Build HubSpot search filters based on search term."""
        # Check if it's an email (contains @)
        if "@" in search_term:
            return [{
                "filters": [{
                    "propertyName": "email",
                    "operator": "EQ",
                    "value": search_term
                }]
            }]

        # Check if it's two words (first name + last name)
        words = search_term.split()

        if len(words) == 2:
            # Search for first AND last name
            return [{
                "filters": [
                    {
                        "propertyName": "firstname",
                        "operator": "CONTAINS_TOKEN",
                        "value": words[0]
                    },
                    {
                        "propertyName": "lastname",
                        "operator": "CONTAINS_TOKEN",
                        "value": words[1]
                    }
                ]
            }]

        if len(words) == 1:
            # Search for first name OR last name
            return [
                {
                    "filters": [{
                        "propertyName": "firstname",
                        "operator": "CONTAINS_TOKEN",
                        "value": search_term
                    }]
                },
                {
                    "filters": [{
                        "propertyName": "lastname",
                        "operator": "CONTAINS_TOKEN",
                        "value": search_term
                    }]
                }
            ]

        # Default: search in firstname
        return [{
            "filters": [{
                "propertyName": "firstname",
                "operator": "CONTAINS_TOKEN",
                "value": search_term
            }]
        }]

    async def speak_contact_details(self, contact: dict):
        """Speak full details of a single contact."""
        props = contact.get("properties", {})

        # Extract fields
        first_name = props.get("firstname", "")
        last_name = props.get("lastname", "")
        full_name = f"{first_name} {last_name}".strip()

        email = props.get("email", "no email on file")
        phone = props.get("phone", "no phone on file")
        company = props.get("company", "no company listed")
        lifecycle = props.get("lifecyclestage", "")

        # Format lifecycle stage for speaking
        lifecycle_text = self.format_lifecycle_stage(lifecycle)

        # Build response
        response = f"I found {full_name}."

        if company != "no company listed":
            response += f" They're at {company}."

        response += f" Email: {email}."

        if phone != "no phone on file":
            response += f" Phone: {phone}."

        if lifecycle_text:
            response += f" They're currently {lifecycle_text}."

        await self.capability_worker.speak(response)

        # Cache this result for follow-up
        await self.cache_recent_result("contact", [contact])

    async def speak_multiple_contacts(self, contacts: List[dict]):
        """Speak a list of contacts and ask which one."""
        count = len(contacts)

        response = f"I found {count} contacts. "

        # List first 3
        for i, contact in enumerate(contacts[:3]):
            props = contact.get("properties", {})
            first_name = props.get("firstname", "")
            last_name = props.get("lastname", "")
            full_name = f"{first_name} {last_name}".strip()
            company = props.get("company", "")

            if company:
                response += f"{full_name} at {company}. "
            else:
                response += f"{full_name}. "

        if count > 3:
            response += f"And {count - 3} more. "

        response += "Which one?"

        await self.capability_worker.speak(response)

        # Cache all results for follow-up
        await self.cache_recent_result("contact", contacts)

    def format_lifecycle_stage(self, stage: str) -> str:
        """Convert lifecycle stage ID to human-readable text."""
        stage_map = {
            "subscriber": "a subscriber",
            "lead": "a lead",
            "marketingqualifiedlead": "a marketing qualified lead",
            "salesqualifiedlead": "a sales qualified lead",
            "opportunity": "an opportunity",
            "customer": "a customer",
            "evangelist": "an evangelist",
            "other": "in other stage"
        }

        return stage_map.get(stage, "")

    # --- CACHING FOR FOLLOW-UP ---
    async def cache_recent_result(self, result_type: str, items: List[dict]):
        """Cache search results for follow-up references."""
        prefs = await self.get_preferences()

        prefs["recent_results"] = {
            "type": result_type,
            "items": items,
            "cached_at": datetime.utcnow().isoformat()
        }

        await self.save_preferences(prefs)

    # --- MODE 2: SEARCH DEALS (FULLY IMPLEMENTED) ---
    async def search_deals(self, query: str):
        """Search for deals by name."""
        await self.capability_worker.speak("Searching for deals...")

        # Extract deal name from query using LLM
        deal_name = await self.extract_deal_name(query)

        if not deal_name:
            await self.capability_worker.speak(
                "I didn't catch which deal you're looking for. Try again?"
            )
            return

        self.worker.editor_logging_handler.info(
            f"Searching for deal: {deal_name}"
        )

        # Fetch pipeline stages (cached or fresh)
        stage_map = await self.get_stage_map()

        # Build search filters
        search_data = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "dealname",
                    "operator": "CONTAINS_TOKEN",
                    "value": deal_name
                }]
            }],
            "properties": [
                "dealname", "dealstage", "pipeline", "amount",
                "closedate", "hubspot_owner_id"
            ],
            "limit": 5
        }

        # Make API call
        result = self._make_request(
            "POST",
            "/crm/v3/objects/deals/search",
            self.API_TOKEN,
            search_data
        )

        if not result:
            await self.capability_worker.speak(
                "I had trouble connecting to HubSpot. Please try again."
            )
            return

        # Process results
        deals = result.get("results", [])

        self.worker.editor_logging_handler.info(
            f"Found {len(deals)} deals"
        )

        if len(deals) == 0:
            await self.capability_worker.speak(
                f"I couldn't find any deals matching {deal_name}. "
                "Want me to search for something else?"
            )
            return

        if len(deals) == 1:
            # Single result - speak full details
            await self.speak_deal_details(deals[0], stage_map)
        else:
            # Multiple results - list them and ask which one
            await self.speak_multiple_deals(deals, stage_map)

    async def extract_deal_name(self, query: str) -> str:
        """Extract the deal name from the query using LLM."""
        prompt = (
            f"Extract the deal name from this query: '{query}'\n"
            "Return ONLY the deal name, nothing else.\n"
            "Examples:\n"
            "Query: 'how's the Acme deal' → Acme\n"
            "Query: 'what's the status of Project Phoenix' → Project Phoenix\n"
            "Query: 'check the Widget Co deal' → Widget Co\n"
        )

        response = self.capability_worker.text_to_text_response(prompt).strip()

        # Clean up response
        response = response.replace('"', '').replace("'", '').strip()

        return response

    async def get_stage_map(self) -> Dict[str, str]:
        """Get pipeline stage mapping (stage_id → stage_label)."""
        # Check cache first
        prefs = await self.get_preferences()

        # Check if cache is fresh (within 30 minutes)
        cache_updated = prefs.get("pipeline_cache_updated")
        if cache_updated:
            cache_time = datetime.fromisoformat(cache_updated)
            age_minutes = (datetime.utcnow() - cache_time).total_seconds() / 60

            if age_minutes < 30 and prefs.get("pipelines"):
                # Use cached pipelines
                return self.build_stage_map_from_cache(prefs["pipelines"])

        # Fetch fresh pipelines
        result = self._make_request(
            "GET",
            "/crm/v3/pipelines/deals",
            self.API_TOKEN
        )

        if not result or "results" not in result:
            # Fallback to empty map
            return {}

        pipelines = result["results"]

        # Cache the pipelines
        prefs["pipelines"] = pipelines
        prefs["pipeline_cache_updated"] = datetime.utcnow().isoformat()
        await self.save_preferences(prefs)

        return self.build_stage_map_from_cache(pipelines)

    def build_stage_map_from_cache(self, pipelines: List[dict]) -> Dict[str, str]:
        """Build stage_id → stage_label mapping from cached pipelines."""
        stage_map = {}

        for pipeline in pipelines:
            for stage in pipeline.get("stages", []):
                stage_id = stage.get("id")
                stage_label = stage.get("label")
                if stage_id and stage_label:
                    stage_map[stage_id] = stage_label

        return stage_map

    async def speak_deal_details(self, deal: dict, stage_map: Dict[str, str]):
        """Speak full details of a single deal."""
        props = deal.get("properties", {})

        # Extract fields
        deal_name = props.get("dealname", "Unknown deal")
        stage_id = props.get("dealstage", "")
        stage_label = stage_map.get(stage_id, stage_id)

        amount = props.get("amount")
        close_date = props.get("closedate", "")
        owner_id = props.get("hubspot_owner_id", "")

        # Format amount
        amount_text = self.format_currency(amount)

        # Format close date
        close_date_text = self.format_close_date(close_date)

        # Get owner name
        owner_name = await self.get_owner_name(owner_id)

        # Build response
        response = f"The {deal_name} deal is in {stage_label}."

        if amount_text:
            response += f" It's worth {amount_text}."

        if close_date_text:
            response += f" Close date: {close_date_text}."

        if owner_name:
            response += f" It's owned by {owner_name}."

        await self.capability_worker.speak(response)

        # Cache this result for follow-up
        await self.cache_recent_result("deal", [deal])

    async def speak_multiple_deals(
        self,
        deals: List[dict],
        stage_map: Dict[str, str]
    ):
        """Speak a list of deals and ask which one."""
        count = len(deals)

        response = f"I found {count} deals. "

        # List first 3
        for i, deal in enumerate(deals[:3]):
            props = deal.get("properties", {})
            deal_name = props.get("dealname", "Unknown")
            stage_id = props.get("dealstage", "")
            stage_label = stage_map.get(stage_id, "unknown stage")

            response += f"{deal_name} in {stage_label}. "

        if count > 3:
            response += f"And {count - 3} more. "

        response += "Which one?"

        await self.capability_worker.speak(response)

        # Cache all results for follow-up
        await self.cache_recent_result("deal", deals)

    def format_currency(self, amount: Optional[str]) -> str:
        """Format amount as currency for speaking."""
        if not amount:
            return ""

        try:
            amount_float = float(amount)

            # Round to nearest dollar
            amount_int = int(amount_float)

            # Format with commas
            if amount_int >= 1000000:
                # Millions
                millions = amount_int / 1000000
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

    def format_close_date(self, close_date: str) -> str:
        """Format close date for speaking."""
        if not close_date:
            return ""

        try:
            # Parse date (format: 2026-03-15)
            date_obj = datetime.fromisoformat(close_date.split("T")[0])

            # Format as "March 15th"
            month = date_obj.strftime("%B")
            day = date_obj.day

            # Add ordinal suffix
            if 10 <= day % 100 <= 20:
                suffix = "th"
            else:
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

            return f"{month} {day}{suffix}"

        except Exception:
            return close_date

    async def get_owner_name(self, owner_id: str) -> str:
        """Get owner name from cached owners list."""
        if not owner_id:
            return ""

        # Check cache first
        prefs = await self.get_preferences()

        # Check if cache is fresh
        cache_updated = prefs.get("owners_cache_updated")
        owners = prefs.get("owners", [])

        if cache_updated:
            cache_time = datetime.fromisoformat(cache_updated)
            age_minutes = (datetime.utcnow() - cache_time).total_seconds() / 60

            if age_minutes >= 30 or not owners:
                # Refresh cache
                owners = await self.fetch_owners()
                prefs["owners"] = owners
                prefs["owners_cache_updated"] = datetime.utcnow().isoformat()
                await self.save_preferences(prefs)
        else:
            # No cache, fetch fresh
            owners = await self.fetch_owners()
            prefs["owners"] = owners
            prefs["owners_cache_updated"] = datetime.utcnow().isoformat()
            await self.save_preferences(prefs)

        # Find owner by ID
        for owner in owners:
            if str(owner.get("id")) == str(owner_id):
                # Return first name only
                name = owner.get("name", "")
                return name.split()[0] if name else ""

        return ""

    async def fetch_owners(self) -> List[dict]:
        """Fetch owners from HubSpot API."""
        result = self._make_request(
            "GET",
            "/crm/v3/owners",
            self.API_TOKEN
        )

        if not result or "results" not in result:
            return []

        return [
            {
                "id": owner["id"],
                "name": f"{owner.get('firstName', '')} {owner.get('lastName', '')}".strip(),
                "email": owner.get("email", "")
            }
            for owner in result["results"]
        ]

    # --- MODE 3: LOG NOTE (FULLY IMPLEMENTED) ---
    async def log_note(self, command: str):
        """Log a note on a contact, company, or deal."""
        await self.capability_worker.speak("Logging a note...")

        # Parse the command to extract target and note content
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

        # Find the target record (try contact first, then company)
        target_record = await self.find_note_target(target_name)

        if not target_record:
            await self.capability_worker.speak(
                f"I couldn't find {target_name}. "
                "Make sure they exist in your HubSpot."
            )
            return

        # Create the note
        success = await self.create_note(
            note_content,
            target_record["type"],
            target_record["id"]
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
        """Parse note command to extract target and content using LLM."""
        prompt = (
            f"Parse this note command: '{command}'\n"
            "Extract the target (person/company name) and the note content.\n"
            "Return ONLY valid JSON with 'target' and 'content' fields.\n\n"
            "Examples:\n"
            "Input: 'log a note on Acme: they want to move forward'\n"
            "Output: {\"target\": \"Acme\", \"content\": \"they want to move forward\"}\n\n"
            "Input: 'add a note to Sarah Chen: she's interested in the enterprise plan'\n"
            "Output: {\"target\": \"Sarah Chen\", \"content\": \"she's interested in the enterprise plan\"}\n\n"
            "Input: 'note for TechCorp: follow up about pricing'\n"
            "Output: {\"target\": \"TechCorp\", \"content\": \"follow up about pricing\"}\n"
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

    async def find_note_target(self, target_name: str) -> Optional[dict]:
        """Find target record (contact or company) for the note."""
        # Try contact first
        contact = await self.search_contact_by_name(target_name)
        if contact:
            props = contact.get("properties", {})
            first_name = props.get("firstname", "")
            last_name = props.get("lastname", "")
            full_name = f"{first_name} {last_name}".strip()

            return {
                "type": "contact",
                "id": contact["id"],
                "name": full_name
            }

        # Try company
        company = await self.search_company_by_name(target_name)
        if company:
            props = company.get("properties", {})
            company_name = props.get("name", "")

            return {
                "type": "company",
                "id": company["id"],
                "name": company_name
            }

        return None

    async def search_contact_by_name(self, name: str) -> Optional[dict]:
        """Search for a contact by name (returns first match)."""
        self.worker.editor_logging_handler.info(
            f"Searching contacts for: {name}"
        )

        filters = self.build_contact_filters(name)

        search_data = {
            "filterGroups": filters,
            "properties": ["firstname", "lastname", "email"],
            "limit": 1
        }

        result = self._make_request(
            "POST",
            "/crm/v3/objects/contacts/search",
            self.API_TOKEN,
            search_data
        )

        if result and result.get("results"):
            self.worker.editor_logging_handler.info(
                f"Found contact: {result['results'][0].get('id')}"
            )
            return result["results"][0]

        self.worker.editor_logging_handler.info("No contact found")
        return None

    async def search_company_by_name(self, name: str) -> Optional[dict]:
        """Search for a company by name (returns first match)."""
        self.worker.editor_logging_handler.info(
            f"Searching companies for: {name}"
        )

        search_data = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "name",
                    "operator": "CONTAINS_TOKEN",
                    "value": name
                }]
            }],
            "properties": ["name", "domain"],
            "limit": 1
        }

        result = self._make_request(
            "POST",
            "/crm/v3/objects/companies/search",
            self.API_TOKEN,
            search_data
        )

        if result and result.get("results"):
            self.worker.editor_logging_handler.info(
                f"Found company: {result['results'][0].get('id')}"
            )
            return result["results"][0]

        self.worker.editor_logging_handler.info("No company found")
        return None

    async def create_note(
        self,
        note_body: str,
        target_type: str,
        target_id: str
    ) -> bool:
        """Create a note associated with a contact or company."""
        # Get current timestamp in UTC
        timestamp = datetime.utcnow().isoformat() + "Z"

        # Determine association type ID
        if target_type == "contact":
            association_type_id = self.ASSOCIATION_TYPES["note_to_contact"]
        elif target_type == "company":
            association_type_id = self.ASSOCIATION_TYPES["note_to_company"]
        elif target_type == "deal":
            association_type_id = self.ASSOCIATION_TYPES["note_to_deal"]
        else:
            return False

        # Build note data
        note_data = {
            "properties": {
                "hs_note_body": note_body,
                "hs_timestamp": timestamp
            },
            "associations": [{
                "to": {"id": target_id},
                "types": [{
                    "associationCategory": "HUBSPOT_DEFINED",
                    "associationTypeId": association_type_id
                }]
            }]
        }

        # Make API call
        result = self._make_request(
            "POST",
            "/crm/v3/objects/notes",
            self.API_TOKEN,
            note_data
        )

        if result:
            self.worker.editor_logging_handler.info(
                f"Note created successfully: {result.get('id')}"
            )
            return True

        return False

    # --- MODE 4: CREATE TASK (FULLY IMPLEMENTED) ---
    async def create_task(self, command: str):
        """Create a task associated with a contact, company, or deal."""
        await self.capability_worker.speak("Creating a task...")

        # Parse the command to extract task details
        parsed = await self.parse_task_command(command)

        if not parsed:
            await self.capability_worker.speak(
                "I didn't catch the task details. Try again?"
            )
            return

        subject = parsed.get("subject")
        due_date_text = parsed.get("due_date")
        priority = parsed.get("priority", "MEDIUM")
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
        due_timestamp = await self.parse_due_date(due_date_text)

        # Find target if specified
        target_record = None
        if target_name:
            target_record = await self.find_note_target(target_name)

        # Create the task
        success = await self.create_task_record(
            subject,
            due_timestamp,
            priority,
            target_record
        )

        if success:
            # Build response
            response = f"Done. I've created a task: {subject}"

            if due_date_text:
                response += f", due {due_date_text}"

            if priority != "MEDIUM":
                response += f", {priority.lower()} priority"

            if target_record:
                response += f", associated with {target_record['name']}"

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
            "Extract: subject, due_date (text), priority (NONE/LOW/MEDIUM/HIGH), and target (person/company).\n"
            "Return ONLY valid JSON.\n\n"
            "Examples:\n"
            "Input: 'create a task: send proposal to Acme by Friday'\n"
            "Output: {{\"subject\": \"send proposal to Acme\", \"due_date\": \"Friday\", \"priority\": \"MEDIUM\", \"target\": \"Acme\"}}\n\n"
            "Input: 'remind me to follow up with Sarah next Monday'\n"
            "Output: {{\"subject\": \"follow up with Sarah\", \"due_date\": \"next Monday\", \"priority\": \"MEDIUM\", \"target\": \"Sarah\"}}\n\n"
            "Input: 'task for Widget Co: schedule a demo, high priority'\n"
            "Output: {{\"subject\": \"schedule a demo\", \"due_date\": null, \"priority\": \"HIGH\", \"target\": \"Widget Co\"}}\n\n"
            "Input: 'create task: call the client tomorrow'\n"
            "Output: {{\"subject\": \"call the client\", \"due_date\": \"tomorrow\", \"priority\": \"MEDIUM\", \"target\": null}}\n"
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

    async def parse_due_date(self, date_text: Optional[str]) -> str:
        """Parse natural language date to ISO 8601 UTC timestamp."""
        if not date_text:
            # Default to tomorrow at 9am
            tomorrow = datetime.now() + timedelta(days=1)
            tomorrow = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
            return tomorrow.isoformat() + "Z"

        date_lower = date_text.lower()
        now = datetime.now()

        # Handle common cases
        if "tomorrow" in date_lower:
            target = now + timedelta(days=1)
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)

        elif "today" in date_lower:
            target = now.replace(hour=17, minute=0, second=0, microsecond=0)

        elif "monday" in date_lower:
            # Next Monday
            days_ahead = 0 - now.weekday()  # Monday is 0
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)

        elif "tuesday" in date_lower:
            days_ahead = 1 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)

        elif "wednesday" in date_lower:
            days_ahead = 2 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)

        elif "thursday" in date_lower:
            days_ahead = 3 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)

        elif "friday" in date_lower:
            days_ahead = 4 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)

            # Friday at 5pm
            target = target.replace(hour=17, minute=0, second=0, microsecond=0)

        elif "saturday" in date_lower:
            days_ahead = 5 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)

        elif "sunday" in date_lower:
            days_ahead = 6 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)

        else:
            # Default to tomorrow at 9am
            target = now + timedelta(days=1)
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)

        # Convert to UTC ISO 8601
        return target.isoformat() + "Z"

    async def create_task_record(
        self,
        subject: str,
        timestamp: str,
        priority: str,
        target_record: Optional[dict] = None
    ) -> bool:
        """Create a task in HubSpot."""
        # Build task data
        task_data = {
            "properties": {
                "hs_task_subject": subject,
                "hs_task_body": "Voice-created via OpenHome",
                "hs_timestamp": timestamp,
                "hs_task_status": "NOT_STARTED",
                "hs_task_priority": priority,
                "hs_task_type": "TODO"
            }
        }

        # Add association if target specified
        if target_record:
            # Determine association type
            if target_record["type"] == "contact":
                assoc_type_id = self.ASSOCIATION_TYPES["task_to_contact"]
            elif target_record["type"] == "company":
                assoc_type_id = self.ASSOCIATION_TYPES["task_to_company"]
            elif target_record["type"] == "deal":
                assoc_type_id = self.ASSOCIATION_TYPES["task_to_deal"]
            else:
                assoc_type_id = None

            if assoc_type_id:
                task_data["associations"] = [{
                    "to": {"id": target_record["id"]},
                    "types": [{
                        "associationCategory": "HUBSPOT_DEFINED",
                        "associationTypeId": assoc_type_id
                    }]
                }]

        # Make API call
        result = self._make_request(
            "POST",
            "/crm/v3/objects/tasks",
            self.API_TOKEN,
            task_data
        )

        if result:
            self.worker.editor_logging_handler.info(
                f"Task created successfully: {result.get('id')}"
            )
            return True

        return False

    # --- MODE 5: PIPELINE SUMMARY (FULLY IMPLEMENTED) ---
    async def pipeline_summary(self):
        """Get summary of open deals by stage."""
        await self.capability_worker.speak("Getting your pipeline summary...")

        # Fetch pipeline stages
        stage_map = await self.get_stage_map()

        if not stage_map:
            await self.capability_worker.speak(
                "I had trouble loading your pipeline stages."
            )
            return

        # Fetch all open deals
        deals = await self.fetch_open_deals()

        if not deals:
            await self.capability_worker.speak(
                "You don't have any open deals in your pipeline right now."
            )
            return

        # Group deals by stage
        stage_groups = self.group_deals_by_stage(deals, stage_map)

        # Calculate totals
        total_deals = len(deals)
        total_value = sum(
            float(deal.get("properties", {}).get("amount", 0) or 0)
            for deal in deals
        )

        # Build and speak response
        await self.speak_pipeline_summary(
            stage_groups,
            total_deals,
            total_value
        )

    async def fetch_open_deals(self) -> List[dict]:
        """Fetch all open deals (excluding closed won/lost)."""
        all_deals = []
        after = None

        while True:
            # Build search query
            search_data = {
                "filterGroups": [{
                    "filters": [{
                        "propertyName": "dealstage",
                        "operator": "NOT_IN",
                        "values": ["closedwon", "closedlost"]
                    }]
                }],
                "properties": ["dealname", "dealstage", "pipeline", "amount"],
                "limit": 100
            }

            # Add pagination if needed
            if after:
                search_data["after"] = after

            # Make API call
            result = self._make_request(
                "POST",
                "/crm/v3/objects/deals/search",
                self.API_TOKEN,
                search_data
            )

            if not result:
                break

            # Add results
            deals = result.get("results", [])
            all_deals.extend(deals)

            # Check for more pages
            paging = result.get("paging", {})
            next_page = paging.get("next", {})
            after = next_page.get("after")

            if not after:
                break

        self.worker.editor_logging_handler.info(
            f"Fetched {len(all_deals)} open deals"
        )

        return all_deals

    def group_deals_by_stage(
        self,
        deals: List[dict],
        stage_map: Dict[str, str]
    ) -> Dict[str, List[dict]]:
        """Group deals by stage and calculate totals per stage."""
        groups = {}

        for deal in deals:
            props = deal.get("properties", {})
            stage_id = props.get("dealstage", "unknown")
            stage_label = stage_map.get(stage_id, stage_id)

            if stage_label not in groups:
                groups[stage_label] = []

            groups[stage_label].append(deal)

        return groups

    async def speak_pipeline_summary(
        self,
        stage_groups: Dict[str, List[dict]],
        total_deals: int,
        total_value: float
    ):
        """Speak the pipeline summary."""
        # Format total value
        total_text = self.format_currency(str(total_value))

        # Start with overview
        response = f"Here's your pipeline. You have {total_deals} open deals"

        if total_text:
            response += f" worth {total_text} total"

        response += ". "

        # Sort stages by deal count (descending)
        sorted_stages = sorted(
            stage_groups.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )

        # Speak top 6 stages
        stages_to_speak = sorted_stages[:6]

        for stage_label, stage_deals in stages_to_speak:
            count = len(stage_deals)

            # Calculate stage value
            stage_value = sum(
                float(deal.get("properties", {}).get("amount", 0) or 0)
                for deal in stage_deals
            )
            stage_value_text = self.format_currency(str(stage_value))

            # Build stage summary
            if count == 1:
                response += f"{count} deal in {stage_label}"
            else:
                response += f"{count} deals in {stage_label}"

            if stage_value_text:
                response += f" worth {stage_value_text}"

            response += ". "

        # If more than 6 stages, mention remaining
        if len(sorted_stages) > 6:
            remaining = len(sorted_stages) - 6
            response += f"Plus {remaining} more in earlier stages."

        await self.capability_worker.speak(response)

    # --- MODE 6: MOVE DEAL STAGE (FULLY IMPLEMENTED) ---
    async def move_deal_stage(self, command: str):
        """Move a deal to a different stage with confirmation."""
        await self.capability_worker.speak("Updating deal stage...")

        # Parse command to extract deal name and target stage
        parsed = await self.parse_move_deal_command(command)

        if not parsed:
            await self.capability_worker.speak(
                "I didn't catch which deal or stage. Try again?"
            )
            return

        deal_name = parsed.get("deal_name")
        target_stage_text = parsed.get("target_stage")

        if not deal_name or not target_stage_text:
            await self.capability_worker.speak(
                "I need both the deal name and the target stage."
            )
            return

        self.worker.editor_logging_handler.info(
            f"Moving deal '{deal_name}' to '{target_stage_text}'"
        )

        # Find the deal
        deal = await self.search_deal_by_name(deal_name)

        if not deal:
            await self.capability_worker.speak(
                f"I couldn't find a deal matching {deal_name}."
            )
            return

        # Get pipeline stages
        stage_map = await self.get_stage_map()
        reverse_map = self.build_reverse_stage_map(stage_map)

        # Get current stage
        current_stage_id = deal.get("properties", {}).get("dealstage", "")
        current_stage_label = stage_map.get(current_stage_id, "unknown")

        # Match target stage
        target_stage_id = await self.match_stage_name(
            target_stage_text,
            reverse_map,
            stage_map
        )

        if not target_stage_id:
            # Couldn't match - list available stages
            stage_list = ", ".join(stage_map.values())
            await self.capability_worker.speak(
                f"I'm not sure which stage you mean. "
                f"Your pipeline stages are: {stage_list}. Which one?"
            )
            return

        target_stage_label = stage_map.get(target_stage_id, target_stage_id)

        # Get deal name for confirmation
        deal_display_name = deal.get("properties", {}).get("dealname", "the deal")

        # CRITICAL: Confirm before updating
        await self.capability_worker.speak(
            f"I'll move the {deal_display_name} deal from {current_stage_label} "
            f"to {target_stage_label}. Confirm?"
        )

        confirmation = await self.capability_worker.run_io_loop(
            "Say yes to confirm or no to cancel."
        )

        if not confirmation or not self.is_yes(confirmation):
            await self.capability_worker.speak("Cancelled. The deal was not updated.")
            return

        # Update the deal
        success = await self.update_deal_stage(deal["id"], target_stage_id)

        if success:
            await self.capability_worker.speak(
                f"Done. I've moved {deal_display_name} to {target_stage_label}."
            )
        else:
            await self.capability_worker.speak(
                "I had trouble updating the deal. Please try again."
            )

    async def parse_move_deal_command(self, command: str) -> Optional[dict]:
        """Parse move deal command using LLM."""
        prompt = (
            f"Parse this deal stage update command: '{command}'\n"
            "Extract the deal name and the target stage.\n"
            "Return ONLY valid JSON.\n\n"
            "Examples:\n"
            "Input: 'move the Acme deal to contract sent'\n"
            "Output: {{\"deal_name\": \"Acme\", \"target_stage\": \"contract sent\"}}\n\n"
            "Input: 'update Widget Co to closed won'\n"
            "Output: {{\"deal_name\": \"Widget Co\", \"target_stage\": \"closed won\"}}\n\n"
            "Input: 'mark Acme as closed lost'\n"
            "Output: {{\"deal_name\": \"Acme\", \"target_stage\": \"closed lost\"}}\n\n"
            "Input: 'change TechCorp deal to presentation scheduled'\n"
            "Output: {{\"deal_name\": \"TechCorp\", \"target_stage\": \"presentation scheduled\"}}\n"
        )

        response = self.capability_worker.text_to_text_response(prompt).strip()

        # Clean markdown fences
        response = response.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(response)
            return parsed
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Failed to parse move deal command: {e}"
            )
            return None

    async def search_deal_by_name(self, name: str) -> Optional[dict]:
        """Search for a deal by name (returns first match)."""
        search_data = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "dealname",
                    "operator": "CONTAINS_TOKEN",
                    "value": name
                }]
            }],
            "properties": ["dealname", "dealstage", "amount"],
            "limit": 1
        }

        result = self._make_request(
            "POST",
            "/crm/v3/objects/deals/search",
            self.API_TOKEN,
            search_data
        )

        if result and result.get("results"):
            return result["results"][0]

        return None

    def build_reverse_stage_map(
        self,
        stage_map: Dict[str, str]
    ) -> Dict[str, str]:
        """Build reverse map: stage_label_lower → stage_id."""
        reverse = {}

        for stage_id, stage_label in stage_map.items():
            # Normalize label to lowercase
            label_lower = stage_label.lower()
            reverse[label_lower] = stage_id

        return reverse

    async def match_stage_name(
        self,
        target_text: str,
        reverse_map: Dict[str, str],
        stage_map: Dict[str, str]
    ) -> Optional[str]:
        """Match natural language stage name to stage ID."""
        target_lower = target_text.lower().strip()

        # Direct match
        if target_lower in reverse_map:
            return reverse_map[target_lower]

        # Common aliases (including speech recognition errors)
        aliases = {
            "won": "closed won",
            "one": "closed won",  # Speech recognition: "won" → "one"
            "we won it": "closed won",
            "lost": "closed lost",
            "dead": "closed lost",
            "we lost it": "closed lost",
            "contract": "contract sent",
            "presentation": "presentation scheduled",
            "demo": "presentation scheduled",
            "appointment": "appointment scheduled",
            "qualified": "qualified to buy",
            "decision maker": "decision maker bought-in"
        }

        if target_lower in aliases:
            canonical = aliases[target_lower]
            if canonical in reverse_map:
                return reverse_map[canonical]

        # Also check for "closed one" → "closed won"
        if "closed one" in target_lower:
            if "closed won" in reverse_map:
                return reverse_map["closed won"]

        # Partial match (fuzzy)
        for label_lower, stage_id in reverse_map.items():
            if target_lower in label_lower or label_lower in target_lower:
                return stage_id

        return None

    async def update_deal_stage(self, deal_id: str, stage_id: str) -> bool:
        """Update deal stage via API."""
        update_data = {
            "properties": {
                "dealstage": stage_id
            }
        }

        result = self._make_request(
            "PATCH",
            f"/crm/v3/objects/deals/{deal_id}",
            self.API_TOKEN,
            update_data
        )

        if result:
            self.worker.editor_logging_handler.info(
                f"Deal stage updated successfully: {deal_id} → {stage_id}"
            )
            return True

        return False

    def is_yes(self, text: str) -> bool:
        """Check if user said yes."""
        yes_words = ["yes", "yeah", "yep", "sure", "confirm", "ok", "okay", "yup"]
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

    # --- API HELPERS ---
    def _make_request(
        self,
        method: str,
        endpoint: str,
        token: str,
        data: Optional[dict] = None
    ) -> Optional[dict]:
        """Make HTTP request to HubSpot API."""
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
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
            else:
                return None

            if response.status_code == 401:
                self.worker.editor_logging_handler.error(
                    "HubSpot API: 401 Unauthorized"
                )
                return None
            elif response.status_code == 403:
                self.worker.editor_logging_handler.error(
                    "HubSpot API: 403 Forbidden"
                )
                return None
            elif response.status_code == 404:
                return None
            elif response.status_code == 429:
                self.worker.editor_logging_handler.warning(
                    "HubSpot API: 429 Rate Limited"
                )
                return None
            elif response.status_code >= 400:
                self.worker.editor_logging_handler.error(
                    f"HubSpot API: {response.status_code}"
                )
                return None

            return response.json()

        except Exception as e:
            self.worker.editor_logging_handler.error(f"HubSpot API error: {e}")
            return None
