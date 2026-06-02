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

The CLI only formats input/output; all real logic lives in the library.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import OpenHomeClient
from .config import Config
from .errors import NotAuthenticatedError, OpenHomeError, SessionExpiredError


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [w.strip() for w in value.split(",") if w.strip()]


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


def cmd_templates(args: argparse.Namespace) -> int:
    client = OpenHomeClient()
    for t in client.list_templates():
        print(f"{t.name}\t({t.source})")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    client = OpenHomeClient()
    dest = client.create_from_template(
        args.name,
        args.template,
        dest_dir=args.dest,
        overwrite=args.overwrite,
    )
    print(f"✓ Created ability at {dest}")
    print(f"  Edit {dest / 'main.py'}, then: openhome push {dest}")
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
    from .workspace import read_manifest

    client = OpenHomeClient()
    folder = Path(args.folder)
    manifest = read_manifest(folder)
    cap_id = manifest.get("capability_id")

    # Existing ability → update in place (never delete + re-create).
    if cap_id:
        result = client.update_ability(
            folder, commit=args.commit, message=args.message or ""
        )
        verb = "Committed" if args.commit else "Saved (draft)"
        print(f"✓ {verb} update to '{manifest.get('name', folder.name)}' (capability_id {cap_id})")
        detail = result.get("detail") if isinstance(result, dict) else None
        if detail:
            print(f"  {detail}")
        new_manifest = read_manifest(folder)
        print(f"  release: {new_manifest.get('version')} (release_id {new_manifest.get('release_id')})")
        return 0

    # New ability → create.
    name = args.name or manifest.get("name") or folder.name
    triggers = _split_csv(args.triggers) or manifest.get("trigger_words") or []
    result = client.save_ability(
        folder,
        name=name,
        description=args.description or manifest.get("description") or f"{name} ability",
        category=args.category or manifest.get("category") or "skill",
        trigger_words=triggers,
        personality_id=args.agent,
        image=args.image,
    )
    print(f"✓ Created ability '{name}'")
    if result.capability_id:
        print(f"  capability_id: {result.capability_id}")
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
    OpenHomeClient().delete_ability(args.id)
    print(f"✓ Deleted {args.id}")
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    client = OpenHomeClient()
    agent_id = args.agent or client.config.agent_id
    if not agent_id:
        _err("No agent id. Pass AGENT_ID or set OPENHOME_AGENT_ID.")
        return 1
    print(f"→ {args.phrase}")
    reply = client.call(agent_id, args.phrase, timeout=args.timeout)
    print(f"← {reply}" if reply else "← (no response within timeout)")
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
    p_create.set_defaults(func=cmd_create)

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
        choices=["skill", "brain_skill", "background_daemon", "local"],
        help="default: manifest value, else 'skill'",
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

    p_del = sub.add_parser("delete", help="Delete an ability")
    p_del.add_argument("id")
    p_del.set_defaults(func=cmd_delete)

    p_call = sub.add_parser("call", help="Send one phrase to an agent (voice stream)")
    p_call.add_argument("agent", nargs="?", help="agent id (or OPENHOME_AGENT_ID)")
    p_call.add_argument("phrase", help="what to say")
    p_call.add_argument("--timeout", type=float, default=30.0)
    p_call.set_defaults(func=cmd_call)

    p_chat = sub.add_parser("chat", help="Interactive voice session with an agent")
    p_chat.add_argument("agent", nargs="?", help="agent id (or OPENHOME_AGENT_ID)")
    p_chat.set_defaults(func=cmd_chat)

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
