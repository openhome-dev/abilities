from __future__ import annotations

import unittest

from mta_next_train_core import (
    ACTION_ARRIVALS,
    ACTION_SET_DEFAULT,
    fetch_arrivals,
    find_station_matches,
    format_arrivals_for_voice,
    parse_query_intent,
    station_from_api_item,
)
from tests.fixtures import SAMPLE_ARRIVALS_RESPONSE, SAMPLE_STATIONS


class MTANextTrainCoreTests(unittest.TestCase):
    def setUp(self):
        self.stations = [station_from_api_item(item) for item in SAMPLE_STATIONS]

    def test_parse_default_station_command(self):
        intent = parse_query_intent("set my default station to astor place")
        self.assertEqual(intent.action, ACTION_SET_DEFAULT)
        self.assertEqual(intent.station_text, "astor place")

    def test_parse_arrivals_command(self):
        intent = parse_query_intent("when is the next northbound 6 train at astor place")
        self.assertEqual(intent.action, ACTION_ARRIVALS)
        self.assertEqual(intent.direction, "N")
        self.assertEqual(intent.routes, ["6"])
        self.assertEqual(intent.station_text, "astor place")

    def test_station_match(self):
        matches = find_station_matches(self.stations, "14 street union square")
        self.assertEqual(matches[0].station.name, "14 St-Union Sq")

    def test_fixture_end_to_end(self):
        station = find_station_matches(self.stations, "astor place", limit=1)[0].station
        import mta_next_train_core
        original_fetch_json = mta_next_train_core.fetch_json
        try:
            mta_next_train_core.fetch_json = lambda url, timeout=12: SAMPLE_ARRIVALS_RESPONSE
            arrivals = fetch_arrivals(station.station_id, routes=["6"], direction=None)
        finally:
            mta_next_train_core.fetch_json = original_fetch_json
        self.assertEqual([arrival.route_id for arrival in arrivals[:3]], ["6", "6", "6"])
        spoken = format_arrivals_for_voice(
            station,
            arrivals,
            routes=["6"],
            direction=None,
        )
        self.assertIn("Astor Pl", spoken)
        self.assertIn("northbound 6 in now", spoken)
        self.assertIn("southbound 6 in 3 minutes", spoken)


if __name__ == "__main__":
    unittest.main()
