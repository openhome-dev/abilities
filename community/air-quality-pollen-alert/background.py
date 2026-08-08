import requests
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "air_quality_data"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

POLL_INTERVAL = 300.0
STARTUP_GRACE = 90
DEFAULT_MORNING_TIME = "07:00"
DEFAULT_EVENING_TIME = "20:00"
DEFAULT_AQI_THRESHOLD = 100

AQI_LABELS = [
    (50, "good"),
    (100, "moderate"),
    (150, "elevated — concerning for sensitive groups"),
    (200, "poor"),
    (300, "very poor"),
    (500, "hazardous"),
]

POLLEN_LABELS = [
    (9, "low"),
    (49, "moderate"),
    (199, "high"),
    (999, "very high"),
]

MORNING_ALERT_PROMPT = (
    "Write a concise 3-sentence morning air quality briefing for a voice assistant. "
    "User conditions: {conditions}. Pollen triggers: {pollen_triggers}. "
    "Current AQI: {aqi} ({aqi_label}). Ozone: {ozone} μg/m³. "
    "Grass pollen: {grass} grains/m³ ({grass_level}). "
    "Tree pollen: {tree} grains/m³ ({tree_level}). "
    "Weed pollen: {weed} grains/m³ ({weed_level}). "
    "Best outdoor window today: {best_window}. "
    "Sentence 1: overall air quality summary. "
    "Sentence 2: specific concern for their condition if any. "
    "Sentence 3: one actionable recommendation. "
    "No markdown. Plain English. Spoken tone."
)

EVENING_PREP_PROMPT = (
    "Write a 2-sentence evening heads-up for a voice assistant. "
    "Tomorrow morning AQI forecast: {aqi_tomorrow} ({label_tomorrow}). "
    "Tomorrow peak pollen — grass: {grass}, tree: {tree}, weed: {weed} grains/m³. "
    "User conditions: {conditions}. "
    "Sentence 1: what tomorrow looks like. "
    "Sentence 2: one prep action for tonight (e.g. take antihistamine before bed, plan indoor morning). "
    "No markdown. Plain English. Spoken tone."
)


def _aqi_label(aqi: float) -> str:
    for threshold, label in AQI_LABELS:
        if aqi <= threshold:
            return label
    return "hazardous"


def _pollen_label(count: float) -> str:
    for threshold, label in POLLEN_LABELS:
        if count <= threshold:
            return label
    return "very high"


def _empty_data() -> dict:
    return {
        "location": {},
        "morning_alert_time": DEFAULT_MORNING_TIME,
        "evening_check_time": DEFAULT_EVENING_TIME,
        "conditions": [],
        "pollen_triggers": [],
        "alert_threshold_aqi": DEFAULT_AQI_THRESHOLD,
        "last_morning_alert_date": "",
        "last_evening_alert_date": "",
    }


class AirQualityPollenAlertBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
            return _empty_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[AQAlertBG] Load error: {e!r}")
            return _empty_data()

    def _save_data(self, data: dict):
        def ok(resp):
            return isinstance(resp, dict) and resp.get("success")
        try:
            if ok(self.capability_worker.create_key(STORAGE_KEY, data)):
                return
            if ok(self.capability_worker.update_key(STORAGE_KEY, data)):
                return
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[AQAlertBG] Save error: {e!r}")
            return
        self.worker.editor_logging_handler.error("[AQAlertBG] Save failed")

    def _fetch_air_quality(self, location: dict) -> dict:
        try:
            resp = requests.get(
                AQ_URL,
                params={
                    "latitude": location["lat"],
                    "longitude": location["lon"],
                    "hourly": "us_aqi,ozone,grass_pollen,birch_pollen,ragweed_pollen",
                    "forecast_days": 2,
                    "timezone": "auto",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                return {}

            hourly = resp.json().get("hourly", {})
            times = hourly.get("time", [])
            aqi_vals = hourly.get("us_aqi", [])
            ozone_vals = hourly.get("ozone", [])
            grass_vals = hourly.get("grass_pollen", [])
            tree_vals = hourly.get("birch_pollen", [])
            weed_vals = hourly.get("ragweed_pollen", [])

            now_hh = datetime.now().strftime("%Y-%m-%dT%H")
            today_str = datetime.now().strftime("%Y-%m-%d")
            from datetime import timedelta
            tomorrow_str = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")

            current_idx = next(
                (i for i, t in enumerate(times) if t.startswith(now_hh)), 0
            )

            def _safe(lst, idx):
                try:
                    v = lst[idx]
                    return float(v) if v is not None else 0.0
                except (IndexError, TypeError, ValueError):
                    return 0.0

            today_indices = [i for i, t in enumerate(times) if t.startswith(today_str)]
            tomorrow_indices = [i for i, t in enumerate(times) if t.startswith(tomorrow_str)]

            today_aqi_vals = [_safe(aqi_vals, i) for i in today_indices if _safe(aqi_vals, i) > 0]
            tomorrow_aqi_vals = [_safe(aqi_vals, i) for i in tomorrow_indices if _safe(aqi_vals, i) > 0]

            best_window = self._best_outdoor_window(
                [_safe(aqi_vals, i) for i in today_indices],
                [times[i] for i in today_indices],
            )

            return {
                "current_aqi": _safe(aqi_vals, current_idx),
                "current_ozone": _safe(ozone_vals, current_idx),
                "current_grass": _safe(grass_vals, current_idx),
                "current_tree": _safe(tree_vals, current_idx),
                "current_weed": _safe(weed_vals, current_idx),
                "today_peak_aqi": max(today_aqi_vals) if today_aqi_vals else 0.0,
                "best_window": best_window,
                "tomorrow_peak_aqi": max(tomorrow_aqi_vals) if tomorrow_aqi_vals else 0.0,
                "tomorrow_grass": max((_safe(grass_vals, i) for i in tomorrow_indices), default=0.0),
                "tomorrow_tree": max((_safe(tree_vals, i) for i in tomorrow_indices), default=0.0),
                "tomorrow_weed": max((_safe(weed_vals, i) for i in tomorrow_indices), default=0.0),
            }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[AQAlertBG] Fetch error: {e!r}")
            return {}

    def _best_outdoor_window(self, aqi_vals: list, times: list) -> str:
        daytime = [
            (aqi_vals[i], times[i])
            for i in range(len(times))
            if "T" in times[i] and 6 <= int(times[i].split("T")[1][:2]) <= 21
            and aqi_vals[i] > 0
        ]
        if not daytime:
            return "this evening"
        best = min(daytime, key=lambda x: x[0])
        hour = int(best[1].split("T")[1][:2])
        if hour < 12:
            return f"this morning around {hour}am"
        if hour == 12:
            return "around noon"
        return f"around {hour - 12}pm"

    def _build_morning_alert(self, aq: dict, data: dict) -> str:
        conditions = data.get("conditions", ["general"])
        pollen_triggers = data.get("pollen_triggers", ["grass", "tree", "weed"])
        return self.capability_worker.text_to_text_response(
            MORNING_ALERT_PROMPT.format(
                conditions=", ".join(conditions),
                pollen_triggers=", ".join(pollen_triggers),
                aqi=int(aq["current_aqi"]),
                aqi_label=_aqi_label(aq["current_aqi"]),
                ozone=int(aq["current_ozone"]),
                grass=int(aq["current_grass"]),
                grass_level=_pollen_label(aq["current_grass"]),
                tree=int(aq["current_tree"]),
                tree_level=_pollen_label(aq["current_tree"]),
                weed=int(aq["current_weed"]),
                weed_level=_pollen_label(aq["current_weed"]),
                best_window=aq["best_window"],
            )
        )

    def _build_evening_alert(self, aq: dict, data: dict) -> str:
        conditions = data.get("conditions", ["general"])
        return self.capability_worker.text_to_text_response(
            EVENING_PREP_PROMPT.format(
                aqi_tomorrow=int(aq["tomorrow_peak_aqi"]),
                label_tomorrow=_aqi_label(aq["tomorrow_peak_aqi"]),
                grass=int(aq["tomorrow_grass"]),
                tree=int(aq["tomorrow_tree"]),
                weed=int(aq["tomorrow_weed"]),
                conditions=", ".join(conditions),
            )
        )

    async def watch_loop(self):
        self.worker.editor_logging_handler.info("[AQAlertBG] Daemon started")
        started_at = datetime.now().timestamp()
        morning_alerted_date = ""
        evening_alerted_date = ""
        flow_released = False

        while True:
            try:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                current_hhmm = now.strftime("%H:%M")
                daemon_age = now.timestamp() - started_at

                # Release conversation control only after the startup grace window.
                # This lets the foreground's outer loop run uninterrupted first.
                if not flow_released and daemon_age > STARTUP_GRACE:
                    self.capability_worker.resume_normal_flow()
                    flow_released = True
                    self.worker.editor_logging_handler.info("[AQAlertBG] Flow released")

                if daemon_age <= STARTUP_GRACE:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                data = self._load_data()
                location = data.get("location")

                if not location or not location.get("lat"):
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                morning_time = data.get("morning_alert_time", DEFAULT_MORNING_TIME)
                evening_time = data.get("evening_check_time", DEFAULT_EVENING_TIME)
                threshold = data.get("alert_threshold_aqi", DEFAULT_AQI_THRESHOLD)

                if current_hhmm == morning_time and morning_alerted_date != today:
                    aq = self._fetch_air_quality(location)
                    if aq and aq["current_aqi"] >= threshold:
                        msg = self._build_morning_alert(aq, data)
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(msg)
                        morning_alerted_date = today
                        self.worker.editor_logging_handler.info(
                            f"[AQAlertBG] Morning alert fired — AQI {aq['current_aqi']:.0f}"
                        )
                    elif aq:
                        morning_alerted_date = today
                        self.worker.editor_logging_handler.info(
                            f"[AQAlertBG] Morning check — AQI {aq['current_aqi']:.0f} below threshold"
                        )

                if current_hhmm == evening_time and evening_alerted_date != today:
                    aq = self._fetch_air_quality(location)
                    if aq and aq["tomorrow_peak_aqi"] >= threshold:
                        msg = self._build_evening_alert(aq, data)
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(msg)
                        self.worker.editor_logging_handler.info(
                            f"[AQAlertBG] Evening prep alert fired — tomorrow AQI {aq['tomorrow_peak_aqi']:.0f}"
                        )
                    evening_alerted_date = today

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[AQAlertBG] Loop error: {e!r}")

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    def call(self, worker: AgentWorker, background_daemon_mode: bool = True):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.background_daemon_mode = background_daemon_mode
        self.worker.session_tasks.create(self.watch_loop())
