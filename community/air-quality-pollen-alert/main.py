import requests
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "air_quality_data"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"

HOTWORDS = {
    "air quality", "aqi", "pollution", "pollen", "allergy", "allergies",
    "asthma", "air outside", "outdoor air", "safe to go outside",
    "safe to run", "should i open", "keep windows", "air today",
    "pollen count", "pollen today", "air quality alert", "smog",
    "particulate", "ozone", "air index", "breathe outside",
    "forecast", "air forecast", "tomorrow air", "tomorrow's forecast",
    "go for a run", "run outside", "exercise outside", "go outside",
    "windows open", "windows closed", "open my windows",
    "set up air", "air alert", "air quality setup",
}

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "that's all"}

CITY_EXTRACT_PROMPT = (
    "Extract the city name from this text if one is explicitly mentioned. "
    "Return ONLY the city name. If no city is mentioned, return NONE. "
    "Text: {text}"
)


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

CHECK_PROMPT = (
    "Answer an on-demand air quality question for a voice assistant. "
    "User conditions: {conditions}. Pollen triggers: {pollen_triggers}. "
    "Current AQI: {aqi} ({aqi_label}). Ozone: {ozone} μg/m³. "
    "Grass pollen: {grass} grains/m³ ({grass_level}). "
    "Tree pollen: {tree} grains/m³ ({tree_level}). "
    "Weed pollen: {weed} grains/m³ ({weed_level}). "
    "Best outdoor window today: {best_window}. "
    "Write 2-3 sentences. Lead with the metric most relevant to their conditions: "
    "pollen first if they have hay fever and any pollen is moderate or higher; "
    "AQI first if they have asthma or COPD or AQI is above 100; "
    "otherwise give a balanced summary. "
    "No greetings (no 'Good morning', 'Hey', etc.). Plain English. Spoken tone."
)

EVENING_PREP_PROMPT = (
    "Write a 2-sentence evening heads-up for a voice assistant. "
    "Tomorrow morning AQI forecast: {aqi_tomorrow} ({label_tomorrow}). "
    "Tomorrow peak pollen — grass: {grass}, tree: {tree}, weed: {weed} grains/m³. "
    "User conditions: {conditions}. "
    "Sentence 1: what tomorrow looks like. "
    "Sentence 2: one prep action for tonight. "
    "No markdown. Plain English. Spoken tone."
)

ACTIVITY_PROMPT = (
    "Answer in 2 sentences whether it is safe to exercise outdoors right now. "
    "Current AQI: {aqi} ({aqi_label}). User conditions: {conditions}. "
    "Best outdoor window today: {best_window}. "
    "Sentence 1: direct yes or no with brief reason. "
    "Sentence 2: specific timing advice or indoor alternative. "
    "No markdown. Plain English."
)

WINDOWS_PROMPT = (
    "Answer in 2 sentences whether to keep windows open or closed right now. "
    "Current AQI: {aqi} ({aqi_label}). "
    "Pollen levels — grass: {grass_level}, tree: {tree_level}, weed: {weed_level}. "
    "User pollen triggers: {pollen_triggers}. "
    "No markdown. Plain English."
)

FORECAST_PROMPT = (
    "Write a 2-sentence spoken forecast for a voice assistant. "
    "Today's current AQI: {aqi_today} ({label_today}), peak AQI: {peak_today}. "
    "Tomorrow's peak AQI: {peak_tomorrow} ({label_tomorrow}). "
    "Grass pollen today: {grass_today} ({grass_level}). "
    "User conditions: {conditions}. "
    "Sentence 1: today's outlook. Sentence 2: tomorrow's outlook and whether it improves or worsens. "
    "No markdown. Plain English."
)

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
        "morning_alert_time": "07:00",
        "evening_check_time": "20:00",
        "conditions": [],
        "pollen_triggers": [],
        "alert_threshold_aqi": 100,
        "last_morning_alert_date": "",
        "last_evening_alert_date": "",
    }


class AirQualityPollenAlertCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        t = text.lower().strip()
        return any(hw in t for hw in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

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
            self.worker.editor_logging_handler.error(f"[AQAlert] Load error: {e!r}")
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
            self.worker.editor_logging_handler.error(f"[AQAlert] Save error: {e!r}")
            return
        self.worker.editor_logging_handler.error("[AQAlert] Save failed")

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _region_city(self) -> str:
        """Try the platform's own region data before falling back to asking
        the user. get_region_data's exact field shape isn't documented or
        verified live here, so this checks a few plausible key names and
        degrades to empty (triggering the ask-the-user fallback) on anything
        unexpected rather than guessing wrong."""
        try:
            region = self.capability_worker.get_region_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[AQAlert] get_region_data failed: {e!r}")
            return ""
        if not isinstance(region, dict):
            return ""
        for key in ("city", "city_name", "name", "location", "region"):
            value = region.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _geocode(self, city: str) -> dict:
        try:
            resp = requests.get(
                GEO_URL,
                params={"name": city, "count": 1, "language": "en", "format": "json"},
                timeout=8,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    r = results[0]
                    return {"city": r.get("name", city), "lat": r["latitude"], "lon": r["longitude"]}
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[AQAlert] Geocode error: {e!r}")
        return {}

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

            current_idx = next(
                (i for i, t in enumerate(times) if t.startswith(now_hh)), 0
            )

            def _safe(lst, idx):
                try:
                    v = lst[idx]
                    return float(v) if v is not None else 0.0
                except (IndexError, TypeError, ValueError):
                    return 0.0

            from datetime import timedelta
            today_str = datetime.now().strftime("%Y-%m-%d")
            tomorrow_str = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")

            today_indices = [i for i, t in enumerate(times) if t.startswith(today_str)]
            tomorrow_indices = [i for i, t in enumerate(times) if t.startswith(tomorrow_str)]

            today_aqi_vals = [_safe(aqi_vals, i) for i in today_indices if _safe(aqi_vals, i) > 0]
            tomorrow_aqi_vals = [_safe(aqi_vals, i) for i in tomorrow_indices if _safe(aqi_vals, i) > 0]

            best_window = self._best_outdoor_window(
                [_safe(aqi_vals, i) for i in today_indices],
                [times[i] for i in today_indices],
            )

            tomorrow_grass = max((_safe(grass_vals, i) for i in tomorrow_indices), default=0.0)
            tomorrow_tree = max((_safe(tree_vals, i) for i in tomorrow_indices), default=0.0)
            tomorrow_weed = max((_safe(weed_vals, i) for i in tomorrow_indices), default=0.0)

            return {
                "current_aqi": _safe(aqi_vals, current_idx),
                "current_ozone": _safe(ozone_vals, current_idx),
                "current_grass": _safe(grass_vals, current_idx),
                "current_tree": _safe(tree_vals, current_idx),
                "current_weed": _safe(weed_vals, current_idx),
                "today_peak_aqi": max(today_aqi_vals) if today_aqi_vals else 0.0,
                "best_window": best_window,
                "tomorrow_peak_aqi": max(tomorrow_aqi_vals) if tomorrow_aqi_vals else 0.0,
                "tomorrow_grass": tomorrow_grass,
                "tomorrow_tree": tomorrow_tree,
                "tomorrow_weed": tomorrow_weed,
            }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[AQAlert] Fetch error: {e!r}")
            return {}

    def _best_outdoor_window(self, aqi_vals: list, times: list) -> str:
        daytime = [
            (aqi_vals[i], times[i])
            for i in range(len(times))
            if "T" in times[i] and 6 <= int(times[i].split("T")[1][:2]) <= 21
            and aqi_vals[i] is not None and aqi_vals[i] > 0
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

    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in EXIT_WORDS):
            return "EXIT"
        if any(w in t for w in ("set up", "setup", "my city is", "i'm in", "i am in")):
            return "SETUP"
        if any(w in t for w in ("update", "change my", "change the", "settings", "alert time")):
            return "UPDATE"
        if any(w in t for w in ("window", "open my window", "keep window")):
            return "WINDOWS"
        if any(w in t for w in ("run", "exercise", "jog", "workout", "safe to go", "go outside", "go for a")):
            return "ACTIVITY"
        if any(w in t for w in ("forecast", "tomorrow", "later today", "rest of the day", "outlook")):
            return "FORECAST"
        return "CHECK"

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_setup(self, data: dict, trigger_text: str = ""):
        city_reply = ""

        if trigger_text:
            extracted = self.capability_worker.text_to_text_response(
                CITY_EXTRACT_PROMPT.format(text=trigger_text)
            ).strip()
            if extracted.upper() != "NONE" and 1 <= len(extracted.split()) <= 4:
                city_reply = extracted

        if not city_reply:
            # Try the platform's own region data before asking the user.
            city_reply = self._region_city()

        if not city_reply:
            await self.capability_worker.speak(
                "To set up, say 'set up air quality for' followed by your city — "
                "for example, 'set up air quality for Ottawa'."
            )
            return

        location = self._geocode(city_reply)
        if not location:
            await self.capability_worker.speak(
                f"I couldn't find {city_reply}. Try the nearest large city."
            )
            return

        data["location"] = location
        data.setdefault("morning_alert_time", "07:00")
        data.setdefault("conditions", ["general"])
        data.setdefault("pollen_triggers", ["grass", "tree", "weed"])
        self._save_data(data)

        await self.capability_worker.speak(
            f"Done. I'll brief you on air quality for {location['city']} every morning at 7am. "
            f"Say 'update air quality settings' to set a custom time or your health conditions."
        )

    async def _handle_update(self, data: dict):
        location = data.get("location", {})
        if not location:
            await self.capability_worker.speak(
                "I don't have your location set up yet. "
                "Say 'set up air quality for' followed by your city first."
            )
            return

        city_name = location.get("city", "your city")
        await self.capability_worker.speak(
            f"Currently set to {city_name}. "
            "What time should I send your morning brief? For example, say 7am or 8:30."
        )
        time_reply = await self.capability_worker.user_response()
        if time_reply is None:
            return
        morning_time = self._parse_time(time_reply)
        if not morning_time:
            await self.capability_worker.speak(
                "I didn't catch a time — try saying something like 7am or 8:30."
            )
            time_reply2 = await self.capability_worker.user_response()
            if time_reply2 is None:
                return
            morning_time = self._parse_time(time_reply2) or "07:00"

        await self.capability_worker.speak(
            "Do you have asthma, hay fever, or both? Or say general."
        )
        condition_reply_raw = await self.capability_worker.user_response()
        if condition_reply_raw is None:
            return
        condition_reply = condition_reply_raw.lower()
        conditions = []
        if "asthma" in condition_reply:
            conditions.append("asthma")
        if "hay fever" in condition_reply or "hayfever" in condition_reply or "allerg" in condition_reply:
            conditions.append("hay_fever")
        if "copd" in condition_reply:
            conditions.append("copd")
        if not conditions:
            conditions = ["general"]

        pollen_triggers = ["grass", "tree", "weed"]
        if "hay_fever" in conditions or "asthma" in conditions:
            await self.capability_worker.speak(
                "Which pollens bother you most — grass, tree, weed, or all?"
            )
            pollen_reply_raw = await self.capability_worker.user_response()
            if pollen_reply_raw is None:
                return
            pollen_reply = pollen_reply_raw.lower()
            pollen_triggers = []
            if "grass" in pollen_reply:
                pollen_triggers.append("grass")
            if "tree" in pollen_reply:
                pollen_triggers.append("tree")
            if "weed" in pollen_reply:
                pollen_triggers.append("weed")
            if "all" in pollen_reply or not pollen_triggers:
                pollen_triggers = ["grass", "tree", "weed"]

        data["morning_alert_time"] = morning_time
        data["conditions"] = conditions
        data["pollen_triggers"] = pollen_triggers
        self._save_data(data)

        condition_str = " and ".join(c.replace("_", " ") for c in conditions)
        pollen_str = ", ".join(pollen_triggers)
        await self.capability_worker.speak(
            f"Updated. Morning brief at {self._fmt_time(morning_time)}, "
            f"watching {pollen_str} pollen for your {condition_str}."
        )

    async def _handle_check(self, data: dict):
        location = data.get("location")
        if not location:
            await self.capability_worker.speak(
                "I don't have your location set up yet. Say 'set up air quality' to get started."
            )
            return

        aq = self._fetch_air_quality(location)
        if not aq:
            await self.capability_worker.speak(
                "I couldn't fetch air quality data right now. Please try again in a moment."
            )
            return

        aqi = aq["current_aqi"]
        conditions = data.get("conditions", ["general"])
        pollen_triggers = data.get("pollen_triggers", ["grass", "tree", "weed"])

        summary = self.capability_worker.text_to_text_response(
            CHECK_PROMPT.format(
                conditions=", ".join(conditions),
                pollen_triggers=", ".join(pollen_triggers),
                aqi=int(aqi),
                aqi_label=_aqi_label(aqi),
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
        await self.capability_worker.speak(summary)

    async def _handle_forecast(self, data: dict):
        location = data.get("location")
        if not location:
            await self.capability_worker.speak(
                "I need your location first. Say 'set up air quality' to get started."
            )
            return

        aq = self._fetch_air_quality(location)
        if not aq:
            await self.capability_worker.speak("Couldn't fetch forecast data right now.")
            return

        conditions = data.get("conditions", ["general"])
        summary = self.capability_worker.text_to_text_response(
            FORECAST_PROMPT.format(
                aqi_today=int(aq["current_aqi"]),
                label_today=_aqi_label(aq["current_aqi"]),
                peak_today=int(aq["today_peak_aqi"]),
                peak_tomorrow=int(aq["tomorrow_peak_aqi"]),
                label_tomorrow=_aqi_label(aq["tomorrow_peak_aqi"]),
                grass_today=int(aq["current_grass"]),
                grass_level=_pollen_label(aq["current_grass"]),
                conditions=", ".join(conditions),
            )
        )
        await self.capability_worker.speak(summary)

    async def _handle_activity(self, data: dict):
        location = data.get("location")
        if not location:
            await self.capability_worker.speak(
                "I need your location first. Say 'set up air quality' to get started."
            )
            return

        aq = self._fetch_air_quality(location)
        if not aq:
            await self.capability_worker.speak("Couldn't fetch conditions right now.")
            return

        conditions = data.get("conditions", ["general"])
        advice = self.capability_worker.text_to_text_response(
            ACTIVITY_PROMPT.format(
                aqi=int(aq["current_aqi"]),
                aqi_label=_aqi_label(aq["current_aqi"]),
                conditions=", ".join(conditions),
                best_window=aq["best_window"],
            )
        )
        await self.capability_worker.speak(advice)

    async def _handle_windows(self, data: dict):
        location = data.get("location")
        if not location:
            await self.capability_worker.speak(
                "I need your location first. Say 'set up air quality' to get started."
            )
            return

        aq = self._fetch_air_quality(location)
        if not aq:
            await self.capability_worker.speak("Couldn't fetch conditions right now.")
            return

        pollen_triggers = data.get("pollen_triggers", ["grass", "tree", "weed"])
        advice = self.capability_worker.text_to_text_response(
            WINDOWS_PROMPT.format(
                aqi=int(aq["current_aqi"]),
                aqi_label=_aqi_label(aq["current_aqi"]),
                grass_level=_pollen_label(aq["current_grass"]),
                tree_level=_pollen_label(aq["current_tree"]),
                weed_level=_pollen_label(aq["current_weed"]),
                pollen_triggers=", ".join(pollen_triggers),
            )
        )
        await self.capability_worker.speak(advice)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _parse_time(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        raw = self.capability_worker.text_to_text_response(
            "Extract a 24-hour time from this text. Return ONLY HH:MM format. "
            "Examples: '7am'→'07:00', '8:30'→'08:30', '9pm'→'21:00', 'half past six'→'06:30'. "
            f"If no time is mentioned, return NONE. Text: {text}"
        ).strip()
        if not raw or raw.upper() == "NONE":
            return ""
        parts = raw.split(":")
        if len(parts) == 2:
            try:
                hh, mm = int(parts[0]), int(parts[1])
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    return f"{hh:02d}:{mm:02d}"
            except ValueError:
                pass
        return ""

    def _fmt_time(self, hhmm: str) -> str:
        try:
            dt = datetime.strptime(hhmm, "%H:%M")
            return dt.strftime("%-I:%M %p").replace(":00 ", " ").lower()
        except ValueError:
            return hhmm

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[AQAlert] Trigger: {trigger!r}")

            data = self._load_data()
            intent = self._classify_intent(trigger or "")
            self.worker.editor_logging_handler.info(f"[AQAlert] Intent: {intent}")

            if intent == "EXIT" or (trigger and any(w in trigger.lower() for w in EXIT_WORDS)):
                await self.capability_worker.speak("Sure thing.")
                return

            await self._dispatch(intent, data, trigger_text=trigger or "")

            while True:
                reply = await self.capability_worker.user_response()
                if reply is None:
                    break
                reply_clean = reply.strip()
                if not reply_clean:
                    break
                if trigger and reply_clean.lower() == trigger.strip().lower():
                    continue
                if any(w in reply_clean.lower() for w in EXIT_WORDS):
                    break
                data = self._load_data()
                intent = self._classify_intent(reply_clean)
                self.worker.editor_logging_handler.info(f"[AQAlert] Intent: {intent}")
                if intent == "EXIT":
                    break
                await self._dispatch(intent, data, trigger_text="")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[AQAlert] Error: {e!r}")
            await self.capability_worker.speak("Something went wrong. Please try again.")
        finally:
            self.capability_worker.resume_normal_flow()

    async def _dispatch(self, intent: str, data: dict, trigger_text: str = ""):
        if intent == "SETUP":
            await self._handle_setup(data, trigger_text)
        elif intent == "UPDATE":
            await self._handle_update(data)
        elif intent == "CHECK":
            await self._handle_check(data)
        elif intent == "FORECAST":
            await self._handle_forecast(data)
        elif intent == "ACTIVITY":
            await self._handle_activity(data)
        elif intent == "WINDOWS":
            await self._handle_windows(data)
