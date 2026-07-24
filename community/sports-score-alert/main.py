import json
import requests
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "sports_score_data"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
CRIC_BASE = "https://api.cricapi.com/v1/currentMatches"

ESPN_LEAGUES = {
    "nfl": ("football", "nfl"),
    "nba": ("basketball", "nba"),
    "mlb": ("baseball", "mlb"),
    "nhl": ("hockey", "nhl"),
    "premier league": ("soccer", "eng.1"),
    "epl": ("soccer", "eng.1"),
    "la liga": ("soccer", "esp.1"),
    "bundesliga": ("soccer", "ger.1"),
    "serie a": ("soccer", "ita.1"),
    "ligue 1": ("soccer", "fra.1"),
    "mls": ("soccer", "usa.1"),
    "champions league": ("soccer", "uefa.champions"),
    "soccer": ("soccer", "all"),
    "football": ("soccer", "eng.1"),
}

HOTWORDS = {
    "sports alert", "follow my team", "follow", "sports score", "game score",
    "live score", "soccer score", "cricket score", "nba score", "nfl score",
    "track my team", "sports update", "game update", "match score",
    "what's the score", "did they win", "game today", "match today",
    "unfollow", "stop following", "sports schedule", "when do they play",
    "cricket", "who's winning", "final score",
}

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "that's all"}


TEAM_EXTRACT_PROMPT = (
    "Extract the team name and sport from: '{text}'. "
    "Reply as JSON with keys: name (string), sport (one of: cricket, soccer, nba, nfl, mlb, nhl, other), "
    "league (league name if mentioned, else empty string). "
    "Reply ONLY with valid JSON, no extra text."
)

LIVE_SCORE_PROMPT = (
    "Describe this live sports situation in 2 spoken sentences for a voice assistant. "
    "Sport: {sport}. Match: {team_a} vs {team_b}. Current score: {score}. "
    "Situation: {context}. "
    "Sentence 1: who is leading and by how much. "
    "Sentence 2: the current game situation (time remaining, innings, period etc). "
    "No markdown. Plain English."
)

SCHEDULE_PROMPT = (
    "Summarise these upcoming games for a voice assistant in 1-2 spoken sentences. "
    "Games: {games}. "
    "State team names, opponents, and dates only. No commentary, hype, or editorialising. "
    "No markdown. Plain English."
)


def _empty_data() -> dict:
    return {
        "followed_teams": [],
        "alert_prefs": {
            "pre_match_minutes": 30,
            "comeback_threshold": 10,
        },
        "fired_alerts": [],
    }


class SportsScoreAlertCapability(MatchingCapability):
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
            self.worker.editor_logging_handler.error(f"[Sports] Load error: {e!r}")
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
            self.worker.editor_logging_handler.error(f"[Sports] Save error: {e!r}")
            return
        self.worker.editor_logging_handler.error("[Sports] Save failed")

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_exit(text: str) -> bool:
        # Short ambiguous words ("stop", "done") only count as an exit when
        # they're the WHOLE reply. In sports commentary "stop" and "done" are
        # frequently real, standalone words ("what a stop by the goalie",
        # "is it done yet", "stop following the Yankees" -> UNFOLLOW below) —
        # a plain word-boundary check still matches those, since the word
        # genuinely is "stop"/"done" there. Only requiring the entire
        # utterance to be the exit word avoids false-exiting on them, at the
        # minor cost of not catching "yeah, stop" with filler words attached.
        # Distinctive multi-word phrases ("that's all") still match anywhere.
        lower = (text or "").lower().strip().rstrip(".!?")
        if not lower:
            return False
        if lower in EXIT_WORDS:
            return True
        return any(phrase in lower for phrase in EXIT_WORDS if " " in phrase)

    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        if self._is_exit(text):
            return "EXIT"
        if any(w in t for w in ("unfollow", "stop following", "remove")):
            return "UNFOLLOW"
        if any(w in t for w in ("follow", "track my", "add team", "watch")):
            return "FOLLOW"
        if any(w in t for w in ("schedule", "when do they", "next game", "upcoming", "when is")):
            return "SCHEDULE"
        if any(w in t for w in ("result", "did they win", "final score", "how did they")):
            return "RESULTS"
        return "LIVE"

    def _extract_team(self, text: str) -> dict:
        raw = self.capability_worker.text_to_text_response(
            TEAM_EXTRACT_PROMPT.format(text=text)
        ).strip()
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Sports] Team extract error: {e!r}")
        return {"name": text.strip(), "sport": "other", "league": ""}

    # ------------------------------------------------------------------
    # ESPN helpers
    # ------------------------------------------------------------------

    def _espn_league_for(self, team: dict) -> str:
        league = team.get("espn_league", "")
        if league:
            return league
        sport = team.get("sport", "").lower()
        if sport == "nba":
            return "nba"
        if sport == "nfl":
            return "nfl"
        if sport == "mlb":
            return "mlb"
        if sport == "nhl":
            return "nhl"
        if sport == "soccer":
            return "eng.1"
        return ""

    def _fetch_espn_live(self, team: dict) -> list:
        league = self._espn_league_for(team)
        if not league:
            return []
        sport_path = team.get("espn_sport", "soccer")
        try:
            resp = requests.get(
                f"{ESPN_BASE}/{sport_path}/{league}/scoreboard",
                timeout=8,
            )
            if resp.status_code != 200:
                return []
            events = resp.json().get("events", [])
            keywords = [k.lower() for k in team.get("keywords", [team["name"].lower()])]
            matches = []
            for ev in events:
                for comp in ev.get("competitions", []):
                    names = [
                        c.get("team", {}).get("displayName", "").lower()
                        for c in comp.get("competitors", [])
                    ]
                    if any(kw in n for kw in keywords for n in names):
                        matches.append({"event": ev, "competition": comp})
            return matches
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Sports] ESPN fetch error: {e!r}")
            return []

    def _fetch_cricket_live(self, api_key: str, team: dict) -> list:
        keywords = [k.lower() for k in team.get("keywords", [team["name"].lower()])]
        try:
            resp = requests.get(
                CRIC_BASE,
                params={"apikey": api_key, "offset": 0},
                timeout=8,
            )
            if resp.status_code != 200:
                return []
            matches = []
            for m in resp.json().get("data", []):
                name = m.get("name", "").lower()
                teams = [t.lower() for t in m.get("teams", [])]
                if any(kw in name or any(kw in t for t in teams) for kw in keywords):
                    matches.append(m)
            return matches
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Sports] CricAPI fetch error: {e!r}")
            return []

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_follow(self, text: str, data: dict):
        extracted = self._extract_team(text)
        name = extracted.get("name", "").strip()
        sport = extracted.get("sport", "other").lower()
        league_hint = extracted.get("league", "").lower()

        if not name:
            await self.capability_worker.speak(
                "I didn't catch which team you want to follow. Try saying 'follow Manchester United' or 'follow Pakistan cricket'."
            )
            return

        existing = [t for t in data.get("followed_teams", []) if t["name"].lower() == name.lower()]
        if existing:
            await self.capability_worker.speak(f"You're already following {name}.")
            return

        team_entry = {
            "name": name,
            "sport": sport,
            "keywords": [name.lower()],
            "api": "cricapi" if sport == "cricket" else "espn",
            "espn_league": "",
            "espn_sport": "soccer",
        }

        if sport == "cricket":
            api_key = self.capability_worker.get_api_keys("cricapi_key") or ""
            if not api_key:
                want_key = await self.capability_worker.run_confirmation_loop(
                    "Cricket alerts need a CricAPI key. Do you have one to add?"
                )
                if want_key:
                    await self.capability_worker.speak("What's your CricAPI key?")
                    key_reply = await self.capability_worker.user_response() or ""
                    key_reply = key_reply.strip().replace(" ", "")
                    if key_reply:
                        try:
                            self.capability_worker.create_key("cricapi_key", {"key": key_reply})
                        except Exception:
                            self.capability_worker.update_key("cricapi_key", {"key": key_reply})
                        await self.capability_worker.speak(
                            f"Key saved. {name} added — I'll alert you for all their matches."
                        )
                    else:
                        await self.capability_worker.speak("No key added. Cricket alerts won't fire without it.")
                        return
                else:
                    await self.capability_worker.speak(
                        "No problem. Get a free key at cricapi.com and say 'follow cricket' to add it later."
                    )
                    return
            else:
                await self.capability_worker.speak(f"Got it — {name} added. I'll alert you for all their matches.")

        elif sport in ("soccer", "football"):
            league_key = ""
            for lname, (espn_sport, espn_league) in ESPN_LEAGUES.items():
                if lname in league_hint or lname in text.lower():
                    league_key = espn_league
                    team_entry["espn_sport"] = espn_sport
                    break
            if not league_key:
                await self.capability_worker.speak(
                    f"Which league does {name} play in? Say Premier League, La Liga, Bundesliga, MLS, or another."
                )
                league_reply = (await self.capability_worker.user_response() or "").lower()
                for lname, (espn_sport, espn_league) in ESPN_LEAGUES.items():
                    if lname in league_reply:
                        league_key = espn_league
                        team_entry["espn_sport"] = espn_sport
                        break
                if not league_key:
                    league_key = "eng.1"
                    team_entry["espn_sport"] = "soccer"
            team_entry["espn_league"] = league_key
            await self.capability_worker.speak(f"{name} added. I'll alert you for their games.")

        else:
            espn_map = {
                "nba": ("basketball", "nba"),
                "nfl": ("football", "nfl"),
                "mlb": ("baseball", "mlb"),
                "nhl": ("hockey", "nhl"),
            }
            if sport in espn_map:
                team_entry["espn_sport"], team_entry["espn_league"] = espn_map[sport]
            await self.capability_worker.speak(f"{name} added. I'll alert you for their games.")

        data.setdefault("followed_teams", []).append(team_entry)
        self._save_data(data)
        self.worker.editor_logging_handler.info(f"[Sports] Followed: {name} ({sport})")

    async def _handle_unfollow(self, text: str, data: dict):
        teams = data.get("followed_teams", [])
        if not teams:
            await self.capability_worker.speak("You're not following any teams yet.")
            return

        extracted = self._extract_team(text)
        name = extracted.get("name", "").strip().lower()
        match = next((t for t in teams if name in t["name"].lower() or t["name"].lower() in name), None)

        if not match:
            names = ", ".join(t["name"] for t in teams)
            await self.capability_worker.speak(
                f"I couldn't find that team. You're currently following: {names}."
            )
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Remove {match['name']} from your followed teams?"
        )
        if confirmed:
            data["followed_teams"] = [t for t in teams if t["name"] != match["name"]]
            self._save_data(data)
            await self.capability_worker.speak(f"{match['name']} removed.")
        else:
            await self.capability_worker.speak("No changes made.")

    async def _handle_live(self, data: dict):
        teams = data.get("followed_teams", [])
        if not teams:
            await self.capability_worker.speak(
                "You're not following any teams yet. Say 'follow' and a team name to get started."
            )
            return

        found_any = False
        for team in teams:
            if team.get("api") == "cricapi":
                api_key = self.capability_worker.get_api_keys("cricapi_key") or ""
                if not api_key:
                    continue
                matches = self._fetch_cricket_live(api_key, team)
                for m in matches:
                    found_any = True
                    score_parts = []
                    for s in m.get("score", []):
                        score_parts.append(f"{s.get('inning','')}: {s.get('r',0)}/{s.get('w',0)} off {s.get('o',0)} overs")
                    score_str = " | ".join(score_parts) if score_parts else "no score yet"
                    " vs ".join(m.get("teams", ["Team A", "Team B"]))
                    summary = self.capability_worker.text_to_text_response(
                        LIVE_SCORE_PROMPT.format(
                            sport="cricket",
                            team_a=m.get("teams", [""])[0],
                            team_b=m.get("teams", ["", ""])[1] if len(m.get("teams", [])) > 1 else "",
                            score=score_str,
                            context=m.get("status", "in progress"),
                        )
                    )
                    await self.capability_worker.speak(summary)

            else:
                matches = self._fetch_espn_live(team)
                for item in matches:
                    found_any = True
                    comp = item["competition"]
                    competitors = comp.get("competitors", [])
                    team_a = competitors[0].get("team", {}).get("displayName", "Team A") if competitors else "Team A"
                    team_b = competitors[1].get("team", {}).get("displayName", "Team B") if len(competitors) > 1 else "Team B"
                    score_a = competitors[0].get("score", "0") if competitors else "0"
                    score_b = competitors[1].get("score", "0") if len(competitors) > 1 else "0"
                    status = comp.get("status", {})
                    clock = status.get("displayClock", "")
                    period = status.get("period", 1)
                    context = f"Period/half {period}, {clock} remaining" if clock else f"Period {period}"
                    summary = self.capability_worker.text_to_text_response(
                        LIVE_SCORE_PROMPT.format(
                            sport=team.get("sport", "sports"),
                            team_a=team_a,
                            team_b=team_b,
                            score=f"{team_a} {score_a} - {score_b} {team_b}",
                            context=context,
                        )
                    )
                    await self.capability_worker.speak(summary)

        if not found_any:
            names = ", ".join(t["name"] for t in teams)
            await self.capability_worker.speak(
                f"No live games right now for {names}. Try asking about their schedule."
            )

    async def _handle_schedule(self, data: dict):
        teams = data.get("followed_teams", [])
        if not teams:
            await self.capability_worker.speak(
                "You're not following any teams yet. Say 'follow' and a team name to get started."
            )
            return

        upcoming = []
        for team in teams:
            if team.get("api") == "espn":
                sport = team.get("espn_sport", "soccer")
                league = team.get("espn_league", "eng.1")
                keywords = [k.lower() for k in team.get("keywords", [team["name"].lower()])]
                for delta in range(4):
                    check_date = (datetime.now() + timedelta(days=delta)).strftime("%Y%m%d")
                    try:
                        resp = requests.get(
                            f"{ESPN_BASE}/{sport}/{league}/scoreboard",
                            params={"dates": check_date},
                            timeout=8,
                        )
                        if resp.status_code != 200:
                            continue
                        found = False
                        for ev in resp.json().get("events", []):
                            for comp in ev.get("competitions", []):
                                names = [
                                    c.get("team", {}).get("displayName", "").lower()
                                    for c in comp.get("competitors", [])
                                ]
                                if any(kw in n for kw in keywords for n in names):
                                    state = comp.get("status", {}).get("type", {}).get("state", "")
                                    if state == "pre":
                                        date_display = ev.get("date", "")[:10]
                                        competitor_names = [
                                            c.get("team", {}).get("displayName", "?")
                                            for c in comp.get("competitors", [])
                                        ]
                                        upcoming.append(f"{' vs '.join(competitor_names)} on {date_display}")
                                        found = True
                        if found:
                            break
                    except Exception as e:
                        self.worker.editor_logging_handler.error(f"[Sports] Schedule fetch error: {e!r}")

        if upcoming:
            summary = self.capability_worker.text_to_text_response(
                SCHEDULE_PROMPT.format(games="; ".join(upcoming[:5]))
            )
            await self.capability_worker.speak(summary)
        else:
            names = ", ".join(t["name"] for t in teams)
            await self.capability_worker.speak(
                f"No games scheduled for {names} in the next few days."
            )

    async def _handle_results(self, data: dict):
        teams = data.get("followed_teams", [])
        if not teams:
            await self.capability_worker.speak("You're not following any teams yet.")
            return

        results = []
        for team in teams:
            if team.get("api") == "espn":
                sport = team.get("espn_sport", "soccer")
                league = team.get("espn_league", "eng.1")
                keywords = [k.lower() for k in team.get("keywords", [team["name"].lower()])]
                for delta in range(4):
                    check_date = (datetime.now() - timedelta(days=delta)).strftime("%Y%m%d")
                    try:
                        resp = requests.get(
                            f"{ESPN_BASE}/{sport}/{league}/scoreboard",
                            params={"dates": check_date},
                            timeout=8,
                        )
                        if resp.status_code != 200:
                            continue
                        found = False
                        for ev in resp.json().get("events", []):
                            for comp in ev.get("competitions", []):
                                names_lower = [
                                    c.get("team", {}).get("displayName", "").lower()
                                    for c in comp.get("competitors", [])
                                ]
                                if any(kw in n for kw in keywords for n in names_lower):
                                    state = comp.get("status", {}).get("type", {}).get("state", "")
                                    if state == "post":
                                        competitors = comp.get("competitors", [])
                                        team_a = competitors[0].get("team", {}).get("displayName", "?") if competitors else "?"
                                        team_b = competitors[1].get("team", {}).get("displayName", "?") if len(competitors) > 1 else "?"
                                        score_a = competitors[0].get("score", "?") if competitors else "?"
                                        score_b = competitors[1].get("score", "?") if len(competitors) > 1 else "?"
                                        winner = next(
                                            (c.get("team", {}).get("displayName", "")
                                             for c in competitors if c.get("winner")), ""
                                        )
                                        result_str = f"{team_a} {score_a} - {score_b} {team_b}"
                                        if winner:
                                            result_str += f" ({winner} won)"
                                        results.append(result_str)
                                        found = True
                        if found:
                            break
                    except Exception as e:
                        self.worker.editor_logging_handler.error(f"[Sports] Results fetch error: {e!r}")

        if results:
            await self.capability_worker.speak(
                "Recent results: " + ". ".join(results[:3]) + "."
            )
        else:
            names = ", ".join(t["name"] for t in teams)
            await self.capability_worker.speak(
                f"No completed games found for {names} in the past few days."
            )

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[Sports] Trigger: {trigger!r}")

            data = self._load_data()
            intent = self._classify_intent(trigger or "")
            self.worker.editor_logging_handler.info(f"[Sports] Intent: {intent}")

            if intent == "EXIT" or (trigger and self._is_exit(trigger)):
                await self.capability_worker.speak("Enjoy the game.")
                return

            await self._dispatch(intent, trigger or "", data)

            await self.capability_worker.speak(
                "What else — score, schedule, results, or done?"
            )

            while True:
                reply = await self.capability_worker.user_response()
                if not reply or self._is_exit(reply):
                    break
                # Use in-memory data — _handle_follow/_handle_unfollow mutate it in-place.
                # Re-reading from storage within the same session returns stale data
                # because newly create_key'd entries aren't visible to get_single_key.
                intent = self._classify_intent(reply)
                if intent == "EXIT":
                    break
                await self._dispatch(intent, reply, data)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Sports] Error: {e!r}")
            await self.capability_worker.speak("Something went wrong. Please try again.")
        finally:
            self.capability_worker.resume_normal_flow()

    async def _dispatch(self, intent: str, text: str, data: dict):
        if intent == "FOLLOW":
            await self._handle_follow(text, data)
        elif intent == "UNFOLLOW":
            await self._handle_unfollow(text, data)
        elif intent == "LIVE":
            await self._handle_live(data)
        elif intent == "SCHEDULE":
            await self._handle_schedule(data)
        elif intent == "RESULTS":
            await self._handle_results(data)
