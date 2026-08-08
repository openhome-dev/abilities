import json
import re

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


# The LLM is the orchestrator: it reads the request + the device list and returns
# one JSON action. Tune this prompt to change behaviour — no code edits needed.
ORCHESTRATOR_PROMPT = """You control smart-home devices over MQTT. Read the user's request, pick the single device they mean, and decide the command to send it.

Devices:
{devices}
Each line gives a device's name, MQTT topic, and description, and may also list MQTT "commands" the device supports.

How to choose the device:
- Match on the device name, its location (e.g. "bedroom", "living room"), or its description.
- If several devices fit or you can't tell which one, ask instead of guessing.

How to choose the action:
- Simple power on/off → "turn_on" / "turn_off". Leave "command" and "value" empty.
- Anything else (brightness, color, temperature, modes, etc.) → "custom" with an MQTT "command" and "value":
    - If the device lists "commands", use them as your main reference, but you may still infer a command yourself when the request needs one that isn't listed.
    - If it lists no "commands", infer a sensible command and value from the device's name, description, and how such devices normally work over MQTT (e.g. Tasmota: Dimmer 0-100, HSBColor h,s,b, CT 153-500).
- Pick exactly one device. Keep "reply" natural, spoken, and under 20 words.

Reply with ONLY this JSON object, nothing else:
{{"topic": "<device topic>", "action": "turn_on" | "turn_off" | "custom", "command": "<command, custom only>", "value": "<value, custom only>", "reply": "<short spoken confirmation>"}}

If the request matches no device, several devices fit, or you can't determine a command, reply instead with:
{{"ask": "<one short clarifying question>"}}

Examples (illustrative only — use the real devices listed above):
- "turn on the kitchen light" -> {{"topic": "kitchen_light", "action": "turn_on", "command": "", "value": "", "reply": "Turning on the kitchen light."}}
- "dim the bedroom lamp to 30 percent" -> {{"topic": "bedroom_lamp", "action": "custom", "command": "Dimmer", "value": "30", "reply": "Setting the bedroom lamp to 30 percent."}}
- "make the living room bulb blue" -> {{"topic": "living_room_bulb", "action": "custom", "command": "HSBColor", "value": "240,100,100", "reply": "Turning the living room bulb blue."}}
- "turn on the light" (when several lights exist) -> {{"ask": "Which light do you mean — kitchen, bedroom, or living room?"}}

User request: {request}"""


class SmartHomeCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    def format_devices(self, devices: list) -> str:
        entries = []
        for device in devices:
            entry = f"- {device['name']} (topic: {device['topic']})"
            if device["description"]:
                entry += f" — {device['description']}"
            if device["commands"]:
                entry += f" [commands: {device['commands']}]"
            entries.append(entry)
        return "\n".join(entries)

    def decide(self, request: str, devices: list) -> dict:
        prompt = ORCHESTRATOR_PROMPT.format(
            devices=self.format_devices(devices),
            request=request,
        )
        history = self.capability_worker.get_full_message_history()
        raw = self.capability_worker.text_to_text_response(prompt, history)

        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {}

    async def run(self):
        try:
            request = await self.capability_worker.wait_for_complete_transcription() or ""

            devices = self.worker.mqtt_devices
            if not devices:
                await self.capability_worker.speak(
                    "There are no devices added. Please add your devices in the OpenHome DevKit MQTT section."
                )
                return

            action = self.decide(request, devices)

            # One clarification round if the model needs more detail.
            if action.get("ask"):
                answer = await self.capability_worker.run_io_loop(action["ask"]) or ""
                action = self.decide(f"{request}. {answer}", devices)

            if not action.get("topic"):
                await self.capability_worker.speak(
                    action.get("ask") or "Sorry, I couldn't tell which device you meant, please try again."
                )
                return

            self.worker.editor_logging_handler.info(f"[SmartHome] {action}")
            await self.capability_worker.send_devkit_mqtt_action(
                topic=action["topic"],
                action=action.get("action", "custom"),
                value=action.get("value", ""),
                command=action.get("command", ""),
            )
            await self.capability_worker.speak(action.get("reply", "Done."))
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SmartHome] Error: {e!r}")
            await self.capability_worker.speak("Something went wrong with that request.")
        finally:
            self.capability_worker.resume_normal_flow()
