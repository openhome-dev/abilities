import requests
from datetime import datetime, timezone

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "lightning_alert_data"
IPAPI_URL = "http://ip-api.com/json"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

POLL_INTERVAL = 600.0        # 10 minutes
POLL_NO_LOCATION = 60.0      # retry fast until location is available
STARTUP_GRACE = 90           # seconds — skip first-poll duplicate alerts

THUNDERSTORM_CODES = {95, 96, 99}
CLOUD_ISPS = {"amazon", "aws", "google", "microsoft", "azure", "digitalocean", "linode", "vultr"}


def _empty_data() -> dict:
    return {
        "location": {},
        "prefs": {
            "warn_minutes": 90,
            "clear_alerts": True,
        },
        "storm_active": False,
        "last_onset_alert": "",
        "last_clear_alert": "",
    }


class LightningAlertBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
            return _empty_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[LightningBG] Load error: {e!r}")
            return _empty_data()

    def _save_data(self, data: dict):
        try:
            self.capability_worker.create_key(STORAGE_KEY, data)
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, data)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[LightningBG] Save error: {e!r}")

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    def _geolocate_ip(self) -> dict | None:
        try:
            ip = self.worker.user_socket.client.host
            resp = requests.get(f"{IPAPI_URL}/{ip}", timeout=5)
            if resp.status_code == 200:
                d = resp.json()
                if d.get("status") == "success":
                    isp = d.get("isp", "").lower()
                    if any(c in isp for c in CLOUD_ISPS):
                        return None
                    return {
                        "lat": d.get("lat"),
                        "lon": d.get("lon"),
                        "name": d.get("city", "your location"),
                        "tz": d.get("timezone", "UTC"),
                        "auto": True,
                    }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[LightningBG] IP geo error: {e!r}")
        return None

    # ------------------------------------------------------------------
    # Weather APIs
    # ------------------------------------------------------------------

    def _fetch_storm_data(self, lat: float, lon: float, warn_minutes: int) -> dict:
        result = {
            "storm_now": False,
            "minutes_to_storm": None,
            "nws_active": False,
        }
        try:
            resp = requests.get(
                OPEN_METEO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "minutely_15": "weathercode",
                    "forecast_days": 1,
                    "timezone": "auto",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                m15 = resp.json().get("minutely_15", {})
                codes = m15.get("weathercode", [])
                times = m15.get("time", [])

                if codes and codes[0] in THUNDERSTORM_CODES:
                    result["storm_now"] = True

                now_ts = datetime.now(timezone.utc).timestamp()
                slots = min(len(codes), len(times), (warn_minutes // 15) + 2)
                for t, c in zip(times[:slots], codes[:slots]):
                    if c in THUNDERSTORM_CODES:
                        try:
                            slot_ts = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
                            result["minutes_to_storm"] = max(0, int((slot_ts - now_ts) / 60))
                        except Exception:
                            result["minutes_to_storm"] = 0
                        break
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[LightningBG] Open-Meteo error: {e!r}")

        try:
            nws_resp = requests.get(
                NWS_ALERTS_URL,
                params={"point": f"{lat},{lon}", "status": "actual"},
                headers={"User-Agent": "OpenHome-LightningAlert"},
                timeout=8,
            )
            if nws_resp.status_code == 200:
                for f in nws_resp.json().get("features", []):
                    event = f.get("properties", {}).get("event", "").lower()
                    if any(k in event for k in ("thunder", "lightning", "severe")):
                        result["nws_active"] = True
                        break
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------
    # Alert builders
    # ------------------------------------------------------------------

    def _onset_message(self, minutes: int, name: str) -> str:
        if minutes == 0:
            return (
                f"Lightning alert — a thunderstorm is active near {name}. "
                "Stay indoors and away from windows."
            )
        if minutes <= 30:
            return (
                f"Lightning alert — a storm is about {minutes} minutes from {name}. "
                "Head inside now."
            )
        hours, mins = divmod(minutes, 60)
        if hours and mins:
            timing = f"{hours} hour{'s' if hours > 1 else ''} and {mins} minutes"
        elif hours:
            timing = f"about {hours} hour{'s' if hours > 1 else ''}"
        else:
            timing = f"about {minutes} minutes"
        return (
            f"Lightning alert — a storm is {timing} from {name}. "
            "Finish up outside and get indoors before it arrives."
        )

    def _clear_message(self, name: str) -> str:
        return f"The storm near {name} has passed. Conditions are clearing."

    # ------------------------------------------------------------------
    # Main daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        self.capability_worker.resume_normal_flow()
        self.worker.editor_logging_handler.info("[LightningBG] Daemon started")

        started_at = datetime.now(timezone.utc).timestamp()

        while True:
            try:
                data = self._load_data()
                loc = data.get("location", {})
                lat = loc.get("lat")
                name = loc.get("name", "your location")

                # Auto-detect location from IP if not set
                if lat is None:
                    detected = self._geolocate_ip()
                    if detected:
                        data["location"] = detected
                        self._save_data(data)
                        lat = detected["lat"]
                        name = detected["name"]
                        self.worker.editor_logging_handler.info(
                            f"[LightningBG] Auto-detected location: {name}"
                        )
                    else:
                        self.worker.editor_logging_handler.info(
                            "[LightningBG] No location yet — retrying in 60s"
                        )
                        await self.worker.session_tasks.sleep(POLL_NO_LOCATION)
                        continue

                lon = data["location"].get("lon")
                prefs = data.get("prefs", {})
                warn_minutes = prefs.get("warn_minutes", 90)
                clear_alerts = prefs.get("clear_alerts", True)

                daemon_age = datetime.now(timezone.utc).timestamp() - started_at
                storm_data = self._fetch_storm_data(lat, lon, warn_minutes)

                storm_incoming = (
                    storm_data["minutes_to_storm"] is not None
                    and storm_data["minutes_to_storm"] <= warn_minutes
                ) or storm_data["nws_active"]

                storm_now = storm_data["storm_now"] or storm_data["nws_active"]
                was_active = data.get("storm_active", False)

                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                changed = False

                # Onset alert — skip during startup grace period
                if storm_incoming and daemon_age > STARTUP_GRACE:
                    if data.get("last_onset_alert") != today:
                        data["last_onset_alert"] = today
                        data["storm_active"] = True
                        changed = True
                        self._save_data(data)
                        minutes = storm_data["minutes_to_storm"] or 0
                        msg = self._onset_message(minutes, name)
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(msg)
                        self.worker.editor_logging_handler.info(
                            f"[LightningBG] Onset alert fired for {name}"
                        )

                # Update storm_active flag
                elif not storm_incoming and was_active:
                    data["storm_active"] = False
                    changed = True

                # Clear alert — storm passed
                if clear_alerts and was_active and not storm_now:
                    if data.get("last_clear_alert") != today:
                        data["last_clear_alert"] = today
                        changed = True
                        self._save_data(data)
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(self._clear_message(name))
                        self.worker.editor_logging_handler.info(
                            f"[LightningBG] Clear alert fired for {name}"
                        )

                if changed:
                    self._save_data(data)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[LightningBG] Loop error: {e!r}")

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.background_daemon_mode = background_daemon_mode
        self.worker.session_tasks.create(self.watch_loop())
