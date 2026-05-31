import re
import requests
from datetime import datetime, timezone

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "lightning_alert_data"
GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
IPAPI_URL = "http://ip-api.com/json"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

HOTWORDS = {
    "lightning alert", "lightning nearby", "any lightning", "lightning warning",
    "lightning monitor", "check lightning", "lightning check",
    "storm coming", "storm nearby", "is there a storm", "storm warning",
    "storm check", "check storm", "any storms",
    "is it safe outside", "safe to go out", "safe outside",
    "shelter now", "should i shelter", "need to shelter",
    "how long until the storm", "when does the storm", "when will the storm",
    "storm timing", "storm alert",
}

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "that's all"}

CLOUD_ISPS = {"amazon", "aws", "google", "microsoft", "azure", "digitalocean", "linode", "vultr"}

THUNDERSTORM_CODES = {95, 96, 99}
APPROACHING_CODES = {80, 81, 82, 85, 86, 95, 96, 99}

INTENT_PROMPT = """Classify the user's input into exactly one of these intents:
STORM_NOW - asking about current storm/lightning conditions right now
TIMING - asking how long until a storm arrives or when to seek shelter
CLEAR_CHECK - asking if a storm has passed or if it is safe now
SET_LOCATION - wanting to change or update their location
SET_PREFS - wanting to change how early they are warned (e.g. "warn me earlier", "give me more notice", "2 hours warning")
EXIT - stopping, done, goodbye

Return ONLY the intent label. Input: {text}"""

STORM_SUMMARY_PROMPT = """You are a concise voice assistant giving a lightning/storm status update.
Data: {data}
Location: {location}
Write ONE sentence (max 20 words) describing current conditions.
No markdown. Plain spoken English. Lead with the key fact."""

TIMING_PROMPT = """You are a concise voice assistant.
Storm timing data: {data}
Location: {location}
Write ONE sentence telling the user how long they have before the storm or when it's expected.
No markdown. Plain spoken English."""

CLEAR_PROMPT = """You are a concise voice assistant.
Weather data: {data}
Location: {location}
Write ONE sentence telling the user whether it is now safe to go outside.
No markdown. Plain spoken English."""

PREFS_PROMPT = """Extract the warning time in minutes from this user request.
Examples: "warn me 2 hours ahead" -> 120, "give me 30 minutes notice" -> 30, "warn me earlier" -> 60, "more warning" -> 120
Return ONLY an integer (number of minutes). Input: {text}"""


_PROCESS_CACHE: dict = {}


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


class LightningAlertCapability(MatchingCapability):
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
        global _PROCESS_CACHE
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                _PROCESS_CACHE = result["value"]
                return result["value"]
            if _PROCESS_CACHE.get("location", {}).get("lat"):
                return _PROCESS_CACHE
            return _empty_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Lightning] Load error: {e!r}")
            return _PROCESS_CACHE if _PROCESS_CACHE.get("location", {}).get("lat") else _empty_data()

    def _save_data(self, data: dict):
        global _PROCESS_CACHE
        _PROCESS_CACHE = data
        try:
            self.capability_worker.create_key(STORAGE_KEY, data)
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, data)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[Lightning] Save error: {e!r}")

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
                        self.worker.editor_logging_handler.warning("[Lightning] Cloud IP — skipping geolocation")
                        return None
                    return {
                        "lat": d.get("lat"),
                        "lon": d.get("lon"),
                        "name": d.get("city", "your location"),
                        "tz": d.get("timezone", "UTC"),
                        "auto": True,
                    }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Lightning] IP geo error: {e!r}")
        return None

    def _geocode_city(self, city: str) -> dict | None:
        try:
            resp = requests.get(
                GEOCODE_URL,
                params={"q": city, "format": "json", "limit": 1},
                headers={"User-Agent": "OpenHome-LightningAlert"},
                timeout=8,
            )
            data = resp.json()
            if data:
                return {
                    "lat": float(data[0]["lat"]),
                    "lon": float(data[0]["lon"]),
                    "name": city.title(),
                    "tz": "UTC",
                    "auto": False,
                }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Lightning] Geocode error: {e!r}")
        return None

    def _extract_city(self, text: str) -> str:
        raw = self.capability_worker.text_to_text_response(
            f"Extract ONLY the city name from this text: '{text}'. "
            "Reply with the city name only — no punctuation, no explanation. "
            "If no city is mentioned, reply NONE."
        )
        result = raw.strip()
        return "" if result.upper() == "NONE" or not result else result

    # ------------------------------------------------------------------
    # Weather APIs
    # ------------------------------------------------------------------

    def _fetch_storm_data(self, lat: float, lon: float) -> dict:
        result = {"codes": [], "minutes_to_storm": None, "nws_alerts": []}
        try:
            resp = requests.get(
                OPEN_METEO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "minutely_15": "weathercode,precipitation_probability",
                    "forecast_days": 1,
                    "timezone": "auto",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                m15 = resp.json().get("minutely_15", {})
                codes = m15.get("weathercode", [])
                result["codes"] = codes[:12]  # next 3 hours (12 × 15-min slots)

                now_ts = datetime.now(timezone.utc).timestamp()
                times = m15.get("time", [])
                for i, (t, c) in enumerate(zip(times[:12], codes[:12])):
                    if c in THUNDERSTORM_CODES:
                        try:
                            slot_ts = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
                            minutes = max(0, int((slot_ts - now_ts) / 60))
                            result["minutes_to_storm"] = minutes
                        except Exception:
                            result["minutes_to_storm"] = i * 15
                        break
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Lightning] Open-Meteo error: {e!r}")

        try:
            nws_resp = requests.get(
                NWS_ALERTS_URL,
                params={"point": f"{lat},{lon}", "status": "actual"},
                headers={"User-Agent": "OpenHome-LightningAlert"},
                timeout=8,
            )
            if nws_resp.status_code == 200:
                features = nws_resp.json().get("features", [])
                for f in features:
                    props = f.get("properties", {})
                    event = props.get("event", "")
                    if any(k in event.lower() for k in ("thunder", "lightning", "severe")):
                        result["nws_alerts"].append({
                            "event": event,
                            "headline": props.get("headline", ""),
                            "expires": props.get("expires", ""),
                        })
        except Exception:
            pass  # NWS is US-only; non-US silently skips

        return result

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    def _classify_intent(self, text: str) -> str:
        raw = self.capability_worker.text_to_text_response(
            INTENT_PROMPT.format(text=text)
        )
        result = raw.strip().upper().split()[0]
        valid = {"STORM_NOW", "TIMING", "CLEAR_CHECK", "SET_LOCATION", "SET_PREFS", "EXIT"}
        return result if result in valid else "STORM_NOW"

    # ------------------------------------------------------------------
    # Response builders
    # ------------------------------------------------------------------

    def _speak_storm_now(self, storm_data: dict, name: str) -> str:
        current_code = storm_data["codes"][0] if storm_data["codes"] else 0
        nws = storm_data["nws_alerts"]

        if nws:
            headline = nws[0].get("headline") or nws[0].get("event", "severe weather alert")
            return f"{headline}."

        data_summary = {
            "current_code": current_code,
            "thunderstorm_active": current_code in THUNDERSTORM_CODES,
            "minutes_to_storm": storm_data["minutes_to_storm"],
            "nws_alerts": nws,
        }
        return self.capability_worker.text_to_text_response(
            STORM_SUMMARY_PROMPT.format(data=data_summary, location=name)
        )

    def _speak_timing(self, storm_data: dict, name: str) -> str:
        minutes = storm_data["minutes_to_storm"]
        if minutes is None:
            return f"No thunderstorms forecast near {name} in the next 3 hours."
        if minutes == 0:
            return f"A thunderstorm is active near {name} right now. Stay indoors."
        hours, mins = divmod(minutes, 60)
        if hours and mins:
            timing = f"{hours} hour{'s' if hours > 1 else ''} and {mins} minutes"
        elif hours:
            timing = f"about {hours} hour{'s' if hours > 1 else ''}"
        else:
            timing = f"about {minutes} minutes"
        return f"Storm reaches {name} in {timing}. Head inside before then."

    def _speak_clear_check(self, storm_data: dict, name: str) -> str:
        current_code = storm_data["codes"][0] if storm_data["codes"] else 0
        nws = storm_data["nws_alerts"]

        if current_code in THUNDERSTORM_CODES or nws:
            return f"Storm still active near {name}. Stay indoors a bit longer."

        data_summary = {
            "current_code": current_code,
            "thunderstorm_active": False,
            "upcoming_storm_minutes": storm_data["minutes_to_storm"],
        }
        return self.capability_worker.text_to_text_response(
            CLEAR_PROMPT.format(data=data_summary, location=name)
        )

    # ------------------------------------------------------------------
    # Main flow
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[Lightning] Trigger: {trigger!r}")

            data = self._load_data()

            if not data.get("location", {}).get("lat"):
                loc = self._geolocate_ip()
                if loc:
                    data["location"] = loc
                    self._save_data(data)
                    self.worker.editor_logging_handler.info(
                        f"[Lightning] Auto-detected: {loc['name']}"
                    )

            intent = self._classify_intent(trigger or "")

            while True:
                loc = data.get("location", {})
                lat = loc.get("lat")
                lon = loc.get("lon")
                name = loc.get("name", "your location")

                if intent == "EXIT":
                    break

                if intent == "SET_LOCATION":
                    city = self._extract_city(trigger or "")
                    if not city:
                        reply = await self.capability_worker.run_io_loop(
                            "Which city should I use for lightning alerts?"
                        )
                        if any(w in (reply or "").lower() for w in EXIT_WORDS):
                            break
                        city = self._extract_city(reply)

                    if city:
                        new_loc = self._geocode_city(city)
                        if new_loc:
                            data["location"] = new_loc
                            self._save_data(data)
                            lat, lon, name = new_loc["lat"], new_loc["lon"], new_loc["name"]
                            await self.capability_worker.speak(
                                f"Got it. Lightning alerts are now set for {name}."
                            )
                        else:
                            await self.capability_worker.speak(
                                "I couldn't find that city. Try a different name."
                            )
                    else:
                        await self.capability_worker.speak("I didn't catch a city name.")

                elif intent == "SET_PREFS":
                    raw = self.capability_worker.text_to_text_response(
                        PREFS_PROMPT.format(text=trigger or "")
                    )
                    try:
                        minutes = max(15, min(240, int(raw.strip())))
                    except (ValueError, TypeError):
                        minutes = 90
                    data["prefs"]["warn_minutes"] = minutes
                    self._save_data(data)
                    hours_str = f"{minutes // 60} hour{'s' if minutes // 60 != 1 else ''}" if minutes >= 60 else f"{minutes} minutes"
                    await self.capability_worker.speak(
                        f"Done. I'll warn you when a storm is {hours_str} away."
                    )

                else:
                    if lat is None:
                        reply = await self.capability_worker.run_io_loop(
                            "I need your city to check lightning conditions. What city are you in?"
                        )
                        if any(w in (reply or "").lower() for w in EXIT_WORDS):
                            break
                        city = self._extract_city(reply or "")
                        if city:
                            new_loc = self._geocode_city(city)
                            if new_loc:
                                data["location"] = new_loc
                                self._save_data(data)
                                lat, lon, name = new_loc["lat"], new_loc["lon"], new_loc["name"]
                            else:
                                await self.capability_worker.speak("Couldn't find that city. Try again later.")
                                break
                        else:
                            await self.capability_worker.speak("I didn't catch a city name. Try again later.")
                            break

                    await self.capability_worker.speak(f"Checking conditions near {name}.")
                    storm_data = self._fetch_storm_data(lat, lon)

                    if intent == "STORM_NOW":
                        msg = self._speak_storm_now(storm_data, name)
                    elif intent == "TIMING":
                        msg = self._speak_timing(storm_data, name)
                    elif intent == "CLEAR_CHECK":
                        msg = self._speak_clear_check(storm_data, name)
                    else:
                        msg = self._speak_storm_now(storm_data, name)

                    await self.capability_worker.speak(msg)

                reply = await self.capability_worker.user_response()
                if not reply or any(w in reply.lower() for w in EXIT_WORDS):
                    break
                trigger = reply
                intent = self._classify_intent(reply)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Lightning] Error: {e!r}")
            await self.capability_worker.speak("Something went wrong. Try again in a moment.")
        finally:
            self.capability_worker.resume_normal_flow()
