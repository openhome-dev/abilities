import asyncio
import json
import time as time_module
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# AIRTHINGS ABILITY
# Fetches indoor air quality readings from Airthings devices via the
# Airthings Consumer API and speaks a natural-language summary.
#
# First-run setup: set AIRTHINGS_CLIENT_ID and AIRTHINGS_CLIENT_SECRET below.
# Credentials and preferences are saved to persistent file storage after the
# first successful run — the file only needs to be edited once.
#
# API docs: https://developer.airthings.com/consumer-api-docs
# =============================================================================

# --- CONFIGURATION ---
# Create a client at https://dashboard.airthings.com/integrations/api-integration
# These values are only read on first run; after that credentials come from
# persistent file storage automatically.
AIRTHINGS_CLIENT_ID = "YOUR_CLIENT_ID_HERE"
AIRTHINGS_CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"


AIRTHINGS_TOKEN_URL = "https://accounts-api.airthings.com/v1/token"
AIRTHINGS_DEVICES_URL = "https://ext-api.airthings.com/v1/devices"
REQUEST_TIMEOUT = 10            # seconds per HTTP request
STALE_THRESHOLD_SECONDS = 3600  # warn if readings are older than 1 hour

VERSION = "1.1.0"
DEFAULT_TIMEZONE = "America/Chicago"

CONFIG_FILE = "airthings_config.json"

_PLACEHOLDER_VALUES = {"YOUR_CLIENT_ID_HERE", "YOUR_CLIENT_SECRET_HERE"}

# Sensor keys that carry no air quality information
_SKIP_KEYS = {"rssi", "time", "relayDeviceType"}

# Human-readable labels and units for known sensor keys
_LABEL_MAP = {
    "co2": ("CO2", "ppm"),
    "voc": ("VOC", "ppb"),
    "pm1": ("PM1", "µg/m³"),
    "pm25": ("PM2.5", "µg/m³"),
    "radonShortTermAvg": ("Radon (short-term)", "Bq/m³"),
    "temp": ("Temperature", "°C"),
    "humidity": ("Humidity", "%"),
    "pressure": ("Pressure", "hPa"),
}

# Health thresholds: key -> (low_warn or None, high_warn or None)
# Sources: WHO guidelines, EPA annual standard, EU Radon Directive
_THRESHOLDS = {
    "co2": (None, 1000),  # ppm  — above 1000 is concerning
    "voc": (None, 250),   # ppb  — above 250 is concerning
    "pm25": (None, 12.0),  # µg/m³ — EPA annual standard
    "radonShortTermAvg": (None, 100),   # Bq/m³ — EU reference level
    "humidity": (30, 60),    # %    — below 30 dry, above 60 humid
}

# Timezone prefixes that indicate a Fahrenheit-preference user
_FAHRENHEIT_TZ_PREFIXES = ("America/", "US/", "Pacific/Honolulu")


class AirthingsCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # File storage helpers
    # -------------------------------------------------------------------------

    async def _load_config(self) -> dict:
        """Load config from persistent file storage. Returns empty dict if not found."""
        try:
            exists = await self.capability_worker.check_if_file_exists(CONFIG_FILE, False)
            if not exists:
                return {}
            raw = await self.capability_worker.read_file(CONFIG_FILE, False)
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[Airthings] Could not read config file: {e}"
            )
            return {}

    async def _save_config(self, config: dict) -> None:
        """Save config to persistent file storage using delete+write to avoid JSON corruption."""
        if await self.capability_worker.check_if_file_exists(CONFIG_FILE, False):
            await self.capability_worker.delete_file(CONFIG_FILE, False)
        await self.capability_worker.write_file(CONFIG_FILE, json.dumps(config), False)

    async def _upsert_config(self, updates: dict) -> None:
        """Merge updates into the stored config dict and save."""
        config = await self._load_config()
        config.update(updates)
        await self._save_config(config)

    async def _load_credentials(self) -> Optional[tuple]:
        """
        Return (client_id, client_secret) from file storage when available.
        On first run, falls back to the file-level constants and migrates them
        to persistent storage so subsequent runs never need the file again.
        """
        config = await self._load_config()
        cid = config.get("client_id", "")
        csecret = config.get("client_secret", "")
        if cid and cid not in _PLACEHOLDER_VALUES and csecret:
            return cid, csecret

        # File storage empty — try hardcoded constants
        if AIRTHINGS_CLIENT_ID in _PLACEHOLDER_VALUES or AIRTHINGS_CLIENT_SECRET in _PLACEHOLDER_VALUES:
            self.worker.editor_logging_handler.warning(
                "[Airthings] Credentials are still placeholder values. "
                "Update AIRTHINGS_CLIENT_ID and AIRTHINGS_CLIENT_SECRET in main.py."
            )
            return None

        # Migrate hardcoded constants to file storage for future runs
        try:
            await self._upsert_config({
                "client_id": AIRTHINGS_CLIENT_ID,
                "client_secret": AIRTHINGS_CLIENT_SECRET,
            })
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"[Airthings] Could not save credentials to file storage: {e}"
            )
        return AIRTHINGS_CLIENT_ID, AIRTHINGS_CLIENT_SECRET

    # -------------------------------------------------------------------------
    # API helpers (all async, non-blocking via asyncio.to_thread)
    # -------------------------------------------------------------------------

    async def _get_access_token(self, client_id: str, client_secret: str) -> Optional[str]:
        """Exchange client credentials for a short-lived access token."""
        try:
            response = await asyncio.to_thread(
                requests.post,
                AIRTHINGS_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "read:device:current_values",
                },
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 401:
                self.worker.editor_logging_handler.error(
                    "[Airthings] Authentication failed (401). Check client ID and secret."
                )
                return None
            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[Airthings] Token request failed {response.status_code}: {response.text}"
                )
                return None
            try:
                token = response.json().get("access_token")
            except ValueError:
                self.worker.editor_logging_handler.error(
                    "[Airthings] Token response was not valid JSON."
                )
                return None
            if not token:
                self.worker.editor_logging_handler.error(
                    "[Airthings] Token response was 200 but 'access_token' key was missing."
                )
                return None
            return token
        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error("[Airthings] Token request timed out.")
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Airthings] Token request error: {e}")
            return None

    async def _get_devices(self, token: str) -> list:
        """Return a list of device dicts from the account."""
        try:
            response = await asyncio.to_thread(
                requests.get,
                AIRTHINGS_DEVICES_URL,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 401:
                self.worker.editor_logging_handler.error(
                    "[Airthings] Devices request returned 401 — token may have expired."
                )
                return []
            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[Airthings] Devices request failed {response.status_code}: {response.text}"
                )
                return []
            try:
                return response.json().get("devices", [])
            except ValueError:
                self.worker.editor_logging_handler.error(
                    "[Airthings] Devices response was not valid JSON."
                )
                return []
        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error("[Airthings] Devices request timed out.")
            return []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Airthings] Devices request error: {e}")
            return []

    async def _get_latest_samples(self, token: str, serial_number: str) -> Optional[dict]:
        """Return the latest sensor readings for a single device, or None on failure."""
        if not serial_number:
            self.worker.editor_logging_handler.error(
                "[Airthings] Cannot fetch samples — device has no serial number."
            )
            return None
        try:
            url = f"{AIRTHINGS_DEVICES_URL}/{serial_number}/latest-samples"
            response = await asyncio.to_thread(
                requests.get,
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 401:
                self.worker.editor_logging_handler.error(
                    f"[Airthings] Samples request returned 401 for {serial_number} — token may have expired."
                )
                return None
            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[Airthings] Samples request failed {response.status_code}: {response.text}"
                )
                return None
            try:
                return response.json().get("data", {})
            except ValueError:
                self.worker.editor_logging_handler.error(
                    f"[Airthings] Samples response for {serial_number} was not valid JSON."
                )
                return None
        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error(
                f"[Airthings] Samples request timed out for {serial_number}."
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[Airthings] Samples request error for {serial_number}: {e}"
            )
            return None

    # -------------------------------------------------------------------------
    # Data helpers
    # -------------------------------------------------------------------------

    def _is_fahrenheit_user(self) -> bool:
        """Return True if the user's timezone suggests Fahrenheit preference."""
        tz = self.capability_worker.get_timezone() or DEFAULT_TIMEZONE
        return any(tz.startswith(prefix) for prefix in _FAHRENHEIT_TZ_PREFIXES)

    def _is_stale(self, samples: dict) -> bool:
        """Return True if the reading timestamp is older than STALE_THRESHOLD_SECONDS."""
        reading_time = samples.get("time")
        if reading_time is None:
            return False
        try:
            return (time_module.time() - float(reading_time)) > STALE_THRESHOLD_SECONDS
        except (TypeError, ValueError):
            return False

    def _threshold_annotation(self, key: str, value) -> str:
        """Return ' [HIGH]', ' [LOW]', or '' based on defined health thresholds."""
        thresholds = _THRESHOLDS.get(key)
        if thresholds is None:
            return ""
        low, high = thresholds
        try:
            numeric = float(value)
            if high is not None and numeric > high:
                return " [HIGH]"
            if low is not None and numeric < low:
                return " [LOW]"
        except (TypeError, ValueError):
            pass
        return ""

    def _build_summary_text(self, device_name: str, samples: dict, use_fahrenheit: bool) -> str:
        """Convert raw sensor data into an annotated string for the LLM."""
        parts = [f"Device: {device_name}"]
        for key, value in samples.items():
            if key in _SKIP_KEYS:
                continue
            if key == "temp" and use_fahrenheit:
                try:
                    value_f = round(float(value) * 9 / 5 + 32, 1)
                    parts.append(f"Temperature: {value_f} °F")
                except (TypeError, ValueError):
                    parts.append(f"Temperature: {value} (conversion error)")
                continue
            if key in _LABEL_MAP:
                label, unit = _LABEL_MAP[key]
                annotation = self._threshold_annotation(key, value)
                parts.append(f"{label}: {value} {unit}{annotation}")
            else:
                # Include unknown sensor keys as-is so new sensors aren't silently dropped
                parts.append(f"{key}: {value}")
        return ", ".join(parts)

    def _device_display_name(self, device: dict) -> str:
        return device.get("segment", {}).get("name", device.get("id", "unknown"))

    # -------------------------------------------------------------------------
    # Device selection
    # -------------------------------------------------------------------------

    async def _ask_device_selection(self, devices: list) -> list:
        """Prompt the user to choose a device (or 'all'), with preferred-device memory."""
        device_names = ", ".join(self._device_display_name(d) for d in devices)
        reply = await self.capability_worker.run_io_loop(
            f"Found {len(devices)} devices: {device_names}. Which one, or all of them?"
        )
        reply_lower = (reply or "").strip().lower()

        if not reply_lower:
            first_name = self._device_display_name(devices[0])
            await self.capability_worker.speak(
                f"I didn't catch that, so I'll use the first device: {first_name}."
            )
            return [devices[0]]

        exit_words = ["never mind", "forget it", "stop", "cancel", "exit", "quit"]
        if any(w in reply_lower for w in exit_words):
            self.capability_worker.resume_normal_flow()
            return []

        if any(w in reply_lower for w in ["all", "both", "every", "all of them", "all devices", "everything"]):
            return devices

        matched = [
            d for d in devices
            if self._device_display_name(d).lower() in reply_lower
        ]
        if not matched:
            first_name = self._device_display_name(devices[0])
            await self.capability_worker.speak(
                f"Didn't catch that, using {first_name}."
            )
            return [devices[0]]

        return matched

    # -------------------------------------------------------------------------
    # Main flow
    # -------------------------------------------------------------------------

    async def run(self):
        await self.capability_worker.speak(
            "Let me pull the latest readings from your Airthings devices."
        )

        # 1. Load credentials (file storage → hardcoded constants → fail)
        credentials = await self._load_credentials()
        if not credentials:
            await self.capability_worker.speak(
                "Airthings isn't set up yet. You'll need to add your credentials first."
            )
            self.capability_worker.resume_normal_flow()
            return

        client_id, client_secret = credentials

        # 2. Authenticate
        token = await self._get_access_token(client_id, client_secret)
        if not token:
            await self.capability_worker.speak(
                "I couldn't connect to Airthings right now. "
                "Please check your credentials and try again."
            )
            self.capability_worker.resume_normal_flow()
            return

        # 4. List devices
        devices = await self._get_devices(token)
        if not devices:
            await self.capability_worker.speak(
                "I connected to Airthings but didn't find any devices on your account."
            )
            self.capability_worker.resume_normal_flow()
            return

        # 5. Determine which devices to read
        if len(devices) == 1:
            chosen_devices = devices
        else:
            chosen_devices = await self._ask_device_selection(devices)
            if not chosen_devices:
                return  # resume_normal_flow already called inside _ask_device_selection

        # 6. Fetch samples sequentially
        use_fahrenheit = self._is_fahrenheit_user()
        sample_results = []
        for d in chosen_devices:
            result = await self._get_latest_samples(token, d.get("id", ""))
            sample_results.append(result)

        # 7. Classify results
        good_summaries = []
        failed_names = []
        stale_names = []
        for device, samples in zip(chosen_devices, sample_results):
            name = self._device_display_name(device)
            if samples is None:
                failed_names.append(name)
            elif not samples:
                good_summaries.append(f"Device: {name} — no sensor readings available.")
            else:
                if self._is_stale(samples):
                    stale_names.append(name)
                good_summaries.append(self._build_summary_text(name, samples, use_fahrenheit))

        # 8. Speak results — only feed real data to the LLM
        if good_summaries:
            combined = " | ".join(good_summaries)
            temp_unit = "Fahrenheit" if use_fahrenheit else "Celsius"
            response = self.capability_worker.text_to_text_response(
                f"Summarize the following indoor air quality readings in one or two clear, "
                f"friendly sentences suitable for voice. Temperature is in {temp_unit}. "
                f"Values annotated [HIGH] or [LOW] exceed health guidelines — call these out "
                f"clearly. Reassure the user if everything looks fine. Data: {combined}",
                system_prompt=(
                    "You are a helpful home assistant reporting indoor air quality. "
                    "Be concise and speak naturally. Respond in 1-2 sentences, maximum 30 words. "
                    "Plain spoken English only. Never use bullet points or formatting."
                ),
            )
            await self.capability_worker.speak(response)
        else:
            await self.capability_worker.speak(
                "I wasn't able to retrieve readings from any of your devices right now. "
                "Please try again in a moment."
            )

        if stale_names:
            await self.capability_worker.speak(
                f"Heads up — readings for {', '.join(stale_names)} are over an hour old, "
                "so they might be off."
            )

        if failed_names:
            await self.capability_worker.speak(
                f"Note: I couldn't get readings for {', '.join(failed_names)}."
            )

        self.capability_worker.resume_normal_flow()
