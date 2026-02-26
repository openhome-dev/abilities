import asyncio
import json
import re
import time
from typing import Any, Dict, Optional

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# Configuration
# =============================================================================

# Set to True to use fake data (no real device or API credentials needed).
# Set to False to use the real Google SDM API.
MOCK_MODE = True

PREFS_FILE = "nest_thermostat_prefs.json"

SDM_BASE_URL = "https://smartdevicemanagement.googleapis.com/v1"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
# NOTE: Nest Device Access uses nestservices.google.com, NOT accounts.google.com
OAUTH_CONSENT_BASE = "https://nestservices.google.com/partnerconnections"
SDM_SCOPE = "https://www.googleapis.com/auth/sdm.service"
REDIRECT_URI = "https://www.google.com"

MIN_TEMP_F = 50
MAX_TEMP_F = 90
MIN_TEMP_C = 10.0
MAX_TEMP_C = 32.0

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel",
    "bye", "goodbye", "leave", "never mind", "no thanks",
}

HELP_WORDS = {"help", "how", "what", "confused", "stuck", "where", "don't know"}

# Maps natural-language terms to API mode values
MODE_ALIASES: Dict[str, str] = {
    "heat": "HEAT",
    "heating": "HEAT",
    "warm": "HEAT",
    "cool": "COOL",
    "cooling": "COOL",
    "ac": "COOL",
    "air conditioning": "COOL",
    "air conditioner": "COOL",
    "auto": "HEATCOOL",
    "heat and cool": "HEATCOOL",
    "heat cool": "HEATCOOL",
    "both": "HEATCOOL",
    "off": "OFF",
    "turn off": "OFF",
}

# =============================================================================
# Module-level utilities
# =============================================================================


def f_to_c(f: float) -> float:
    """Convert Fahrenheit to Celsius, rounded to 2 decimal places."""
    return round((f - 32) * 5 / 9, 2)


def c_to_f(c: float) -> float:
    """Convert Celsius to Fahrenheit, rounded to 2 decimal places."""
    return round(c * 9 / 5 + 32, 2)


def round_for_voice(temp: float) -> int:
    """Round a temperature to the nearest whole number for voice output."""
    return round(temp)


def parse_json_response(raw: str) -> Dict[str, Any]:
    """
    Parse JSON from an LLM response that may contain markdown fences.
    Returns an empty dict on any parse failure.
    """
    if not raw:
        return {}
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        result = json.loads(clean)
        if isinstance(result, dict):
            return result
        return {}
    except (json.JSONDecodeError, ValueError):
        return {}


# =============================================================================
# Mock device state
# =============================================================================
# This dict is mutated by execute_command() in mock mode so that subsequent
# reads reflect the changes — simulating real device state.

MOCK_DEVICE_STATE: Dict[str, Any] = {
    "device_id": "enterprises/mock-project-id/devices/mock-thermostat-001",
    "custom_name": "Living Room",
    "connectivity": "ONLINE",
    "temperature_scale": "FAHRENHEIT",
    "available_modes": ["HEAT", "COOL", "HEATCOOL", "OFF"],
    "has_fan": True,
    # Current readings
    "ambient_temp_c": 21.5,
    "humidity_percent": 42,
    # Thermostat state
    "mode": "HEAT",
    "hvac_status": "HEATING",
    "eco_mode": "OFF",
    "heat_setpoint_c": 22.2,
    "cool_setpoint_c": 24.4,
    # Fan state
    "fan_timer_mode": "OFF",
    "fan_timer_timeout": "",
}


# =============================================================================
# Ability class
# =============================================================================


class NestThermostatCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # Main entry point
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            if MOCK_MODE:
                self.prefs = self._mock_prefs()
                self._log("MOCK_MODE enabled — using simulated device data.")
            else:
                self.prefs = await self.load_prefs()

                if not self.prefs.get("refresh_token"):
                    has_creds = await self._ask_yes_no(
                        "To control your Nest thermostat I need to connect to Google. "
                        "Do you already have your Client ID, Client Secret, and "
                        "Device Access Project ID ready?"
                    )
                    success = await self.run_oauth_setup_flow(skip_walkthrough=has_creds)
                    if not success:
                        await self.capability_worker.speak(
                            "Setup didn't complete. Say 'thermostat' again when you're ready."
                        )
                        return
                    self.prefs = await self.load_prefs()

                elif self._token_expired():
                    refreshed = await self.refresh_access_token()
                    if not refreshed:
                        await self.capability_worker.speak(
                            "Your Nest connection expired. Let's reconnect."
                        )
                        await self._invalidate_tokens()
                        return

            trigger_context = self._get_trigger_context()
            await self._conversation_loop(trigger_context)

        except Exception as e:
            self._log_err(f"run() unhandled error: {e}")
            await self.capability_worker.speak(
                "Something went wrong with the thermostat. Please try again."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    async def load_prefs(self) -> Dict[str, Any]:
        try:
            exists = await self.capability_worker.check_if_file_exists(PREFS_FILE, False)
            if not exists:
                return {}
            raw = await self.capability_worker.read_file(PREFS_FILE, False)
            if not raw or not raw.strip():
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Prefs is not a JSON object.")
            return data
        except (json.JSONDecodeError, ValueError) as e:
            self._log_err(f"Prefs file corrupt, resetting. Error: {e}")
            await self.capability_worker.delete_file(PREFS_FILE, False)
            return {}
        except Exception as e:
            self._log_err(f"load_prefs error: {e}")
            return {}

    async def save_prefs(self):
        try:
            exists = await self.capability_worker.check_if_file_exists(PREFS_FILE, False)
            if exists:
                await self.capability_worker.delete_file(PREFS_FILE, False)
            await self.capability_worker.write_file(
                PREFS_FILE,
                json.dumps(self.prefs),
                False,
            )
        except Exception as e:
            self._log_err(f"save_prefs error: {e}")

    def _mock_prefs(self) -> Dict[str, Any]:
        return {
            "project_id": "mock-project-id",
            "client_id": "mock-client-id",
            "client_secret": "mock-client-secret",
            "access_token": "mock-access-token",
            "refresh_token": "mock-refresh-token",
            "token_expires_at": time.time() + 3600,
            "device_id": MOCK_DEVICE_STATE["device_id"],
            "device_custom_name": MOCK_DEVICE_STATE["custom_name"],
            "temperature_scale": MOCK_DEVICE_STATE["temperature_scale"],
            "available_modes": MOCK_DEVICE_STATE["available_modes"],
            "has_fan": MOCK_DEVICE_STATE["has_fan"],
        }

    # -------------------------------------------------------------------------
    # OAuth setup flow
    # -------------------------------------------------------------------------

    async def run_oauth_setup_flow(self, skip_walkthrough: bool = False) -> bool:
        try:
            if not skip_walkthrough:
                await self.capability_worker.speak(
                    "Let me walk you through the setup. "
                    "First, you'll need to register for Nest Device Access at "
                    "console dot nest dot google dot com slash device-access. "
                    "There is a one-time five dollar fee from Google. "
                    "Have you already done that?"
                )
                paid = await self._ask_yes_no(None)
                if not paid:
                    await self.capability_worker.speak(
                        "Go to console dot nest dot google dot com slash device-access, "
                        "accept the terms, and pay the five dollar fee. "
                        "Then say 'done' when you're ready."
                    )
                    await self.capability_worker.user_response()

                await self.capability_worker.speak(
                    "Next, go to console dot cloud dot google dot com. "
                    "Create or select a Google Cloud project, then enable the "
                    "Smart Device Management API under APIs and Services. "
                    "Then create an OAuth 2.0 Client ID under Credentials. "
                    "Set the application type to Web Application, and add "
                    "https colon slash slash www dot google dot com as a redirect URI. "
                    "Say 'done' when you have your Client ID and Client Secret."
                )
                await self.capability_worker.user_response()

                await self.capability_worker.speak(
                    "Important: go to APIs and Services, then OAuth consent screen. "
                    "Set Publishing Status to Production. "
                    "This prevents your login from expiring after 7 days."
                )

                await self.capability_worker.speak(
                    "Finally, go back to the Device Access console, create a new project, "
                    "and enter your OAuth Client ID when it asks. "
                    "Say 'done' when you have your Device Access Project ID."
                )
                await self.capability_worker.user_response()

            # Collect credentials
            await self.capability_worker.speak("What is your OAuth Client ID?")
            client_id = (await self.capability_worker.user_response() or "").strip()
            if not client_id:
                await self.capability_worker.speak("I didn't catch a Client ID. Setup cancelled.")
                return False

            await self.capability_worker.speak("What is your Client Secret?")
            client_secret = (await self.capability_worker.user_response() or "").strip()
            if not client_secret:
                await self.capability_worker.speak("I didn't catch a Client Secret. Setup cancelled.")
                return False

            await self.capability_worker.speak("What is your Device Access Project ID?")
            project_id = (await self.capability_worker.user_response() or "").strip()
            if not project_id:
                await self.capability_worker.speak("I didn't catch a Project ID. Setup cancelled.")
                return False

            self.prefs["client_id"] = client_id
            self.prefs["client_secret"] = client_secret
            self.prefs["project_id"] = project_id

            # Build consent URL and walk user through it
            consent_url = (
                f"{OAUTH_CONSENT_BASE}/{project_id}/auth"
                f"?redirect_uri={REDIRECT_URI}"
                f"&access_type=offline"
                f"&prompt=consent"
                f"&client_id={client_id}"
                f"&response_type=code"
                f"&scope={SDM_SCOPE}"
            )
            await self.capability_worker.speak(
                f"Open this link in your browser: {consent_url}"
            )
            await self.capability_worker.speak(
                "Sign in with the Google account that has your Nest thermostat, "
                "select your devices, and allow access. "
                "You'll be redirected to google dot com. "
                "Look at the URL — find the part after 'code equals' and before the ampersand. "
                "Read or paste that authorization code to me now."
            )

            raw_code = (await self.capability_worker.user_response() or "").strip()
            if not raw_code:
                await self.capability_worker.speak("I didn't receive an authorization code. Setup cancelled.")
                return False

            # Sanitize: user might paste the full URL
            if "code=" in raw_code:
                raw_code = raw_code.split("code=")[-1]
            auth_code = raw_code.split("&")[0].strip()

            token_data = await self._exchange_code_for_tokens(auth_code)
            if not token_data:
                await self.capability_worker.speak(
                    "The authorization failed. Double-check your Client ID, Secret, and Project ID and try again."
                )
                return False

            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                await self.capability_worker.speak(
                    "Google didn't return a refresh token. "
                    "This usually means you've authorized before. "
                    "Go to your Google account, revoke access for this app, then try setup again."
                )
                return False

            self.prefs["access_token"] = token_data.get("access_token", "")
            self.prefs["refresh_token"] = refresh_token
            self.prefs["token_expires_at"] = time.time() + int(token_data.get("expires_in", 3599)) - 60

            # Discover thermostat
            device = await self._discover_devices()
            if not device:
                await self.capability_worker.speak(
                    "I couldn't find a thermostat on your account. "
                    "Make sure your Nest is set up in the Google Home app with a consumer Gmail account, "
                    "and that you shared it during authorization."
                )
                return False

            await self.save_prefs()

            name = self.prefs.get("device_custom_name", "your thermostat")
            await self.capability_worker.speak(
                f"You're all set! I found {name}. "
                "Try asking: what's the temperature?"
            )
            return True

        except Exception as e:
            self._log_err(f"run_oauth_setup_flow error: {e}")
            await self.capability_worker.speak("Setup encountered an error. Please try again.")
            return False

    async def _exchange_code_for_tokens(self, auth_code: str) -> Optional[Dict[str, Any]]:
        try:
            payload = {
                "client_id": self.prefs.get("client_id"),
                "client_secret": self.prefs.get("client_secret"),
                "code": auth_code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
            }
            response = await asyncio.to_thread(
                requests.post,
                OAUTH_TOKEN_URL,
                data=payload,
                timeout=10,
            )
            if response.status_code != 200:
                self._log_err(f"Token exchange failed: {response.status_code} {response.text}")
                return None
            return response.json()
        except Exception as e:
            self._log_err(f"_exchange_code_for_tokens error: {e}")
            return None

    async def _discover_devices(self) -> Optional[Dict[str, Any]]:
        """
        Call list devices, find the first thermostat, and cache its config into prefs.
        Returns the device dict on success, None on failure.
        """
        try:
            project_id = self.prefs.get("project_id", "")
            data = await self.sdm_request("GET", f"/enterprises/{project_id}/devices")
            if not data:
                return None

            devices = data.get("devices", [])
            thermostat = None
            for dev in devices:
                if "sdm.devices.types.THERMOSTAT" in dev.get("type", ""):
                    thermostat = dev
                    break

            if not thermostat:
                self._log("No thermostat found in device list.")
                return None

            device_name = thermostat.get("name", "")
            traits = thermostat.get("traits", {})

            custom_name = (
                traits.get("sdm.devices.traits.Info", {}).get("customName", "")
                or "Nest Thermostat"
            )
            temp_scale = (
                traits.get("sdm.devices.traits.Settings", {}).get("temperatureScale", "FAHRENHEIT")
            )
            available_modes = (
                traits.get("sdm.devices.traits.ThermostatMode", {}).get("availableModes", [])
            )
            has_fan = "sdm.devices.traits.Fan" in traits

            # Store only the device UUID portion for commands
            self.prefs["device_id"] = device_name
            self.prefs["device_custom_name"] = custom_name
            self.prefs["temperature_scale"] = temp_scale
            self.prefs["available_modes"] = available_modes
            self.prefs["has_fan"] = has_fan

            return thermostat

        except Exception as e:
            self._log_err(f"_discover_devices error: {e}")
            return None

    # -------------------------------------------------------------------------
    # Token management
    # -------------------------------------------------------------------------

    def _token_expired(self) -> bool:
        return time.time() >= self.prefs.get("token_expires_at", 0)

    async def refresh_access_token(self) -> bool:
        try:
            payload = {
                "client_id": self.prefs.get("client_id"),
                "client_secret": self.prefs.get("client_secret"),
                "refresh_token": self.prefs.get("refresh_token"),
                "grant_type": "refresh_token",
            }
            response = await asyncio.to_thread(
                requests.post,
                OAUTH_TOKEN_URL,
                data=payload,
                timeout=10,
            )
            if response.status_code != 200:
                error_data = {}
                try:
                    error_data = response.json()
                except Exception:
                    pass
                error_code = error_data.get("error", "")
                if error_code in ("invalid_grant", "invalid_client"):
                    self._log_err("Refresh token invalid — forcing re-auth.")
                    await self._invalidate_tokens()
                else:
                    self._log_err(f"Token refresh failed: {response.status_code}")
                return False

            token_data = response.json()
            new_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3599)
            if not new_token:
                self._log_err("Token refresh response missing access_token.")
                return False

            self.prefs["access_token"] = new_token
            self.prefs["token_expires_at"] = time.time() + int(expires_in) - 60
            await self.save_prefs()
            self._log("Access token refreshed.")
            return True

        except Exception as e:
            self._log_err(f"refresh_access_token error: {e}")
            return False

    async def _invalidate_tokens(self):
        self.prefs.pop("access_token", None)
        self.prefs.pop("refresh_token", None)
        self.prefs.pop("token_expires_at", None)
        await self.save_prefs()
        self._log("OAuth tokens invalidated.")

    # -------------------------------------------------------------------------
    # API layer
    # -------------------------------------------------------------------------

    async def sdm_request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Make a request to the SDM API.
        In MOCK_MODE, returns simulated data instead of calling the real API.
        Handles token refresh and one 401 retry automatically.
        """
        if MOCK_MODE:
            return self._mock_response(method, path, json_body)

        if self._token_expired():
            refreshed = await self.refresh_access_token()
            if not refreshed:
                await self.capability_worker.speak(
                    "Your Nest connection expired. Let's reconnect."
                )
                return None

        return await self._do_sdm_request(method, path, json_body, retry_on_401=True)

    async def _do_sdm_request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]],
        retry_on_401: bool,
    ) -> Optional[Dict[str, Any]]:
        url = f"{SDM_BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self.prefs.get('access_token', '')}",
            "Content-Type": "application/json",
        }
        try:
            response = await asyncio.to_thread(
                requests.request,
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=10,
            )

            if response.status_code == 401 and retry_on_401:
                refreshed = await self.refresh_access_token()
                if refreshed:
                    return await self._do_sdm_request(method, path, json_body, retry_on_401=False)
                return None

            if response.status_code == 200:
                return response.json()

            # Non-success: extract error details for callers
            error_detail = ""
            try:
                error_detail = response.json().get("error", {}).get("message", "")
            except Exception:
                pass

            self._log_err(
                f"SDM API error {response.status_code}: {error_detail or response.text[:200]}"
            )

            # Surface errors the caller needs to handle contextually
            if response.status_code == 400:
                return {"_error": "BAD_REQUEST", "_detail": error_detail}
            if response.status_code == 403:
                return {"_error": "FORBIDDEN"}
            if response.status_code == 404:
                return {"_error": "NOT_FOUND"}
            if response.status_code == 429:
                return {"_error": "RATE_LIMITED"}
            if response.status_code >= 500:
                return {"_error": "SERVER_ERROR"}

            return None

        except Exception as e:
            self._log_err(f"_do_sdm_request error: {e}")
            return None

    def _mock_response(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Return simulated API responses based on the request path and method."""
        if method == "GET" and "/devices" in path and ":executeCommand" not in path:
            # Single device GET or list devices
            project_id = self.prefs.get("project_id", "mock-project-id")
            device_path = f"enterprises/{project_id}/devices"
            traits = self._mock_build_traits()
            device = {
                "name": MOCK_DEVICE_STATE["device_id"],
                "type": "sdm.devices.types.THERMOSTAT",
                "traits": traits,
            }
            if path.endswith("/devices"):
                return {"devices": [device]}
            return device

        if method == "POST" and ":executeCommand" in path:
            return self._mock_execute(json_body or {})

        return {}

    def _mock_build_traits(self) -> Dict[str, Any]:
        s = MOCK_DEVICE_STATE
        traits: Dict[str, Any] = {
            "sdm.devices.traits.Info": {"customName": s["custom_name"]},
            "sdm.devices.traits.Settings": {"temperatureScale": s["temperature_scale"]},
            "sdm.devices.traits.Connectivity": {"status": s["connectivity"]},
            "sdm.devices.traits.Temperature": {"ambientTemperatureCelsius": s["ambient_temp_c"]},
            "sdm.devices.traits.Humidity": {"ambientHumidityPercent": s["humidity_percent"]},
            "sdm.devices.traits.ThermostatMode": {
                "mode": s["mode"],
                "availableModes": s["available_modes"],
            },
            "sdm.devices.traits.ThermostatEco": {
                "mode": s["eco_mode"],
                "heatCelsius": s["heat_setpoint_c"],
                "coolCelsius": s["cool_setpoint_c"],
            },
            "sdm.devices.traits.ThermostatHvac": {"status": s["hvac_status"]},
            "sdm.devices.traits.ThermostatTemperatureSetpoint": {
                "heatCelsius": s["heat_setpoint_c"],
                "coolCelsius": s["cool_setpoint_c"],
            },
        }
        if s["has_fan"]:
            traits["sdm.devices.traits.Fan"] = {
                "timerMode": s["fan_timer_mode"],
                "timerTimeout": s["fan_timer_timeout"],
            }
        return traits

    def _mock_execute(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a command to MOCK_DEVICE_STATE and return empty success."""
        command = body.get("command", "")
        params = body.get("params", {})

        if command == "sdm.devices.commands.ThermostatMode.SetMode":
            MOCK_DEVICE_STATE["mode"] = params.get("mode", MOCK_DEVICE_STATE["mode"])
            if MOCK_DEVICE_STATE["mode"] == "OFF":
                MOCK_DEVICE_STATE["hvac_status"] = "OFF"
            elif MOCK_DEVICE_STATE["mode"] == "HEAT":
                MOCK_DEVICE_STATE["hvac_status"] = "HEATING"
            elif MOCK_DEVICE_STATE["mode"] == "COOL":
                MOCK_DEVICE_STATE["hvac_status"] = "COOLING"

        elif command == "sdm.devices.commands.ThermostatEco.SetMode":
            MOCK_DEVICE_STATE["eco_mode"] = params.get("mode", MOCK_DEVICE_STATE["eco_mode"])

        elif command == "sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat":
            MOCK_DEVICE_STATE["heat_setpoint_c"] = params.get("heatCelsius", MOCK_DEVICE_STATE["heat_setpoint_c"])

        elif command == "sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool":
            MOCK_DEVICE_STATE["cool_setpoint_c"] = params.get("coolCelsius", MOCK_DEVICE_STATE["cool_setpoint_c"])

        elif command == "sdm.devices.commands.ThermostatTemperatureSetpoint.SetRange":
            MOCK_DEVICE_STATE["heat_setpoint_c"] = params.get("heatCelsius", MOCK_DEVICE_STATE["heat_setpoint_c"])
            MOCK_DEVICE_STATE["cool_setpoint_c"] = params.get("coolCelsius", MOCK_DEVICE_STATE["cool_setpoint_c"])

        elif command == "sdm.devices.commands.Fan.SetTimer":
            MOCK_DEVICE_STATE["fan_timer_mode"] = params.get("timerMode", "OFF")
            MOCK_DEVICE_STATE["fan_timer_timeout"] = params.get("duration", "")

        return {}

    async def get_device_state(self) -> Optional[Dict[str, Any]]:
        """
        Fetch current thermostat state and return a flat dict of meaningful values.
        All temperatures are stored in both Celsius (for API calls) and
        converted to the user's preferred scale (for voice output).
        """
        project_id = self.prefs.get("project_id", "")
        device_id = self.prefs.get("device_id", "")

        # device_id is already the full path; use it directly
        data = await self.sdm_request("GET", f"/{device_id}")
        if not data or "_error" in data:
            return None

        traits = data.get("traits", {})
        scale = self.prefs.get("temperature_scale", "FAHRENHEIT")

        def _temp(c: Optional[float]) -> Optional[int]:
            if c is None:
                return None
            return round_for_voice(c_to_f(c) if scale == "FAHRENHEIT" else c)

        ambient_c = traits.get("sdm.devices.traits.Temperature", {}).get("ambientTemperatureCelsius")
        humidity = traits.get("sdm.devices.traits.Humidity", {}).get("ambientHumidityPercent")
        mode = traits.get("sdm.devices.traits.ThermostatMode", {}).get("mode", "OFF")
        available_modes = traits.get("sdm.devices.traits.ThermostatMode", {}).get("availableModes", [])
        eco_mode = traits.get("sdm.devices.traits.ThermostatEco", {}).get("mode", "OFF")
        hvac_status = traits.get("sdm.devices.traits.ThermostatHvac", {}).get("status", "OFF")
        heat_c = traits.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {}).get("heatCelsius")
        cool_c = traits.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {}).get("coolCelsius")
        connectivity = traits.get("sdm.devices.traits.Connectivity", {}).get("status", "ONLINE")
        has_fan = "sdm.devices.traits.Fan" in traits
        fan_mode = traits.get("sdm.devices.traits.Fan", {}).get("timerMode", "OFF")
        custom_name = traits.get("sdm.devices.traits.Info", {}).get("customName", "")

        return {
            "ambient_display": _temp(ambient_c),
            "ambient_c": ambient_c,
            "humidity": humidity,
            "mode": mode,
            "available_modes": available_modes,
            "eco_mode": eco_mode,
            "hvac_status": hvac_status,
            "heat_setpoint_display": _temp(heat_c),
            "cool_setpoint_display": _temp(cool_c),
            "heat_setpoint_c": heat_c,
            "cool_setpoint_c": cool_c,
            "connectivity": connectivity,
            "has_fan": has_fan,
            "fan_mode": fan_mode,
            "custom_name": custom_name,
            "scale": scale,
            "scale_label": "degrees" if scale == "FAHRENHEIT" else "Celsius",
        }

    async def execute_command(
        self, command: str, params: Dict[str, Any]
    ) -> tuple:
        """
        Execute an SDM command. Returns (success: bool, error_detail: str).
        error_detail will be empty on success.
        """
        project_id = self.prefs.get("project_id", "")
        device_id = self.prefs.get("device_id", "")
        path = f"/{device_id}:executeCommand"
        body = {
            "command": f"sdm.devices.commands.{command}",
            "params": params,
        }
        result = await self.sdm_request("POST", path, json_body=body)
        if result is None:
            return False, "network_error"
        if "_error" in result:
            detail = result.get("_detail", "").lower()
            error_code = result.get("_error", "")
            if "failed_precondition" in detail:
                return False, "precondition"
            if "invalid_argument" in detail or "out of range" in detail:
                return False, "invalid_argument"
            return False, error_code.lower()
        return True, ""

    # -------------------------------------------------------------------------
    # Voice mode handlers
    # -------------------------------------------------------------------------

    async def handle_check_status(self):
        """Mode 1: Read and speak current thermostat state."""
        await self.capability_worker.speak("Let me check your thermostat.")
        state = await self.get_device_state()

        if not state:
            await self.capability_worker.speak(
                "I couldn't read your thermostat right now. Please try again."
            )
            return

        if state["connectivity"] == "OFFLINE":
            await self.capability_worker.speak(
                "Your thermostat appears to be offline. Check its WiFi connection."
            )
            return

        scale_label = state["scale_label"]
        ambient = state["ambient_display"]
        humidity = state["humidity"]
        mode = state["mode"]
        eco_mode = state["eco_mode"]
        hvac_status = state["hvac_status"]
        heat_sp = state["heat_setpoint_display"]
        cool_sp = state["cool_setpoint_display"]
        name = state["custom_name"] or "your thermostat"

        # Build spoken status
        parts = []

        if ambient is not None:
            parts.append(f"It's currently {ambient} {scale_label} inside")
            if humidity is not None and (humidity > 60 or humidity < 20):
                parts[-1] += f" with {humidity} percent humidity"
            parts[-1] += "."

        if eco_mode == "MANUAL_ECO":
            parts.append(f"{name} is in eco mode.")
        elif mode == "HEAT" and heat_sp is not None:
            parts.append(f"The thermostat is set to heat at {heat_sp} {scale_label}.")
            if hvac_status == "HEATING":
                parts.append("The heater is running.")
            else:
                parts.append("The heater is idle.")
        elif mode == "COOL" and cool_sp is not None:
            parts.append(f"The thermostat is set to cool at {cool_sp} {scale_label}.")
            if hvac_status == "COOLING":
                parts.append("The AC is running.")
            else:
                parts.append("The AC is idle.")
        elif mode == "HEATCOOL" and heat_sp is not None and cool_sp is not None:
            parts.append(
                f"The thermostat is in auto mode, "
                f"heating to {heat_sp} and cooling to {cool_sp} {scale_label}."
            )
        elif mode == "OFF":
            parts.append("The thermostat is off.")

        await self.capability_worker.speak(" ".join(parts) if parts else "I couldn't read the thermostat status.")

    async def handle_set_temperature(self, target_text: str):
        """
        Mode 2: Parse a target temperature from user speech and set it.
        Handles mode preconditions (OFF/ECO), relative adjustments (up/down),
        sanity checks, and F/C conversion.
        """
        state = await self.get_device_state()
        if not state:
            await self.capability_worker.speak("I couldn't read your thermostat. Please try again.")
            return

        scale = state["scale"]
        mode = state["mode"]
        eco_mode = state["eco_mode"]

        # --- Precondition checks ---
        if mode == "OFF":
            await self.capability_worker.speak(
                "The thermostat is off, so I can't set a temperature. "
                "Want me to switch it to heat or cool first?"
            )
            follow = (await self.capability_worker.user_response() or "").lower()
            if self._is_exit(follow) or "no" in follow:
                return
            # Try to infer desired mode from follow-up
            new_mode = "HEAT"
            for alias, api_mode in MODE_ALIASES.items():
                if alias in follow:
                    new_mode = api_mode
                    break
            if new_mode == "OFF":
                new_mode = "HEAT"
            await self.handle_change_mode(new_mode)
            state = await self.get_device_state()
            if not state:
                return
            mode = state["mode"]

        if eco_mode == "MANUAL_ECO":
            await self.capability_worker.speak(
                "Eco mode is on, so I can't change the temperature. "
                "Should I turn off eco mode first?"
            )
            follow = (await self.capability_worker.user_response() or "").lower()
            if self._is_exit(follow) or "no" in follow:
                return
            success, err = await self.execute_command("ThermostatEco.SetMode", {"mode": "OFF"})
            if not success:
                await self.capability_worker.speak("I wasn't able to turn off eco mode. Please try again.")
                return
            state = await self.get_device_state()
            if not state:
                return
            eco_mode = state["eco_mode"]

        # --- Parse target temperature ---
        target_c = await self._parse_target_temperature(target_text, state)
        if target_c is None:
            return  # Already spoke an error

        # --- Execute the right command for the current mode ---
        if mode == "HEAT":
            success, err = await self.execute_command(
                "ThermostatTemperatureSetpoint.SetHeat", {"heatCelsius": target_c}
            )
        elif mode == "COOL":
            success, err = await self.execute_command(
                "ThermostatTemperatureSetpoint.SetCool", {"coolCelsius": target_c}
            )
        elif mode == "HEATCOOL":
            # Determine whether user is adjusting heat or cool bound based on target
            heat_c = state.get("heat_setpoint_c") or f_to_c(68)
            cool_c = state.get("cool_setpoint_c") or f_to_c(76)
            if target_c <= heat_c or (target_c < (heat_c + cool_c) / 2):
                success, err = await self.execute_command(
                    "ThermostatTemperatureSetpoint.SetRange",
                    {"heatCelsius": target_c, "coolCelsius": cool_c},
                )
            else:
                success, err = await self.execute_command(
                    "ThermostatTemperatureSetpoint.SetRange",
                    {"heatCelsius": heat_c, "coolCelsius": target_c},
                )
        else:
            await self.capability_worker.speak("I can't set the temperature in the current thermostat mode.")
            return

        if success:
            display_temp = round_for_voice(c_to_f(target_c) if scale == "FAHRENHEIT" else target_c)
            scale_label = "degrees" if scale == "FAHRENHEIT" else "degrees Celsius"
            await self.capability_worker.speak(f"Done. I've set the thermostat to {display_temp} {scale_label}.")
        else:
            await self._speak_command_error(err)

    async def _parse_target_temperature(
        self, text: str, state: Dict[str, Any]
    ) -> Optional[float]:
        """
        Extract a target temperature in Celsius from user text.
        Handles absolute values, relative adjustments ("turn it up"), and F/C.
        Returns None and speaks an error if the value is invalid.
        """
        scale = state["scale"]
        text_lower = text.lower()

        # Relative adjustments
        if any(w in text_lower for w in ["turn it up", "warmer", "hotter", "increase", "raise"]):
            current_c = state.get("heat_setpoint_c") or state.get("cool_setpoint_c")
            if current_c is None:
                await self.capability_worker.speak("I can't read the current setpoint to adjust it.")
                return None
            adjustment = 2.0 if scale == "FAHRENHEIT" else 1.0  # 2°F ≈ 1°C
            return round(current_c + (f_to_c(adjustment + 32) if scale == "FAHRENHEIT" else adjustment), 2)

        if any(w in text_lower for w in ["turn it down", "cooler", "colder", "decrease", "lower"]):
            current_c = state.get("heat_setpoint_c") or state.get("cool_setpoint_c")
            if current_c is None:
                await self.capability_worker.speak("I can't read the current setpoint to adjust it.")
                return None
            adjustment_c = f_to_c(2 + 32) if scale == "FAHRENHEIT" else 1.0
            return round(current_c - (f_to_c(2 + 32) if scale == "FAHRENHEIT" else 1.0), 2)

        # Extract a number from text (regex first, LLM fallback)
        number_match = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
        if number_match:
            raw_val = float(number_match.group(1))
        else:
            # Ask LLM to extract the number
            extraction = self.capability_worker.text_to_text_response(
                f'Extract only the numeric temperature value from this text. '
                f'Reply with just the number, nothing else: "{text}"'
            )
            num_match = re.search(r"\d+(?:\.\d+)?", extraction or "")
            if not num_match:
                await self.capability_worker.speak("I didn't catch a temperature. Try saying a number like 72.")
                return None
            raw_val = float(num_match.group())

        # Determine if user said Celsius or Fahrenheit
        if "celsius" in text_lower or "°c" in text_lower:
            target_c = raw_val
        elif "fahrenheit" in text_lower or "°f" in text_lower:
            target_c = f_to_c(raw_val)
        elif scale == "FAHRENHEIT":
            target_c = f_to_c(raw_val)
        else:
            target_c = raw_val

        # Sanity check
        if not (MIN_TEMP_C <= target_c <= MAX_TEMP_C):
            display_min = round_for_voice(c_to_f(MIN_TEMP_C)) if scale == "FAHRENHEIT" else MIN_TEMP_C
            display_max = round_for_voice(c_to_f(MAX_TEMP_C)) if scale == "FAHRENHEIT" else MAX_TEMP_C
            await self.capability_worker.speak(
                f"That temperature is out of range. "
                f"Try something between {display_min} and {display_max} degrees."
            )
            return None

        return target_c

    async def handle_change_mode(self, target_mode: str):
        """Mode 3: Switch thermostat to HEAT, COOL, HEATCOOL, or OFF."""
        # Resolve aliases
        api_mode = None
        target_lower = target_mode.lower().strip()
        for alias, mode in MODE_ALIASES.items():
            if alias == target_lower or alias in target_lower:
                api_mode = mode
                break

        if not api_mode:
            # Let LLM interpret
            classification = parse_json_response(
                self.capability_worker.text_to_text_response(
                    f'Map this to one of: HEAT, COOL, HEATCOOL, OFF. '
                    f'Reply with JSON: {{"mode": "HEAT"}}. Input: "{target_mode}"'
                )
            )
            api_mode = classification.get("mode", "").upper()

        if api_mode not in ("HEAT", "COOL", "HEATCOOL", "OFF"):
            await self.capability_worker.speak(
                "I didn't understand that mode. "
                "Try: heat, cool, auto, or off."
            )
            return

        available = self.prefs.get("available_modes", ["HEAT", "COOL", "HEATCOOL", "OFF"])
        if api_mode not in available:
            await self.capability_worker.speak(
                f"Your thermostat doesn't support {api_mode.lower()} mode."
            )
            return

        success, err = await self.execute_command(
            "ThermostatMode.SetMode", {"mode": api_mode}
        )
        if success:
            mode_labels = {
                "HEAT": "heat",
                "COOL": "cool",
                "HEATCOOL": "heat and cool",
                "OFF": "off",
            }
            await self.capability_worker.speak(
                f"Done. The thermostat is now set to {mode_labels.get(api_mode, api_mode)} mode."
            )
        else:
            await self._speak_command_error(err)

    async def handle_eco_mode(self, on_or_off: str):
        """Mode 4: Toggle eco mode on or off."""
        turning_on = "on" in on_or_off.lower() or "eco" in on_or_off.lower()

        if turning_on:
            eco_value = "MANUAL_ECO"
            success, err = await self.execute_command(
                "ThermostatEco.SetMode", {"mode": eco_value}
            )
            if not success and err == "precondition":
                # Thermostat may be OFF — offer to set a mode first
                await self.capability_worker.speak(
                    "I wasn't able to enable eco mode. "
                    "This sometimes happens when the thermostat is off. "
                    "Want me to switch it to heat mode first?"
                )
                follow = (await self.capability_worker.user_response() or "").lower()
                if self._is_exit(follow) or "no" in follow:
                    return
                await self.handle_change_mode("HEAT")
                success, err = await self.execute_command(
                    "ThermostatEco.SetMode", {"mode": "MANUAL_ECO"}
                )

            if success:
                await self.capability_worker.speak(
                    "Eco mode is now on. The thermostat will use energy-saving temperatures. "
                    "I won't be able to change the temperature until eco mode is turned off."
                )
            else:
                await self._speak_command_error(err)

        else:
            success, err = await self.execute_command(
                "ThermostatEco.SetMode", {"mode": "OFF"}
            )
            if success:
                state = await self.get_device_state()
                mode_label = ""
                if state:
                    mode_labels = {"HEAT": "heat", "COOL": "cool", "HEATCOOL": "auto"}
                    mode_label = mode_labels.get(state["mode"], "")
                if mode_label:
                    await self.capability_worker.speak(
                        f"Eco mode is off. The thermostat is back to {mode_label} mode."
                    )
                else:
                    await self.capability_worker.speak("Eco mode is off.")
            else:
                await self._speak_command_error(err)

    async def handle_fan_control(self, on_or_off: str, duration_text: str):
        """Mode 5: Turn the fan on or off with an optional timer."""
        if not self.prefs.get("has_fan", False):
            await self.capability_worker.speak(
                "Your thermostat doesn't support fan control."
            )
            return

        turning_on = "on" in on_or_off.lower() or "run" in on_or_off.lower() or "start" in on_or_off.lower()

        if turning_on:
            duration_seconds = self._parse_duration(duration_text)
            params: Dict[str, Any] = {"timerMode": "ON"}
            if duration_seconds:
                params["duration"] = duration_seconds

            success, err = await self.execute_command("Fan.SetTimer", params)
            if success:
                if duration_seconds:
                    minutes = int(duration_seconds.rstrip("s")) // 60
                    if minutes >= 60:
                        hours = minutes // 60
                        time_str = f"{hours} hour{'s' if hours > 1 else ''}"
                    else:
                        time_str = f"{minutes} minute{'s' if minutes > 1 else ''}"
                    await self.capability_worker.speak(
                        f"The fan is running. It'll turn off automatically in {time_str}."
                    )
                else:
                    await self.capability_worker.speak(
                        "The fan is running. It'll turn off automatically in 15 minutes."
                    )
            else:
                await self._speak_command_error(err)

        else:
            success, err = await self.execute_command("Fan.SetTimer", {"timerMode": "OFF"})
            if success:
                await self.capability_worker.speak("The fan is off.")
            else:
                await self._speak_command_error(err)

    async def _speak_command_error(self, error_detail: str):
        """Speak an appropriate error message based on error detail code."""
        messages = {
            "precondition": (
                "I wasn't able to do that because of the current thermostat state. "
                "For example, you may need to turn off eco mode or switch modes first."
            ),
            "invalid_argument": "That value is out of the allowed range. Try a different setting.",
            "forbidden": "I don't have permission for that. You may need to re-authorize.",
            "not_found": "I can't find your thermostat. It may have been removed from your account.",
            "rate_limited": "I'm making too many requests. Try again in a moment.",
            "server_error": "Google's Nest API is having issues. Try again in a few minutes.",
            "network_error": "I couldn't reach the Nest API. Check your internet connection.",
        }
        msg = messages.get(error_detail, "Something went wrong. Please try again.")
        await self.capability_worker.speak(msg)

    # -------------------------------------------------------------------------
    # Intent classification and dispatch
    # -------------------------------------------------------------------------

    def classify_intent(self, user_input: str) -> Dict[str, Any]:
        """
        Use the LLM to classify user intent and extract parameters.
        Returns a dict with 'intent' and optional parameter fields.
        """
        prompt = (
            "Classify the user's thermostat request. "
            "Return JSON with these fields:\n"
            '- "intent": one of check_status, set_temperature, change_mode, eco_mode, fan_control, unknown\n'
            '- "target_value": temperature number as string if mentioned (e.g. "72"), else ""\n'
            '- "target_mode": mode if mentioned (heat/cool/auto/off), else ""\n'
            '- "on_or_off": "on" or "off" for eco and fan commands, else ""\n'
            '- "duration": duration phrase if mentioned (e.g. "an hour"), else ""\n'
            f'User said: "{user_input}"\n'
            "Reply with only the JSON object."
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        result = parse_json_response(raw)
        if not result.get("intent"):
            result["intent"] = "unknown"
        return result

    async def dispatch(self, classification: Dict[str, Any]):
        """Route a classified intent to the appropriate handler."""
        intent = classification.get("intent", "unknown")

        if intent == "check_status":
            await self.handle_check_status()

        elif intent == "set_temperature":
            target = classification.get("target_value", "")
            # Pass the raw classification as text context for the parser
            raw_text = target if target else str(classification)
            await self.handle_set_temperature(raw_text)

        elif intent == "change_mode":
            mode = classification.get("target_mode", "")
            await self.handle_change_mode(mode)

        elif intent == "eco_mode":
            on_or_off = classification.get("on_or_off", "on")
            await self.handle_eco_mode(on_or_off)

        elif intent == "fan_control":
            on_or_off = classification.get("on_or_off", "on")
            duration = classification.get("duration", "")
            await self.handle_fan_control(on_or_off, duration)

        else:
            await self.capability_worker.speak(
                "I can check the temperature, set a target, change modes, "
                "toggle eco mode, or control the fan. What would you like?"
            )

    async def _conversation_loop(self, trigger_context: str):
        """
        Unified conversation loop.
        Turn 0: classify and dispatch the trigger phrase.
        Turn 1+: listen, classify, dispatch.
        Exits on: exit words, 2 silent turns, or 20-turn cap.
        """
        max_turns = 20
        turn_count = 0
        idle_count = 0

        if trigger_context and trigger_context.strip():
            classification = self.classify_intent(trigger_context)
            await self.dispatch(classification)
            turn_count += 1

        while turn_count < max_turns:
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                idle_count += 1
                if idle_count >= 2:
                    break
                continue

            idle_count = 0

            if self._is_exit(user_input):
                await self.capability_worker.speak("Okay, let me know if you need anything else.")
                break

            classification = self.classify_intent(user_input)
            await self.dispatch(classification)
            turn_count += 1

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    def _get_trigger_context(self) -> str:
        """Return the phrase that triggered this ability, if available."""
        try:
            return self.worker.get_trigger_context() or ""
        except Exception:
            return ""

    def _is_exit(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower().strip()
        return any(word in lower for word in EXIT_WORDS)

    async def _ask_yes_no(self, question: Optional[str]) -> bool:
        """
        Optionally speak a question, then interpret the user's response as yes/no.
        Returns True for yes, False for no.
        """
        if question:
            await self.capability_worker.speak(question)
        response = (await self.capability_worker.user_response() or "").lower()
        return any(w in response for w in ("yes", "yeah", "yep", "sure", "ready", "done", "yup", "already"))

    def _parse_duration(self, text: str) -> Optional[str]:
        """
        Convert a duration phrase to an SDM duration string (e.g. "3600s").
        Returns None if no duration is mentioned.
        """
        if not text:
            return None
        text_lower = text.lower()

        # "X hours"
        m = re.search(r"(\d+)\s*hour", text_lower)
        if m:
            return f"{int(m.group(1)) * 3600}s"

        # "X minutes"
        m = re.search(r"(\d+)\s*min", text_lower)
        if m:
            return f"{int(m.group(1)) * 60}s"

        # "an hour" / "a hour"
        if re.search(r"\ban?\s+hour\b", text_lower):
            return "3600s"

        # "half an hour"
        if re.search(r"half\s+(?:an?\s+)?hour", text_lower):
            return "1800s"

        # "until I say stop" / "all day"
        if any(phrase in text_lower for phrase in ("until i say", "all day", "indefinitely")):
            return "43200s"

        return None

    def _log(self, msg: str):
        self.worker.editor_logging_handler.info(f"[NestThermostat] {msg}")

    def _log_err(self, msg: str):
        self.worker.editor_logging_handler.error(f"[NestThermostat] {msg}")
