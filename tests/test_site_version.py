import json

from pluralspace.api_client import PluralspaceAPI


def _login_page(version):
    page = json.dumps({"version": version}).replace('"', "&quot;")
    return f'<script data-page="app" type="application/json">{page}</script>'


def _client(monkeypatch, version):
    c = PluralspaceAPI("sv")
    monkeypatch.setattr(c, "_request", lambda *a, **kw: (200, {}, _login_page(version)))
    return c


def test_first_sight_stores_silently(monkeypatch):
    c = _client(monkeypatch, "aaaa")
    c._bootstrap()
    assert c.notices == []
    assert c.version_path.read_text().strip() == "aaaa"


def test_same_version_is_quiet(monkeypatch):
    _client(monkeypatch, "aaaa")._bootstrap()
    c = _client(monkeypatch, "aaaa")
    c._bootstrap()
    assert c.notices == []


def test_changed_version_warns_and_updates(monkeypatch):
    _client(monkeypatch, "aaaa")._bootstrap()
    c = _client(monkeypatch, "bbbb")
    c._bootstrap()
    assert len(c.notices) == 1 and "aaaa" in c.notices[0] and "bbbb" in c.notices[0]
    assert c.version_path.read_text().strip() == "bbbb"
    d = _client(monkeypatch, "bbbb")
    d._bootstrap()
    assert d.notices == []


def test_unwritable_store_is_not_fatal(monkeypatch):
    c = _client(monkeypatch, "aaaa")
    c.version_path.parent.mkdir(parents=True, exist_ok=True)
    c.version_path.mkdir()  # a directory where the file should be
    c._bootstrap()
    assert c.version == "aaaa"
