"""Safe generic triage for unsupported issue types."""

from __future__ import annotations

from .playbook_base import (
    OUTCOME_CONTINUE,
    OUTCOME_ESCALATE,
    OUTCOME_UNSAFE,
    URGENCY_EMERGENCY,
    URGENCY_ROUTINE,
    StepResult,
)

ISSUE_TYPE = "generic"


def initial_state() -> dict:
    return {
        "phase": "safety",
        "safety_clear": None,
        "description": None,
        "location": None,
        "duration": None,
        "already_tried": None,
        "awaiting": "safety",
    }


def _next_after_basics(state: dict) -> None:
    """Advance to the next missing intake field, or escalate."""
    if not state.get("description"):
        state["phase"] = "describe"
        state["awaiting"] = "describe"
        return
    if not state.get("location"):
        state["phase"] = "location"
        state["awaiting"] = "location"
        return
    if not state.get("duration"):
        state["phase"] = "duration"
        state["awaiting"] = "duration"
        return
    if state.get("already_tried") is None:
        state["phase"] = "tried"
        state["awaiting"] = "tried"
        return
    state["phase"] = "escalate"
    state["awaiting"] = None


def prompt_for_state(state: dict) -> StepResult:
    phase = state.get("phase") or "safety"
    if phase == "unsafe":
        return StepResult(
            speak=(
                "Please stop DIY and stay clear of anything that could be dangerous. "
                "If anyone is at risk, call emergency services first."
            ),
            outcome=OUTCOME_UNSAFE,
            urgency=URGENCY_EMERGENCY,
            diagnostic_summary="Safety concern reported during generic home triage.",
        )
    if phase == "escalate":
        bits = [state.get("description") or "household issue"]
        if state.get("location"):
            bits.append(f"at {state['location']}")
        if state.get("duration"):
            bits.append(f"for {state['duration']}")
        summary = ", ".join(bits)
        if state.get("already_tried"):
            summary += f". Already tried: {state['already_tried']}"
        return StepResult(
            speak=(
                "I don't have a guided troubleshooting flow for this issue yet, "
                "but I have enough detail to arrange a professional."
            ),
            outcome=OUTCOME_ESCALATE,
            urgency=URGENCY_ROUTINE,
            diagnostic_summary=summary,
            observations_added=[],
        )
    if phase == "safety":
        return StepResult(
            speak=(
                "Before we go further, is there any burning smell, smoke, sparking, "
                "gas smell, flooding, or something structural that looks unsafe?"
            ),
            outcome=OUTCOME_CONTINUE,
        )
    if phase == "describe":
        return StepResult(
            speak="In one short sentence, what exactly is going wrong?",
            outcome=OUTCOME_CONTINUE,
        )
    if phase == "location":
        return StepResult(
            speak="Where in the home is this happening?",
            outcome=OUTCOME_CONTINUE,
        )
    if phase == "duration":
        return StepResult(
            speak="How long has this been going on?",
            outcome=OUTCOME_CONTINUE,
        )
    if phase == "tried":
        return StepResult(
            speak="Have you already tried anything to fix it?",
            outcome=OUTCOME_CONTINUE,
        )
    _next_after_basics(state)
    return prompt_for_state(state)


def apply_reply(state: dict, obs: dict) -> StepResult:
    awaiting = state.get("awaiting") or state.get("phase")
    notes: list[str] = []

    if obs.get("safety_flag") or (
        awaiting == "safety" and obs.get("safety_clear") is False
    ):
        state["safety_clear"] = False
        state["phase"] = "unsafe"
        state["awaiting"] = None
        notes.append(obs.get("safety_flag_detail") or "Safety concern reported")
        result = prompt_for_state(state)
        result.observations_added = notes
        return result

    if awaiting == "safety":
        if obs.get("safety_clear") is True:
            state["safety_clear"] = True
            notes.append("No immediate safety red flags reported")
            _next_after_basics(state)
            result = prompt_for_state(state)
            result.observations_added = notes
            return result
        return StepResult(
            speak="Any burning smell, smoke, sparking, gas, flooding, or structural danger — yes or no?",
            outcome=OUTCOME_CONTINUE,
        )

    if awaiting == "describe":
        desc = obs.get("description") or obs.get("raw_if_substantive")
        if not desc:
            return StepResult(
                speak="I still need a short description of the problem.",
                outcome=OUTCOME_CONTINUE,
            )
        state["description"] = desc
        notes.append(f"Issue: {desc}")
        _next_after_basics(state)
        result = prompt_for_state(state)
        result.observations_added = notes
        return result

    if awaiting == "location":
        loc = obs.get("location") or obs.get("raw_if_substantive")
        if not loc:
            return StepResult(
                speak="Which room or area is affected?",
                outcome=OUTCOME_CONTINUE,
            )
        state["location"] = loc
        notes.append(f"Location: {loc}")
        _next_after_basics(state)
        result = prompt_for_state(state)
        result.observations_added = notes
        return result

    if awaiting == "duration":
        dur = obs.get("duration") or obs.get("raw_if_substantive")
        if not dur:
            return StepResult(
                speak="About how long has this been happening?",
                outcome=OUTCOME_CONTINUE,
            )
        state["duration"] = dur
        notes.append(f"Duration: {dur}")
        _next_after_basics(state)
        result = prompt_for_state(state)
        result.observations_added = notes
        return result

    if awaiting == "tried":
        tried = obs.get("already_tried")
        if tried is None and obs.get("negative"):
            tried = "nothing yet"
        if tried is None and obs.get("raw_if_substantive"):
            tried = obs["raw_if_substantive"]
        if tried is None and obs.get("affirmative"):
            return StepResult(
                speak="What did you already try?",
                outcome=OUTCOME_CONTINUE,
            )
        if tried is None:
            return StepResult(
                speak="Have you tried anything already, or not yet?",
                outcome=OUTCOME_CONTINUE,
            )
        state["already_tried"] = tried
        notes.append(f"Already tried: {tried}")
        _next_after_basics(state)
        result = prompt_for_state(state)
        result.observations_added = notes
        return result

    state["phase"] = "escalate"
    state["awaiting"] = None
    return prompt_for_state(state)


def interpret_reply_keywords(text: str, awaiting: str) -> dict:
    lower = (text or "").lower().strip()
    obs: dict = {}
    if any(
        p in lower
        for p in (
            "sorry",
            "repeat that",
            "say that again",
            "come again",
            "didn't catch",
        )
    ):
        obs["is_clarification"] = True
        return obs

    if awaiting == "safety":
        if lower in ("no", "nope", "none", "nothing", "n") or lower.startswith("no "):
            obs["safety_clear"] = True
        elif lower in ("yes", "yeah", "yep") or any(
            p in lower
            for p in ("burning", "smoke", "spark", "gas", "flood", "structural")
        ):
            obs["safety_clear"] = False
            obs["safety_flag"] = True
        return obs

    if awaiting == "tried":
        if lower in ("no", "nope", "nothing", "not yet", "n"):
            obs["negative"] = True
            obs["already_tried"] = "nothing yet"
            return obs
        if lower in ("yes", "yeah", "yep"):
            obs["affirmative"] = True
            return obs

    if len(lower) >= 3 and not lower.startswith("sorry"):
        if awaiting == "describe":
            obs["description"] = text.strip()
            obs["raw_if_substantive"] = text.strip()
        elif awaiting == "location":
            obs["location"] = text.strip()
            obs["raw_if_substantive"] = text.strip()
        elif awaiting == "duration":
            obs["duration"] = text.strip()
            obs["raw_if_substantive"] = text.strip()
        elif awaiting == "tried":
            obs["already_tried"] = text.strip()
            obs["raw_if_substantive"] = text.strip()
    return obs
