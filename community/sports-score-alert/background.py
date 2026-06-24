import requests
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "sports_score_data"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
CRIC_BASE = "https://api.cricapi.com/v1/currentMatches"

POLL_LIVE = 60.0
POLL_PREMATCH = 300.0
POLL_IDLE = 1800.0

STARTUP_GRACE = 90
PRE_MATCH_MINUTES = 30
COMEBACK_THRESHOLD = 10

ALERT_PROMPT = (
    "Write a short exciting 1-2 sentence spoken sports alert for a voice assistant. "
    "Event: {event_type}. Sport: {sport}. "
    "Teams: {team_a} vs {team_b}. Score: {score}. "
    "Context: {context}. "
    "Be specific, include the score, and mention the match situation. "
    "No markdown. Excited but not over the top. Plain English."
)


class SportsScoreAlertBackground(MatchingCapability):
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
            return {"followed_teams": [], "alert_prefs": {}, "fired_alerts": []}
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SportsBG] Load error: {e!r}")
            return {"followed_teams": [], "alert_prefs": {}, "fired_alerts": []}

    def _save_data(self, data: dict):
        try:
            self.capability_worker.create_key(STORAGE_KEY, data)
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, data)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[SportsBG] Save error: {e!r}")

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _already_fired(self, data: dict, game_id: str, alert_type: str) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        return any(
            a.get("game_id") == game_id
            and a.get("date") == today
            and a.get("alert_type") == alert_type
            for a in data.get("fired_alerts", [])
        )

    def _mark_fired(self, data: dict, game_id: str, alert_type: str):
        today = datetime.now().strftime("%Y-%m-%d")
        data.setdefault("fired_alerts", []).append(
            {"game_id": game_id, "date": today, "alert_type": alert_type}
        )
        cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        data["fired_alerts"] = [
            a for a in data["fired_alerts"] if a.get("date", "") >= cutoff
        ]

    # ------------------------------------------------------------------
    # Alert composition
    # ------------------------------------------------------------------

    def _compose_alert(
        self, event_type: str, sport: str, team_a: str, team_b: str, score: str, context: str
    ) -> str:
        return self.capability_worker.text_to_text_response(
            ALERT_PROMPT.format(
                event_type=event_type,
                sport=sport,
                team_a=team_a,
                team_b=team_b,
                score=score,
                context=context,
            )
        )

    # ------------------------------------------------------------------
    # ESPN helpers
    # ------------------------------------------------------------------

    def _fetch_espn_games(self, team: dict) -> list:
        sport = team.get("espn_sport", "soccer")
        league = team.get("espn_league", "eng.1")
        keywords = [k.lower() for k in team.get("keywords", [team["name"].lower()])]
        try:
            resp = requests.get(
                f"{ESPN_BASE}/{sport}/{league}/scoreboard",
                timeout=8,
            )
            if resp.status_code != 200:
                return []
            games = []
            for ev in resp.json().get("events", []):
                for comp in ev.get("competitions", []):
                    names = [
                        c.get("team", {}).get("displayName", "").lower()
                        for c in comp.get("competitors", [])
                    ]
                    if any(kw in n for kw in keywords for n in names):
                        competitors = comp.get("competitors", [])
                        games.append({
                            "id": f"espn_{ev.get('id', '')}",
                            "sport": team.get("sport", sport),
                            "team_a": competitors[0].get("team", {}).get("displayName", "Team A") if competitors else "Team A",
                            "team_b": competitors[1].get("team", {}).get("displayName", "Team B") if len(competitors) > 1 else "Team B",
                            "score_a": competitors[0].get("score", "0") if competitors else "0",
                            "score_b": competitors[1].get("score", "0") if len(competitors) > 1 else "0",
                            "state": comp.get("status", {}).get("type", {}).get("state", "pre"),
                            "clock": comp.get("status", {}).get("displayClock", ""),
                            "period": comp.get("status", {}).get("period", 1),
                            "date": ev.get("date", ""),
                            "winner": next(
                                (c.get("team", {}).get("displayName", "")
                                 for c in competitors if c.get("winner")), ""
                            ),
                            "detail": comp.get("status", {}).get("type", {}).get("detail", ""),
                        })
            return games
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SportsBG] ESPN fetch error: {e!r}")
            return []

    # ------------------------------------------------------------------
    # CricAPI helpers
    # ------------------------------------------------------------------

    def _fetch_cricket_games(self, team: dict, api_key: str) -> list:
        keywords = [k.lower() for k in team.get("keywords", [team["name"].lower()])]
        try:
            resp = requests.get(
                CRIC_BASE,
                params={"apikey": api_key, "offset": 0},
                timeout=8,
            )
            if resp.status_code != 200:
                return []
            games = []
            for m in resp.json().get("data", []):
                name = m.get("name", "").lower()
                teams = m.get("teams", [])
                teams_lower = [t.lower() for t in teams]
                if not any(kw in name or any(kw in t for t in teams_lower) for kw in keywords):
                    continue

                score_parts = []
                for s in m.get("score", []):
                    score_parts.append(
                        f"{s.get('inning','')}: {s.get('r',0)}/{s.get('w',0)} ({s.get('o',0)} ov)"
                    )
                score_str = " | ".join(score_parts) if score_parts else "yet to bat"

                status = m.get("status", "").lower()
                if "won" in status or "tied" in status or "draw" in status:
                    state = "post"
                elif "progress" in status or "innings" in status:
                    state = "in"
                else:
                    state = "pre"

                games.append({
                    "id": f"cric_{m.get('id', '')}",
                    "sport": "cricket",
                    "team_a": teams[0] if teams else "Team A",
                    "team_b": teams[1] if len(teams) > 1 else "Team B",
                    "score_a": score_str,
                    "score_b": "",
                    "state": state,
                    "clock": "",
                    "period": 1,
                    "date": m.get("dateTimeGMT", ""),
                    "winner": m.get("status", ""),
                    "detail": m.get("matchType", ""),
                })
            return games
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SportsBG] CricAPI fetch error: {e!r}")
            return []

    # ------------------------------------------------------------------
    # Game evaluation
    # ------------------------------------------------------------------

    def _evaluate_game(self, game: dict, team: dict, data: dict) -> tuple:
        alerts = []
        game_id = game["id"]
        state = game["state"]
        sport = game.get("sport", "")
        team_a = game["team_a"]
        team_b = game["team_b"]
        score_a = game["score_a"]
        score_b = game["score_b"]
        sleep_time = POLL_IDLE
        prefs = data.get("alert_prefs", {})
        comeback_threshold = int(prefs.get("comeback_threshold", COMEBACK_THRESHOLD))

        if state == "pre":
            date_str = game.get("date", "")
            if date_str:
                try:
                    game_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    now_utc = datetime.now().astimezone()
                    minutes_until = (game_time - now_utc).total_seconds() / 60
                    if 0 <= minutes_until <= PRE_MATCH_MINUTES:
                        sleep_time = POLL_PREMATCH
                        if not self._already_fired(data, game_id, "pre_match"):
                            context = f"kicks off in {int(minutes_until)} minutes"
                            msg = self._compose_alert(
                                "pre-match countdown", sport, team_a, team_b,
                                "not started yet", context
                            )
                            alerts.append(("pre_match", msg))
                    elif minutes_until <= 120:
                        sleep_time = POLL_PREMATCH
                except Exception:
                    pass

        elif state == "in":
            sleep_time = POLL_LIVE
            score_key = f"score_{score_a}-{score_b}"
            if not self._already_fired(data, game_id, "game_start"):
                context = f"{game.get('detail', 'match in progress')}"
                msg = self._compose_alert(
                    "game start", sport, team_a, team_b,
                    f"{team_a} 0 - 0 {team_b}", context
                )
                alerts.append(("game_start", msg))

            if score_b and not self._already_fired(data, game_id, score_key):
                try:
                    a_val = float(score_a) if score_a.replace(".", "").isdigit() else 0
                    b_val = float(score_b) if score_b.replace(".", "").isdigit() else 0
                    leader = team_a if a_val > b_val else team_b if b_val > a_val else "level"
                    diff = abs(a_val - b_val)
                    context = (
                        f"{game.get('clock', '')} remaining, period {game.get('period', 1)}"
                        if game.get("clock") else game.get("detail", "in progress")
                    )
                    msg = self._compose_alert(
                        "score update", sport, team_a, team_b,
                        f"{team_a} {score_a} - {score_b} {team_b}",
                        f"{leader} leading by {diff:.0f}, {context}" if diff else f"level at {score_a}, {context}",
                    )
                    alerts.append((score_key, msg))

                    # Comeback detection
                    if diff >= comeback_threshold and not self._already_fired(
                        data, game_id, f"comeback_{score_key}"
                    ):
                        trailing = team_b if a_val > b_val else team_a
                        comeback_context = (
                            f"{trailing} closing the gap — now only {diff:.0f} behind"
                        )
                        comeback_msg = self._compose_alert(
                            "comeback", sport, team_a, team_b,
                            f"{team_a} {score_a} - {score_b} {team_b}",
                            comeback_context,
                        )
                        alerts.append((f"comeback_{score_key}", comeback_msg))
                except (ValueError, TypeError):
                    pass

            period = game.get("period", 1)
            detail = game.get("detail", "").lower()
            if ("halftime" in detail or "half time" in detail) and not self._already_fired(
                data, game_id, f"halftime_p{period}"
            ):
                ht_msg = self._compose_alert(
                    "halftime", sport, team_a, team_b,
                    f"{team_a} {score_a} - {score_b} {team_b}",
                    "half-time whistle",
                )
                alerts.append((f"halftime_p{period}", ht_msg))

        elif state == "post":
            final_key = "final"
            if not self._already_fired(data, game_id, final_key):
                winner = game.get("winner", "")
                context = f"{winner} win" if winner else "full time"
                msg = self._compose_alert(
                    "final result", sport, team_a, team_b,
                    f"{team_a} {score_a} - {score_b} {team_b}",
                    context,
                )
                alerts.append((final_key, msg))

        return alerts, sleep_time

    # ------------------------------------------------------------------
    # Daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        self.capability_worker.resume_normal_flow()
        self.worker.editor_logging_handler.info("[SportsBG] Daemon started")
        started_at = datetime.now().timestamp()

        while True:
            try:
                daemon_age = datetime.now().timestamp() - started_at
                if daemon_age <= STARTUP_GRACE:
                    await self.worker.session_tasks.sleep(POLL_IDLE)
                    continue

                data = self._load_data()
                followed = data.get("followed_teams", [])

                if not followed:
                    await self.worker.session_tasks.sleep(POLL_IDLE)
                    continue

                sleep_time = POLL_IDLE
                changed = False
                cric_key = self.capability_worker.get_api_keys("cricapi_key") or ""

                for team in followed:
                    api = team.get("api", "espn")
                    if api == "espn":
                        games = self._fetch_espn_games(team)
                    elif api == "cricapi":
                        if not cric_key:
                            continue
                        games = self._fetch_cricket_games(team, cric_key)
                    else:
                        continue

                    for game in games:
                        pending_alerts, game_sleep = self._evaluate_game(game, team, data)
                        sleep_time = min(sleep_time, game_sleep)
                        for alert_type, msg in pending_alerts:
                            if not self._already_fired(data, game["id"], alert_type):
                                await self.capability_worker.send_interrupt_signal()
                                await self.capability_worker.speak(msg)
                                self._mark_fired(data, game["id"], alert_type)
                                changed = True

                if changed:
                    self._save_data(data)

                self.worker.editor_logging_handler.info(
                    f"[SportsBG] Poll done — next check in {sleep_time:.0f}s"
                )

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[SportsBG] Loop error: {e!r}")
                sleep_time = POLL_IDLE

            await self.worker.session_tasks.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.background_daemon_mode = background_daemon_mode
        self.worker.session_tasks.create(self.watch_loop())
