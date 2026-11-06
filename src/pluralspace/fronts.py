"""Pure front-set planning: diff current fronts against a requested set."""

from dataclasses import dataclass

from .render import _day, front_member_label, front_type_name


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

    lines = ["Dry run: no changes made. Would:"]
    for mid in plan.start:
        lines.append(f"  + start  {name(mid)}  [{tname(plan.target[mid])}]")
    for mid in plan.retype:
        old = tname(now[mid]["system_front_type_id"])
        lines.append(f"  ~ retype {name(mid)}  [{old} -> {tname(plan.target[mid])}]")
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
