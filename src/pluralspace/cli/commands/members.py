"""members, member."""

import sys
import textwrap

from ...api_client import PluralspaceAPI
from ...credentials import PassStore
from ...render import (
    _day,
    _field_value,
    _format_relationship,
    front_type_name,
    member_flags,
)
from ...resolve import resolve_member
from ..common import _authed, _emit_json, add_json


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


def register(sub) -> None:
    p = sub.add_parser("members", help="list members")
    p.add_argument("-q", "--query")
    p.add_argument("--archived", action="store_true")
    p.add_argument("--fronting", action="store_true", help="only current fronters")
    p.add_argument("--type", help="raw server-side type filter (default: alter)")
    add_json(p)
    p.set_defaults(func=cmd_members)
    p = sub.add_parser("member", aliases=["m"], help="show one member's profile")
    p.add_argument("name", help="member name or id suffix")
    p.add_argument("--full", action="store_true", help="don't truncate the description")
    p.add_argument(
        "--history", type=int, default=5, help="recent fronts to show (default 5)"
    )
    add_json(p)
    p.set_defaults(func=cmd_member)
