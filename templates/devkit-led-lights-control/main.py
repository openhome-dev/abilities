import json
import re

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# All available neopixel commands with their args format
NEOPIXEL_COMMANDS = {
    "neopixel_off": {
        "description": "Turn all LEDs off",
        "args": [],
        "example": "neopixel_off"
    },
    "neopixel_solid": {
        "description": "Solid hex color fill",
        "args": ["hex_color", "brightness"],
        "example": "neopixel_solid ff0000 180"
    },
    "neopixel_set_pixel": {
        "description": "Set a single LED by index",
        "args": ["pixel_index", "hex_color"],
        "example": "neopixel_set_pixel 5 00ff00"
    },
    "neopixel_set_range": {
        "description": "Set a range of LEDs",
        "args": ["start_index", "end_index", "hex_color"],
        "example": "neopixel_set_range 0 11 ff6600"
    },
    "neopixel_brightness": {
        "description": "Set global brightness (0-255)",
        "args": ["brightness_value"],
        "example": "neopixel_brightness 100"
    },
    "neopixel_rainbow": {
        "description": "Rainbow cycle animation",
        "args": ["duration", "speed"],
        "example": "neopixel_rainbow 5 30"
    },
    "neopixel_breathe": {
        "description": "Breathing pulse with any color",
        "args": ["hex_color", "duration", "speed"],
        "example": "neopixel_breathe 0066ff 5 35"
    },
    "neopixel_chase": {
        "description": "Theater chase animation",
        "args": ["hex_color", "duration", "speed"],
        "example": "neopixel_chase ff0000 5 80"
    },
    "neopixel_fire": {
        "description": "Flickering fire/flame effect",
        "args": ["duration"],
        "example": "neopixel_fire 5"
    },
    "neopixel_sparkle": {
        "description": "Random twinkle effect",
        "args": ["hex_color", "duration", "count"],
        "example": "neopixel_sparkle ffffff 5 3"
    },
    "neopixel_comet": {
        "description": "Meteor trail sweeping the ring",
        "args": ["hex_color", "duration", "speed"],
        "example": "neopixel_comet 0088ff 5 40"
    },
    "neopixel_color_wipe": {
        "description": "Fill LEDs one by one",
        "args": ["hex_color", "speed"],
        "example": "neopixel_color_wipe 00ff00 50"
    },
    "neopixel_gradient": {
        "description": "Smooth 2-color gradient",
        "args": ["hex_color_1", "hex_color_2"],
        "example": "neopixel_gradient ff0000 0000ff"
    },
    "neopixel_strobe": {
        "description": "Flash/strobe effect",
        "args": ["hex_color", "duration", "speed"],
        "example": "neopixel_strobe ffffff 3 50"
    },
    "neopixel_wave": {
        "description": "Sine wave brightness rotation",
        "args": ["hex_color", "duration"],
        "example": "neopixel_wave 0066ff 5"
    },
    "neopixel_police": {
        "description": "Alternating red/blue halves",
        "args": ["duration"],
        "example": "neopixel_police 5"
    },
    "neopixel_candle": {
        "description": "Warm candle flicker",
        "args": ["duration"],
        "example": "neopixel_candle 10"
    },
    "neopixel_mode": {
        "description": "Built-in LED mode (off, bot-speaking, bot-listening, bot-interrupted, music-mode, pause)",
        "args": ["mode_name"],
        "example": "neopixel_mode bot-listening"
    },
    "neopixel_music": {
        "description": "Music reactive mode",
        "args": ["duration"],
        "example": "neopixel_music 10"
    },
    "neopixel_sleep": {
        "description": "Sleep animation",
        "args": ["duration"],
        "example": "neopixel_sleep 10"
    },
    "neopixel_speaking": {
        "description": "Speaking animation",
        "args": ["duration"],
        "example": "neopixel_speaking 10"
    },
    "neopixel_listening": {
        "description": "Listening animation",
        "args": ["duration"],
        "example": "neopixel_listening 10"
    },
}

COMMANDS_SUMMARY = "\n".join(
    f"- {name}({', '.join(info['args'])}): {info['description']}. Example: {info['example']}"
    for name, info in NEOPIXEL_COMMANDS.items()
)

SYSTEM_PROMPT = f"""You are a devkit LED controller assistant. The user will describe what they want the lights to do in natural language.

You must respond with ONLY a valid JSON object (no markdown, no explanation) in this format:
{{
    \"function_name\": \"<command_name>\",
    \"args\": [<arg1>, <arg2>, ...],
    \"spoken_response\": \"<short friendly confirmation to speak to user>\"
}}

Available commands:
{COMMANDS_SUMMARY}

Rules:
1. Return ONLY valid JSON. No markdown fences, no extra text.
2. All args must be strings in the array.
3. Pick the best matching command for the user's request.
4. For color requests, convert color names to hex (e.g. \"red\" -> \"ff0000\", \"blue\" -> \"0000ff\", \"green\" -> \"00ff00\", \"purple\" -> \"8800ff\", \"orange\" -> \"ff6600\", \"pink\" -> \"ff69b4\", \"white\" -> \"ffffff\", \"yellow\" -> \"ffff00\", \"cyan\" -> \"00ffff\").
5. Use sensible defaults for missing params (brightness: 150, speed: 30). For duration: if the user does NOT specify a time, pass 999999 (effect runs continuously until the user explicitly changes or stops it). Only use a smaller duration when the user explicitly asks (e.g. \"for 1 minute\", \"30 seconds\", \"a few seconds\").
6. The spoken_response should be a short, natural confirmation of what you're doing.
7. If the user wants to turn off lights (\"turn off\", \"lights off\", \"turn the lights off\", \"off\"), use neopixel_off. NOTE: the verb \"stop\" is NOT turn-off — \"stop\", \"stop the lights\", \"stop the rainbow\" all mean EXIT (rule 14), not neopixel_off. Only treat as turn-off when the user uses \"off\" or \"turn off\".
8. If the user asks something unrelated to lights, return: {{\"function_name\": \"none\", \"args\": [], \"spoken_response\": \"<polite redirect about lights>\"}}
9. Prefer fast, clear commands for vague requests. Examples:
   - \"make it red\" -> neopixel_solid
   - \"turn them funky blue\" -> neopixel_breathe with blue
   - \"something cool\" -> neopixel_rainbow
10. First-turn fallback. If the user prompt is tagged [first turn] AND the user gave no actionable command (just a wake/trigger phrase like \"control the lights\"), pick ONE varied fun effect from: neopixel_rainbow, neopixel_breathe, neopixel_sparkle, neopixel_comet, neopixel_chase, neopixel_wave, neopixel_fire, neopixel_candle. Use a duration of 10 in args (sensible defaults for color/speed per the function table — e.g. neopixel_breathe takes [\"0066ff\",\"10\",\"35\"], neopixel_fire takes [\"10\"], neopixel_rainbow takes [\"10\",\"30\"]). The spoken_response MUST name the chosen effect and offer the menu, e.g. \"Starting a sparkle effect. I can also do dancing, bouncing ball, music reactive mode, or set solid colors — what would you like?\" or \"Going with a candle flicker. I can also do rainbow, sparkle, music reactive, or solid colors — what's next?\". Vary the chosen effect across sessions. This rule applies only on [first turn] — after 10s the effect ends and the cloud transitions to the default gradient.
11. Time conversion. Convert spoken durations to seconds in args: \"for 1 minute\" -> 60, \"30 seconds\" -> 30, \"two minutes\" -> 120, \"a few seconds\" -> 5.
12. Duration only when user asks. Never invent a short duration. If the user did not mention any time, the effect must run until they say otherwise — pass 999999 in the duration arg. If they said \"for a bit\" or \"a while\" without a number, treat as 30-60 seconds.
13. Switch vs exit. An utterance is a SWITCH only when the user names a NEW effect/color to replace the current one — e.g. \"stop and start dancing\", \"switch to candle\", \"now do music\", \"stop the rainbow and try fire\". Emit the new function_name; the device replaces the running effect automatically. WITHOUT an alternative effect named, \"stop the lights\", \"stop the rainbow\", \"stop the effect\" are all EXIT (rule 14), not switch and not turn-off.
14. Exit detection (HIGHEST PRIORITY). The verbs \"stop\", \"exit\", \"quit\" and the phrases \"bye\", \"goodbye\", \"thanks\", \"I'm good\", \"that'll do\", \"all done\", \"got it\", \"that's it\" — used alone, with the lights as object, or in any short phrasing — ALWAYS mean EXIT THE ABILITY. They never mean neopixel_off. They never mean a switch unless the user names a REPLACEMENT effect in the same sentence (rule 13).

   Required examples to memorize (all → function_name \"exit\"):
   - \"stop\" → exit
   - \"stop the lights\" → exit
   - \"stop the rainbow\" → exit
   - \"stop the music\" → exit
   - \"stop the effect\" → exit
   - \"please stop\" / \"stop please\" / \"okay stop\" / \"stop now\" → exit
   - \"exit\" / \"exit now\" / \"I want to exit\" → exit
   - \"quit\" / \"quit lights\" → exit
   - \"bye\" / \"goodbye\" / \"see you\" → exit
   - \"thanks\" / \"thanks that's good\" / \"thank you\" → exit
   - \"I'm good\" / \"I'm done\" / \"we're done\" / \"all done\" → exit
   - \"perfect\" / \"that'll do\" / \"that's it\" / \"got it\" → exit

   Counter-examples that are NOT exit (rule 13 — switch):
   - \"stop and do candle\" → neopixel_candle
   - \"stop the rainbow and try fire\" → neopixel_fire
   - \"switch to dancing\" → neopixel_chase

   spoken_response must clearly signal the ability is closing — 3-6 words, neutral. The user is staying with the agent, you're just handing control back, so DO NOT use parting phrases like \"see you\", \"talk soon\", \"take care\", \"goodbye\", or \"bye\" alone. Examples: \"Closing lights control.\", \"Lights ability off.\", \"Done with the lights.\", \"Exiting lights mode.\", \"Lights control closed.\". Vary across sessions.
15. Conversational tone. spoken_response should sound like a calm, friendly person who just did what was asked. Sometimes confirm only (\"Going red.\"). Sometimes add a warm natural follow-up (\"Going red — looks great. Tell me when to switch.\"). Vary the phrasing across turns. Avoid mechanical fillers like \"Anything else?\" or \"What's next?\".
"""


FALLBACK_FUNCTION = "neopixel_rainbow"
FALLBACK_ARGS = ["999999", "30"]


class LedlightstemplateCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _command_counter: int = 0

    #{{register capability}}

    def _duration_for_effect(self, function_name, args):
        info = NEOPIXEL_COMMANDS.get(function_name, {})
        arg_names = info.get("args", [])
        if "duration" not in arg_names:
            return None
        try:
            return float(args[arg_names.index("duration")])
        except (ValueError, IndexError, TypeError):
            return None

    async def _fallback_after(self, duration: float, my_id: int):
        """After a timed effect ends, drop a soft gradient so the strip isn't dark."""
        await self.worker.session_tasks.sleep(duration)
        if my_id != self._command_counter:
            return  # a newer command has been issued; this fallback is stale
        self.worker.editor_logging_handler.info("[Lights] Effect ended — falling back to default look")
        await self.capability_worker.send_devkit_capability_action(
            FALLBACK_FUNCTION, FALLBACK_ARGS, 5
        )

    async def execute_light_command(self, command_dict: dict):
        function_name = command_dict.get("function_name", "")
        args = command_dict.get("args", [])
        spoken = command_dict.get("spoken_response", "Done!")

        if function_name == "none" or function_name not in NEOPIXEL_COMMANDS:
            await self.capability_worker.speak(spoken)
            return

        # Bump the counter so any pending fallback timer from a previous command
        # knows it's been superseded and will exit silently.
        self._command_counter += 1
        my_id = self._command_counter

        self.worker.editor_logging_handler.info(
            f"[Lights] Executing: {function_name} with args: {args}"
        )

        # Speak and bridge in parallel — user hears the response while
        # the device is already running the command in the background.
        self.worker.session_tasks.create(self.capability_worker.speak(spoken))

        response_timeout = 8
        result = await self.capability_worker.send_devkit_capability_action(
            function_name, args, response_timeout
        )
        self.worker.editor_logging_handler.info(f"[Lights] bridge result: {result!r}")

        success = True
        if isinstance(result, dict) and result.get("error") and not result.get("success"):
            success = False
            self.worker.editor_logging_handler.error(
                f"[Lights] Command failed: {result.get('error')}"
            )

        if not success:
            await self.capability_worker.speak("Sorry, that didn't work.")
            return

        duration = self._duration_for_effect(function_name, args)
        if duration:
            self.worker.session_tasks.create(self._fallback_after(duration, my_id))

    async def first_function(self):
        try:
            await self.capability_worker.send_devkit_action("automatic_leds_off")

            first_time = True
            history = []

            while True:
                is_first_iteration = first_time
                if first_time:
                    msg = await self.capability_worker.wait_for_complete_transcription()
                    self.worker.editor_logging_handler.info(
                        f"[Lights] Initial input: {msg}"
                    )
                    first_time = False
                else:
                    msg = await self.capability_worker.user_response()
                    self.worker.editor_logging_handler.info(f"[Lights] User said: {msg}")

                if not msg or not msg.strip():
                    break

                turn_marker = "[first turn]" if is_first_iteration else "[follow-up turn]"
                user_prompt = f'{turn_marker} User request: "{msg}"'
                response = self.capability_worker.text_to_text_response(
                    user_prompt, history, system_prompt=SYSTEM_PROMPT
                )

                self.worker.editor_logging_handler.info(
                    f"[Lights] LLM response: {response}"
                )

                try:
                    cleaned = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", response.strip())
                    command_dict = json.loads(cleaned)
                except (json.JSONDecodeError, Exception) as e:
                    self.worker.editor_logging_handler.error(
                        f"[Lights] Failed to parse LLM response: {e}"
                    )
                    await self.capability_worker.speak("Sorry, say that again?")
                    continue

                history.append({"role": "user", "content": user_prompt})
                history.append({"role": "assistant", "content": response})
                if len(history) > 20:
                    history = history[-20:]

                # LLM-routed exit (catches natural endings the regex doesn't).
                if command_dict.get("function_name") == "exit":
                    goodbye = command_dict.get("spoken_response") or "Lights Control turned off."
                    await self.capability_worker.speak(goodbye)
                    break

                await self.execute_light_command(command_dict)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Lights] Error: {e}")
            await self.capability_worker.speak("Something went wrong with lights control.")
        finally:
            try:
                await self.capability_worker.send_devkit_capability_action("neopixel_off", [], 5)
                await self.capability_worker.send_devkit_action("automatic_leds_on")
                self.capability_worker.resume_normal_flow()
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[Lights] Cleanup error: {e}")

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.first_function())
