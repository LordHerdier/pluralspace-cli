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
from typing import Any, Dict, Iterable, List, NamedTuple, Optional

from . import __version__
from .fronts import reopen_body, row_from_calendar
from .state import state_dir
from .timeutil import month_of

BASE_URL = "https://pluralspace.app"
USER_AGENT = f"pluralspace-cli/{__version__}"

_PAGE_RE = re.compile(r'<script[^>]*data-page="app"[^>]*>(.*?)</script>', re.DOTALL)


class APIError(Exception):
    pass


class AuthError(APIError):
    """Login rejected, or the session is missing/expired."""


class CalendarState(NamedTuple):
    """Front rows from the calendar view. `timezone` is the viewer's IANA zone,
    which the front edit form uses for naive timestamps."""

    timezone: str
    can_edit: bool
    rows: Dict[str, Dict[str, Any]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class PluralspaceAPI:
    def __init__(
        self, profile: str = "default", base_url: str = BASE_URL, debug: bool = False
    ):
        self.base_url = base_url.rstrip("/")
        self.debug = debug
        self.version: Optional[str] = None
        self.jar_path = state_dir() / f"{profile}.cookies"
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

    def _request(
        self,
        method: str,
        path: str,
        *,
        inertia: bool = True,
        json_body: Optional[dict] = None,
        partial: Optional[List[str]] = None,
        component: Optional[str] = None,
    ):
        headers = {
            "User-Agent": USER_AGENT,
            "Origin": self.base_url,
            "Referer": self.base_url + "/",
        }
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

        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
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
            "POST",
            "/login",
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
            raise AuthError(
                {
                    419: "CSRF/session mismatch (419)",
                    429: "too many attempts (429), try later",
                }[status]
            )
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

    def page(
        self,
        path: str,
        partial: Optional[List[str]] = None,
        component: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch an Inertia page and return its decoded JSON payload."""
        if not self.has_session():
            raise AuthError("not logged in")
        if self.version is None:
            self._bootstrap_version()
        status, headers, body = self._request(
            "GET", path, partial=partial, component=component
        )
        if status == 409 and headers.get("X-Inertia-Location"):
            # Asset version changed under us: refresh once and retry.
            self.version = None
            self._bootstrap_version()
            status, headers, body = self._request(
                "GET", path, partial=partial, component=component
            )
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
        payload = self.page(
            "/space", partial=["currentUser"], component="App/Dashboard"
        )
        user = payload.get("props", {}).get("currentUser")
        if not user:
            raise AuthError("session expired")
        return user

    def page_deferred(self, path: str) -> Dict[str, Any]:
        """Fetch a page plus the props Inertia defers to a follow-up request."""
        first = self.page(path)
        names = [n for group in first.get("deferredProps", {}).values() for n in group]
        if not names:
            return first.get("props", {})
        second = self.page(path, partial=names, component=first["component"])
        return {**first.get("props", {}), **second.get("props", {})}

    # -- members / fronts -------------------------------------------------

    def members(
        self,
        query: str = "",
        archived: bool = False,
        fronting: bool = False,
        member_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if query:
            params["q"] = query
        if archived:
            params["status"] = "archived"
        if fronting:
            params["fronting"] = "1"
        if member_type:
            params["type"] = member_type
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            qs = urllib.parse.urlencode({**params, "page": page})
            members = self.page_deferred(f"/members?{qs}")["members"]
            out.extend(members["data"])
            if page >= members["meta"]["last_page"]:
                return out
            page += 1

    def current_fronts(self) -> List[Dict[str, Any]]:
        payload = self.page(
            "/space",
            component="App/Dashboard",
            partial=["currentFronts", "currentFrontsTotal"],
        )
        return payload["props"]["currentFronts"]

    def fronts_page(self, month: Optional[str] = None) -> Dict[str, Any]:
        """Props of the front calendar for a YYYY-MM month (default: current)."""
        path = "/space/fronts" + (
            f"?month={urllib.parse.quote(month)}" if month else ""
        )
        return self.page_deferred(path)

    def front_history(self, month: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fronts touching the given YYYY-MM month (default: current), newest first."""
        return dedupe_fronts(self.fronts_page(month)["weeks"])

    def calendar_state(self, started_ats: Iterable[str] = ()) -> CalendarState:
        """Every front row in the current month plus the months the given
        start times fall in, as normalized rows keyed by id.

        Unlike `current_fronts`, the calendar lists *every* ongoing row, so it
        shows a member with two live rows (the dashboard hides one).
        """
        props = self.fronts_page()
        tz = props.get("viewerTimezone") or "UTC"
        can_edit = bool((props.get("permissions") or {}).get("edit_fronts"))
        current = (props.get("month") or {}).get("value")
        rows: Dict[str, Dict[str, Any]] = {}

        def add(page_props):
            for f in dedupe_fronts(page_props["weeks"]):
                rows.setdefault(f["id"], row_from_calendar(f))

        add(props)
        for month in sorted({month_of(ts, tz) for ts in started_ats} - {current}):
            add(self.fronts_page(month))
        return CalendarState(tz, can_edit, rows)

    def end_front(self, member_id: str) -> None:
        """End a member's live front. Leaves other fronters untouched."""
        self._mutate(f"/space/fronts/{urllib.parse.quote(member_id)}/end", {})

    def delete_front(self, front_id: str) -> None:
        """Delete one front row from the history. There is no undo for this."""
        self._mutate(
            f"/space/fronts/{urllib.parse.quote(front_id)}",
            {},
            method="DELETE",
            retry_on_409=False,  # a replay would 404 and hide that it worked
        )

    def reopen_front(self, row: Dict[str, Any], tz_name: str) -> None:
        """Make an ended front row live again, keeping its start time."""
        try:
            body = reopen_body(row, tz_name)
        except ValueError as e:
            raise APIError(f"won't edit front {row['id']}: {e}") from None
        self._mutate(
            f"/space/fronts/{urllib.parse.quote(row['id'])}", body, method="PATCH"
        )

    def member(self, member_id: str) -> Dict[str, Any]:
        """Full profile props for one member (by full id)."""
        return self.page_deferred(f"/members/{urllib.parse.quote(member_id)}")

    # -- moods ------------------------------------------------------------

    def moods(self) -> List[Dict[str, Any]]:
        return self._get_json("/system/moods/search?q=")["data"]

    def atmosphere(self) -> Dict[str, Any]:
        """The dashboard's headspace summary, including the current mood."""
        payload = self.page("/space", component="App/Dashboard", partial=["atmosphere"])
        return payload["props"]["atmosphere"]

    def set_mood(self, mood_id: str) -> None:
        self._mutate("/space/mood", {"mood": mood_id})

    def clear_mood(self) -> None:
        self._mutate("/space/mood", {}, method="DELETE")

    # -- switching --------------------------------------------------------

    def front_types(self) -> List[Dict[str, Any]]:
        payload = self.page(
            "/space",
            component="App/Dashboard",
            partial=["frontTypes", "subsystemFrontTypes"],
        )
        props = payload["props"]
        return props["frontTypes"] + props.get("subsystemFrontTypes", [])

    def search_members(self, query: str) -> List[Dict[str, Any]]:
        """The front picker's search; includes custom fronts, unlike /members."""
        qs = urllib.parse.urlencode({"tree": "front", "q": query})
        return self._get_json(f"/space/members/search?{qs}")

    def set_fronts(
        self,
        fronters: Dict[str, str],
        comment: Optional[str] = None,
        silent: bool = False,
    ) -> None:
        """Replace the whole front set. fronters maps member id -> front type id.

        The server diffs against the current set: unchanged fronters keep
        their start time, so this is safe to send with the full list.
        """
        self._mutate(
            "/space/fronts/start-multi",
            {"fronters": fronters, "comment": comment, "silent": silent},
        )

    def end_all(self) -> None:
        self._mutate("/space/fronts/end-all", {})

    def _get_json(self, path: str):
        if not self.has_session():
            raise AuthError("not logged in")
        if self.version is None:
            self._bootstrap_version()
        status, headers, body = self._request("GET", path)
        self._check_session(status, headers)
        if status != 200:
            raise APIError(f"GET {path} returned {status}")
        try:
            data = json.loads(body)
        except ValueError:
            raise AuthError("session expired") from None
        self._save_jar()
        return data

    def _mutate(
        self, path: str, body: dict, method: str = "POST", retry_on_409: bool = True
    ) -> None:
        """Send a write.

        On a 409 with X-Inertia-Location (the asset version changed under us)
        refresh the version and send it once more, but only if `retry_on_409`:
        every caller except `delete_front` sends full desired state, so a
        replay can't double-apply. Otherwise the outcome is unknown and we say
        so rather than guess.
        """
        if not self.has_session():
            raise AuthError("not logged in")
        if self.version is None:
            self._bootstrap_version()
        status, headers, text = self._request(method, path, json_body=body)
        if status == 409 and headers.get("X-Inertia-Location"):
            self.version = None
            self._bootstrap_version()
            if not retry_on_409:
                raise APIError(
                    f"{method} {path} returned 409 (site updated); it may or may "
                    "not have been applied. Check the current state before retrying."
                )
            status, headers, text = self._request(method, path, json_body=body)
        self._check_session(status, headers)
        # Inertia answers a successful form post with a redirect (302, or 303 for DELETE).
        if status not in (200, 204, 302, 303):
            detail = ""
            try:
                detail = "; ".join(
                    f"{k}: {v}" for k, v in json.loads(text).get("errors", {}).items()
                )
            except (ValueError, AttributeError):
                pass
            raise APIError(f"{method} {path} returned {status} {detail}".strip())
        self._save_jar()

    @staticmethod
    def _check_session(status: int, headers) -> None:
        if status in (401, 419) or (
            status in (301, 302, 303) and "/login" in (headers.get("Location") or "")
        ):
            raise AuthError("session expired")


def dedupe_fronts(weeks: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The calendar repeats a front on every day it spans; keep each once."""
    seen: Dict[str, Dict[str, Any]] = {}
    for week in weeks:
        for day in week:
            for front in day["fronts"]:
                seen.setdefault(front["id"], front)
    return sorted(seen.values(), key=lambda f: f["started_at"], reverse=True)
