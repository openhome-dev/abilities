"""Thin CLI over :class:`openhome.OpenHomeClient`.

Commands mirror the dashboard live-editor flow:

    openhome login                       # save API key (+ optional JWT) to ~/.openhome
    openhome agents                      # list agents on the account
    openhome templates                   # list available templates
    openhome create NAME --template T    # scaffold a new ability locally
    openhome push FOLDER --name N ...     # save/commit an ability (+ install to agent)
    openhome list                        # list abilities on the account
    openhome set-triggers ID "a, b, c"   # update trigger words
    openhome enable/disable ID
    openhome delete ID
    openhome call AGENT_ID "phrase"       # direct voice-to-voice trigger
    openhome chat AGENT_ID                # interactive voice session
    openhome devkit onboard               # set up a DevKit over Bluetooth
    openhome devkit status                # how is my DevKit doing?

The CLI only formats input/output; all real logic lives in the library.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import re
import os
import sys
import threading
from pathlib import Path
from typing import Any

from .abilities import VALID_CATEGORIES
from .client import OpenHomeClient
from .config import Config
from .errors import (
    ApiKeyRejected,
    ConnectionLost,
    DeviceNotFound,
    DeviceOffline,
    DevKitError,
    NotAuthenticatedError,
    OpenHomeError,
    ScanFailed,
    SessionExpiredError,
    WifiFailed,
)
from . import local



def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [w.strip() for w in value.split(",") if w.strip()]


MIN_TRIGGER_LEN = 4
_TRIGGER_OK = re.compile(r"^[A-Za-z0-9 '\-]+$")
_HAS_LETTER = re.compile(r"[A-Za-z]")


def _trigger_problems(words: list[str]) -> list[str]:
    problems = []
    for w in words:
        if not _HAS_LETTER.search(w):
            problems.append(f'"{w}" must contain letters')
        elif not _TRIGGER_OK.match(w):
            problems.append(f'"{w}" has an invalid character (only letters, numbers, spaces, \' and - allowed)')
        elif len(_HAS_LETTER.findall(w)) < MIN_TRIGGER_LEN:
            problems.append(f'"{w}" must contain at least {MIN_TRIGGER_LEN} letters')
    return problems


def _check_triggers(words: list[str]) -> None:
    problems = _trigger_problems(words)
    if problems:
        _err("invalid trigger words:\n  " + "\n  ".join(problems))
        raise SystemExit(1)


def _prompt_triggers() -> list[str]:
    while True:
        words = _split_csv(_prompt("Trigger words (comma-separated)", required=True))
        if not words:
            return []
        problems = _trigger_problems(words)
        if problems:
            print("  invalid trigger words:\n  " + "\n  ".join(problems) + "\n  Please try again.")
            continue
        return words


def _resolve_folder(arg: str) -> Path:
    """Resolve an ability folder from a path *or* bare name, regardless of cwd.

    Tries, in order: the path as given (relative to cwd), relative to the repo
    root (so ``user/foo`` works from ``cli/``), and the ``user/`` workspace by
    name (so ``foo`` → ``<repo>/user/foo``). Falls back to the original path so
    the caller's error message stays meaningful.
    """
    from .templates import repo_root, user_dir

    candidates = [
        Path(arg),
        repo_root() / arg,
        user_dir() / arg,
        user_dir() / Path(arg).name,
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return Path(arg)


# ── commands ─────────────────────────────────────────────────────────────
def cmd_login(args: argparse.Namespace) -> int:
    api_key = args.api_key or input("Paste your OpenHome API key: ").strip()
    if not api_key:
        _err("API key is required.")
        return 1
    cfg = Config.from_env(api_key=api_key, jwt=args.jwt)
    client = OpenHomeClient(cfg)
    try:
        client.verify_api_key()
    except OpenHomeError as exc:
        _err(f"Could not verify API key: {exc}")
        return 1
    path = cfg.save()
    print(f"✓ API key verified and saved to {path}")
    if args.jwt:
        print("✓ Session token (JWT) saved.")
    else:
        print(
            "note: no JWT set. Saving/uploading abilities currently needs one — "
            "set OPENHOME_JWT or pass --jwt until the backend accepts the API key."
        )
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    client = OpenHomeClient()
    agents = client.list_agents()
    if not agents:
        print("No agents found. Create one at https://app.openhome.com")
        return 0
    for a in agents:
        print(f"{a.id}\t{a.name}")
    return 0


# The frontend shows some categories under a different name than the API
# value. Only list ones that actually differ.
CATEGORY_DISPLAY_NAMES = {
    "brain_skill": "Agent_Controlled",
}


def _display_category(category: str) -> str:
    display = CATEGORY_DISPLAY_NAMES.get(category)
    return f"{display} ({category})" if display else category


def cmd_templates(args: argparse.Namespace) -> int:
    from .templates import template_category

    client = OpenHomeClient()
    for t in client.list_templates():
        category = template_category(t.name) or "skill"
        print(f"{t.name}\t({t.source})\tCategory: {_display_category(category)}")
    return 0


def _prompt(label: str, *, required: bool = False, default: str = "") -> str:
    """Prompt the user for a value (returns default / "" in non-interactive mode)."""
    if not sys.stdin.isatty():
        return default
    while True:
        suffix = f" [{default}]" if default else ""
        try:
            val = input(f"{label}{suffix}: ").strip()
        except EOFError:
            return default
        if val:
            return val
        if default or not required:
            return default


def _ability_name(name: str) -> str:
    """The account requires alphanumeric ability names; folders may use hyphens."""
    cleaned = name.replace("-", "")
    if cleaned != name:
        print(f"  note: using '{cleaned}' as the ability name (alphanumeric required)")
    return cleaned


def cmd_create(args: argparse.Namespace) -> int:
    from .templates import template_category
    from .workspace import read_manifest, write_manifest

    client = OpenHomeClient()

    # Validate any --triggers flag BEFORE scaffolding, so a bad flag exits
    # before a folder is created (avoids "Destination already exists" on retry).
    triggers = _split_csv(args.triggers)
    if triggers:
        _check_triggers(triggers)

    dest = client.create_from_template(
        args.name,
        args.template,
        dest_dir=args.dest,
        overwrite=args.overwrite,
    )
    print(f"✓ Created ability at {dest}")

    category = args.category or template_category(args.template) or "skill"

    # Collect triggers/description now, whether or not we're pushing today, so
    # a later `openhome push` has everything it needs without repeating flags.
    # The prompt re-asks until every trigger word is valid.
    if not triggers:
        triggers = _prompt_triggers()
    description = args.description or _prompt(
        "Description", default=f"{args.name} ability"
    )

    manifest = read_manifest(dest)
    manifest.update(
        {"category": category, "trigger_words": triggers, "description": description}
    )
    write_manifest(dest, manifest)

    if args.no_push:
        print(f"  category: {category}")
        print(f"  triggers: {', '.join(triggers) if triggers else '(none yet)'}")
        print(f"  Edit {dest / 'main.py'}, then: openhome push {dest}")
        return 0

    if not triggers:
        print(
            f"  No trigger words given — not pushed. Add some, then: "
            f"openhome push {dest} --triggers \"a, b\""
        )
        return 0

    ability_name = _ability_name(args.name)

    result = client.save_ability(
        dest,
        name=ability_name,
        description=description,
        category=category,
        trigger_words=triggers,
        personality_id=args.agent,
    )
    print(f"✓ Pushed '{ability_name}'")
    if result.capability_id:
        print(f"  capability_id: {result.capability_id}")
    print(f"  category: {category}")
    print(f"  triggers: {', '.join(triggers)}")
    if args.agent:
        print(f"  installed into agent {args.agent}'s call flow")
    print(f"  edit {dest / 'main.py'} then `openhome push {dest}` to update in place")
    return 0


def cmd_push_to_community(args: argparse.Namespace) -> int:
    import subprocess
    import sys as _sys
    from .templates import promote_to_community, repo_root

    dest = promote_to_community(args.name, overwrite=args.overwrite)
    rel = dest.relative_to(repo_root())
    print(f"✓ Copied {args.name} → {rel}  (manifest + junk stripped)")

    # Best-effort validation using the repo's validator.
    validator = repo_root() / "validate_ability.py"
    if validator.is_file():
        print(f"\nValidating {rel} …")
        res = subprocess.run(
            [_sys.executable, str(validator), str(rel)], cwd=repo_root()
        )
        if res.returncode != 0:
            print("\n⚠️  Validation reported issues — fix them before opening a PR.")

    print(
        "\nNext steps to contribute:\n"
        f"  git checkout -b add-{args.name}\n"
        f"  git add {rel} && git commit -m 'Add {args.name} ability'\n"
        "  git push and open a PR to `dev` (see CONTRIBUTING.md)"
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    client = OpenHomeClient()
    report = client.sync(dest=args.dest, force=args.force, prune=args.prune)
    for e in report.entries:
        tag = "new" if e.created_folder else "updated"
        suffix = f"  ({e.code_action}{': ' + e.note if e.note else ''})"
        print(f"✓ {e.name}\t[{tag}]\t{e.folder}{suffix}")
    if not report.entries:
        print("No abilities on the account.")
    for name in report.pruned:
        print(f"🗑  pruned {name} (deleted on account)")
    if report.kept_local:
        print(
            f"\nnote: kept local code for {len(report.kept_local)} ability(ies). "
            "Re-run with --force to overwrite with the account's version."
        )
    if report.prunable:
        print(
            f"\nnote: {len(report.prunable)} local folder(s) no longer on the account "
            f"({', '.join(report.prunable)}). Re-run with --prune to delete them."
        )
    if report.failed:
        print(f"\nwarning: {len(report.failed)} ability(ies) failed to download.")
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    from .templates import template_category
    from .workspace import read_manifest

    client = OpenHomeClient()
    folder = _resolve_folder(args.folder)
    manifest = read_manifest(folder)
    cap_id = manifest.get("capability_id")

    # Existing ability → update in place (never delete + re-create).
    if cap_id:
        result = client.update_ability(
            folder, commit=args.commit, message=args.message or "",
            category=args.category,
        )
        verb = "Committed" if args.commit else "Saved (draft)"
        print(f"✓ {verb} update to '{manifest.get('name', folder.name)}' (capability_id {cap_id})")
        if args.category:
            print(f"  category: {args.category}")
        detail = result.get("detail") if isinstance(result, dict) else None
        if detail:
            print(f"  {detail}")
        new_manifest = read_manifest(folder)
        print(f"  release: {new_manifest.get('version')} (release_id {new_manifest.get('release_id')})")
        return 0

    # New ability → create.
    name = _ability_name(args.name or manifest.get("name") or folder.name)
    triggers = _split_csv(args.triggers) or manifest.get("trigger_words") or []
    if not triggers:
        _err(
            "No trigger words. Add some with: "
            f'openhome push {folder} --triggers "a, b"'
        )
        return 1
    _check_triggers(triggers)
    category = (
        args.category
        or template_category(manifest.get("template") or "")
        or manifest.get("category")
        or "skill"
    )
    result = client.save_ability(
        folder,
        name=name,
        description=args.description or manifest.get("description") or f"{name} ability",
        category=category,
        trigger_words=triggers,
        personality_id=args.agent,
        image=args.image,
    )
    print(f"✓ Created ability '{name}'")
    if result.capability_id:
        print(f"  capability_id: {result.capability_id}")
    print(f"  category: {category}")
    if result.detail:
        print(f"  {result.detail}")
    if args.agent:
        print(f"  installed into agent {args.agent}'s call flow")
    print("  (future pushes to this folder update it in place)")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    client = OpenHomeClient()
    for a in client.list_abilities():
        triggers = ", ".join(a.trigger_words) if a.trigger_words else "—"
        state = "installed" if a.is_installed else "not installed"
        print(f"{a.id}\t{a.name}\t[{state}]\ttriggers: {triggers}")
    return 0


def cmd_set_triggers(args: argparse.Namespace) -> int:
    client = OpenHomeClient()
    words = _split_csv(args.triggers)
    if not words:
        _err("Provide at least one trigger word.")
        return 1
    _check_triggers(words)
    client.set_trigger_words(args.id, words)
    print(f"✓ Updated trigger words for {args.id}: {', '.join(words)}")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    OpenHomeClient().set_enabled(args.id, True)
    print(f"✓ Enabled {args.id}")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    OpenHomeClient().set_enabled(args.id, False)
    print(f"✓ Disabled {args.id}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    import shutil
    from .templates import user_dir

    OpenHomeClient().delete_ability(args.id)
    print(f"✓ Deleted {args.id} from your account")

    if not args.keep_local:
        folder = _resolve_folder(args.id)
        udir = user_dir().resolve()
        # Only ever remove a folder that lives directly inside user/.
        if folder.is_dir() and folder.resolve().parent == udir:
            try:
                shutil.rmtree(folder)
                print(f"  removed local folder {folder}")
            except OSError as exc:
                print(f"  (could not remove local folder: {exc})")
    return 0


def _build_call_logger():
    """Return an ``on_log(data)`` that renders server logs with level-based colors.

    Uses ``coloredlogs`` when available (consistent per-level styling), and falls
    back to manual ANSI otherwise. The server's ``data`` is ``{"l": level, "m": msg}``.
    """
    import logging

    _LEVELS = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "warn": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }

    logger = logging.getLogger("openhome.call")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        try:
            import coloredlogs

            coloredlogs.install(
                level="DEBUG",
                logger=logger,
                fmt="%(levelname)-8s %(message)s",
            )
        except ImportError:
            # Fallback: manual ANSI, colored by level.
            colors = {
                logging.DEBUG: "\033[36m", logging.INFO: "\033[32m",
                logging.WARNING: "\033[33m", logging.ERROR: "\033[31m",
                logging.CRITICAL: "\033[31m",
            }

            class _AnsiFormatter(logging.Formatter):
                def format(self, record):
                    c = colors.get(record.levelno, "")
                    return f"{c}{record.levelname:<8}\033[0m {record.getMessage()}"

            h = logging.StreamHandler()
            h.setFormatter(_AnsiFormatter())
            logger.addHandler(h)

    def on_log(d: dict) -> None:
        if not isinstance(d, dict):
            logger.info(str(d))
            return
        level = _LEVELS.get((d.get("l") or "info").lower(), logging.INFO)
        logger.log(level, d.get("m", ""))

    return on_log


def cmd_call(args: argparse.Namespace) -> int:
    client = OpenHomeClient()
    # Default to agent "0" (the account's default agent) when none is given.
    agent_id = args.agent or client.config.agent_id or "0"

    # One-shot text trigger when --say is given.
    if args.say:
        print(f"→ {args.say}")
        reply = client.call(agent_id, args.say, timeout=args.timeout)
        print(f"← {reply}" if reply else "← (no response within timeout)")
        return 0

    # Otherwise: a real voice call — mic in, speaker out.
    print(f"📞 Calling agent {agent_id} …  (SPACE = interrupt, Ctrl-C = hang up)")

    on_log = _build_call_logger()
    dim, reset = "\033[2m", "\033[0m"

    def on_text(d: dict) -> None:
        # The assistant's text already appears in the TTT debug log, so only echo
        # the user's transcribed turns here (not in the logs).
        if (d.get("role") or "").lower() == "user" and d.get("final") and d.get("content"):
            print(f"🎙  {d['content']}")

    try:
        client.voice_call(
            agent_id,
            on_text=on_text,
            on_log=on_log,
            on_status=lambda s: print(f"{dim}  ({s}){reset}"),
        )
    except OpenHomeError as exc:
        _err(str(exc))
        return 1
    print("\nCall ended.")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    client = OpenHomeClient()
    agent_id = args.agent or client.config.agent_id
    if not agent_id:
        _err("No agent id. Pass AGENT_ID or set OPENHOME_AGENT_ID.")
        return 1

    print(f"Connecting to agent {agent_id}… (type /quit to exit)")
    last_live = {"on": False}

    def on_connect() -> None:
        print("Connected. Type a message and press Enter.\n")

    def on_message(m) -> None:
        if m.role != "assistant":
            return
        if m.live and not m.final:
            print(f"\rAgent: {m.content}", end="", flush=True)
            last_live["on"] = True
        else:
            if last_live["on"]:
                print()
            else:
                print(f"Agent: {m.content}")
            last_live["on"] = False

    def on_error(e) -> None:
        print(f"\nserver error: {e}", file=sys.stderr)

    session = client.voice_session(
        agent_id, on_connect=on_connect, on_message=on_message, on_error=on_error
    )
    session.connect()
    try:
        while not session.wait(0.1):
            try:
                line = input()
            except EOFError:
                break
            text = line.strip()
            if text in ("/quit", "/exit", "/q"):
                break
            if text:
                session.say(text)
    except KeyboardInterrupt:
        pass
    finally:
        session.close()
    print("\nDisconnected.")
    return 0

def cmd_local(args: argparse.Namespace) -> int:
    action = args.local_action
    if action == "run":
        return local.run_worker(
            OpenHomeClient().config,
            client_id=args.client_id, role=args.role,
            timeout=args.timeout, once=args.once,
        )
    if action == "start":
        return local.start(client_id=args.client_id, role=args.role, timeout=args.timeout)
    if action == "stop":
        return local.stop()
    if action == "status":
        return local.status()
    if action == "logs":
        return local.logs(follow=not args.no_follow, lines=args.lines)
    _err(f"unknown local action: {action}")
    return 1

# ── devkit ─────────────────────────────────────────────────────────────
def _mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "…"


def _prompt_secret(label: str) -> str:
    """Prompt without echoing (returns "" in non-interactive mode)."""
    if not sys.stdin.isatty():
        return ""
    try:
        return getpass.getpass(f"{label}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _confirm(label: str, default: bool = True) -> bool:
    if not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{label} {suffix}: ").strip().lower()
    except EOFError:
        return default
    return default if not answer else answer in ("y", "yes")


def _require_interactive(hint: str) -> None:
    """Interactive loops must never spin against a closed stdin."""
    if not sys.stdin.isatty():
        raise DevKitError(f"This step needs a terminal. {hint}")


async def _ask(fn, *args, **kwargs):
    """Run a blocking prompt on a daemon thread, keeping the event loop free.

    Not asyncio.to_thread: its worker cannot be interrupted, so Ctrl-C would
    hang until the user pressed Enter.
    """
    loop = asyncio.get_running_loop()
    done = loop.create_future()

    def settle(exc: BaseException | None, result: Any = None) -> None:
        if done.cancelled():
            return
        if isinstance(exc, StopIteration):  # futures refuse StopIteration outright
            exc = RuntimeError("prompt ended unexpectedly")
        if exc is not None:
            done.set_exception(exc)
        else:
            done.set_result(result)

    def run() -> None:
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - relayed to the awaiting task
            loop.call_soon_threadsafe(settle, exc)
        else:
            loop.call_soon_threadsafe(settle, None, result)

    threading.Thread(target=run, daemon=True).start()
    return await done


def _api_keys_url(cfg) -> str:
    return f"{cfg.api_base.rstrip('/')}/dashboard/settings"


def _print_key_hint(cfg) -> None:
    print(f"  Grab your API key from {_api_keys_url(cfg)} → API Keys tab")


# Braille "dots" spinner frames.
_SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_VERBOSE = False  # set by --verbose; the spinner would redraw over trace lines


@contextlib.asynccontextmanager
async def _spinner(label: str):
    """Show an animated status line for the duration of a block."""
    if not _ansi_ok() or _VERBOSE:
        # Pipes, logs, CI, consoles that cannot redraw a line, and --verbose.
        print(f"  {label}…")
        yield
        return

    colour = _colour_ok()
    cyan, dim, reset = ("\033[36m", "\033[2m", "\033[0m") if colour else ("", "", "")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    started = loop.time()

    async def spin() -> None:
        frame = 0
        sys.stdout.write("\033[?25l")  # hide cursor
        while not stop.is_set():
            elapsed = int(loop.time() - started)
            timer = f" {dim}· {elapsed}s{reset}" if elapsed else ""
            glyph = _SPIN_FRAMES[frame % len(_SPIN_FRAMES)]
            line = f"  {cyan}{glyph}{reset} {label}{timer}"
            sys.stdout.write("\r" + line + "\033[K")
            sys.stdout.flush()
            frame += 1
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=0.08)
        sys.stdout.write("\r\033[K\033[?25h")  # clear line, show cursor
        sys.stdout.flush()

    task = asyncio.create_task(spin())
    try:
        yield
    finally:
        stop.set()
        await task


def _devkit_note(message: str) -> None:
    print(f"  {message}")


def _devkit_guide() -> int:
    print(
        "openhome devkit — set up and check an OpenHome DevKit\n"
        "\n"
        "  openhome devkit onboard    Put a DevKit on WiFi and sign it in to your\n"
        "                             account, over Bluetooth. Run this next to the\n"
        "                             device, with it powered on.\n"
        "  openhome devkit status     Ask OpenHome how your DevKit is doing.\n"
        "                             Works from anywhere once it is set up.\n"
        "\n"
        "Before onboarding:\n"
        "  • run `openhome login` so your API key can be filled in for you\n"
        "  • have your WiFi password to hand (2.4GHz networks are safest)\n"
        "  • enable Bluetooth on this computer\n"
    )
    return 0


# ── output blocks ──────────────────────────────────────────────────────
_ANSI: bool | None = None


def _ansi_ok() -> bool:
    """Whether the terminal renders escape codes, enabling them on Windows if needed."""
    global _ANSI
    if _ANSI is not None:
        return _ANSI
    _ANSI = sys.stdout.isatty()
    if _ANSI and sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                _ANSI = False
            else:
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING
                _ANSI = bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
        except Exception:
            _ANSI = False
    return _ANSI


def _colour_ok() -> bool:
    """Colour only when a terminal will render it, and NO_COLOR is unset."""
    return _ansi_ok() and not os.environ.get("NO_COLOR")


def _dot(ok: bool) -> str:
    """A green/red indicator, or a plain marker where colour is unavailable."""
    if not _colour_ok():
        return "*" if ok else "!"
    return "\033[32m●\033[0m" if ok else "\033[31m●\033[0m"


def _state(ok: bool, yes: str, no: str) -> str:
    return f"{_dot(ok)} {yes if ok else no}"


def _print_networks(networks: list) -> None:
    print(f"\n  {'#':<4}{'Network':<28}{'Signal':<15}Security")
    for idx, net in enumerate(networks, 1):
        filled = max(0, min(8, net.signal // 13))
        bars = "▓" * filled + "░" * (8 - filled)
        security = "open" if net.is_open else (net.security or "secured")
        here = f"   {_dot(True)} connected" if net.connected else ""
        print(f"  {idx:<4}{net.ssid[:27]:<28}{bars} {net.signal:>3}%   {security:<10}{here}".rstrip())
    print()


def _print_overview(status, *, device: str = "", ssid: str = "", title: str = "DevKit") -> None:
    """The status block shared by `devkit status` and the end of onboarding."""
    print(f"\n{_dot(status.online)} {title}")
    if device:
        print(f"  Device    : {device}")
    if ssid:
        print(f"  WiFi      : {ssid}")
    if status.ip_address:
        print(f"  IP        : {status.ip_address}")
    if status.firmware:
        print(f"  Firmware  : {status.firmware}")
    print(f"  Agent     : {_state(status.agent_connected, 'connected', 'not connected')}")
    if status.local_mode:
        print("  Mode      : local")
    cells = []
    for name in ("cpu", "ram", "disk"):
        metric = status.metrics.get(name)
        if not metric:
            continue
        pct = metric.percent
        detail = f"{metric.used:g}/{metric.total:g} {metric.unit}".strip()
        label = f"{name.upper()}: {pct}%" if pct is not None else f"{name.upper()}:"
        # CPU is already a percentage; used/total adds nothing there.
        cells.append(label if name == "cpu" else f"{label} ({detail})")
    if cells:
        print("  " + "    ".join(cells))
    if status.timestamp:
        print(f"  Updated   : {status.timestamp}")


async def _devkit_read_state(kit, cfg):
    """Read the DevKit's WiFi and account state. Best effort: failures are ignored."""
    from . import devkit

    wifi, key = devkit.WifiStatus(), devkit.ApiKeyStatus()
    async with _spinner("Reading the DevKit's current state"):
        try:
            wifi = await kit.wifi_status()
        except DevKitError:
            pass
        try:
            key = await kit.api_key_status()
        except DevKitError:
            pass

    signed_in = ""
    if key.configured:
        # Bounded: HTTP retries on server errors can otherwise take over a minute.
        async with _spinner("Checking which account it is signed in to"):
            try:
                signed_in = await asyncio.wait_for(
                    _ask(_describe_signed_in, key, cfg), timeout=12.0
                )
            except asyncio.TimeoutError:
                signed_in = f"{key.key_prefix}…" if key.key_prefix else "signed in"
    return wifi, key, signed_in


def _describe_signed_in(key, cfg) -> str:
    """Describe the account the DevKit is signed in to.

    The DevKit reports only its key's prefix. If that matches the saved key,
    the account can be looked up by name.
    """
    fragment = f"{key.key_prefix}…" if key.key_prefix else "signed in (key not shown)"
    saved = cfg.api_key or ""
    if key.key_prefix and saved.startswith(key.key_prefix):
        user, _error = _lookup_account(saved)
        if user:
            # Same key as the saved one, so it can be masked in full.
            who = user.display_name
            if user.username and user.username != who:
                who = f"{who} ({user.username})"
            return f"{who} — {_mask(saved)}"
        # Our key, but the account lookup failed.
        return f"{_mask(saved)} (account details unavailable right now)"
    if saved and key.key_prefix:
        # Only the key's prefix is known, so the owner can't be named.
        return f"another account ({fragment})"
    return fragment


def _print_devkit_state(wifi, key, signed_in: str = "") -> None:
    """Print the DevKit's current state; WiFi is shown only when the DevKit reports it."""
    print("\nCurrent state")
    if wifi.is_connected:
        ssid = wifi.ssid
        print(f"  WiFi      : {_dot(True)} joined {ssid!r}" if ssid
              else f"  WiFi      : {_dot(True)} connected")
    if key.configured:
        print(f"  Signed in : {_dot(True)} {signed_in}")
    else:
        print(f"  Signed in : {_dot(False)} not yet")


# ── steps ──────────────────────────────────────────────────────────────
async def _devkit_pick_device(devkit, args):
    """Find the DevKit to talk to, or raise DeviceNotFound."""
    wanted = (getattr(args, "device", None) or "").strip()
    if wanted:
        print(f"Looking for {wanted}…")
        devices = await devkit.scan_devices(timeout=args.scan_timeout, strict=False)
        for dev in devices:
            if wanted.lower() in (dev.name.lower(), dev.address.lower()):
                return dev
        raise DeviceNotFound(
            f"Couldn't find a DevKit called {wanted!r} nearby. "
            "Make sure it's switched on and close by."
        )

    while True:
        print("Scanning for DevKits…")
        devices = await devkit.scan_devices(
            timeout=args.scan_timeout, on_progress=_devkit_note
        )

        if not devices:
            print(
                "  No DevKit found nearby.\n"
                "  • is it powered on and within a few metres?\n"
                "  • is Bluetooth enabled on this computer?\n"
                "  • if it is already set up, try `openhome devkit status` instead."
            )
            if sys.stdin.isatty() and await _ask(_confirm, "  Scan again?"):
                continue
            raise DeviceNotFound("No DevKit found nearby.")

        if len(devices) == 1:
            print(f"  using {devices[0].name}")
            return devices[0]

        _require_interactive("Pass --device <address> to choose one non-interactively.")
        print(f"\n  {'#':<4}{'Device':<24}Signal")
        for idx, dev in enumerate(devices, 1):
            print(f"  {idx:<4}{dev.name[:23]:<24}{dev.rssi} dBm")
        print()

        rescan = False
        while not rescan:
            choice = (await _ask(
                _prompt, "  Which DevKit? (r = rescan)", default="1"
            )).strip().lower()
            if choice in ("r", "rescan"):
                rescan = True
            elif choice.isdigit() and 1 <= int(choice) <= len(devices):
                return devices[int(choice) - 1]
            else:
                print("  enter a number from the list, or r to scan again.")


async def _devkit_wifi(kit) -> str | None:
    """Put the DevKit on WiFi. Returns the SSID, or None if skipped."""
    _require_interactive("Run `openhome devkit onboard` in a terminal.")
    networks: list | None = None
    retry = None  # network whose password was wrong; ask for it again
    while True:
        if networks is None:
            print()
            try:
                async with _spinner("Scanning for WiFi networks"):
                    with kit.muted():
                        networks = await kit.scan_networks()
                print(f"  ✓ {len(networks)} network(s) found")
            except ScanFailed as exc:
                print(f"  ✗ {exc}")
                if not await _ask(_confirm, "  Scan again?"):
                    return None
                continue
        if not networks:
            print("  no networks found.")
            if not await _ask(_confirm, "  Scan again?"):
                return None
            networks = None
            continue

        if retry is not None:
            net, retry = retry, None
        else:
            _print_networks(networks)
            while True:
                choice = (await _ask(_prompt, "  Which network? (r = rescan, q = skip)")).strip().lower()
                if choice in ("q", "quit", "skip"):
                    return None
                if choice in ("r", "rescan") or (
                    choice.isdigit() and 1 <= int(choice) <= len(networks)
                ):
                    break
                print(f"  enter a number from 1 to {len(networks)}, r or q.")
            if choice in ("r", "rescan"):
                networks = None
                continue
            net = networks[int(choice) - 1]

        password = ""
        if not net.is_open:
            password = await _ask(_prompt_secret, f"  Password for {net.ssid!r}")
            if not password:
                print("  a password is required for a secured network.")
                continue

        print()
        try:
            async with _spinner(f"Connecting the DevKit to {net.ssid!r}"):
                with kit.muted():
                    status = await kit.join_wifi(net.ssid, password)
        except ConnectionLost as exc:
            print(f"  ! {exc}")
            if not await _ask(_confirm, "  Reconnect and try again?"):
                return None
            try:
                await kit.reconnect()
            except DevKitError as retry_exc:
                print(f"  ✗ {retry_exc}")
                return None
            continue
        except WifiFailed as exc:
            print(f"  ✗ {exc}")
            if exc.wrong_password:
                # Same network, new password; the list stays one step away.
                if await _ask(_confirm, "  Enter the password again?"):
                    retry = net
                    continue
            # Scan results and the link survive; back to the list.
            if not await _ask(_confirm, "  Try again?"):
                return None
            continue

        if status is None:
            # Never report success without a verdict: a wrong password can end up here.
            print(f"  ! Couldn't confirm whether the DevKit joined {net.ssid!r}.")
            if await _ask(_confirm, "  Try again?"):
                continue
            return net.ssid
        print(f"  ✓ joined {net.ssid!r} — you should hear a tone")
        return net.ssid


def _lookup_account(api_key: str):
    """Return ``(user, None)``, or ``(None, reason)`` with a reason safe to show."""
    from .client import OpenHomeClient
    from .errors import ApiError

    try:
        client = OpenHomeClient(Config.from_env(api_key=api_key))
        return client.get_user(), None
    except ApiError as exc:
        if str(exc.code) in ("401", "403"):
            return None, "That API key wasn't recognised."
        return None, "Couldn't check the account right now."
    except OpenHomeError:
        return None, "Couldn't check the account right now."


async def _lookup_account_bounded(api_key: str, timeout: float = 12.0):
    """``_lookup_account`` off the event loop, with a time limit."""
    try:
        return await asyncio.wait_for(_ask(_lookup_account, api_key), timeout=timeout)
    except asyncio.TimeoutError:
        return None, "Couldn't check the account right now."


async def _devkit_api_key(
    kit, cfg, *, switching: bool = False, current_prefix: str = ""
) -> str | None:
    """Sign the DevKit in and return the key used, or None if the user gives up.

    ``current_prefix`` is the start of the key the DevKit already has; that
    account is never offered as the one to switch to.
    """
    _require_interactive("Run `openhome devkit onboard` in a terminal.")
    saved = cfg.api_key or ""

    def is_current(candidate: str) -> bool:
        return bool(current_prefix) and candidate.startswith(current_prefix)

    print("\nSwitch account" if switching else "\nSign in")
    key = ""
    if saved and is_current(saved):
        pass  # already on the saved account: go straight to entering another key
    elif saved:
        async with _spinner("Checking your saved account"):
            user, error = await _lookup_account_bounded(saved)
        print(f"  Key       : {_mask(saved)}")
        if user:
            print(f"  Account   : {user.describe()}")
            if await _ask(_confirm, "\n  Use this account?"):
                key = saved
        else:
            print(f"  Account   : {error}")
            if await _ask(_confirm, "\n  Use the saved key anyway?"):
                key = saved
    else:
        print("  No account is saved on this computer.")
        print("  Run `openhome login` to save one, or paste a key below.")

    while not key:
        _print_key_hint(cfg)
        entered = await _ask(_prompt_secret, "  Enter your API key")
        if not entered:
            print("  an API key is required.")
            if not await _ask(_confirm, "  Try again?"):
                return None
            continue
        # Look the key up before sending, so a wrong key is caught here.
        user, error = await _lookup_account_bounded(entered)
        if not user:
            print(f"  ✗ {error}")
            if not await _ask(_confirm, "  Try a different key?"):
                return None
            continue
        if is_current(entered):
            print(f"  {user.describe()} is the account it's already signed in to.")
            continue
        print(f"  ✓ that key belongs to {user.describe()}")
        if await _ask(_confirm, "  Send it to the DevKit?"):
            key = entered

    print()
    while True:
        try:
            async with _spinner("Signing the DevKit in"):
                with kit.muted():
                    status = await kit.set_api_key(key)
        except ApiKeyRejected as exc:
            print(f"  ✗ {exc}")
            if not await _ask(_confirm, "  Enter a different key?"):
                return None
            _print_key_hint(cfg)
            entered = await _ask(_prompt_secret, "  Enter your API key")
            if not entered:
                return None
            # Check a replacement key the same way before sending it.
            user, error = await _lookup_account_bounded(entered)
            if not user:
                print(f"  ✗ {error}")
                continue
            print(f"  ✓ that key belongs to {user.describe()}")
            key = entered
            continue
        except ConnectionLost as exc:
            # A valid key restarts the DevKit's services, which can drop the link.
            print(f"  ! {exc}")
            if not await _ask(_confirm, "  Reconnect and try again?"):
                return None
            try:
                await kit.reconnect()
            except DevKitError as retry_exc:
                print(f"  ✗ {retry_exc}")
                return None
            continue
        if status is None:
            print("  ✓ Signing in — this can take a moment")
        else:
            print("  ✓ Signed in")
        return key


async def _devkit_verify(cfg, *, device: str = "", ssid: str = "") -> None:
    """Wait for the DevKit to report in to OpenHome and show its status."""
    from . import devkit

    print()
    try:
        async with _spinner("Waiting for the DevKit to come online"):
            status = await devkit.wait_until_online(cfg, timeout=90.0)
    except DeviceOffline:
        print(
            "  The DevKit is still starting up.\n"
            "  Give it a minute, then run: openhome devkit status"
        )
        return
    except OpenHomeError as exc:
        # The DevKit was set up either way, so this is a note, not a failure.
        print(
            f"  {exc}\n"
            "  Your DevKit is set up — we just couldn't confirm it's online.\n"
            "  Check again later with: openhome devkit status"
        )
        return
    _print_overview(status, device=device, ssid=ssid, title="DevKit ready")


# ── commands ───────────────────────────────────────────────────────────
async def _devkit_onboard(args: argparse.Namespace) -> int:
    from . import devkit

    if not sys.stdin.isatty():
        _err("`openhome devkit onboard` is interactive — run it in a terminal.")
        return 1

    cfg = Config.from_env()
    device = await _devkit_pick_device(devkit, args)
    name = device if isinstance(device, str) else device.name

    print(f"\nConnecting to {name}…")
    ssid = None
    key = None
    async with devkit.DevKit(device, on_progress=_devkit_note) as kit:
        print("  ✓ connected")
        wifi_state, key_state, signed_in = await _devkit_read_state(kit, cfg)
        _print_devkit_state(wifi_state, key_state, signed_in)

        change_wifi = True
        if wifi_state.is_connected:
            ssid = wifi_state.ssid or None
            change_wifi = await _ask(_confirm, "\n  Change the WiFi network?", False)
        if change_wifi:
            joined = await _devkit_wifi(kit)
            if joined is None and not wifi_state.is_connected:
                print("\nSkipped WiFi — the DevKit needs it to reach your account.")
            ssid = joined or ssid

        if not kit.is_connected:
            # The key still has to be sent, so restore a link dropped during WiFi.
            try:
                async with _spinner("Reconnecting to the DevKit"):
                    await kit.reconnect()
            except DevKitError:
                _err("Couldn't reconnect to the DevKit.")
                print("Run `openhome devkit onboard` again to finish signing it in.")
                return 1

        set_key = True
        if key_state.configured:
            set_key = await _ask(_confirm, "\n  Switch account?", False)
        if set_key:
            key = await _devkit_api_key(
                kit, cfg, switching=key_state.configured, current_prefix=key_state.key_prefix
            )
            if key is None:
                print("\nStopped before signing in. Run it again when you're ready.")
                return 1

    # Checking the DevKit is online needs its own account's key: the one just
    # sent, or the saved one if the DevKit is signed in with it.
    logged_in = bool(cfg.api_key)
    prefix = key_state.key_prefix
    saved_matches = logged_in and (not prefix or cfg.api_key.startswith(prefix))
    check_key = key or (cfg.api_key if saved_matches else None)
    if not check_key:
        if logged_in:
            print(
                "\nYour DevKit is set up, but it's signed in to another account,\n"
                "  so its status can't be checked from here."
            )
        else:
            print(
                "\nYour DevKit is set up.\n"
                "  Log in with `openhome login` to check it's online,\n"
                "  then run: openhome devkit status"
            )
        return 0

    await _devkit_verify(Config.from_env(api_key=check_key), device=name, ssid=ssid or "")
    if not logged_in:
        # The key was typed for this run only; `devkit status` won't find it later.
        print(
            "\n  Log in with `openhome login` to check on your DevKit any time\n"
            "  with `openhome devkit status`."
        )
    return 0


async def _devkit_status(args: argparse.Namespace) -> int:
    from . import devkit

    cfg = Config.from_env()
    while True:
        try:
            _print_overview(await devkit.cloud_status(cfg), title="DevKit online")
        except DeviceOffline:
            print(
                f"\n{_dot(False)} DevKit offline\n"
                "  If you just set it up, give it a minute to come online.\n"
                "  Not set up yet? Run `openhome devkit onboard`."
            )
            if not args.watch:
                return 1
        if not args.watch:
            return 0
        await asyncio.sleep(20.0)


def _save_terminal():
    """Snapshot the terminal settings (POSIX), so they can be put back on exit."""
    if sys.platform == "win32" or not sys.stdin.isatty():
        return None
    try:
        import termios

        return termios.tcgetattr(sys.stdin.fileno())
    except Exception:  # termios.error is not an OSError
        return None


def _restore_terminal(saved) -> None:
    # A password prompt interrupted by Ctrl-C dies with echo still switched off;
    # its own cleanup runs on a thread that never gets the chance.
    if saved is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved)
    except Exception:  # best effort: never mask the real exit status
        pass


def cmd_devkit(args: argparse.Namespace) -> int:
    global _VERBOSE
    action = getattr(args, "devkit_action", None)
    if action is None:
        return _devkit_guide()
    try:
        from . import devkit
    except ImportError:
        # An update pulled in without reinstalling leaves `bleak` uninstalled.
        _err("Bluetooth support isn't included in this installation.")
        if sys.platform == "win32":
            print("Update the OpenHome CLI by reinstalling it, then try again.")
        else:
            print(
                "Update the OpenHome CLI by re-running the installer:\n"
                "  curl -fsSL https://app.openhome.com/install.sh | sh"
            )
        return 1
    if getattr(args, "verbose", False):
        _VERBOSE = True
        devkit.enable_trace(lambda line: print(line, file=sys.stderr, flush=True))
    saved_tty = _save_terminal()
    try:
        if action == "onboard":
            return asyncio.run(_devkit_onboard(args))
        if action == "status":
            return asyncio.run(_devkit_status(args))
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    finally:
        _restore_terminal(saved_tty)
    _err(f"unknown devkit action: {action}")
    return 1


# ── parser ─────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openhome",
        description="Link this abilities repo with your OpenHome account.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Save and verify your API key")
    p_login.add_argument("--api-key", help="API key (else prompted)")
    p_login.add_argument("--jwt", help="Browser session token for save/upload endpoints")
    p_login.set_defaults(func=cmd_login)

    sub.add_parser("agents", help="List agents on the account").set_defaults(
        func=cmd_agents
    )
    sub.add_parser("templates", help="List available templates").set_defaults(
        func=cmd_templates
    )

    p_create = sub.add_parser("create", help="Scaffold a new ability from a template")
    p_create.add_argument("name", help="ability name (lowercase-hyphen)")
    p_create.add_argument("--template", "-t", default="basic-template")
    p_create.add_argument("--dest", help="parent dir (default: user/)")
    p_create.add_argument("--overwrite", action="store_true")
    p_create.add_argument("--triggers", help="comma-separated trigger words (else prompted)")
    p_create.add_argument("--description", "-d", help="marketplace description")
    p_create.add_argument(
        "--category",
        "-c",
        default=None,
        choices=list(VALID_CATEGORIES),
        help="default: the template's category, else 'skill'",
    )
    p_create.add_argument("--agent", help="agent/personality id to install into")
    p_create.add_argument(
        "--no-push", action="store_true", help="only scaffold locally, don't push"
    )
    p_create.set_defaults(func=cmd_create)

    p_community = sub.add_parser(
        "push_to_community",
        aliases=["push-to-community"],
        help="Copy a user/ ability into community/ for a contribution PR",
    )
    p_community.add_argument("name", help="ability folder name in user/")
    p_community.add_argument("--overwrite", action="store_true")
    p_community.set_defaults(func=cmd_push_to_community)

    p_sync = sub.add_parser(
        "sync", help="Pull your account's abilities into the user/ workspace"
    )
    p_sync.add_argument("--dest", help="target dir (default: user/)")
    p_sync.add_argument(
        "--force", action="store_true", help="overwrite local code with the account's version"
    )
    p_sync.add_argument(
        "--prune",
        action="store_true",
        help="delete local folders for abilities no longer on the account",
    )
    p_sync.set_defaults(func=cmd_sync)

    p_push = sub.add_parser("push", help="Save/commit an ability to the account")
    p_push.add_argument("folder", help="path to the ability folder")
    p_push.add_argument("--name", help="ability name (default: folder name)")
    p_push.add_argument("--description", "-d", help="marketplace description")
    p_push.add_argument(
        "--category",
        "-c",
        default=None,
        choices=list(VALID_CATEGORIES),
        help="on update: change the category; on create: default from the template",
    )
    p_push.add_argument("--triggers", help="comma-separated trigger words (create only)")
    p_push.add_argument("--agent", help="agent/personality id to install into (create only)")
    p_push.add_argument("--image", help="path to a marketplace icon (png/jpg, create only)")
    p_push.add_argument(
        "--commit",
        action="store_true",
        help="on update: commit a version instead of saving a draft",
    )
    p_push.add_argument("-m", "--message", help="commit message (with --commit)")
    p_push.set_defaults(func=cmd_push)

    sub.add_parser("list", help="List abilities on the account").set_defaults(
        func=cmd_list
    )

    p_trig = sub.add_parser("set-triggers", help="Update an ability's trigger words")
    p_trig.add_argument("id", help="ability id or name")
    p_trig.add_argument("triggers", help="comma-separated trigger words")
    p_trig.set_defaults(func=cmd_set_triggers)

    p_en = sub.add_parser("enable", help="Enable an installed ability")
    p_en.add_argument("id")
    p_en.set_defaults(func=cmd_enable)

    p_dis = sub.add_parser("disable", help="Disable an installed ability")
    p_dis.add_argument("id")
    p_dis.set_defaults(func=cmd_disable)

    p_del = sub.add_parser("delete", help="Delete an ability (account + local folder)")
    p_del.add_argument("id", help="ability id or name")
    p_del.add_argument(
        "--keep-local", action="store_true", help="don't remove the local user/ folder"
    )
    p_del.set_defaults(func=cmd_delete)

    p_call = sub.add_parser(
        "call", help="Voice call an agent (mic + speakers); --say for one-shot text"
    )
    p_call.add_argument(
        "agent", nargs="?", help="agent id (default: 0 = default agent; or OPENHOME_AGENT_ID)"
    )
    p_call.add_argument("--say", help="one-shot: send this text and print the reply (no audio)")
    p_call.add_argument("--timeout", type=float, default=30.0, help="--say reply timeout")
    p_call.set_defaults(func=cmd_call)

    p_chat = sub.add_parser("chat", help="Interactive voice session with an agent")
    p_chat.add_argument("agent", nargs="?", help="agent id (or OPENHOME_AGENT_ID)")
    p_chat.set_defaults(func=cmd_chat)
    
    p_local = sub.add_parser(
        "local", help="Run a local bridge that executes requests from your agent"
    )
    local_sub = p_local.add_subparsers(dest="local_action", required=True)

    p_l_start = local_sub.add_parser("start", help="Start the bridge in the background")
    p_l_start.add_argument("--client-id", default="laptop", help="device id (default: laptop)")
    p_l_start.add_argument("--role", default="agent")
    p_l_start.add_argument("--timeout", type=float, default=30.0, help="per-request timeout (s)")

    local_sub.add_parser("stop", help="Stop the background bridge")
    local_sub.add_parser("status", help="Show whether the bridge is running")

    p_l_logs = local_sub.add_parser("logs", help="Stream the bridge's logs (Ctrl-C to stop)")
    p_l_logs.add_argument("--no-follow", action="store_true", help="print recent logs and exit")
    p_l_logs.add_argument("-n", "--lines", type=int, default=50, help="history lines to show first")

    p_l_run = local_sub.add_parser("run", help="Run the bridge in the foreground (debugging)")
    p_l_run.add_argument("--client-id", default="laptop")
    p_l_run.add_argument("--role", default="agent")
    p_l_run.add_argument("--timeout", type=float, default=30.0)
    p_l_run.add_argument("--once", action="store_true", help="don't reconnect on drop")

    p_local.set_defaults(func=cmd_local)

    p_devkit = sub.add_parser(
        "devkit", help="Set up and check an OpenHome DevKit"
    )
    # Unlike `local`, the action is optional: bare `openhome devkit` prints a guide.
    devkit_sub = p_devkit.add_subparsers(dest="devkit_action")

    p_dk_onboard = devkit_sub.add_parser(
        "onboard", help="Interactive Bluetooth setup (WiFi + API key)"
    )
    p_dk_onboard.add_argument(
        "--device", help="DevKit name or Bluetooth address to use, without asking"
    )
    p_dk_onboard.add_argument(
        "--scan-timeout", type=float, default=10.0, help="seconds to scan for DevKits"
    )
    p_dk_onboard.add_argument(
        "-v", "--verbose", action="store_true",
        help="log every Bluetooth exchange with timings (to stderr)",
    )

    p_dk_status = devkit_sub.add_parser(
        "status", help="Check how your DevKit is doing"
    )
    p_dk_status.add_argument(
        "--watch", action="store_true", help="keep polling until Ctrl-C"
    )
    p_dk_status.add_argument(
        "-v", "--verbose", action="store_true", help="log the status exchange (to stderr)"
    )

    p_devkit.set_defaults(func=cmd_devkit)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NotAuthenticatedError as exc:
        _err(str(exc))
        _err("Run `openhome login` or set OPENHOME_API_KEY.")
        return 2
    except SessionExpiredError as exc:
        _err(str(exc))
        _err("Re-grab your JWT: copy(localStorage.getItem('access_token')) on app.openhome.com")
        return 2
    except OpenHomeError as exc:
        _err(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())