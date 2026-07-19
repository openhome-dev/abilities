import requests
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    _HAS_ZONEINFO = True
except ImportError:
    _HAS_ZONEINFO = False

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "space_window_data"
ISS_NORAD_ID = 25544
N2YO_BASE = "https://www.n2yo.com/rest/v1/satellite"
NOAA_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
LAUNCHES_URL = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/"

POLL_INTERVAL = 1800.0       # 30 minutes
POLL_NO_LOCATION = 60.0      # fast retry until location is set
ISS_ALERT_WINDOW = 2400      # alert if pass starts within 40 minutes (> poll interval)


def _empty_data() -> dict:
    return {
        "location": {},
        "alert_prefs": {
            "min_elevation": 30,
            "aurora_kp_threshold": 5,
            "iss_alerts": True,
            "aurora_alerts": True,
            "launch_alerts": True,
        },
        "alerted_passes": [],
        "alerted_launches": [],
        "last_aurora_alert": "",
        "last_morning_brief": "",
    }


class SpaceWindowBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False
    n2yo_key: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Context Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
            return _empty_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SpaceWindow] Load error: {e}")
            return _empty_data()

    def _save_data(self, data: dict):
        try:
            self.capability_worker.create_key(STORAGE_KEY, data)
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, data)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[SpaceWindow] Save error: {e!r}")

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------

    def _format_local_time(self, utc_ts: int, tz_name: str) -> str:
        dt_utc = datetime.fromtimestamp(utc_ts, tz=timezone.utc)
        if _HAS_ZONEINFO and tz_name:
            try:
                dt_local = dt_utc.astimezone(ZoneInfo(tz_name))
                hour = dt_local.hour
                minute = dt_local.minute
                period = "am" if hour < 12 else "pm"
                hour12 = hour % 12 or 12
                if minute:
                    return f"{hour12}:{minute:02d}{period}"
                return f"{hour12}{period}"
            except Exception:
                pass
        return dt_utc.strftime("%H:%M UTC")

    def _local_hour(self, tz_name: str) -> int:
        if _HAS_ZONEINFO and tz_name:
            try:
                return datetime.now(ZoneInfo(tz_name)).hour
            except Exception:
                pass
        return datetime.now(timezone.utc).hour

    def _today_str(self, tz_name: str) -> str:
        if _HAS_ZONEINFO and tz_name:
            try:
                return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
            except Exception:
                pass
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Aurora
    # ------------------------------------------------------------------

    def _aurora_min_kp(self, lat: float) -> int:
        lat = abs(lat)
        if lat >= 65:
            return 3
        elif lat >= 60:
            return 4
        elif lat >= 55:
            return 5
        elif lat >= 50:
            return 6
        elif lat >= 45:
            return 7
        return 8

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def _fetch_iss_passes(self, lat: float, lon: float) -> list:
        if not self.n2yo_key:
            return []
        try:
            url = f"{N2YO_BASE}/visualpasses/{ISS_NORAD_ID}/{lat}/{lon}/0/2/60/"
            resp = requests.get(url, params={"apiKey": self.n2yo_key}, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("passes") or []
            return []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SpaceWindow] N2YO error: {e}")
            return []

    def _fetch_kp(self) -> float | None:
        try:
            resp = requests.get(NOAA_KP_URL, timeout=10)
            if resp.status_code != 200:
                return None
            rows = resp.json()
            if not isinstance(rows, list):
                return None
            for row in reversed(rows):
                if isinstance(row, dict):
                    for key in ("Kp", "kp", "kp_index", "Planetary_Kp"):
                        if key in row:
                            return float(row[key])
                elif isinstance(row, (list, tuple)) and len(row) > 1:
                    try:
                        return float(row[1])
                    except (ValueError, TypeError):
                        continue
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SpaceWindow] NOAA error: {e!r}")
            return None

    def _fetch_launches(self, days: int = 2) -> list:
        try:
            window_end = (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            resp = requests.get(
                LAUNCHES_URL,
                params={"limit": 5, "status": 1, "net__lte": window_end},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("results", [])
            return []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SpaceWindow] Launches error: {e}")
            return []

    # ------------------------------------------------------------------
    # Proactive alerts
    # ------------------------------------------------------------------

    async def _alert_iss(self, p: dict, name: str, tz_name: str):
        rise_time = self._format_local_time(p["startUTC"], tz_name)
        max_el = p.get("maxEl", 0)
        duration_min = max(1, p.get("duration", 60) // 60)
        start_dir = p.get("startAzCompass", "")
        quality = "great" if max_el >= 60 else "good" if max_el >= 40 else "fair"
        mins_away = max(1, int((p["startUTC"] - datetime.now(timezone.utc).timestamp()) / 60))

        msg = (
            f"ISS passes {name} in {mins_away} {'minute' if mins_away == 1 else 'minutes'}. "
            f"Rises {start_dir} at {rise_time}, peaks {max_el:.0f} degrees — {quality} pass, "
            f"{duration_min} {'minute' if duration_min == 1 else 'minutes'} visible. Head outside now."
        )
        await self.capability_worker.send_interrupt_signal()
        await self.capability_worker.speak(msg)

    async def _alert_aurora(self, kp: float, name: str):
        msg = (
            f"Aurora alert — Kp index just hit {kp:.0f}, which is high enough to see northern lights "
            f"from {name}. Look north, away from city lights. Activity can fade fast."
        )
        await self.capability_worker.send_interrupt_signal()
        await self.capability_worker.speak(msg)

    async def _alert_launch(self, launch: dict, tz_name: str, hours_away: float):
        lname = launch.get("name", "Unknown mission")
        rocket = launch.get("rocket", {}).get("configuration", {}).get("full_name", "")
        pad = launch.get("pad", {}).get("location", {}).get("name", "")
        launch.get("net", "")

        if hours_away <= 1:
            timing = "in about an hour"
        else:
            timing = f"in {int(hours_away)} hours"

        msg = lname
        if rocket and rocket not in lname:
            msg += f" on {rocket}"
        msg += f" launches {timing}"
        if pad:
            msg += f" from {pad}"
        msg += "."

        await self.capability_worker.send_interrupt_signal()
        await self.capability_worker.speak(msg)

    async def _speak_morning_brief(self, data: dict):
        loc = data.get("location", {})
        name = loc.get("name", "your location")
        tz_name = loc.get("tz", "UTC")
        lat = loc.get("lat")
        lon = loc.get("lon")
        min_el = data["alert_prefs"].get("min_elevation", 30)

        parts = []

        if self.n2yo_key and lat is not None:
            passes = self._fetch_iss_passes(lat, lon)
            good = [p for p in passes if p.get("maxEl", 0) >= min_el]
            if good:
                count = len(good)
                p = good[0]
                t = self._format_local_time(p["startUTC"], tz_name)
                max_el = p.get("maxEl", 0)
                iss_part = f"ISS passes {count} {'time' if count == 1 else 'times'} today, first at {t}, peaks {max_el:.0f} degrees"
                parts.append(iss_part)
            else:
                parts.append("No good ISS passes today")

        launches = self._fetch_launches(days=1)
        if launches:
            lname = launches[0].get("name", "Unknown")
            parts.append(f"{lname} launches today")

        kp = self._fetch_kp()
        if kp is not None:
            min_kp = data["alert_prefs"].get("aurora_kp_threshold", 5)
            if kp >= min_kp:
                parts.append(f"aurora activity elevated, Kp at {kp:.0f}")

        if not parts:
            return

        try:
            await self.capability_worker.send_interrupt_signal()
            await self.capability_worker.speak(
                f"Good morning — here's tonight's sky for {name}. " + ". ".join(parts) + "."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SpaceWindow] Morning brief error: {e}")

    # ------------------------------------------------------------------
    # Main daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        self.n2yo_key = self.capability_worker.get_api_keys("n2yo_api_key") or ""

        if not self.n2yo_key:
            self.worker.editor_logging_handler.warning(
                "[SpaceWindow] No N2YO API key — ISS tracking disabled. "
                "Aurora and launch alerts still active."
            )

        self.capability_worker.resume_normal_flow()
        self.worker.editor_logging_handler.info("[SpaceWindow] daemon started")

        started_at = datetime.now(timezone.utc).timestamp()

        while True:
            try:
                data = self._load_data()
                loc = data.get("location", {})
                lat = loc.get("lat")
                lon = loc.get("lon")
                tz_name = loc.get("tz", "UTC")
                name = loc.get("name", "your location")

                if lat is None:
                    await self.worker.session_tasks.sleep(POLL_NO_LOCATION)
                    continue

                prefs = data.get("alert_prefs", {})
                today = self._today_str(tz_name)
                local_hour = self._local_hour(tz_name)

                # Morning brief once per day around 9am
                if local_hour == 9 and data.get("last_morning_brief") != today:
                    data["last_morning_brief"] = today
                    self._save_data(data)
                    await self._speak_morning_brief(data)

                now_ts = datetime.now(timezone.utc).timestamp()
                changed = False

                # ISS pass alerts
                if prefs.get("iss_alerts", True) and self.n2yo_key:
                    min_el = prefs.get("min_elevation", 30)
                    passes = self._fetch_iss_passes(lat, lon)
                    alerted = data.get("alerted_passes", [])

                    for p in passes:
                        if p.get("maxEl", 0) < min_el:
                            continue
                        start_utc = p.get("startUTC", 0)
                        secs_away = start_utc - now_ts
                        if 0 < secs_away <= ISS_ALERT_WINDOW and start_utc not in alerted:
                            alerted.append(start_utc)
                            data["alerted_passes"] = alerted
                            changed = True
                            self._save_data(data)
                            await self._alert_iss(p, name, tz_name)
                            break  # one alert per poll cycle

                # Aurora alerts
                if prefs.get("aurora_alerts", True):
                    kp = self._fetch_kp()
                    min_kp = prefs.get("aurora_kp_threshold", self._aurora_min_kp(lat))
                    last_alert = data.get("last_aurora_alert", "")
                    if kp is not None and kp >= min_kp and last_alert != today:
                        data["last_aurora_alert"] = today
                        changed = True
                        self._save_data(data)
                        await self._alert_aurora(kp, name)

                # Launch alerts (24h and 1h before)
                # Skip first poll if daemon just started — foreground already announced any imminent launches
                daemon_age_secs = datetime.now(timezone.utc).timestamp() - started_at
                if prefs.get("launch_alerts", True) and daemon_age_secs > 90:
                    launches = self._fetch_launches(days=2)
                    alerted_launches = data.get("alerted_launches", [])

                    for launch in launches:
                        launch_id = launch.get("id", "")
                        net = launch.get("net", "")
                        if not launch_id or not net:
                            continue
                        try:
                            launch_dt = datetime.fromisoformat(net.replace("Z", "+00:00"))
                            hours_away = (launch_dt.timestamp() - now_ts) / 3600

                            for window_hours, suffix in [(1.5, "_1h"), (25, "_24h")]:
                                alert_key = f"{launch_id}{suffix}"
                                threshold = 1.5 if suffix == "_1h" else 25
                                if 0 < hours_away <= threshold and alert_key not in alerted_launches:
                                    alerted_launches.append(alert_key)
                                    data["alerted_launches"] = alerted_launches
                                    changed = True
                                    self._save_data(data)
                                    await self._alert_launch(launch, tz_name, hours_away)
                                    break
                        except Exception:
                            continue

                if changed:
                    self.worker.editor_logging_handler.info(
                        "[SpaceWindow] Poll complete — alerts fired"
                    )

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[SpaceWindow] Loop error: {e}")

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.background_daemon_mode = background_daemon_mode
        self.worker.session_tasks.create(self.watch_loop())
