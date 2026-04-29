#!/usr/bin/env python3
"""
Sonos local command runner for OpenHome ability.
Receives a JSON command via argv[1], executes via SoCo, prints JSON result to stdout.

Usage:
    python3 sonos_local.py '{"action": "discover"}'
    python3 sonos_local.py '{"action": "play", "room": "Kitchen"}'
"""

import json
import sys
import time
import soco

CACHE_FILE = "/tmp/sonos_devices.json"
CACHE_TTL = 300  # seconds before re-discovering


# ── Output helpers ────────────────────────────────────────────────────────────

def _out(data: dict):
    print(json.dumps(data))
    sys.exit(0)


def _err(msg: str):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


# ── Device cache ──────────────────────────────────────────────────────────────

def _load_cache():
    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        if time.time() - cache.get("ts", 0) < CACHE_TTL:
            return cache["devices"]  # {name: ip}
    except Exception:
        pass
    return None


def _save_cache(devices):
    data = {
        "ts": time.time(),
        "devices": {d.player_name: d.ip_address for d in devices},
    }
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)
    return data["devices"]


def _get_all():
    """Return {room_name: SoCo} using cache when possible."""
    cached = _load_cache()
    if cached:
        return {name: soco.SoCo(ip) for name, ip in cached.items()}
    discovered = soco.discover()
    if not discovered:
        return {}
    _save_cache(discovered)
    return {d.player_name: d for d in discovered}


def _get(room: str):
    d = _get_all().get(room)
    if not d:
        _err(f"Room not found: {room}")
    return d


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_discover():
    discovered = soco.discover()
    if not discovered:
        _err("No devices found")
    _save_cache(discovered)
    _out({"ok": True, "data": [d.player_name for d in discovered]})


def cmd_play(c):
    _get(c["room"]).play()
    _out({"ok": True})


def cmd_pause(c):
    _get(c["room"]).pause()
    _out({"ok": True})


def cmd_next(c):
    _get(c["room"]).next()
    _out({"ok": True})


def cmd_previous(c):
    _get(c["room"]).previous()
    _out({"ok": True})


def cmd_toggle_play(c):
    d = _get(c["room"])
    info = d.get_transport_info()
    if info["current_transport_state"] == "PLAYING":
        d.pause()
    else:
        d.play()
    _out({"ok": True})


def cmd_volume_set(c):
    d = _get(c["room"])
    d.volume = max(0, min(100, int(c["vol"])))
    _out({"ok": True})


def cmd_volume_up(c):
    d = _get(c["room"])
    d.volume = min(100, d.volume + int(c.get("step", 10)))
    _out({"ok": True})


def cmd_volume_down(c):
    d = _get(c["room"])
    d.volume = max(0, d.volume - int(c.get("step", 10)))
    _out({"ok": True})


def cmd_mute(c):
    _get(c["room"]).mute = True
    _out({"ok": True})


def cmd_unmute(c):
    _get(c["room"]).mute = False
    _out({"ok": True})


def cmd_toggle_mute(c):
    d = _get(c["room"])
    d.mute = not d.mute
    _out({"ok": True})


def cmd_shuffle_on(c):
    d = _get(c["room"])
    d.play_mode = "SHUFFLE" if "REPEAT" in d.play_mode else "SHUFFLE_NOREPEAT"
    _out({"ok": True})


def cmd_shuffle_off(c):
    d = _get(c["room"])
    d.play_mode = "REPEAT_ALL" if "REPEAT" in d.play_mode else "NORMAL"
    _out({"ok": True})


def cmd_repeat_on(c):
    d = _get(c["room"])
    d.play_mode = "SHUFFLE" if "SHUFFLE" in d.play_mode else "REPEAT_ALL"
    _out({"ok": True})


def cmd_repeat_off(c):
    d = _get(c["room"])
    d.play_mode = "SHUFFLE_NOREPEAT" if "SHUFFLE" in d.play_mode else "NORMAL"
    _out({"ok": True})


def cmd_crossfade_on(c):
    _get(c["room"]).cross_fade = True
    _out({"ok": True})


def cmd_crossfade_off(c):
    _get(c["room"]).cross_fade = False
    _out({"ok": True})


def cmd_get_state(c):
    d = _get(c["room"])
    track = d.get_current_track_info()
    transport = d.get_transport_info()
    _out({"ok": True, "data": {
        "title": track.get("title", ""),
        "artist": track.get("artist", ""),
        "state": transport.get("current_transport_state", "STOPPED"),
        "volume": d.volume,
    }})


def cmd_get_favorites(c):
    d = _get(c["room"])
    favs = d.music_library.get_favorites()
    _out({"ok": True, "data": [f.title for f in favs]})


def cmd_play_favorite(c):
    d = _get(c["room"])
    name = c["name"]
    favs = d.music_library.get_favorites()
    fav = next((f for f in favs if name.lower() in f.title.lower()), None)
    if fav is None:
        _err(f"Favorite not found: {name}")
    d.play_uri(fav.resources[0].uri, meta=fav.resource_meta_data)
    _out({"ok": True})


def cmd_get_playlists(c):
    d = _get(c["room"])
    playlists = d.music_library.get_playlists()
    _out({"ok": True, "data": [p.title for p in playlists]})


def cmd_play_playlist(c):
    d = _get(c["room"])
    name = c["name"]
    playlists = d.music_library.get_playlists()
    playlist = next((p for p in playlists if name.lower()
                    in p.title.lower()), None)
    if playlist is None:
        _err(f"Playlist not found: {name}")
    d.clear_queue()
    d.add_uri_to_queue(playlist)
    d.play_from_queue(0)
    _out({"ok": True})


def cmd_pause_all(c):
    for d in _get_all().values():
        try:
            d.pause()
        except Exception:
            pass
    _out({"ok": True})


def cmd_resume_all(c):
    for d in _get_all().values():
        try:
            d.play()
        except Exception:
            pass
    _out({"ok": True})


def cmd_sleep(c):
    _get(c["room"]).set_sleep_timer(int(c["seconds"]))
    _out({"ok": True})


def cmd_join(c):
    devices = _get_all()
    joiner = devices.get(c["joiner"])
    leader = devices.get(c["leader"])
    if not joiner:
        _err(f"Room not found: {c['joiner']}")
    if not leader:
        _err(f"Room not found: {c['leader']}")
    joiner.join(leader)
    _out({"ok": True})


def cmd_unjoin(c):
    _get(c["room"]).unjoin()
    _out({"ok": True})


# ── Dispatch ──────────────────────────────────────────────────────────────────

HANDLERS = {
    "discover": cmd_discover,
    "play": cmd_play,
    "pause": cmd_pause,
    "next": cmd_next,
    "previous": cmd_previous,
    "toggle_play": cmd_toggle_play,
    "volume_set": cmd_volume_set,
    "volume_up": cmd_volume_up,
    "volume_down": cmd_volume_down,
    "mute": cmd_mute,
    "unmute": cmd_unmute,
    "toggle_mute": cmd_toggle_mute,
    "shuffle_on": cmd_shuffle_on,
    "shuffle_off": cmd_shuffle_off,
    "repeat_on": cmd_repeat_on,
    "repeat_off": cmd_repeat_off,
    "crossfade_on": cmd_crossfade_on,
    "crossfade_off": cmd_crossfade_off,
    "get_state": cmd_get_state,
    "get_favorites": cmd_get_favorites,
    "play_favorite": cmd_play_favorite,
    "get_playlists": cmd_get_playlists,
    "play_playlist": cmd_play_playlist,
    "pause_all": cmd_pause_all,
    "resume_all": cmd_resume_all,
    "sleep": cmd_sleep,
    "join": cmd_join,
    "unjoin": cmd_unjoin,
}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        _err("No command provided")

    try:
        cmd = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        _err(f"Invalid JSON: {e}")

    action = cmd.get("action", "")
    handler = HANDLERS.get(action)
    if not handler:
        _err(f"Unknown action: {action}")

    try:
        if action == "discover":
            handler()
        else:
            handler(cmd)
    except SystemExit:
        raise
    except Exception as e:
        _err(str(e))
