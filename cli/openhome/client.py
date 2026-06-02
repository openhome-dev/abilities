"""OpenHomeClient — the high-level facade most callers should use.

Wraps config + transport and exposes the dashboard live-editor flow as methods:
create-from-template, save/commit, set trigger words, assign to an agent, list,
delete, and the direct voice-to-voice call.
"""

from __future__ import annotations

from pathlib import Path

from . import abilities as _abilities
from . import templates as _templates
from . import voice as _voice
from . import workspace as _workspace
from .abilities import Ability, SaveResult
from .agents import Agent
from .config import Config
from .errors import OpenHomeError
from . import endpoints
from .transport import Transport
from .workspace import SyncReport


class OpenHomeClient:
    def __init__(self, config: Config | None = None):
        self.config = config or Config.from_env()
        self.transport = Transport(self.config)

    @classmethod
    def from_env(cls, **kwargs) -> "OpenHomeClient":
        """Build a client from .env / environment / ~/.openhome/config.json."""
        return cls(Config.from_env(**kwargs))

    # ── auth / account ──────────────────────────────────────────────────
    def verify_api_key(self) -> bool:
        result = self.transport.request(
            "POST",
            endpoints.VERIFY_API_KEY,
            auth="apikey_body",
            json={"api_key": self.config.api_key},
        )
        # Endpoint returns {valid: bool} or 200/personalities on success.
        if isinstance(result, dict) and "valid" in result:
            return bool(result["valid"])
        return True

    def list_agents(self) -> list[Agent]:
        """List the account's agents/personalities (action: choose where to install)."""
        result = self.transport.request(
            "POST",
            endpoints.GET_PERSONALITIES,
            auth="apikey_body",
            json={"api_key": self.config.api_key, "with_image": True},
        )
        rows = result.get("personalities", []) if isinstance(result, dict) else []
        return [Agent.from_api(row) for row in rows]

    # ── create from template (dashboard action #1) ──────────────────────
    def list_templates(self) -> list[_templates.Template]:
        return _templates.list_templates()

    def user_dir(self) -> Path:
        """The gitignored ``user/`` workspace for this user's own abilities."""
        return _templates.user_dir()

    def create_from_template(
        self,
        name: str,
        template: str = "basic-template",
        *,
        dest_dir: Path | str | None = None,
        overwrite: bool = False,
    ) -> Path:
        folder = _templates.create_from_template(
            name, template, dest_dir=dest_dir, overwrite=overwrite
        )
        # Seed a manifest so later push/sync can reconcile this folder.
        _workspace.write_manifest(
            folder,
            {"name": name, "capability_id": None, "template": template},
        )
        return folder

    # ── sync (pull account abilities into user/) ─────────────────────────
    def sync(
        self,
        dest: Path | str | None = None,
        *,
        force: bool = False,
        prune: bool = False,
    ) -> SyncReport:
        """Pull the account's abilities (code + effective triggers) into ``user/``.

        Downloads and extracts each ability's source and writes a manifest with
        its effective (overridden) trigger words and release history. Local code
        is preserved unless ``force=True``. With ``prune=True``, account-linked
        folders that no longer exist remotely are deleted (mirror mode).
        """
        target = Path(dest) if dest else self.user_dir()
        return _workspace.sync_abilities(
            self.list_abilities(),
            target,
            download=lambda cid: _abilities.download_ability_zip(self.transport, cid),
            detail=lambda cid: _abilities.get_installed_detail(self.transport, cid),
            force=force,
            prune=prune,
        )

    def download_ability(self, capability_id: str | int) -> bytes:
        """Raw zip bytes of an ability's current source."""
        return _abilities.download_ability_zip(self.transport, capability_id)

    def installed_detail(self, capability_id: str | int) -> dict:
        """Installed-capability detail (effective triggers + release history)."""
        return _abilities.get_installed_detail(self.transport, capability_id)

    # ── save / commit (actions #2, #3, #4) ──────────────────────────────
    def save_ability(
        self,
        folder: Path | str,
        *,
        name: str,
        description: str,
        category: str = "skill",
        trigger_words: list[str] | None = None,
        personality_id: str | None = None,
        image: Path | str | None = None,
        timeout: float = 120.0,
    ) -> SaveResult:
        """Create/commit an ability. Pass ``personality_id`` to auto-install it."""
        result = _abilities.save_ability(
            self.transport,
            folder,
            name=name,
            description=description,
            category=category,
            trigger_words=trigger_words,
            personality_id=personality_id,
            image=image,
            timeout=timeout,
        )
        # Record the remote id + metadata locally so the folder stays linked.
        manifest = _workspace.read_manifest(folder)
        manifest.update(
            {
                "name": name,
                "capability_id": result.capability_id or manifest.get("capability_id"),
                "category": category,
                "description": description,
                "trigger_words": trigger_words or [],
            }
        )
        _workspace.write_manifest(folder, manifest)
        return result

    def update_ability(
        self,
        folder: Path | str,
        *,
        commit: bool = False,
        message: str = "",
        capability_id: str | None = None,
    ) -> dict:
        """Update an existing ability's code **in place** (keeps the capability_id).

        Resolves the ability's current release from its manifest/account, uploads
        a flat zip to ``validate/release-code``, and refreshes the local manifest.
        Use ``commit=True`` + ``message`` to commit a version (default saves a draft).
        """
        folder = Path(folder)
        manifest = _workspace.read_manifest(folder)
        cap_id = capability_id or manifest.get("capability_id")
        if not cap_id:
            raise OpenHomeError(
                f"No capability_id for {folder}. Push it first to create it, "
                "or run `openhome sync` to link this folder to an account ability."
            )

        detail = _abilities.get_installed_detail(self.transport, cap_id)
        release_id = detail.get("release_id")
        if not release_id:
            raise OpenHomeError(
                f"Could not find an editable release for capability {cap_id}."
            )

        result = _abilities.update_release(
            self.transport,
            release_id,
            folder,
            committed=commit,
            commit_message=message,
        )

        # Refresh the manifest (release_id/version may have changed after a commit).
        refreshed = _abilities.get_installed_detail(self.transport, cap_id)
        manifest.update(
            {
                "capability_id": str(cap_id),
                "release_id": refreshed.get("release_id", release_id),
                "version": refreshed.get("version"),
                "is_committed": refreshed.get("is_committed"),
                "trigger_words": refreshed.get("trigger_words")
                or manifest.get("trigger_words", []),
            }
        )
        _workspace.write_manifest(folder, manifest)
        return result

    def list_abilities(self) -> list[Ability]:
        return _abilities.list_abilities(self.transport)

    def set_trigger_words(self, id_or_name: str, trigger_words: list[str]) -> dict:
        return _abilities.set_trigger_words(self.transport, id_or_name, trigger_words)

    def set_enabled(self, id_or_name: str, enabled: bool) -> dict:
        return _abilities.set_enabled(self.transport, id_or_name, enabled)

    def assign_to_agent(
        self, personality_id: str, capability_ids: list[int | str]
    ) -> dict:
        return _abilities.assign_to_agent(
            self.transport, personality_id, capability_ids
        )

    def delete_ability(self, id_or_name: str) -> dict:
        return _abilities.delete_ability(self.transport, id_or_name)

    # ── voice-to-voice (action #5) ──────────────────────────────────────
    def call(self, agent_id: str, phrase: str, *, timeout: float = 30.0) -> str:
        """Send one phrase to an agent over the voice stream; return its reply."""
        return _voice.trigger_once(self.config, agent_id, phrase, timeout=timeout)

    def voice_session(self, agent_id: str, **callbacks) -> _voice.VoiceSession:
        """Open an interactive voice session (caller drives send/receive)."""
        return _voice.VoiceSession(self.config, agent_id, **callbacks)

    def voice_call(self, agent_id: str, **kwargs) -> None:
        """Run a full mic-in / speaker-out voice call (blocks until hung up)."""
        from . import audio as _audio

        _audio.voice_call(self.config, agent_id, **kwargs)
