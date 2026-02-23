import asyncio
import json
import os
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# HOME ASSISTANT CONTROLLER
# Phase 0: Load config, validate HA connection.
# Phase 1: Fetch entities, parse one voice command (lights), call service, confirm.
# =============================================================================

HA_CONFIG_FILE = "ha_config.json"

# Domains we care about for voice control (Phase 1 focuses on lights; list for entity summary)
CONTROLLABLE_DOMAINS = [
    "light",
    "switch",
    "climate",
    "lock",
    "cover",
    "fan",
    "scene",
    "script",
    "media_player",
    "input_boolean",
    "vacuum",
    "alarm_control_panel",
]
QUERYABLE_DOMAINS = CONTROLLABLE_DOMAINS + [
    "sensor",
    "binary_sensor",
    "weather",
    "person",
]

PARSE_COMMAND_PROMPT = """You are a Home Assistant API translator.
Convert the user's voice command into a Home Assistant service call.

Available entities:
{entity_summary}

Return ONLY a JSON object (no markdown, no explanation):
{{
    "entity_id": "the exact entity_id from the list above, or null if no match",
    "domain": "light",
    "service": "turn_on or turn_off",
    "service_data": {{}},
    "spoken_confirmation": "short phrase to say after executing, e.g. 'Living room lights are off.'"
}}

Rules:
- entity_id MUST exactly match one from the available entities list. Do not invent entity IDs.
- If the user says a room or device name, match it to the entity with that in its friendly_name or entity_id.
- For Phase 1 only support lights: domain must be "light", service "turn_on" or "turn_off". service_data can be empty or {{"brightness": 0-255}} for dimming.
- If you cannot match the command to any light entity, return {{"entity_id": null, "spoken_confirmation": ""}}.
- spoken_confirmation should be one short sentence.

User's command: {user_input}
"""


class HomeAssistantControllerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        """Registers the capability and loads hotwords from config.json."""
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

    def ha_request(
        self, config: dict, method: str, endpoint: str, json_body: dict = None
    ):
        """Make an authenticated request to Home Assistant REST API."""
        url = f"{config['ha_url'].rstrip('/')}/api{endpoint}"
        headers = {
            "Authorization": f"Bearer {config['ha_token']}",
            "Content-Type": "application/json",
        }
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(
                    url, headers=headers, json=json_body or {}, timeout=10
                )
            else:
                return None
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                self.worker.editor_logging_handler.error(
                    "HA auth failed — invalid token"
                )
                return None
            else:
                self.worker.editor_logging_handler.error(
                    f"HA error {response.status_code}: {response.text}"
                )
                return None
        except requests.exceptions.ConnectionError:
            self.worker.editor_logging_handler.error(
                "Cannot reach Home Assistant"
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"HA request failed: {e}")
            return None

    def ha_check_connection(self, config: dict) -> bool:
        """Test if Home Assistant is reachable and token is valid."""
        result = self.ha_request(config, "GET", "/")
        return result is not None and "message" in result

    def ha_get_states(self, config: dict) -> list:
        """Fetch all entity states from Home Assistant."""
        result = self.ha_request(config, "GET", "/states")
        if result and isinstance(result, list):
            return result
        return []

    def ha_call_service(
        self, config: dict, domain: str, service: str, service_data: dict = None
    ) -> bool:
        """Call a Home Assistant service to control a device."""
        result = self.ha_request(
            config, "POST", f"/services/{domain}/{service}", service_data or {}
        )
        return result is not None

    def build_entity_summary(self, entities: list, config: dict) -> str:
        """Build a compact entity summary for LLM prompts."""
        lines = []
        aliases = (config or {}).get("aliases") or {}
        for entity in entities:
            eid = entity.get("entity_id", "")
            if not eid:
                continue
            domain = eid.split(".")[0]
            if domain not in QUERYABLE_DOMAINS:
                continue
            friendly_name = (
                entity.get("attributes") or {}
            ).get("friendly_name", eid)
            state = entity.get("state", "unknown")
            alias = aliases.get(eid, "")
            alias_str = f" (alias: {alias})" if alias else ""
            lines.append(f"- {eid} | {friendly_name}{alias_str} | state: {state}")
        return "\n".join(lines) if lines else "(no entities)"

    def get_trigger_context(self) -> str:
        """Get the user's message that triggered the ability (last user message in history)."""
        try:
            if not hasattr(self.worker.agent_memory, "full_message_history"):
                return ""
            history = self.worker.agent_memory.full_message_history
            if not history:
                return ""
            last_msg = history[-1]
            if isinstance(last_msg, dict):
                if last_msg.get("role") == "user":
                    return (last_msg.get("content") or "").strip()
            elif hasattr(last_msg, "role") and last_msg.role == "user":
                content = last_msg.content if hasattr(last_msg, "content") else None
                return (content or "").strip()
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Error reading trigger context: {e}"
            )
        return ""

    def parse_single_command(
        self, user_input: str, entity_summary: str
    ) -> dict | None:
        """Use LLM to parse user command into entity_id, domain, service, service_data, spoken_confirmation."""
        if not user_input:
            return None
        if not entity_summary:
            return None
        prompt = PARSE_COMMAND_PROMPT.format(
            entity_summary=entity_summary,
            user_input=user_input,
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            if not raw:
                return None
            clean = (
                raw.replace("```json", "")
                .replace("```", "")
                .strip()
            )
            return json.loads(clean)
        except json.JSONDecodeError as e:
            self.worker.editor_logging_handler.error(
                f"LLM returned invalid JSON: {e}"
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Parse command error: {e}")
            return None

    async def run(self):
        try:
            # Load ha_config.json via file storage API (use local vars; platform disallows extra fields on capability)
            exists = await self.capability_worker.check_if_file_exists(
                HA_CONFIG_FILE, False
            )
            if not exists:
                await self.capability_worker.speak(
                    "Home Assistant isn't configured yet. "
                    "Ask your developer to set up the connection in the config file."
                )
                self.capability_worker.resume_normal_flow()
                return

            content = await self.capability_worker.read_file(
                HA_CONFIG_FILE, False
            )
            try:
                config = json.loads(content)
            except json.JSONDecodeError as e:
                self.worker.editor_logging_handler.error(
                    f"Invalid ha_config.json: {e}"
                )
                await self.capability_worker.speak(
                    "Home Assistant config is invalid. Ask your developer to fix the config file."
                )
                self.capability_worker.resume_normal_flow()
                return

            if not config.get("ha_url") or not config.get("ha_token"):
                await self.capability_worker.speak(
                    "Home Assistant isn't configured yet. "
                    "A developer needs to add the URL and access token to the config file."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Debug: confirm ha_config.json loaded (token redacted)
            ha_url = config.get("ha_url", "")
            token = config.get("ha_token", "")
            self.worker.editor_logging_handler.info(
                f"[HA] Loaded config: ha_url={ha_url}, token_present={bool(token)}"
            )

            await self.capability_worker.speak(
                "One sec, connecting to your smart home."
            )

            connected = await asyncio.to_thread(self.ha_check_connection, config)
            if connected:
                self.worker.editor_logging_handler.info("[HA] API connection OK")
            if not connected:
                await self.capability_worker.speak(
                    "I can't reach Home Assistant right now. "
                    "Check that it's running and your network is connected."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Phase 1: fetch entities and build summary
            entities = await asyncio.to_thread(self.ha_get_states, config)
            if not entities:
                await self.capability_worker.speak(
                    "I couldn't find any devices. Check your Home Assistant setup."
                )
                self.capability_worker.resume_normal_flow()
                return

            entity_summary = self.build_entity_summary(entities, config)
            self.worker.editor_logging_handler.info(
                f"[HA] Fetched {len(entities)} entities, summary length={len(entity_summary)}"
            )

            # Get user command: trigger context or ask
            user_input = self.get_trigger_context()
            if not user_input or not user_input.strip():
                await self.capability_worker.speak(
                    "What would you like me to do?"
                )
                user_input = await self.capability_worker.user_response()
            if not user_input or not user_input.strip():
                await self.capability_worker.speak(
                    "I didn't catch that. Say something like 'turn off the living room lights.'"
                )
                self.capability_worker.resume_normal_flow()
                return

            user_input = user_input.strip()
            self.worker.editor_logging_handler.info(
                f"[HA] User command: {user_input!r}"
            )

            await self.capability_worker.speak("One sec.")
            parsed = self.parse_single_command(user_input, entity_summary)

            if parsed:
                self.worker.editor_logging_handler.info(
                    f"[HA] Parsed: entity_id={parsed.get('entity_id')}, "
                    f"domain={parsed.get('domain')}, service={parsed.get('service')}"
                )
            if not parsed:
                await self.capability_worker.speak(
                    "I didn't quite get that. Try again with a specific light, like 'turn off the living room lights.'"
                )
                self.capability_worker.resume_normal_flow()
                return

            if not parsed.get("entity_id"):
                await self.capability_worker.speak(
                    "I'm not sure which device you mean. Can you be more specific?"
                )
                self.capability_worker.resume_normal_flow()
                return

            domain = parsed.get("domain", "light")
            service = parsed.get("service", "turn_off")
            service_data = dict(parsed.get("service_data") or {})
            service_data["entity_id"] = parsed["entity_id"]

            success = await asyncio.to_thread(
                self.ha_call_service, config, domain, service, service_data
            )
            self.worker.editor_logging_handler.info(
                f"[HA] Service call {domain}.{service}: success={success}"
            )
            if not success:
                await self.capability_worker.speak(
                    "Something went wrong controlling that device. It might be unavailable."
                )
                self.capability_worker.resume_normal_flow()
                return

            confirmation = parsed.get("spoken_confirmation") or "Done."
            await self.capability_worker.speak(confirmation)
            self.capability_worker.resume_normal_flow()

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Home Assistant Controller error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Try again later."
            )
            self.capability_worker.resume_normal_flow()
