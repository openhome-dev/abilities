"""Announcement copy in the emergency-broadcast voice.

Shared by the device (for logs) and background.py (for speech). Numbers are
spoken as words so text-to-speech never reads "6.2" as a date.
"""
from __future__ import annotations

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def say_number(x: float) -> str:
    """6.2 -> 'six point two'; 10.0 -> 'ten'; 1.41 -> 'one point four'."""
    x = round(float(x), 1)
    whole = int(x)
    tenth = int(round((x - whole) * 10))
    if whole == 10:
        w = "ten"
    elif whole < 10:
        w = ONES[whole]
    else:
        w = str(whole)
    return w if tenth == 0 else f"{w} point {ONES[tenth]}"


CLASS_LINES = {
    "whisper":        ("Minor event detected.", "Probably deniable."),
    "squeak":         ("Localised event detected.", "No action required."),
    "standard-issue": ("Warning. Fart detected.", "Be on smell lookout."),
    "notable":        ("Warning. Notable event detected.", "Be on smell lookout."),
    "room-clearing":  ("Warning. Room-clearing event detected.", "Open a window and be on smell lookout."),
    "structural":     ("Warning. Structural event detected.", "Check on the dog."),
    "evacuate":       ("Warning. Evacuate the vicinity.", "This is not a drill."),
    "biblical":       ("Warning. A magnitude nine event.", "Records have been kept."),
}

NEAR_MISS_LINE = "Nice try."


def pitch_phrase(dominant_hz: int, tonality: float) -> str:
    if not dominant_hz:
        return ""
    quality = "squeaky" if tonality >= 0.5 else "airy"
    register = "a low one" if dominant_hz < 150 else "a high one" if dominant_hz > 400 else "mid-range"
    return f"{register.capitalize()}, {quality}, around {dominant_hz} hertz."


def announcement(event: dict, include_pitch: bool = False) -> str:
    cls = event.get("class", "standard-issue")
    lead, advice = CLASS_LINES.get(cls, CLASS_LINES["standard-issue"])
    parts = [lead,
             f"Magnitude {say_number(event['magnitude'])}.",
             f"Duration {say_number(event['duration_s'])} seconds."]
    if include_pitch:
        p = pitch_phrase(event.get("dominant_hz", 0), event.get("tonality", 0.0))
        if p:
            parts.append(p)
    parts.append(advice)
    return " ".join(parts)


def consent_prompt() -> str:
    return ("Fart Finder listens to this room continuously. Audio never leaves the device "
            "and nothing is stored. Say yes to arm it, or no to leave it off.")


def status_line(status: dict) -> str:
    today = status.get("today", {})
    n = int(today.get("count", 0))
    if n == 0:
        base = "No events detected today."
    else:
        base = f"{say_number(n).capitalize()} event{'s' if n != 1 else ''} detected today."
        mx = today.get("max_magnitude")
        if mx:
            base += f" The largest was magnitude {say_number(mx)}."
    armed = "Armed" if status.get("armed") else "Disarmed"
    return f"{base} {armed}, sensitivity {status.get('sensitivity', 'medium')}."
