import json
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# ==========================================================
# RapidAPI – Cricbuzz Cricket API
# ==========================================================
# 👉 Get your API key from:
# https://rapidapi.com/cricketapilive/api/cricbuzz-cricket
#
# IMPORTANT:
# - OpenHome does NOT allow editable config.json
# - Environment variables are NOT supported
# - Hardcode key ONLY for demo/testing
# - REMOVE before publishing
# ==========================================================

RAPIDAPI_KEY = "5741ec984cmshbe03b0e4ecbfc8fp1bff73jsnbe07d84e8795"
RAPIDAPI_HOST = "cricbuzz-cricket.p.rapidapi.com"


class LiveCricketScoresCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    async def first_function(self):
        if not RAPIDAPI_KEY:
            await self.capability_worker.speak(
                "Live cricket scores are not configured yet."
            )
            self.capability_worker.resume_normal_flow()
            return

        await self.capability_worker.speak(
            "Checking live cricket matches now."
        )

        summary = self.get_live_matches_summary()
        await self.capability_worker.speak(summary)

        self.capability_worker.resume_normal_flow()

    def get_live_matches_summary(self) -> str:
        url = f"https://{RAPIDAPI_HOST}/matches/v1/live"

        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": RAPIDAPI_HOST,
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return (
                "Sorry, I couldn’t fetch live cricket scores right now. "
                "Please try again shortly."
            )

        matches = []

        for type_block in data.get("typeMatches", []):
            for series in type_block.get("seriesMatches", []):
                wrapper = series.get("seriesAdWrapper")
                if not wrapper:
                    continue

                for match in wrapper.get("matches", []):
                    info = match.get("matchInfo", {})
                    team1 = info.get("team1", {}).get("teamName")
                    team2 = info.get("team2", {}).get("teamName")
                    status = info.get("status")

                    if team1 and team2 and status:
                        matches.append(
                            f"{team1} versus {team2}. {status}"
                        )

        if not matches:
            return "There are no live cricket matches at the moment."

        return f"Live match update: {matches[0]}"

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.first_function())