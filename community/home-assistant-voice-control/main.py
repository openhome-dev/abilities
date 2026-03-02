"""
OpenHome Ability: Home Assistant Voice Control

Voice-controlled interface for Home Assistant via REST API.
Supports lights, switches, covers, sensors, sirens, media players, and shopping lists.
LLM-based intent classification with fuzzy entity name matching.
"""

import json
import os
import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# ─── Configuration ───────────────────────────────────────────────────────────
# Load from .env file alongside main.py, or set environment variables:
#   HA_TOKEN - Long-Lived Access Token (generate at http://YOUR_HA_IP:8123/profile)
#   HA_URL   - Home Assistant base URL
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

HA_TOKEN = os.environ.get("HA_TOKEN", "YOUR_HOME_ASSISTANT_TOKEN_HERE")
HA_URL = os.environ.get("HA_URL", "http://192.168.68.60:8123")

ACTIONABLE_DOMAINS = [
    "light", "switch", "cover", "media_player",
    "siren", "binary_sensor", "sensor", "todo",
]

# Actions requiring voice confirmation before execution
DANGEROUS_ACTIONS = {"open_cover", "close_cover", "activate_siren", "deactivate_siren"}

EXIT_WORDS = ["done", "stop", "exit", "quit", "nevermind", "never mind", "goodbye", "bye", "that's all"]

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
- unknown → user request doesn't match any smart home action

Fuzzy match entity names. "The floodlight" matches light.camera_1_floodlight. "Front door" matches binary_sensor.front_door_motion. Pick the best match from the entity list.

For check_state, read the entity state from the list and include it in spoken_response.
For unknown, set entity_id to "" and spoken_response to a helpful message."""


class HomeAssistantAbility(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # ─── Core Logic ──────────────────────────────────────────────────────

    async def run(self):
        try:
            # Fetch entities from HA
            entities = self._fetch_entities()
            if entities is None:
                await self.capability_worker.speak(
                    "I couldn't connect to Home Assistant. Please check the connection and try again."
                )
                return

            # Build compact registry for LLM prompt
            registry = self._build_registry(entities)
            entity_count = sum(len(v) for v in registry.values())

            if entity_count == 0:
                await self.capability_worker.speak(
                    "I connected to Home Assistant but found no controllable devices."
                )
                return

            # Greet
            await self.capability_worker.speak(
                f"Home Assistant connected. I found {entity_count} devices across "
                f"{len(registry)} categories. What would you like to do?"
            )

            # Main conversation loop
            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak("I didn't catch that. Could you repeat?")
                    continue

                # Check for exit
                if any(word in user_input.lower() for word in EXIT_WORDS):
                    await self.capability_worker.speak("Home Assistant control ended. Have a good one.")
                    break

                # Classify intent via LLM
                intent = self._classify_intent(user_input, registry)

                if intent is None:
                    await self.capability_worker.speak(
                        "I had trouble understanding that. Could you try rephrasing?"
                    )
                    continue

                action = intent.get("action", "unknown")
                entity_id = intent.get("entity_id", "")
                service_data = intent.get("service_data", {})
                spoken = intent.get("spoken_response", "Done.")

                # Handle unknown
                if action == "unknown":
                    await self.capability_worker.speak(spoken)
                    continue

                # Handle state checks (no API call needed)
                if action == "check_state":
                    await self.capability_worker.speak(spoken)
                    continue

                # Safety confirmation for dangerous actions
                if action in DANGEROUS_ACTIONS:
                    confirmed = await self.capability_worker.run_confirmation_loop(
                        f"Are you sure you want to {spoken.rstrip('.').lower()}?"
                    )
                    if not confirmed:
                        await self.capability_worker.speak("Cancelled.")
                        continue

                # Execute the action
                success = self._execute_action(action, entity_id, service_data)

                if success:
                    await self.capability_worker.speak(spoken)
                else:
                    await self.capability_worker.speak(
                        f"Sorry, I couldn't complete that action. Please check Home Assistant."
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
                lines = json_str.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                json_str = "\n".join(lines).strip()

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
