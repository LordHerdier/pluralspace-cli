#!/usr/bin/env python3
"""
Pluralspace CLI

Usage:
    pluralspace login [--email EMAIL]   Log in (uses the pass entry, offers to create it)
    pluralspace logout                  Drop the local session
    pluralspace whoami                  Show the logged-in account
    pluralspace members [-q TEXT]       List members (--archived, --fronting, --json)
    pluralspace member NAME             Show one member's profile (fuzzy match ok) (--json for everything)
    pluralspace mood [NAME]             Show, set (NAME), --list, or --clear the mood
    pluralspace fronting                Show current fronters (alias: who)
    pluralspace history [--month YYYY-MM]  Front history for this month
    pluralspace switch NAME[:TYPE]...   Set the front (--add keeps, --replace skips the confirmation)
    pluralspace end                     End all fronts

Credentials live in pass at pluralspace/<profile>:
    <password>
    email: you@example.com
"""

import argparse
import getpass
import json
import sys
import textwrap
from typing import Callable, TypeVar

from . import __version__
from .api_client import APIError, AuthError, PluralspaceAPI
from .credentials import CredentialError, Credentials, PassStore
from .errors import UsageError
from .fronts import format_front_plan, plan_fronts, replaced_names
from .render import (
    _day,
    _field_value,
    _format_relationship,
    front_member_label,
    front_type_name,
    member_flags,
)
from .resolve import (  # noqa: F401  (re-exported for tests)
    match_member_exact,
    resolve_front_type,
    resolve_member,
    resolve_mood,
)

T = TypeVar("T")


def _authed(api: PluralspaceAPI, store: PassStore, fn: Callable[[], T]) -> T:
    """Run fn; on an expired session, re-login from pass and retry once."""
    try:
        return fn()
    except AuthError:
        if not store.exists():
            raise
        creds = store.load()
        api.login(creds.email, creds.password)
        return fn()


def cmd_login(args, api: PluralspaceAPI, store: PassStore) -> int:
    if store.exists() and not args.email:
        creds = store.load()
    else:
        email = args.email or input("Email: ").strip()
        password = getpass.getpass("Password: ")
        creds = Credentials(email, password)
    api.login(creds.email, creds.password)
    user = api.whoami()
    print(f"Logged in as {user.get('name')} ({user.get('email')})")
    if not store.exists() or args.email:
        if input(
            f"Save credentials to pass ({store.entry})? [Y/n] "
        ).strip().lower() in ("", "y", "yes"):
            store.save(creds)
            print(f"Saved to pass: {store.entry}")
    return 0


def cmd_logout(args, api: PluralspaceAPI, store: PassStore) -> int:
    api.logout()
    print("Session cleared (pass entry left in place)")
    return 0


def cmd_whoami(args, api: PluralspaceAPI, store: PassStore) -> int:
    user = _authed(api, store, api.whoami)
    print(f"{user.get('name')} <{user.get('email')}> [{user.get('id')}]")
    return 0


DEFAULT_FRONT_TYPE = "front"


def confirm_replace(names, stdin=None, stdout=None) -> None:
    """Refuse to silently end fronters. Prompts on a terminal; otherwise errors."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stderr
    listed = ", ".join(names)
    hint = "pass --replace to confirm, or --add to keep them"
    if not stdin.isatty():
        raise UsageError(f"this switch would end current fronters ({listed}); {hint}")
    stdout.write(
        f"This will end current fronters: {listed}\n(or use --add to keep them)\n"
    )
    stdout.write("Replace the front set? [y/N] ")
    stdout.flush()
    if stdin.readline().strip().lower() not in ("y", "yes"):
        raise UsageError("aborted; nothing changed")


def cmd_switch(args, api: PluralspaceAPI, store: PassStore) -> int:
    def run():
        types = api.front_types()
        default = resolve_front_type(types, args.type or DEFAULT_FRONT_TYPE)
        current = api.current_fronts()
        fronters = {}
        if args.add:
            for f in current:
                fronters[f["member_id"]] = f["system_front_type_id"]
        labels = {}
        for ref in args.members:
            name, _, type_ref = ref.partition(":")
            member = resolve_member(api, name, exact=True)
            ftype = resolve_front_type(types, type_ref) if type_ref else default
            fronters[member["id"]] = ftype["id"]
            labels[member["id"]] = (
                member.get("display_label")
                or member.get("display_name")
                or member.get("name")
            )
        if args.dry_run:
            print(
                "\n".join(
                    format_front_plan(
                        plan_fronts(current, fronters),
                        labels,
                        {t["id"]: t["name"] for t in types},
                        args.comment,
                        args.silent,
                    )
                )
            )
            return
        if not args.add and not args.replace:
            plan = plan_fronts(current, fronters)
            if plan.end:
                confirm_replace(replaced_names(plan))
        api.set_fronts(fronters, args.comment, args.silent)

    _authed(api, store, run)
    if not args.dry_run:
        return cmd_fronting(argparse.Namespace(json=False), api, store)
    return 0


def cmd_mood(args, api: PluralspaceAPI, store: PassStore) -> int:
    if args.list:
        moods = _authed(api, store, api.moods)
        if args.json:
            return _emit_json(moods)
        for m in moods:
            print(f"{m['name']:<12} {m.get('tagline', '')}")
        return 0
    if args.dry_run and not (args.clear or args.name):
        raise UsageError("--dry-run needs a mood NAME or --clear")
    if args.dry_run:

        def preview():
            before = api.atmosphere().get("mood_label") or "(none)"
            after = (
                "(none)" if args.clear else resolve_mood(api.moods(), args.name)["name"]
            )
            return before, after

        before, after = _authed(api, store, preview)
        print("Dry run: no changes made. Would:")
        if before.casefold() == after.casefold():
            print(f"  mood: {before} (unchanged)")
        else:
            print(f"  mood: {before} -> {after}")
        return 0
    if args.clear:
        _authed(api, store, api.clear_mood)
    elif args.name:
        _authed(
            api, store, lambda: api.set_mood(resolve_mood(api.moods(), args.name)["id"])
        )
    atmosphere = _authed(api, store, api.atmosphere)
    if args.json:
        return _emit_json(atmosphere)
    print(f"Mood: {atmosphere.get('mood_label') or '(none)'}")
    print(atmosphere.get("tagline", ""))
    return 0


def cmd_end(args, api: PluralspaceAPI, store: PassStore) -> int:
    if args.dry_run:
        current = _authed(api, store, api.current_fronts)
        print("\n".join(format_front_plan(plan_fronts(current, {}), {}, {})))
        return 0
    _authed(api, store, api.end_all)
    print("Nobody is fronting")
    return 0


def _emit_json(data) -> int:
    print(json.dumps(data, indent=2))
    return 0


def cmd_members(args, api: PluralspaceAPI, store: PassStore) -> int:
    members = _authed(
        api,
        store,
        lambda: api.members(args.query or "", args.archived, args.fronting, args.type),
    )
    if args.json:
        return _emit_json(members)
    for m in members:
        flags = member_flags(m, fronting=True)
        pronouns = f" ({m['pronouns']})" if m.get("pronouns") else ""
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        plain = (
            f"  name: {m['name']}"
            if m.get("name") and m["name"] != m["display_label"]
            else ""
        )
        print(f"{m['id'][-8:]}  {m['display_label']}{pronouns}{plain}{suffix}")
    print(f"{len(members)} members", file=sys.stderr)
    return 0


def cmd_member(args, api: PluralspaceAPI, store: PassStore) -> int:
    def run():
        member = resolve_member(api, args.name)
        return api.member(member["id"])

    props = _authed(api, store, run)
    if args.json:
        keys = (
            "member",
            "customFields",
            "assignedGroups",
            "relationships",
            "frontHistory",
            "connectedSystems",
            "currentLocation",
        )
        return _emit_json({k: props.get(k) for k in keys})
    m = props["member"]
    flags = member_flags(m, custom_label="custom front")
    print(
        m["display_label"]
        + (f" ({m['pronouns']})" if m.get("pronouns") else "")
        + (f"  [{', '.join(flags)}]" if flags else "")
    )
    if m.get("name") and m["name"] != m["display_label"]:
        print(f"name: {m['name']}")
    print(f"id: {m['id']}")
    if m.get("aliases"):
        print("aliases:", ", ".join(m["aliases"]))
    if m.get("role"):
        print("roles:", ", ".join(m["role"]))
    if props.get("assignedGroups"):
        print("groups:", ", ".join(g["name"] for g in props["assignedGroups"]))
    desc = (props.get("editState") or {}).get("description")
    if desc:
        if not args.full and len(desc) > 400:
            desc = desc[:400] + " … (--full for the rest)"
        print(f"\n{desc}")
    fields = [
        (c["name"], _field_value(c["value"])) for c in props.get("customFields", [])
    ]
    fields = [(n, v) for n, v in fields if v]
    if fields:
        print("\nFields:")
        for name, value in fields:
            if "\n" in value:
                print(f"  {name}:")
                print(textwrap.indent(value, "    "))
            else:
                print(f"  {name}: {value}")
    if props.get("relationships"):
        print("\nRelationships:")
        for r in props["relationships"]:
            print("  " + _format_relationship(r))
    history = props.get("frontHistory") or []
    if history:
        print("\nRecent fronts:")
        for h in history[: args.history]:
            end = "now" if not h.get("ended_at") else _day(h["ended_at"])
            others = [x["display_label"] for x in h["members"] if x["id"] != m["id"]]
            with_ = f"  with {', '.join(others)}" if others else ""
            print(
                f"  {_day(h['started_at'])} -> {end}  ({h.get('duration_human', '')})"
                f"  [{front_type_name(h)}]{with_}"
            )
    return 0


def cmd_fronting(args, api: PluralspaceAPI, store: PassStore) -> int:
    fronts = _authed(api, store, api.current_fronts)
    if args.json:
        return _emit_json(fronts)
    if not fronts:
        print("Nobody is fronting")
    for f in fronts:
        name = front_member_label(f)
        kind = front_type_name(f)
        note = f"  - {f['comment']}" if f.get("comment") else ""
        print(f"{name}  [{kind}]  since {_day(f['started_at'])}{note}")
    return 0


def cmd_history(args, api: PluralspaceAPI, store: PassStore) -> int:
    fronts = _authed(api, store, lambda: api.front_history(args.month))
    if args.json:
        return _emit_json(fronts)
    for f in fronts:
        name = front_member_label(f)
        kind = front_type_name(f)
        end = "now" if f.get("is_ongoing") else _day(f["ended_at"])
        print(f"{_day(f['started_at'])} -> {end}  {name}  [{kind}]")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="plsp", description="Pluralspace CLI")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="log in and optionally store credentials in pass")
    p.add_argument("--email")
    p.set_defaults(func=cmd_login)
    sub.add_parser("logout", help="drop the local session").set_defaults(
        func=cmd_logout
    )
    sub.add_parser("whoami", help="show the logged-in account").set_defaults(
        func=cmd_whoami
    )

    p = sub.add_parser("members", help="list members")
    p.add_argument("-q", "--query")
    p.add_argument("--archived", action="store_true")
    p.add_argument("--fronting", action="store_true", help="only current fronters")
    p.add_argument("--type", help="raw server-side type filter (default: alter)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_members)
    p = sub.add_parser("member", aliases=["m"], help="show one member's profile")
    p.add_argument("name", help="member name or id suffix")
    p.add_argument("--full", action="store_true", help="don't truncate the description")
    p.add_argument(
        "--history", type=int, default=5, help="recent fronts to show (default 5)"
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_member)
    p = sub.add_parser("fronting", aliases=["who", "w"], help="show current fronters")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fronting)
    p = sub.add_parser("switch", aliases=["sw"], help="set the current front")
    p.add_argument(
        "members",
        nargs="+",
        metavar="NAME[:TYPE]",
        help="exact member name or id suffix, optionally with a front type",
    )
    p.add_argument("--type", help="default front type (default: Front)")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--add", action="store_true", help="keep current fronters")
    grp.add_argument(
        "--replace",
        action="store_true",
        help="end current fronters not listed, without asking",
    )
    p.add_argument("-c", "--comment")
    p.add_argument("--silent", action="store_true", help="no notifications")
    p.add_argument(
        "--dry-run", action="store_true", help="show what would change, change nothing"
    )
    p.set_defaults(func=cmd_switch)
    p = sub.add_parser("mood", help="show, set or clear the system mood")
    p.add_argument("name", nargs="?", help="mood to set (exact name)")
    p.add_argument("--list", action="store_true", help="list available moods")
    p.add_argument("--clear", action="store_true", help="clear the current mood")
    p.add_argument(
        "--dry-run", action="store_true", help="show what would change, change nothing"
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_mood)
    p = sub.add_parser("end", help="end all fronts")
    p.add_argument(
        "--dry-run", action="store_true", help="show what would change, change nothing"
    )
    p.set_defaults(func=cmd_end)
    p = sub.add_parser("history", help="front history for this month")
    p.add_argument("--month", help="YYYY-MM (default: current)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    args = parser.parse_args(argv)
    api = PluralspaceAPI(args.profile, debug=args.debug)
    store = PassStore(args.profile)
    try:
        return args.func(args, api, store)
    except (AuthError, CredentialError, UsageError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except APIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        return 130


if __name__ == "__main__":
    sys.exit(main())
