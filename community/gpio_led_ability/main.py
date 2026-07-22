import json
import re
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


AVAILABLE_COMMANDS = {
    "led_on": "Turn the LED on",
    "led_off": "Turn the LED off",
    "led_blink": "Blink the LED a number of times",
    "led_status": "Report whether the LED is currently on or off",
}

FUNCTIONS_DESCRIPTION = "\n".join(
    f"- {name}: {description}" for name, description in AVAILABLE_COMMANDS.items()
)

SYSTEM_PROMPT = f"""You are a strict command router for a GPIO LED controller Ability on a Raspberry Pi 4.
Your only job is to map user input to exactly one function name. Do not answer questions, explain, or generate prose.

## Response Format
Always return a single JSON object. No markdown, no extra keys.
{{"function_name": "<function_name | none | exit>", "blink_count": <integer or null>}}

## Available Functions
{FUNCTIONS_DESCRIPTION}

## Routing Rules
- Turn on, switch on, enable, light up  -> led_on
- Turn off, switch off, disable, kill the light -> led_off
- Blink, flash, pulse -> led_blink. Extract the count from phrases like "blink 3 times" or "flash 5 times". Default blink_count to 3 if not specified.
- Status, is it on, check, state -> led_status

## Exit Routing
Trigger `exit` when the user says: stop, quit, cancel, done, all done, that's all, thank you, thanks, bye, goodbye.

## Unsupported Requests
If the request is unrelated to LED control, return:
{{"function_name": "none", "blink_count": null}}

## Hard Rules
- Return exactly one function_name per response.
- Never include text outside the JSON object.
- blink_count must be an integer between 1 and 20. If the user says "many times" use 5. If they say "once" use 1.
"""


class GpioLedCapability(MatchingCapability):
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

                route = self._route_to_led_function(user_message, conversation_history)
                function_name = route.get("function_name", "")
                blink_count = route.get("blink_count") or 3

                # Default to status check on first turn if routing is unclear
                if is_first_turn and function_name in ("", "none"):
                    function_name = "led_status"

                if function_name == "exit":
                    await self.capability_worker.speak("Exiting LED control.")
                    break

                if function_name not in AVAILABLE_COMMANDS:
                    await self.capability_worker.speak(
                        "I can only control the LED. Try saying turn on, turn off, blink, or check status."
                    )
                    is_first_turn = False
                    continue

                # Build args — led_blink needs the count, others need nothing
                args = [str(blink_count)] if function_name == "led_blink" else []

                result = await self.capability_worker.send_devkit_capability_action(
                    function_name=function_name,
                    args=args,
                    timeout=15,  # blink can take a few seconds
                )

                spoken_message = self._spoken_response_from_result(result)
                await self.capability_worker.speak(spoken_message)

                conversation_history.append({"role": "user", "content": user_message})
                conversation_history.append({"role": "assistant", "content": spoken_message})
                conversation_history = conversation_history[-10:]

                await self.capability_worker.speak(
                    "Anything else? You can say turn on, turn off, blink, or stop."
                )
                is_first_turn = False

        except Exception as error:
            self.worker.editor_logging_handler.error(f"GPIO LED ability failed: {error}")
            await self.capability_worker.speak(
                "Something went wrong with the LED controller."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    def _route_to_led_function(self, user_message, conversation_history):
        response = self.capability_worker.text_to_text_response(
            f'User request: "{user_message}"',
            conversation_history,
            system_prompt=SYSTEM_PROMPT,
        )
        cleaned = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", response.strip())
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"function_name": "", "blink_count": None}

    def _spoken_response_from_result(self, result):
        if not isinstance(result, dict):
            return "I couldn't reach the DevKit."

        if not result.get("success"):
            self.worker.editor_logging_handler.error(
                f"DevKit LED call failed: {result.get('error')}"
            )
            return "I couldn't control the LED. There may be a hardware issue."

        output = (result.get("output") or "").strip()
        if not output:
            return "The LED command ran but returned no response."

        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            self.worker.editor_logging_handler.error(f"Invalid DevKit output: {output}")
            return "I couldn't read the LED response."

        if not payload.get("success"):
            error = payload.get("error") or {}
            self.worker.editor_logging_handler.warning(
                f"LED action failed: {error.get('code')} — {error.get('message')}"
            )

        return payload.get("spoken_response") or "LED action completed."

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.first_function())
