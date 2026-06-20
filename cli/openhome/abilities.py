"""Ability operations: zip a folder, save it to the account, edit triggers, list, delete.

These map onto the dashboard live-editor actions:

* :func:`save_ability`  → ``POST /api/capabilities/add-capability/``  (create/commit + set trigger words; optional ``personality_id`` auto-installs it into that agent's call flow)
* :func:`set_trigger_words` / :func:`set_enabled` → ``PUT …/edit-installed-capability/{id}/``
* :func:`assign_to_agent` → ``PUT /api/personalities/edit-personality/``
* :func:`list_abilities` / :func:`delete_ability`

All functions take a :class:`~openhome.transport.Transport`.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import endpoints
from .errors import OpenHomeError
from .transport import Transport

VALID_CATEGORIES = ("skill", "brain_skill", "background_daemon", "local")

# Files/dirs we never want inside an uploaded ability zip.
_ZIP_EXCLUDE_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".idea"}
_ZIP_EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip"}
_ZIP_EXCLUDE_NAMES = {".DS_Store", ".openhome.json"}


@dataclass
class Ability:
    """Summary of an ability on the account (from get-all-capabilities)."""

    id: str
    name: str
    category: str | None = None
    description: str | None = None
    trigger_words: list[str] = field(default_factory=list)
    is_installed: bool = False
    is_published: bool = False
    last_updated: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "Ability":
        return cls(
            id=str(data.get("id")),
            name=data.get("name", ""),
            category=data.get("category"),
            description=data.get("description"),
            trigger_words=list(data.get("trigger_words") or []),
            is_installed=bool(data.get("is_installed")),
            is_published=bool(data.get("is_published")),
            last_updated=data.get("last_updated"),
        )


@dataclass
class InstalledAbility:
    """An installed capability (from get-installed-capabilities)."""

    id: str
    name: str
    category: str | None = None
    trigger_words: list[str] = field(default_factory=list)
    enabled: bool = False
    system_capability: bool = False
    agent_capability: bool = False

    @classmethod
    def from_api(cls, data: dict) -> "InstalledAbility":
        return cls(
            id=str(data.get("id")),
            name=data.get("name", ""),
            category=data.get("category"),
            trigger_words=list(data.get("trigger_words") or []),
            enabled=bool(data.get("enabled")),
            system_capability=bool(data.get("system_capability")),
            agent_capability=bool(data.get("agent_capability")),
        )


@dataclass
class SaveResult:
    """Result of saving/uploading an ability."""

    capability_id: str | None
    detail: str | None
    raw: dict

    @classmethod
    def from_api(cls, data: dict) -> "SaveResult":
        cid = data.get("capability_id") or data.get("ability_id")
        return cls(
            capability_id=str(cid) if cid is not None else None,
            detail=data.get("detail") or data.get("message"),
            raw=data,
        )


# ── zipping ─────────────────────────────────────────────────────────────
def zip_ability(
    folder: Path | str, root_name: str | None = None, *, flat: bool = False
) -> bytes:
    """Zip an ability folder into an in-memory archive, skipping junk files.

    The two backend upload endpoints disagree on layout:

    * ``add-capability`` (create) wants a **single top-level directory** — the
      layout you get by zipping the folder itself in Finder
      (``<root_name>/main.py``). This is the default.
    * ``validate/release-code`` (update) wants the files **flat** at the archive
      root (``main.py`` directly). Pass ``flat=True`` for this.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise OpenHomeError(f"Not a directory: {folder}")
    if not (folder / "main.py").is_file():
        raise OpenHomeError(f"No main.py found in {folder} — is this an ability folder?")

    root = root_name or folder.name

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(folder)
            if any(part in _ZIP_EXCLUDE_DIRS for part in rel.parts):
                continue
            if path.suffix in _ZIP_EXCLUDE_SUFFIXES or path.name in _ZIP_EXCLUDE_NAMES:
                continue
            arcname = rel.as_posix() if flat else f"{root}/{rel.as_posix()}"
            zf.write(path, arcname)
    return buffer.getvalue()


# ── save / create ───────────────────────────────────────────────────────
def save_ability(
    transport: Transport,
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
    """Create/commit an ability to the account (dashboard "save" action).

    Passing ``personality_id`` installs it into that agent's voice call flow.
    ``trigger_words`` are persisted alongside it in the OpenHome database.
    """
    if category not in VALID_CATEGORIES:
        raise OpenHomeError(
            f"Invalid category '{category}'. One of: {', '.join(VALID_CATEGORIES)}"
        )
    trigger_words = trigger_words or []

    zip_bytes = zip_ability(folder)

    files: list[tuple] = [
        ("zip_file", ("ability.zip", zip_bytes, "application/zip")),
    ]
    if image:
        image = Path(image)
        ext = image.suffix.lower().lstrip(".") or "png"
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
        files.append(("image_file", (image.name, image.read_bytes(), mime)))

    data: dict[str, str] = {
        "name": name,
        "description": description,
        "category": category,
        "trigger_words": ", ".join(trigger_words),
    }
    if personality_id:
        data["personality_id"] = str(personality_id)

    # multipart/form-data — requests sets the boundary header from files=.
    result = transport.request(
        "POST",
        endpoints.ADD_CAPABILITY,
        auth="jwt",
        data=data,
        files=files,
        timeout=timeout,
    )
    return SaveResult.from_api(result if isinstance(result, dict) else {})


# ── list / get ────────────────────────────────────────────────────────────
def list_abilities(transport: Transport) -> list[Ability]:
    result = transport.request("GET", endpoints.LIST_CAPABILITIES, auth="jwt")
    rows = result if isinstance(result, list) else result.get("abilities", [])
    return [Ability.from_api(row) for row in rows]


def find_ability(transport: Transport, id_or_name: str) -> Ability:
    for ability in list_abilities(transport):
        if ability.id == str(id_or_name) or ability.name == id_or_name:
            return ability
    raise OpenHomeError(f'Ability "{id_or_name}" not found on this account.')


# ── installed view (enable / disable / set-triggers) ──────────────────────
def list_installed(transport: Transport) -> list[InstalledAbility]:
    """List installed capabilities (the runtime view)."""
    result = transport.request(
        "GET", endpoints.LIST_INSTALLED_CAPABILITIES, auth="jwt"
    )
    rows = result if isinstance(result, list) else result.get("capabilities", [])
    return [InstalledAbility.from_api(row) for row in rows]


def find_installed(transport: Transport, id_or_name: str) -> InstalledAbility:
    """Resolve an installed ability by installed id, name, or capability id.

    ``openhome list`` shows the capability id, but the edit endpoint needs the
    installed id; the two are bridged by name via get-all-capabilities.
    """
    installed = list_installed(transport)

    for ia in installed:
        if ia.id == str(id_or_name) or ia.name == id_or_name:
            return ia

    name: str | None = None
    for a in list_abilities(transport):
        if a.id == str(id_or_name) or a.name == id_or_name:
            name = a.name
            break
    if name is not None:
        for ia in installed:
            if ia.name == name:
                return ia
        raise OpenHomeError(
            f'"{name}" exists on your account but is not installed, '
            "so it can't be enabled, disabled, or have triggers changed."
        )

    raise OpenHomeError(f'Ability "{id_or_name}" not found.')


def download_ability_zip(transport: Transport, capability_id: str | int) -> bytes:
    """Download an ability's current source as raw zip bytes."""
    return transport.request(
        "GET",
        endpoints.download_capability(capability_id),
        auth="jwt",
        parse_json=False,
        timeout=120.0,
    )


def update_release(
    transport: Transport,
    release_id: str | int,
    folder: Path | str,
    *,
    committed: bool = False,
    commit_message: str = "",
    timeout: float = 120.0,
) -> dict:
    """Update an existing release's code in place (the dashboard "Save"/"Commit").

    Uploads a **flat** zip of ``folder`` to ``validate/release-code/{release_id}``.
    ``committed=False`` saves a draft; ``committed=True`` (+ ``commit_message``)
    commits a version.
    """
    zip_bytes = zip_ability(folder, flat=True)
    return transport.request(
        "POST",
        endpoints.validate_release_code(release_id),
        auth="jwt",
        data={
            "committed": "true" if committed else "false",
            "commit_message": commit_message or "",
        },
        files=[("zip_file", ("ability.zip", zip_bytes, "application/zip"))],
        timeout=timeout,
    )


def get_installed_detail(transport: Transport, capability_id: str | int) -> dict:
    """Installed-capability detail: effective trigger words + release history.

    Returns ``{}`` if the ability has no installed record.
    """
    try:
        result = transport.request(
            "GET",
            endpoints.installed_capability_by_capability(capability_id),
            auth="jwt",
        )
    except OpenHomeError:
        return {}
    return result if isinstance(result, dict) else {}


# ── edit installed (triggers / enable-disable) ────────────────────────────
def edit_installed(
    transport: Transport,
    ability: InstalledAbility,
    *,
    enabled: bool | None = None,
    trigger_words: list[str] | None = None,
) -> dict:
    """PUT the full installed-capability object (the API replaces, not patches)."""
    return transport.request(
        "PUT",
        endpoints.edit_installed_capability(ability.id),
        auth="xapikey",
        json={
            "enabled": ability.enabled if enabled is None else enabled,
            "name": ability.name,
            "category": ability.category or "skill",
            "trigger_words": (
                ability.trigger_words if trigger_words is None else trigger_words
            ),
            "system_capability": ability.system_capability,
            "agent_capability": ability.agent_capability,
        },
    )


def set_trigger_words(
    transport: Transport, id_or_name: str, trigger_words: list[str]
) -> dict:
    """Update an installed ability's trigger words (dashboard "edit triggers")."""
    ability = find_installed(transport, id_or_name)
    return edit_installed(transport, ability, trigger_words=trigger_words)


def set_enabled(transport: Transport, id_or_name: str, enabled: bool) -> dict:
    ability = find_installed(transport, id_or_name)
    return edit_installed(transport, ability, enabled=enabled)


# ── assign to agent ─────────────────────────────────────────────────────
def assign_to_agent(
    transport: Transport, personality_id: str, capability_ids: list[int | str]
) -> dict:
    """Attach abilities to an agent's call flow via edit-personality (multipart)."""
    fields: list[tuple] = [("personality_id", (None, str(personality_id)))]
    for cap_id in capability_ids:
        fields.append(("matching_capabilities", (None, str(cap_id))))
    return transport.request(
        "PUT", endpoints.EDIT_PERSONALITY, auth="xapikey", files=fields
    )


# ── delete ──────────────────────────────────────────────────────────────
def delete_ability(transport: Transport, id_or_name: str) -> dict:
    """Delete a single ability by id or name."""
    ability = find_ability(transport, id_or_name)
    return delete_capabilities(transport, [ability.id])


def delete_capabilities(transport: Transport, capability_ids: list[str | int]) -> dict:
    """Batch-delete abilities: ``POST /delete-capability/`` with
    ``{"capability_ids": [...]}``. Ids are sent as integers."""
    ids = [int(cid) for cid in capability_ids]
    return transport.request(
        "POST",
        endpoints.DELETE_CAPABILITY,
        auth="jwt",
        json={"capability_ids": ids},
    )