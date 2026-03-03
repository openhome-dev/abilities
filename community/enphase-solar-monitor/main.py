"""
Enphase Solar Monitor - OpenHome Ability
Voice-activated solar dashboard for Enphase systems (IQ Gateway with microinverters).
Fetches production, consumption, and battery data from Enphase Cloud API v4.
"""

import json
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# Demo mode - set to False when you have real Enphase credentials
DEMO_MODE = True

ENPHASE_BASE_URL = "https://api.enphaseenergy.com/api/v4"
ENPHASE_TOKEN_URL = "https://api.enphaseenergy.com/oauth/token"
CACHE_TTL = 900  # 15 minutes
EXIT_WORDS = ["stop", "quit", "exit", "done", "cancel"]
PREFS_FILE = "enphase_solar_prefs.json"

# Hardcoded from config.json - OpenHome forbids open() in register_capability
UNIQUE_NAME = "enphase_solar_monitor"
MATCHING_HOTWORDS = [
    "solar", "solar status", "solar production", "how's my solar",
    "hows my solar", "how is my solar", "enphase", "solar panels",
    "battery level", "battery status", "my battery status", "battery",
    "am I exporting", "grid status", "solar today", "check my solar", "solar power",
]

ERROR_RESPONSES = {
    "no_system_id": "You haven't set up your Enphase system yet.",
    "auth_failed": "Your Enphase authorization has expired. You'll need to re-authorize.",
    "rate_limited": "I've hit the API limit. Try again later, or check the Enphase app.",
    "system_not_found": "I can't find that system ID. Check your preferences file.",
    "timeout": "I can't reach the Enphase cloud right now. Check your internet.",
}


class EnphaseSolarMonitorCapability(MatchingCapability):
    """Voice-activated Enphase solar monitoring capability."""

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        return cls(
            unique_name=UNIQUE_NAME,
            matching_hotwords=MATCHING_HOTWORDS,
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_solar_monitor())

    async def _load_prefs(self) -> dict:
        """Load preferences using OpenHome File Storage API."""
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                prefs = json.loads(raw)
                if DEMO_MODE and not prefs.get("system_id"):
                    prefs.setdefault("has_battery", True)
                    prefs.setdefault("has_consumption", True)
                return prefs
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Failed to load prefs: {e}")
        if DEMO_MODE:
            return {"has_battery": True, "has_consumption": True}
        return {}

    async def _save_prefs(self, prefs: dict) -> None:
        """Save preferences using OpenHome File Storage API."""
        try:
            await self.capability_worker.write_file(
                PREFS_FILE, json.dumps(prefs, indent=2), False, mode="w"
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Failed to save prefs: {e}")

    async def _refresh_access_token(self) -> bool:
        """Refresh the Enphase OAuth access token using refresh token."""
        try:
            prefs = await self._load_prefs()
            response = requests.post(
                ENPHASE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": prefs.get("refresh_token", ""),
                    "client_id": prefs.get("client_id", ""),
                    "client_secret": prefs.get("client_secret", ""),
                },
                timeout=15,
            )
            if response.status_code == 200:
                tokens = response.json()
                prefs["access_token"] = tokens["access_token"]
                if "refresh_token" in tokens:
                    prefs["refresh_token"] = tokens["refresh_token"]
                await self._save_prefs(prefs)
                self.worker.editor_logging_handler.info("Enphase token refreshed")
                return True
            return False
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Token refresh failed: {e}")
            return False

    async def _api_call(
        self, endpoint: str, extra_params: Optional[dict] = None
    ) -> dict:
        """Make an Enphase API call. Returns dict with data or {"error": "error_type"}."""
        if DEMO_MODE:
            return self._demo_response(endpoint)
        try:
            prefs = await self._load_prefs()
            system_id = prefs.get("system_id")
            if not system_id:
                return {"error": "no_system_id"}
            access_token = prefs.get("access_token")
            if not access_token:
                return {"error": "auth_failed"}
            url = f"{ENPHASE_BASE_URL}/systems/{system_id}/{endpoint}"
            params = {"key": prefs.get("api_key", ""), "access_token": access_token}
            if extra_params:
                params.update(extra_params)
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                if await self._refresh_access_token():
                    return await self._api_call(endpoint, extra_params)
                return {"error": "auth_failed"}
            elif response.status_code == 404:
                return {"error": "system_not_found"}
            elif response.status_code == 429:
                return {"error": "rate_limited"}
            else:
                self.worker.editor_logging_handler.error(
                    f"Enphase API {endpoint}: {response.status_code}"
                )
                return {"error": f"http_{response.status_code}"}
        except requests.exceptions.Timeout:
            return {"error": "timeout"}
        except Exception as e:
            self.worker.editor_logging_handler.error(f"API call error: {e}")
            return {"error": str(e)}

    def _demo_response(self, endpoint: str) -> dict:
        """Return realistic fake data for demo mode."""
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        if "stats" in endpoint or "summary" in endpoint:
            return {
                "intervals": [
                    {
                        "end_at": ts,
                        "powr": 4200,
                        "enwh": 28000,
                    }
                ],
                "meta": {"status": "normal"},
            }
        if "battery" in endpoint or "storage" in endpoint:
            return {
                "intervals": [
                    {
                        "end_at": ts,
                        "powr": -1500,
                        "percent_full": 73,
                    }
                ],
            }
        if "consumption" in endpoint:
            return {
                "intervals": [
                    {
                        "end_at": ts,
                        "enwh": 3100,
                        "powr": 3100,
                    }
                ],
            }
        if "grid" in endpoint or "net" in endpoint:
            return {
                "intervals": [
                    {
                        "end_at": ts,
                        "powr": -1500,
                    }
                ],
            }
        return {"intervals": [], "meta": {"status": "normal"}}

    async def _get_cached_or_fetch(
        self, cache_key: str, fetch_function: Callable
    ) -> dict:
        """Check cache first, fetch if expired. Cache TTL: 15 minutes."""
        try:
            prefs = await self._load_prefs()
            cache = prefs.get("cache", {})
            if cache_key in cache:
                cached_data = cache[cache_key]
                timestamp = cached_data.get("timestamp", 0)
                if time.time() - timestamp < CACHE_TTL:
                    self.worker.editor_logging_handler.info(f"Cache hit: {cache_key}")
                    return cached_data.get("data", {})
            self.worker.editor_logging_handler.info(f"Cache miss: {cache_key}")
            data = await fetch_function()
            if not isinstance(data, dict) or "error" not in data:
                cache[cache_key] = {"timestamp": time.time(), "data": data}
                prefs["cache"] = cache
                await self._save_prefs(prefs)
            return data
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Cache error: {e}")
            return await fetch_function()

    def _format_power(self, watts: Optional[float]) -> str:
        if watts is None:
            return "unknown"
        kilowatts = watts / 1000.0
        if kilowatts < 0.1:
            return f"{round(watts)} watts"
        return f"{round(kilowatts, 1)} kilowatts"

    def _format_energy(self, watt_hours: Optional[float]) -> str:
        if watt_hours is None:
            return "unknown"
        kwh = watt_hours / 1000.0
        return f"{round(kwh, 1)} kilowatt hours"

    def _format_battery(self, percentage: Optional[float]) -> str:
        if percentage is None:
            return "unknown"
        return f"{round(percentage)} percent"

    def _is_exit_word(self, text: Optional[str]) -> bool:
        if not text:
            return False
        return any(word in text.lower() for word in EXIT_WORDS)

    def _classify_intent(self, user_input: str) -> str:
        system_prompt = """Classify the user's solar system query into ONE of these intents:
- solar_snapshot: General status, "how's my solar", overall view
- battery_status: Battery level, charging status
- consumption: How much am I using, consumption
- grid_status: Am I exporting, grid status
- today_summary: Today's totals
- system_health: System health, panel status
- unknown: Anything else

Respond with ONLY the intent name, nothing else."""
        intent = self.capability_worker.text_to_text_response(
            prompt_text=f"User query: {user_input}",
            system_prompt=system_prompt,
            history=[],
        )
        return (intent or "unknown").strip().lower()

    def _speak_error(self, error_key: str) -> str:
        return ERROR_RESPONSES.get(error_key, "Something went wrong. Try again later.")

    async def run_solar_monitor(self) -> None:
        try:
            await self.capability_worker.speak("Sure! Let me check your solar system.")
            await self._handle_solar_snapshot()
            while True:
                await self.capability_worker.speak("Anything else about your solar?")
                response = await self.capability_worker.user_response()
                if not response or self._is_exit_word(response):
                    await self.capability_worker.speak("Okay, talk to you later!")
                    break
                intent = self._classify_intent(response)
                if intent == "solar_snapshot":
                    await self._handle_solar_snapshot()
                elif intent == "battery_status":
                    await self._handle_battery_status()
                elif intent == "consumption":
                    await self._handle_consumption()
                elif intent == "grid_status":
                    await self._handle_grid_status()
                elif intent == "today_summary":
                    await self._handle_today_summary()
                elif intent == "system_health":
                    await self._handle_system_health()
                else:
                    await self.capability_worker.speak(
                        "I didn't catch that. You can ask about production, "
                        "battery, consumption, or grid status."
                    )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Solar monitor error: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    async def _handle_solar_snapshot(self) -> None:
        async def fetch():
            return await self._api_call("stats?granularity=day&start_at=2020-01-01")

        stats = await self._get_cached_or_fetch("stats", fetch)
        if isinstance(stats, dict) and "error" in stats:
            await self.capability_worker.speak(
                self._speak_error(stats["error"])
            )
            return
        intervals = stats.get("intervals", [])
        power = 0
        energy_today = 0
        if intervals:
            last = intervals[-1]
            power = last.get("powr", 0)
            energy_today = last.get("enwh", 0)
        power_str = self._format_power(power)
        energy_str = self._format_energy(energy_today)
        await self.capability_worker.speak(
            f"You're producing {power_str} right now, as of about 15 minutes ago."
        )
        await self.capability_worker.speak(
            f"Today you've generated {energy_str}."
        )
        prefs = await self._load_prefs()
        if prefs.get("has_battery"):
            await self._handle_battery_status()
        if prefs.get("has_consumption"):
            await self._handle_consumption()
            await self._handle_grid_status()

    async def _handle_battery_status(self) -> None:
        prefs = await self._load_prefs()
        if not prefs.get("has_battery"):
            await self.capability_worker.speak(
                "Your system doesn't have a battery configured."
            )
            return

        async def fetch():
            return await self._api_call("stats?granularity=day&start_at=2020-01-01")

        battery = await self._get_cached_or_fetch("battery", fetch)
        if isinstance(battery, dict) and "error" in battery:
            await self.capability_worker.speak(
                self._speak_error(battery["error"])
            )
            return
        intervals = battery.get("intervals", [])
        if not intervals:
            await self.capability_worker.speak("No battery data available.")
            return
        last = intervals[-1]
        soc = last.get("percent_full", 0)
        power = last.get("powr", 0)
        soc_str = self._format_battery(soc)
        if power < -50:
            status = "and charging."
        elif power > 50:
            status = "and discharging."
        else:
            status = "and idle."
        await self.capability_worker.speak(
            f"Your battery is at {soc_str} {status}"
        )

    async def _handle_consumption(self) -> None:
        prefs = await self._load_prefs()
        if not prefs.get("has_consumption"):
            await self.capability_worker.speak(
                "Your system doesn't have consumption monitoring."
            )
            return

        async def fetch():
            return await self._api_call("stats?granularity=day&start_at=2020-01-01")

        consumption = await self._get_cached_or_fetch("consumption", fetch)
        if isinstance(consumption, dict) and "error" in consumption:
            await self.capability_worker.speak(
                self._speak_error(consumption["error"])
            )
            return
        intervals = consumption.get("intervals", [])
        power = intervals[-1].get("powr", 0) if intervals else 0
        power_str = self._format_power(power)
        await self.capability_worker.speak(
            f"You're using {power_str} right now."
        )

    async def _handle_grid_status(self) -> None:
        prefs = await self._load_prefs()
        if not prefs.get("has_consumption"):
            return

        async def fetch():
            return await self._api_call("stats?granularity=day&start_at=2020-01-01")

        grid = await self._get_cached_or_fetch("grid", fetch)
        if isinstance(grid, dict) and "error" in grid:
            return
        intervals = grid.get("intervals", [])
        power = intervals[-1].get("powr", 0) if intervals else 0
        power_str = self._format_power(abs(power))
        if power < -100:
            await self.capability_worker.speak(
                f"You're sending {power_str} to the grid."
            )
        elif power > 100:
            await self.capability_worker.speak(
                f"You're drawing {power_str} from the grid."
            )
        else:
            await self.capability_worker.speak("You're roughly net zero with the grid.")

    async def _handle_today_summary(self) -> None:
        async def fetch():
            return await self._api_call("stats?granularity=day&start_at=2020-01-01")

        stats = await self._get_cached_or_fetch("stats", fetch)
        if isinstance(stats, dict) and "error" in stats:
            await self.capability_worker.speak(
                self._speak_error(stats["error"])
            )
            return
        intervals = stats.get("intervals", [])
        energy_today = intervals[-1].get("enwh", 0) if intervals else 0
        energy_str = self._format_energy(energy_today)
        await self.capability_worker.speak(
            f"Today so far you've generated {energy_str}."
        )

    async def _handle_system_health(self) -> None:
        async def fetch():
            return await self._api_call("stats?granularity=day&start_at=2020-01-01")

        stats = await self._get_cached_or_fetch("stats", fetch)
        if isinstance(stats, dict) and "error" in stats:
            await self.capability_worker.speak(
                self._speak_error(stats["error"])
            )
            return
        meta = stats.get("meta", {})
        status = meta.get("status", "normal")
        await self.capability_worker.speak(
            f"Your system health is {status}."
        )
