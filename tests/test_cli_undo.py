import io
import sys

import pytest
from fakes import CO_FRONT, FRONT, FakeServer, FakeStore

from pluralspace import cli
from pluralspace.cli import app
from pluralspace.state import load_snapshot


class TTY(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def server(monkeypatch):
    srv = FakeServer()
    monkeypatch.setattr(app, "PluralspaceAPI", lambda profile, debug=False: srv)
    monkeypatch.setattr(app, "PassStore", FakeStore)
    return srv


def undo(*extra):
    return cli.main(["undo", "--yes", *extra])


def live_members(server):
    return sorted(r["member_id"] for r in server.live())


def test_nothing_to_undo_without_a_snapshot(server, capsys):
    assert cli.main(["undo"]) == 1
    assert "nothing to undo" in capsys.readouterr().err


def test_undo_end_reopens_the_original_row_with_its_start_time(server):
    ada = server.start("m-ada", comment="hello")
    assert cli.main(["end"]) == 0
    assert server.live() == []
    server.calls.clear()
    assert undo() == 0
    (row,) = server.live()
    assert row["id"] == ada["id"]  # same row, not a new one
    assert row["started_at"] == ada["started_at"]
    assert row["comment"] == "hello"
    assert server.calls == [("reopen_front", ada["id"], "UTC")]


def test_undo_a_switch_deletes_the_new_row_and_reopens_the_old(server):
    ada = server.start("m-ada")
    assert cli.main(["switch", "Bo", "--replace"]) == 0
    bo = next(r for r in server.live() if r["member_id"] == "m-bo")
    assert undo() == 0
    (row,) = server.live()
    assert row["id"] == ada["id"] and row["started_at"] == ada["started_at"]
    assert ("delete_front", bo["id"]) in server.calls
    # no short entry left behind: history is exactly what it was before
    assert set(server.rows) == {ada["id"]}


def test_undo_that_deleted_rows_cannot_be_redone(server, capsys):
    server.start("m-ada")
    cli.main(["switch", "Bo", "--replace"])
    assert undo() == 0
    assert "can't be undone" in capsys.readouterr().out
    assert load_snapshot("default") is None
    assert cli.main(["undo"]) == 1
    assert "nothing to undo" in capsys.readouterr().err


def test_no_delete_ends_the_new_row_instead_and_stays_redoable(server):
    ada = server.start("m-ada")
    cli.main(["switch", "Bo", "--replace"])
    assert undo("--no-delete") == 0
    assert ("end_front", "m-bo") in server.calls
    assert not any(c[0] == "delete_front" for c in server.calls)
    assert len(server.rows) == 2  # Bo's short entry is kept
    assert load_snapshot("default")["command"] == "undo"
    assert undo() == 0  # redo
    assert live_members(server) == ["m-bo"] and ada["id"] in server.rows


def test_a_new_row_edited_in_the_app_is_ended_not_deleted(server):
    server.start("m-ada")
    cli.main(["switch", "Bo", "--replace"])
    bo = next(r for r in server.live() if r["member_id"] == "m-bo")
    bo["comment"] = "added in the app"
    assert undo() == 0
    assert not any(c[0] == "delete_front" for c in server.calls)
    assert bo["id"] in server.rows and bo["ended_at"] is not None


def test_undo_a_retype_restores_the_original_type_and_start_time(server):
    ada = server.start("m-ada", FRONT)
    assert cli.main(["switch", "Ada:Co-Front", "--replace"]) == 0
    assert server.live()[0]["type_id"] == CO_FRONT
    assert undo() == 0
    (row,) = server.live()
    assert row["id"] == ada["id"] and row["type_id"] == FRONT


def test_undo_never_leaves_two_live_rows_for_a_member(server):
    server.start("m-ada", FRONT)
    cli.main(["switch", "Ada:Co-Front", "--replace"])
    assert undo() == 0
    members = [r["member_id"] for r in server.live()]
    assert members == ["m-ada"]  # not ["m-ada", "m-ada"]
    # and the new row was removed before the old one was reopened
    kinds = [c[0] for c in server.calls if c[0] in ("delete_front", "reopen_front")]
    assert kinds == ["delete_front", "reopen_front"]


def test_a_live_row_the_dashboard_hides_is_still_ended(server):
    server.start("m-ada")
    cli.main(["switch", "Bo", "--add"])
    hidden = server.start("m-bo")  # a duplicate live row for Bo
    assert len(server.live()) == 3
    assert undo("--force") == 0  # state differs from the saved "after"
    assert live_members(server) == ["m-ada"]
    assert hidden["id"] not in {r["id"] for r in server.live()}


def test_undo_twice_redoes(server):
    ada = server.start("m-ada")
    cli.main(["end"])
    assert undo() == 0 and live_members(server) == ["m-ada"]
    assert undo() == 0 and server.live() == []  # redo: ends Ada again
    # ...but never deletes her: the row undo reopened is not one a write created
    assert ada["id"] in server.rows
    assert not any(c[0] == "delete_front" for c in server.calls)
    assert undo() == 0  # and back
    assert server.live()[0]["id"] == ada["id"]


def test_dry_run_prints_the_plan_and_changes_nothing(server, capsys):
    server.start("m-ada")
    cli.main(["end"])
    server.calls.clear()
    assert cli.main(["undo", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out and "+ reopen Ada  [Front]  since " in out
    assert server.calls == [] and server.live() == []
    assert load_snapshot("default")["command"] == "end"  # snapshot kept


def test_dry_run_reports_what_would_make_it_refuse(server, capsys):
    server.start("m-ada")
    cli.main(["end"])
    server.start("m-cy")  # changed in the app since
    assert cli.main(["undo", "--dry-run"]) == 0
    assert "undo would refuse" in capsys.readouterr().out


def test_changes_made_since_need_force(server, capsys):
    server.start("m-ada")
    cli.main(["end"])
    server.start("m-cy")
    server.calls.clear()
    assert undo() == 1
    err = capsys.readouterr().err
    assert "fronts have changed" in err and "--force" in err
    assert server.calls == []
    assert undo("--force") == 0
    assert live_members(server) == ["m-ada"]


def test_an_old_end_time_needs_force(server, capsys):
    ada = server.start("m-ada")
    cli.main(["end"])
    server.rows[ada["id"]]["ended_at"] = "2020-01-01T00:00:00+00:00"
    assert undo() == 1
    assert "minutes ago" in capsys.readouterr().err
    assert undo("--force") == 0


def test_an_edited_row_is_refused_even_with_force(server, capsys):
    ada = server.start("m-ada")
    cli.main(["end"])
    server.rows[ada["id"]]["started_at"] = "2020-01-01T00:00:00+00:00"
    assert undo("--force") == 1
    assert "was edited" in capsys.readouterr().err
    assert server.live() == []


def test_a_deleted_row_is_refused(server, capsys):
    ada = server.start("m-ada")
    cli.main(["end"])
    del server.rows[ada["id"]]
    assert undo("--force") == 1
    assert "no longer exists" in capsys.readouterr().err


def test_an_account_that_cannot_edit_fronts_is_refused(server, capsys):
    server.start("m-ada")
    cli.main(["end"])
    server.can_edit = False
    assert undo("--force") == 1
    assert "can't edit fronts" in capsys.readouterr().err


def test_confirmation_is_required_on_a_pipe(server, capsys):
    server.start("m-ada")
    cli.main(["end"])
    assert cli.main(["undo"]) == 1  # stdin under pytest is not a tty
    assert "--yes" in capsys.readouterr().err
    assert server.live() == []


def test_confirmation_prompt_accepts_y_and_rejects_anything_else(server, monkeypatch):
    server.start("m-ada")
    cli.main(["end"])
    monkeypatch.setattr(sys, "stdin", TTY("n\n"))
    assert cli.main(["undo"]) == 1 and server.live() == []
    monkeypatch.setattr(sys, "stdin", TTY("y\n"))
    assert cli.main(["undo"]) == 0 and live_members(server) == ["m-ada"]


def test_a_failed_end_stops_before_reopening_anything(server, monkeypatch, capsys):
    server.start("m-ada")
    cli.main(["switch", "Bo", "--replace"])
    monkeypatch.setattr(server, "end_front", lambda member_id: None)  # silently ignored
    server.calls.clear()
    assert undo("--no-delete") == 2
    assert "stopped before reopening anything" in capsys.readouterr().err
    assert not any(c[0] == "reopen_front" for c in server.calls)
    assert load_snapshot("default")["command"] == "switch"  # still retryable


def test_a_delete_that_did_not_take_stops_before_reopening_anything(
    server, monkeypatch, capsys
):
    server.start("m-ada")
    cli.main(["switch", "Bo", "--replace"])
    monkeypatch.setattr(server, "delete_front", lambda front_id: None)  # ignored
    server.calls.clear()
    assert undo() == 2
    err = capsys.readouterr().err
    assert "couldn't remove" in err and "stopped before reopening anything" in err
    assert not any(c[0] == "reopen_front" for c in server.calls)
    assert load_snapshot("default")["command"] == "switch"


def test_a_reopen_that_did_not_take_is_reported_not_trusted(
    server, monkeypatch, capsys
):
    server.start("m-ada")
    cli.main(["end"])
    monkeypatch.setattr(server, "reopen_front", lambda row, tz: None)
    assert undo() == 2
    assert "didn't produce the expected fronts" in capsys.readouterr().err
    assert load_snapshot("default")["command"] == "end"


def test_already_restored_is_not_an_error_and_sends_nothing(server, capsys):
    ada = server.start("m-ada")
    cli.main(["end"])
    server.rows[ada["id"]]["ended_at"] = None  # put back by hand in the app
    server.calls.clear()
    assert undo("--force") == 0  # --force only to get past the "changed since" warning
    assert "nothing to change" in capsys.readouterr().out
    assert server.calls == []


# -- mood ---------------------------------------------------------------


def test_undo_mood_restores_the_previous_mood(server, capsys):
    server.set_mood("mood-tired")
    cli.main(["mood", "calm"])
    assert undo() == 0
    assert server.mood["id"] == "mood-tired"
    assert "Mood: Tired" in capsys.readouterr().out


def test_undo_mood_back_to_none(server):
    cli.main(["mood", "calm"])
    assert undo() == 0
    assert server.mood == {"id": None, "label": None}
    assert ("clear_mood",) in server.calls


def test_undo_mood_twice_redoes(server):
    cli.main(["mood", "calm"])
    undo()
    undo()
    assert server.mood["id"] == "mood-calm"


def test_undo_mood_changed_since_needs_force(server, capsys):
    cli.main(["mood", "calm"])
    server.set_mood("mood-tired")  # changed in the app
    assert undo() == 1
    assert "mood has changed" in capsys.readouterr().err
    assert undo("--force") == 0 and server.mood["id"] is None


def test_undo_mood_dry_run(server, capsys):
    cli.main(["mood", "calm"])
    server.calls.clear()
    assert cli.main(["undo", "--dry-run"]) == 0
    assert "mood: Calm -> (none)" in capsys.readouterr().out
    assert server.calls == [] and server.mood["id"] == "mood-calm"


def test_dry_run_shows_deletions_and_deletes_nothing(server, capsys):
    server.start("m-ada")
    cli.main(["switch", "Bo", "--replace"])
    server.calls.clear()
    assert cli.main(["undo", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "- delete Bo  [Front]  started " in out and "removed from history" in out
    assert "can't be undone" in out
    assert server.calls == [] and len(server.rows) == 2
