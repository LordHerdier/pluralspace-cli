"""undo."""

import sys

from ...api_client import APIError, PluralspaceAPI
from ...credentials import PassStore
from ...errors import UsageError
from ...fronts import DRY_RUN_HEADER
from ...render import _day
from ...state import (
    StateError,
    build_snapshot,
    clear_snapshot,
    load_snapshot,
    save_snapshot,
)
from ...undo import (
    format_mood_undo_plan,
    format_undo_plan,
    fronts_discrepancies,
    live_rows,
    plan_fronts_undo,
    plan_mood_undo,
)
from ..common import _authed, add_dry_run
from .fronts import _print_fronting
from .mood import mood_state


def confirm_undo(stdin=None, stdout=None) -> None:
    """Undo is a write like any other: ask first, and never assume on a pipe."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stderr
    if not stdin.isatty():
        raise UsageError("pass --yes to undo without a terminal to confirm on")
    stdout.write("Apply this undo? [y/N] ")
    stdout.flush()
    if stdin.readline().strip().lower() not in ("y", "yes"):
        raise UsageError("aborted; nothing changed")


def _refuse(blockers, force) -> None:
    lines = "\n".join(f"  - {b}" for b in blockers)
    hint = "" if force else "\n(--force overrides the warnings, but not the others)"
    raise UsageError(f"can't undo:\n{lines}{hint}")


def _save_redo(args, kind, before, after) -> None:
    """Make the undo itself undoable. The undo has already happened, so a
    failure only warns."""
    try:
        save_snapshot(args.profile, build_snapshot(kind, "undo", before, after))
    except StateError as e:
        print(f"warning: undone, but can't save redo state: {e}", file=sys.stderr)


def _clear_after_delete(args) -> None:
    """The saved state described rows that no longer exist: drop it, so a
    second `plsp undo` says there's nothing to undo instead of failing."""
    try:
        clear_snapshot(args.profile)
    except StateError as e:
        print(f"warning: {e}", file=sys.stderr)
    print("Deleted entries can't be restored, so this undo can't be undone.")


def _header(args, snap) -> str:
    if args.dry_run:
        return DRY_RUN_HEADER
    return f"Undoing `{snap['command']}` from {_day(snap['taken_at'])}:"


def _gate(args, plan, snap, lines) -> bool:
    """Print the plan; True if the caller should go on to apply it."""
    print("\n".join(lines))
    blockers = plan.blockers(args.force)
    if args.dry_run:
        for b in blockers:
            print(f"  ! undo would refuse: {b}")
        return False
    if blockers:
        _refuse(blockers, args.force)
    if not plan:
        return False
    if not args.yes:
        confirm_undo()
    return True


def _undo_fronts(args, api, store, snap) -> int:
    starts = [r["started_at"] for r in snap["before"]]
    state = _authed(api, store, lambda: api.calendar_state(starts))
    plan = plan_fronts_undo(
        snap, state.rows, state.can_edit, allow_delete=not args.no_delete
    )
    lines = format_undo_plan(plan, _header(args, snap))
    lines += [f"  ! {w}" for w in plan.warnings]
    if not _gate(args, plan, snap, lines):
        return 0

    goal = snap["before"]
    goal_ids = {g["id"] for g in goal}
    pre_state = live_rows(state.rows)

    # Remove what the write started, then end anything else, and check both
    # took before reopening, so a reopened row never sits beside a live one.
    for row in plan.delete:
        _authed(api, store, lambda: api.delete_front(row["id"]))
    for member_id in dict.fromkeys(r["member_id"] for r in plan.end):
        _authed(api, store, lambda: api.end_front(member_id))
    if plan.delete or plan.end:
        mid = _authed(api, store, lambda: api.calendar_state(starts))
        stuck = [r["label"] for r in live_rows(mid.rows) if r["id"] not in goal_ids]
        kept = [r["label"] for r in plan.delete if r["id"] in mid.rows]
        if stuck or kept:
            raise APIError(
                f"couldn't remove {', '.join(stuck + kept)}; stopped before "
                "reopening anything. Check the app, then run `plsp undo --force` "
                "to retry"
            )
    for row in plan.reopen:
        _authed(api, store, lambda: api.reopen_front(row, state.timezone))

    final = _authed(api, store, lambda: api.calendar_state(starts))
    problems = fronts_discrepancies(final.rows, goal)
    if problems:
        raise APIError(
            "undo didn't produce the expected fronts: "
            + "; ".join(problems)
            + ". Check the app before changing anything else"
        )
    if plan.delete:
        # What it deleted can't come back, so there is nothing to redo.
        _clear_after_delete(args)
    else:
        _save_redo(args, "fronts", pre_state, live_rows(final.rows))
    _print_fronting(_authed(api, store, api.current_fronts))
    return 0


def _undo_mood(args, api, store, snap) -> int:
    current = mood_state(_authed(api, store, api.atmosphere))
    plan = plan_mood_undo(snap, current)
    lines = format_mood_undo_plan(plan, _header(args, snap))
    lines += [f"  ! {w}" for w in plan.warnings]
    if not _gate(args, plan, snap, lines):
        return 0

    target = plan.target
    if target["id"] is None:
        _authed(api, store, api.clear_mood)
    else:
        _authed(api, store, lambda: api.set_mood(target["id"]))
    result = mood_state(_authed(api, store, api.atmosphere))
    if result["id"] != target["id"]:
        raise APIError(
            f"undo didn't change the mood as expected (now {result['label'] or '(none)'})"
        )
    _save_redo(args, "mood", current, result)
    print(f"Mood: {result['label'] or '(none)'}")
    return 0


def cmd_undo(args, api: PluralspaceAPI, store: PassStore) -> int:
    snap = load_snapshot(args.profile)
    if snap is None:
        raise UsageError("nothing to undo")
    if snap["kind"] == "fronts":
        return _undo_fronts(args, api, store, snap)
    return _undo_mood(args, api, store, snap)


def register(sub) -> None:
    p = sub.add_parser(
        "undo",
        help="undo the last switch, end or mood change",
        description=(
            "Restore the state saved before the last switch, end or mood "
            "change. Fronts come back on their original row, keeping their "
            "start time. Fronts that write started are deleted from the "
            "history (or ended, with --no-delete); anything else live is ended."
        ),
    )
    add_dry_run(p)
    p.add_argument("-y", "--yes", action="store_true", help="don't ask to confirm")
    p.add_argument(
        "--no-delete",
        action="store_true",
        help="end the fronts the write started instead of deleting them "
        "(leaves short entries in history, but keeps the undo redoable)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="go ahead despite warnings (changes since the write, old end times)",
    )
    p.set_defaults(func=cmd_undo)
