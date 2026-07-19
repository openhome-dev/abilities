"""Create a new ability locally from the repo's own templates.

This is action #1 of the dashboard live-editor flow ("create an ability from a
template"), but driven from the repo: it copies one of the existing folders under
``templates/`` (or an ``official/`` example) into a destination directory and
rewrites the capability class name to match the new ability name. Nothing is
uploaded here — that's :func:`openhome.abilities` territory.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .errors import OpenHomeError

# Locate the repo root (…/abilities) relative to this file: cli/openhome/templates.py
_REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = _REPO_ROOT / "templates"
OFFICIAL_DIR = _REPO_ROOT / "official"

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")


@dataclass
class Template:
    name: str
    path: Path
    source: str  # "template" or "official"

    @property
    def has_main(self) -> bool:
        return (self.path / "main.py").is_file()


def repo_root() -> Path:
    return _REPO_ROOT


def user_dir() -> Path:
    """The per-user workspace (``<repo>/user/``) — gitignored, holds the user's
    own abilities created or synced via the CLI."""
    return _REPO_ROOT / "user"


def community_dir() -> Path:
    """The repo's ``community/`` folder — where contributed abilities live for PRs."""
    return _REPO_ROOT / "community"


# Files that are personal/build junk and must not be contributed to community/.
_PROMOTE_IGNORE = (".openhome.json", "__pycache__", "*.pyc", "*.pyo", ".DS_Store", "*.zip")


def promote_to_community(name: str, *, overwrite: bool = False) -> Path:
    """Copy an ability from ``user/<name>`` into ``community/<name>`` for a PR.

    Strips the personal ``.openhome.json`` manifest and build junk. Leaves the
    original ``user/`` copy untouched. Returns the new ``community/`` path.
    """
    src = user_dir() / name
    if not src.is_dir():
        raise OpenHomeError(
            f"No ability '{name}' found in user/. Looked in {src}"
        )
    if not (src / "main.py").is_file():
        raise OpenHomeError(f"{src} has no main.py — is this an ability folder?")

    if re.search(r"[_ ]", name):
        suggested = re.sub(r"[_ ]+", "-", name)
        raise OpenHomeError(
            f"Community folder names use only hyphens — rename '{name}' to "
            f"'{suggested}' first (e.g. `openhome sync` after renaming, or rename "
            f"the user/ folder)."
        )

    dest = community_dir() / name
    if dest.exists():
        if not overwrite:
            raise OpenHomeError(f"community/{name} already exists (use --overwrite).")
        shutil.rmtree(dest)

    community_dir().mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*_PROMOTE_IGNORE))
    return dest


def list_templates() -> list[Template]:
    """All available starting points: ``templates/*`` plus ``official/*`` examples."""
    found: list[Template] = []
    for base, source in ((TEMPLATES_DIR, "template"), (OFFICIAL_DIR, "official")):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and (child / "main.py").is_file():
                found.append(Template(name=child.name, path=child, source=source))
    return found


def find_template(name: str) -> Template:
    """Resolve a template by folder name (templates/ takes precedence over official/)."""
    matches = [t for t in list_templates() if t.name == name]
    if not matches:
        available = ", ".join(t.name for t in list_templates())
        raise OpenHomeError(
            f"Template '{name}' not found. Available: {available}"
        )
    # templates/ before official/ when names collide
    matches.sort(key=lambda t: 0 if t.source == "template" else 1)
    return matches[0]


def _to_class_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("-")) + "Capability"


def create_from_template(
    name: str,
    template: str = "basic-template",
    *,
    dest_dir: Path | str | None = None,
    overwrite: bool = False,
) -> Path:
    """Scaffold a new ability folder from a template.

    Args:
        name: lowercase-hyphen ability name (also the new folder name).
        template: which template/official folder to copy from.
        dest_dir: parent directory for the new folder (default: ``user/``).
        overwrite: replace an existing destination folder.

    Returns:
        Path to the created ability folder.
    """
    if not _NAME_RE.match(name):
        raise OpenHomeError(
            "Invalid name. Use lowercase letters, numbers and hyphens only, "
            "starting with a letter (e.g. 'my-weather')."
        )

    tpl = find_template(template)

    parent = Path(dest_dir) if dest_dir else user_dir()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / name

    if target.exists():
        if not overwrite:
            raise OpenHomeError(f"Destination already exists: {target}")
        shutil.rmtree(target)

    shutil.copytree(tpl.path, target)
    _rename_capability_class(target / "main.py", name)
    return target


def _rename_capability_class(main_py: Path, ability_name: str) -> None:
    """Rename the first ``class XxxCapability(MatchingCapability)`` to match the ability."""
    if not main_py.is_file():
        return
    code = main_py.read_text(encoding="utf-8")
    new_class = _to_class_name(ability_name)

    match = re.search(r"class\s+(\w+)\s*\(\s*MatchingCapability\s*\)", code)
    if not match:
        return
    old_class = match.group(1)
    if old_class == new_class:
        return
    # Replace the class name everywhere it is referenced (definition + any self refs).
    code = re.sub(rf"\b{re.escape(old_class)}\b", new_class, code)
    main_py.write_text(code, encoding="utf-8")
