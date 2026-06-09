"""The local ``user/`` workspace: per-ability manifests and account sync.

Each ability folder carries a small ``.openhome.json`` manifest linking the local
folder to its remote capability (id, category, trigger words, last sync time), so
commands like ``push`` / ``set-triggers`` can work from the folder alone and so
``sync`` can reconcile what's local with what's on the account.

Note on code download: the API contract we have exposes ability *metadata*
(``get-all-capabilities``) but no endpoint that returns an ability's source. So
``sync`` writes/updates manifests and creates folders for remote-only abilities,
but it can't fetch their ``main.py`` until a download endpoint is wired in. See
:data:`SyncEntry.code_synced`.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .abilities import Ability

MANIFEST_NAME = ".openhome.json"

# Never extract these out of a downloaded zip into the workspace.
_EXTRACT_SKIP_NAMES = {".openhome.json"}
_EXTRACT_SKIP_DIRS = {"__pycache__"}


def manifest_path(folder: Path | str) -> Path:
    return Path(folder) / MANIFEST_NAME


def read_manifest(folder: Path | str) -> dict:
    try:
        return json.loads(manifest_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_manifest(folder: Path | str, data: dict) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = manifest_path(folder)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def manifest_from_ability(ability: Ability, detail: dict | None = None) -> dict:
    detail = detail or {}
    # Effective (overridden) trigger words live on the installed record; fall back
    # to the template defaults from the capability listing.
    trigger_words = detail.get("trigger_words") or ability.trigger_words
    releases = detail.get("releases") or []
    return {
        "capability_id": ability.id,
        "name": ability.name,
        "category": detail.get("category") or ability.category,
        "description": detail.get("description") or ability.description,
        "trigger_words": trigger_words,
        "is_installed": ability.is_installed,
        "version": detail.get("version"),
        "release_id": detail.get("release_id"),
        "is_committed": detail.get("is_committed"),
        "releases": [
            {k: r.get(k) for k in ("id", "version", "is_committed", "commit_message")}
            for r in releases
        ],
        "last_synced": _now_iso(),
    }


def extract_zip_into(folder: Path | str, zip_bytes: bytes) -> list[str]:
    """Extract a (flat) ability zip into ``folder``, skipping junk. Returns the
    list of files written (relative paths)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename
            parts = Path(rel).parts
            if any(p in _EXTRACT_SKIP_DIRS for p in parts):
                continue
            if Path(rel).name in _EXTRACT_SKIP_NAMES:
                continue
            target = folder / rel
            # Guard against zip-slip (entries escaping the folder).
            if not str(target.resolve()).startswith(str(folder.resolve())):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            written.append(rel)
    return written


@dataclass
class SyncEntry:
    name: str
    capability_id: str
    folder: Path
    created_folder: bool       # the local folder didn't exist before
    code_synced: bool          # source files present locally after sync
    code_action: str           # "downloaded" | "kept-local" | "failed" | "skipped"
    note: str = ""


@dataclass
class SyncReport:
    entries: list[SyncEntry] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)        # folders removed
    prunable: list[str] = field(default_factory=list)      # stale, not removed (no --prune)

    @property
    def kept_local(self) -> list[SyncEntry]:
        return [e for e in self.entries if e.code_action == "kept-local"]

    @property
    def failed(self) -> list[SyncEntry]:
        return [e for e in self.entries if e.code_action == "failed"]


def sync_abilities(
    abilities: list[Ability],
    dest: Path,
    *,
    download=None,
    detail=None,
    force: bool = False,
    prune: bool = False,
) -> SyncReport:
    """Reconcile remote abilities into the local ``dest`` (``user/``) workspace.

    For each remote ability: ensure ``dest/<name>/`` exists, fetch its effective
    metadata + trigger words (``detail``), download and extract its source
    (``download``), and write a manifest.

    Args:
        download: ``callable(capability_id) -> bytes`` returning the ability zip.
                  If None, code isn't downloaded (manifest-only sync).
        detail:   ``callable(capability_id) -> dict`` returning installed-capability
                  detail (effective trigger words, releases). Optional.
        force:    overwrite local source even if the folder already has a ``main.py``.
                  Without it, locally-present code is preserved (so you don't clobber
                  edits you haven't pushed).
        prune:    delete local folders that were previously account-linked (their
                  manifest has a ``capability_id``) but no longer exist on the
                  account. Folders with no ``capability_id`` (purely local, never
                  pushed) are always kept.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    report = SyncReport()
    account_ids = {str(a.id) for a in abilities}

    for ability in abilities:
        folder = dest / ability.name
        created = not folder.exists()
        folder.mkdir(parents=True, exist_ok=True)

        det = {}
        if detail is not None:
            try:
                det = detail(ability.id) or {}
            except Exception:  # noqa: BLE001 — detail is best-effort enrichment
                det = {}

        had_local_code = (folder / "main.py").is_file()
        code_action, note = "skipped", ""

        if download is not None:
            if had_local_code and not force:
                code_action, note = "kept-local", "use --force to overwrite local code"
            else:
                try:
                    extract_zip_into(folder, download(ability.id))
                    code_action = "downloaded"
                except Exception as exc:  # noqa: BLE001
                    code_action, note = "failed", str(exc)

        write_manifest(folder, manifest_from_ability(ability, det))
        report.entries.append(
            SyncEntry(
                name=ability.name,
                capability_id=ability.id,
                folder=folder,
                created_folder=created,
                code_synced=(folder / "main.py").is_file(),
                code_action=code_action,
                note=note,
            )
        )

    # Reconcile deletions: folders that were account-linked but are gone remotely.
    for child in sorted(dest.iterdir()):
        if not child.is_dir():
            continue
        cap_id = read_manifest(child).get("capability_id")
        if not cap_id or str(cap_id) in account_ids:
            continue  # purely-local folder, or still on the account → keep
        if prune:
            shutil.rmtree(child)
            report.pruned.append(child.name)
        else:
            report.prunable.append(child.name)

    return report
