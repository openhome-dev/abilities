"""Configuration resolution for the OpenHome client.

Credentials are resolved in priority order so the same code works for a local dev
(.env file), CI (real env vars), and an interactive ``openhome login`` (config file):

    1. Explicit value passed to the constructor
    2. Environment variable (incl. values loaded from a nearby ``.env``)
    3. ``~/.openhome/config.json`` (written by ``openhome login``)

Nothing here talks to the network — see :mod:`openhome.transport`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_API_BASE = "https://app.openhome.com"

CONFIG_DIR = Path.home() / ".openhome"
CONFIG_FILE = CONFIG_DIR / "config.json"

ENV_API_KEY = "OPENHOME_API_KEY"
ENV_JWT = "OPENHOME_JWT"
ENV_API_BASE = "OPENHOME_API_BASE"
ENV_AGENT_ID = "OPENHOME_AGENT_ID"


def _load_dotenv(start: Path | None = None) -> None:
    """Load KEY=VALUE pairs from the nearest ``.env`` into ``os.environ``.

    Walks up from ``start`` (default: cwd) looking for a ``.env`` file. Existing
    environment variables always win, so real env vars override the file. Kept
    dependency-free on purpose; ``python-dotenv`` is only an optional extra.
    """
    if os.environ.get("OPENHOME_SKIP_DOTENV"):
        return

    here = (start or Path.cwd()).resolve()
    for directory in [here, *here.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            _parse_env_file(candidate)
            return


def _parse_env_file(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Don't clobber values already present in the real environment.
        if key and key not in os.environ:
            os.environ[key] = value


def _clean_token(value: str | None) -> str | None:
    """Normalize a pasted credential.

    Tolerates the two most common copy/paste mistakes:
    * surrounding whitespace / quotes
    * a leading ``Bearer `` prefix (e.g. copied from a Network-tab Authorization
      header) — we add the prefix ourselves, so it must not be in the stored value.
    """
    if not value:
        return value
    value = value.strip().strip('"').strip("'").strip()
    if value[:7].lower() == "bearer ":
        value = value[7:].strip()
    return value or None


def _read_config_file() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@dataclass
class Config:
    """Resolved credentials + endpoint settings."""

    api_key: str | None = None
    jwt: str | None = None
    api_base: str = DEFAULT_API_BASE
    agent_id: str | None = None

    @classmethod
    def from_env(
        cls,
        *,
        api_key: str | None = None,
        jwt: str | None = None,
        api_base: str | None = None,
        agent_id: str | None = None,
        load_dotenv: bool = True,
    ) -> "Config":
        if load_dotenv:
            _load_dotenv()

        file_cfg = _read_config_file()

        resolved_base = (
            api_base
            or os.environ.get(ENV_API_BASE)
            or file_cfg.get("api_base")
            or DEFAULT_API_BASE
        )
        if not resolved_base.startswith("https://"):
            raise ValueError(
                f"API base URL must use HTTPS. Got: {resolved_base}"
            )

        return cls(
            api_key=_clean_token(
                api_key or os.environ.get(ENV_API_KEY) or file_cfg.get("api_key")
            ),
            jwt=_clean_token(
                jwt or os.environ.get(ENV_JWT) or file_cfg.get("jwt")
            ),
            api_base=resolved_base.rstrip("/"),
            agent_id=agent_id
            or os.environ.get(ENV_AGENT_ID)
            or file_cfg.get("agent_id"),
        )

    # ── persistence (used by `openhome login`) ──────────────────────────
    def save(self) -> Path:
        """Persist non-secret-aware credentials to ``~/.openhome/config.json``."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = _read_config_file()
        if self.api_key:
            data["api_key"] = self.api_key
        if self.jwt:
            data["jwt"] = self.jwt
        if self.agent_id:
            data["agent_id"] = self.agent_id
        if self.api_base and self.api_base != DEFAULT_API_BASE:
            data["api_base"] = self.api_base
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            CONFIG_FILE.chmod(0o600)
        except OSError:
            pass  # best-effort (Windows)
        return CONFIG_FILE

    @property
    def ws_base(self) -> str:
        """WebSocket base derived from the API base."""
        return self.api_base.replace("https://", "wss://", 1).replace(
            "http://", "ws://", 1
        )
