"""Pure planning for `plsp undo`: decide what restoring a snapshot would do.

Nothing here talks to the network. The caller reads the calendar rows (see
PluralspaceAPI.calendar_state), asks for a plan, and refuses or applies it.

Fronts are restored by *reopening the original row* (PATCH ended_at -> null),
which keeps its start time and comment, after ending whatever is live now.
Pluralspace allows two live rows for one member and the dashboard hides the
extra one, so the plan is built from the calendar and never reopens a row
next to a live one.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .render import _day
from .timeutil import parse_iso

# Reopening counts the whole gap since the row ended as fronting time, so
# undo is for catching a mistake soon after; older than this needs --force.
DEFAULT_WINDOW = timedelta(hours=1)


# A row can only have been started by the saved write if it starts about when
# the snapshot was taken (allowing for the site's clock vs ours).
CREATED_SLACK = timedelta(minutes=5)


@dataclass
class UndoPlan:
    delete: List[dict] = field(default_factory=list)  # rows the write created
    end: List[dict] = field(default_factory=list)  # other live rows to end
    reopen: List[dict] = field(default_factory=list)  # ended rows to make live
    keep: List[dict] = field(default_factory=list)  # already as they were
    problems: List[str] = field(default_factory=list)  # never overridable
    warnings: List[str] = field(default_factory=list)  # --force overrides

    def __bool__(self) -> bool:
        return bool(self.delete or self.end or self.reopen)

    def blockers(self, force: bool = False) -> List[str]:
        return list(self.problems) + ([] if force else list(self.warnings))


def live_rows(rows: Dict[str, dict]) -> List[dict]:
    return [r for r in rows.values() if r["ended_at"] is None]


def _same_instant(a: str, b: str) -> bool:
    return parse_iso(a) == parse_iso(b)


def _unchanged(row: dict, saved: dict) -> bool:
    """Is the row still what we saved? Compares what a reopen would resend."""
    return (
        row["member_id"] == saved["member_id"]
        and row["type_id"] == saved["type_id"]
        and _same_instant(row["started_at"], saved["started_at"])
        and (row.get("comment") or None) == (saved.get("comment") or None)
    )


def _signature(rows) -> set:
    return {(r["member_id"], r["type_id"]) for r in rows}


def _created_by_write(snapshot: dict) -> Dict[str, dict]:
    """Rows (id -> row as saved) that the saved write itself started.

    Only `switch` creates front rows. `end` creates none, and an `undo` only
    reopens, ends or deletes existing ones: its "after" rows include the
    original rows it reopened, which must never be mistaken for new ones.
    """
    after = snapshot.get("after")
    if snapshot["command"] != "switch" or after is None:
        return {}
    before_ids = {r["id"] for r in snapshot["before"]}
    taken = parse_iso(snapshot["taken_at"])
    return {
        r["id"]: r
        for r in after
        if r["id"] not in before_ids
        and parse_iso(r["started_at"]) >= taken - CREATED_SLACK
    }


def plan_fronts_undo(
    snapshot: dict,
    rows: Dict[str, dict],
    can_edit: bool,
    now: Optional[datetime] = None,
    window: timedelta = DEFAULT_WINDOW,
    allow_delete: bool = True,
) -> UndoPlan:
    """Plan restoring the front set recorded in `snapshot["before"]`.

    `rows` maps front id -> normalized calendar row. Rows the saved write
    created are deleted rather than ended, so undo doesn't leave short
    entries in the history, but only if they are still exactly as saved and
    younger than `window`: never someone's edited or long-running front.
    """
    now = now or datetime.now(timezone.utc)
    plan = UndoPlan()
    if not can_edit:
        plan.problems.append("this account can't edit fronts")
        return plan

    goal = snapshot["before"]
    goal_ids = {g["id"] for g in goal}
    live = live_rows(rows)
    live_ids = {r["id"] for r in live}

    after = snapshot.get("after")
    if after is None:
        plan.warnings.append(
            "the state after that write wasn't recorded, so changes made since "
            "can't be detected"
        )
    elif _signature(live) != _signature(after):
        plan.warnings.append(
            "fronts have changed since the last plsp write (made in the app, "
            "or by another command); undoing would overwrite that"
        )

    created = _created_by_write(snapshot) if allow_delete else {}
    for r in live:
        if r["id"] in goal_ids:
            continue
        saved_new = created.get(r["id"])
        if (
            saved_new is not None
            and _unchanged(r, saved_new)
            and now - parse_iso(r["started_at"]) <= window
        ):
            plan.delete.append(r)
        else:
            plan.end.append(r)
    for saved in goal:
        row = rows.get(saved["id"])
        name = saved.get("label") or "(hidden)"
        if saved["id"] in live_ids:
            plan.keep.append(row)
        elif row is None:
            plan.problems.append(f"{name}'s front no longer exists in the history")
        elif not _unchanged(row, saved):
            plan.problems.append(
                f"{name}'s front was edited since it was saved; won't overwrite it"
            )
        else:
            plan.reopen.append(row)
            ended = parse_iso(row["ended_at"])
            if now - ended > window:
                plan.warnings.append(
                    f"{name}'s front ended {_day(row['ended_at'])}, more than "
                    f"{int(window.total_seconds() // 60)} minutes ago; reopening "
                    "it would count all the time since as fronting"
                )

    # Never leave a member with two live rows.
    seen: Dict[str, str] = {r["member_id"]: r["id"] for r in plan.keep}
    for row in plan.reopen:
        if row["member_id"] in seen:
            plan.problems.append(
                f"{row['label']} would end up with two live fronts; won't do that"
            )
        seen[row["member_id"]] = row["id"]
    return plan


def fronts_discrepancies(rows: Dict[str, dict], expected: List[dict]) -> List[str]:
    """After a write: what differs between the live calendar rows and the
    rows we meant to have live? Empty means exactly as intended."""
    live = live_rows(rows)
    by_id = {r["id"]: r for r in live}
    want = {e["id"] for e in expected}
    out = []
    for e in expected:
        name = e.get("label") or e["id"]
        if e["id"] not in by_id:
            out.append(f"{name} is not live")
        elif not _unchanged(by_id[e["id"]], e):
            out.append(f"{name}'s front came back different (start time or type)")
    for r in live:
        if r["id"] not in want:
            out.append(f"{r['label']} has an unexpected live front")
    counts: Dict[str, int] = {}
    for r in live:
        counts[r["member_id"]] = counts.get(r["member_id"], 0) + 1
    out += [
        f"{next(r['label'] for r in live if r['member_id'] == m)} has {n} live fronts"
        for m, n in counts.items()
        if n > 1
    ]
    return out


def format_undo_plan(plan: UndoPlan, header: str) -> List[str]:
    lines = [header]
    for r in plan.delete:
        lines.append(
            f"  - delete {r['label']}  [{r['type_name']}]  started "
            f"{_day(r['started_at'])} by that write  (removed from history)"
        )
    for r in plan.end:
        lines.append(
            f"  - end    {r['label']}  [{r['type_name']}]"
            "  (stays in history as a short entry)"
        )
    for r in plan.reopen:
        lines.append(
            f"  + reopen {r['label']}  [{r['type_name']}]  since "
            f"{_day(r['started_at'])}  (ended {_day(r['ended_at'])}; "
            "the gap will count as fronting)"
        )
    for r in plan.keep:
        lines.append(f"  = keep   {r['label']}  [{r['type_name']}]")
    if not plan:
        lines.append("  (nothing to change)")
    if plan.delete:
        lines.append(
            "  note: deleted entries can't be restored, so this undo can't be "
            "undone (--no-delete ends them instead)"
        )
    return lines


@dataclass
class MoodUndoPlan:
    current: dict
    target: dict
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.current["id"] != self.target["id"]

    def blockers(self, force: bool = False) -> List[str]:
        return list(self.problems) + ([] if force else list(self.warnings))


def plan_mood_undo(snapshot: dict, current: dict) -> MoodUndoPlan:
    """Plan restoring `snapshot["before"]`; `current` is {"id", "label"}."""
    plan = MoodUndoPlan(current=current, target=snapshot["before"])
    after = snapshot.get("after")
    if after is None:
        plan.warnings.append(
            "the mood after that write wasn't recorded, so changes made since "
            "can't be detected"
        )
    elif current["id"] != after["id"]:
        plan.warnings.append(
            "the mood has changed since the last plsp write; undoing would "
            "overwrite that"
        )
    return plan


def format_mood_undo_plan(plan: MoodUndoPlan, header: str) -> List[str]:
    def name(m):
        return m["label"] or "(none)"

    if not plan:
        return [header, f"  mood: {name(plan.current)} (unchanged)"]
    return [header, f"  mood: {name(plan.current)} -> {name(plan.target)}"]
