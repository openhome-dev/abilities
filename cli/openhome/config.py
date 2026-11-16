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
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_API_BASE = "https://app.openhome.com"

CONFIG_DIR = Path.home() / ".openhome"
CONFIG_FILE = CONFIG_DIR / "config.json"

# The abilities repo root (…/abilities), so a `.env` there is found no matter
# which directory you run `openhome` from. config.py lives at cli/openhome/config.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]

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
    # Search order: the cwd and its parents (project-local .env), then the repo
    # root, then cli/ (backward compat). First one found wins.
    candidates = [d / ".env" for d in [here, *here.parents]]
    candidates += [_REPO_ROOT / ".env", _REPO_ROOT / "cli" / ".env"]
    for candidate in candidates:
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


def _write_config_file(data: dict) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass  # best-effort (Windows)
    return CONFIG_FILE


def clear_login(revoked_sid: str) -> None:
    """Forget the saved API key and session after the server revoked ``revoked_sid``.

    Skipped if another ``openhome login`` has already replaced that session.
    """
    data = _read_config_file()
    if data.get("sid") == revoked_sid:
        data.pop("sid", None)
        data.pop("api_key", None)
        _write_config_file(data)


@dataclass
class Config:
    """Resolved credentials + endpoint settings."""

    api_key: str | None = None
    jwt: str | None = None
    api_base: str = DEFAULT_API_BASE
    agent_id: str | None = None
    # This terminal's CLI session. Only ever used with the API key it was
    # created for: the one saved next to it in config.json.
    sid: str | None = None
    machine_id: str | None = None
    # The saved key has no session yet (logged in before sessions existed):
    # the transport creates one before its first API-key request.
    needs_session: bool = False

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

        resolved_key = _clean_token(
            api_key or os.environ.get(ENV_API_KEY) or file_cfg.get("api_key")
        )
        # The saved session belongs to the saved key. Any other key (a .env, or
        # one passed in for another account) runs without it, so a request
        # for someone else's account can never log this terminal out.
        saved_key = resolved_key is not None and resolved_key == _clean_token(
            file_cfg.get("api_key")
        )
        sid = (file_cfg.get("sid") or None) if saved_key else None

        return cls(
            api_key=resolved_key,
            jwt=_clean_token(
                jwt or os.environ.get(ENV_JWT) or file_cfg.get("jwt")
            ),
            api_base=resolved_base.rstrip("/"),
            agent_id=agent_id
            or os.environ.get(ENV_AGENT_ID)
            or file_cfg.get("agent_id"),
            sid=sid,
            machine_id=file_cfg.get("machine_id") or None,
            needs_session=saved_key and not sid,
        )

    # ── persistence (used by `openhome login`) ──────────────────────────
    def save(self) -> Path:
        """Persist non-secret-aware credentials to ``~/.openhome/config.json``."""
        data = _read_config_file()
        if self.api_key:
            data["api_key"] = self.api_key
        if self.jwt:
            data["jwt"] = self.jwt
        if self.agent_id:
            data["agent_id"] = self.agent_id
        if self.api_base and self.api_base != DEFAULT_API_BASE:
            data["api_base"] = self.api_base
        if self.machine_id:
            data["machine_id"] = self.machine_id
        if self.sid:
            data["sid"] = self.sid
        else:
            data.pop("sid", None)
        return _write_config_file(data)

    def save_sid(self) -> None:
        """Save only the session (for a key already saved), nothing else."""
        data = _read_config_file()
        data["sid"] = self.sid
        data["machine_id"] = self.machine_id
        _write_config_file(data)

    def ensure_machine_id(self) -> str:
        """This computer's ID for its CLI session: a random UUID, made once.

        Logging in again with the same ID replaces the old session instead of
        adding another. It is saved with the session, not here.
        """
        if not self.machine_id:
            self.machine_id = str(uuid.uuid4())
        return self.machine_id

    @property
    def ws_base(self) -> str:
        """WebSocket base derived from the API base."""
        return self.api_base.replace("https://", "wss://", 1).replace(
            "http://", "ws://", 1
        )
