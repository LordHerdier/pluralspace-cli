import pytest
from fakes import CO_FRONT, FRONT, FakeServer, FakeStore

from pluralspace import cli
from pluralspace.cli import app, common
from pluralspace.state import StateError, build_snapshot, load_snapshot, save_snapshot


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    srv = FakeServer()
    monkeypatch.setattr(app, "PluralspaceAPI", lambda profile, debug=False: srv)
    monkeypatch.setattr(app, "PassStore", FakeStore)
    return srv


def snap():
    return load_snapshot("default")


def ids(rows):
    return [r["id"] for r in rows]


def test_replacing_a_fronter_saves_the_old_rows_and_the_confirmed_result(server):
    ada = server.start("m-ada")
    assert cli.main(["switch", "Bo", "--replace"]) == 0
    s = snap()
    assert s["kind"] == "fronts" and s["command"] == "switch"
    assert ids(s["before"]) == [ada["id"]]
    assert s["before"][0]["started_at"] == ada["started_at"]
    assert [r["member_id"] for r in s["after"]] == ["m-bo"]


def test_a_switch_that_changes_nothing_keeps_the_previous_snapshot(server):
    server.start("m-ada")
    save_snapshot(
        "default", build_snapshot("fronts", "end", [], now="2026-01-01T00:00:00Z")
    )
    assert cli.main(["switch", "Ada"]) == 0
    assert snap()["command"] == "end"


def test_dry_run_saves_nothing(server):
    server.start("m-ada")
    assert cli.main(["switch", "Bo", "--replace", "--dry-run"]) == 0
    assert snap() is None and server.calls == []


def test_refused_confirmation_saves_nothing_and_writes_nothing(server, capsys):
    server.start("m-ada")
    assert cli.main(["switch", "Bo"]) == 1  # non-tty: needs --replace
    assert snap() is None and server.calls == []


def test_adding_a_fronter_is_recorded(server):
    server.start("m-ada")
    assert cli.main(["switch", "Bo", "--add"]) == 0
    assert len(snap()["before"]) == 1 and len(snap()["after"]) == 2


def test_a_retype_is_recorded(server):
    ada = server.start("m-ada", FRONT)
    assert cli.main(["switch", "Ada:Co-Front", "--replace"]) == 0
    assert ids(snap()["before"]) == [ada["id"]]
    assert snap()["after"][0]["type_id"] == CO_FRONT


def test_end_saves_before_and_an_empty_after(server):
    ada = server.start("m-ada")
    assert cli.main(["end"]) == 0
    s = snap()
    assert s["command"] == "end" and ids(s["before"]) == [ada["id"]]
    assert s["after"] == []


def test_end_with_nobody_fronting_keeps_the_previous_snapshot(server):
    save_snapshot(
        "default", build_snapshot("fronts", "switch", [], now="2026-01-01T00:00:00Z")
    )
    assert cli.main(["end"]) == 0
    assert snap()["command"] == "switch"


def test_end_dry_run_saves_nothing(server):
    server.start("m-ada")
    assert cli.main(["end", "--dry-run"]) == 0
    assert snap() is None


def test_mood_change_saves_old_and_new(server):
    server.set_mood("mood-tired")
    server.calls.clear()
    assert cli.main(["mood", "calm"]) == 0
    s = snap()
    assert s["kind"] == "mood"
    assert s["before"] == {"id": "mood-tired", "label": "Tired"}
    assert s["after"] == {"id": "mood-calm", "label": "Calm"}


def test_setting_the_mood_it_already_has_keeps_the_snapshot(server):
    server.set_mood("mood-calm")
    assert cli.main(["mood", "calm"]) == 0
    assert snap() is None


def test_clearing_a_mood_records_it_and_clearing_none_does_not(server):
    server.set_mood("mood-calm")
    assert cli.main(["mood", "--clear"]) == 0
    assert snap()["before"]["id"] == "mood-calm"
    assert snap()["after"] == {"id": None, "label": None}
    save_snapshot(
        "default", build_snapshot("fronts", "end", [], now="2026-01-01T00:00:00Z")
    )
    assert cli.main(["mood", "--clear"]) == 0
    assert snap()["command"] == "end"


def test_mood_dry_run_and_read_save_nothing(server):
    assert cli.main(["mood", "calm", "--dry-run"]) == 0
    assert cli.main(["mood"]) == 0
    assert snap() is None


def test_if_the_snapshot_cannot_be_saved_the_write_does_not_happen(
    server, monkeypatch, capsys
):
    server.start("m-ada")

    def boom(*a, **kw):
        raise StateError("disk full")

    monkeypatch.setattr(common, "save_snapshot", boom)
    assert cli.main(["end"]) == 1
    assert "disk full" in capsys.readouterr().err
    assert len(server.live()) == 1 and server.calls == []


def test_failing_to_record_the_result_only_warns(server, monkeypatch, capsys):
    server.start("m-ada")

    def boom(*a, **kw):
        raise StateError("disk full")

    monkeypatch.setattr(common, "update_after", boom)
    assert cli.main(["end"]) == 0
    assert "warning: disk full" in capsys.readouterr().err
    assert server.live() == []
