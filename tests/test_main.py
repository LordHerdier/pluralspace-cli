import pytest

from pluralspace import cli
from pluralspace.api_client import APIError, AuthError
from pluralspace.cli import app
from pluralspace.errors import UsageError


class FakeStore:
    entry = "pluralspace/test"

    def __init__(self, profile):
        pass

    def exists(self):
        return False


class FakeAPI:
    """Stands in for PluralspaceAPI; `calls` records what the CLI invoked."""

    fronts = []
    moods_ = [{"id": "m1", "name": "Calm", "tagline": "ok"}]
    mood_label = "Tired"
    raises = None
    calls = []

    def __init__(self, profile, debug=False):
        pass

    def _maybe_raise(self):
        if FakeAPI.raises:
            raise FakeAPI.raises

    def current_fronts(self):
        self._maybe_raise()
        return FakeAPI.fronts

    def end_all(self):
        FakeAPI.calls.append("end_all")

    def moods(self):
        return FakeAPI.moods_

    def atmosphere(self):
        return {"mood_label": FakeAPI.mood_label, "tagline": ""}

    def set_mood(self, mood_id):
        FakeAPI.calls.append(("set_mood", mood_id))

    def clear_mood(self):
        FakeAPI.calls.append("clear_mood")


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    FakeAPI.fronts, FakeAPI.raises, FakeAPI.calls = [], None, []
    monkeypatch.setattr(app, "PluralspaceAPI", FakeAPI)
    monkeypatch.setattr(app, "PassStore", FakeStore)


def test_usage_error_exits_1_with_message(capsys):
    FakeAPI.raises = UsageError("nope")
    assert cli.main(["fronting"]) == 1
    assert "error: nope" in capsys.readouterr().err


def test_auth_error_exits_1(capsys):
    FakeAPI.raises = AuthError("expired")
    assert cli.main(["fronting"]) == 1
    assert "error: expired" in capsys.readouterr().err


def test_api_error_exits_2(capsys):
    FakeAPI.raises = APIError("boom")
    assert cli.main(["fronting"]) == 2
    assert "error: boom" in capsys.readouterr().err


def test_ctrl_c_exits_130():
    FakeAPI.raises = KeyboardInterrupt()
    assert cli.main(["fronting"]) == 130


def test_end_dry_run_names_who_would_end_and_changes_nothing(capsys):
    FakeAPI.fronts = [
        {
            "member_id": "a",
            "system_front_type_id": "t1",
            "started_at": "2026-11-03T03:04:19+00:00",
            "member": {"display_label": "Alex"},
            "front_type": {"name": "Front"},
        }
    ]
    assert cli.main(["end", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out and "- end    Alex  [Front]" in out
    assert FakeAPI.calls == []


def test_end_dry_run_with_nobody_fronting(capsys):
    assert cli.main(["end", "--dry-run"]) == 0
    assert "nobody fronting" in capsys.readouterr().out


def test_end_really_ends(capsys):
    assert cli.main(["end"]) == 0
    assert FakeAPI.calls == ["end_all"]
    assert "Nobody is fronting" in capsys.readouterr().out


def test_mood_dry_run_requires_name_or_clear(capsys):
    assert cli.main(["mood", "--dry-run"]) == 1
    assert "needs a mood NAME or --clear" in capsys.readouterr().err


def test_mood_dry_run_shows_transition_without_writing(capsys):
    assert cli.main(["mood", "calm", "--dry-run"]) == 0
    assert "mood: Tired -> Calm" in capsys.readouterr().out
    assert FakeAPI.calls == []


def test_mood_dry_run_unchanged_and_clear(capsys):
    FakeAPI.mood_label = "Calm"
    cli.main(["mood", "Calm", "--dry-run"])
    assert "(unchanged)" in capsys.readouterr().out
    cli.main(["mood", "--clear", "--dry-run"])
    assert "mood: Calm -> (none)" in capsys.readouterr().out
    assert FakeAPI.calls == []


def test_mood_set_resolves_by_exact_name(capsys):
    assert cli.main(["mood", "calm"]) == 0
    assert FakeAPI.calls == [("set_mood", "m1")]
    assert cli.main(["mood", "cal"]) == 1  # prefixes rejected
    assert FakeAPI.calls == [("set_mood", "m1")]


def test_mood_list_json(capsys):
    assert cli.main(["mood", "--list", "--json"]) == 0
    assert '"name": "Calm"' in capsys.readouterr().out
