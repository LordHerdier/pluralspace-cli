import pytest

from pluralspace.api_client import PluralspaceAPI
from pluralspace.errors import UsageError


def test_read_only_refuses_writes_before_any_request(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    api = PluralspaceAPI(read_only=True)

    def boom(*a, **kw):
        raise AssertionError("request sent")

    monkeypatch.setattr(api, "_request", boom)
    with pytest.raises(UsageError, match="read-only"):
        api.end_all()


def test_refused_write_keeps_saved_undo_state(tmp_path, monkeypatch):
    from pluralspace.cli.common import snapshot_before
    from pluralspace.state import build_snapshot, load_snapshot, save_snapshot

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    save_snapshot("p", build_snapshot("mood", "mood", {"id": "a", "label": "A"}))
    args = type("A", (), {"profile": "p", "read_only": True})()
    with pytest.raises(UsageError):
        snapshot_before(args, "mood", "mood", {"id": "b", "label": "B"})
    assert load_snapshot("p")["before"]["id"] == "a"
