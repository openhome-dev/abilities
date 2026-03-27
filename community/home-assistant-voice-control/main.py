"""
OpenHome Ability: Home Assistant Voice Control

Voice-controlled interface for Home Assistant via REST API.
Supports lights, switches, covers, sensors, sirens, media players, and shopping lists.
LLM-based intent classification with fuzzy entity name matching.
"""

import json
import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# ─── Configuration ───────────────────────────────────────────────────────────
# Set these environment variables before running:
#   HA_TOKEN - Long-Lived Access Token (generate at http://YOUR_HA_IP:8123/profile)
#   HA_URL   - Home Assistant base URL (e.g. http://192.168.1.100:8123)
HA_TOKEN = "YOUR_HOME_ASSISTANT_TOKEN_HERE"
HA_URL = "http://YOUR_HA_IP:8123"

ACTIONABLE_DOMAINS = [
    "light", "switch", "cover", "media_player",
    "siren", "binary_sensor", "sensor", "todo",
]

# Actions requiring voice confirmation before execution
DANGEROUS_ACTIONS = {"open_cover", "close_cover", "activate_siren", "deactivate_siren"}

CONFIRMATION_SYSTEM_PROMPT = """You are a voice assistant interpreting a user's response to a yes/no confirmation question.
The user was asked to confirm a smart home action. Determine if they said yes or no.

Return ONLY a JSON object (no markdown, no explanation):
{"confirmed": true/false, "spoken_response": "<short response>"}

- confirmed: true if the user is agreeing, affirming, or saying yes in any way.
- confirmed: false if the user is declining, refusing, cancelling, or saying no in any way.

Examples of YES: "yeah", "yep", "sure", "do it", "go ahead", "go for it", "uh huh", "why not", "absolutely", "please", "sounds good", "that's fine", "yes please", "mm hmm", "hit it"
Examples of NO: "no", "nah", "nope", "cancel", "don't", "stop", "never mind", "forget it", "hold on", "wait", "not right now", "actually no", "scratch that", "back out"

SPOKEN RESPONSE RULES:
The spoken_response will be read aloud by a text-to-speech engine. Use plain spoken English only. No markdown, no emojis, no special characters. Keep it under 6 words.
- If confirmed, spoken_response should be empty string "" (the action result will be spoken separately).
- If not confirmed, use a short acknowledgement like "Okay, cancelled." or "No problem."."""

INTENT_SYSTEM_PROMPT = """You are a Home Assistant voice controller. Given a user command and entity list, return ONLY a JSON object (no markdown, no explanation).

JSON format:
{"action": "<action>", "entity_id": "<entity_id>", "service_data": {}, "spoken_response": "<natural speech>"}

Valid actions:
- turn_on / turn_off / toggle → service: homeassistant/turn_on, turn_off, toggle
- open_cover / close_cover → service: cover/open_cover, cover/close_cover
- activate_siren → service: siren/turn_on
- deactivate_siren → service: siren/turn_off
- check_state → no API call, just read cached state and report
- add_shopping → service: todo/add_item (use service_data: {"item": "<item>"}, entity_id: the todo list entity)
- exit → user wants to stop, leave, end the session, or says they are done
- unknown → user request doesn't match any smart home action

Fuzzy match entity names. "The floodlight" matches light.camera_1_floodlight. "Front door" matches binary_sensor.front_door_motion. Pick the best match from the entity list.

For check_state, read the entity state from the list and include it in spoken_response.
For exit, set entity_id to "" and spoken_response to a short goodbye like "See ya."
For unknown, set entity_id to "" and spoken_response to a helpful message.

SPOKEN RESPONSE RULES:
The spoken_response will be read aloud by a text-to-speech engine on a smart speaker. You must follow these rules strictly:
- Use plain spoken English only. No markdown, no asterisks, no bullet points, no numbered lists, no emojis, no URLs, no special characters, no stage directions.
- Keep confirmations and acknowledgements under 10 words (e.g. "Kitchen light is off.").
- Keep state check responses to 1-2 short sentences, under 15 words total.
- Keep unknown/help responses to 1-2 short sentences, under 20 words total.

Examples of natural spoken commands and their JSON output:

User: "Hey kill the kitchen lights"
{"action": "turn_off", "entity_id": "light.kitchen", "service_data": {}, "spoken_response": "Kitchen lights are off."}

User: "What's the garage door doing"
{"action": "check_state", "entity_id": "cover.garage_door", "service_data": {}, "spoken_response": "The garage door is closed."}

User: "Throw some milk on the shopping list"
{"action": "add_shopping", "entity_id": "todo.shopping_list", "service_data": {"item": "milk"}, "spoken_response": "Added milk to the list."}

User: "I'm done here"
{"action": "exit", "entity_id": "", "service_data": {}, "spoken_response": "See ya."}

User: "Flip on the porch light"
{"action": "turn_on", "entity_id": "light.porch", "service_data": {}, "spoken_response": "Porch light is on."}"""


class HomeAssistantAbility(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # ─── Core Logic ──────────────────────────────────────────────────────

    async def run(self):
        try:
            # Validate configuration: token must be non-empty and URL must start with http
            if not HA_TOKEN or not HA_URL or not HA_URL.startswith("http"):
                await self.capability_worker.speak(
                    "This ability isn't configured yet."
                )
                return

            # Fetch entities from HA
            entities = self._fetch_entities()
            if entities is None:
                await self.capability_worker.speak(
                    "Couldn't reach your smart home. Check your connection and try again."
                )
                return

            # Build compact registry for LLM prompt
            registry = self._build_registry(entities)
            entity_count = sum(len(v) for v in registry.values())

            if entity_count == 0:
                await self.capability_worker.speak(
                    "Connected, but I didn't find any controllable devices."
                )
                return

            # Greet
            await self.capability_worker.speak(
                "Connected. What would you like to do?"
            )

            # Main conversation loop
            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak("Didn't catch that — go ahead.")
                    continue

                # Classify intent via LLM
                intent = self._classify_intent(user_input, registry)

                if intent is None:
                    await self.capability_worker.speak(
                        "Not sure what you mean — try saying it differently."
                    )
                    continue

                action = intent.get("action", "unknown")
                entity_id = intent.get("entity_id", "")
                service_data = intent.get("service_data", {})
                spoken = intent.get("spoken_response", "Done.")

                # Handle exit detected by LLM
                if action == "exit":
                    await self.capability_worker.speak(spoken)
                    break

                # Handle unknown
                if action == "unknown":
                    await self.capability_worker.speak(spoken)
                    continue

                # Handle state checks (no API call needed)
                if action == "check_state":
                    await self.capability_worker.speak(spoken)
                    continue

                # Safety confirmation for dangerous actions (LLM-classified)
                if action in DANGEROUS_ACTIONS:
                    await self.capability_worker.speak(
                        f"Just to confirm, you want to {spoken.rstrip('.').lower()}?"
                    )
                    confirm_input = await self.capability_worker.user_response()
                    if not confirm_input or not confirm_input.strip():
                        await self.capability_worker.speak("I didn't hear a response. Cancelling.")
                        continue
                    confirmed = self._classify_confirmation(confirm_input)
                    if not confirmed:
                        continue

                # Execute the action
                success = self._execute_action(action, entity_id, service_data)

                if success:
                    await self.capability_worker.speak(spoken)
                else:
                    await self.capability_worker.speak(
                        "Couldn't do that — the device might be unavailable."
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[HomeAssistant] Unexpected error: {e}")
            await self.capability_worker.speak("Something went wrong with Home Assistant control.")
        finally:
            self.capability_worker.resume_normal_flow()

    # ─── HA API Methods ──────────────────────────────────────────────────

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        }

    def _fetch_entities(self):
        """Fetch all entity states from HA REST API."""
        try:
            response = requests.get(
                f"{HA_URL}/api/states",
                headers=self._get_headers(),
                timeout=10,
            )
            if response.status_code == 200:
                return response.json()
            else:
                self.worker.editor_logging_handler.error(
                    f"[HomeAssistant] HA API returned {response.status_code}: {response.text[:200]}"
                )
                return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[HomeAssistant] Connection error: {e}")
            return None

    def _build_registry(self, entities):
        """Filter entities to actionable domains and build compact registry."""
        registry = {}
        for entity in entities:
            entity_id = entity.get("entity_id", "")
            domain = entity_id.split(".")[0] if "." in entity_id else ""

            if domain not in ACTIONABLE_DOMAINS:
                continue

            friendly_name = entity.get("attributes", {}).get("friendly_name", entity_id)
            state = entity.get("state", "unknown")

            if domain not in registry:
                registry[domain] = []

            registry[domain].append({
                "id": entity_id,
                "name": friendly_name,
                "state": state,
            })

        return registry

    def _classify_intent(self, user_input, registry):
        """Use LLM to classify user intent and match entities."""
        # Build compact entity list for the prompt
        entity_lines = []
        for domain, entities in registry.items():
            for e in entities:
                entity_lines.append(f"  {e['id']} | {e['name']} | state: {e['state']}")

        entity_text = "\n".join(entity_lines)

        prompt = (
            f"ENTITY LIST:\n{entity_text}\n\n"
            f"USER COMMAND: \"{user_input}\"\n\n"
            "Return the JSON object for this command."
        )

        try:
            raw = self.capability_worker.text_to_text_response(
                prompt=prompt,
                history=[],
                system_prompt=INTENT_SYSTEM_PROMPT,
            )

            self.worker.editor_logging_handler.info(f"[HomeAssistant] LLM raw: {raw[:300]}")

            # Parse JSON from response (handle markdown fences)
            json_str = raw.strip()
            if json_str.startswith("```"):
                # Strip markdown code fences
                parts = json_str.split("\n")
                parts = [p for p in parts if not p.strip().startswith("```")]
                json_str = "\n".join(parts).strip()

            intent = json.loads(json_str)
            return intent

        except json.JSONDecodeError as e:
            self.worker.editor_logging_handler.error(
                f"[HomeAssistant] JSON parse error: {e}, raw: {raw[:200]}"
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[HomeAssistant] LLM error: {e}")
            return None

    def _classify_confirmation(self, user_input):
        """Use LLM to classify a yes/no confirmation response."""
        prompt = (
            f"The user was asked to confirm a smart home action.\n"
            f"USER RESPONSE: \"{user_input}\"\n\n"
            "Return the JSON object."
        )

        try:
            raw = self.capability_worker.text_to_text_response(
                prompt=prompt,
                history=[],
                system_prompt=CONFIRMATION_SYSTEM_PROMPT,
            )

            json_str = raw.strip()
            if json_str.startswith("```"):
                parts = json_str.split("\n")
                parts = [p for p in parts if not p.strip().startswith("```")]
                json_str = "\n".join(parts).strip()

            result = json.loads(json_str)
            spoken = result.get("spoken_response", "")
            if spoken:
                self.worker.session_tasks.create(self.capability_worker.speak(spoken))
            return result.get("confirmed", False)

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[HomeAssistant] Confirmation parse error: {e}"
            )
            self.worker.session_tasks.create(
                self.capability_worker.speak("I couldn't tell. Cancelling to be safe.")
            )
            return False

    def _execute_action(self, action, entity_id, service_data):
        """Execute a Home Assistant service call."""
        # Map actions to HA service endpoints
        service_map = {
            "turn_on": "homeassistant/turn_on",
            "turn_off": "homeassistant/turn_off",
            "toggle": "homeassistant/toggle",
            "open_cover": "cover/open_cover",
            "close_cover": "cover/close_cover",
            "activate_siren": "siren/turn_on",
            "deactivate_siren": "siren/turn_off",
            "add_shopping": "todo/add_item",
        }

        service = service_map.get(action)
        if not service:
            self.worker.editor_logging_handler.error(
                f"[HomeAssistant] Unknown action: {action}"
            )
            return False

        payload = {"entity_id": entity_id}
        if service_data:
            payload.update(service_data)

        try:
            response = requests.post(
                f"{HA_URL}/api/services/{service}",
                headers=self._get_headers(),
                json=payload,
                timeout=10,
            )

            if response.status_code in (200, 201):
                self.worker.editor_logging_handler.info(
                    f"[HomeAssistant] Executed {service} on {entity_id}"
                )
                return True
            else:
                self.worker.editor_logging_handler.error(
                    f"[HomeAssistant] Service call failed {response.status_code}: {response.text[:200]}"
                )
                return False

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[HomeAssistant] Service call error: {e}"
            )
            return False
