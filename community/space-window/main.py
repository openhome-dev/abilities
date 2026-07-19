import re
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

HOTWORDS = {
    "space window", "sky tonight", "night sky", "what's up tonight",
    "iss tonight", "iss passing", "iss pass", "when's the iss", "spot the station",
    "aurora tonight", "northern lights", "aurora forecast", "southern lights",
    "any launches", "rocket launch", "rocket launches", "launch tonight",
    "space events", "what's in the sky", "sky events",
    "set my location", "change my location", "i'm in", "i am in",
}

CITY_MAP = {
    "london": (51.5074, -0.1278),
    "new york": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "houston": (29.7604, -95.3698),
    "toronto": (43.6532, -79.3832),
    "vancouver": (49.2827, -123.1207),
    "paris": (48.8566, 2.3522),
    "berlin": (52.5200, 13.4050),
    "madrid": (40.4168, -3.7038),
    "rome": (41.9028, 12.4964),
    "amsterdam": (52.3676, 4.9041),
    "brussels": (50.8503, 4.3517),
    "vienna": (48.2082, 16.3738),
    "zurich": (47.3769, 8.5417),
    "stockholm": (59.3293, 18.0686),
    "oslo": (59.9139, 10.7522),
    "helsinki": (60.1699, 24.9384),
    "copenhagen": (55.6761, 12.5683),
    "dubai": (25.2048, 55.2708),
    "singapore": (1.3521, 103.8198),
    "tokyo": (35.6762, 139.6503),
    "seoul": (37.5665, 126.9780),
    "beijing": (39.9042, 116.4074),
    "shanghai": (31.2304, 121.4737),
    "hong kong": (22.3193, 114.1694),
    "sydney": (-33.8688, 151.2093),
    "melbourne": (-37.8136, 144.9631),
    "auckland": (-36.8485, 174.7633),
    "mumbai": (19.0760, 72.8777),
    "delhi": (28.7041, 77.1025),
    "bangalore": (12.9716, 77.5946),
    "cairo": (30.0444, 31.2357),
    "johannesburg": (-26.2041, 28.0473),
    "lagos": (6.5244, 3.3792),
    "nairobi": (-1.2921, 36.8219),
    "moscow": (55.7558, 37.6173),
    "istanbul": (41.0082, 28.9784),
    "mexico city": (19.4326, -99.1332),
    "sao paulo": (-23.5505, -46.6333),
    "buenos aires": (-34.6037, -58.3816),
    "bogota": (4.7110, -74.0721),
    "lima": (-12.0464, -77.0428),
    "santiago": (-33.4489, -70.6693),
    "miami": (25.7617, -80.1918),
    "san francisco": (37.7749, -122.4194),
    "seattle": (47.6062, -122.3321),
    "denver": (39.7392, -104.9903),
    "boston": (42.3601, -71.0589),
    "washington": (38.9072, -77.0369),
    "atlanta": (33.7490, -84.3880),
    "dallas": (32.7767, -96.7970),
    "phoenix": (33.4484, -112.0740),
    "montreal": (45.5017, -73.5673),
    "calgary": (51.0447, -114.0719),
    "manchester": (53.4808, -2.2426),
    "edinburgh": (55.9533, -3.1883),
    "glasgow": (55.8642, -4.2518),
    "birmingham": (52.4862, -1.8904),
    "dublin": (53.3498, -6.2603),
    "lisbon": (38.7223, -9.1393),
    "barcelona": (41.3851, 2.1734),
    "milan": (45.4654, 9.1859),
    "munich": (48.1351, 11.5820),
    "prague": (50.0755, 14.4378),
    "warsaw": (52.2297, 21.0122),
    "budapest": (47.4979, 19.0402),
    "athens": (37.9838, 23.7275),
    "tel aviv": (32.0853, 34.7818),
    "riyadh": (24.7136, 46.6753),
    "karachi": (24.8607, 67.0011),
    "dhaka": (23.8103, 90.4125),
    "kuala lumpur": (3.1390, 101.6869),
    "jakarta": (-6.2088, 106.8456),
    "manila": (14.5995, 120.9842),
    "taipei": (25.0330, 121.5654),
    "osaka": (34.6937, 135.5023),
    "cape town": (-33.9249, 18.4241),
    "reykjavik": (64.1466, -21.9426),
    "anchorage": (61.2181, -149.9003),
    "honolulu": (21.3069, -157.8583),
    "las vegas": (36.1699, -115.1398),
    "minneapolis": (44.9778, -93.2650),
    "detroit": (42.3314, -83.0458),
    "philadelphia": (39.9526, -75.1652),
    "san diego": (32.7157, -117.1611),
    "portland": (45.5051, -122.6750),
    "new orleans": (29.9511, -90.0715),
    "nashville": (36.1627, -86.7816),
    "charlotte": (35.2271, -80.8431),
    "orlando": (28.5383, -81.3792),
    "salt lake city": (40.7608, -111.8910),
}

_VALID_INTENTS = frozenset({
    "TONIGHT", "ISS", "AURORA", "LAUNCHES", "SETUP", "ALERTS"
})

_EXIT_PATTERN = re.compile(
    r'\b(stop|exit|quit|done|cancel|bye|goodbye|never\s*mind|no\s*thanks|'
    r"that'?s\s*all|nothing|nah|skip)\b",
    re.IGNORECASE,
)

_AFFIRMATIVE_PATTERN = re.compile(
    r'\b(yes|yeah|sure|yep|absolutely|ok|okay|go ahead|enable|on)\b',
    re.IGNORECASE,
)


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


# Process-scoped cache — survives across CapabilityWorker re-instantiation within the same session.
# Used as fallback when the storage API doesn't return persisted data on a new call().
_PROCESS_CACHE: dict = {}


class SpaceWindowCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    n2yo_key: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Hotword matching
    # ------------------------------------------------------------------

    def does_match(self, text: str) -> bool:
        t = text.lower().strip()
        if any(hw in t for hw in HOTWORDS):
            return True
        # Capture bare city name responses (e.g., user answers "London")
        if t in CITY_MAP:
            return True
        # Capture location-specifying phrases (e.g., "I'm in London", "from New York")
        if re.search(r"\bi'?m in\b|\bi am in\b|\bfrom\b", t) and any(city in t for city in CITY_MAP):
            return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        if not text or not text.strip():
            return True
        stripped = text.strip().rstrip(".,!?").strip().lower()
        if stripped in ("no", "skip", "stop"):
            return True
        return bool(_EXIT_PATTERN.search(text))

    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        if any(kw in t for kw in ("set my location", "change my location", "i'm in", "i am in", "my city", "my location")):
            return "SETUP"
        try:
            raw = self.capability_worker.text_to_text_response(
                "Route this request for a sky-watching voice assistant.\n"
                "Pick exactly one intent:\n"
                "TONIGHT — full sky summary for tonight: ISS, aurora, launches\n"
                "ISS — ISS pass times and directions specifically\n"
                "AURORA — aurora / northern lights forecast\n"
                "LAUNCHES — upcoming rocket launches\n"
                "SETUP — user is setting or changing their location\n"
                "ALERTS — user wants to configure or change alert preferences\n\n"
                "Reply with ONLY the intent label.\n"
                f"User input: {text.strip() or '(sky tonight)'}"
            )
            intent = raw.strip().upper().split()[0].strip(".,")
            return intent if intent in _VALID_INTENTS else "TONIGHT"
        except Exception:
            return "TONIGHT"

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    def _resolve_location(self, text: str) -> tuple[float | None, float | None]:
        t = text.lower().strip()
        for city, coords in sorted(CITY_MAP.items(), key=lambda x: -len(x[0])):
            if city in t:
                return coords
        return self._resolve_location_llm(text)

    def _resolve_location_llm(self, text: str) -> tuple[float | None, float | None]:
        try:
            raw = self.capability_worker.text_to_text_response(
                "Extract the city or location from this text and return its latitude and longitude.\n"
                "Format: LAT,LON (decimal degrees, e.g. 51.5074,-0.1278)\n"
                "Return NONE if no recognizable location found.\n"
                f"Text: {text}"
            )
            raw = raw.strip()
            if raw.upper() == "NONE" or "," not in raw:
                return None, None
            parts = raw.split(",")
            return float(parts[0].strip()), float(parts[1].strip())
        except Exception:
            return None, None

    def _find_city_in_text(self, text: str) -> tuple[float | None, float | None, str | None]:
        """CITY_MAP-only lookup — no LLM, safe to call on every trigger."""
        t = text.lower().strip()
        for city, coords in sorted(CITY_MAP.items(), key=lambda x: -len(x[0])):
            if city in t:
                return coords[0], coords[1], city.title()
        return None, None, None

    def _get_city_name(self, text: str) -> str:
        t = text.lower()
        for city in sorted(CITY_MAP.keys(), key=lambda x: -len(x)):
            if city in t:
                return city.title()
        try:
            raw = self.capability_worker.text_to_text_response(
                f"Extract just the city name from: '{text}'. Return ONLY the city name, nothing else."
            )
            return raw.strip().title() or text.strip().title()
        except Exception:
            return text.strip().title()

    # ------------------------------------------------------------------
    # Time formatting
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

    def _format_launch_time(self, net: str, tz_name: str) -> str:
        try:
            dt = datetime.fromisoformat(net.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = dt - now
            hours = int(delta.total_seconds() / 3600)
            if hours < 1:
                mins = int(delta.total_seconds() / 60)
                when = f"in about {mins} minutes"
            elif hours < 24:
                when = f"in {hours} hours"
            else:
                days = hours // 24
                when = f"in {days} {'day' if days == 1 else 'days'}"
            local_time = self._format_local_time(int(dt.timestamp()), tz_name)
            return f"{local_time} ({when})"
        except Exception:
            return "time unknown"

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
            # Walk backwards — skip metadata/header rows, handle both list and dict formats
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

    def _fetch_launches(self, days: int = 7) -> list:
        try:
            window_end = (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            resp = requests.get(
                LAUNCHES_URL,
                params={"limit": 8, "status": 1, "net__lte": window_end},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("results", [])
            return []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SpaceWindow] Launches error: {e}")
            return []

    # ------------------------------------------------------------------
    # Context Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        global _PROCESS_CACHE
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                loaded = result["value"]
                _PROCESS_CACHE = loaded
                loc_status = "set" if loaded.get("location", {}).get("lat") else "unset"
                self.worker.editor_logging_handler.info(f"[SpaceWindow] Loaded from storage, location={loc_status}")
                return loaded
            # Storage miss — use process cache if it has a location
            if _PROCESS_CACHE.get("location", {}).get("lat"):
                self.worker.editor_logging_handler.info("[SpaceWindow] Storage miss — using process cache")
                return _PROCESS_CACHE
            self.worker.editor_logging_handler.info("[SpaceWindow] Storage miss — starting fresh")
            return _empty_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SpaceWindow] Load error: {e!r}")
            if _PROCESS_CACHE.get("location", {}).get("lat"):
                return _PROCESS_CACHE
            return _empty_data()

    def _save_data(self, data: dict):
        global _PROCESS_CACHE
        _PROCESS_CACHE = data  # always update process cache first
        try:
            self.capability_worker.create_key(STORAGE_KEY, data)
            self.worker.editor_logging_handler.info("[SpaceWindow] Saved via create_key")
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, data)
                self.worker.editor_logging_handler.info("[SpaceWindow] Saved via update_key")
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[SpaceWindow] Save error: {e!r}")

    # ------------------------------------------------------------------
    # Location gate — ask inline if not set, save, return True/False
    # ------------------------------------------------------------------

    async def _ensure_location(self, data: dict) -> bool:
        if data.get("location", {}).get("lat"):
            return True

        await self.capability_worker.speak(
            "Just say your city name — like 'London' or 'New York'."
        )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return False

        # Guard: if the reply is a hotword phrase (not a city), re-ask once
        reply_lower = (reply or "").lower().strip()
        if reply_lower not in CITY_MAP and any(hw in reply_lower for hw in HOTWORDS):
            await self.capability_worker.speak(
                "I need your city to get started — just say the city name, like 'London' or 'Chicago'."
            )
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return False

        lat, lon = self._resolve_location(reply)
        if lat is None:
            await self.capability_worker.speak(
                "Couldn't find that — try a major nearby city like London or New York."
            )
            return False

        city_name = self._get_city_name(reply)
        tz_name = self.capability_worker.get_timezone() or "UTC"
        min_kp = self._aurora_min_kp(lat)

        data["location"] = {"lat": lat, "lon": lon, "name": city_name, "tz": tz_name}
        data["alert_prefs"]["aurora_kp_threshold"] = min_kp
        self._save_data(data)

        await self.capability_worker.speak(
            f"Got it — watching from {city_name}. "
            f"Aurora visible at Kp {min_kp} or higher at your latitude."
        )
        return True

    # ------------------------------------------------------------------
    # ISS pass formatting
    # ------------------------------------------------------------------

    def _describe_passes(self, passes: list, min_el: int, tz_name: str) -> list[str]:
        good = [p for p in passes if p.get("maxEl", 0) >= min_el]
        lines = []
        for p in good[:3]:
            t = self._format_local_time(p["startUTC"], tz_name)
            max_el = p.get("maxEl", 0)
            duration_min = max(1, p.get("duration", 60) // 60)
            start_dir = p.get("startAzCompass", "")
            end_dir = p.get("endAzCompass", "")
            quality = "great" if max_el >= 60 else "good" if max_el >= 40 else "fair"
            direction = f"rises {start_dir}, sets {end_dir}" if start_dir and end_dir else ""
            line = f"{t} — {quality} pass, peaks {max_el:.0f} degrees"
            if direction:
                line += f", {direction}"
            line += f", {duration_min} {'minute' if duration_min == 1 else 'minutes'} visible"
            lines.append(line)
        return lines

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_setup(self, trigger_text: str):
        lat, lon = self._resolve_location(trigger_text)

        if lat is None:
            await self.capability_worker.speak(
                "Where should I watch from? Say a city name — like London, Tokyo, or New York."
            )
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            lat, lon = self._resolve_location(reply)
            trigger_text = reply

        if lat is None:
            await self.capability_worker.speak(
                "I couldn't find that location. Try a major nearby city."
            )
            return

        city_name = self._get_city_name(trigger_text)
        tz_name = self.capability_worker.get_timezone() or "UTC"
        min_kp = self._aurora_min_kp(lat)

        data = self._load_data()
        data["location"] = {"lat": lat, "lon": lon, "name": city_name, "tz": tz_name}
        data["alert_prefs"]["aurora_kp_threshold"] = min_kp
        self._save_data(data)

        await self.capability_worker.speak(
            f"Set to {city_name}. I'll alert you before ISS passes, when aurora picks up, "
            f"and before rocket launches. At your latitude, aurora becomes visible around "
            f"Kp {min_kp} or higher — I'll watch for that."
        )

    async def _handle_tonight(self, data: dict):
        if not await self._ensure_location(data):
            return

        loc = data["location"]
        lat = loc["lat"]
        lon = loc["lon"]
        name = loc.get("name", "your location")
        tz_name = loc.get("tz", "UTC")
        min_el = data["alert_prefs"].get("min_elevation", 30)

        await self.capability_worker.speak(f"Checking tonight's sky for {name}...")

        parts = []

        # ISS
        if self.n2yo_key:
            passes = self._fetch_iss_passes(lat, lon)
            good = [p for p in passes if p.get("maxEl", 0) >= min_el]
            if good:
                p = good[0]
                t = self._format_local_time(p["startUTC"], tz_name)
                max_el = p.get("maxEl", 0)
                duration_min = max(1, p.get("duration", 60) // 60)
                quality = "great" if max_el >= 60 else "good" if max_el >= 40 else "fair"
                iss_part = (
                    f"ISS passes at {t} — {quality} pass, {max_el:.0f} degrees max, "
                    f"{duration_min} {'minute' if duration_min == 1 else 'minutes'}"
                )
                if len(good) > 1:
                    iss_part += f", plus {len(good) - 1} more {'pass' if len(good) == 2 else 'passes'}"
                parts.append(iss_part)
            else:
                parts.append("No good ISS passes tonight")
        else:
            parts.append("Add your N2YO API key in Settings to enable ISS tracking")

        # Aurora
        kp = self._fetch_kp()
        min_kp = data["alert_prefs"].get("aurora_kp_threshold", self._aurora_min_kp(lat))
        if kp is not None:
            if kp >= min_kp:
                parts.append(
                    f"Aurora alert — Kp is {kp:.0f}, aurora may be visible at your latitude. "
                    "Look north, away from city lights"
                )
            else:
                parts.append(
                    f"Aurora quiet — Kp at {kp:.1f}, you'd need {min_kp} or above to see it"
                )
        else:
            parts.append("Aurora data unavailable right now")

        # Launches in next 24h
        launches = self._fetch_launches(days=1)
        if launches:
            launch = launches[0]
            lname = launch.get("name", "Unknown mission")
            net = launch.get("net", "")
            pad = launch.get("pad", {}).get("location", {}).get("name", "")
            launch_time = self._format_launch_time(net, tz_name)
            launch_part = f"{lname} launches at {launch_time}"
            if pad:
                launch_part += f", from {pad}"
            parts.append(launch_part)

        await self.capability_worker.speak(". ".join(parts) + ".")

    async def _handle_iss(self, data: dict):
        if not self.n2yo_key:
            await self.capability_worker.speak(
                "ISS tracking needs a free N2YO API key. "
                "Get one at n2yo.com and add it in Settings as n2yo_api_key."
            )
            return

        if not await self._ensure_location(data):
            return

        loc = data["location"]
        lat = loc["lat"]
        lon = loc["lon"]
        name = loc.get("name", "your location")
        tz_name = loc.get("tz", "UTC")
        min_el = data["alert_prefs"].get("min_elevation", 30)

        await self.capability_worker.speak(f"Checking ISS passes for {name}...")
        passes = self._fetch_iss_passes(lat, lon)
        lines = self._describe_passes(passes, min_el, tz_name)

        if not lines:
            await self.capability_worker.speak(
                f"No visible ISS passes over {name} in the next 2 days — "
                f"all passes are below {min_el} degrees. Try lowering the minimum elevation in alerts."
            )
            return

        count = len([p for p in passes if p.get("maxEl", 0) >= min_el])
        await self.capability_worker.speak(
            f"ISS passes {name} {count} {'time' if count == 1 else 'times'} in the next 2 days. "
            + ". ".join(lines) + "."
        )

    async def _handle_aurora(self, data: dict):
        if not await self._ensure_location(data):
            return

        kp = self._fetch_kp()
        if kp is None:
            await self.capability_worker.speak(
                "Couldn't reach the NOAA space weather service right now. Try again in a moment."
            )
            return

        loc = data["location"]
        lat = loc["lat"]
        min_kp = data["alert_prefs"].get("aurora_kp_threshold", self._aurora_min_kp(lat))
        name = loc.get("name", "your location")

        if kp >= min_kp:
            await self.capability_worker.speak(
                f"Aurora alert — Kp is {kp:.0f} right now, above your threshold of {min_kp}. "
                f"Aurora may be visible from {name}. Head somewhere dark and look north. "
                "Activity can change fast — check again if you don't see anything in 30 minutes."
            )
        else:
            gap = min_kp - kp
            await self.capability_worker.speak(
                f"Aurora is quiet — Kp is {kp:.1f} right now. "
                f"At your latitude you'd need {min_kp} or above, so you're {gap:.0f} points away. "
                "I'll alert you if it spikes."
            )

    async def _handle_launches(self, data: dict):
        tz_name = data.get("location", {}).get("tz", "UTC")

        await self.capability_worker.speak("Checking upcoming launches...")
        launches = self._fetch_launches(days=7)

        if not launches:
            await self.capability_worker.speak(
                "No confirmed launches in the next 7 days — check back soon."
            )
            return

        parts = []
        for launch in launches[:4]:
            lname = launch.get("name", "Unknown")
            net = launch.get("net", "")
            rocket = launch.get("rocket", {}).get("configuration", {}).get("full_name", "")
            pad = launch.get("pad", {}).get("location", {}).get("name", "")
            launch_time = self._format_launch_time(net, tz_name)
            line = lname
            if rocket and rocket not in lname:
                line += f" on {rocket}"
            line += f", launching {launch_time}"
            if pad:
                line += f" from {pad}"
            parts.append(line)

        await self.capability_worker.speak(". ".join(parts) + ".")

    async def _handle_alerts(self, data: dict):
        prefs = data["alert_prefs"]
        loc = data.get("location", {})
        name = loc.get("name", "your location") if loc else "not set"

        await self.capability_worker.speak(
            f"Current alerts for {name}: "
            f"ISS {'on' if prefs.get('iss_alerts') else 'off'}, "
            f"aurora {'on' if prefs.get('aurora_alerts') else 'off'} at Kp {prefs.get('aurora_kp_threshold', 5)}, "
            f"launches {'on' if prefs.get('launch_alerts') else 'off'}. "
            f"ISS minimum elevation is {prefs.get('min_elevation', 30)} degrees. "
            "What would you like to change?"
        )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        r = reply.lower()
        changed = False

        if "iss" in r:
            prefs["iss_alerts"] = bool(_AFFIRMATIVE_PATTERN.search(r)) or "on" in r or "enable" in r
            changed = True
            state = "on" if prefs["iss_alerts"] else "off"
            await self.capability_worker.speak(f"ISS alerts turned {state}.")

        elif "aurora" in r or "northern lights" in r:
            nums = re.findall(r'\d+', r)
            if nums:
                prefs["aurora_kp_threshold"] = int(nums[0])
                changed = True
                await self.capability_worker.speak(
                    f"Aurora threshold set to Kp {nums[0]}."
                )
            else:
                prefs["aurora_alerts"] = bool(_AFFIRMATIVE_PATTERN.search(r)) or "on" in r or "enable" in r
                changed = True
                state = "on" if prefs["aurora_alerts"] else "off"
                await self.capability_worker.speak(f"Aurora alerts turned {state}.")

        elif "launch" in r:
            prefs["launch_alerts"] = bool(_AFFIRMATIVE_PATTERN.search(r)) or "on" in r or "enable" in r
            changed = True
            state = "on" if prefs["launch_alerts"] else "off"
            await self.capability_worker.speak(f"Launch alerts turned {state}.")

        elif "elevation" in r or "degree" in r:
            nums = re.findall(r'\d+', r)
            if nums:
                prefs["min_elevation"] = int(nums[0])
                changed = True
                await self.capability_worker.speak(
                    f"Minimum ISS elevation set to {nums[0]} degrees. "
                    "Higher means fewer but better passes."
                )

        else:
            await self.capability_worker.speak(
                "Say 'ISS on/off', 'aurora threshold Kp 4', 'launches on/off', "
                "or 'minimum elevation 20 degrees'."
            )

        if changed:
            data["alert_prefs"] = prefs
            self._save_data(data)

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            self.n2yo_key = self.capability_worker.get_api_keys("n2yo_api_key") or ""

            trigger_text = await self.capability_worker.wait_for_complete_transcription()
            if not trigger_text or not isinstance(trigger_text, str):
                trigger_text = ""

            data = self._load_data()

            # Pre-populate location if a city is embedded in the trigger phrase
            # e.g., "space window from London" or "ISS passes tonight London"
            if not data.get("location", {}).get("lat"):
                pre_lat, pre_lon, pre_city = self._find_city_in_text(trigger_text)
                if pre_lat is not None:
                    tz_name = self.capability_worker.get_timezone() or "UTC"
                    min_kp = self._aurora_min_kp(pre_lat)
                    data["location"] = {"lat": pre_lat, "lon": pre_lon, "name": pre_city, "tz": tz_name}
                    data["alert_prefs"]["aurora_kp_threshold"] = min_kp
                    self._save_data(data)

            intent = self._classify_intent(trigger_text)
            self.worker.editor_logging_handler.info(
                f"[SpaceWindow] Intent: {intent} | Trigger: {trigger_text[:80]}"
            )

            if intent == "SETUP":
                await self._handle_setup(trigger_text)
            elif intent == "TONIGHT":
                await self._handle_tonight(data)
            elif intent == "ISS":
                await self._handle_iss(data)
            elif intent == "AURORA":
                await self._handle_aurora(data)
            elif intent == "LAUNCHES":
                await self._handle_launches(data)
            elif intent == "ALERTS":
                await self._handle_alerts(data)
            else:
                await self.capability_worker.speak(
                    "I can check tonight's sky, ISS passes, aurora, or upcoming launches. "
                    "What would you like?"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SpaceWindow] Error: {e}")
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Try again in a moment."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())
