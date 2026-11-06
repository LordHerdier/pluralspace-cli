import pytest


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path, monkeypatch):
    """Writes save undo state and the client keeps cookies there: no test may
    ever touch the real $XDG_STATE_HOME."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
