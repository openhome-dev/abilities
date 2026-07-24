"""Playbook registry for immersive-diagnosis."""

from __future__ import annotations

from . import playbook_ac_not_cooling as ac_not_cooling, playbook_generic as generic

PLAYBOOKS = {
    ac_not_cooling.ISSUE_TYPE: ac_not_cooling,
    "generic": generic,
}


def get_playbook(issue_type: str | None):
    if issue_type and issue_type in PLAYBOOKS:
        return PLAYBOOKS[issue_type]
    return generic


def classify_issue_type(text: str) -> tuple[str | None, str | None]:
    """Heuristic classify category + issue_type from complaint text."""
    lower = (text or "").lower()
    if any(
        p in lower
        for p in (
            "ac ",
            " a/c",
            "air con",
            "aircon",
            "air conditioner",
            "air-conditioning",
            "hvac",
        )
    ) or ("cooling" in lower and any(p in lower for p in ("ac", "air", "conditioner"))):
        if any(
            p in lower
            for p in ("not cool", "isn't cool", "isnt cool", "not cooling", "warm", "hot air")
        ) or "cooling" in lower:
            return "hvac", "ac_not_cooling"
        return "hvac", "ac_not_cooling"
    if "ac" in lower and any(p in lower for p in ("cool", "cold", "warm", "hot")):
        return "hvac", "ac_not_cooling"
    return None, None
