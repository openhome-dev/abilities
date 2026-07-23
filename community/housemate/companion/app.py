"""
HouseMate companion dashboard.
Run: pip install flask flask-cors
     python companion/app.py
Then set DASHBOARD_URL in main.py to http://YOUR_HOST:8080
"""

from collections import deque
import time

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder=".")
CORS(app)

STATE = {
    "session_id": None,
    "last_update": None,
    "last_event": None,
    "last_action": None,
    "weather": {},
    "prayer": {},
    "brief": "",
    "contacts": {},
    "plans": [],
    "reminders": [],
    "sos_sent_to": [],
    "sos_ok": False,
    "last_email_to": None,
    "last_email_ok": False,
}
HISTORY = deque(maxlen=100)


@app.route("/api/housemate/<event>", methods=["POST"])
def ingest(event):
    payload = request.get_json(silent=True) or {}
    print(f"[housemate/{event}] {payload.get('session_id', '?')} keys={list(payload.keys())}")
    STATE["last_update"] = time.time()
    STATE["last_event"] = event
    STATE["session_id"] = payload.get("session_id", STATE["session_id"])
    for key, val in payload.items():
        if isinstance(val, dict) and isinstance(STATE.get(key), dict):
            STATE[key].update(val)
        else:
            STATE[key] = val
    if event in ("update", "session_start"):
        HISTORY.append({"event": event, **payload})
    return jsonify({"ok": True})


@app.route("/api/state")
def get_state():
    return jsonify(STATE)


@app.route("/api/history")
def get_history():
    return jsonify(list(HISTORY))


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
