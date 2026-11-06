import pytest

from pluralspace.api_client import APIError, PluralspaceAPI


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    client = PluralspaceAPI("test")
    client.sent = []
    monkeypatch.setattr(client, "_mutate", lambda *a, **kw: client.sent.append((a, kw)))
    return client


def _front(fid, start, end, member="m1"):
    return {
        "id": fid,
        "started_at": start,
        "ended_at": end,
        "is_ongoing": end is None,
        "comment": None,
        "member": {"id": member, "display_label": "Ada"},
        "front_type": {"id": "t1", "name": "Front"},
    }


def _props(fronts, month="2026-11", tz="UTC", edit=True):
    return {
        "month": {"value": month},
        "viewerTimezone": tz,
        "permissions": {"edit_fronts": edit},
        "weeks": [[{"date": "2026-11-06", "fronts": fronts}]],
    }


def test_end_front_posts_to_the_member_keyed_endpoint(api):
    api.end_front("m 1")
    assert api.sent == [(("/space/fronts/m%201/end", {}), {})]


def test_delete_front_sends_a_delete_for_that_row_only(api):
    api.delete_front("row 1")
    assert api.sent == [(("/space/fronts/row%201", {}), {"method": "DELETE"})]


def test_reopen_front_patches_the_row_with_a_null_end(api):
    row = {
        "id": "row1",
        "member_id": "m1",
        "type_id": "t1",
        "started_at": "2026-11-06T19:52:44+00:00",
        "comment": None,
    }
    api.reopen_front(row, "UTC")
    (path, body), kw = api.sent[0]
    assert path == "/space/fronts/row1" and kw == {"method": "PATCH"}
    assert body["ended_at"] is None and body["started_at"] == "2026-11-06T19:52:44"


def test_reopen_front_refuses_before_sending_if_time_cannot_be_written(api):
    row = {
        "id": "row1",
        "member_id": "m1",
        "type_id": "t1",
        "started_at": "2026-11-06T19:52:44+00:00",
        "comment": None,
    }
    with pytest.raises(APIError, match="unknown timezone"):
        api.reopen_front(row, "Mars/Olympus")
    assert api.sent == []


def test_calendar_state_lists_every_ongoing_row_including_duplicates(api, monkeypatch):
    fronts = [
        _front("a", "2026-11-06T19:52:44+00:00", None),
        _front("b", "2026-11-06T20:03:04+00:00", None),
    ]
    monkeypatch.setattr(api, "fronts_page", lambda month=None: _props(fronts))
    state = api.calendar_state()
    assert state.timezone == "UTC" and state.can_edit
    assert {r["id"] for r in state.rows.values() if r["ended_at"] is None} == {"a", "b"}


def test_calendar_state_fetches_the_months_of_the_given_start_times(api, monkeypatch):
    seen = []

    def fake(month=None):
        seen.append(month)
        return _props([_front(f"r-{month}", "2026-10-30T10:00:00+00:00", None)])

    monkeypatch.setattr(api, "fronts_page", fake)
    state = api.calendar_state(
        ["2026-10-30T10:00:00+00:00", "2026-11-02T10:00:00+00:00"]
    )
    assert seen == [None, "2026-10"]  # November is already the current page
    assert set(state.rows) == {"r-None", "r-2026-10"}


def test_calendar_state_reports_missing_edit_permission(api, monkeypatch):
    monkeypatch.setattr(api, "fronts_page", lambda month=None: _props([], edit=False))
    assert api.calendar_state().can_edit is False
