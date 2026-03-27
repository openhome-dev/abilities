import os
import sys
from typing import Dict, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

from mta_next_train_core import (
    ACTION_HELP,
    ACTION_SET_DEFAULT,
    QueryIntent,
    Station,
    fetch_arrivals,
    find_station_matches,
    format_arrivals_for_voice,
    parse_query_intent,
    search_stations,
    station_from_prefs,
)


PREFS_KEY = "mta_next_train_prefs"
EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "nothing else",
}


class MTANextTrainCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    prefs: Dict = None

    #{{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.prefs = self.load_prefs()
            trigger_text = self.get_trigger_text()
            if not trigger_text:
                trigger_text = await self.capability_worker.run_io_loop(
                    "What would you like to check? You can say, when is my next train, or set my default station to Astor Place."
                )
            if not trigger_text:
                return

            while True:
                if self._is_exit(trigger_text):
                    await self.capability_worker.speak("Okay. Closing MTA Next Train.")
                    return

                intent = parse_query_intent(trigger_text)
                if intent.action == ACTION_HELP:
                    await self.capability_worker.speak(
                        "You can ask for your next train, ask for a specific line at a station, or set a default station. For example: when is my next train, next Q train at Union Square, or set my default station to Astor Place."
                    )
                elif intent.action == ACTION_SET_DEFAULT:
                    await self.handle_set_default(intent)
                else:
                    await self.handle_arrivals(intent)

                trigger_text = await self.capability_worker.run_io_loop(
                    "Anything else for the subway? Say another station or line, or say done."
                )
                if not trigger_text:
                    return
        except Exception as exc:
            self.worker.editor_logging_handler.error(f"[MTANextTrain] {exc}")
            await self.capability_worker.speak(
                "Something went wrong while checking live arrivals."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    def load_prefs(self) -> Dict:
        prefs = self.capability_worker.get_single_key(PREFS_KEY)
        if isinstance(prefs, dict):
            return prefs
        return {
            "default_station_id": "",
            "default_station_name": "",
            "default_station_borough": "",
            "default_station_lines": [],
        }

    def save_prefs(self):
        existing = self.capability_worker.get_single_key(PREFS_KEY)
        if existing:
            self.capability_worker.update_key(PREFS_KEY, self.prefs)
        else:
            self.capability_worker.create_key(PREFS_KEY, self.prefs)

    def get_trigger_text(self) -> str:
        history = self.capability_worker.get_full_message_history() or []
        for item in reversed(history):
            if item.get("role") == "user":
                content = (item.get("content") or "").strip()
                if content:
                    return content
        return ""

    def _is_exit(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        return any(phrase in lowered for phrase in EXIT_WORDS)

    async def handle_set_default(self, intent: QueryIntent):
        station_text = intent.station_text
        if not station_text:
            station_text = await self.capability_worker.run_io_loop(
                "Which station should I save as your default?"
            )
            if not station_text:
                return

        station = await self.resolve_station(station_text)
        if not station:
            return

        self.prefs["default_station_id"] = station.station_id
        self.prefs["default_station_name"] = station.name
        self.prefs["default_station_borough"] = station.borough
        self.prefs["default_station_lines"] = station.lines
        self.save_prefs()
        await self.capability_worker.speak(
            f"Saved {station.name} as your default station."
        )

    async def handle_arrivals(self, intent: QueryIntent):
        station = None
        if intent.station_text:
            station = await self.resolve_station(intent.station_text)
        elif self.prefs.get("default_station_id"):
            station = station_from_prefs(
                self.prefs["default_station_id"],
                self.prefs.get("default_station_name", ""),
                self.prefs.get("default_station_borough", ""),
                self.prefs.get("default_station_lines", []),
            )

        if not station:
            spoken_station = await self.capability_worker.run_io_loop(
                "Which station do you want to check? You can also say set my default station to save one."
            )
            if not spoken_station:
                return
            if self._is_exit(spoken_station):
                await self.capability_worker.speak("Okay. Closing MTA Next Train.")
                return
            station = await self.resolve_station(spoken_station)
            if not station:
                return

        await self.capability_worker.speak(f"Checking live arrivals for {station.name}.")
        arrivals = fetch_arrivals(station.station_id, intent.routes, intent.direction)
        summary = format_arrivals_for_voice(
            station,
            arrivals,
            intent.routes,
            intent.direction,
        )
        await self.capability_worker.speak(summary)

    async def resolve_station(self, station_text: str) -> Optional[Station]:
        stations = search_stations(station_text, limit=5)
        matches = find_station_matches(stations, station_text)
        if not matches:
            await self.capability_worker.speak(
                f"I could not find a subway station matching {station_text}."
            )
            return None

        top_match = matches[0]
        if len(matches) > 1 and (top_match.score - matches[1].score) < 0.08:
            options = ", ".join(match.station.name for match in matches[:3])
            response = await self.capability_worker.run_io_loop(
                f"I found a few close matches: {options}. Which one did you mean?"
            )
            if not response:
                return None
            narrowed = find_station_matches(stations, response, limit=1)
            if not narrowed:
                await self.capability_worker.speak("I still could not pin down the station.")
                return None
            return narrowed[0].station

        return top_match.station
