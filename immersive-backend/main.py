"""Immersive backend + live dashboard — single-file Flask app, Replit-ready.

Serves the five endpoints the OpenHome skills call, plus POST /requests for the
intake skill, and a live dashboard at / that polls /api/state every 2 seconds.

State is an in-memory dict persisted to immersive_db.json on every mutation, so
a Replit restart loses nothing. Endpoints are tolerant per OpenHome dashboard
rules: unknown fields ignored, no 500s for missing fields, CORS wide open.
"""
import json
import os
import random
import threading
import time
import uuid

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_FILE = "immersive_db.json"
_lock = threading.Lock()

# Provider catalog: the marketplace. rating/reliability are LIVE — they move
# with every piece of feedback (rating = running average of jobs).
SEED_PROVIDERS = [
    {"name": "Rapid Plumbing Co", "category": "plumbing", "base_price": 135, "rating": 4.8, "jobs": 24, "reliability": 0.96},
    {"name": "HomeFix Solutions", "category": "plumbing", "base_price": 110, "rating": 4.4, "jobs": 31, "reliability": 0.90},
    {"name": "BlueWrench Services", "category": "plumbing", "base_price": 95, "rating": 3.9, "jobs": 12, "reliability": 0.78},
    {"name": "Volt & Vine Electric", "category": "electrical", "base_price": 150, "rating": 4.7, "jobs": 19, "reliability": 0.94},
    {"name": "BrightSpark Electricians", "category": "electrical", "base_price": 120, "rating": 4.2, "jobs": 27, "reliability": 0.88},
    {"name": "CoolBreeze HVAC", "category": "hvac", "base_price": 160, "rating": 4.6, "jobs": 22, "reliability": 0.93},
    {"name": "AirCare Comfort", "category": "hvac", "base_price": 130, "rating": 4.1, "jobs": 15, "reliability": 0.85},
    {"name": "Summit Roofing", "category": "roofing", "base_price": 220, "rating": 4.5, "jobs": 17, "reliability": 0.92},
    {"name": "Handy Andy General Repair", "category": "general", "base_price": 90, "rating": 4.3, "jobs": 40, "reliability": 0.89},
    {"name": "FixItAll Home Services", "category": "general", "base_price": 105, "rating": 4.0, "jobs": 21, "reliability": 0.84},
]

AVAILABILITY_SLOTS = ["today at 5 PM", "today at 7 PM", "tomorrow morning", "tomorrow afternoon", "in two days"]


def _default_state():
    return {"providers": [dict(p) for p in SEED_PROVIDERS], "requests": [], "quotes": [], "feedback_log": [], "events": []}


def load_state():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE) as f:
                return json.load(f)
        except (ValueError, OSError):
            pass
    return _default_state()


STATE = load_state()


def save_state():
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(STATE, f, indent=2)
    os.replace(tmp, DB_FILE)


def log_event(text):
    STATE["events"].insert(0, {"time": time.strftime("%H:%M:%S"), "text": text})
    STATE["events"] = STATE["events"][:100]


def generate_quotes(req):
    """Real quote generation: providers in the request's category respond with a
    price derived from their base price (deterministic per request+provider)."""
    rng = random.Random(req["id"])
    providers = [p for p in STATE["providers"] if p["category"] == req["category"]]
    if not providers:
        providers = [p for p in STATE["providers"] if p["category"] == "general"]
    quotes = []
    for p in providers:
        quotes.append({
            "id": uuid.uuid4().hex[:8],
            "request_id": req["id"],
            "provider": p["name"],
            "price": int(p["base_price"] * rng.uniform(0.9, 1.15)),
            "rating": round(p["rating"], 1),
            "reliability": round(p["reliability"], 2),
            "availability": rng.choice(AVAILABILITY_SLOTS),
            "status": "offered",
        })
    STATE["quotes"].extend(quotes)
    log_event(f"{len(quotes)} providers quoted on '{req['description'][:40]}'")
    return quotes


def find(collection, key, value):
    return next((x for x in STATE[collection] if x.get(key) == value), None)


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/requests")
def create_request():
    data = request.get_json(silent=True) or {}
    with _lock:
        req = {
            "id": uuid.uuid4().hex[:8],
            "category": (data.get("category") or "general").lower(),
            "description": data.get("description") or "home service request",
            "urgency": data.get("urgency") or "soon",
            "status": "open",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "booked_provider": None,
            "feedback": None,
        }
        STATE["requests"].insert(0, req)
        log_event(f"New {req['category']} request: {req['description'][:50]}")
        generate_quotes(req)
        save_state()
    return jsonify({"ok": True, "request": req})


@app.get("/requests")
def list_requests():
    status = request.args.get("status")
    reqs = STATE["requests"]
    if status:
        reqs = [r for r in reqs if r.get("status") == status]
    out = []
    for r in reqs:
        item = dict(r)
        item["quote_count"] = sum(1 for q in STATE["quotes"] if q["request_id"] == r["id"])
        out.append(item)
    return jsonify({"ok": True, "requests": out})


@app.get("/requests/<req_id>/quotes")
def list_quotes(req_id):
    quotes = [q for q in STATE["quotes"] if q["request_id"] == req_id]
    # Refresh each quote's rating/reliability from live provider scores.
    for q in quotes:
        p = find("providers", "name", q["provider"])
        if p:
            q["rating"] = round(p["rating"], 1)
            q["reliability"] = round(p["reliability"], 2)
    return jsonify({"ok": True, "quotes": quotes})


@app.post("/quotes/<quote_id>/accept")
def accept_quote(quote_id):
    data = request.get_json(silent=True) or {}
    with _lock:
        quote = find("quotes", "id", quote_id)
        if not quote:
            return jsonify({"ok": False, "error": "unknown quote"})
        req = find("requests", "id", data.get("request_id") or quote["request_id"])
        quote["status"] = "accepted"
        for q in STATE["quotes"]:
            if q["request_id"] == quote["request_id"] and q["id"] != quote_id:
                q["status"] = "declined"
        if req:
            req["status"] = "booked"
            req["booked_provider"] = quote["provider"]
        log_event(f"Booked {quote['provider']} for {quote['price']} dollars")
        save_state()
    return jsonify({"ok": True, "quote": quote})


@app.post("/feedback")
def submit_feedback():
    data = request.get_json(silent=True) or {}
    rating = data.get("rating")
    provider_name = data.get("provider")
    with _lock:
        req = find("requests", "id", data.get("request_id"))
        if req:
            req["status"] = "rated"
            req["feedback"] = {"rating": rating, "comment": data.get("comment", "")}
        provider = find("providers", "name", provider_name)
        if provider and isinstance(rating, (int, float)) and 1 <= rating <= 5:
            # Personalized ranking update: rating joins the running average,
            # reliability nudges toward the outcome.
            provider["rating"] = (provider["rating"] * provider["jobs"] + rating) / (provider["jobs"] + 1)
            provider["jobs"] += 1
            nudge = 0.02 if rating >= 4 else -0.04 if rating <= 2 else 0.0
            provider["reliability"] = max(0.3, min(0.99, provider["reliability"] + nudge))
        STATE["feedback_log"].insert(0, {
            "time": time.strftime("%H:%M:%S"),
            "provider": provider_name,
            "rating": rating,
            "comment": data.get("comment", ""),
        })
        log_event(f"{provider_name} rated {rating}/5 — score now {provider['rating']:.2f}" if provider else f"Feedback for {provider_name}")
        save_state()
    return jsonify({"ok": True})


@app.get("/api/state")
def api_state():
    return jsonify({
        "providers": sorted(STATE["providers"], key=lambda p: -p["rating"]),
        "requests": STATE["requests"][:25],
        "quotes": STATE["quotes"][-60:],
        "feedback_log": STATE["feedback_log"][:25],
        "events": STATE["events"][:40],
        "server_time": time.strftime("%H:%M:%S"),
    })


@app.post("/api/reset")
def api_reset():
    """Demo helper: wipe back to seed state."""
    global STATE
    with _lock:
        STATE = _default_state()
        log_event("State reset to seed data")
        save_state()
    return jsonify({"ok": True})


DASHBOARD_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Immersive — Live Ops</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-900 text-slate-100 font-sans">
<div class="max-w-6xl mx-auto p-6">
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-bold text-indigo-400">Immersive — Live Marketplace</h1>
    <div class="text-sm text-slate-400">server <span id="clock" class="text-slate-200">–</span>
      <span id="dot" class="inline-block w-3 h-3 rounded-full bg-red-500 ml-2"></span></div>
  </div>
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
    <div class="rounded-2xl ring-1 ring-slate-700 bg-slate-800/60 p-4">
      <h2 class="font-semibold text-indigo-300 mb-3">Service Requests</h2>
      <div id="requests" class="space-y-2 text-sm"></div>
    </div>
    <div class="rounded-2xl ring-1 ring-slate-700 bg-slate-800/60 p-4">
      <h2 class="font-semibold text-indigo-300 mb-3">Provider Leaderboard <span class="text-xs text-slate-400">(live scores)</span></h2>
      <div id="providers" class="space-y-2 text-sm"></div>
    </div>
    <div class="rounded-2xl ring-1 ring-slate-700 bg-slate-800/60 p-4">
      <h2 class="font-semibold text-indigo-300 mb-3">Activity Feed</h2>
      <div id="events" class="space-y-1 text-xs text-slate-300"></div>
    </div>
  </div>
  <div class="rounded-2xl ring-1 ring-slate-700 bg-slate-800/60 p-4 mt-4">
    <h2 class="font-semibold text-indigo-300 mb-3">Latest Feedback</h2>
    <div id="feedback" class="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm"></div>
  </div>
</div>
<script>
const badge = s => ({open:"bg-amber-500/20 text-amber-300", booked:"bg-indigo-500/20 text-indigo-300", rated:"bg-emerald-500/20 text-emerald-300"}[s] || "bg-slate-600/40 text-slate-300");
async function tick(){
  try{
    const s = await (await fetch("/api/state")).json();
    document.getElementById("clock").textContent = s.server_time;
    document.getElementById("dot").className = "inline-block w-3 h-3 rounded-full bg-emerald-500 ml-2";
    document.getElementById("requests").innerHTML = s.requests.map(r =>
      `<div class="rounded-xl bg-slate-900/60 p-3 ring-1 ring-slate-700/60">
        <div class="flex justify-between"><span class="font-medium">${r.category}</span>
        <span class="px-2 py-0.5 rounded-full text-xs ${badge(r.status)}">${r.status}</span></div>
        <div class="text-slate-400">${r.description}</div>
        ${r.booked_provider ? `<div class="text-indigo-300 text-xs mt-1">→ ${r.booked_provider}</div>` : ""}
      </div>`).join("") || '<div class="text-slate-500">No requests yet — say "home help" to your agent.</div>';
    document.getElementById("providers").innerHTML = s.providers.map((p,i) =>
      `<div class="flex justify-between items-center rounded-xl bg-slate-900/60 p-2 ring-1 ring-slate-700/60">
        <div><span class="text-slate-500 mr-2">${i+1}.</span>${p.name}
        <span class="text-xs text-slate-500">(${p.category}, ${p.jobs} jobs)</span></div>
        <div class="text-right"><span class="text-amber-300">★ ${p.rating.toFixed(2)}</span>
        <span class="text-xs text-slate-400 ml-2">${Math.round(p.reliability*100)}% on-time</span></div>
      </div>`).join("");
    document.getElementById("events").innerHTML = s.events.map(e =>
      `<div><span class="text-slate-500">${e.time}</span> ${e.text}</div>`).join("");
    document.getElementById("feedback").innerHTML = s.feedback_log.map(f =>
      `<div class="rounded-xl bg-slate-900/60 p-3 ring-1 ring-slate-700/60">
        <div class="flex justify-between"><span>${f.provider}</span>
        <span class="text-amber-300">${"★".repeat(f.rating||0)}</span></div>
        ${f.comment ? `<div class="text-slate-400 text-xs mt-1">"${f.comment}"</div>` : ""}
      </div>`).join("") || '<div class="text-slate-500">No ratings yet.</div>';
  }catch(e){ document.getElementById("dot").className = "inline-block w-3 h-3 rounded-full bg-red-500 ml-2"; }
}
tick(); setInterval(tick, 2000);
</script></body></html>"""


@app.get("/")
def dashboard():
    return Response(DASHBOARD_HTML, mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
