"""
Outlook Daily Brief — OpenHome Ability.
Fetches calendar, email, and weather in parallel, synthesizes one ~60s spoken briefing.
One file, one class. Microsoft Graph (OAuth) + Open-Meteo (free) API.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# CONFIG — use env/secrets in production

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
CLIENT_ID = "your_client_id"
TENANT_ID = "consumers"
REFRESH_TOKEN = "your_refresh_token"

# Prevents collision with other abilities
PREFS_FILE = "outlook_daily_brief_prefs.json"
API_TIMEOUT = 5
PARALLEL_TIMEOUT = 6

# Idle timeouts before sign-off; high count so follow-ups are still in scope
FOLLOW_UP_IDLE_TIMEOUT_SEC = 20.0
FOLLOW_UP_IDLE_COUNT_BEFORE_SIGNOFF = 5

EXIT_WORDS = [
    "stop",
    "done",
    "quit",
    "exit",
    "bye",
    "goodbye",
    "nothing else",
    "all good",
    "nope",
    "no thanks",
    "i'm good",
    "im good",
]
CANCEL_PHRASES = ["never mind", "nevermind", "cancel", "forget it"]
REPEAT_WORDS = ["repeat", "again", "say that again", "replay"]
CATCH_UP_PHRASES = ["what did i miss", "what i miss", "catch me up", "anything urgent"]

BRIEFING_SYSTEM_PROMPT = (
    "You are a warm, professional morning briefing host. Synthesize the following "
    "data into a concise ~60-second spoken morning briefing. Be conversational but "
    "efficient. Transition smoothly between sections. If a section has no data, skip "
    "it without mentioning it's missing. Output only the script to be read aloud, "
    "no meta-commentary."
)

BRIEFING_SYSTEM_PROMPT_URGENT = (
    "The user asked 'What did I miss?' — give a short catch-up, not a full morning brief. "
    "Lead with what needs attention: upcoming calendar (times, what's next), then unread email "
    "that matters (, important senders). Use phrases like 'heads up', 'worth checking', "
    "'came in recently'. Skip or one-line non-urgent items (e.g. promos). Weather: one sentence only "
    "if at all. Keep it to ~30–40 seconds. Do NOT open with 'Good morning' or a full date — open with "
    "'Here's what's new' or 'Quick catch-up'. End with 'That's what's new' or similar. "
    "Output only the script to be read aloud."
)

TRIGGER_INTENT_PROMPT = """Classify the user's trigger for a daily brief. Return ONLY JSON:
{"mode": "full" or "urgent"}

- "full" = standard morning brief (good morning, brief me, start my day, give me my brief, daily brief).
- "urgent" = what did I miss / catch-up emphasis.

User's recent message(s):
{trigger_context}
"""

# =============================================================================
# MAIN CLASS
# =============================================================================


class OutlookBriefCapability(MatchingCapability):

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    prefs: Dict = {}
    last_script: Optional[str] = None
    last_brief_mode: str = "full"  # full | urgent, for repeat

    # -------------------------------------------------------------------------
    # REGISTRATION & ENTRY
    # -------------------------------------------------------------------------

    # {{register capability}}

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def log(self, msg: str):
        self.worker.editor_logging_handler.info(f"[OutlookDailyBrief] {msg}")

    def log_err(self, msg: str):
        self.worker.editor_logging_handler.error(f"[OutlookDailyBrief] {msg}")

    # -------------------------------------------------------------------------
    # MAIN RUN
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            await self.capability_worker.speak("One sec, pulling your brief together.")

            self.prefs = await self.load_preferences()
            trigger_context = self.get_trigger_context()
            intent = self.classify_trigger_intent(trigger_context)
            mode = intent.get("mode", "full")

            enabled = self.prefs.get("enabled_sections") or [
                "weather",
                "calendar",
                "email",
            ]
            calendar_data: Optional[Dict] = None
            email_data: Optional[Dict] = None
            weather_data: Optional[Dict] = None

            try:
                calendar_data, email_data, weather_data = (
                    await self._fetch_all_parallel(enabled)
                )
            except Exception as e:
                self.log_err(f"Parallel fetch error: {e}")

            if not any([calendar_data, email_data, weather_data]):
                await self.capability_worker.speak(
                    "I'm having trouble reaching some services right now. Let me try again in a moment."
                )
                self.capability_worker.resume_normal_flow()
                return

            await self._save_preferences()

            system_prompt = (
                BRIEFING_SYSTEM_PROMPT_URGENT
                if mode == "urgent"
                else BRIEFING_SYSTEM_PROMPT
            )
            script = self._synthesize_briefing(
                calendar_data, email_data, weather_data, system_prompt, enabled
            )
            if not (script and script.strip()):
                await self.capability_worker.speak(
                    "I couldn't put together a briefing right now. Try again in a moment."
                )
                self.capability_worker.resume_normal_flow()
                return

            self.last_script = script.strip()
            self.last_brief_mode = mode
            await self.capability_worker.speak(self.last_script)
            await self._follow_up_loop()

        except Exception as e:
            self.log_err(str(e))
            await self.capability_worker.speak(
                "I'm having trouble reaching some services right now. Let me try again in a moment."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    # -------------------------------------------------------------------------
    # TRIGGER CONTEXT
    # -------------------------------------------------------------------------

    def get_trigger_context(self) -> Dict:
        recent: List[str] = []
        trigger = ""
        try:
            history = self.worker.agent_memory.full_message_history
            for msg in reversed(history or []):
                if hasattr(msg, "role") and "user" in str(msg.role).lower():
                    content = str(msg.content).strip()
                    if content:
                        recent.append(content)
                        if not trigger:
                            trigger = content
                    if len(recent) >= 5:
                        break
        except Exception:
            pass
        recent_text = (
            "\n".join(reversed(recent)) if recent else (trigger or "good morning")
        )
        return {"trigger": trigger, "trigger_context": recent_text}

    def classify_trigger_intent(self, trigger_context: Dict) -> Dict:
        # Classify from current utterance only so history doesn't override
        current = trigger_context.get("trigger", "") or ""
        if not isinstance(current, str):
            current = str(current)
        current_lower = current.lower().strip()
        if "what did i miss" in current_lower or "what i miss" in current_lower:
            return {"mode": "urgent"}
        if any(
            p in current_lower
            for p in [
                "good morning",
                "brief me",
                "give me my brief",
                "daily brief",
                "start my day",
            ]
        ):
            return {"mode": "full"}
        text = trigger_context.get("trigger_context", "") or current
        if not isinstance(text, str):
            text = str(text)
        try:
            prompt = TRIGGER_INTENT_PROMPT.format(trigger_context=text)
            raw = self.capability_worker.text_to_text_response(prompt)
            clean = (raw or "").replace("```json", "").replace("```", "").strip()
            start, end = clean.find("{"), clean.rfind("}")
            if start != -1 and end > start:
                clean = clean[start : end + 1]
            out = json.loads(clean)
            if isinstance(out, dict) and out.get("mode") in ("full", "urgent"):
                return out
        except Exception as e:
            self.log_err(f"Trigger classify: {e}")
        return {"mode": "full"}

    # -------------------------------------------------------------------------
    # PARALLEL FETCH
    # -------------------------------------------------------------------------

    async def _fetch_all_parallel(
        self, enabled_sections: Optional[List[str]] = None
    ) -> tuple:
        enabled = enabled_sections or ["weather", "calendar", "email"]
        do_cal = "calendar" in enabled
        do_mail = "email" in enabled
        do_weather = "weather" in enabled

        async def _none() -> None:
            return None

        tasks = []
        if do_cal:
            tasks.append(
                asyncio.wait_for(
                    asyncio.to_thread(self._fetch_calendar_sync),
                    timeout=PARALLEL_TIMEOUT,
                )
            )
        else:
            tasks.append(_none())
        if do_mail:
            tasks.append(
                asyncio.wait_for(
                    asyncio.to_thread(self._fetch_email_sync),
                    timeout=PARALLEL_TIMEOUT,
                )
            )
        else:
            tasks.append(_none())
        if do_weather:
            tasks.append(
                asyncio.wait_for(
                    asyncio.to_thread(self._fetch_weather_sync),
                    timeout=PARALLEL_TIMEOUT,
                )
            )
        else:
            tasks.append(_none())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        cal = results[0] if not isinstance(results[0], BaseException) else None
        mail = results[1] if not isinstance(results[1], BaseException) else None
        weather = results[2] if not isinstance(results[2], BaseException) else None
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                self.log_err(f"Fetch error ({['cal', 'mail', 'weather'][i]}): {r}")
        return (cal, mail, weather)

    def _fetch_calendar_sync(self) -> Optional[Dict]:
        if not REFRESH_TOKEN or REFRESH_TOKEN == "YOUR_REFRESH_TOKEN":
            return None
        token, err = self._refresh_access_token()
        if err or not token:
            return None
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        start_iso = start.isoformat().replace("+00:00", "Z")
        end_iso = end.isoformat().replace("+00:00", "Z")
        url = (
            f"{GRAPH_BASE_URL}/me/calendarview"
            f"?startDateTime={start_iso}&endDateTime={end_iso}"
        )
        try:
            r = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=API_TIMEOUT,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            events = data.get("value", [])
            out = []
            for ev in events:
                start_dt = (ev.get("start") or {}).get("dateTime")
                end_dt = (ev.get("end") or {}).get("dateTime")
                loc = (ev.get("location") or {}).get("displayName") or ""
                out.append(
                    {
                        "subject": ev.get("subject") or "(No title)",
                        "start": start_dt,
                        "end": end_dt,
                        "location": loc,
                    }
                )
            return {"events": out}
        except Exception as e:
            self.log_err(f"Calendar API: {e}")
            return None

    def _fetch_email_sync(self) -> Optional[Dict]:
        if not REFRESH_TOKEN or REFRESH_TOKEN == "YOUR_REFRESH_TOKEN":
            return None
        token, err = self._refresh_access_token()
        if err or not token:
            return None
        url = (
            f"{GRAPH_BASE_URL}/me/mailFolders/inbox/messages"
            "?$filter=isRead eq false&$top=5&$select=subject,from,receivedDateTime"
        )
        try:
            r = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=API_TIMEOUT,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            items = data.get("value", [])
            out = []
            for m in items:
                from_addr = (m.get("from") or {}).get("emailAddress", {})
                name = from_addr.get("name") or from_addr.get("address") or "Unknown"
                out.append(
                    {
                        "subject": m.get("subject") or "(No subject)",
                        "from": name,
                        "received": m.get("receivedDateTime"),
                    }
                )
            return {"unread_count": len(out), "messages": out}
        except Exception as e:
            self.log_err(f"Mail API: {e}")
            return None

    def _fetch_weather_sync(self) -> Optional[Dict]:
        lat, lon, city = self._resolve_weather_location_sync()
        if lat is None or lon is None:
            return None
        try:
            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lon}"
                "&current=temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m"
                "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
                "&timezone=auto"
            )
            r = requests.get(url, timeout=API_TIMEOUT)
            if r.status_code != 200:
                return None
            data = r.json()
            cur = data.get("current", {})
            daily = data.get("daily") or {}
            daily_max = daily.get("temperature_2m_max") or []
            daily_min = daily.get("temperature_2m_min") or []
            daily_pop = daily.get("precipitation_probability_max") or []
            today_max = daily_max[0] if daily_max else cur.get("temperature_2m")
            today_min = daily_min[0] if daily_min else None
            pop_today = daily_pop[0] if daily_pop else None
            return {
                "location": city or f"{lat:.1f}, {lon:.1f}",
                "current_temp": cur.get("temperature_2m"),
                "weather_code": cur.get("weather_code"),
                "wind_speed": cur.get("wind_speed_10m"),
                "humidity": cur.get("relative_humidity_2m"),
                "today_high": today_max,
                "today_low": today_min,
                "precipitation_chance": pop_today,
            }
        except Exception as e:
            self.log_err(f"Weather API: {e}")
            return None

    def _resolve_weather_location_sync(self) -> tuple:
        location = self.prefs.get("location")
        if location and isinstance(location, str) and location.strip():
            lat, lon = self._geocode_city_sync(location.strip())
            if lat is not None and lon is not None:
                return (lat, lon, location.strip())
        lat, lon, city = self._ip_geo_sync()
        if lat is not None and lon is not None and city:
            self.prefs["location"] = city
        return (lat, lon, city or (self.prefs.get("location") or "your area"))

    def _geocode_city_sync(self, city: str) -> tuple:
        try:
            r = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1},
                timeout=API_TIMEOUT,
            )
            if r.status_code != 200:
                return (None, None)
            data = r.json()
            results = data.get("results", [])
            if not results:
                return (None, None)
            first = results[0]
            return (first.get("latitude"), first.get("longitude"))
        except Exception:
            return (None, None)

    def _ip_geo_sync(self) -> tuple:
        try:
            r = requests.get(
                "http://ip-api.com/json/?fields=lat,lon,city",
                timeout=API_TIMEOUT,
            )
            if r.status_code != 200:
                return (None, None, None)
            data = r.json()
            return (
                data.get("lat"),
                data.get("lon"),
                data.get("city") or None,
            )
        except Exception:
            return (None, None, None)

    def _refresh_access_token(self) -> tuple:
        url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
        payload = {
            "client_id": CLIENT_ID,
            "refresh_token": REFRESH_TOKEN,
            "grant_type": "refresh_token",
            "scope": (
                "https://graph.microsoft.com/Calendars.Read "
                "https://graph.microsoft.com/Mail.Read"
            ),
        }
        try:
            r = requests.post(url, data=payload, timeout=API_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                return (data.get("access_token"), None)
            self.log_err(f"Token refresh: {r.status_code} {r.text}")
            return (None, "refresh_failed")
        except Exception as e:
            self.log_err(f"Token refresh: {e}")
            return (None, str(e))

    # -------------------------------------------------------------------------
    # LLM SYNTHESIS
    # -------------------------------------------------------------------------

    def _synthesize_briefing(
        self,
        calendar_data: Optional[Dict],
        email_data: Optional[Dict],
        weather_data: Optional[Dict],
        system_prompt: str,
        enabled_sections: Optional[List[str]] = None,
    ) -> str:
        enabled = enabled_sections or ["weather", "calendar", "email"]
        payload = {}
        if "calendar" in enabled and calendar_data:
            payload["calendar"] = calendar_data
        if "email" in enabled and email_data:
            payload["email"] = email_data
        if "weather" in enabled and weather_data:
            payload["weather"] = weather_data
        prompt = "Data for the briefing:\n" + json.dumps(payload, indent=2)
        try:
            return self.capability_worker.text_to_text_response(
                prompt, history=[], system_prompt=system_prompt
            )
        except Exception as e:
            self.log_err(f"LLM synthesis: {e}")
            return ""

    # -------------------------------------------------------------------------
    # FOLLOW-UP LOOP
    # -------------------------------------------------------------------------

    async def _follow_up_loop(self):
        idle_count = 0
        while True:
            try:
                user = await asyncio.wait_for(
                    self.capability_worker.user_response(),
                    timeout=FOLLOW_UP_IDLE_TIMEOUT_SEC,
                )
            except Exception:
                idle_count += 1
                if idle_count >= FOLLOW_UP_IDLE_COUNT_BEFORE_SIGNOFF:
                    await self.capability_worker.speak(
                        "I'm still here if you need anything. Otherwise I'll sign off."
                    )
                    break
                continue
            if not user or not user.strip():
                idle_count += 1
                if idle_count >= FOLLOW_UP_IDLE_COUNT_BEFORE_SIGNOFF:
                    await self.capability_worker.speak(
                        "I'm still here if you need anything. Otherwise I'll sign off."
                    )
                    break
                continue
            idle_count = 0
            lower = user.strip().lower()
            if any(w in lower for w in EXIT_WORDS):
                await self.capability_worker.speak(
                    "Done. Let me know when you want your next brief."
                )
                break
            if any(p in lower for p in CANCEL_PHRASES):
                await self.capability_worker.speak("Okay.")
                break
            if any(w in lower for w in REPEAT_WORDS):
                # Re-fetch so repeat uses current prefs
                await self.capability_worker.speak("One sec.")
                enabled = self.prefs.get("enabled_sections") or [
                    "weather",
                    "calendar",
                    "email",
                ]
                try:
                    calendar_data, email_data, weather_data = (
                        await self._fetch_all_parallel(enabled)
                    )
                except Exception as e:
                    self.log_err(f"Repeat fetch: {e}")
                    if self.last_script:
                        await self.capability_worker.speak(self.last_script)
                    continue
                if not any([calendar_data, email_data, weather_data]):
                    if self.last_script:
                        await self.capability_worker.speak(self.last_script)
                    continue
                system_prompt = (
                    BRIEFING_SYSTEM_PROMPT_URGENT
                    if self.last_brief_mode == "urgent"
                    else BRIEFING_SYSTEM_PROMPT
                )
                script = self._synthesize_briefing(
                    calendar_data,
                    email_data,
                    weather_data,
                    system_prompt,
                    enabled,
                )
                if script and script.strip():
                    self.last_script = script.strip()
                    await self.capability_worker.speak(self.last_script)
                elif self.last_script:
                    await self.capability_worker.speak(self.last_script)
                continue
            if "change my city" in lower or "change city" in lower:
                city = self._extract_city_from_change(user)
                if city:
                    self.prefs["location"] = city
                    await self._save_preferences()
                    await self.capability_worker.speak(
                        f"Updated to {city}. Say repeat to hear your brief again."
                    )
                else:
                    await self.capability_worker.speak(
                        "Which city? Say 'change my city to' and the city name."
                    )
                continue
            if any(p in lower for p in CATCH_UP_PHRASES):
                await self.capability_worker.speak("One sec, checking what's new.")
                enabled = self.prefs.get("enabled_sections") or [
                    "weather",
                    "calendar",
                    "email",
                ]
                try:
                    calendar_data, email_data, weather_data = (
                        await self._fetch_all_parallel(enabled)
                    )
                except Exception as e:
                    self.log_err(f"Catch-up fetch: {e}")
                    await self.capability_worker.speak(
                        "I'm having trouble reaching some services right now. Try again in a moment."
                    )
                    continue
                if not any([calendar_data, email_data, weather_data]):
                    await self.capability_worker.speak(
                        "I'm having trouble reaching some services right now. Try again in a moment."
                    )
                    continue
                script = self._synthesize_briefing(
                    calendar_data,
                    email_data,
                    weather_data,
                    BRIEFING_SYSTEM_PROMPT_URGENT,
                    enabled,
                )
                if not (script and script.strip()):
                    await self.capability_worker.speak(
                        "I couldn't put together an update right now. Try again in a moment."
                    )
                    continue
                self.last_script = script.strip()
                self.last_brief_mode = "urgent"
                await self.capability_worker.speak(self.last_script)
                continue
            break

    def _extract_city_from_change(self, text: str) -> Optional[str]:
        lower = text.lower().strip()
        out = None
        for prefix in (
            "change my city to ",
            "change city to ",
            "set city to ",
            "change my location to ",
        ):
            if lower.startswith(prefix):
                out = text[len(prefix) :].strip()
                break
        if out is None and " to " in lower:
            out = text.split(" to ", 1)[-1].strip()
        if not out:
            return None
        # Trailing punctuation breaks geocoding
        return out.rstrip(".,?!").strip() or None

    # -------------------------------------------------------------------------
    # PREFERENCES (platform file APIs)
    # -------------------------------------------------------------------------

    async def load_preferences(self) -> Dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )
            if not exists:
                return {
                    "location": None,
                    "calendar_connected": False,
                    "email_connected": False,
                    "enabled_sections": ["weather", "calendar", "email"],
                }
            raw = await self.capability_worker.read_file(PREFS_FILE, False)
            data = json.loads(raw) if raw else {}
            data.setdefault("location", None)
            data.setdefault("calendar_connected", False)
            data.setdefault("email_connected", False)
            data.setdefault("enabled_sections", ["weather", "calendar", "email"])
            return data
        except Exception as e:
            self.log_err(f"Load prefs: {e}")
            return {
                "location": None,
                "calendar_connected": False,
                "email_connected": False,
                "enabled_sections": ["weather", "calendar", "email"],
            }

    async def _save_preferences(self):
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                await self.capability_worker.delete_file(PREFS_FILE, False)
            await self.capability_worker.write_file(
                PREFS_FILE, json.dumps(self.prefs), False
            )
        except Exception as e:
            self.log_err(f"Save prefs: {e}")
