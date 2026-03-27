SAMPLE_STATIONS = [
    {
        "id": "636",
        "name": "Astor Pl",
        "lat": 40.730054,
        "lon": -73.99107,
        "borough": "Manhattan",
        "lines": ["4", "6"],
    },
    {
        "id": "R20",
        "name": "14 St-Union Sq",
        "lat": 40.734673,
        "lon": -73.989951,
        "borough": "Manhattan",
        "lines": ["4", "5", "6", "L", "N", "Q", "R", "W"],
    },
]

SAMPLE_ARRIVALS_RESPONSE = {
    "stationId": "636",
    "stationName": "Astor Pl",
    "arrivals": [
        {
            "line": "6",
            "direction": "N",
            "directionLabel": "Bronx-bound to Pelham Bay Park",
            "arrivalTime": "2026-03-27T21:10:30.000Z",
            "minutesAway": 0,
            "isAssigned": False,
            "headsign": "Pelham Bay Park",
        },
        {
            "line": "6",
            "direction": "S",
            "directionLabel": "to Brooklyn Bridge",
            "arrivalTime": "2026-03-27T21:12:42.000Z",
            "minutesAway": 3,
            "isAssigned": False,
            "headsign": "Brooklyn Bridge-City Hall",
        },
        {
            "line": "6",
            "direction": "N",
            "directionLabel": "Bronx-bound to Pelham Bay Park",
            "arrivalTime": "2026-03-27T21:13:19.000Z",
            "minutesAway": 3,
            "isAssigned": False,
            "headsign": "Pelham Bay Park",
        },
    ],
    "lastUpdated": "2026-03-27T21:09:08.865Z",
}
