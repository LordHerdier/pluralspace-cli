"""Pure front-set planning: diff current fronts against a requested set."""

from dataclasses import dataclass

from .render import _day, front_member_label, front_type_name
from .timeutil import parse_iso, to_viewer_naive

DRY_RUN_HEADER = "Dry run: no changes made. Would:"


def row_from_current(front: dict) -> dict:
    """Normalize a dashboard `currentFronts` entry into a front row."""
    return {
        "id": front["id"],
        "member_id": front["member_id"],
        "type_id": front["system_front_type_id"],
        "started_at": front["started_at"],
        "ended_at": None,
        "comment": front.get("comment"),
        "label": front_member_label(front),
        "type_name": front_type_name(front),
    }


def row_from_calendar(front: dict) -> dict:
    """Normalize a calendar (`/space/fronts`) entry into the same row shape."""
    member = front.get("member") or {}
    ftype = front.get("front_type") or {}
    return {
        "id": front["id"],
        "member_id": member.get("id"),
        "type_id": ftype.get("id"),
        "started_at": front["started_at"],
        "ended_at": front.get("ended_at"),
        "comment": front.get("comment"),
        "label": member.get("display_label") or "(hidden)",
        "type_name": ftype.get("name", ""),
    }


def reopen_body(row: dict, tz_name: str) -> dict:
    """Body for PATCH /space/fronts/{id} that makes an ended row live again.

    The endpoint replaces the whole row, so every other field is sent back
    exactly as read. Raises ValueError if the start time can't be written
    back exactly (see timeutil.to_viewer_naive).
    """
    return {
        "member_id": row["member_id"],
        "system_front_type_id": row["type_id"],
        "started_at": to_viewer_naive(row["started_at"], tz_name),
        "ended_at": None,
        "comment": row.get("comment"),
    }


@dataclass
class FrontPlan:
    """Member-id lists describing a front change.

    `keep` members stay in the same type (and keep their start time); `retype`
    members are already fronting under a different type. `current` maps
    member_id -> front (for naming); `target` maps member_id -> type_id.
    """

    start: list
    keep: list
    retype: list
    end: list
    current: dict
    target: dict

    def __bool__(self) -> bool:
        return bool(self.start or self.keep or self.retype or self.end)


def plan_fronts(current, fronters: dict) -> FrontPlan:
    """Diff the current front list against the requested {member_id: type_id}."""
    now = {f["member_id"]: f for f in current}

    def same_type(m):
        return now[m]["system_front_type_id"] == fronters[m]

    return FrontPlan(
        start=[m for m in fronters if m not in now],
        keep=[m for m in fronters if m in now and same_type(m)],
        retype=[m for m in fronters if m in now and not same_type(m)],
        end=[m for m in now if m not in fronters],
        current=now,
        target=fronters,
    )


def replaced_names(plan) -> list:
    """Names of current fronters a plain `switch` would end."""
    return [front_member_label(plan.current[mid]) for mid in plan.end]


def format_front_plan(plan, labels, type_names, comment=None, silent=False):
    """Human-readable lines for a plan_fronts result. `labels` names members
    that were resolved from arguments; the rest come from the current fronts."""
    now = plan.current

    def name(mid):
        """display_label everywhere, so a member reads the same on every line."""
        shown = (now.get(mid, {}).get("member") or {}).get("display_label")
        return shown or labels.get(mid) or "(hidden)"

    def tname(tid):
        return type_names.get(tid, tid)

    lines = [DRY_RUN_HEADER]
    for mid in plan.start:
        lines.append(f"  + start  {name(mid)}  [{tname(plan.target[mid])}]")
    for mid in plan.retype:
        old = tname(now[mid]["system_front_type_id"])
        # Pluralspace ends the old front row and opens a new one on a type
        # change, so the start time (and comment) do not carry over.
        lines.append(
            f"  ~ retype {name(mid)}  [{old} -> {tname(plan.target[mid])}]"
            "  (start time resets)"
        )
    for mid in plan.keep:
        lines.append(
            f"  = keep   {name(mid)}  [{tname(plan.target[mid])}]"
            f"  since {_day(now[mid]['started_at'])}"
        )
    for mid in plan.end:
        lines.append(f"  - end    {name(mid)}  [{front_type_name(now[mid])}]")
    if not plan:
        lines.append("  (nobody fronting before or after)")
    if comment:
        lines.append(f"  comment: {comment}")
    if silent:
        lines.append("  silent: no notifications")
    return lines


def front_discrepancies(before, after, fronters: dict, labels=None) -> list:
    """After a write: how does the re-read front list differ from the one we
    asked for? `before`/`after` are `currentFronts` lists and `fronters` the
    requested {member_id: type_id}. Empty means exactly as intended.

    A fronter whose type didn't change must still have its original start
    time; that is what tells a real "keep" from a silent restart.
    """
    labels = labels or {}
    was = {f["member_id"]: f for f in before}
    now = {f["member_id"]: f for f in after}

    def name(mid):
        src = now.get(mid) or was.get(mid)
        return (front_member_label(src) if src else None) or labels.get(mid) or mid

    out = []
    for mid, tid in fronters.items():
        f = now.get(mid)
        if f is None:
            out.append(f"{name(mid)} is not fronting")
        elif f["system_front_type_id"] != tid:
            out.append(f"{name(mid)} is fronting as a different type")
        elif (
            mid in was
            and was[mid]["system_front_type_id"] == tid
            and parse_iso(f["started_at"]) != parse_iso(was[mid]["started_at"])
        ):
            out.append(f"{name(mid)}'s start time changed")
    out += [f"{name(mid)} is still fronting" for mid in now if mid not in fronters]
    return out
