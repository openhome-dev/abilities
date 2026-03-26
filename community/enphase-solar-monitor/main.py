"""
Enphase Solar Monitor - OpenHome Ability V2
Voice-activated solar dashboard for Enphase systems.
Fetches production, consumption, and battery data from Enphase Cloud API v4.

V2 Features: Historical data, comparisons, lifetime stats, panel health
"""

import json
import time
from datetime import datetime, timezone, timedelta
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

# Hardcoded configuration - OpenHome blocks file access at registration time
UNIQUE_NAME = "enphase_solar_monitor"
MATCHING_HOTWORDS = [
    "solar",
    "solar status",
    "solar production",
    "how's my solar",
    "hows my solar",
    "how is my solar",
    "enphase",
    "solar panels",
    "battery level",
    "battery status",
    "my battery status",
    "battery",
    "am I exporting",
    "grid status",
    "solar today",
    "check my solar",
    "solar power",
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

    # {{register_capability}}
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

    async def _load_prefs(self):
        """Load preferences using OpenHome File Storage API."""
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                content = await self.capability_worker.read_file(PREFS_FILE, False)
                prefs = json.loads(content)
                if DEMO_MODE and not prefs.get("system_id"):
                    prefs.setdefault("has_battery", True)
                    prefs.setdefault("has_consumption", True)
                return prefs
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Failed to load prefs: {e}")

        if DEMO_MODE:
            return {"has_battery": True, "has_consumption": True}
        return {}

    async def _save_prefs(self, prefs):
        """Save preferences using OpenHome File Storage API with delete-then-write pattern."""
        try:
            # SDK requirement: delete file before writing
            if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                await self.capability_worker.delete_file(PREFS_FILE, False)

            await self.capability_worker.write_file(
                PREFS_FILE,
                json.dumps(prefs, indent=2),
                False,
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

    async def _api_call(self, endpoint: str, extra_params: Optional[dict] = None):
        """Make an authenticated Enphase API call with auto-retry on 401."""
        if DEMO_MODE:
            now = datetime.now(timezone.utc)

            if endpoint == "summary":
                return {
                    "current_power": 4200,
                    "energy_today": 28000,
                    "energy_lifetime": 15000000,
                    "status": "normal",
                    "last_report_at": now.isoformat(),
                }
            if endpoint == "encharge":
                return {
                    "state_of_charge": 0.73,
                    "status": "charging",
                    "available_energy": 8500,
                }
            if endpoint == "consumption_stats":
                return {
                    "consumption": 3100,
                    "energy_today": 22000,
                }
            if "energy_lifetime" in endpoint:
                days = []
                for i in range(7, 0, -1):
                    date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                    energy = 25000 + (i * 1500)
                    days.append({"date": date, "wh": energy})
                return {"intervals": days}
            if endpoint == "inventory" or endpoint == "devices":
                devices = []
                for i in range(24):
                    devices.append({
                        "serial_num": f"12345{i:02d}",
                        "device_status": ["normal", "normal", "normal", "power"][i % 4],
                        "last_report_date": now.isoformat(),
                    })
                return {"envoys": [{"devices": devices}]}

            return {"error": "unknown_endpoint"}

        try:
            prefs = await self._load_prefs()
            system_id = prefs.get("system_id")
            if not system_id:
                return {"error": "no_system_id"}

            url = f"{ENPHASE_BASE_URL}/systems/{system_id}/{endpoint}"
            params = {"key": prefs.get("api_key")}
            if extra_params:
                params.update(extra_params)

            headers = {"Authorization": f"Bearer {prefs.get('access_token')}"}
            response = requests.get(url, headers=headers, params=params, timeout=15)

            if response.status_code == 401:
                if await self._refresh_access_token():
                    prefs = await self._load_prefs()
                    headers = {"Authorization": f"Bearer {prefs.get('access_token')}"}
                    response = requests.get(url, headers=headers, params=params, timeout=15)
                else:
                    return {"error": "auth_failed"}

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                return {"error": "rate_limited"}
            elif response.status_code == 404:
                return {"error": "system_not_found"}
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

    async def _get_cached_or_fetch(self, cache_key: str, fetch_function: Callable):
        """Check cache first, fetch if expired or missing. Cache TTL: 15 minutes."""
        try:
            prefs = await self._load_prefs()
            cache = prefs.get("cache", {})

            if cache_key in cache:
                cached_data = cache[cache_key]
                timestamp = cached_data.get("timestamp", 0)
                age = time.time() - timestamp
                if age < CACHE_TTL:
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

    def _format_megawatt_hours(self, watt_hours: Optional[float]) -> str:
        if watt_hours is None:
            return "unknown"
        mwh = watt_hours / 1000000.0
        if mwh < 1:
            return self._format_energy(watt_hours)
        return f"{round(mwh, 1)} megawatt hours"

    def _format_battery(self, soc_decimal: Optional[float]) -> str:
        if soc_decimal is None:
            return "unknown"
        percentage = round(soc_decimal * 100)
        return f"{percentage} percent"

    def _format_timestamp_age(self, timestamp_str: Optional[str]) -> str:
        if not timestamp_str:
            return "from the latest reading"
        try:
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
            age_minutes = age_seconds / 60
            if age_minutes < 20:
                return "as of about 15 minutes ago"
            elif age_minutes < 60:
                return f"as of about {round(age_minutes)} minutes ago"
            else:
                return f"as of about {round(age_minutes / 60, 1)} hours ago"
        except Exception:
            return "from the latest reading"

    def _calculate_percentage_change(self, old_value: float, new_value: float) -> str:
        if old_value == 0:
            return "significantly higher"
        change = ((new_value - old_value) / old_value) * 100
        if abs(change) < 1:
            return "about the same"
        direction = "up" if change > 0 else "down"
        return f"{direction} {abs(round(change))} percent"

    def _is_exit_word(self, text: Optional[str]) -> bool:
        if not text:
            return False
        return any(word in text.lower() for word in EXIT_WORDS)

    def _classify_intent(self, user_input: str) -> str:
        system_prompt = """Classify the user's solar system query into ONE of these intents:

V1 Intents:
- solar_snapshot: "how's my solar", "solar status", "check my solar", "give me a summary"
- battery_status: "battery level", "battery percentage", "what's my battery"
- consumption: "how much am I using", "consumption", "usage", "power usage"
- grid_status: "grid status", "am I exporting", "grid import", "grid export"
- today_summary: "today's total", "how much today", "today so far", "production today"
- system_health: "system health", "is my system ok", "system status"

V2 Historical Intents:
- yesterday_summary: "how much yesterday", "yesterday's production", "yesterday"
- this_week: "this week", "weekly total", "week's production", "how much this week"
- this_month: "this month", "monthly total", "how much this month", "month's production"
- compare_yesterday: "better than yesterday", "compared to yesterday", "am I doing better"
- lifetime_stats: "total production ever", "lifetime", "all time", "total ever"
- panel_health: "are all panels working", "panel status", "microinverters", "panel health"

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
            if not DEMO_MODE:
                prefs = await self._load_prefs()
                if not prefs.get("system_id") or not prefs.get("api_key"):
                    await self.capability_worker.speak(
                        "You haven't set up your Enphase system yet. "
                        "Add your system ID and API credentials in the preferences file."
                    )
                    return

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
                elif intent == "yesterday_summary":
                    await self._handle_yesterday_summary()
                elif intent == "this_week":
                    await self._handle_this_week()
                elif intent == "this_month":
                    await self._handle_this_month()
                elif intent == "compare_yesterday":
                    await self._handle_compare_yesterday()
                elif intent == "lifetime_stats":
                    await self._handle_lifetime_stats()
                elif intent == "panel_health":
                    await self._handle_panel_health()
                else:
                    await self.capability_worker.speak(
                        "I didn't catch that. You can ask about production, "
                        "consumption, battery, grid status, or historical data."
                    )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Solar monitor error: {e}")
            await self.capability_worker.speak("Something went wrong. Try again later.")
        finally:
            self.capability_worker.resume_normal_flow()

    async def _handle_solar_snapshot(self) -> None:
        async def fetch():
            return await self._api_call("summary")

        data = await self._get_cached_or_fetch("summary", fetch)

        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        power = data.get("current_power")
        energy_today = data.get("energy_today")
        last_report = data.get("last_report_at")

        staleness = self._format_timestamp_age(last_report)
        power_str = self._format_power(power)
        energy_str = self._format_energy(energy_today)

        await self.capability_worker.speak(
            f"You're producing {power_str} right now, {staleness}."
        )
        await self.capability_worker.speak(
            f"Today you've generated {energy_str}."
        )

        prefs = await self._load_prefs()

        if prefs.get("has_battery"):
            await self._handle_battery_status()

        if prefs.get("has_consumption"):
            async def fetch_consumption():
                return await self._api_call("consumption_stats")

            consumption_data = await self._get_cached_or_fetch("consumption_stats", fetch_consumption)
            if not (isinstance(consumption_data, dict) and "error" in consumption_data):
                if isinstance(consumption_data, list) and len(consumption_data) > 0:
                    consumption_data = consumption_data[-1]
                consumption = consumption_data.get("consumption")
                consumption_str = self._format_power(consumption)
                await self.capability_worker.speak(f"You're using {consumption_str} right now.")

        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            async def fetch_yesterday():
                return await self._api_call(
                    f"energy_lifetime?start_date={yesterday}&end_date={yesterday}"
                )
            yesterday_data = await self._get_cached_or_fetch(f"energy_{yesterday}", fetch_yesterday)

            if not (isinstance(yesterday_data, dict) and "error" in yesterday_data):
                intervals = yesterday_data.get("intervals", [])
                if intervals:
                    yesterday_energy = intervals[0].get("wh", 0)
                    if yesterday_energy > 0:
                        change = self._calculate_percentage_change(yesterday_energy, energy_today)
                        await self.capability_worker.speak(
                            f"You're {change} compared to yesterday."
                        )
        except Exception as e:
            self.worker.editor_logging_handler.info(f"Yesterday comparison skipped: {e}")

    async def _handle_battery_status(self) -> None:
        prefs = await self._load_prefs()
        if not prefs.get("has_battery"):
            await self.capability_worker.speak("Your system doesn't have battery storage.")
            return

        async def fetch():
            return await self._api_call("encharge")

        data = await self._get_cached_or_fetch("encharge", fetch)

        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        if isinstance(data, list) and len(data) > 0:
            data = data[0]

        soc = data.get("state_of_charge")
        status = data.get("status", "idle")
        soc_str = self._format_battery(soc)

        status_map = {
            "charging": "and charging.",
            "discharging": "and discharging.",
            "idle": "and idle.",
        }
        status_phrase = status_map.get((status or "").lower(), "and idle.")

        await self.capability_worker.speak(f"Your battery is at {soc_str} {status_phrase}")

    async def _handle_consumption(self) -> None:
        prefs = await self._load_prefs()
        if not prefs.get("has_consumption"):
            await self.capability_worker.speak("Your system doesn't have consumption monitoring.")
            return

        async def fetch():
            return await self._api_call("consumption_stats")

        data = await self._get_cached_or_fetch("consumption_stats", fetch)

        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        if isinstance(data, list) and len(data) > 0:
            data = data[-1]

        consumption = data.get("consumption")
        energy_today = data.get("energy_today")
        consumption_str = self._format_power(consumption)
        energy_str = self._format_energy(energy_today)

        await self.capability_worker.speak(f"You're using {consumption_str} right now.")
        await self.capability_worker.speak(f"Today you've used {energy_str}.")

    async def _handle_grid_status(self) -> None:
        prefs = await self._load_prefs()
        if not prefs.get("has_consumption"):
            await self.capability_worker.speak(
                "Your system doesn't have consumption monitoring, "
                "so I can't tell grid import or export."
            )
            return

        async def fetch_summary():
            return await self._api_call("summary")

        async def fetch_consumption():
            return await self._api_call("consumption_stats")

        summary = await self._get_cached_or_fetch("summary", fetch_summary)
        consumption_data = await self._get_cached_or_fetch("consumption_stats", fetch_consumption)

        if isinstance(summary, dict) and "error" in summary:
            await self.capability_worker.speak(self._speak_error(summary["error"]))
            return
        if isinstance(consumption_data, dict) and "error" in consumption_data:
            await self.capability_worker.speak(self._speak_error(consumption_data["error"]))
            return

        if isinstance(consumption_data, list) and len(consumption_data) > 0:
            consumption_data = consumption_data[-1]

        production = summary.get("current_power") or 0
        consumption = consumption_data.get("consumption") or 0
        net = production - consumption
        last_report = summary.get("last_report_at")
        staleness = self._format_timestamp_age(last_report)

        if net > 0:
            await self.capability_worker.speak(
                f"You're sending {self._format_power(net)} to the grid, {staleness}."
            )
        elif net < 0:
            await self.capability_worker.speak(
                f"You're pulling {self._format_power(abs(net))} from the grid, {staleness}."
            )
        else:
            await self.capability_worker.speak(
                f"You're balanced with the grid right now, {staleness}."
            )

    async def _handle_today_summary(self) -> None:
        async def fetch():
            return await self._api_call("summary")

        data = await self._get_cached_or_fetch("summary", fetch)

        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        energy_today = data.get("energy_today")
        energy_str = self._format_energy(energy_today)

        await self.capability_worker.speak(f"Today so far you've generated {energy_str}.")

    async def _handle_system_health(self) -> None:
        async def fetch():
            return await self._api_call("summary")

        data = await self._get_cached_or_fetch("summary", fetch)

        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        status = data.get("status", "unknown")

        if status == "normal":
            await self.capability_worker.speak("Your system is healthy and reporting normally.")
        else:
            await self.capability_worker.speak(
                "Your system is reporting an issue. Check the Enphase app for details."
            )

    async def _handle_yesterday_summary(self) -> None:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        async def fetch():
            return await self._api_call(
                f"energy_lifetime?start_date={yesterday}&end_date={yesterday}"
            )

        data = await self._get_cached_or_fetch(f"energy_{yesterday}", fetch)
        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        intervals = data.get("intervals", [])
        if not intervals:
            await self.capability_worker.speak("I don't have data for yesterday yet.")
            return

        yesterday_energy = intervals[0].get("wh", 0)
        energy_str = self._format_energy(yesterday_energy)

        await self.capability_worker.speak(f"Yesterday you generated {energy_str}.")

    async def _handle_this_week(self) -> None:
        today = datetime.now()
        week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        async def fetch():
            return await self._api_call(
                f"energy_lifetime?start_date={week_start}&end_date={today_str}"
            )

        data = await self._get_cached_or_fetch(f"energy_week_{week_start}", fetch)
        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        intervals = data.get("intervals", [])
        if not intervals:
            await self.capability_worker.speak("I don't have weekly data yet.")
            return

        total_wh = sum(day.get("wh", 0) for day in intervals)
        avg_wh = total_wh / len(intervals) if intervals else 0
        best_day = max(intervals, key=lambda d: d.get("wh", 0))
        best_day_wh = best_day.get("wh", 0)
        best_day_date = best_day.get("date", "")

        try:
            day_name = datetime.strptime(best_day_date, "%Y-%m-%d").strftime("%A")
        except Exception:
            day_name = "one day"

        total_str = self._format_energy(total_wh)
        avg_str = self._format_energy(avg_wh)
        best_str = self._format_energy(best_day_wh)

        await self.capability_worker.speak(
            f"This week you've generated {total_str} total. "
            f"That's an average of {avg_str} per day."
        )
        await self.capability_worker.speak(f"Your best day was {day_name} with {best_str}.")

    async def _handle_this_month(self) -> None:
        today = datetime.now()
        month_start = today.replace(day=1).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        async def fetch():
            return await self._api_call(
                f"energy_lifetime?start_date={month_start}&end_date={today_str}"
            )

        data = await self._get_cached_or_fetch(f"energy_month_{month_start}", fetch)
        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        intervals = data.get("intervals", [])
        if not intervals:
            await self.capability_worker.speak("I don't have monthly data yet.")
            return

        total_wh = sum(day.get("wh", 0) for day in intervals)
        avg_wh = total_wh / len(intervals) if intervals else 0

        total_str = self._format_energy(total_wh)
        avg_str = self._format_energy(avg_wh)

        await self.capability_worker.speak(
            f"This month you've generated {total_str} total. "
            f"That's an average of {avg_str} per day."
        )

    async def _handle_compare_yesterday(self) -> None:
        async def fetch_today():
            return await self._api_call("summary")

        today_data = await self._get_cached_or_fetch("summary", fetch_today)
        if isinstance(today_data, dict) and "error" in today_data:
            await self.capability_worker.speak(self._speak_error(today_data["error"]))
            return

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        async def fetch_yesterday():
            return await self._api_call(
                f"energy_lifetime?start_date={yesterday}&end_date={yesterday}"
            )

        yesterday_data = await self._get_cached_or_fetch(f"energy_{yesterday}", fetch_yesterday)
        if isinstance(yesterday_data, dict) and "error" in yesterday_data:
            await self.capability_worker.speak("I don't have yesterday's data to compare.")
            return

        today_energy = today_data.get("energy_today", 0)
        intervals = yesterday_data.get("intervals", [])
        yesterday_energy = intervals[0].get("wh", 0) if intervals else 0

        if yesterday_energy == 0:
            await self.capability_worker.speak("I don't have enough data to compare yet.")
            return

        change = self._calculate_percentage_change(yesterday_energy, today_energy)
        today_str = self._format_energy(today_energy)
        yesterday_str = self._format_energy(yesterday_energy)

        await self.capability_worker.speak(
            f"You're {change} compared to yesterday. "
            f"Yesterday you made {yesterday_str}, today you're at {today_str}."
        )

    async def _handle_lifetime_stats(self) -> None:
        async def fetch():
            return await self._api_call("summary")

        data = await self._get_cached_or_fetch("summary", fetch)
        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        lifetime_wh = data.get("energy_lifetime", 0)
        lifetime_str = self._format_megawatt_hours(lifetime_wh)
        kwh = lifetime_wh / 1000

        await self.capability_worker.speak(
            f"Since installation, you've generated {lifetime_str} total. "
            f"That's {round(kwh)} kilowatt hours."
        )

    async def _handle_panel_health(self) -> None:
        async def fetch():
            return await self._api_call("inventory")

        data = await self._get_cached_or_fetch("inventory", fetch)
        if isinstance(data, dict) and "error" in data:
            await self.capability_worker.speak(self._speak_error(data["error"]))
            return

        envoys = data.get("envoys", [])
        if not envoys:
            await self.capability_worker.speak("I can't get panel data right now.")
            return

        devices = envoys[0].get("devices", [])
        total_devices = len(devices)

        offline = [d for d in devices if d.get("device_status") != "normal"]
        offline_count = len(offline)

        if offline_count == 0:
            await self.capability_worker.speak(
                f"All {total_devices} microinverters are reporting normally. Your system is healthy."
            )
        else:
            await self.capability_worker.speak(
                f"You have {offline_count} microinverter{'s' if offline_count > 1 else ''} "
                f"not reporting normally out of {total_devices} total. "
                "Check the Enphase app for details."
            )
