import json
import re
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


AVAILABLE_STATS = {
    "get_cpu": "CPU usage",
    "get_memory": "Memory usage",
    "get_temperature": "Device temperature",
    "get_uptime": "Device uptime",
    "get_wifi": "Wi-Fi connection",
    "get_disk": "Disk usage",
    "get_health": "Overall device health",
    "get_all_stats": "Summary of all key metrics",
}

FUNCTIONS_DESCRIPTION = "\n".join(
    f"- {name}: {description}" for name, description in AVAILABLE_STATS.items()
)

SYSTEM_PROMPT = f"""You are a request router for a DevKit telemetry Ability. Your sole responsibility is to map user input to exactly one function name. You do not answer questions, explain concepts, or generate conversational responses.

## Device Context
The OpenHome DevKit is the user's locally connected device. Telemetry refers to its live runtime metrics: CPU, memory, temperature, uptime, Wi-Fi, disk, and health. This Ability is limited strictly to the functions listed below.

## Response Format
Always return a single JSON object. No prose, no markdown, no extra keys.
{{"function_name": "<function_name | none | exit>"}}

## Available Functions
{FUNCTIONS_DESCRIPTION}

## Routing Rules
- General status, "all stats", "everything", "snapshot", "system info" -> get_all_stats
- CPU, processor, load, compute, busy, usage -> get_cpu
- Memory, RAM, available memory, used memory -> get_memory
- Temperature, temp, heat, thermal, hot, warm -> get_temperature
- Uptime, boot time, running time, how long running -> get_uptime
- Wi-Fi, wifi, network, SSID, connection -> get_wifi
- Disk, storage, free space, used space -> get_disk
- Health, diagnostics, issues, problems, anything wrong -> get_health

## Exit Routing
Trigger `exit` when the user says: stop, quit, cancel, end, done, all done, that's all, thank you, thanks, goodbye, bye — or any close variation, even with filler words.

## Unsupported Requests
If the request is unrelated to DevKit telemetry, or asks for telemetry not covered by any available function, return:
{{"function_name": "none"}}

## Hard Rules
- Return exactly one function_name per response.
- Never explain, define, or discuss any concept — even if directly asked.
- Route by intent: if the user asks "what is my CPU usage?" that is a CPU telemetry request -> get_cpu.
- Do not include any text outside the JSON object.
"""


class DevkitStatsCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    async def first_function(self):
        try:
            is_first_turn = True
            conversation_history = []

            while True:
                if is_first_turn:
                    user_message = await self.capability_worker.wait_for_complete_transcription()
                else:
                    user_message = await self.capability_worker.user_response()

                if not user_message or not user_message.strip():
                    continue

                route = self._route_to_devkit_function(user_message, conversation_history)
                function_name = route.get("function_name", "")

                if is_first_turn and function_name in ("", "none"):
                    function_name = "get_all_stats"

                if function_name == "exit":
                    await self.capability_worker.speak("Exiting DevKit stats.")
                    break

                if function_name not in AVAILABLE_STATS:
                    await self.capability_worker.speak(
                        "I can't fetch that DevKit information. Try asking for CPU, memory, temperature, disk, uptime, Wi-Fi, or health."
                    )
                    is_first_turn = False
                    continue

                result = await self.capability_worker.send_devkit_capability_action(
                    function_name=function_name,
                    args=[],
                    timeout=8,
                )
                spoken_message = self._spoken_response_from_result(result)
                await self.capability_worker.speak(spoken_message)

                conversation_history.append({"role": "user", "content": user_message})
                conversation_history.append({"role": "assistant", "content": spoken_message})
                conversation_history = conversation_history[-12:]

                await self.capability_worker.speak("Want me to check anything else, or say stop to exit.")
                is_first_turn = False

        except Exception as error:
            self.worker.editor_logging_handler.error(f"DevKit stats failed: {error}")
            await self.capability_worker.speak("Something went wrong while checking DevKit stats.")
        finally:
            self.capability_worker.resume_normal_flow()

    def _route_to_devkit_function(self, user_message, conversation_history):
        response = self.capability_worker.text_to_text_response(
            f'User request: "{user_message}"',
            conversation_history,
            system_prompt=SYSTEM_PROMPT,
        )
        cleaned = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", response.strip())
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"function_name": ""}

    def _spoken_response_from_result(self, result):
        if not isinstance(result, dict):
            return "I couldn't reach the DevKit."

        if not result.get("success"):
            self.worker.editor_logging_handler.error(
                f"DevKit call failed: {result.get('error')}"
            )
            return "I couldn't fetch that DevKit information. Try asking for another stat."

        output = (result.get("output") or "").strip()
        if not output:
            return "I couldn't fetch that DevKit information. Try asking for another stat."

        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            self.worker.editor_logging_handler.error(f"Invalid DevKit output: {output}")
            return "I couldn't read the DevKit response."

        if not payload.get("success"):
            error = payload.get("error") or {}
            self.worker.editor_logging_handler.warning(
                f"DevKit stat unavailable: {error.get('code')} {error.get('message')}"
            )

        return payload.get("spoken_response") or "I couldn't read that DevKit stat."

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.first_function())
