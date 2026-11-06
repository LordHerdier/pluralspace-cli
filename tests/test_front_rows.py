import pytest

from pluralspace.fronts import reopen_body, row_from_calendar, row_from_current


def _current():
    return {
        "id": "row1",
        "member_id": "m1",
        "system_front_type_id": "t1",
        "started_at": "2026-11-06T19:52:44+00:00",
        "comment": "hi",
        "member": {"display_label": "Ada"},
        "front_type": {"name": "Front"},
    }


def _calendar():
    return {
        "id": "row1",
        "started_at": "2026-11-06T19:52:44+00:00",
        "ended_at": "2026-11-06T20:00:00+00:00",
        "is_ongoing": False,
        "comment": "hi",
        "system_front_type_id": None,  # the calendar leaves this empty
        "member": {"id": "m1", "display_label": "Ada"},
        "front_type": {"id": "t1", "name": "Front"},
    }


def test_current_and_calendar_rows_share_a_shape():
    cur, cal = row_from_current(_current()), row_from_calendar(_calendar())
    assert set(cur) == set(cal)
    for key in ("id", "member_id", "type_id", "started_at", "comment", "label"):
        assert cur[key] == cal[key]
    assert cur["ended_at"] is None
    assert cal["ended_at"] == "2026-11-06T20:00:00+00:00"


def test_rows_tolerate_a_hidden_member():
    cal = {**_calendar(), "member": None}
    row = row_from_calendar(cal)
    assert row["member_id"] is None and row["label"] == "(hidden)"


def test_reopen_body_changes_only_ended_at():
    row = row_from_calendar(_calendar())
    assert reopen_body(row, "UTC") == {
        "member_id": "m1",
        "system_front_type_id": "t1",
        "started_at": "2026-11-06T19:52:44",
        "ended_at": None,
        "comment": "hi",
    }


def test_reopen_body_refuses_an_unwritable_start_time():
    row = {**row_from_calendar(_calendar()), "started_at": "2026-11-06T19:52:44.5Z"}
    with pytest.raises(ValueError):
        reopen_body(row, "UTC")
