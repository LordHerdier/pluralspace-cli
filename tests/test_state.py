import json
import stat

import pytest

from pluralspace import state
from pluralspace.state import (
    StateError,
    build_snapshot,
    clear_snapshot,
    load_snapshot,
    save_snapshot,
    snapshot_path,
    update_after,
    validate_snapshot,
)


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return tmp_path


def _row(rid="r1"):
    return {
        "id": rid,
        "member_id": "m1",
        "type_id": "t1",
        "started_at": "2026-11-06T19:52:44+00:00",
        "ended_at": None,
        "comment": None,
        "label": "Ada",
        "type_name": "Front",
    }


def _fronts(**kw):
    return build_snapshot(
        "fronts", "switch", [_row()], now="2026-11-06T20:00:00Z", **kw
    )


def test_round_trip(state_home):
    snap = _fronts(after=[])
    save_snapshot("default", snap)
    assert load_snapshot("default") == snap
    assert (
        snapshot_path("default") == state_home / "pluralspace/default.last-state.json"
    )


def test_no_file_means_no_snapshot():
    assert load_snapshot("default") is None


def test_file_is_0600_and_no_temp_file_is_left(state_home):
    path = save_snapshot("default", _fronts())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_overwrite_replaces_the_previous_snapshot():
    save_snapshot("default", _fronts())
    newer = build_snapshot("fronts", "end", [], now="2026-11-06T21:00:00Z")
    save_snapshot("default", newer)
    assert load_snapshot("default")["command"] == "end"


def test_profiles_are_isolated():
    save_snapshot("a", _fronts())
    assert load_snapshot("b") is None


def test_mood_snapshot_round_trips():
    snap = build_snapshot(
        "mood",
        "mood",
        {"id": None, "label": None},
        {"id": "m9", "label": "Calm"},
    )
    save_snapshot("default", snap)
    assert load_snapshot("default") == snap


def test_corrupt_file_is_a_clear_error_not_a_crash():
    path = snapshot_path("default")
    path.parent.mkdir(parents=True)
    path.write_text('{"version": 1, "kind": "fro')
    with pytest.raises(StateError, match="corrupt"):
        load_snapshot("default")


def test_unknown_version_is_refused():
    path = snapshot_path("default")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**_fronts(), "version": 2}))
    with pytest.raises(StateError, match="version 2"):
        load_snapshot("default")


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {**_fronts(), "kind": "members"},
        {**_fronts(), "before": "nobody"},
        {**_fronts(), "before": [{"id": "r1"}]},
        {**_fronts(), "after": [{"id": ""}]},
        {**_fronts(), "taken_at": ""},
        {**build_snapshot("mood", "mood", {"id": None, "label": None}), "before": {}},
    ],
)
def test_malformed_snapshots_are_rejected(bad):
    with pytest.raises(StateError):
        validate_snapshot(bad)


def test_unwritable_state_dir_raises_instead_of_continuing(state_home, monkeypatch):
    def boom(*a, **kw):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(state.os, "open", boom)
    with pytest.raises(StateError, match="can't save undo state"):
        save_snapshot("default", _fronts())


def test_a_failed_replace_leaves_the_old_snapshot_intact(monkeypatch):
    save_snapshot("default", _fronts())

    def boom(*a, **kw):
        raise OSError(5, "I/O error")

    with monkeypatch.context() as m:
        m.setattr(state.os, "replace", boom)
        with pytest.raises(StateError):
            save_snapshot("default", build_snapshot("fronts", "end", []))
    assert load_snapshot("default")["command"] == "switch"
    leftovers = [p.name for p in snapshot_path("default").parent.iterdir()]
    assert leftovers == ["default.last-state.json"]


def test_update_after_records_the_confirmed_state():
    save_snapshot("default", _fronts())
    update_after("default", [])
    assert load_snapshot("default")["after"] == []
    assert load_snapshot("default")["before"] == _fronts()["before"]


def test_update_after_without_a_snapshot_is_an_error():
    with pytest.raises(StateError, match="no saved state"):
        update_after("default", [])


def test_clear_snapshot_removes_it_and_is_idempotent():
    save_snapshot("default", _fronts())
    clear_snapshot("default")
    assert load_snapshot("default") is None
    clear_snapshot("default")  # nothing there: not an error


def test_clear_snapshot_only_touches_its_own_profile():
    save_snapshot("a", _fronts())
    save_snapshot("b", _fronts())
    clear_snapshot("a")
    assert load_snapshot("a") is None and load_snapshot("b") is not None
