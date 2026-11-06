from datetime import datetime, timedelta, timezone

from pluralspace.fronts import DRY_RUN_HEADER
from pluralspace.undo import (
    format_mood_undo_plan,
    format_undo_plan,
    fronts_discrepancies,
    plan_fronts_undo,
    plan_mood_undo,
)

NOW = datetime(2026, 11, 6, 20, 5, tzinfo=timezone.utc)


def row(rid, member="m1", type_id="t1", ended="2026-11-06T20:03:00+00:00", **kw):
    return {
        "id": rid,
        "member_id": member,
        "type_id": type_id,
        "started_at": "2026-11-06T19:52:44+00:00",
        "ended_at": ended,
        "comment": None,
        "label": member.upper(),
        "type_name": "Front",
        **kw,
    }


def live(rid, **kw):
    return row(rid, ended=None, **kw)


def snap(before, after=None, command="switch", taken_at="2026-11-06T19:50:00Z"):
    return {"command": command, "taken_at": taken_at, "before": before, "after": after}


def rows(*rs):
    return {r["id"]: r for r in rs}


def plan(snapshot, *rs, can_edit=True, **kw):
    return plan_fronts_undo(snapshot, rows(*rs), can_edit, now=NOW, **kw)


def test_undo_of_end_all_reopens_the_original_row():
    saved = live("r1")
    p = plan(snap([saved], after=[]), row("r1"))
    assert [r["id"] for r in p.reopen] == ["r1"] and not p.end
    assert not p.blockers()


def test_undo_of_a_switch_deletes_the_new_row_and_reopens_the_old():
    old = live("old", member="a")
    p = plan(
        snap([old], after=[live("new", member="b")]),
        row("old", member="a"),
        live("new", member="b"),
    )
    assert [r["id"] for r in p.delete] == ["new"] and not p.end
    assert [r["id"] for r in p.reopen] == ["old"]
    assert not p.blockers()


def test_undo_of_a_retype_deletes_the_new_row_before_reopening_the_old_one():
    p = plan(
        snap([live("old", type_id="t1")], after=[live("new", type_id="t2")]),
        row("old", type_id="t1"),
        live("new", type_id="t2"),
    )
    assert [r["id"] for r in p.delete] == ["new"]
    assert [r["id"] for r in p.reopen] == ["old"]


def test_rows_already_live_are_kept_not_touched():
    p = plan(snap([live("r1")], after=[live("r1")]), live("r1"))
    assert [r["id"] for r in p.keep] == ["r1"] and not p and not p.blockers()


def test_a_live_row_hidden_from_the_dashboard_is_still_ended():
    # The calendar shows two live rows for m1; only r1 was in the saved state.
    p = plan(snap([live("r1")], after=[live("r1")]), live("r1"), live("dup"))
    assert [r["id"] for r in p.end] == ["dup"]
    assert [r["id"] for r in p.keep] == ["r1"]
    assert "- end" in "\n".join(format_undo_plan(p, "h"))


def test_missing_row_is_a_hard_problem():
    p = plan(snap([live("gone")], after=[]))
    assert any("no longer exists" in m for m in p.problems)
    assert p.blockers(force=True)


def test_edited_row_is_a_hard_problem_force_does_not_override():
    for changed in (
        row("r1", type_id="t9"),
        row("r1", started_at="2026-11-06T18:00:00+00:00"),
        row("r1", comment="edited"),
        row("r1", member="other"),
    ):
        p = plan(snap([live("r1")], after=[]), changed)
        assert any("edited" in m for m in p.problems)
        assert p.blockers(force=True)


def test_same_instant_in_a_different_format_is_not_an_edit():
    p = plan(
        snap([live("r1")], after=[]),
        row("r1", started_at="2026-11-06T19:52:44Z"),
    )
    assert not p.problems and len(p.reopen) == 1


def test_comment_none_and_empty_are_the_same():
    p = plan(snap([live("r1", comment="")], after=[]), row("r1", comment=None))
    assert not p.problems


def test_changes_since_the_write_need_force():
    p = plan(snap([live("r1")], after=[]), row("r1"), live("x", member="b"))
    assert p.warnings and p.blockers() and not p.blockers(force=True)


def test_unrecorded_after_state_warns():
    p = plan(snap([live("r1")], after=None), row("r1"))
    assert any("wasn't recorded" in m for m in p.warnings)


def test_old_end_time_needs_force():
    old = row("r1", ended="2026-11-06T18:00:00+00:00")
    p = plan(snap([live("r1")], after=[]), old)
    assert any("minutes ago" in m for m in p.warnings)
    assert p.blockers() and not p.blockers(force=True)
    assert [r["id"] for r in p.reopen] == ["r1"]


def test_window_is_adjustable():
    p = plan(
        snap([live("r1")], after=[]),
        row("r1", ended="2026-11-06T18:00:00+00:00"),
        window=timedelta(hours=5),
    )
    assert not p.blockers()


def test_no_edit_permission_refuses_everything():
    p = plan(snap([live("r1")], after=[]), row("r1"), can_edit=False)
    assert p.problems == ["this account can't edit fronts"] and not p


def test_never_reopens_beside_a_live_row_of_the_same_member():
    # r1 is live and kept; r2 (same member) is also in the saved set.
    p = plan(
        snap([live("r1"), live("r2")], after=[]),
        live("r1"),
        row("r2"),
    )
    assert any("two live fronts" in m for m in p.problems)


def test_discrepancies_empty_when_exactly_as_expected():
    assert not fronts_discrepancies(
        rows(live("r1"), row("r2", member="b")), [live("r1")]
    )


def test_discrepancies_catch_missing_extra_and_duplicate_rows():
    expected = [live("r1")]
    assert fronts_discrepancies(rows(row("r1")), expected) == ["M1 is not live"]
    assert fronts_discrepancies(rows(live("r1"), live("x", member="b")), expected) == [
        "B has an unexpected live front"
    ]
    dup = fronts_discrepancies(rows(live("r1"), live("r9")), expected)
    assert "M1 has 2 live fronts" in dup


def test_format_lists_each_action():
    p = plan(
        snap([live("old", member="a")], after=[live("new", member="b")]),
        row("old", member="a"),
        live("new", member="b"),
    )
    text = "\n".join(format_undo_plan(p, DRY_RUN_HEADER))
    assert text.startswith(DRY_RUN_HEADER)
    assert "- delete B  [Front]  started " in text
    assert "by that write  (removed from history)" in text
    assert "can't be undone" in text
    assert "+ reopen A  [Front]  since " in text
    assert "the gap will count as fronting" in text


def test_format_nothing_to_change():
    p = plan(snap([live("r1")], after=[live("r1")]), live("r1"))
    assert format_undo_plan(p, "h") == [
        "h",
        "  = keep   M1  [Front]",
        "  (nothing to change)",
    ]


MOOD_NONE = {"id": None, "label": None}
CALM = {"id": "c", "label": "Calm"}
TIRED = {"id": "t", "label": "Tired"}


def test_mood_undo_restores_the_previous_mood():
    p = plan_mood_undo({"before": TIRED, "after": CALM}, CALM)
    assert p and not p.blockers()
    assert format_mood_undo_plan(p, "h") == ["h", "  mood: Calm -> Tired"]


def test_mood_undo_back_to_no_mood():
    p = plan_mood_undo({"before": MOOD_NONE, "after": CALM}, CALM)
    assert format_mood_undo_plan(p, "h")[1] == "  mood: Calm -> (none)"


def test_mood_unchanged_when_already_at_target():
    p = plan_mood_undo({"before": TIRED, "after": CALM}, TIRED)
    assert not p and format_mood_undo_plan(p, "h")[1] == "  mood: Tired (unchanged)"


def test_mood_changed_since_the_write_needs_force():
    p = plan_mood_undo({"before": TIRED, "after": CALM}, {"id": "z", "label": "Z"})
    assert p.blockers() and not p.blockers(force=True)


def test_mood_unrecorded_after_warns():
    assert plan_mood_undo({"before": TIRED, "after": None}, CALM).warnings


def test_discrepancies_catch_a_shifted_start_time():
    shifted = live("r1", started_at="2026-11-06T18:52:44+00:00")
    out = fronts_discrepancies(rows(shifted), [live("r1")])
    assert out == ["M1's front came back different (start time or type)"]


# -- deleting the rows a write created ------------------------------------


def _switch_snapshot(**kw):
    return snap([live("old", member="a")], after=[live("new", member="b")], **kw)


def _after_switch(**row_kw):
    return (row("old", member="a"), live("new", member="b", **row_kw))


def test_delete_is_opt_out_and_falls_back_to_ending():
    p = plan(_switch_snapshot(), *_after_switch(), allow_delete=False)
    assert [r["id"] for r in p.end] == ["new"] and not p.delete
    text = "\n".join(format_undo_plan(p, "h"))
    assert "- end    B" in text and "can't be undone" not in text


def test_a_row_that_is_not_in_the_saved_after_state_is_ended_not_deleted():
    # Started later, in the app: not ours to delete.
    p = plan(
        _switch_snapshot(),
        row("old", member="a"),
        live("new", member="b"),
        live("theirs", member="c"),
    )
    assert [r["id"] for r in p.delete] == ["new"]
    assert [r["id"] for r in p.end] == ["theirs"]


def test_an_edited_new_row_is_ended_not_deleted():
    for changed in (
        live("new", member="b", comment="added by hand"),
        live("new", member="b", type_id="t9"),
        live("new", member="b", started_at="2026-11-06T19:55:00+00:00"),
    ):
        p = plan(_switch_snapshot(), row("old", member="a"), changed)
        assert not p.delete and [r["id"] for r in p.end] == ["new"]


def test_a_row_older_than_the_window_is_ended_not_deleted():
    p = plan(_switch_snapshot(), *_after_switch(), window=timedelta(minutes=5))
    assert not p.delete and [r["id"] for r in p.end] == ["new"]


def test_nothing_is_deleted_when_the_after_state_was_not_recorded():
    p = plan(
        snap([live("old", member="a")], after=None),
        row("old", member="a"),
        live("new", member="b"),
    )
    assert not p.delete and [r["id"] for r in p.end] == ["new"]


def test_only_a_switch_ever_creates_rows_so_only_a_switch_deletes():
    # `end` creates nothing; an `undo` snapshot's "after" holds the original
    # rows it reopened. Deleting those would destroy real history.
    reopened = live("orig", member="a")
    for command in ("end", "undo"):
        s = snap([], after=[reopened], command=command)
        p = plan(s, reopened)
        assert not p.delete and [r["id"] for r in p.end] == ["orig"]


def test_a_row_from_long_before_the_write_is_never_deleted():
    # In `after` and not in `before`, but it started hours before the snapshot.
    old_start = "2026-11-06T10:00:00+00:00"
    s = snap([], after=[live("new", member="b", started_at=old_start)])
    p = plan(s, live("new", member="b", started_at=old_start), window=timedelta(days=1))
    assert not p.delete and [r["id"] for r in p.end] == ["new"]


def test_rows_in_both_before_and_after_are_kept_not_deleted():
    s = snap([live("r1")], after=[live("r1")])
    p = plan(s, live("r1"))
    assert not p.delete and not p.end and [r["id"] for r in p.keep] == ["r1"]


def test_a_delete_counts_as_something_to_do():
    p = plan(snap([], after=[live("new", member="b")]), live("new", member="b"))
    assert p and [r["id"] for r in p.delete] == ["new"]
