"""Nothing secret may reach stdout, stderr or an error message: not the
password, not the session cookie, not the XSRF token. The server here is
hostile on purpose and echoes those values back in its responses."""

import json
import urllib.parse

import pytest

from pluralspace.api_client import APIError, PluralspaceAPI
from pluralspace.cli import app
from pluralspace.credentials import Credentials

PASSWORD = "hunter2-PASSWORD-sentinel"
SESSION = "SESSION-cookie-sentinel"
XSRF = "XSRF token/sentinel=="
SECRETS = [PASSWORD, SESSION, XSRF, urllib.parse.quote(XSRF)]

LOGIN_PAGE = '<script data-page="app" type="application/json">{"version":"v1"}</script>'


class Resp:
    def __init__(self, status, body="", headers=None):
        self.status, self.headers = status, headers or {}
        self._body = body.encode() if isinstance(body, str) else body

    def read(self):
        return self._body


class HostileOpener:
    """Stands in for urllib's opener. `routes` maps (method, path) to a Resp
    or a function of the request body; every request is kept in `seen`."""

    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def open(self, req, timeout=None):
        path = urllib.parse.urlsplit(req.full_url).path
        self.seen.append((req.get_method(), path, dict(req.header_items())))
        route = self.routes[(req.get_method(), path)]
        return route(req) if callable(route) else route


class FakeStore:
    entry = "pluralspace/test"

    def __init__(self, profile):
        pass

    def exists(self):
        return False

    def load(self):
        return Credentials("me@example.com", PASSWORD)


def _install(monkeypatch, routes, cookies=False):
    opener = HostileOpener(routes)
    real_init = PluralspaceAPI.__init__

    def init(self, *a, **kw):
        real_init(self, *a, **kw)
        self._opener = opener
        if cookies:
            for name, value in (
                ("pluralspace-session", SESSION),
                ("XSRF-TOKEN", urllib.parse.quote(XSRF)),
            ):
                self.jar.set_cookie(_cookie(name, value))

    monkeypatch.setattr(PluralspaceAPI, "__init__", init)
    monkeypatch.setattr(app, "PassStore", FakeStore)
    return opener


def _cookie(name, value):
    import http.cookiejar as cj

    return cj.Cookie(
        0, name, value, None, False, "pluralspace.app", True, False, "/", True,
        True, None, True, None, None, {},
    )  # fmt: skip


def _assert_clean(*texts):
    for text in texts:
        for secret in SECRETS:
            assert secret not in text, f"leaked {secret!r} in:\n{text}"


def _run(capsys, argv):
    code = app.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_debug_login_failure_echoing_password(monkeypatch, capsys):
    echo = json.dumps({"props": {"errors": {"email": f"bad login for {PASSWORD}"}}})
    _install(
        monkeypatch,
        {
            ("GET", "/login"): Resp(200, LOGIN_PAGE),
            ("POST", "/login"): Resp(200, echo),
        },
    )
    monkeypatch.setattr("getpass.getpass", lambda *_: PASSWORD)
    code, out, err = _run(capsys, ["--debug", "login", "--email", "me@example.com"])
    assert code == 1
    assert "[debug] POST /login -> 200" in out
    _assert_clean(out, err)


@pytest.mark.parametrize("status", [401, 419, 500, 302])
def test_debug_read_with_live_session(monkeypatch, capsys, status):
    headers = {"Location": "/login"} if status == 302 else {}
    _install(
        monkeypatch,
        {("GET", "/space"): Resp(status, f"{SESSION} {PASSWORD}", headers)},
        cookies=True,
    )
    code, out, err = _run(capsys, ["--debug", "whoami"])
    assert code != 0
    assert "[debug] GET /space" in out
    _assert_clean(out, err)


def test_response_shape_error_does_not_quote_values(monkeypatch, capsys):
    bad = {"component": "App/Dashboard", "props": {"currentFronts": [{"x": SESSION}]}}
    _install(monkeypatch, {("GET", "/space"): Resp(200, json.dumps(bad))}, cookies=True)
    code, out, err = _run(capsys, ["--debug", "fronting"])
    assert code == 2
    _assert_clean(out, err)


@pytest.mark.parametrize("status", [403, 422, 500])
def test_failed_write_scrubs_echoed_secrets(monkeypatch, status):
    body = json.dumps(
        {"errors": {"x": f"{SESSION} {XSRF} {urllib.parse.quote(XSRF)} {PASSWORD}"}}
    )
    _install(
        monkeypatch,
        {("POST", "/space/fronts/end-all"): Resp(status, body)},
        cookies=True,
    )
    api = PluralspaceAPI("default")
    api.version = "v1"
    api._secrets.append(PASSWORD)
    with pytest.raises(APIError) as e:
        api.end_all()
    _assert_clean(str(e.value))
    assert "[redacted]" in str(e.value)


def test_xsrf_header_is_sent_but_never_printed(monkeypatch, capsys):
    opener = _install(monkeypatch, {("GET", "/space"): Resp(500, "")}, cookies=True)
    _run(capsys, ["--debug", "whoami"])
    sent = {k.lower(): v for _, _, h in opener.seen for k, v in h.items()}
    assert sent.get("x-xsrf-token") == XSRF  # sanity: the secret was in play
