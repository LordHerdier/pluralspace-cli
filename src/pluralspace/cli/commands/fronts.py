"""switch, end, fronting, history."""

import sys

from ...api_client import PluralspaceAPI
from ...credentials import PassStore
from ...errors import UsageError
from ...fronts import format_front_plan, plan_fronts, replaced_names
from ...render import _day, front_member_label, front_type_name
from ...resolve import resolve_front_type, resolve_member
from ..common import _authed, _emit_json, add_dry_run, add_json

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
        _print_fronting(_authed(api, store, api.current_fronts))
    return 0


def cmd_end(args, api: PluralspaceAPI, store: PassStore) -> int:
    if args.dry_run:
        current = _authed(api, store, api.current_fronts)
        print("\n".join(format_front_plan(plan_fronts(current, {}), {}, {})))
        return 0
    _authed(api, store, api.end_all)
    print("Nobody is fronting")
    return 0


def _print_fronting(fronts) -> None:
    if not fronts:
        print("Nobody is fronting")
    for f in fronts:
        name = front_member_label(f)
        kind = front_type_name(f)
        note = f"  - {f['comment']}" if f.get("comment") else ""
        print(f"{name}  [{kind}]  since {_day(f['started_at'])}{note}")


def cmd_fronting(args, api: PluralspaceAPI, store: PassStore) -> int:
    fronts = _authed(api, store, api.current_fronts)
    if args.json:
        return _emit_json(fronts)
    _print_fronting(fronts)
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


def register(sub) -> None:
    p = sub.add_parser("fronting", aliases=["who", "w"], help="show current fronters")
    add_json(p)
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
    add_dry_run(p)
    p.set_defaults(func=cmd_switch)
    p = sub.add_parser("end", help="end all fronts")
    add_dry_run(p)
    p.set_defaults(func=cmd_end)
    p = sub.add_parser("history", help="front history for this month")
    p.add_argument("--month", help="YYYY-MM (default: current)")
    add_json(p)
    p.set_defaults(func=cmd_history)
