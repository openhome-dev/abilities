#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))

from mta_next_train_core import (
    fetch_arrivals,
    find_station_matches,
    format_arrivals_for_voice,
    parse_query_intent,
    search_stations,
    station_from_api_item,
)
from tests.fixtures import SAMPLE_ARRIVALS_RESPONSE, SAMPLE_STATIONS


def run_fixture_mode(phrase: str) -> int:
    stations = [station_from_api_item(item) for item in SAMPLE_STATIONS]
    intent = parse_query_intent(phrase)
    station_query = intent.station_text or "Astor Place"
    matches = find_station_matches(stations, station_query, limit=1)
    if not matches:
        print("No station match")
        return 1
    station = matches[0].station
    import mta_next_train_core
    original_fetch_json = mta_next_train_core.fetch_json
    try:
        mta_next_train_core.fetch_json = lambda url, timeout=12: SAMPLE_ARRIVALS_RESPONSE
        arrivals = fetch_arrivals(station.station_id, intent.routes, intent.direction)
    finally:
        mta_next_train_core.fetch_json = original_fetch_json
    print(format_arrivals_for_voice(station, arrivals, intent.routes, intent.direction))
    return 0


def run_live_mode(phrase: str) -> int:
    intent = parse_query_intent(phrase)
    station_query = intent.station_text
    if not station_query:
        print("Live mode needs a station in the phrase, e.g. 'next Q train at Union Square'")
        return 1
    stations = search_stations(station_query, limit=5)
    matches = find_station_matches(stations, station_query, limit=1)
    if not matches:
        print("No station match")
        return 1
    station = matches[0].station
    arrivals = fetch_arrivals(station.station_id, intent.routes, intent.direction)
    print(format_arrivals_for_voice(station, arrivals, intent.routes, intent.direction))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phrase", required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    if args.live:
        return run_live_mode(args.phrase)
    return run_fixture_mode(args.phrase)


if __name__ == "__main__":
    raise SystemExit(main())
