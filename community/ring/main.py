import json
import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

try:
    from src.agent.capability import MatchingCapability
    from src.main import AgentWorker
    from src.agent.capability_worker import CapabilityWorker
except ImportError:
    # Local testing fallback stubs
    class MatchingCapability:
        pass

    class AgentWorker:
        pass

    class CapabilityWorker:
        pass


# =============================================================================
# Constants (Customize Per Ability)
# =============================================================================

ABILITY_NAMESPACE = "ring"

EXIT_WORDS = {
    "stop", "exit", "quit", "cancel", "bye",
    "never mind", "no thanks", "i'm done", "im done",
}

OAUTH_URL = "https://oauth.ring.com/oauth/token"
API_BASE = "https://api.ring.com/clients_api"
DEVICES_API_BASE = "https://api.ring.com/devices/v1"
CLIENT_ID = "ring_official_android"
USER_AGENT = "OpenHome-Ring/1.0"
TOKENS_FILE = "ring_tokens.json"

MAX_ACTIVITY_DEVICES = 5
SIREN_DURATION_SECONDS = 30

# =============================================================================
# Generic OpenHome Ability Template
# =============================================================================


class RingSecurityAbility(MatchingCapability):
    """
    Ring Security OpenHome Ability (V1).
    Supports authentication, device listing, device health,
    recent activity summaries, last ring queries, floodlight/siren control,
    motion detection toggle, chime test/volume, and motion history.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # --- session state fields (must be declared for sandbox) ---
    devices: dict[str, dict] = {}
    name_map: dict[str, str] = {}
    doorbells: list[str] = []
    cameras: list[str] = []
    chimes: list[str] = []
    pending_action: dict | None = None
    refresh_token: str | None = None
    access_token: str | None = None

    # mock mode
    mock_mode: bool = True
    mock_history: dict[str, list] = {}
    mock_health: dict[str, dict] = {}

    # =========================================================================
    # Registration
    # =========================================================================

    # {{register capability}}

    # =========================================================================
    # Entry Point
    # =========================================================================

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        """
        Main ability lifecycle entry point.
        """

        try:
            self._log("Starting Ring ability session.")

            # Initialize Session State
            self.devices = {}
            self.name_map = {}
            self.doorbells = []
            self.cameras = []
            self.chimes = []
            self.pending_action = None
            self.refresh_token = None
            self.access_token = None

            # 1. Load Tokens
            self._log("Loading stored tokens.")
            await self._load_tokens()

            # 2. Authenticate
            self._log("Authenticating or refreshing token.")
            auth_success = await self._authenticate_or_refresh()

            if not auth_success:
                await self.capability_worker.speak(
                    "Authentication failed. Please try again later."
                )
                self._log_err("Authentication failed during session startup.")
                self.capability_worker.resume_normal_flow()
                return

            # 3. Cache Devices
            self._log("Caching Ring devices for session.")
            cache_success = await self._cache_devices()

            if not cache_success:
                await self.capability_worker.speak(
                    "Ring's servers aren't responding right now. Please try again later."
                )
                self._log_err("Device cache failed. Exiting session.")
                self.capability_worker.resume_normal_flow()
                return

            # 4. Handle Trigger Context
            trigger_context = self._get_trigger_context()

            if trigger_context:
                stripped = self._strip_activation_phrase(trigger_context)

                if self._is_exit(stripped):
                    self._log("Exit detected in trigger context.")
                    self.capability_worker.resume_normal_flow()
                    return

                classification = self._classify(stripped)
                await self._dispatch(classification)

            # 5. Conversation Loop
            await self._conversation_loop(
                skip_greeting=bool(trigger_context)
            )

            # 6. Clean Exit
            self._log("Session completed normally.")
            self.capability_worker.resume_normal_flow()
            return

        except Exception as e:
            self._log_err(f"Unhandled run() exception: {e}")

            try:
                await self.capability_worker.speak(
                    "Something went wrong. Handing you back."
                )
            except Exception:
                pass

            self.capability_worker.resume_normal_flow()

    # =========================================================================
    # Unified Conversation Loop
    # =========================================================================

    async def _conversation_loop(self, skip_greeting: bool = False):
        max_turns = 20
        turn_count = 0
        idle_count = 0

        if not skip_greeting:
            await self.capability_worker.speak(
                "How can I help with your Ring devices?"
            )

        while turn_count < max_turns:

            # Pending State Check
            if self.pending_action:
                user_input = await self.capability_worker.user_response()

                if user_input and self._is_exit(user_input):
                    await self.capability_worker.speak(
                        "Okay, cancelling that request."
                    )
                    self.pending_action = None
                    continue

                await self._handle_pending(user_input)
                turn_count += 1
                continue

            # Collect User Input
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                idle_count += 1
                if idle_count >= 2:
                    break
                continue

            idle_count = 0

            # Deterministic Exit
            if self._is_exit(user_input):
                break

            # Strip Activation Phrase
            cleaned = self._strip_activation_phrase(user_input)

            # Classify Intent
            classification = self._classify(cleaned)

            # Dispatch
            await self._dispatch(classification)

            turn_count += 1

        await self.capability_worker.speak(
            "Let me know if you need anything else."
        )

    # =========================================================================
    # Central Dispatcher
    # =========================================================================

    async def _dispatch(self, classification: dict):
        intent = classification.get("intent")
        device_hint = classification.get("device_hint")

        # Intent: List Devices
        if intent == "list_devices":
            await self._handle_list_devices()
            return

        # Intent: Help
        if intent == "help":
            await self._handle_help()
            return

        # Intent: Activity All Devices (no device resolution)
        if intent == "activity_all":
            await self._handle_activity_all_devices()
            return

        # Intents requiring a doorbot/stickup_cam device
        cam_intents = {
            "device_status", "check_activity", "last_ring",
            "motion_history", "floodlight_on", "floodlight_off",
            "siren_on", "siren_off", "motion_toggle_on", "motion_toggle_off",
        }

        if intent in cam_intents:
            if intent == "last_ring":
                allowed = ["doorbot"]
            else:
                allowed = ["doorbot", "stickup_cam"]
            device_id = await self._resolve_device(device_hint, intent, allowed_types=allowed)

            if device_id is None:
                # Store classifier extras in pending_action if device resolution deferred
                if self.pending_action is not None:
                    self.pending_action["hours"] = classification.get("hours")
                    self.pending_action["volume"] = classification.get("volume")
                return

            if intent == "device_status":
                await self._handle_device_status(device_id)
                return

            if intent == "check_activity":
                await self._handle_check_activity(device_id)
                return

            if intent == "last_ring":
                await self._handle_last_ring(device_id)
                return

            if intent == "motion_history":
                hours = classification.get("hours")
                if hours is None:
                    hours = self._extract_time_window(
                        classification.get("_raw_text", "")
                    )
                await self._handle_motion_history(device_id, hours)
                return

            if intent == "floodlight_on":
                await self._handle_floodlight(device_id, True)
                return

            if intent == "floodlight_off":
                await self._handle_floodlight(device_id, False)
                return

            if intent == "siren_on":
                await self._handle_siren(device_id, True)
                return

            if intent == "siren_off":
                await self._handle_siren(device_id, False)
                return

            if intent == "motion_toggle_on":
                await self._handle_motion_toggle(device_id, True)
                return

            if intent == "motion_toggle_off":
                await self._handle_motion_toggle(device_id, False)
                return

        # Chime intents
        if intent == "chime_test":
            chime_id = await self._resolve_device(device_hint, intent, allowed_types=["chime"])
            if chime_id is None:
                if self.pending_action is not None:
                    self.pending_action["hours"] = classification.get("hours")
                    self.pending_action["volume"] = classification.get("volume")
                return
            await self._handle_chime_test(chime_id)
            return

        if intent == "chime_volume":
            chime_id = await self._resolve_device(device_hint, intent, allowed_types=["chime"])
            if chime_id is None:
                if self.pending_action is not None:
                    self.pending_action["hours"] = classification.get("hours")
                    self.pending_action["volume"] = classification.get("volume")
                return
            volume = classification.get("volume")
            await self._handle_chime_volume(chime_id, volume)
            return

        # Unknown / Fallback
        await self.capability_worker.speak(
            "I can list your Ring devices, check battery and WiFi health, "
            "summarize recent activity, control floodlights and sirens, "
            "toggle motion detection, test your chime, or adjust chime volume."
        )

    async def _cache_devices(self) -> bool:
        """
        Fetch devices and build lookup maps.
        """

        if self.mock_mode:
            self._init_mock_state()
            return True

        data = await self._ring_request_with_retry("ring_devices")

        if not data or not isinstance(data, dict):
            self._log_err("Failed to fetch devices.")
            return False

        try:
            self.devices = {}
            self.name_map = {}
            self.doorbells = []
            self.cameras = []
            self.chimes = []

            type_map = {
                "doorbots": "doorbot",
                "authorized_doorbots": "doorbot",
                "stickup_cams": "stickup_cam",
                "chimes": "chime",
            }

            for key, device_type in type_map.items():
                for device in data.get(key, []):
                    device_id = str(device.get("id"))
                    name = device.get("description", "Unknown device")
                    lower = name.lower()

                    device["_type"] = device_type

                    self.devices[device_id] = device
                    self.name_map[lower] = device_id

                    if device_type == "doorbot":
                        self.doorbells.append(device_id)
                    elif device_type == "stickup_cam":
                        self.cameras.append(device_id)
                    elif device_type == "chime":
                        self.chimes.append(device_id)

            self._log(f"Cached {len(self.devices)} devices.")
            return True

        except Exception as e:
            self._log_err(f"Device cache error: {e}")
            return False

    async def _handle_help(self):
        await self.capability_worker.speak(
            "I can list your Ring devices, check battery and WiFi health, "
            "summarize recent activity, tell you when your doorbell last rang, "
            "show motion history, control floodlights and sirens, "
            "toggle motion detection, test your chime, or adjust chime volume. "
            "What would you like?"
        )

    # =========================================================================
    # LLM Intent Classifier
    # =========================================================================

    def _classify(self, text: str) -> dict[str, Any]:
        system_prompt = (
            "You classify commands for a Ring security assistant.\n"
            "Return ONLY valid JSON. No markdown.\n\n"
            "Schema:\n"
            "{\n"
            '  "intent": "list_devices | device_status | check_activity | activity_all | last_ring | motion_history | floodlight_on | floodlight_off | siren_on | siren_off | motion_toggle_on | motion_toggle_off | chime_test | chime_volume | help | unknown",\n'
            '  "device_hint": string or null,\n'
            '  "hours": number or null,\n'
            '  "volume": number or null\n'
            "}\n\n"
            "Rules:\n"
            "- device_status: battery or WiFi health\n"
            "- check_activity: motion or activity summary for a specific device\n"
            "- activity_all: check activity across ALL devices (no specific device mentioned)\n"
            "- last_ring: last doorbell ring\n"
            "- motion_history: motion history with optional time filter (set hours if mentioned)\n"
            "- floodlight_on/floodlight_off: turn floodlight or spotlight on/off\n"
            "- siren_on/siren_off: activate or deactivate siren\n"
            "- motion_toggle_on/motion_toggle_off: enable or disable motion detection\n"
            "- chime_test: test or play chime sound\n"
            "- chime_volume: set or change chime volume (set volume to the number mentioned)\n"
            "- list_devices: list all devices\n"
            "- help: ask what assistant can do\n"
            "- device_hint must be a DEVICE NAME (e.g. 'front door', 'backyard cam'), not a capability or attribute.\n"
            "- If the user does not mention a specific device by name, set device_hint to null.\n"
            "- Words like 'battery', 'wifi', 'status', 'activity' are NOT device names.\n"
            "- If unsure about intent, return unknown.\n"
        )

        try:
            raw = self.capability_worker.text_to_text_response(
                text,
                system_prompt=system_prompt,
            )

            cleaned = raw.replace("```json", "").replace("```", "").strip()

            parsed = json.loads(cleaned)

            if not isinstance(parsed, dict):
                raise ValueError("Invalid classifier output")

            # Attach raw text for fallback time extraction
            parsed["_raw_text"] = text

            return parsed

        except Exception as e:
            self._log_err(f"Classification failed: {e}")
            return {"intent": "unknown", "device_hint": None, "_raw_text": text}

    # =========================================================================
    # Time Window Extraction
    # =========================================================================

    def _extract_time_window(self, text: str) -> int | None:
        if not text:
            return None
        lower = text.lower()

        # "last N hours" / "past N hours"
        match = re.search(r"(?:last|past)\s+(\d+)\s+hours?", lower)
        if match:
            return int(match.group(1))

        # "last hour" / "past hour"
        if re.search(r"(?:last|past)\s+hour\b", lower):
            return 1

        # "last day" / "past day"
        if re.search(r"(?:last|past)\s+day\b", lower):
            return 24

        return None

    # =========================================================================
    # Utilities
    # =========================================================================

    def _get_trigger_context(self) -> str:
        try:
            history = self.worker.agent_memory.full_message_history
            if not history:
                return ""

            for msg in reversed(history):
                if msg.get("role") == "user":
                    return msg.get("content", "")
            return ""

        except Exception:
            return ""

    def _is_exit(self, text: str) -> bool:
        if not text:
            return False
        normalized = text.lower().strip()
        normalized = re.sub(r"[^\w\s']", " ", normalized)
        normalized = " ".join(normalized.split())
        return normalized in EXIT_WORDS

    def _strip_activation_phrase(self, text: str) -> str:
        if not text:
            return text

        lowered = text.lower()

        if hasattr(self, "matching_hotwords") and self.matching_hotwords:
            for hotword in self.matching_hotwords:
                hw = hotword.lower()
                if lowered.startswith(hw):
                    return text[len(hotword):].strip(" .,")

        return text

    def _format_relative_time(self, iso_string: str) -> str:
        try:
            if iso_string.endswith("Z"):
                iso_string = iso_string.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_string)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            seconds = int(delta.total_seconds())
            if seconds < 60:
                return "just now"
            minutes = seconds // 60
            if minutes < 60:
                return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
            hours = minutes // 60
            if hours < 24:
                return f"{hours} hour{'s' if hours != 1 else ''} ago"
            days = hours // 24
            if days == 1:
                return "Yesterday"
            if days < 7:
                return f"{days} days ago"
            if days < 30:
                weeks = days // 7
                return f"{weeks} week{'s' if weeks != 1 else ''} ago"
            if days < 365:
                months = days // 30
                return f"{months} month{'s' if months != 1 else ''} ago"
            years = days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"
        except Exception:
            try:
                dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
                return dt.strftime("on %B %d, %Y")
            except Exception:
                return iso_string

    def _log(self, msg: str):
        self.worker.editor_logging_handler.info(
            f"[{ABILITY_NAMESPACE}] {msg}"
        )

    def _log_err(self, msg: str):
        self.worker.editor_logging_handler.error(
            f"[{ABILITY_NAMESPACE}] {msg}"
        )

    async def _resolve_device(
        self,
        device_hint: str | None,
        intent: str,
        allowed_types: list[str] | None = None,
    ) -> str | None:
        """
        Resolve a device hint to a device_id.
        If allowed_types is provided, only consider devices whose _type matches.
        """

        # Build filtered device set
        if allowed_types:
            filtered_ids = [
                did for did, dev in self.devices.items()
                if dev.get("_type") in allowed_types
            ]
            filtered_name_map = {
                name: did for name, did in self.name_map.items()
                if did in filtered_ids
            }
        else:
            filtered_ids = list(self.devices.keys())
            filtered_name_map = dict(self.name_map)

        if not filtered_ids:
            type_label = ", ".join(allowed_types) if allowed_types else "any"
            await self.capability_worker.speak(
                f"I couldn't find any {type_label} devices on your account."
            )
            return None

        # No Hint Provided
        if not device_hint:
            if len(filtered_ids) == 1:
                return filtered_ids[0]

            available_names = [
                self.devices[did].get("description", "Unknown device")
                for did in filtered_ids
            ]
            await self.capability_worker.speak(
                "Which device are you asking about? You have: "
                + ", ".join(available_names) + "."
            )

            self.pending_action = {
                "type": "clarify_device",
                "intent": intent,
                "candidates": filtered_ids,
            }

            return None

        normalized = device_hint.lower().strip()

        # Exact Match
        if normalized in filtered_name_map:
            return filtered_name_map[normalized]

        # Partial Match
        matches = []

        for name, device_id in filtered_name_map.items():
            if normalized in name:
                matches.append(device_id)

        if len(matches) == 1:
            return matches[0]

        # Ambiguous Match
        if len(matches) > 1:
            device_names = [
                self.devices[d]["description"]
                for d in matches
            ]

            await self.capability_worker.speak(
                "I found multiple devices: "
                + ", ".join(device_names)
                + ". Which one did you mean?"
            )

            self.pending_action = {
                "type": "clarify_device",
                "intent": intent,
                "candidates": matches,
            }

            return None

        # No Match Found
        available_names = [
            self.devices[did].get("description", "Unknown device")
            for did in filtered_ids
        ]

        await self.capability_worker.speak(
            "I couldn't find that device. Which one did you mean? You have: "
            + ", ".join(available_names)
            + "."
        )

        # IMPORTANT:
        # We intentionally set pending_action on no-match so that a follow-up
        # like "Front door" is treated as a clarification response rather
        # than going through full classification again.
        self.pending_action = {
            "type": "clarify_device",
            "intent": intent,
            "candidates": filtered_ids,
        }

        return None

    async def _handle_pending(self, user_input: str | None):
        if not self.pending_action:
            return

        pending_type = self.pending_action.get("type")

        # Device Clarification Flow
        if pending_type == "clarify_device":

            candidates = self.pending_action.get("candidates", [])
            intent = self.pending_action.get("intent")
            hours = self.pending_action.get("hours")
            volume = self.pending_action.get("volume")

            if not isinstance(candidates, list):
                self._log_err(f"clarify_device bad candidates: {candidates!r}")
                if candidates is None:
                    candidates = []
                else:
                    candidates = [str(candidates)]

            self._log(f"clarify_device: intent={intent!r}, candidates={len(candidates)}")

            if not intent:
                self._log_err("clarify_device missing intent")

            if not user_input:
                await self.capability_worker.speak(
                    "Please tell me which device you meant."
                )
                return

            normalized = user_input.lower().strip()
            normalized = re.sub(r"[^\w\s']", " ", normalized)
            normalized = " ".join(normalized.split())

            if not normalized:
                await self.capability_worker.speak(
                    "Please tell me which device you meant."
                )
                return

            # PASS 1 — Exact match only
            for device_id in candidates:
                device = self.devices.get(device_id)
                if not device:
                    continue

                device_name = device.get("description", "").lower()
                if normalized == device_name:
                    self._log(f"clarify_device resolved exact: {device_id!r}")
                    self.pending_action = None
                    await self._route_device_intent(intent, device_id, hours=hours, volume=volume)
                    return

            # PASS 2 — Partial match (substring)
            matches = []
            for device_id in candidates:
                device = self.devices.get(device_id)
                if not device:
                    continue

                device_name = device.get("description", "").lower()
                if normalized in device_name:
                    matches.append(device_id)

            if len(matches) == 1:
                self._log(f"clarify_device resolved partial: {matches[0]!r}")
                self.pending_action = None
                await self._route_device_intent(intent, matches[0], hours=hours, volume=volume)
                return

            if len(matches) > 1:
                device_names = [
                    self.devices[d]["description"]
                    for d in matches
                ]

                await self.capability_worker.speak(
                    "I still found multiple matches: "
                    + ", ".join(device_names)
                    + ". Please be more specific."
                )

                self.pending_action["candidates"] = matches
                return

            # No Match
            device_names = [
                self.devices[did].get("description", "Unknown device")
                for did in candidates
                if self.devices.get(did)
            ]

            await self.capability_worker.speak(
                "I couldn't match that to a device. You can choose from: "
                + ", ".join(device_names)
                + "."
            )

            return

        # Chime Volume Follow-up
        if pending_type == "chime_volume_followup":
            chime_id = self.pending_action.get("device_id")

            if not user_input:
                await self.capability_worker.speak(
                    "Please specify a volume level from 0 to 10."
                )
                return

            parsed_volume = self._parse_volume_input(user_input)
            if parsed_volume is None:
                await self.capability_worker.speak(
                    "I need a number between 0 and 10. What volume level would you like?"
                )
                return

            self.pending_action = None
            await self._handle_chime_volume(chime_id, parsed_volume)
            return

        if pending_type:
            self._log_err(f"Unhandled pending_action type: {pending_type!r}")

    async def _route_device_intent(
        self,
        intent: str,
        device_id: str,
        hours: int | None = None,
        volume: int | None = None,
    ):
        """
        Route a resolved device_id to the correct handler
        based on stored intent.
        """

        if intent == "device_status":
            await self._handle_device_status(device_id)
            return

        if intent == "check_activity":
            await self._handle_check_activity(device_id)
            return

        if intent == "last_ring":
            await self._handle_last_ring(device_id)
            return

        if intent == "motion_history":
            await self._handle_motion_history(device_id, hours)
            return

        if intent == "floodlight_on":
            await self._handle_floodlight(device_id, True)
            return

        if intent == "floodlight_off":
            await self._handle_floodlight(device_id, False)
            return

        if intent == "siren_on":
            await self._handle_siren(device_id, True)
            return

        if intent == "siren_off":
            await self._handle_siren(device_id, False)
            return

        if intent == "motion_toggle_on":
            await self._handle_motion_toggle(device_id, True)
            return

        if intent == "motion_toggle_off":
            await self._handle_motion_toggle(device_id, False)
            return

        if intent == "chime_test":
            await self._handle_chime_test(device_id)
            return

        if intent == "chime_volume":
            await self._handle_chime_volume(device_id, volume)
            return

        # Fallback safety
        await self.capability_worker.speak(
            "Something went wrong routing your request."
        )

    async def _load_tokens(self):
        self.refresh_token = None
        self.access_token = None

        try:
            exists = await self.capability_worker.check_if_file_exists(
                TOKENS_FILE, False
            )

            if not exists:
                return

            raw = await self.capability_worker.read_file(
                TOKENS_FILE, False
            )

            if not raw:
                return

            data = json.loads(raw)

            self.refresh_token = data.get("refresh_token")
            self.access_token = data.get("access_token")

            self._log("Tokens loaded from storage.")

        except Exception as e:
            self._log_err(f"Token load failed (non-fatal): {e}")

    async def _save_tokens(self, refresh_token: str, access_token: str):
        try:
            exists = await self.capability_worker.check_if_file_exists(
                TOKENS_FILE, False
            )

            if exists:
                await self.capability_worker.delete_file(
                    TOKENS_FILE, False
                )

            payload = {
                "refresh_token": refresh_token,
                "access_token": access_token,
                "last_refresh": datetime.now(timezone.utc).isoformat()
            }

            await self.capability_worker.write_file(
                TOKENS_FILE,
                json.dumps(payload),
                False
            )

            self._log("Tokens persisted successfully.")

        except Exception as e:
            self._log_err(f"Token save failed: {e}")

    async def _authenticate_or_refresh(self) -> bool:
        if self.mock_mode:
            self._log("Mock auth success.")
            self.access_token = "mock_token"
            return True

        if self.refresh_token:
            self._log("Attempting token refresh.")
            success = await self._refresh_token(self.refresh_token)
            if success:
                return True

            self._log("Refresh failed. Proceeding to full auth.")

        return await self._full_auth_flow()

    async def _refresh_token(self, refresh_token: str) -> bool:
        try:
            response = await asyncio.to_thread(
                requests.post,
                OAUTH_URL,
                data={
                    "client_id": CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )

            if response.status_code != 200:
                self._log_err(
                    f"Refresh failed with status {response.status_code}"
                )
                return False

            data = response.json()

            new_refresh = data.get("refresh_token")
            new_access = data.get("access_token")

            if not new_refresh or not new_access:
                self._log_err("Refresh response missing tokens.")
                return False

            self.refresh_token = new_refresh
            self.access_token = new_access

            await self._save_tokens(new_refresh, new_access)

            self._log("Token refresh successful.")
            return True

        except Exception as e:
            self._log_err(f"Refresh exception: {e}")
            return False

    async def _full_auth_flow(self) -> bool:
        try:
            await self.capability_worker.speak(
                "To connect your Ring account, please type your Ring email into the chat."
            )

            email = await self.capability_worker.user_response()

            if not email:
                return False

            confirmed = await self.capability_worker.run_confirmation_loop(
                f"I got {email}. Is that correct?"
            )

            if not confirmed:
                return False

            await self.capability_worker.speak(
                "Please type your Ring password into the chat. "
                "Note that your password will be visible in the chat. "
                "It will not be stored or logged by this ability."
            )

            password = await self.capability_worker.user_response()

            if not password:
                return False

            response = await asyncio.to_thread(
                requests.post,
                OAUTH_URL,
                data={
                    "client_id": CLIENT_ID,
                    "grant_type": "password",
                    "username": email,
                    "password": password,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )

            # 2FA required
            if response.status_code == 412:
                await self.capability_worker.speak(
                    "Please type your two-factor authentication code into the chat."
                )

                code = await self.capability_worker.user_response()

                if not code:
                    await self.capability_worker.speak(
                        "No code received. Authentication cancelled."
                    )
                    return False

                response = await asyncio.to_thread(
                    requests.post,
                    OAUTH_URL,
                    data={
                        "client_id": CLIENT_ID,
                        "grant_type": "password",
                        "username": email,
                        "password": password,
                    },
                    headers={
                        "User-Agent": USER_AGENT,
                        "2fa-support": "true",
                        "2fa-code": code,
                    },
                    timeout=10,
                )

                # Single Retry for Incorrect 2FA Code
                if response.status_code != 200:
                    await self.capability_worker.speak(
                        "That code didn't work. Please type your two-factor authentication code again."
                    )

                    retry_code = await self.capability_worker.user_response()

                    if not retry_code:
                        await self.capability_worker.speak(
                            "No code received. Authentication cancelled."
                        )
                        return False

                    response = await asyncio.to_thread(
                        requests.post,
                        OAUTH_URL,
                        data={
                            "client_id": CLIENT_ID,
                            "grant_type": "password",
                            "username": email,
                            "password": password,
                        },
                        headers={
                            "User-Agent": USER_AGENT,
                            "2fa-support": "true",
                            "2fa-code": retry_code,
                        },
                        timeout=10,
                    )

            if response.status_code != 200:
                self._log_err(
                    f"Full auth failed with status {response.status_code}"
                )
                await self.capability_worker.speak(
                    "Authentication failed. Please check your credentials."
                )
                return False

            data = response.json()

            refresh_token = data.get("refresh_token")
            access_token = data.get("access_token")

            if not refresh_token or not access_token:
                self._log_err("Full auth response missing tokens.")
                return False

            self.refresh_token = refresh_token
            self.access_token = access_token

            await self._save_tokens(refresh_token, access_token)

            await self.capability_worker.speak(
                "Your Ring account is now connected."
            )

            return True

        except Exception as e:
            self._log_err(f"Full auth exception: {e}")
            await self.capability_worker.speak(
                "Authentication failed due to a network error."
            )
            return False

    # =========================================================================
    # Ring API Request with Retry
    # =========================================================================

    async def _ring_request_with_retry(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict | None = None,
        params: dict | None = None,
        base_override: str | None = None,
        force_null_body: bool = False,
    ) -> dict | list | None:
        """
        Make a Ring API request with a single refresh retry on 401.
        Supports GET, POST, PUT, PATCH.
        """

        if self.mock_mode:
            return self._mock_api_response(endpoint, method)

        if not self.access_token:
            self._log_err("No access token available for API request.")
            return None

        base = base_override if base_override else API_BASE
        url = f"{base}/{endpoint}"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": USER_AGENT,
        }

        self._log(f"Calling Ring API: {method} {endpoint}")

        async def _perform_request():
            upper = method.upper()

            if upper == "GET":
                return await asyncio.to_thread(
                    requests.get,
                    url,
                    headers=headers,
                    params=params,
                    timeout=10,
                )
            elif upper == "POST":
                kwargs = {
                    "headers": headers,
                    "params": params,
                    "timeout": 10,
                }
                if data is not None:
                    kwargs["json"] = data
                return await asyncio.to_thread(
                    requests.post,
                    url,
                    **kwargs,
                )
            elif upper == "PUT":
                if force_null_body:
                    put_headers = dict(headers)
                    put_headers["Content-Type"] = "application/json"
                    return await asyncio.to_thread(
                        requests.put,
                        url,
                        headers=put_headers,
                        params=params,
                        data="null",
                        timeout=10,
                    )
                else:
                    kwargs = {
                        "headers": headers,
                        "params": params,
                        "timeout": 10,
                    }
                    if data is not None:
                        kwargs["json"] = data
                    return await asyncio.to_thread(
                        requests.put,
                        url,
                        **kwargs,
                    )
            elif upper == "PATCH":
                kwargs = {
                    "headers": headers,
                    "params": params,
                    "timeout": 10,
                }
                if data is not None:
                    kwargs["json"] = data
                return await asyncio.to_thread(
                    requests.patch,
                    url,
                    **kwargs,
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

        try:
            response = await _perform_request()

            # If Unauthorized -> Attempt Refresh
            if response.status_code == 401:
                self._log("401 received. Attempting token refresh.")

                refresh_success = await self._refresh_token(
                    self.refresh_token
                )

                if not refresh_success:
                    self._log_err("Token refresh failed after 401.")
                    await self.capability_worker.speak(
                        "I need to reconnect to Ring. Please start a new session."
                    )
                    return None

                headers["Authorization"] = (
                    f"Bearer {self.access_token}"
                )

                response = await _perform_request()

                if response.status_code == 401:
                    self._log_err("Second 401 after refresh.")
                    await self.capability_worker.speak(
                        "I need to reconnect to Ring. Please start a new session."
                    )
                    return None

            # 204 No Content is success for PUT/PATCH commands
            if response.status_code == 204:
                return {}

            # Non-success errors
            if response.status_code not in (200, 201):
                self._log_err(
                    f"API error {response.status_code} on {endpoint}"
                )
                return None

            # Parse JSON
            try:
                return response.json()
            except Exception as parse_err:
                self._log_err(
                    f"JSON parse error on {endpoint}: {parse_err}"
                )
                return None

        except Exception as e:
            self._log_err(f"API request exception on {endpoint}: {e}")
            await self.capability_worker.speak(
                "Ring's servers aren't responding right now."
            )
            return None

    # =========================================================================
    # Confirmation Helper
    # =========================================================================

    async def _confirm_action(self, prompt: str) -> bool:
        return await self.capability_worker.run_confirmation_loop(prompt)

    # =========================================================================
    # MOCK IMPLEMENTATION
    # =========================================================================

    def _init_mock_state(self):
        self._log("Initializing mock Ring state.")
        self.mock_history = {}
        self.mock_health = {}

        mock_devices_doorbots = [
            {"id": "1", "description": "Front Door", "kind": "doorbot"},
        ]

        mock_devices_stickup = [
            {"id": "2", "description": "Backyard Cam", "kind": "stickup_cam"},
        ]

        mock_devices_chimes = [
            {"id": "3", "description": "Hallway Chime", "kind": "chime",
             "settings": {"volume": 5}},
        ]

        self.devices = {}
        self.name_map = {}
        self.doorbells = []
        self.cameras = []
        self.chimes = []

        for d in mock_devices_doorbots:
            device_id = d["id"]
            d["_type"] = "doorbot"
            self.devices[device_id] = d
            self.name_map[d["description"].lower()] = device_id
            self.doorbells.append(device_id)

        for d in mock_devices_stickup:
            device_id = d["id"]
            d["_type"] = "stickup_cam"
            self.devices[device_id] = d
            self.name_map[d["description"].lower()] = device_id
            self.cameras.append(device_id)

        for d in mock_devices_chimes:
            device_id = d["id"]
            d["_type"] = "chime"
            self.devices[device_id] = d
            self.name_map[d["description"].lower()] = device_id
            self.chimes.append(device_id)

        self.mock_history = {
            "1": [
                {"kind": "ding", "created_at": "2026-01-01T12:00:00Z"},
                {"kind": "motion", "created_at": "2026-01-01T10:00:00Z"},
            ],
            "2": [
                {"kind": "motion", "created_at": "2026-01-02T09:00:00Z"}
            ],
        }

        self.mock_health = {
            "1": {
                "device_health": {
                    "battery_percentage": 85,
                    "latest_signal_strength": -58,
                }
            },
            "2": {
                "device_health": {
                    "battery_percentage": 62,
                    "latest_signal_strength": -72,
                }
            },
            "3": {
                "device_health": {
                    "wifi_name": "ring_mock_wifi",
                    "latest_signal_strength": -61,
                    "latest_signal_category": "good",
                }
            },
        }

    def _mock_api_response(self, endpoint: str, method: str = "GET"):
        """
        Return fake responses matching Ring API structure.
        """

        if endpoint == "ring_devices":
            return {
                "doorbots": [self.devices["1"]],
                "authorized_doorbots": [],
                "stickup_cams": [self.devices["2"]],
                "chimes": [self.devices["3"]],
            }

        # Health endpoints
        if endpoint.startswith("doorbots/") and endpoint.endswith("/health"):
            device_id = endpoint.split("/")[1]
            return self.mock_health.get(device_id)

        if endpoint.startswith("chimes/") and endpoint.endswith("/health"):
            device_id = endpoint.split("/")[1]
            return self.mock_health.get(device_id)

        # History
        if "history" in endpoint:
            device_id = endpoint.split("/")[1]
            return self.mock_history.get(device_id, [])

        # Floodlight on/off
        if "floodlight_light_on" in endpoint or "floodlight_light_off" in endpoint:
            return {}

        # Siren on/off
        if "siren_on" in endpoint or "siren_off" in endpoint:
            return {}

        # Motion toggle (devices/{id}/settings via PATCH)
        if "settings" in endpoint:
            return {}

        # Chime play_sound
        if "play_sound" in endpoint:
            return {}

        # Chime volume update (PUT chimes/{id})
        if endpoint.startswith("chimes/") and "/" not in endpoint.split("chimes/")[1]:
            return {}

        return None

    # =========================================================================
    # Device Handlers
    # =========================================================================

    async def _handle_device_status(self, device_id: str):
        device = self.devices.get(device_id)

        if not device:
            self._log_err(f"Device {device_id} not found in cache.")
            await self.capability_worker.speak(
                "That device may be offline."
            )
            return

        device_name = device.get("description", "Your device")

        endpoint = f"doorbots/{device_id}/health"

        data = await self._ring_request_with_retry(endpoint)

        if not data:
            return

        try:
            health = data.get("device_health", {})

            battery = health.get("battery_percentage")
            rssi = health.get("latest_signal_strength")

            if battery is not None:
                battery_text = (
                    f"{device_name} battery is at {battery} percent."
                )
            else:
                battery_text = (
                    f"I couldn't determine the battery level for {device_name}."
                )

            signal_text = ""

            if isinstance(rssi, (int, float)):
                signal_label = self._rssi_to_label(rssi)
                signal_text = f" WiFi signal is {signal_label.lower()}."

            await self.capability_worker.speak(
                battery_text + signal_text
            )

        except Exception as e:
            self._log_err(f"Device status parse error: {e}")
            await self.capability_worker.speak(
                "I couldn't retrieve the device status."
            )

    def _rssi_to_label(self, rssi: float) -> str:
        if rssi >= -50:
            return "Excellent"
        if rssi >= -60:
            return "Good"
        if rssi >= -70:
            return "Fair"
        if rssi >= -80:
            return "Weak"
        return "Very weak"

    async def _handle_list_devices(self):
        try:
            if not self.devices:
                self._log("No devices found in cache.")
                await self.capability_worker.speak(
                    "I couldn't find any Ring devices on your account."
                )
                return

            device_names = [
                d.get("description", "Unknown device")
                for d in self.devices.values()
            ]

            count = len(device_names)

            if count == 1:
                await self.capability_worker.speak(
                    f"You have one Ring device: {device_names[0]}."
                )
                return

            if count == 2:
                joined = f"{device_names[0]} and {device_names[1]}"
            else:
                joined = ", ".join(device_names[:-1]) + f", and {device_names[-1]}"

            await self.capability_worker.speak(
                f"You have {count} Ring devices: {joined}."
            )

        except Exception as e:
            self._log_err(f"List devices error: {e}")
            await self.capability_worker.speak(
                "I couldn't retrieve your device list."
            )

    async def _handle_check_activity(self, device_id: str):
        device = self.devices.get(device_id)

        if not device:
            self._log_err(f"Device {device_id} not found in cache.")
            await self.capability_worker.speak(
                "That device may be offline."
            )
            return

        device_name = device.get("description", "That device")

        endpoint = f"doorbots/{device_id}/history"

        data = await self._ring_request_with_retry(endpoint, params={"limit": 10})

        if data is None:
            return

        try:
            if not isinstance(data, list):
                self._log_err("Unexpected history response format.")
                await self.capability_worker.speak(
                    "I couldn't retrieve recent activity."
                )
                return

            if not data:
                await self.capability_worker.speak(
                    f"No recent activity at {device_name}."
                )
                return

            motion_count = 0
            ring_count = 0
            most_recent_time = None

            for event in data:
                kind = event.get("kind")
                created_at = event.get("created_at")

                if kind == "motion":
                    motion_count += 1
                elif kind == "ding":
                    ring_count += 1

                if created_at:
                    if not most_recent_time or created_at > most_recent_time:
                        most_recent_time = created_at

            if motion_count == 0 and ring_count == 0:
                await self.capability_worker.speak(
                    f"No recent activity at {device_name}."
                )
                return

            parts = []

            if motion_count:
                parts.append(
                    f"{motion_count} motion event"
                    + ("s" if motion_count != 1 else "")
                )

            if ring_count:
                parts.append(
                    f"{ring_count} ring"
                    + ("s" if ring_count != 1 else "")
                )

            summary = " and ".join(parts)

            if most_recent_time:
                relative = self._format_relative_time(most_recent_time)
                await self.capability_worker.speak(
                    f"In the last 10 events, {summary}. The most recent was {relative}."
                )
            else:
                await self.capability_worker.speak(
                    f"In the last 10 events, {summary}."
                )

        except Exception as e:
            self._log_err(f"Activity parsing error: {e}")
            await self.capability_worker.speak(
                "I couldn't retrieve recent activity."
            )

    async def _handle_last_ring(self, device_id: str):
        device = self.devices.get(device_id)

        if not device:
            self._log_err(f"Device {device_id} not found in cache.")
            await self.capability_worker.speak(
                "That device may be offline."
            )
            return

        device_name = device.get("description", "That device")
        device_type = device.get("_type", "")

        if device_type == "stickup_cam":
            await self.capability_worker.speak(
                f"{device_name} is a camera, not a doorbell. It doesn't have ring events, but I can check its activity if you like."
            )
            return

        endpoint = f"doorbots/{device_id}/history"

        data = await self._ring_request_with_retry(endpoint, params={"limit": 10})

        if data is None:
            return

        try:
            if not isinstance(data, list):
                self._log_err("Unexpected history response format.")
                await self.capability_worker.speak(
                    "I couldn't retrieve ring history."
                )
                return

            ring_events = [
                event for event in data
                if event.get("kind") == "ding"
            ]

            if not ring_events:
                await self.capability_worker.speak(
                    f"There haven't been any recent rings at {device_name}."
                )
                return

            ring_events.sort(
                key=lambda e: e.get("created_at", ""),
                reverse=True,
            )

            most_recent = ring_events[0]
            created_at = most_recent.get("created_at")

            if not created_at:
                await self.capability_worker.speak(
                    f"There was a recent ring at {device_name}, but I couldn't determine when."
                )
                return

            relative = self._format_relative_time(created_at)

            await self.capability_worker.speak(
                f"The last ring at {device_name} was {relative}."
            )

        except Exception as e:
            self._log_err(f"Last ring parsing error: {e}")
            await self.capability_worker.speak(
                "I couldn't retrieve the last ring information."
            )

    # =========================================================================
    # New V1 Handlers
    # =========================================================================

    async def _handle_activity_all_devices(self):
        """Check activity across all doorbots and stickup cams."""
        cam_ids = [
            did for did, dev in self.devices.items()
            if dev.get("_type") in ("doorbot", "stickup_cam")
        ]

        if not cam_ids:
            await self.capability_worker.speak(
                "You don't have any cameras or doorbells to check."
            )
            return

        capped = len(cam_ids) > MAX_ACTIVITY_DEVICES
        check_ids = cam_ids[:MAX_ACTIVITY_DEVICES]

        total_motion = 0
        total_dings = 0
        most_recent_time = None

        for device_id in check_ids:
            endpoint = f"doorbots/{device_id}/history"
            data = await self._ring_request_with_retry(endpoint, params={"limit": 10})

            if data is None or not isinstance(data, list):
                continue

            for event in data:
                kind = event.get("kind")
                created_at = event.get("created_at")

                if kind == "motion":
                    total_motion += 1
                elif kind == "ding":
                    total_dings += 1

                if created_at:
                    if not most_recent_time or created_at > most_recent_time:
                        most_recent_time = created_at

        if total_motion == 0 and total_dings == 0:
            await self.capability_worker.speak(
                "No recent activity across your devices."
            )
            return

        parts = []
        if total_motion:
            parts.append(
                f"{total_motion} motion event"
                + ("s" if total_motion != 1 else "")
            )
        if total_dings:
            parts.append(
                f"{total_dings} ring"
                + ("s" if total_dings != 1 else "")
            )

        summary = " and ".join(parts)

        msg = f"Across your devices, {summary}."

        if most_recent_time:
            relative = self._format_relative_time(most_recent_time)
            msg += f" The most recent was {relative}."

        if capped:
            msg += f" I checked your first {MAX_ACTIVITY_DEVICES} devices."

        await self.capability_worker.speak(msg)

    async def _handle_motion_history(self, device_id: str, hours: int | None):
        """Fetch motion history for a device with optional time filter."""
        device = self.devices.get(device_id)

        if not device:
            self._log_err(f"Device {device_id} not found in cache.")
            await self.capability_worker.speak("That device may be offline.")
            return

        device_name = device.get("description", "That device")

        endpoint = f"doorbots/{device_id}/history"
        data = await self._ring_request_with_retry(endpoint, params={"limit": 30})

        if data is None:
            return

        try:
            if not isinstance(data, list):
                self._log_err("Unexpected history response format.")
                await self.capability_worker.speak(
                    "I couldn't retrieve motion history."
                )
                return

            motion_events = [e for e in data if e.get("kind") == "motion"]

            # Time filter
            if hours is not None and hours > 0:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
                filtered = []
                for event in motion_events:
                    created_at = event.get("created_at", "")
                    try:
                        if created_at.endswith("Z"):
                            created_at = created_at.replace("Z", "+00:00")
                        dt = datetime.fromisoformat(created_at)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt >= cutoff:
                            filtered.append(event)
                    except Exception:
                        continue
                motion_events = filtered

            if not motion_events:
                if hours:
                    await self.capability_worker.speak(
                        f"No motion at {device_name} in the last {hours} hour{'s' if hours != 1 else ''}."
                    )
                else:
                    await self.capability_worker.speak(
                        f"No recent motion at {device_name}."
                    )
                return

            count = len(motion_events)

            # Find most recent
            motion_events.sort(
                key=lambda e: e.get("created_at", ""),
                reverse=True,
            )
            most_recent = motion_events[0].get("created_at")

            msg = f"{count} motion event{'s' if count != 1 else ''} at {device_name}"

            if hours:
                msg += f" in the last {hours} hour{'s' if hours != 1 else ''}"

            msg += "."

            if most_recent:
                relative = self._format_relative_time(most_recent)
                msg += f" The most recent was {relative}."

            await self.capability_worker.speak(msg)

        except Exception as e:
            self._log_err(f"Motion history error: {e}")
            await self.capability_worker.speak(
                "I couldn't retrieve motion history."
            )

    async def _handle_floodlight(self, device_id: str, turn_on: bool):
        """Turn floodlight on or off."""
        device = self.devices.get(device_id)
        device_name = device.get("description", "Your device") if device else "Your device"

        state = "on" if turn_on else "off"
        endpoint = f"doorbots/{device_id}/floodlight_light_{state}"

        result = await self._ring_request_with_retry(
            endpoint, method="PUT", force_null_body=True,
        )

        if result is not None:
            await self.capability_worker.speak(
                f"Floodlight turned {state} for {device_name}."
            )
        else:
            await self.capability_worker.speak(
                f"I couldn't turn the floodlight {state} for {device_name}."
            )

    async def _handle_siren(self, device_id: str, turn_on: bool):
        """Activate or deactivate siren. Requires confirmation for activation."""
        device = self.devices.get(device_id)
        device_name = device.get("description", "Your device") if device else "Your device"

        if turn_on:
            confirmed = await self._confirm_action(
                f"Are you sure you want to activate the siren on {device_name} "
                f"for {SIREN_DURATION_SECONDS} seconds?"
            )

            if not confirmed:
                await self.capability_worker.speak("Siren activation cancelled.")
                return

            endpoint = f"doorbots/{device_id}/siren_on"
            result = await self._ring_request_with_retry(
                endpoint,
                method="PUT",
                params={"duration": SIREN_DURATION_SECONDS},
                force_null_body=True,
            )

            if result is not None:
                await self.capability_worker.speak(
                    f"Siren activated on {device_name} for {SIREN_DURATION_SECONDS} seconds."
                )
            else:
                await self.capability_worker.speak(
                    f"I couldn't activate the siren on {device_name}."
                )
        else:
            endpoint = f"doorbots/{device_id}/siren_off"
            result = await self._ring_request_with_retry(
                endpoint, method="PUT", force_null_body=True,
            )

            if result is not None:
                await self.capability_worker.speak(
                    f"Siren turned off for {device_name}."
                )
            else:
                await self.capability_worker.speak(
                    f"I couldn't turn off the siren for {device_name}."
                )

    async def _handle_motion_toggle(self, device_id: str, enabled: bool):
        """Enable or disable motion detection."""
        device = self.devices.get(device_id)
        device_name = device.get("description", "Your device") if device else "Your device"

        endpoint = f"devices/{device_id}/settings"
        body = {"motion_settings": {"motion_detection_enabled": enabled}}

        result = await self._ring_request_with_retry(
            endpoint,
            method="PATCH",
            data=body,
            base_override=DEVICES_API_BASE,
        )

        state = "enabled" if enabled else "disabled"
        action = "enable" if enabled else "disable"

        if result is not None:
            await self.capability_worker.speak(
                f"Motion detection {state} for {device_name}."
            )
        else:
            await self.capability_worker.speak(
                f"I couldn't {action} motion detection for {device_name}."
            )

    async def _handle_chime_test(self, chime_id: str):
        """Play a test sound on a chime."""
        device = self.devices.get(chime_id)
        device_name = device.get("description", "Your chime") if device else "Your chime"

        endpoint = f"chimes/{chime_id}/play_sound"

        result = await self._ring_request_with_retry(
            endpoint,
            method="POST",
            params={"kind": "ding"},
        )

        if result is not None:
            await self.capability_worker.speak(
                f"Playing test sound on {device_name}."
            )
        else:
            await self.capability_worker.speak(
                f"I couldn't play the test sound on {device_name}."
            )

    def _parse_volume_input(self, volume: Any) -> int | None:
        """Parse a spoken or typed volume value and return 0-10 candidate."""
        if isinstance(volume, int):
            return volume

        cleaned = str(volume).lower().strip()
        cleaned = re.sub(r"[^\w\s]", "", cleaned)

        digit_match = re.search(r"\d+", cleaned)
        if digit_match:
            return int(digit_match.group())

        number_words = {
            "zero": 0,
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }

        for word, value in number_words.items():
            if word in cleaned:
                return value

        return None

    async def _handle_chime_volume(self, chime_id: str, volume: int | None):
        """Set chime volume."""
        device = self.devices.get(chime_id)
        device_name = device.get("description", "Your chime") if device else "Your chime"

        # Follow-up flow
        if volume is None:
            await self.capability_worker.speak(
                "What volume level would you like? Please specify a number from 0 to 10."
            )
            self.pending_action = {
                "type": "chime_volume_followup",
                "device_id": chime_id,
            }
            return

        volume = self._parse_volume_input(volume)
        if volume is None:
            await self.capability_worker.speak(
                "I need a number between 0 and 10. What volume level would you like?"
            )
            return

        # Bounds check
        if volume < 0 or volume > 10:
            await self.capability_worker.speak(
                "Volume must be a number between 0 and 10."
            )
            return

        desc = device.get("description", "Chime") if device else "Chime"

        endpoint = f"chimes/{chime_id}"

        result = await self._ring_request_with_retry(
            endpoint,
            method="PUT",
            params={
                "chime[description]": desc,
                "chime[settings][volume]": volume,
            },
            force_null_body=True,
        )

        if result is not None:
            await self.capability_worker.speak(
                f"Volume set to {volume} for {device_name}."
            )
        else:
            await self.capability_worker.speak(
                f"I couldn't update the volume for {device_name}."
            )
