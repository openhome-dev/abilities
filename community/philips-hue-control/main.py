import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

EXIT_WORDS = {
    "stop",
    "exit",
    "quit",
    "done",
    "cancel",
    "bye",
    "goodbye",
    "that's all",
    "thats all",
}

VOICE_COLORS = {
    "red": (0.675, 0.322),
    "orange": (0.585, 0.390),
    "yellow": (0.484, 0.477),
    "green": (0.210, 0.710),
    "cyan": (0.170, 0.340),
    "blue": (0.139, 0.081),
    "purple": (0.263, 0.126),
    "violet": (0.263, 0.126),
    "magenta": (0.385, 0.155),
    "pink": (0.396, 0.214),
    "white": (0.323, 0.329),
    "sunset": (0.555, 0.380),
    "forest": (0.215, 0.650),
    "ocean": (0.160, 0.220),
    "lavender": (0.310, 0.205),
    "coral": (0.520, 0.330),
    "turquoise": (0.175, 0.360),
    "gold": (0.500, 0.445),
    "lime": (0.350, 0.600),
}

VOICE_TEMPS = {
    "warm": 400,
    "warm white": 370,
    "soft white": 340,
    "neutral": 285,
    "cool": 230,
    "cool white": 200,
    "daylight": 181,
    "bright white": 167,
    "candlelight": 475,
}

PREFS_FILE = "philips_hue_control_prefs.json"

CLASSIFY_PROMPT = """You are a voice command router for Philips Hue smart lights.
Return ONLY valid JSON, no markdown.

Available rooms: {room_names}
Available lights: {light_names}
Available scenes: {scene_names}

User said: "{user_input}"

JSON schema:
{{
  "intent": "turn_on|turn_off|set_brightness|set_color|set_temp|activate_scene|status|list_rooms|list_scenes|all_off|all_on|help|exit|unknown",
  "confidence": 0.0,
  "target_name": "room or light name" or null,
  "target_type": "room|light|all" or null,
  "brightness": 1-100 or null,
  "color": "color name" or null,
  "color_temp": "warm|cool|daylight|candlelight|warm white|cool white|soft white|neutral|bright white" or null,
  "scene_name": "scene name" or null
}}
"""


class PhilipsHueControlCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    bridge_ip: Optional[str] = None
    app_key: Optional[str] = None
    bridge_id: Optional[str] = None

    room_cache: Dict[str, Dict[str, Any]] = {}
    light_cache: Dict[str, Dict[str, Any]] = {}
    scene_cache: Dict[str, Dict[str, Any]] = {}

    last_grouped_light_call: float = 0.0

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def _log_info(self, message: str):
        self.worker.editor_logging_handler.info(f"[PhilipsHueControl] {message}")

    def _log_error(self, message: str):
        self.worker.editor_logging_handler.error(f"[PhilipsHueControl] {message}")

    async def _safe_exit(self, text: str):
        await self.capability_worker.speak(text)

    def _extract_ipv4(self, text: str) -> Optional[str]:
        if not text:
            return None

        # Try direct match first (e.g. "192.168.1.45")
        direct = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text)
        if direct:
            candidate = direct.group(1)
            if self._is_valid_ipv4(candidate):
                return candidate

        # Normalize common speech forms:
        # "192 dot 168 dot 1 dot 45", "192Dot168Dot1Dot45"
        normalized = text.lower()
        normalized = re.sub(r"[^a-z0-9\. ]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        normalized = normalized.replace(" dot ", ".")
        normalized = normalized.replace("dot", ".")
        normalized = normalized.replace(" ", "")

        noisy = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", normalized)
        if noisy:
            candidate = noisy.group(1)
            if self._is_valid_ipv4(candidate):
                return candidate

        return None

    def _is_valid_ipv4(self, ip: str) -> bool:
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(part) <= 255 for part in parts)
        except ValueError:
            return False

    async def _load_prefs(self):
        try:
            if not await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                return
            raw = await self.capability_worker.read_file(PREFS_FILE, False)
            data = json.loads(raw)
            self.bridge_ip = data.get("bridge_ip")
            self.app_key = data.get("app_key")
            self.bridge_id = data.get("bridge_id")
            self.room_cache = data.get("rooms_cache", {})
            self.light_cache = data.get("lights_cache", {})
            self.scene_cache = data.get("scenes_cache", {})
        except Exception as exc:
            self._log_error(f"Failed to load prefs: {exc}")

    async def _save_prefs(self):
        payload = {
            "bridge_ip": self.bridge_ip,
            "app_key": self.app_key,
            "bridge_id": self.bridge_id or "",
            "rooms_cache": self.room_cache,
            "lights_cache": self.light_cache,
            "scenes_cache": self.scene_cache,
            "default_brightness": 100,
            "default_color_temp": 370,
            "transition_ms": 400,
            "times_used": 1,
        }
        try:
            await self.capability_worker.delete_file(PREFS_FILE, False)
            await self.capability_worker.write_file(
                PREFS_FILE, json.dumps(payload), False
            )
        except Exception as exc:
            self._log_error(f"Failed to save prefs: {exc}")

    def _hue_request(
        self, method: str, endpoint: str, body: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Dict[str, Any], str]:
        if not self.bridge_ip or not self.app_key:
            return False, {}, "missing_credentials"
        url = f"https://{self.bridge_ip}/clip/v2/{endpoint.lstrip('/')}"
        headers = {"hue-application-key": self.app_key, "Content-Type": "application/json"}
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=body,
                verify=False,
                timeout=5,
            )
            if response.status_code in (200, 201, 207):
                data = response.json()
                errors = data.get("errors", []) if isinstance(data, dict) else []
                if errors:
                    return False, data, "api_error"
                return True, data, ""
            return (
                False,
                {"status_code": response.status_code, "body": response.text},
                f"http_{response.status_code}",
            )
        except requests.exceptions.Timeout:
            return False, {}, "timeout"
        except requests.exceptions.ConnectionError:
            return False, {}, "connection_failed"
        except Exception as exc:
            self._log_error(f"Hue request exception: {exc}")
            return False, {}, "unexpected_error"

    def _discover_bridges(self) -> List[Dict[str, str]]:
        try:
            response = requests.get("https://discovery.meethue.com", timeout=5)
            if response.status_code == 200:
                bridges = response.json()
                results = []
                for item in bridges:
                    bridge_ip = item.get("internalipaddress")
                    bridge_id = item.get("id")
                    if bridge_ip:
                        results.append({"ip": bridge_ip, "id": bridge_id or ""})
                return results
        except Exception as exc:
            self._log_error(f"Bridge discovery failed: {exc}")
        return []

    def _validate_bridge(self, bridge_ip: str) -> Optional[Dict[str, str]]:
        try:
            response = requests.get(
                f"https://{bridge_ip}/api/0/config", verify=False, timeout=5
            )
            if response.status_code != 200:
                return None
            data = response.json()
            bridge_id = data.get("bridgeid")
            return {
                "bridge_id": bridge_id or "",
                "name": data.get("name", "Hue Bridge"),
                "model": data.get("modelid", ""),
            }
        except Exception as exc:
            self._log_error(f"Bridge validation failed: {exc}")
            return None

    def _create_app_key(self, bridge_ip: str) -> Dict[str, Any]:
        url = f"https://{bridge_ip}/api"
        body = {
            "devicetype": "openhome#philips_hue_control",
            "generateclientkey": True,
        }
        try:
            response = requests.post(url, json=body, verify=False, timeout=5)
            data = response.json()
            if not isinstance(data, list) or not data:
                return {"error": "unexpected_response"}
            first = data[0]
            if "error" in first:
                err = first["error"]
                if err.get("type") == 101:
                    return {"error": "link_button_not_pressed"}
                return {"error": err.get("description", "pairing_failed")}
            if "success" in first and first["success"].get("username"):
                return {
                    "username": first["success"]["username"],
                    "clientkey": first["success"].get("clientkey", ""),
                }
            return {"error": "pairing_failed"}
        except Exception as exc:
            self._log_error(f"App key creation failed: {exc}")
            return {"error": "pairing_failed"}

    def _extract_json(self, text: str) -> Dict[str, Any]:
        if not text:
            return {}
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except Exception:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                return {}
            try:
                return json.loads(match.group(0))
            except Exception:
                return {}

    async def _throttle_grouped_light(self):
        now = time.monotonic()
        elapsed = now - self.last_grouped_light_call
        wait_seconds = 1.0 - elapsed
        if wait_seconds > 0:
            await self.worker.session_tasks.sleep(wait_seconds)
        self.last_grouped_light_call = time.monotonic()

    async def _setup_bridge(self) -> bool:
        await self.capability_worker.speak("Let me find your Hue Bridge.")
        bridge_ip = ""
        bridge_id = ""
        discovered = self._discover_bridges()
        if discovered:
            bridge_ip = discovered[0]["ip"]
            bridge_id = discovered[0]["id"]
        else:
            await self.capability_worker.speak(
                "I couldn't auto-discover a bridge. Please say only your bridge IP address."
            )
            bridge_ip = ""
            for _ in range(3):
                user_ip = await self.capability_worker.user_response()
                parsed_ip = self._extract_ipv4((user_ip or "").strip())
                if parsed_ip:
                    bridge_ip = parsed_ip
                    break
                await self.capability_worker.speak(
                    "I did not catch a valid IP. Please say numbers only, like 192 dot 168 dot 1 dot 45."
                )
            if not bridge_ip:
                await self._safe_exit("Setup cancelled. I still need a valid bridge IP.")
                return False

        details = self._validate_bridge(bridge_ip)
        if not details:
            await self._safe_exit(
                "I could not validate that bridge. Check your network and try again."
            )
            return False

        bridge_id = details.get("bridge_id") or bridge_id
        await self.capability_worker.speak(
            "Press the round button on your Hue Bridge, then say ready."
        )
        readiness = (await self.capability_worker.user_response() or "").lower()
        if "ready" not in readiness:
            await self.capability_worker.speak("I will try pairing now.")

        pair_result = self._create_app_key(bridge_ip)
        if pair_result.get("error") == "link_button_not_pressed":
            await self.capability_worker.speak(
                "I did not detect the button press. Press it once more and say ready."
            )
            await self.capability_worker.user_response()
            pair_result = self._create_app_key(bridge_ip)

        if "username" not in pair_result:
            await self._safe_exit("I couldn't pair with the bridge right now.")
            return False

        self.bridge_ip = bridge_ip
        self.app_key = pair_result["username"]
        self.bridge_id = bridge_id
        await self.build_name_cache()
        await self._save_prefs()
        await self.capability_worker.speak(
            f"Connected. I found {len(self.light_cache)} lights in {len(self.room_cache)} rooms."
        )
        return True

    async def _verify_connection(self) -> bool:
        ok, data, err = self._hue_request("GET", "resource/device")
        if ok and isinstance(data, dict):
            return True
        self._log_error(f"Connection verification failed: {err}")
        return False

    async def build_name_cache(self):
        room_cache: Dict[str, Dict[str, Any]] = {}
        light_cache: Dict[str, Dict[str, Any]] = {}
        scene_cache: Dict[str, Dict[str, Any]] = {}

        ok_rooms, rooms_data, _ = self._hue_request("GET", "resource/room")
        if ok_rooms:
            for room in rooms_data.get("data", []):
                grouped_light_id = ""
                for svc in room.get("services", []):
                    if svc.get("rtype") == "grouped_light":
                        grouped_light_id = svc.get("rid", "")
                        break
                name = room.get("metadata", {}).get("name", "").strip()
                if name:
                    room_cache[name.lower()] = {
                        "id": room.get("id", ""),
                        "name": name,
                        "grouped_light_id": grouped_light_id,
                        "children": room.get("children", []),
                    }

        ok_lights, lights_data, _ = self._hue_request("GET", "resource/light")
        if ok_lights:
            for light in lights_data.get("data", []):
                name = light.get("metadata", {}).get("name", "").strip()
                if name:
                    light_cache[name.lower()] = {
                        "id": light.get("id", ""),
                        "name": name,
                        "owner_rid": light.get("owner", {}).get("rid", ""),
                        "supports_color": "color" in light,
                        "supports_temp": "color_temperature" in light,
                    }

        ok_scenes, scenes_data, _ = self._hue_request("GET", "resource/scene")
        if ok_scenes:
            for scene in scenes_data.get("data", []):
                name = scene.get("metadata", {}).get("name", "").strip()
                if name:
                    scene_cache[name.lower()] = {
                        "id": scene.get("id", ""),
                        "name": name,
                        "room_id": scene.get("group", {}).get("rid", ""),
                    }

        self.room_cache = room_cache
        self.light_cache = light_cache
        self.scene_cache = scene_cache
        await self._save_prefs()

    async def _resolve_name_with_llm(
        self, target_name: str, names: List[str]
    ) -> Optional[str]:
        if not target_name or not names:
            return None
        prompt = (
            "Pick the closest match from this list for the spoken phrase.\n"
            f"Spoken phrase: {target_name}\n"
            f"Choices: {names}\n"
            'Return ONLY JSON: {"match": "<exact choice or null>"}'
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        parsed = self._extract_json(raw)
        match = parsed.get("match")
        if isinstance(match, str) and match.lower() in [n.lower() for n in names]:
            for name in names:
                if name.lower() == match.lower():
                    return name
        return None

    async def resolve_target(
        self, target_name: str, target_type: Optional[str]
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        if not target_name:
            return "", None
        key = target_name.lower().strip()
        if target_type in (None, "room"):
            if key in self.room_cache:
                return "room", self.room_cache[key]
        if target_type in (None, "light"):
            if key in self.light_cache:
                return "light", self.light_cache[key]

        for room_name in self.room_cache:
            if key in room_name or room_name in key:
                return "room", self.room_cache[room_name]
        for light_name in self.light_cache:
            if key in light_name or light_name in key:
                return "light", self.light_cache[light_name]

        candidate_names = list(self.room_cache.keys()) + list(self.light_cache.keys())
        llm_match = await self._resolve_name_with_llm(key, candidate_names)
        if llm_match:
            if llm_match in self.room_cache:
                return "room", self.room_cache[llm_match]
            if llm_match in self.light_cache:
                return "light", self.light_cache[llm_match]
        return "", None

    async def _classify_intent(self, user_input: str) -> Dict[str, Any]:
        lower = user_input.lower().strip()
        if any(word in lower for word in EXIT_WORDS):
            return {"intent": "exit", "confidence": 1.0}
        if "help" in lower:
            return {"intent": "help", "confidence": 1.0}
        if "all" in lower and "off" in lower:
            return {"intent": "all_off", "confidence": 0.9, "target_type": "all"}
        if "all" in lower and "on" in lower:
            return {"intent": "all_on", "confidence": 0.9, "target_type": "all"}

        prompt = CLASSIFY_PROMPT.format(
            room_names=list(self.room_cache.keys()),
            light_names=list(self.light_cache.keys()),
            scene_names=list(self.scene_cache.keys()),
            user_input=user_input,
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        parsed = self._extract_json(raw)
        if parsed.get("intent"):
            return parsed
        return {"intent": "unknown", "confidence": 0.0}

    async def _control_target(
        self,
        resolved_type: str,
        resolved_data: Dict[str, Any],
        *,
        on: Optional[bool] = None,
        brightness: Optional[int] = None,
        color_xy: Optional[Tuple[float, float]] = None,
        mirek: Optional[int] = None,
    ) -> Tuple[bool, str]:
        if resolved_type == "room":
            grouped_light_id = resolved_data.get("grouped_light_id")
            if not grouped_light_id:
                return False, "Room has no grouped light."
            body: Dict[str, Any] = {}
            if on is not None:
                body["on"] = {"on": on}
            if brightness is not None:
                body["dimming"] = {"brightness": max(1, min(100, int(brightness)))}
            if color_xy is not None:
                body["color"] = {"xy": {"x": color_xy[0], "y": color_xy[1]}}
            elif mirek is not None:
                body["color_temperature"] = {"mirek": max(153, min(500, int(mirek)))}
            await self._throttle_grouped_light()
            ok, _, err = self._hue_request(
                "PUT", f"resource/grouped_light/{grouped_light_id}", body
            )
            return ok, err

        if resolved_type == "light":
            light_id = resolved_data.get("id")
            if not light_id:
                return False, "Light missing id."
            body = {}
            if on is not None:
                body["on"] = {"on": on}
            if brightness is not None:
                body["dimming"] = {"brightness": max(1, min(100, int(brightness)))}
            if color_xy is not None:
                if not resolved_data.get("supports_color", False):
                    return False, "color_not_supported"
                body["color"] = {"xy": {"x": color_xy[0], "y": color_xy[1]}}
            elif mirek is not None:
                if not resolved_data.get("supports_temp", False):
                    return False, "temp_not_supported"
                body["color_temperature"] = {"mirek": max(153, min(500, int(mirek)))}
            ok, _, err = self._hue_request("PUT", f"resource/light/{light_id}", body)
            return ok, err
        return False, "unknown_target"

    def _format_targets(self) -> str:
        names = [r["name"] for r in self.room_cache.values()]
        if not names:
            return "none"
        return ", ".join(names[:6])

    async def _handle_all_lights(self, turn_on: bool):
        ok, homes, err = self._hue_request("GET", "resource/bridge_home")
        if not ok:
            await self.capability_worker.speak(
                "I couldn't reach the bridge right now."
            )
            self._log_error(f"bridge_home fetch failed: {err}")
            return
        for home in homes.get("data", []):
            for svc in home.get("services", []):
                if svc.get("rtype") == "grouped_light":
                    await self._throttle_grouped_light()
                    self._hue_request(
                        "PUT",
                        f"resource/grouped_light/{svc.get('rid')}",
                        {"on": {"on": turn_on}},
                    )
                    await self.capability_worker.speak(
                        "All lights on." if turn_on else "All lights off."
                    )
                    return
        await self.capability_worker.speak("I couldn't find your home light group.")

    async def _handle_status(self, target_name: Optional[str], target_type: Optional[str]):
        if not target_name:
            ok, lights, _ = self._hue_request("GET", "resource/light")
            if not ok:
                await self.capability_worker.speak("I couldn't read the light status.")
                return
            total = 0
            on_count = 0
            for light in lights.get("data", []):
                total += 1
                if light.get("on", {}).get("on"):
                    on_count += 1
            await self.capability_worker.speak(f"{on_count} of {total} lights are on.")
            return

        resolved_type, resolved_data = await self.resolve_target(target_name, target_type)
        if not resolved_data:
            await self.capability_worker.speak(
                f"I don't see {target_name}. Rooms: {self._format_targets()}."
            )
            return

        if resolved_type == "light":
            light_id = resolved_data["id"]
            ok, data, _ = self._hue_request("GET", f"resource/light/{light_id}")
            if not ok:
                await self.capability_worker.speak("I couldn't fetch that light status.")
                return
            payload = data.get("data", [{}])[0]
            state = "on" if payload.get("on", {}).get("on") else "off"
            bright = int(payload.get("dimming", {}).get("brightness", 0))
            await self.capability_worker.speak(
                f"{resolved_data['name']} is {state} at {bright} percent."
            )
            return

        if resolved_type == "room":
            child_device_ids = [
                c.get("rid")
                for c in resolved_data.get("children", [])
                if c.get("rtype") == "device"
            ]
            ok, lights, _ = self._hue_request("GET", "resource/light")
            if not ok:
                await self.capability_worker.speak("I couldn't fetch that room status.")
                return
            room_lights = [
                light_item
                for light_item in lights.get("data", [])
                if light_item.get("owner", {}).get("rid") in child_device_ids
            ]
            if not room_lights:
                await self.capability_worker.speak(
                    f"I don't see lights in {resolved_data['name']}."
                )
                return
            on_count = sum(
                1 for light_item in room_lights if light_item.get("on", {}).get("on")
            )
            avg_bright = int(
                sum(
                    light_item.get("dimming", {}).get("brightness", 0)
                    for light_item in room_lights
                )
                / len(room_lights)
            )
            await self.capability_worker.speak(
                f"{resolved_data['name']}: {on_count} of {len(room_lights)} on, about {avg_bright} percent."
            )

    async def _handle_user_command(self, user_input: str):
        parsed = await self._classify_intent(user_input)
        intent = parsed.get("intent", "unknown")
        target_name = parsed.get("target_name")
        target_type = parsed.get("target_type")
        brightness = parsed.get("brightness")
        color = (parsed.get("color") or "").lower() if parsed.get("color") else ""
        color_temp = (
            (parsed.get("color_temp") or "").lower() if parsed.get("color_temp") else ""
        )
        scene_name = parsed.get("scene_name")

        if intent == "exit":
            await self.capability_worker.speak("Lights staying as they are. See you.")
            return True

        if intent == "help":
            await self.capability_worker.speak(
                "Try saying turn off the kitchen, set bedroom to 50 percent, make office blue, or activate movie night."
            )
            return False

        if intent == "list_rooms":
            room_names = [r["name"] for r in self.room_cache.values()]
            if room_names:
                await self.capability_worker.speak(
                    f"You have {len(room_names)} rooms: {', '.join(room_names)}."
                )
            else:
                await self.capability_worker.speak("I couldn't find any rooms.")
            return False

        if intent == "list_scenes":
            scene_names = [s["name"] for s in self.scene_cache.values()]
            if scene_names:
                await self.capability_worker.speak(
                    f"Available scenes: {', '.join(scene_names[:10])}."
                )
            else:
                await self.capability_worker.speak("I couldn't find any scenes.")
            return False

        if intent == "all_off":
            await self._handle_all_lights(turn_on=False)
            return False

        if intent == "all_on":
            await self._handle_all_lights(turn_on=True)
            return False

        if intent == "activate_scene":
            scene_lookup = (scene_name or target_name or "").lower().strip()
            if not scene_lookup:
                await self.capability_worker.speak("Which scene should I activate?")
                return False
            scene = self.scene_cache.get(scene_lookup)
            if not scene:
                for key, item in self.scene_cache.items():
                    if scene_lookup in key or key in scene_lookup:
                        scene = item
                        break
            if not scene:
                await self.capability_worker.speak("I couldn't find that scene.")
                return False
            ok, _, _ = self._hue_request(
                "PUT", f"resource/scene/{scene['id']}", {"recall": {"action": "active"}}
            )
            if ok:
                await self.capability_worker.speak(f"{scene['name']} activated.")
            else:
                await self.capability_worker.speak("I couldn't activate that scene.")
            return False

        if intent == "status":
            await self._handle_status(target_name, target_type)
            return False

        if intent in {"turn_on", "turn_off", "set_brightness", "set_color", "set_temp"}:
            if not target_name and target_type != "all":
                await self.capability_worker.speak(
                    f"Which room or light? Rooms: {self._format_targets()}."
                )
                return False

            resolved_type = "room"
            resolved_data: Optional[Dict[str, Any]] = None
            if target_type == "all":
                await self._handle_all_lights(turn_on=(intent == "turn_on"))
                return False
            if target_name:
                resolved_type, resolved_data = await self.resolve_target(
                    target_name, target_type
                )

            if not resolved_data:
                await self.capability_worker.speak(
                    f"I don't see {target_name}. Try one of: {self._format_targets()}."
                )
                return False

            on_value = None
            bright_value = None
            xy_value = None
            mirek_value = None

            if intent == "turn_on":
                on_value = True
            elif intent == "turn_off":
                on_value = False
            elif intent == "set_brightness":
                if brightness is None:
                    await self.capability_worker.speak("What brightness percent?")
                    return False
                bright_value = max(1, min(100, int(brightness)))
            elif intent == "set_color":
                if not color:
                    await self.capability_worker.speak("Which color should I use?")
                    return False
                xy_value = VOICE_COLORS.get(color)
                if not xy_value:
                    await self.capability_worker.speak(
                        "I don't know that color yet. Try blue, red, green, or purple."
                    )
                    return False
            elif intent == "set_temp":
                if not color_temp:
                    await self.capability_worker.speak("Do you want warm, cool, or daylight?")
                    return False
                mirek_value = VOICE_TEMPS.get(color_temp)
                if mirek_value is None:
                    await self.capability_worker.speak(
                        "Try warm white, cool white, daylight, or candlelight."
                    )
                    return False

            ok, err = await self._control_target(
                resolved_type,
                resolved_data,
                on=on_value,
                brightness=bright_value,
                color_xy=xy_value,
                mirek=mirek_value,
            )
            if ok:
                if intent == "turn_on":
                    await self.capability_worker.speak(f"{resolved_data['name']} on.")
                elif intent == "turn_off":
                    await self.capability_worker.speak(f"{resolved_data['name']} off.")
                elif intent == "set_brightness":
                    await self.capability_worker.speak(
                        f"{resolved_data['name']} at {bright_value} percent."
                    )
                elif intent == "set_color":
                    await self.capability_worker.speak(
                        f"{resolved_data['name']} is now {color}."
                    )
                elif intent == "set_temp":
                    await self.capability_worker.speak(
                        f"{resolved_data['name']} set to {color_temp}."
                    )
            else:
                if err == "color_not_supported":
                    await self.capability_worker.speak(
                        "That light doesn't support color. I can set brightness and white temperature."
                    )
                elif err == "temp_not_supported":
                    await self.capability_worker.speak(
                        "That light doesn't support white temperature."
                    )
                elif err == "connection_failed":
                    await self.capability_worker.speak(
                        "I couldn't reach the Hue Bridge. Check network and power."
                    )
                else:
                    await self.capability_worker.speak("I couldn't apply that command.")
            return False

        await self.capability_worker.speak(
            "Try saying turn off the kitchen, set bedroom to 50 percent, or activate movie night."
        )
        return False

    async def run(self):
        try:
            self._log_info("Ability started")
            await self._load_prefs()

            if not self.bridge_ip or not self.app_key:
                setup_ok = await self._setup_bridge()
                if not setup_ok:
                    return
            else:
                connected = await self._verify_connection()
                if not connected:
                    await self.capability_worker.speak(
                        "I lost bridge connection. Let's pair again."
                    )
                    setup_ok = await self._setup_bridge()
                    if not setup_ok:
                        return
                else:
                    await self.build_name_cache()

            if not self.room_cache and not self.light_cache:
                await self.capability_worker.speak(
                    "Connected, but I couldn't find any lights. Check Hue app setup."
                )
                return

            await self.capability_worker.speak(
                "Hue control ready. What would you like to do?"
            )

            while True:
                user_input = await self.capability_worker.user_response()
                if not user_input or not user_input.strip():
                    await self.capability_worker.speak(
                        "I didn't catch that. Tell me a light command or say stop."
                    )
                    continue

                should_exit = await self._handle_user_command(user_input.strip())
                if should_exit:
                    break
                await self.capability_worker.speak("Anything else?")

        except Exception as exc:
            self._log_error(f"Unexpected run error: {exc}")
            await self.capability_worker.speak(
                "Something went wrong with Hue control. Exiting now."
            )
        finally:
            self._log_info("Ability ended")
            self.capability_worker.resume_normal_flow()
