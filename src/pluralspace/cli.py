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
    pluralspace switch NAME[:TYPE]...   Set the front (--add keeps current fronters)
    pluralspace end                     End all fronts

Credentials live in pass at pluralspace/<profile>:
    <password>
    email: you@example.com
"""

import argparse
import getpass
import html
import json
import re
import sys
import textwrap
from datetime import datetime, timezone
from typing import Callable, TypeVar

from . import __version__
from .api_client import APIError, AuthError, PluralspaceAPI
from .credentials import CredentialError, Credentials, PassStore

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
        if input(f"Save credentials to pass ({store.entry})? [Y/n] ").strip().lower() in ("", "y", "yes"):
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


def _id_matches(member_id: str, ref: str) -> bool:
    ref = ref.lower()
    return member_id.lower() == ref or (len(ref) >= 6 and member_id.lower().endswith(ref))


def resolve_front_type(types, ref: str) -> dict:
    """Match a front type by name or slug, case-insensitively."""
    hits = [t for t in types if ref.lower() in (t["name"].lower(), (t.get("slug") or "").lower())]
    if len(hits) != 1:
        names = ", ".join(t["name"] for t in types)
        raise CredentialError(f"front type '{ref}' not found; available: {names}"
                              if not hits else f"front type '{ref}' is ambiguous")
    return hits[0]


def match_member_exact(candidates, ref: str) -> list:
    """Members whose `name`, `display_name`, or `display_label` equals ref
    (case-insensitive, whole string), or whose id matches ref. No prefix or
    substring matching; this is what writes use."""
    low = ref.strip().lower()
    if not low:
        return []
    return [m for m in candidates
            if _id_matches(m["id"], low)
            or low in {(m.get(k) or "").strip().lower()
                       for k in ("name", "display_name", "display_label")} - {""}]


def _describe_member(m: dict) -> str:
    label = m.get("display_label") or m.get("display_name") or m.get("name") or "?"
    plain = m.get("name")
    named = f" aka {plain!r}" if plain and plain != label else ""
    return f"{label}{named} ({m['id'][-8:]})"


def resolve_member(api: PluralspaceAPI, ref: str, exact: bool = False) -> dict:
    """Resolve a name or id (or id suffix, as shown by `members`) to one member.

    exact=False (reads) falls back to a lone fuzzy search hit. exact=True
    (writes) only accepts a whole-string match on name/display name or an id;
    near misses are listed in the error but never used.
    """
    search = api.search_members(ref)
    if exact:
        # /members has the plain `name` but omits custom fronts; the search
        # has custom fronts but only the display label. Use both, keyed by id.
        merged = {m["id"]: m for m in search}
        merged.update({m["id"]: m for m in api.members()})
        hits = match_member_exact(merged.values(), ref)
        if not hits:
            near = ", ".join(_describe_member(m) for m in search)
            raise CredentialError(
                f"no member exactly matches '{ref}' (writes need an exact name or id)"
                + (f"; did you mean: {near}" if near else ""))
    else:
        exact_hits = match_member_exact(search, ref)
        hits = exact_hits or (search if len(search) == 1 else [])
        if not hits:
            # `members` lists ids by suffix; fall back to that listing for id lookups
            hits = [m for m in api.members() if _id_matches(m["id"], ref)]
        if not hits:
            raise CredentialError(f"no member matches '{ref}'")
    if len(hits) > 1:
        ids = ", ".join(_describe_member(m) for m in hits)
        raise CredentialError(f"'{ref}' is ambiguous: {ids}; use the id suffix")
    return hits[0]


def cmd_switch(args, api: PluralspaceAPI, store: PassStore) -> int:
    def run():
        types = api.front_types()
        default = resolve_front_type(types, args.type or DEFAULT_FRONT_TYPE)
        fronters = {}
        if args.add:
            for f in api.current_fronts():
                fronters[f["member_id"]] = f["system_front_type_id"]
        for ref in args.members:
            name, _, type_ref = ref.partition(":")
            member = resolve_member(api, name, exact=True)
            ftype = resolve_front_type(types, type_ref) if type_ref else default
            fronters[member["id"]] = ftype["id"]
        if args.dry_run:
            print(json.dumps({"fronters": fronters, "comment": args.comment,
                              "silent": args.silent}, indent=2))
            return
        api.set_fronts(fronters, args.comment, args.silent)

    _authed(api, store, run)
    if not args.dry_run:
        return cmd_fronting(argparse.Namespace(json=False), api, store)
    return 0


def resolve_mood(moods, ref: str) -> dict:
    """Match a mood by exact name (case-insensitive). Prefixes are not accepted."""
    low = ref.strip().lower()
    hits = [m for m in moods if m["name"].lower() == low]
    if len(hits) != 1:
        names = ", ".join(m["name"] for m in moods)
        raise CredentialError(f"mood '{ref}' " + ("not found" if not hits else "is ambiguous")
                              + f" (moods must match exactly); available: {names}")
    return hits[0]


def cmd_mood(args, api: PluralspaceAPI, store: PassStore) -> int:
    if args.list:
        moods = _authed(api, store, api.moods)
        if args.json:
            return _emit_json(moods)
        for m in moods:
            print(f"{m['name']:<12} {m.get('tagline', '')}")
        return 0
    if args.clear:
        _authed(api, store, api.clear_mood)
    elif args.name:
        _authed(api, store, lambda: api.set_mood(resolve_mood(api.moods(), args.name)["id"]))
    atmosphere = _authed(api, store, api.atmosphere)
    if args.json:
        return _emit_json(atmosphere)
    print(f"Mood: {atmosphere.get('mood_label') or '(none)'}")
    print(atmosphere.get("tagline", ""))
    return 0


def cmd_end(args, api: PluralspaceAPI, store: PassStore) -> int:
    _authed(api, store, api.end_all)
    print("Nobody is fronting")
    return 0


def _emit_json(data) -> int:
    print(json.dumps(data, indent=2))
    return 0


def _day(ts: str) -> str:
    """Format an API timestamp (UTC) in the system's local timezone."""
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts[:16].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def cmd_members(args, api: PluralspaceAPI, store: PassStore) -> int:
    members = _authed(api, store, lambda: api.members(
        args.query or "", args.archived, args.fronting, args.type))
    if args.json:
        return _emit_json(members)
    for m in members:
        flags = [f for f, on in (("fronting", m.get("active_front")),
                                 ("custom", m.get("is_custom_front")),
                                 ("pinned", m.get("is_pinned")),
                                 ("archived", m.get("is_archived"))) if on]
        pronouns = f" ({m['pronouns']})" if m.get("pronouns") else ""
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        plain = f"  name: {m['name']}" if m.get("name") and m["name"] != m["display_label"] else ""
        print(f"{m['id'][-8:]}  {m['display_label']}{pronouns}{plain}{suffix}")
    print(f"{len(members)} members", file=sys.stderr)
    return 0


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    return html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ").strip()


def _list_lines(items, style: str, depth: int = 0):
    for i, item in enumerate(items or [], 1):
        if isinstance(item, str):
            item = {"content": item}
        marker = f"{i}." if style == "ordered" else "-"
        yield "  " * depth + f"{marker} {_strip_html(item.get('content', ''))}"
        yield from _list_lines(item.get("items"), style, depth + 1)


def _block_lines(block: dict):
    """Render one Editor.js block as plain-text lines (media become a marker/URL)."""
    kind, data = block.get("type"), block.get("data") or {}
    if kind in ("paragraph", "header"):
        yield _strip_html(data.get("text", ""))
    elif kind == "quote":
        yield f"> {_strip_html(data.get('text', ''))}"
        if data.get("caption"):
            yield f"  — {_strip_html(data['caption'])}"
    elif kind == "list":
        yield from _list_lines(data.get("items"), data.get("style", "unordered"))
    elif kind == "table":
        for row in data.get("content", []):
            yield " | ".join(_strip_html(c) for c in row)
    elif kind == "columns":
        for col in data.get("cols", []):
            for b in col.get("blocks", []):
                yield from _block_lines(b)
    elif kind == "image":
        yield f"[image: {(data.get('file') or {}).get('url', '')}]"
    elif kind == "gallery":
        for img in data.get("images", []):
            yield f"[image: {(img.get('file') or {}).get('url', '')}]"
    elif kind == "delimiter":
        yield "---"


def editorjs_text(value) -> str:
    """Plain text for an Editor.js document (dict or JSON string); "" if empty or not one."""
    if isinstance(value, str):
        if not value.lstrip().startswith("{"):
            return value
        try:
            value = json.loads(value)
        except ValueError:
            return value
    if not isinstance(value, dict) or "blocks" not in value:
        return ""
    lines = [ln for b in value["blocks"] for ln in _block_lines(b)]
    # a document of nothing but delimiters/blank lines is empty
    if not any(ln and ln != "---" for ln in lines):
        return ""
    return "\n".join(ln for ln in lines if ln)


def _field_value(value):
    """Custom field values are a string, a list (padded with "") when multiple, or rich text."""
    if isinstance(value, list):
        return ", ".join(v for v in value if v)
    return editorjs_text(value) if value else ""


def _format_relationship(r: dict) -> str:
    other = r.get("other_member") or {}
    line = f"{r.get('label', '?')}: {other.get('display_label', '(hidden)')}"
    if r.get("cross_system"):
        line += "  [cross-system]"
    if r.get("notes"):
        line += f"  - {r['notes']}"
    return line


def cmd_member(args, api: PluralspaceAPI, store: PassStore) -> int:
    def run():
        member = resolve_member(api, args.name)
        return api.member(member["id"])

    props = _authed(api, store, run)
    if args.json:
        keys = ("member", "customFields", "assignedGroups", "relationships",
                "frontHistory", "connectedSystems", "currentLocation")
        return _emit_json({k: props.get(k) for k in keys})
    m = props["member"]
    flags = [f for f, on in (("custom front", m.get("is_custom_front")),
                             ("pinned", m.get("is_pinned")),
                             ("archived", m.get("is_archived"))) if on]
    print(m["display_label"] + (f" ({m['pronouns']})" if m.get("pronouns") else "")
          + (f"  [{', '.join(flags)}]" if flags else ""))
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
    fields = [(c["name"], _field_value(c["value"])) for c in props.get("customFields", [])]
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
        for h in history[:args.history]:
            end = "now" if not h.get("ended_at") else _day(h["ended_at"])
            others = [x["display_label"] for x in h["members"] if x["id"] != m["id"]]
            with_ = f"  with {', '.join(others)}" if others else ""
            print(f"  {_day(h['started_at'])} -> {end}  ({h.get('duration_human', '')})"
                  f"  [{(h.get('front_type') or {}).get('name', '')}]{with_}")
    return 0


def cmd_fronting(args, api: PluralspaceAPI, store: PassStore) -> int:
    fronts = _authed(api, store, api.current_fronts)
    if args.json:
        return _emit_json(fronts)
    if not fronts:
        print("Nobody is fronting")
    for f in fronts:
        name = (f.get("member") or {}).get("display_label", "(hidden)")
        kind = (f.get("front_type") or {}).get("name", "")
        note = f"  - {f['comment']}" if f.get("comment") else ""
        print(f"{name}  [{kind}]  since {_day(f['started_at'])}{note}")
    return 0


def cmd_history(args, api: PluralspaceAPI, store: PassStore) -> int:
    fronts = _authed(api, store, lambda: api.front_history(args.month))
    if args.json:
        return _emit_json(fronts)
    for f in fronts:
        name = (f.get("member") or {}).get("display_label", "(hidden)")
        kind = (f.get("front_type") or {}).get("name", "")
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
    sub.add_parser("logout", help="drop the local session").set_defaults(func=cmd_logout)
    sub.add_parser("whoami", help="show the logged-in account").set_defaults(func=cmd_whoami)

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
    p.add_argument("--history", type=int, default=5, help="recent fronts to show (default 5)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_member)
    p = sub.add_parser("fronting", aliases=["who", "w"], help="show current fronters")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fronting)
    p = sub.add_parser("switch", aliases=["sw"], help="set the current front")
    p.add_argument("members", nargs="+", metavar="NAME[:TYPE]",
                   help="exact member name or id suffix, optionally with a front type")
    p.add_argument("--type", help="default front type (default: Front)")
    p.add_argument("--add", action="store_true", help="keep current fronters")
    p.add_argument("-c", "--comment")
    p.add_argument("--silent", action="store_true", help="no notifications")
    p.add_argument("--dry-run", action="store_true", help="print the request, change nothing")
    p.set_defaults(func=cmd_switch)
    p = sub.add_parser("mood", help="show, set or clear the system mood")
    p.add_argument("name", nargs="?", help="mood to set (exact name)")
    p.add_argument("--list", action="store_true", help="list available moods")
    p.add_argument("--clear", action="store_true", help="clear the current mood")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_mood)
    sub.add_parser("end", help="end all fronts").set_defaults(func=cmd_end)
    p = sub.add_parser("history", help="front history for this month")
    p.add_argument("--month", help="YYYY-MM (default: current)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    args = parser.parse_args(argv)
    api = PluralspaceAPI(args.profile, debug=args.debug)
    store = PassStore(args.profile)
    try:
        return args.func(args, api, store)
    except (AuthError, CredentialError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except APIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        return 130


if __name__ == "__main__":
    sys.exit(main())
