"""Agent (a.k.a. personality) data model and lookups."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Agent:
    """An OpenHome agent / personality on the account."""

    id: str
    name: str
    description: str | None = None
    image: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "Agent":
        return cls(
            id=str(data.get("id")),
            name=data.get("name", ""),
            description=data.get("description"),
            image=data.get("image"),
        )
