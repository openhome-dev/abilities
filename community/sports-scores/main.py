import json
import re

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# SPORTS SCORES & STANDINGS
# Fetches sports scores, recent results, upcoming games, and league standings
# using TheSportsDB free API (test key "3"). Supports multi-turn conversation.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

SPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"

INTENT_PROMPT = (
    "Classify this sports request. Return ONLY valid JSON.\n"
    'Format: {{"intent": "recent|upcoming|standings|search", "team": "<team name>"}}\n'
    "Rules:\n"
    "- 'score', 'won', 'lost', 'last game', 'recent results' -> recent\n"
    "- 'next game', 'upcoming', 'schedule', 'playing next' -> upcoming\n"
    "- 'standings', 'table', 'league', 'rankings', 'position' -> standings\n"
    "- general team question -> search\n"
    "Extract the team name. If no team mentioned, set team to empty string.\n"
    "Input: {text}"
)

SUMMARIZE_PROMPT = (
    "You are a sports commentator giving a brief voice update. "
    "Summarize this sports data in 2-3 conversational sentences. "
    "Include key scores, teams, and dates. Be enthusiastic but concise."
)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class SportsScoresCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.last_team_id = None
        self.last_team_name = None
        self.last_league_id = None
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info(
                "[SportsScores] Ability started"
            )

            await self.capability_worker.speak(
                "I can get you sports scores, upcoming games, and standings. "
                "Which team or league are you interested in?"
            )

            idle_count = 0

            for _ in range(15):
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Closing sports scores. Catch you later!"
                        )
                        break
                    await self.capability_worker.speak(
                        "I'm here. What team would you like scores for?"
                    )
                    continue

                idle_count = 0

                if any(w in user_input.lower() for w in EXIT_WORDS):
                    await self.capability_worker.speak(
                        "See you next game day! Goodbye."
                    )
                    break

                intent_data = self._classify_intent(user_input)
                intent = intent_data.get("intent", "recent")
                team_name = intent_data.get("team", "")

                if team_name:
                    team_info = self._search_team(team_name)
                    if team_info:
                        self.last_team_id = team_info["id"]
                        self.last_team_name = team_info["name"]
                        self.last_league_id = team_info.get("league_id")
                    else:
                        await self.capability_worker.speak(
                            f"I couldn't find a team called {team_name}. "
                            "Try the full team name, like Los Angeles Lakers."
                        )
                        continue

                if not self.last_team_id:
                    team_input = await self.capability_worker.run_io_loop(
                        "Which team are you interested in?"
                    )
                    if not team_input or any(
                        w in team_input.lower() for w in EXIT_WORDS
                    ):
                        await self.capability_worker.speak("Goodbye!")
                        break
                    team_info = self._search_team(team_input.strip())
                    if team_info:
                        self.last_team_id = team_info["id"]
                        self.last_team_name = team_info["name"]
                        self.last_league_id = team_info.get("league_id")
                    else:
                        await self.capability_worker.speak(
                            "I couldn't find that team. Try again?"
                        )
                        continue

                if intent == "recent":
                    await self._handle_recent()
                elif intent == "upcoming":
                    await self._handle_upcoming()
                elif intent == "standings":
                    await self._handle_standings()
                else:
                    await self._handle_recent()

                await self.capability_worker.speak(
                    "Want scores for another team or more info?"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SportsScores] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing sports scores."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[SportsScores] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _classify_intent(self, text: str) -> dict:
        lower = text.lower()

        if any(w in lower for w in ("standing", "table", "ranking", "position")):
            return {"intent": "standings", "team": self._extract_team_keyword(text)}
        if any(w in lower for w in ("next", "upcoming", "schedule", "playing next")):
            return {"intent": "upcoming", "team": self._extract_team_keyword(text)}
        if any(w in lower for w in ("score", "won", "lost", "last", "recent", "result")):
            return {"intent": "recent", "team": self._extract_team_keyword(text)}

        try:
            raw = self.capability_worker.text_to_text_response(
                INTENT_PROMPT.format(text=text)
            )
            return json.loads(_strip_json_fences(raw))
        except (json.JSONDecodeError, Exception) as e:
            self.worker.editor_logging_handler.error(
                f"[SportsScores] Intent error: {e}"
            )
            return {"intent": "recent", "team": text.strip()}

    def _extract_team_keyword(self, text: str) -> str:
        try:
            result = self.capability_worker.text_to_text_response(
                f"Extract the sports team name from this text. "
                f"Return ONLY the team name, nothing else. "
                f"If no team mentioned, return empty string. Input: {text}"
            )
            cleaned = result.strip().strip('"').strip("'")
            if cleaned and len(cleaned) < 100:
                return cleaned
        except Exception:
            pass
        return ""

    def _search_team(self, name: str) -> dict:
        try:
            resp = requests.get(
                f"{SPORTSDB_BASE}/searchteams.php",
                params={"t": name},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                teams = data.get("teams")
                if teams and len(teams) > 0:
                    team = teams[0]
                    return {
                        "id": team.get("idTeam"),
                        "name": team.get("strTeam"),
                        "league_id": team.get("idLeague"),
                        "league": team.get("strLeague"),
                        "sport": team.get("strSport"),
                    }
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SportsScores] Team search error: {e}"
            )
        return None

    async def _handle_recent(self):
        try:
            resp = requests.get(
                f"{SPORTSDB_BASE}/eventslast.php",
                params={"id": self.last_team_id},
                timeout=5,
            )
            if resp.status_code != 200:
                await self.capability_worker.speak(
                    "I couldn't fetch recent results right now."
                )
                return

            data = resp.json()
            events = data.get("results")
            if not events:
                await self.capability_worker.speak(
                    f"No recent results found for {self.last_team_name}."
                )
                return

            events_summary = []
            for e in events[:5]:
                events_summary.append({
                    "home": e.get("strHomeTeam", ""),
                    "away": e.get("strAwayTeam", ""),
                    "home_score": e.get("intHomeScore", ""),
                    "away_score": e.get("intAwayScore", ""),
                    "date": e.get("dateEvent", ""),
                    "league": e.get("strLeague", ""),
                })

            summary = self._voice_summarize(
                f"Recent results for {self.last_team_name}",
                events_summary,
            )
            await self.capability_worker.speak(summary)

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SportsScores] Recent results error: {e}"
            )
            await self.capability_worker.speak(
                "I had trouble fetching recent results."
            )

    async def _handle_upcoming(self):
        try:
            resp = requests.get(
                f"{SPORTSDB_BASE}/eventsnext.php",
                params={"id": self.last_team_id},
                timeout=5,
            )
            if resp.status_code != 200:
                await self.capability_worker.speak(
                    "I couldn't fetch upcoming games right now."
                )
                return

            data = resp.json()
            events = data.get("events")
            if not events:
                await self.capability_worker.speak(
                    f"No upcoming games found for {self.last_team_name}."
                )
                return

            events_summary = []
            for e in events[:5]:
                events_summary.append({
                    "home": e.get("strHomeTeam", ""),
                    "away": e.get("strAwayTeam", ""),
                    "date": e.get("dateEvent", ""),
                    "time": e.get("strTime", ""),
                    "league": e.get("strLeague", ""),
                })

            summary = self._voice_summarize(
                f"Upcoming games for {self.last_team_name}",
                events_summary,
            )
            await self.capability_worker.speak(summary)

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SportsScores] Upcoming games error: {e}"
            )
            await self.capability_worker.speak(
                "I had trouble fetching upcoming games."
            )

    async def _handle_standings(self):
        if not self.last_league_id:
            await self.capability_worker.speak(
                "I don't have league information for this team to show standings."
            )
            return

        try:
            from datetime import datetime
            season = str(datetime.now().year)

            resp = requests.get(
                f"{SPORTSDB_BASE}/lookuptable.php",
                params={"l": self.last_league_id, "s": season},
                timeout=5,
            )
            if resp.status_code != 200:
                await self.capability_worker.speak(
                    "I couldn't fetch standings right now."
                )
                return

            data = resp.json()
            table = data.get("table")
            if not table:
                resp2 = requests.get(
                    f"{SPORTSDB_BASE}/lookuptable.php",
                    params={
                        "l": self.last_league_id,
                        "s": str(int(season) - 1),
                    },
                    timeout=5,
                )
                if resp2.status_code == 200:
                    table = resp2.json().get("table")

            if not table:
                await self.capability_worker.speak(
                    "I couldn't find standings for this league and season."
                )
                return

            standings_summary = []
            for entry in table[:10]:
                standings_summary.append({
                    "position": entry.get("intRank", ""),
                    "team": entry.get("strTeam", ""),
                    "played": entry.get("intPlayed", ""),
                    "wins": entry.get("intWin", ""),
                    "draws": entry.get("intDraw", ""),
                    "losses": entry.get("intLoss", ""),
                    "points": entry.get("intPoints", ""),
                })

            summary = self._voice_summarize(
                "League standings", standings_summary
            )
            await self.capability_worker.speak(summary)

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SportsScores] Standings error: {e}"
            )
            await self.capability_worker.speak(
                "I had trouble fetching standings."
            )

    def _voice_summarize(self, context: str, data: list) -> str:
        data_text = json.dumps(data, indent=2)
        prompt = f"{context}:\n{data_text}"
        try:
            response = self.capability_worker.text_to_text_response(
                prompt, system_prompt=SUMMARIZE_PROMPT
            )
            return response
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[SportsScores] Summary error: {e}"
            )
            return f"I found data for {context} but had trouble summarizing it."
