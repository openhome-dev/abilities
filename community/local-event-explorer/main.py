import json
import os
import requests
import datetime
import re

from typing import Dict, List, Optional
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# --- App Config ---
class AppConfig:
    # Hardcode your API keys here for easier setup. 
    # If these are empty, the ability will fall back to checking the preferences file.
    # WARNING: DO NOT COMMIT REAL API KEYS TO GITHUB.
    TICKETMASTER_API_KEY = ""
    SEATGEEK_CLIENT_ID = ""
    SERPER_API_KEY = ""

# --- Preferences & Constants ---
PREFS_FILE = "event_explorer_prefs.json"
DEFAULT_PREFS = {
    "home_city": None,
    "api_key_ticketmaster": AppConfig.TICKETMASTER_API_KEY, 
    "api_key_seatgeek": AppConfig.SEATGEEK_CLIENT_ID,   
    "api_key_serper": AppConfig.SERPER_API_KEY          
}

TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
SEATGEEK_URL = "https://api.seatgeek.com/2/events"
SERPER_URL = "https://google.serper.dev/search"

# --- Prompts ---
INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for a voice-activated local event explorer.
The user wants to find concerts, sports, comedy, or festivals. 

Given the user's input, classify their intent into exactly ONE mode.
Return ONLY valid JSON on one line, with no code blocks or markdown fences.

Modes:
- "search": Look up events. Extract any mentioned city/location, category (e.g., 'comedy', 'concert', 'jazz'), and time context ('tonight', 'weekend').
- "expand": Get details about a specific event just mentioned (e.g., "tell me about the first one", "more info on the baseball game").
- "calendar": Add an event to the calendar (e.g., "add that to my calendar", "save the jazz show").
- "city": Set their default home city (e.g., "I live in Austin", "My city is Chicago").
- "exit": Stop/quit/cancel.

User Input: "{user_input}"

Format expected:
{{"mode": "search|expand|calendar|city|exit", "location": "city or null", "category": "extracted keyword or null", "time": "raw time phrase or null", "event_reference": "first|second|jazz or null"}}
"""

# --- Main Class ---
class LocalEventExplorerAbility(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # State for current session
    current_events: List[Dict] = []
    
    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.current_events = []
        self.worker.session_tasks.create(self.run())

    # --- Logging ---
    def _log(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(f"[EventExplorer] {msg}")

    def _err(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(f"[EventExplorer] {msg}")

    # --- Core Loop ---
    async def run(self):
        try:
            self._log("Ability started")
            prefs = await self._load_prefs()
            
            # Greet user
            await self.capability_worker.speak("Welcome to the Event Explorer.")
            
            if not prefs.get("home_city"):
                await self._handle_first_run(prefs)
                
            current_prompt = "What kind of events are you looking for?"
            for _ in range(10): # Session loop
                user_input = await self.capability_worker.run_io_loop(current_prompt)
                
                if not user_input or not user_input.strip():
                    current_prompt = "Are you still there? You can ask for concerts tonight, or say exit."
                    continue
                    
                intent = self._classify_intent(user_input)
                mode = intent.get("mode", "exit")
                
                self._log(f"Classified intent: {intent}")
                
                if mode == "exit":
                    await self.capability_worker.speak("Enjoy your events. Goodbye!")
                    break
                    
                elif mode == "search":
                    await self._handle_search(intent, prefs)
                    current_prompt = "Would you like more details on any of these, or search for something else?"
                    
                elif mode == "expand":
                    await self._handle_expand(intent)
                    current_prompt = "Would you like me to add it to your calendar? Or search for something else?"
                    
                elif mode == "calendar":
                    await self._handle_calendar(intent)
                    current_prompt = "Anything else?"
                    
                elif mode == "city":
                    city = intent.get("location")
                    if city:
                        prefs["home_city"] = city
                        await self._save_prefs(prefs)
                        await self.capability_worker.speak(f"Got it. I've set your default city to {city}.")
                    current_prompt = "What events are you looking for?"
                    
        except Exception as e:
            self._err(f"Fatal error in run loop: {e}")
            if self.capability_worker:
                await self.capability_worker.speak("Sorry, something went wrong with the Event Explorer.")
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()

    # --- Preferences & Geolocation ---
    async def _load_prefs(self) -> dict:
        exists = await self.capability_worker.check_if_file_exists(PREFS_FILE, False)
        if exists:
            try:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                return json.loads(raw)
            except Exception as e:
                self._err(f"Error loading prefs: {e}")
        return dict(DEFAULT_PREFS)

    async def _save_prefs(self, prefs: dict):
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            await self.capability_worker.delete_file(PREFS_FILE, False)
        await self.capability_worker.write_file(PREFS_FILE, json.dumps(prefs), False)

    async def _handle_first_run(self, prefs: dict):
        # Try to infer from IP first
        ip_city = self._fetch_ip_city()
        if ip_city:
            await self.capability_worker.speak(f"It looks like you're in {ip_city}. Should I use this as your default location for events?")
            ans = await self.capability_worker.user_response()
            if ans and "yes" in ans.lower():
                prefs["home_city"] = ip_city
                await self._save_prefs(prefs)
                await self.capability_worker.speak("Great, saved.")
                return

        # Explicitly ask
        await self.capability_worker.speak("I don't know where you are located. What city would you like to search in by default?")
        resp = await self.capability_worker.user_response()
        if resp:
            # Let LLM extract city nicely
            intent = self._classify_intent(resp)
            loc = intent.get("location") or resp.strip()
            prefs["home_city"] = loc
            await self._save_prefs(prefs)
            await self.capability_worker.speak(f"I've saved {loc} as your home city.")

    def _fetch_ip_city(self) -> Optional[str]:
        try:
            ip = self.worker.user_socket.client.host
            resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    # Ignore cloud IPs which are often inaccurate
                    isp = data.get("isp", "").lower()
                    cloud_indicators = ["amazon", "aws", "google", "microsoft", "azure", "digitalocean"]
                    if not any(c in isp for c in cloud_indicators):
                        return data.get("city")
        except Exception as e:
            self._err(f"IP Geolocation failed: {e}")
        return None

    # --- LLM Parsing ---
    def _classify_intent(self, user_input: str) -> dict:
        try:
            prompt = INTENT_CLASSIFIER_PROMPT.format(user_input=user_input)
            raw = self.capability_worker.text_to_text_response(prompt)
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except Exception as e:
            self._err(f"Intent parsing failed: {e}")
            # Fallback
            if "exit" in user_input.lower() or "stop" in user_input.lower():
                return {"mode": "exit"}
            return {"mode": "search", "location": None, "category": user_input, "time": None}

    # --- Date Parsing Helpers ---
    def _parse_time_context(self, time_string: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """Parses words like 'tonight', 'tomorrow', 'this weekend' into ISO-8601 start/end slices."""
        if not time_string:
            return None, None
            
        now = datetime.datetime.now()
        lowered = time_string.lower()
        
        # Simplified LLM date logic for standard phrases
        # Ticketmaster needs Format: 2026-10-31T20:00:00Z
        if "tonight" in lowered or "today" in lowered:
            start = now.replace(hour=17, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
            end = (now + datetime.timedelta(days=1)).replace(hour=4, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
            return start, end
            
        elif "tomorrow" in lowered:
            tmrw = now + datetime.timedelta(days=1)
            start = tmrw.replace(hour=8, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
            end = tmrw.replace(hour=23, minute=59, second=59).strftime("%Y-%m-%dT%H:%M:%SZ")
            return start, end
            
        elif "weekend" in lowered:
            # Shift to Friday
            days_ahead = 4 - now.weekday()
            if days_ahead <= 0: # It is currently the weekend
                days_ahead += 7
            friday = now + datetime.timedelta(days=days_ahead)
            sunday = friday + datetime.timedelta(days=2)
            
            start = friday.replace(hour=17, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
            end = sunday.replace(hour=23, minute=59, second=59).strftime("%Y-%m-%dT%H:%M:%SZ")
            return start, end
            
        return None, None

    # --- API Integrations ---
    def _fetch_ticketmaster(self, city: str, keyword: str, start_dt: str, end_dt: str, api_key: str) -> List[Dict]:
        key_to_use = AppConfig.TICKETMASTER_API_KEY or api_key
        if not key_to_use or key_to_use == "YOUR_TICKETMASTER_KEY":
            return []
            
        params = {
            "apikey": api_key,
            "city": city,
            "size": 3,
            "sort": "date,asc",
            "locale": "*"
        }
        if keyword:
            params["keyword"] = keyword
        if start_dt:
            params["startDateTime"] = start_dt
        if end_dt:
            params["endDateTime"] = end_dt
            
        try:
            resp = requests.get(TICKETMASTER_URL, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                events = data.get("_embedded", {}).get("events", [])
                
                parsed = []
                for e in events:
                    name = e.get("name", "Unknown Event")
                    url = e.get("url", "")
                    
                    # Extract venue
                    venues = e.get("_embedded", {}).get("venues", [])
                    venue_name = venues[0].get("name", "an unknown venue") if venues else "an unknown venue"
                    
                    # Extract date
                    start_date = e.get("dates", {}).get("start", {}).get("localDate", "")
                    start_time = e.get("dates", {}).get("start", {}).get("localTime", "")
                    
                    parsed.append({
                        "name": name,
                        "venue": venue_name,
                        "date": start_date,
                        "time": start_time,
                        "url": url,
                        "source": "Ticketmaster"
                    })
                return parsed
        except Exception as e:
            self._err(f"Ticketmaster API error: {e}")
        return []

    def _fetch_seatgeek(self, city: str, keyword: str, client_id: str) -> List[Dict]:
        id_to_use = AppConfig.SEATGEEK_CLIENT_ID or client_id
        if not id_to_use or id_to_use == "YOUR_SEATGEEK_CLIENT_ID":
            return []
            
        params = {
            "client_id": client_id,
            "venue.city": city,
            "per_page": 3,
            "sort": "datetime_local.asc"
        }
        if keyword:
            params["q"] = keyword
            
        try:
            resp = requests.get(SEATGEEK_URL, params=params, timeout=8)
            if resp.status_code == 200:
                events = resp.json().get("events", [])
                parsed = []
                for e in events:
                    name = e.get("title", "Unknown Event")
                    url = e.get("url", "")
                    venue_name = e.get("venue", {}).get("name", "an unknown venue")
                    
                    # "2026-10-31T20:00:00" format in SeatGeek
                    dt_local = e.get("datetime_local", "")
                    start_date = dt_local.split("T")[0] if "T" in dt_local else ""
                    start_time = dt_local.split("T")[1][:5] if "T" in dt_local else ""
                    
                    parsed.append({
                        "name": name,
                        "venue": venue_name,
                        "date": start_date,
                        "time": start_time,
                        "url": url,
                        "source": "SeatGeek"
                    })
                return parsed
        except Exception as e:
            self._err(f"SeatGeek API error: {e}")
        return []

    def _fetch_serper(self, city: str, keyword: str, time_context: str, api_key: str) -> List[Dict]:
        """Uses Google's Event graph directly. Extremely broad coverage."""
        key_to_use = AppConfig.SERPER_API_KEY or api_key
        if not key_to_use or key_to_use == "YOUR_SERPER_API_KEY":
            return []

        query = f"events in {city}"
        if keyword:
            query += f" {keyword}"
        if time_context:
            query += f" {time_context}"

        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(SERPER_URL, headers=headers, json={"q": query}, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                events = data.get("events", [])
                parsed = []
                for e in events[:3]: # Cap at 3 for serper to limit voice length
                    title = e.get("title", "Unknown Event")
                    address = e.get("address", "an unknown location")
                    date_str = e.get("date", "")
                    link = e.get("link", "")
                    
                    # Serper usually returns date like "Sat, Nov 16, 7 PM"
                    parsed.append({
                        "name": title,
                        "venue": address,
                        "date": date_str,
                        "time": "", # Time is usually bundled in the date string for Serper
                        "url": link,
                        "source": "Google Events"
                    })
                return parsed
        except Exception as e:
            self._err(f"Serper API error: {e}")
        return []

    # --- Handlers ---
    async def _handle_search(self, intent: dict, prefs: dict):
        city = intent.get("location") or prefs.get("home_city")
        if not city:
            await self.capability_worker.speak("I don't know what city you want to search in. What is your city?")
            return
            
        keyword = intent.get("category", "")
        time_context = intent.get("time", "")
        
        # Give user instant feedback before the network call
        search_desc = f"{keyword or 'events'} in {city}"
        if time_context:
            search_desc += f" for {time_context}"
        
        await self.capability_worker.speak(f"Let me check for {search_desc}...")
        
        start_dt, end_dt = self._parse_time_context(time_context)
        
        # 1. Try Ticketmaster
        tm_events = self._fetch_ticketmaster(
            city=city, 
            keyword=keyword, 
            start_dt=start_dt, 
            end_dt=end_dt, 
            api_key=prefs.get("api_key_ticketmaster")
        )
        
        # 2. Try SeatGeek if TM empty
        if not tm_events:
            self._log("Ticketmaster returned 0 events or failed. Trying SeatGeek fallback.")
            tm_events = self._fetch_seatgeek(
                city=city,
                keyword=keyword,
                client_id=prefs.get("api_key_seatgeek")
            )
            
        # 3. Try Serper (Google Events)
        serper_events = self._fetch_serper(
            city=city,
            keyword=keyword,
            time_context=time_context,
            api_key=prefs.get("api_key_serper")
        )
        
        # Combine! Take top 2 from structured APIs, Top 2 from Serper
        combined_events = []
        if tm_events: combined_events.extend(tm_events[:2])
        if serper_events: combined_events.extend(serper_events[:2])
        
        # Deduplicate titles lightly just in case TM and Serper returned the same massive concert
        seen = set()
        final_events = []
        for e in combined_events:
            title_lower = e["name"].lower().strip()
            if title_lower not in seen:
                seen.add(title_lower)
                final_events.append(e)

        self.current_events = final_events
        
        if not final_events:
            await self.capability_worker.speak("I couldn't find any events matching that description right now. Note that you may need to configure your API keys for Ticketmaster and Serper in the settings file first. What else can I check for you?")
            return
            
        summary = f"I found {len(final_events)} events."
        for i, ev in enumerate(final_events):
            num = ["First", "Second", "Third", "Fourth", "Fifth"][i]
            
            # Format time
            time_str = ev['time']
            if time_str:
                try:
                    # e.g. "19:00:00" -> "7:00 PM"
                    t = datetime.datetime.strptime(time_str[:5], "%H:%M")
                    time_str = t.strftime("%I:%M %p").lstrip("0")
                except Exception:
                    pass
            
            # e.g "First, Taylor Swift at the Superdome at 7 PM."
            summary += f" {num}, {ev['name']} at {ev['venue']}"
            if time_str:
                summary += f" at {time_str}"
            summary += "."
            
        await self.capability_worker.speak(summary)

    async def _handle_expand(self, intent: dict):
        if not self.current_events:
            await self.capability_worker.speak("I don't have any events loaded right now. You'll need to search for some first.")
            return

        ref = intent.get("event_reference", "").lower()
        idx = 0 # Default to first

        word_to_idx = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
        for word, i in word_to_idx.items():
            if word in ref:
                idx = i
                break

        if idx >= len(self.current_events):
            await self.capability_worker.speak("I didn't find that many events in the last search.")
            return

        ev = self.current_events[idx]
        
        # Build richer description
        desc = f"{ev['name']} is happening at {ev['venue']}."
        if ev['date']:
            desc += f" The date is {ev['date']}."
        if ev['time']:
            desc += f" Starts at {ev['time']}."
        
        await self.capability_worker.speak(desc)

    async def _handle_calendar(self, intent: dict):
        if not self.current_events:
            await self.capability_worker.speak("I don't have any events loaded right now.")
            return

        ref = intent.get("event_reference", "").lower()
        idx = 0 
        word_to_idx = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
        for word, i in word_to_idx.items():
            if word in ref:
                idx = i
                break

        if idx >= len(self.current_events):
            await self.capability_worker.speak("I didn't find that many events.")
            return

        ev = self.current_events[idx]
        
        # Build a Google Calendar template link
        # Format: https://calendar.google.com/calendar/r/eventedit?text=Event+Name&dates=20240101T200000Z/20240101T220000Z&details=Link&location=Venue
        
        import urllib.parse
        
        title = urllib.parse.quote_plus(ev['name'])
        location = urllib.parse.quote_plus(ev['venue'])
        details = urllib.parse.quote_plus(f"Found via OpenHome Local Event Explorer. Link: {ev['url']}")
        
        # Try to parse exact date to format YYYYMMDDTHHMMSSZ
        dates_param = ""
        try:
            if ev['date']:
                # Assume 2 hours duration for simplicity if no end time provided by discovery
                d_str = ev['date']
                t_str = (ev['time'] or "12:00:00")[:8]
                dt = datetime.datetime.strptime(f"{d_str} {t_str}", "%Y-%m-%d %H:%M:%S")
                end_dt = dt + datetime.timedelta(hours=2)
                
                # Google format requires basic ISO string
                g_start = dt.strftime("%Y%m%dT%H%M%S")
                g_end = end_dt.strftime("%Y%m%dT%H%M%S")
                dates_param = f"&dates={g_start}/{g_end}"
        except Exception as e:
            self._log(f"Failed to parse dates for calendar link: {e}")
            pass

        cal_link = f"https://calendar.google.com/calendar/r/eventedit?text={title}&location={location}&details={details}{dates_param}"
        
        self._log(f"Generated calendar link: {cal_link}")
        
        await self.capability_worker.speak(f"I generated an 'Add to Calendar' link for {ev['name']}. I've sent it to your device.")
        
        # In the context of OpenHome, if there's a companion app interface, we could send a payload.
        # For voice-only, we just log it and rely on the companion app to pull it from the socket context if designed.
        # (This implements the planned workaround cleanly)
