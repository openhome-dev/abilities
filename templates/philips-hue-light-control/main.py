import asyncio
import json
import re

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


ACTION_ORDER = (
    "hue_on", "hue_off", "hue_brightness", "hue_temp", "hue_color", "hue_status",
)

ACTION_SCHEMAS = {
    "hue_on": {
        "requires": "supports_on_off",
        "description": "turn the light on",
        "examples": (
            ("turn it on", []),
            ("switch on the bulb", []),
            ("lights on please", []),
            ("flip it on", []),
            ("light it up", []),
            ("can you put the light on", []),
        ),
    },
    "hue_off": {
        "requires": "supports_on_off",
        "description": "turn the light off",
        "examples": (
            ("turn off the light", []),
            ("switch it off", []),
            ("kill the lights", []),
            ("shut it off", []),
            ("lights off", []),
            ("cut the light", []),
        ),
    },
    "hue_brightness": {
        "requires": "supports_brightness",
        "description": (
            "set brightness, args=[Hue level 1-254]. Natural amounts are ok: "
            "full=254, half=127, dim=60. User numbers from 0-100 are "
            "percentages unless they explicitly say raw Hue level."
        ),
        "examples": (
            ("set brightness to full", ["254"]),
            ("set brightness to half", ["127"]),
            ("brightness ten percent", ["25"]),
            ("brightness 75", ["190"]),
            ("set it to 50 percent", ["127"]),
            ("dim it", ["60"]),
            ("make it brighter", ["220"]),
            ("crank it up", ["254"]),
            ("not so bright", ["60"]),
            ("a little dimmer please", ["60"]),
            ("tone it down a bit", ["80"]),
            ("bit brighter", ["200"]),
        ),
    },
    "hue_temp": {
        "requires": "supports_colour_temp",
        "description": (
            "white colour temperature in mireds, args=[value {lo}-{hi}]. "
            "{lo}=cool/daylight, {hi}=warm/candle."
        ),
        "examples": (
            ("warmer light", ["{hi}"]),
            ("cooler", ["{lo}"]),
            ("set temperature to 350", ["350"]),
            ("make it more cozy", ["{hi}"]),
            ("a bit warmer please", ["{hi}"]),
            ("reading light", ["300"]),
            ("something warm", ["{hi}"]),
            ("less harsh", ["{hi}"]),
        ),
    },
    "hue_color": {
        "requires": "supports_colour_xy",
        "description": "RGB colour, args=[\"r,g,b\"] each 0-255",
        "examples": (
            ("make it red", ["255,0,0"]),
            ("set colour to purple", ["128,0,128"]),
            ("go blue", ["0,0,255"]),
            ("hit me with some green", ["0,255,0"]),
            ("red please", ["255,0,0"]),
            ("something orange", ["255,140,0"]),
        ),
    },
    "hue_status": {
        "description": "report current state",
        "examples": (
            ("what's the status", []),
            ("is it on", []),
            ("how's the light", []),
            ("what's it set to", []),
            ("check the light", []),
        ),
    },
}

COLOR_NAMES = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 140, 0),
    "pink": (255, 105, 180),
    "cyan": (0, 255, 255),
    "purple": (128, 0, 128),
    "violet": (128, 0, 128),
    "magenta": (255, 0, 255),
}

BRIGHTNESS_PHRASES = (
    ("all the way up", 254),
    ("all the way", 254),
    ("crank it up", 254),
    ("one hundred percent", 254),
    ("hundred percent", 254),
    ("maximum", 254),
    ("brightest", 254),
    ("full", 254),
    ("max", 254),
    ("high", 220),
    ("bit brighter", 200),
    ("a bit brighter", 200),
    ("brighter", 220),
    ("bright", 220),
    ("seventy five percent", 190),
    ("three quarters", 190),
    ("half", 127),
    ("fifty percent", 127),
    ("medium", 127),
    ("middle", 127),
    ("quarter", 64),
    ("twenty five percent", 64),
    ("tone it down", 80),
    ("not so bright", 60),
    ("a little dimmer", 60),
    ("a bit dimmer", 60),
    ("bit dimmer", 60),
    ("dimmer", 60),
    ("dim", 60),
    ("low", 40),
    ("minimum", 1),
    ("lowest", 1),
)

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}

TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def _supported_actions(capabilities: dict) -> set:
    supported = {"hue_status"}
    for action in ACTION_ORDER:
        requirement = ACTION_SCHEMAS.get(action, {}).get("requires")
        if not requirement or capabilities.get(requirement):
            supported.add(action)
    return supported


def _build_router_prompt(capabilities: dict) -> str:
    """Build a routing prompt that only mentions actions the bulb supports."""
    lo = capabilities.get("minimum_mireds") or 153
    hi = capabilities.get("maximum_mireds") or 500
    supported = _supported_actions(capabilities)

    func_lines = []
    example_lines = []
    for action in ACTION_ORDER:
        if action not in supported:
            continue
        schema = ACTION_SCHEMAS[action]
        description = schema["description"].format(lo=lo, hi=hi)
        func_lines.append(f'  "{action}": {description}')
        for utterance, args in schema["examples"]:
            formatted_args = [str(arg).format(lo=lo, hi=hi) for arg in args]
            payload = {"function_name": action, "args": formatted_args}
            example_lines.append(f'  "{utterance}" -> {json.dumps(payload)}')

    func_lines.append('  "exit": user wants to leave')
    func_lines.append('  "none": request unrelated to controlling the light')

    functions_block = "\n".join(func_lines)
    examples_block = "\n".join(example_lines + [
        '  "thanks, bye" -> {"function_name": "exit", "args": []}',
        '  "that\'s all" -> {"function_name": "exit", "args": []}',
        '  "I\'m done" -> {"function_name": "exit", "args": []}',
        '  "stop" -> {"function_name": "exit", "args": []}',
        '  "never mind" -> {"function_name": "exit", "args": []}',
        '  "forget it" -> {"function_name": "exit", "args": []}',
        '  "all good thanks" -> {"function_name": "exit", "args": []}',
        '  "what\'s the weather" -> {"function_name": "none", "args": []}',
        '  "play some music" -> {"function_name": "none", "args": []}',
    ])

    return f"""You route natural language requests for a Hue light to ONE function.

Output ONLY a JSON object on a single line:
{{"function_name": "<name>", "args": [<string args>]}}

Functions:
{functions_block}

Examples:
{examples_block}

Rules:
- Accept casual speech: "crank it up" = full brightness, "kill the lights" = off, "go blue" = colour blue, "cozy vibe" = warm temperature.
- Convert spelled-out numbers, including "ten", "fifty", and "one hundred".
- For brightness, numbers from 0-100 are percentages unless the user says raw Hue level.
- Brightness percentages map to the scale: brightness percent times 254 / 100.
- For temperature, if the user gives a number, use that number instead of generic warm/cool defaults.
- For colour names use the common RGB triple (red 255,0,0 / green 0,255,0 /
  blue 0,0,255 / white 255,255,255 / yellow 255,255,0 / orange 255,140,0 /
  pink 255,105,180 / cyan 0,255,255 / purple 128,0,128).
- args is always a list of strings, even if empty.
- Never output anything except the JSON object.
"""


class PhillipHueCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    async def first_function(self):
        try:
            # ---- Connect phase ---------------------------------------------
            # hue_connect returns quickly (≤5 s) and signals {"still_connecting": True}
            # while the daemon is still doing BLE discovery/connect.  We poll here
            # (up to 12 × 5 s = ~60 s) so no devkit subprocess timeout can fire.
            # The daemon writes a status phase (scanning/connecting/connected) which
            # we surface as spoken progress so the user isn't left in silence.
            _PHASE_LINES = {
                "scanning":   "Scanning for your bulb.",
                "connecting": "Found it, connecting.",
                "connected":  "Almost there.",
            }
            spoken_phase = None

            capabilities = None
            for _ in range(12):
                connect_result = await self.capability_worker.send_devkit_capability_action(
                    function_name="hue_connect",
                    args=[],
                    timeout=10,
                )
                caps = self._capabilities_from_result(connect_result)
                if caps is None:
                    spoken = self._spoken_response_from_result(connect_result)
                    await self.capability_worker.speak(
                        spoken or "I couldn't connect to the bulb."
                    )
                    return
                if not caps.get("still_connecting"):
                    capabilities = caps
                    break
                # Speak a progress line the first time each phase is reached.
                phase = caps.get("phase", "scanning")
                if phase != spoken_phase and phase in _PHASE_LINES:
                    await self.capability_worker.speak(_PHASE_LINES[phase])
                    spoken_phase = phase
            else:
                await self.capability_worker.speak(
                    "I couldn't connect to the bulb in time."
                )
                return

            self.worker.editor_logging_handler.info(
                f"Hue bulb connected with capabilities: {capabilities}"
            )

            # Build a router prompt tailored to this bulb's actual features.
            system_prompt = _build_router_prompt(capabilities)
            supported_actions = _supported_actions(capabilities)

            await self.capability_worker.speak(
                "Connected to the bulb. What would you like to do?"
            )

            # ---- Action loop -----------------------------------------------
            conversation_history = []
            while True:
                user_message = await self.capability_worker.user_response()
                if not user_message or not user_message.strip():
                    continue

                route = self._route(
                    user_message, conversation_history, system_prompt, capabilities
                )
                function_name = route.get("function_name", "")
                function_args = route.get("args", []) or []
                self.worker.editor_logging_handler.info(
                    f"Hue route ({route.get('source', 'unknown')}): "
                    f"user={user_message!r} -> {function_name} {function_args}"
                )

                if function_name == "exit":
                    break

                if function_name not in supported_actions:
                    await self.capability_worker.speak(self._help_message(capabilities))
                    continue

                spoken_message = await self._run_action(function_name, function_args)

                conversation_history.append({"role": "user", "content": user_message})
                conversation_history.append({"role": "assistant", "content": spoken_message})
                conversation_history = conversation_history[-12:]

        except Exception as error:
            self.worker.editor_logging_handler.error(f"Hue ability failed: {error}")
            await self.capability_worker.speak("Something went wrong with the bulb.")
        finally:
            # ---- Disconnect: always runs ------------------------------------
            try:
                await self.capability_worker.send_devkit_capability_action(
                    function_name="hue_disconnect",
                    args=[],
                    timeout=10,
                )
            except Exception as e:
                self.worker.editor_logging_handler.warning(
                    f"hue_disconnect call failed (non-fatal): {e}"
                )
            try:
                await self.capability_worker.speak("Disconnected from the bulb. Goodbye.")
            except Exception:
                pass
            self.capability_worker.resume_normal_flow()

    # ---- Helpers --------------------------------------------------------
    async def _run_action(self, function_name: str, function_args: list) -> str:
        """Run a BLE action and speak the result.

        For action commands (on/off/brightness/temp/color) we know what to say
        before the daemon responds, so we speak and act in parallel.
        For hue_status we need the data first, so it stays sequential.
        """
        instant = self._instant_spoken(function_name, function_args)
        if instant:
            _, result = await asyncio.gather(
                self.capability_worker.speak(instant),
                self.capability_worker.send_devkit_capability_action(
                    function_name=function_name,
                    args=[str(a) for a in function_args],
                    timeout=15,
                ),
            )
            if not (isinstance(result, dict) and result.get("success")):
                self.worker.editor_logging_handler.warning(
                    f"Action {function_name} may have failed: {result}"
                )
            return instant

        result = await self.capability_worker.send_devkit_capability_action(
            function_name=function_name,
            args=[str(a) for a in function_args],
            timeout=15,
        )
        spoken_message = self._spoken_response_from_result(result)
        await self.capability_worker.speak(spoken_message)
        return spoken_message

    def _instant_spoken(self, function_name: str, args: list) -> str | None:
        """Return the spoken confirmation for action commands without waiting for the daemon.

        Returns None for query commands (hue_status) that need the daemon's data.
        """
        if function_name == "hue_on":
            return "Turning the light on."
        if function_name == "hue_off":
            return "Turning the light off."
        if function_name == "hue_brightness" and args:
            try:
                level = max(1, min(254, int(args[0])))
            except (TypeError, ValueError):
                return "Adjusting the brightness."
            if level >= 250:
                return "Setting brightness to full."
            if 124 <= level <= 130:
                return "Setting brightness to half."
            percent = max(1, min(100, round(level * 100 / 254)))
            return f"Setting brightness to {percent} percent."
        if function_name == "hue_temp" and args:
            try:
                mireds = int(args[0])
            except (TypeError, ValueError):
                return "Adjusting the colour temperature."
            return f"Setting colour temperature to {mireds} mireds."
        if function_name == "hue_color" and args:
            try:
                r, g, b = (int(p) for p in args[0].split(","))
                return f"Setting colour to red {r}, green {g}, blue {b}."
            except (TypeError, ValueError):
                return "Changing the colour."
        return None

    def _route(self, user_message: str, conversation_history: list,
               system_prompt: str, capabilities: dict) -> dict:
        local_route = self._route_locally(user_message, capabilities)
        if local_route:
            local_route["source"] = "local"
            return local_route

        response = self.capability_worker.text_to_text_response(
            f'User said: "{user_message}"',
            conversation_history,
            system_prompt=system_prompt,
        )
        cleaned = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", (response or "").strip())
        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                return {"function_name": "", "args": []}
            return self._normalise_llm_route(parsed, user_message, capabilities)
        except (json.JSONDecodeError, TypeError, ValueError):
            self.worker.editor_logging_handler.warning(
                f"router returned non-JSON: {response!r}"
            )
            return {"function_name": "", "args": []}

    def _normalise_llm_route(self, route: dict, user_message: str, capabilities: dict) -> dict:
        """Clamp and reinterpret LLM args with the same rules as local routing."""
        route["source"] = "llm"
        function_name = route.get("function_name")
        args = route.get("args", []) or []
        text = self._normalise_message(user_message)

        if function_name == "hue_brightness" and args:
            level = self._brightness_from_text(text)
            if level is None:
                level = self._brightness_arg_to_level(args[0], text)
            if level is not None:
                route["args"] = [str(level)]

        if function_name == "hue_temp" and args:
            number = self._extract_number(text)
            value = (
                self._temperature_number_to_mireds(number, capabilities)
                if number is not None
                else self._temperature_arg_to_mireds(args[0], capabilities)
            )
            if value is not None:
                route["args"] = [str(value)]

        return route

    def _route_locally(self, user_message: str, capabilities: dict) -> dict | None:
        """Fast path for common commands so routing does not depend on the LLM."""
        text = self._normalise_message(user_message)
        supported = _supported_actions(capabilities)

        if self._is_status_request(text):
            return {"function_name": "hue_status", "args": []}

        if "hue_temp" in supported:
            temp = self._temperature_from_text(text, capabilities)
            if temp is not None:
                return {"function_name": "hue_temp", "args": [str(temp)]}

        if "hue_color" in supported:
            color = self._color_from_text(text)
            if color is not None:
                return {"function_name": "hue_color", "args": [color]}

        if "hue_brightness" in supported:
            level = self._brightness_from_text(text)
            if level is not None:
                return {"function_name": "hue_brightness", "args": [str(level)]}

        if "hue_off" in supported and self._is_off_request(text):
            return {"function_name": "hue_off", "args": []}

        if "hue_on" in supported and self._is_on_request(text):
            return {"function_name": "hue_on", "args": []}

        return None

    @staticmethod
    def _normalise_message(message: str) -> str:
        text = (message or "").lower()
        text = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 percent", text)
        replacements = {
            "brighteness": "brightness",
            "brighness": "brightness",
            "briteness": "brightness",
            "bightness": "brightness",
            "colour": "color",
            "per cent": "percent",
            "100%": "100 percent",
            "50%": "50 percent",
            "25%": "25 percent",
            "75%": "75 percent",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r"[^a-z0-9.%\s-]", " ", text)
        text = text.replace("-", " ")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _contains_phrase(text: str, phrase: str) -> bool:
        return bool(re.search(rf"\b{re.escape(phrase)}\b", text))

    def _is_status_request(self, text: str) -> bool:
        return any(
            self._contains_phrase(text, phrase)
            for phrase in (
                "status", "state", "what is it doing", "what's it doing",
                "what s it doing", "is it on", "is the light on", "is the bulb on",
                "check it", "check the light", "how s the light", "how is the light",
                "what s it set to", "how bright is it",
            )
        )

    def _is_on_request(self, text: str) -> bool:
        return bool(
            re.search(r"\b(turn|switch|power|put|flip|get)\b.*\bon\b", text)
            or re.search(r"\blight\s*(it\s*)?up\b", text)
            or self._contains_phrase(text, "lights on")
            or self._contains_phrase(text, "light on")
            or text == "on"
        )

    def _is_off_request(self, text: str) -> bool:
        return bool(
            re.search(r"\b(turn|switch|power|put|shut|flip|cut)\b.*\boff\b", text)
            or re.search(r"\b(kill|cut)\b.*\blight", text)
            or self._contains_phrase(text, "lights off")
            or self._contains_phrase(text, "light off")
            or text == "off"
        )

    def _brightness_from_text(self, text: str) -> int | None:
        brightness_terms = (
            "brightness", "bright", "brighter", "brighten", "dim", "dimmer",
            "full", "half", "percent", "maximum", "minimum", "low", "medium",
            "level",
        )
        if not any(self._contains_phrase(text, term) for term in brightness_terms):
            return None

        for phrase, level in BRIGHTNESS_PHRASES:
            if self._contains_phrase(text, phrase):
                return level

        number = self._extract_number(text)
        if number is None:
            return None

        if number <= 100 and not self._is_raw_hue_level(text):
            return self._percent_to_brightness(number)
        return max(1, min(254, int(round(number))))

    def _brightness_arg_to_level(self, raw_arg, text: str = "") -> int | None:
        try:
            number = float(str(raw_arg).strip())
        except (TypeError, ValueError):
            return None
        if number <= 100 and not self._is_raw_hue_level(text):
            return self._percent_to_brightness(number)
        return max(1, min(254, int(round(number))))

    def _is_raw_hue_level(self, text: str) -> bool:
        return any(
            self._contains_phrase(text, phrase)
            for phrase in ("raw", "hue level", "hue value", "level out of 254")
        )

    def _temperature_from_text(self, text: str, capabilities: dict) -> int | None:
        lo = int(capabilities.get("minimum_mireds") or 153)
        hi = int(capabilities.get("maximum_mireds") or 500)
        midpoint = (lo + hi) // 2

        temp_terms = (
            "temperature", "temp", "mired", "kelvin", "warm", "warmer",
            "cool", "cooler", "daylight", "candle", "cozy", "white",
        )
        if not any(self._contains_phrase(text, term) for term in temp_terms):
            return None

        number = self._extract_number(text)
        if number is not None:
            return self._temperature_number_to_mireds(number, capabilities)

        if any(self._contains_phrase(text, phrase) for phrase in ("warm", "warmer", "cozy", "candle")):
            return hi
        if any(self._contains_phrase(text, phrase) for phrase in ("cool", "cooler", "daylight")):
            return lo
        if any(self._contains_phrase(text, phrase) for phrase in ("neutral", "normal", "reading")):
            return midpoint

        return None

    def _temperature_arg_to_mireds(self, raw_arg, capabilities: dict) -> int | None:
        try:
            number = float(str(raw_arg).strip())
        except (TypeError, ValueError):
            return None
        return self._temperature_number_to_mireds(number, capabilities)

    def _temperature_number_to_mireds(self, number: float, capabilities: dict) -> int:
        lo = int(capabilities.get("minimum_mireds") or 153)
        hi = int(capabilities.get("maximum_mireds") or 500)
        if number >= 1000:
            number = round(1000000 / number)
        return max(lo, min(hi, int(round(number))))

    def _color_from_text(self, text: str) -> str | None:
        rgb_match = re.search(
            r"\b(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\b", text
        )
        if rgb_match:
            rgb = [max(0, min(255, int(part))) for part in rgb_match.groups()]
            return ",".join(str(part) for part in rgb)

        color_intent = any(
            self._contains_phrase(text, term)
            for term in ("color", "make it", "set it", "turn it")
        )
        for name, rgb in COLOR_NAMES.items():
            if self._contains_phrase(text, name) and (color_intent or text == name):
                return ",".join(str(part) for part in rgb)
        return None

    def _extract_number(self, text: str) -> float | None:
        digit_match = re.search(r"\b\d+(?:\.\d+)?\b", text)
        if digit_match:
            return float(digit_match.group(0))

        tokens = text.split()
        for idx, token in enumerate(tokens):
            if token in UNITS and idx + 1 < len(tokens) and tokens[idx + 1] == "hundred":
                return float(UNITS[token] * 100)
            if token == "hundred":
                return 100.0
            if token in TENS:
                value = TENS[token]
                if idx + 1 < len(tokens) and tokens[idx + 1] in UNITS:
                    value += UNITS[tokens[idx + 1]]
                return float(value)
            if token in UNITS:
                return float(UNITS[token])
        return None

    @staticmethod
    def _percent_to_brightness(percent: float) -> int:
        percent = max(0, min(100, percent))
        return max(1, min(254, int(round(percent * 254 / 100))))

    def _help_message(self, capabilities: dict) -> str:
        supported = _supported_actions(capabilities)
        options = []
        if "hue_on" in supported and "hue_off" in supported:
            options.append("turn it on or off")
        if "hue_brightness" in supported:
            options.append("set brightness")
        if "hue_color" in supported:
            options.append("change color")
        if "hue_temp" in supported:
            options.append("change warmth")
        options.append("check status")

        if len(options) == 1:
            return f"I can {options[0]}."
        return f"I can {', '.join(options[:-1])}, or {options[-1]}."

    def _capabilities_from_result(self, result) -> dict | None:
        """Returns capability dict on successful connect, None on failure."""
        if not isinstance(result, dict) or not result.get("success"):
            return None
        output = (result.get("output") or "").strip()
        if not output:
            return None
        try:
            payload = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None
        if not payload.get("success"):
            return None
        return payload.get("data") or {}

    def _spoken_response_from_result(self, result) -> str:
        if not isinstance(result, dict):
            return "I couldn't reach the DevKit."
        if not result.get("success"):
            self.worker.editor_logging_handler.error(
                f"DevKit call failed: {result.get('error')}"
            )
            return "Something went wrong while talking to the bulb."
        output = (result.get("output") or "").strip()
        if not output:
            return "I didn't get a response from the bulb."
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            self.worker.editor_logging_handler.error(f"Invalid DevKit output: {output}")
            return "I couldn't read the bulb's response."
        if not payload.get("success"):
            error = payload.get("error") or {}
            self.worker.editor_logging_handler.warning(
                f"Bulb action failed: {error.get('code')} {error.get('message')}"
            )
        return payload.get("spoken_response") or "Done."

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.first_function())
