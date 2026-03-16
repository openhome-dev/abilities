import json
from datetime import datetime
from time import time
from zoneinfo import ZoneInfo

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

ALADHAN_URL = "https://api.aladhan.com/v1/timingsByCity"
DATA_FILE = "prayer_data.json"
PRAYER_NAMES = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]
DEFAULT_METHOD = 2

# How many minutes before prayer to send reminder
REMINDER_MINUTES = 5

# Check interval in seconds
CHECK_INTERVAL = 30

# Re-read config file every N loops (~5 min) to pick up user changes
CONFIG_REFRESH_LOOPS = 10

# After API failure, wait this many loops before retrying (~5 min)
API_RETRY_COOLDOWN = 10


class PrayerTimesBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    #{{register capability}}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_time(raw: str) -> str:
        return raw.split("(")[0].strip()

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------
    async def _read_data(self) -> dict:
        try:
            if not await self.capability_worker.check_if_file_exists(DATA_FILE, False):
                return {}
            raw = await self.capability_worker.read_file(DATA_FILE, False)
            if not (raw or "").strip():
                return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    async def _write_data(self, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            await self.capability_worker.delete_file(DATA_FILE, False)
        except Exception:
            pass
        try:
            await self.capability_worker.write_file(DATA_FILE, payload, False)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PrayerBG] Write failed: {e}"
            )

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    def _fetch_times(self, city: str, country: str, method: int) -> dict | None:
        try:
            resp = requests.get(
                ALADHAN_URL,
                params={"city": city, "country": country, "method": method},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("data", {}).get("timings", {})
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PrayerBG] API error: {e}"
            )
        return None

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------
    def _get_now(self) -> datetime:
        tz_name = self.capability_worker.get_timezone()
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        return datetime.now(tz=tz)

    def _parse_time(self, time_str: str, now: datetime) -> datetime | None:
        try:
            clean = self._clean_time(time_str)
            h, m = map(int, clean.split(":"))
            return now.replace(hour=h, minute=m, second=0, microsecond=0)
        except Exception:
            return None

    def _safe_interrupt(self, message: str) -> None:
        try:
            self.capability_worker.send_interrupt_signal(message)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PrayerBG] Interrupt failed: {e}"
            )

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------
    async def first_function(self):
        self.worker.editor_logging_handler.info(
            f"{time()}: Prayer Times background daemon started"
        )

        # In-memory caches to avoid repeated file reads and time parsing
        cached_data: dict = {}
        cached_timings: dict = {}  # {name: datetime} for today
        sent_today: dict[str, bool] = {}
        last_date: str = ""
        loops_since_file_read: int = CONFIG_REFRESH_LOOPS  # force read on first loop
        api_retry_countdown: int = 0

        while True:
            try:
                now = self._get_now()
                today_str = now.strftime("%Y-%m-%d")

                # Reset on new day
                if today_str != last_date:
                    sent_today = {}
                    cached_timings = {}
                    last_date = today_str
                    loops_since_file_read = CONFIG_REFRESH_LOOPS  # force re-read

                # Re-read config periodically to pick up user changes
                if loops_since_file_read >= CONFIG_REFRESH_LOOPS:
                    cached_data = await self._read_data()
                    loops_since_file_read = 0
                else:
                    loops_since_file_read += 1

                # Skip if not configured yet
                if not cached_data.get("city"):
                    await self.worker.session_tasks.sleep(CHECK_INTERVAL)
                    continue

                # Fetch and parse times once per day
                if not cached_timings:
                    if api_retry_countdown > 0:
                        api_retry_countdown -= 1
                        await self.worker.session_tasks.sleep(CHECK_INTERVAL)
                        continue

                    # Try cached timings from file first
                    file_timings = cached_data.get("last_timings", {})
                    if cached_data.get("last_fetch_date") == today_str and file_timings:
                        raw_timings = file_timings
                    else:
                        raw_timings_api = self._fetch_times(
                            cached_data["city"],
                            cached_data["country"],
                            cached_data.get("method", DEFAULT_METHOD),
                        )
                        if not raw_timings_api:
                            api_retry_countdown = API_RETRY_COOLDOWN
                            await self.worker.session_tasks.sleep(CHECK_INTERVAL)
                            continue
                        raw_timings = {
                            name: self._clean_time(raw_timings_api.get(name, ""))
                            for name in PRAYER_NAMES
                        }
                        cached_data["last_timings"] = raw_timings
                        cached_data["last_fetch_date"] = today_str
                        await self._write_data(cached_data)

                    # Parse all times into datetime objects (once per day)
                    for name in PRAYER_NAMES:
                        t_str = raw_timings.get(name)
                        if t_str:
                            dt = self._parse_time(t_str, now)
                            if dt:
                                cached_timings[name] = dt

                # Check each prayer time (cheap in-memory comparison)
                for name, prayer_dt in cached_timings.items():
                    diff_minutes = (prayer_dt - now).total_seconds() / 60

                    reminder_key = f"reminder_{name}"
                    adhan_key = f"adhan_{name}"

                    # Pre-prayer reminder (5 min before)
                    if (
                        0 < diff_minutes <= REMINDER_MINUTES
                        and reminder_key not in sent_today
                    ):
                        sent_today[reminder_key] = True
                        mins = int(diff_minutes)
                        self._safe_interrupt(
                            f"{name} is in {mins} minute{'s' if mins != 1 else ''}. "
                            f"Time to prepare."
                        )

                    # Adhan time notification (within 1 min window)
                    if (
                        -1 <= diff_minutes <= 0
                        and adhan_key not in sent_today
                    ):
                        sent_today[adhan_key] = True
                        self._safe_interrupt(f"It's time for {name}.")

                await self.worker.session_tasks.sleep(CHECK_INTERVAL)

            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[PrayerBG] Loop error: {e}"
                )
                await self.worker.session_tasks.sleep(CHECK_INTERVAL)

        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.first_function())
