"""Shared playbook types for immersive-diagnosis."""

from __future__ import annotations


# Outcomes returned by playbook steps
OUTCOME_CONTINUE = "continue"
OUTCOME_RESOLVED = "resolved"
OUTCOME_ESCALATE = "escalate"
OUTCOME_UNSAFE = "unsafe"

URGENCY_EMERGENCY = "emergency"
URGENCY_URGENT = "urgent_professional"
URGENCY_ROUTINE = "routine_professional"
URGENCY_DIY = "diy_ok"


def empty_session() -> dict:
    return {
        "category": None,
        "issue_type": None,
        "asset_type": None,
        "location": None,
        "symptoms": [],
        "safety_flags": [],
        "urgency": None,
        "active_playbook": None,
        "playbook_state": {},
        "observations": [],
        "troubleshooting_attempted": [],
        "diagnostic_summary": None,
        "possible_causes": [],
        "idle_empty": 0,
        "initial_complaint": None,
    }


def append_unique(items: list, value: str) -> None:
    if value and value not in items:
        items.append(value)


def merge_observation(session: dict, text: str) -> None:
    append_unique(session["observations"], text)


def merge_troubleshoot(session: dict, text: str) -> None:
    append_unique(session["troubleshooting_attempted"], text)


class StepResult:
    """Result of one playbook turn."""

    __slots__ = (
        "speak",
        "outcome",
        "urgency",
        "observations_added",
        "troubleshooting_added",
        "possible_causes",
        "diagnostic_summary",
    )

    def __init__(
        self,
        speak: str,
        outcome: str = OUTCOME_CONTINUE,
        urgency: str | None = None,
        observations_added: list | None = None,
        troubleshooting_added: list | None = None,
        possible_causes: list | None = None,
        diagnostic_summary: str | None = None,
    ):
        self.speak = speak
        self.outcome = outcome
        self.urgency = urgency
        self.observations_added = observations_added or []
        self.troubleshooting_added = troubleshooting_added or []
        self.possible_causes = possible_causes or []
        self.diagnostic_summary = diagnostic_summary
