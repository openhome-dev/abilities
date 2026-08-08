"""Deterministic adaptive playbook: AC not cooling (golden demo path)."""

from __future__ import annotations

from .playbook_base import (
    OUTCOME_CONTINUE,
    OUTCOME_ESCALATE,
    OUTCOME_RESOLVED,
    OUTCOME_UNSAFE,
    URGENCY_DIY,
    URGENCY_EMERGENCY,
    URGENCY_ROUTINE,
    StepResult,
)

ISSUE_TYPE = "ac_not_cooling"
CATEGORY = "hvac"

SAFETY_QUESTION = (
    "I can help you check that. First, is there any burning smell, smoke, "
    "sparking, or water near electrical wiring?"
)

POWER_MODE_QUESTION = (
    "Good. Is the AC running normally, and is it set to Cool mode?"
)

AIRFLOW_QUESTION = (
    "Got it. Is the air coming from the indoor unit strong, or does the airflow feel weak?"
)

FILTER_WHEN_QUESTION = (
    "A restricted filter can cause weak airflow. Do you know when the filter was last cleaned?"
)

FILTER_INSPECT_QUESTION = (
    "Let's check it. Switch the AC off first. Open the front panel of the indoor unit "
    "and look at the mesh filters. Tell me if they look heavily covered in dust."
)

FILTER_CLEAN_STEP = (
    "That could be restricting airflow. Remove the filters, clean them according to the "
    "manufacturer's instructions, make sure they're completely dry, then reinstall them. "
    "Tell me when that's done."
)

RETEST_AFTER_CLEAN = (
    "How's the airflow now, and is the air colder than before?"
)

OUTDOOR_QUESTION = (
    "Good, we've improved the airflow but the cooling problem remains. "
    "Is the outdoor AC unit currently running?"
)

ICE_QUESTION = (
    "Do you see any ice or frost on the indoor unit or the visible refrigerant pipes?"
)

ESCALATE_SPEAK = (
    "We've ruled out the AC settings and a blocked filter, and the outdoor unit is running. "
    "The remaining issue may require a technician to check components such as the "
    "refrigerant system, coils, or compressor. I can create a service request with "
    "everything we've already tested."
)

RESOLVED_SPEAK = (
    "Great — cooling is back after clearing the filter. You're all set."
)

UNSAFE_SPEAK = (
    "Stop using the AC and keep clear of any wiring or water near power. "
    "If there's smoke or fire risk, call emergency services first."
)


def initial_state() -> dict:
    return {
        "phase": "safety",
        "safety_clear": None,
        "ac_type": None,
        "power_on": None,
        "mode": None,
        "set_temperature": None,
        "airflow_strength": None,
        "filter_condition": None,
        "filter_cleaned": None,
        "airflow_after_cleaning": None,
        "cooling_after_cleaning": None,
        "outdoor_unit_running": None,
        "ice_present": None,
        "error_code": None,
        "unusual_noise": None,
        "awaiting": "safety",
    }


def seed_from_extract(state: dict, extract: dict) -> dict:
    """Apply pre-extracted fields before the first question."""
    for key in (
        "ac_type",
        "power_on",
        "mode",
        "set_temperature",
        "airflow_strength",
        "filter_condition",
        "outdoor_unit_running",
        "ice_present",
    ):
        if extract.get(key) is not None and state.get(key) is None:
            state[key] = extract[key]
    if extract.get("safety_clear") is True:
        state["safety_clear"] = True
    if extract.get("safety_clear") is False:
        state["safety_clear"] = False
    _advance_phase(state)
    return state


def _advance_phase(state: dict) -> None:
    if state.get("safety_clear") is None:
        state["phase"] = "safety"
        state["awaiting"] = "safety"
        return
    if state.get("safety_clear") is False:
        state["phase"] = "unsafe"
        state["awaiting"] = None
        return
    if state.get("power_on") is None or state.get("mode") is None:
        state["phase"] = "power_mode"
        state["awaiting"] = "power_mode"
        return
    if state.get("airflow_strength") is None:
        state["phase"] = "airflow"
        state["awaiting"] = "airflow"
        return
    if state["airflow_strength"] == "weak":
        if state.get("filter_condition") is None:
            # Ask when cleaned first if unknown, then inspect — for demo we go inspect
            state["phase"] = "filter_when"
            state["awaiting"] = "filter_when"
            return
        if state.get("filter_condition") == "dirty" and state.get("filter_cleaned") is not True:
            state["phase"] = "filter_clean"
            state["awaiting"] = "filter_clean"
            return
        if state.get("filter_cleaned") is True:
            if state.get("cooling_after_cleaning") is True:
                state["phase"] = "resolved"
                state["awaiting"] = None
                return
            if state.get("cooling_after_cleaning") is None:
                state["phase"] = "retest"
                state["awaiting"] = "retest"
                return
            # cooling_after_cleaning is False → outdoor path below
        # cooling still fails (or filter was clean) → outdoor path
        if state.get("outdoor_unit_running") is None:
            state["phase"] = "outdoor"
            state["awaiting"] = "outdoor"
            return
        if state.get("ice_present") is None:
            state["phase"] = "ice"
            state["awaiting"] = "ice"
            return
        state["phase"] = "escalate"
        state["awaiting"] = None
        return
    # strong airflow — skip filter DIY
    if state.get("outdoor_unit_running") is None:
        state["phase"] = "outdoor"
        state["awaiting"] = "outdoor"
        return
    if state.get("ice_present") is None:
        state["phase"] = "ice"
        state["awaiting"] = "ice"
        return
    state["phase"] = "escalate"
    state["awaiting"] = None


def prompt_for_state(state: dict) -> StepResult:
    """Return the next question/step without consuming a user reply."""
    _advance_phase(state)
    phase = state["phase"]

    if phase == "unsafe":
        return StepResult(
            speak=UNSAFE_SPEAK,
            outcome=OUTCOME_UNSAFE,
            urgency=URGENCY_EMERGENCY,
            observations_added=["Safety red flag reported"],
            diagnostic_summary="Unsafe electrical or fire-related signs reported with AC issue.",
        )
    if phase == "resolved":
        return StepResult(
            speak=RESOLVED_SPEAK,
            outcome=OUTCOME_RESOLVED,
            urgency=URGENCY_DIY,
            diagnostic_summary="AC cooling restored after filter cleaning.",
        )
    if phase == "escalate":
        causes = [
            "refrigerant system issue",
            "coil issue",
            "compressor or related component issue",
        ]
        return StepResult(
            speak=ESCALATE_SPEAK,
            outcome=OUTCOME_ESCALATE,
            urgency=URGENCY_ROUTINE,
            possible_causes=causes,
            diagnostic_summary=(
                "AC runs with improved airflow after filter cleaning but still does not cool."
                if state.get("filter_cleaned")
                else "AC not cooling after settings and airflow checks."
            ),
        )
    if phase == "safety":
        return StepResult(speak=SAFETY_QUESTION, outcome=OUTCOME_CONTINUE)
    if phase == "power_mode":
        return StepResult(speak=POWER_MODE_QUESTION, outcome=OUTCOME_CONTINUE)
    if phase == "airflow":
        return StepResult(speak=AIRFLOW_QUESTION, outcome=OUTCOME_CONTINUE)
    if phase == "filter_when":
        return StepResult(speak=FILTER_WHEN_QUESTION, outcome=OUTCOME_CONTINUE)
    if phase == "filter_inspect":
        return StepResult(speak=FILTER_INSPECT_QUESTION, outcome=OUTCOME_CONTINUE)
    if phase == "filter_clean":
        return StepResult(
            speak=FILTER_CLEAN_STEP,
            outcome=OUTCOME_CONTINUE,
            troubleshooting_added=["Inspected filter", "Guided filter cleaning"],
        )
    if phase == "retest":
        return StepResult(speak=RETEST_AFTER_CLEAN, outcome=OUTCOME_CONTINUE)
    if phase == "outdoor":
        return StepResult(
            speak=OUTDOOR_QUESTION
            if state.get("filter_cleaned")
            else (
                "Airflow seems fine, so let's check further. "
                "Is the outdoor AC unit currently running?"
            ),
            outcome=OUTCOME_CONTINUE,
        )
    if phase == "ice":
        return StepResult(speak=ICE_QUESTION, outcome=OUTCOME_CONTINUE)
    return StepResult(speak=SAFETY_QUESTION, outcome=OUTCOME_CONTINUE)


def apply_reply(state: dict, obs: dict) -> StepResult:
    """Apply structured observation from a user reply, then return next prompt/outcome."""
    awaiting = state.get("awaiting") or state.get("phase")
    notes: list[str] = []
    trouble: list[str] = []

    # Continuous safety
    if obs.get("safety_flag"):
        state["safety_clear"] = False
        flag = obs.get("safety_flag_detail") or "Safety concern mentioned"
        notes.append(flag)
        _advance_phase(state)
        return prompt_for_state(state)

    if awaiting == "safety":
        if obs.get("safety_clear") is True:
            state["safety_clear"] = True
            notes.append(
                "No burning smell, smoke, sparking, or electrical water exposure"
            )
        elif obs.get("safety_clear") is False:
            state["safety_clear"] = False
            notes.append(obs.get("safety_flag_detail") or "Safety red flag reported")
        else:
            return StepResult(
                speak="I need a clear yes or no on safety. Any burning smell, smoke, sparking, or water near wiring?",
                outcome=OUTCOME_CONTINUE,
            )

    elif awaiting == "power_mode":
        if obs.get("power_on") is not None:
            state["power_on"] = bool(obs["power_on"])
        if obs.get("mode") is not None:
            state["mode"] = obs["mode"]
        if obs.get("set_temperature") is not None:
            state["set_temperature"] = obs["set_temperature"]
        # Accept combined answers like "yes cool at 18"
        if state.get("power_on") is None and obs.get("affirmative"):
            state["power_on"] = True
        if state.get("mode") is None and obs.get("mode_cool"):
            state["mode"] = "cool"
        if state.get("power_on") is None or state.get("mode") is None:
            return StepResult(
                speak="Is the unit powered on, and is the mode set to Cool?",
                outcome=OUTCOME_CONTINUE,
            )
        if state["power_on"]:
            notes.append("AC is powered on")
        if state["mode"] == "cool":
            notes.append("Cool mode enabled")
            trouble.append("Checked operating mode")
        if state.get("set_temperature") is not None:
            notes.append(f"Set temperature is {state['set_temperature']}")
            trouble.append("Checked temperature setting")

    elif awaiting == "airflow":
        strength = obs.get("airflow_strength")
        if strength not in ("weak", "strong"):
            return StepResult(
                speak="Is the airflow from the indoor unit strong, or weak?",
                outcome=OUTCOME_CONTINUE,
            )
        state["airflow_strength"] = strength
        notes.append(
            "Initial airflow weak" if strength == "weak" else "Initial airflow strong"
        )

    elif awaiting == "filter_when":
        # Any answer → move to inspect (unknown last cleaned is fine)
        if obs.get("filter_condition") in ("dirty", "clean"):
            state["filter_condition"] = obs["filter_condition"]
        else:
            state["phase"] = "filter_inspect"
            state["awaiting"] = "filter_inspect"
            return StepResult(speak=FILTER_INSPECT_QUESTION, outcome=OUTCOME_CONTINUE)

    elif awaiting == "filter_inspect":
        cond = obs.get("filter_condition")
        if cond not in ("dirty", "clean"):
            return StepResult(
                speak="Do the mesh filters look heavily dusty, or fairly clean?",
                outcome=OUTCOME_CONTINUE,
            )
        state["filter_condition"] = cond
        trouble.append("Inspected filter")
        if cond == "dirty":
            notes.append("Filter heavily dusty")
        else:
            notes.append("Filter looked clean")
            # Clean filter + weak airflow → escalate path via outdoor
            state["filter_cleaned"] = False

    elif awaiting == "filter_clean":
        if obs.get("filter_cleaned") is True or obs.get("affirmative") or obs.get("done"):
            state["filter_cleaned"] = True
            notes.append("Filter cleaned")
            trouble.append("Cleaned filter")
        else:
            return StepResult(
                speak="Take your time — tell me when the filters are clean, dry, and back in place.",
                outcome=OUTCOME_CONTINUE,
            )

    elif awaiting == "retest":
        if obs.get("airflow_after_cleaning") is not None:
            state["airflow_after_cleaning"] = obs["airflow_after_cleaning"]
        if obs.get("cooling_after_cleaning") is not None:
            state["cooling_after_cleaning"] = obs["cooling_after_cleaning"]
        # Parse combined: "airflow better but still not cooling"
        if state.get("airflow_after_cleaning") is None and obs.get("airflow_improved"):
            state["airflow_after_cleaning"] = "improved"
        if state.get("cooling_after_cleaning") is None and obs.get("still_not_cooling"):
            state["cooling_after_cleaning"] = False
        if state.get("cooling_after_cleaning") is None and obs.get("cooling_fixed"):
            state["cooling_after_cleaning"] = True
        if state.get("cooling_after_cleaning") is None and state.get("airflow_after_cleaning") is None:
            return StepResult(
                speak="Is airflow better now, and is the air colder?",
                outcome=OUTCOME_CONTINUE,
            )
        if state.get("airflow_after_cleaning") in ("improved", "strong", True):
            notes.append("Airflow improved after cleaning")
            trouble.append("Retested airflow")
        if state.get("cooling_after_cleaning") is True:
            notes.append("Cooling improved after cleaning")
            trouble.append("Retested cooling")
        elif state.get("cooling_after_cleaning") is False:
            notes.append("Cooling did not improve")
            trouble.append("Retested cooling")
        # If airflow answered but cooling unknown, ask cooling only
        if state.get("cooling_after_cleaning") is None:
            state["awaiting"] = "retest"
            return StepResult(
                speak="Is the air colder than before?",
                outcome=OUTCOME_CONTINUE,
                observations_added=notes,
                troubleshooting_added=trouble,
            )

    elif awaiting == "outdoor":
        if obs.get("outdoor_unit_running") is None and obs.get("affirmative") is None and obs.get("negative") is None:
            return StepResult(
                speak="Is the outdoor unit running right now — yes or no?",
                outcome=OUTCOME_CONTINUE,
            )
        running = obs.get("outdoor_unit_running")
        if running is None:
            running = True if obs.get("affirmative") else False if obs.get("negative") else None
        if running is None:
            return StepResult(
                speak="Is the outdoor unit running right now — yes or no?",
                outcome=OUTCOME_CONTINUE,
            )
        state["outdoor_unit_running"] = running
        notes.append(
            "Outdoor unit running" if running else "Outdoor unit not running"
        )
        trouble.append("Checked outdoor unit")
        if not running:
            # Still escalate — different summary
            state["phase"] = "escalate"
            state["awaiting"] = None
            result = prompt_for_state(state)
            result.observations_added = notes + result.observations_added
            result.troubleshooting_added = trouble + result.troubleshooting_added
            result.diagnostic_summary = (
                "AC not cooling; outdoor unit not running after indoor checks."
            )
            result.speak = (
                "If the outdoor unit isn't running, a technician should check the system. "
                "I can create a service request with what we found."
            )
            return result

    elif awaiting == "ice":
        if obs.get("ice_present") is None and obs.get("affirmative") is None and obs.get("negative") is None:
            return StepResult(
                speak="Any ice or frost on the indoor unit or pipes — yes or no?",
                outcome=OUTCOME_CONTINUE,
            )
        ice = obs.get("ice_present")
        if ice is None:
            ice = True if obs.get("affirmative") else False if obs.get("negative") else None
        if ice is None:
            return StepResult(
                speak="Any ice or frost on the indoor unit or pipes — yes or no?",
                outcome=OUTCOME_CONTINUE,
            )
        state["ice_present"] = ice
        notes.append("Visible icing present" if ice else "No visible icing")
        trouble.append("Checked for visible icing")

    _advance_phase(state)
    # Special: after filter_when answered without condition, _advance may still say filter_when
    if state.get("phase") == "filter_when" and awaiting == "filter_when":
        state["phase"] = "filter_inspect"
        state["awaiting"] = "filter_inspect"
    # After setting filter dirty, next should be clean step immediately
    if state.get("filter_condition") == "dirty" and state.get("filter_cleaned") is not True:
        if awaiting == "filter_inspect":
            state["phase"] = "filter_clean"
            state["awaiting"] = "filter_clean"
            result = StepResult(
                speak=FILTER_CLEAN_STEP,
                outcome=OUTCOME_CONTINUE,
                observations_added=notes,
                troubleshooting_added=trouble + ["Guided filter cleaning"],
            )
            return result

    result = prompt_for_state(state)
    result.observations_added = notes + result.observations_added
    result.troubleshooting_added = trouble + result.troubleshooting_added
    return result


def interpret_reply_keywords(text: str, awaiting: str) -> dict:
    """Deterministic NL → observation map for tests and LLM fallback."""
    lower = (text or "").lower().strip()
    obs: dict = {}

    # Non-answers
    if any(
        p in lower
        for p in (
            "sorry",
            "repeat that",
            "say that again",
            "come again",
            "didn't catch",
            "what was that",
        )
    ):
        obs["is_clarification"] = True
        return obs

    # Safety signals anywhere
    if any(
        p in lower
        for p in (
            "burning",
            "smoke",
            "spark",
            "sparks",
            "sparking",
            "breaker trip",
            "tripped",
            "exposed wir",
            "water near",
            "shock",
        )
    ):
        if not any(n in lower for n in ("no burning", "no smoke", "no spark", "no water")):
            if awaiting == "safety" and lower in ("no", "nope", "none", "nothing"):
                pass
            elif any(
                p in lower
                for p in ("burning", "smoke", "spark", "sparking", "tripped", "shock")
            ) and not lower.startswith("no"):
                # "no burning..." handled below
                if not lower.startswith("no ") and "no " not in lower[:8]:
                    obs["safety_flag"] = True
                    obs["safety_flag_detail"] = "User mentioned electrical/fire safety concern"
                    obs["safety_clear"] = False
                    return obs

    if awaiting == "safety":
        if lower in ("no", "nope", "none", "nothing", "n") or lower.startswith("no ") or "no burning" in lower or "all clear" in lower or "nothing like that" in lower:
            obs["safety_clear"] = True
        elif lower in ("yes", "yeah", "yep", "y") or any(
            p in lower for p in ("burning", "smoke", "spark", "water")
        ):
            obs["safety_clear"] = False
            obs["safety_flag"] = True
            obs["safety_flag_detail"] = "User confirmed a safety concern"
        return obs

    if awaiting == "power_mode":
        if any(p in lower for p in ("cool", "cold")):
            obs["mode"] = "cool"
            obs["mode_cool"] = True
        if any(p in lower for p in ("yes", "yeah", "running", "it's on", "its on", "powered")):
            obs["power_on"] = True
            obs["affirmative"] = True
        if any(p in lower for p in ("no", "off", "not on")):
            obs["power_on"] = False
        # temperature like 18
        for token in lower.replace("degrees", " ").replace("c", " ").split():
            token = token.strip(".,")
            if token.isdigit() and 10 <= int(token) <= 32:
                obs["set_temperature"] = f"{token} C"
                break
        return obs

    if awaiting == "airflow":
        if any(p in lower for p in ("weak", "low", "poor", "not much", "barely")):
            obs["airflow_strength"] = "weak"
        elif any(p in lower for p in ("strong", "good", "fine", "normal", "powerful")):
            obs["airflow_strength"] = "strong"
        return obs

    if awaiting == "filter_when":
        if any(p in lower for p in ("dirty", "dusty", "clogged")):
            obs["filter_condition"] = "dirty"
        elif any(p in lower for p in ("clean", "recently")):
            obs["filter_condition"] = "clean"
        return obs

    if awaiting == "filter_inspect":
        if any(p in lower for p in ("yes", "dirty", "dusty", "really", "covered", "clogged")):
            obs["filter_condition"] = "dirty"
        elif any(p in lower for p in ("clean", "no", "not dusty", "looks fine")):
            obs["filter_condition"] = "clean"
        return obs

    if awaiting == "filter_clean":
        if any(p in lower for p in ("done", "finished", "cleaned", "did it", "ready", "yes")):
            obs["filter_cleaned"] = True
            obs["done"] = True
            obs["affirmative"] = True
        return obs

    if awaiting == "retest":
        if any(p in lower for p in ("still not", "not cooling", "still warm", "same", "no colder")):
            obs["still_not_cooling"] = True
            obs["cooling_after_cleaning"] = False
        if any(
            p in lower
            for p in (
                "colder",
                "cooling now",
                "it's fixed",
                "its fixed",
                "working now",
                "fixed",
                "cooling again",
            )
        ):
            if "still" not in lower and "not cool" not in lower:
                obs["cooling_fixed"] = True
                obs["cooling_after_cleaning"] = True
        if any(
            p in lower
            for p in ("airflow better", "better airflow", "stronger", "improved", "better")
        ):
            obs["airflow_improved"] = True
            obs["airflow_after_cleaning"] = "improved"
        # "airflow is better but it's still not cooling"
        if "better" in lower and ("still" in lower or "not cool" in lower):
            obs["airflow_improved"] = True
            obs["airflow_after_cleaning"] = "improved"
            obs["cooling_after_cleaning"] = False
            obs["still_not_cooling"] = True
        return obs

    if awaiting in ("outdoor", "ice"):
        if lower in ("yes", "yeah", "yep", "y") or lower.startswith("yes"):
            obs["affirmative"] = True
            if awaiting == "outdoor":
                obs["outdoor_unit_running"] = True
            else:
                obs["ice_present"] = True
        elif lower in ("no", "nope", "n") or lower.startswith("no"):
            obs["negative"] = True
            if awaiting == "outdoor":
                obs["outdoor_unit_running"] = False
            else:
                obs["ice_present"] = False
        return obs

    return obs
