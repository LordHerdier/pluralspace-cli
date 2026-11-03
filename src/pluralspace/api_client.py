"""
HTTP client for Pluralspace.

The web app is Laravel + Inertia with cookie-session auth, so this client
speaks Inertia: a cookie jar, the XSRF header echoed from the XSRF-TOKEN
cookie, and X-Inertia headers so pages come back as JSON props.
"""

import html
import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__

BASE_URL = "https://pluralspace.app"
USER_AGENT = f"pluralspace-cli/{__version__}"

_PAGE_RE = re.compile(
    r'<script[^>]*data-page="app"[^>]*>(.*?)</script>', re.DOTALL
)


class APIError(Exception):
    pass


class AuthError(APIError):
    """Login rejected, or the session is missing/expired."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(base) / "pluralspace"


class PluralspaceAPI:
    def __init__(self, profile: str = "default", base_url: str = BASE_URL, debug: bool = False):
        self.base_url = base_url.rstrip("/")
        self.debug = debug
        self.version: Optional[str] = None
        self.jar_path = _state_dir() / f"{profile}.cookies"
        self.jar = http.cookiejar.MozillaCookieJar(str(self.jar_path))
        self._load_jar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect()
        )

    # -- cookie jar -------------------------------------------------------

    def _load_jar(self) -> None:
        try:
            self.jar.load(ignore_discard=True, ignore_expires=False)
        except (FileNotFoundError, http.cookiejar.LoadError):
            pass

    def _save_jar(self) -> None:
        self.jar_path.parent.mkdir(parents=True, exist_ok=True)
        # The jar holds a live session: create it 0600 before writing.
        fd = os.open(self.jar_path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
        os.chmod(self.jar_path, 0o600)
        self.jar.save(ignore_discard=True, ignore_expires=False)

    def clear_session(self) -> None:
        self.jar.clear()
        try:
            self.jar_path.unlink()
        except FileNotFoundError:
            pass

    def _cookie(self, name: str) -> Optional[str]:
        for c in self.jar:
            if c.name == name:
                return c.value
        return None

    def has_session(self) -> bool:
        return self._cookie("pluralspace-session") is not None

    # -- transport --------------------------------------------------------

    def _request(self, method: str, path: str, *, inertia: bool = True,
                 json_body: Optional[dict] = None,
                 partial: Optional[List[str]] = None,
                 component: Optional[str] = None):
        headers = {"User-Agent": USER_AGENT, "Origin": self.base_url,
                   "Referer": self.base_url + "/"}
        data = None
        if inertia:
            headers["Accept"] = "text/html, application/xhtml+xml"
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["X-Inertia"] = "true"
            if self.version:
                headers["X-Inertia-Version"] = self.version
            if partial and component:
                headers["X-Inertia-Partial-Component"] = component
                headers["X-Inertia-Partial-Data"] = ",".join(partial)
        else:
            headers["Accept"] = "text/html"
        xsrf = self._cookie("XSRF-TOKEN")
        if xsrf:
            headers["X-XSRF-TOKEN"] = urllib.parse.unquote(xsrf)
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers=headers, method=method)
        try:
            resp = self._opener.open(req, timeout=30)
        except urllib.error.HTTPError as e:
            resp = e  # HTTPError is also a readable response (409, 302, 4xx)
        except urllib.error.URLError as e:
            raise APIError(f"network error: {e.reason}") from None
        body = resp.read().decode("utf-8", "replace")
        if self.debug:
            print(f"[debug] {method} {path} -> {resp.status}", flush=True)
        return resp.status, resp.headers, body

    # -- auth -------------------------------------------------------------

    def _bootstrap(self) -> None:
        """GET /login to obtain fresh XSRF/session cookies and Inertia version."""
        status, _, body = self._request("GET", "/login", inertia=False)
        if status != 200:
            raise APIError(f"GET /login returned {status}")
        m = _PAGE_RE.search(body)
        if m:
            self.version = json.loads(html.unescape(m.group(1))).get("version")

    def login(self, email: str, password: str, remember: bool = True) -> None:
        self.clear_session()
        self._bootstrap()
        status, headers, body = self._request(
            "POST", "/login",
            json_body={"email": email, "password": password, "remember": remember},
        )
        location = headers.get("X-Inertia-Location")
        if status == 409 and location and not location.rstrip("/").endswith("/login"):
            self._save_jar()
            return
        if status in (302, 303) or (status == 200 and body):
            raise AuthError(self._login_error(headers, body))
        if status == 422:
            raise AuthError(self._login_error(headers, body))
        if status in (419, 429):
            raise AuthError({419: "CSRF/session mismatch (419)",
                             429: "too many attempts (429), try later"}[status])
        raise AuthError(f"unexpected login response: HTTP {status}")

    def _login_error(self, headers, body: str) -> str:
        # Validation failures redirect back to /login with props.errors set;
        # follow that once to read the message.
        try:
            if headers.get("Location"):
                _, _, body = self._request("GET", "/login")
            errors = json.loads(body).get("props", {}).get("errors", {})
            if errors:
                return "; ".join(f"{k}: {v}" for k, v in errors.items())
        except (ValueError, APIError):
            pass
        return "login failed"

    def logout(self) -> None:
        if self.has_session():
            try:
                self._request("POST", "/logout")
            except APIError:
                pass
        self.clear_session()

    # -- inertia pages ----------------------------------------------------

    def page(self, path: str, partial: Optional[List[str]] = None,
             component: Optional[str] = None) -> Dict[str, Any]:
        """Fetch an Inertia page and return its decoded JSON payload."""
        if not self.has_session():
            raise AuthError("not logged in")
        if self.version is None:
            self._bootstrap_version()
        status, headers, body = self._request("GET", path, partial=partial,
                                              component=component)
        if status == 409 and headers.get("X-Inertia-Location"):
            # Asset version changed under us: refresh once and retry.
            self.version = None
            self._bootstrap_version()
            status, headers, body = self._request("GET", path, partial=partial,
                                                  component=component)
        if status in (301, 302, 303) and "/login" in (headers.get("Location") or ""):
            raise AuthError("session expired")
        if status in (401, 419):
            raise AuthError("session expired")
        if status != 200:
            raise APIError(f"GET {path} returned {status}")
        try:
            payload = json.loads(body)
        except ValueError:
            raise AuthError("session expired") from None  # got HTML, not Inertia JSON
        self._save_jar()  # cookies rotate on every response
        return payload

    def _bootstrap_version(self) -> None:
        status, _, body = self._request("GET", "/space", inertia=False)
        m = _PAGE_RE.search(body) if status == 200 else None
        if m:
            self.version = json.loads(html.unescape(m.group(1))).get("version")

    def whoami(self) -> Dict[str, Any]:
        payload = self.page("/space", partial=["currentUser"], component="App/Dashboard")
        user = payload.get("props", {}).get("currentUser")
        if not user:
            raise AuthError("session expired")
        return user
