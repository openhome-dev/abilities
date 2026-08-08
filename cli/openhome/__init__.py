"""openhome — Python client + CLI to link this abilities repo with an OpenHome account.

Typical use::

    from openhome import OpenHomeClient

    oh = OpenHomeClient.from_env()          # reads OPENHOME_API_KEY / OPENHOME_JWT
    agents = oh.list_agents()
    result = oh.save_ability(
        "official/weather",
        name="weather",
        description="Current weather by location",
        category="skill",
        trigger_words=["what's the weather", "weather"],
        personality_id=agents[0].id,        # auto-installs into that agent's call flow
    )
    oh.call(agents[0].id, "what's the weather in Tokyo")
"""

from .client import OpenHomeClient
from .config import Config
from .errors import (
    ApiError,
    NotAuthenticatedError,
    OpenHomeError,
    SessionExpiredError,
)
from .abilities import Ability
from .agents import Agent

__all__ = [
    "OpenHomeClient",
    "Config",
    "Agent",
    "Ability",
    "OpenHomeError",
    "ApiError",
    "SessionExpiredError",
    "NotAuthenticatedError",
]

__version__ = "0.1.0"
