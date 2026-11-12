#!/usr/bin/env python3
"""Record scrubbed Pluralspace responses as offline test fixtures.

Logs in to the real site with Playwright, walks through the things plsp does
(login, logout, session expiry, reading pages, switching fronts, moods...) and
saves every response, scrubbed (see scrub.py), under tests/fixtures/site/.

Read-only scenarios are the default. Scenarios that WRITE (fronts, moods) only
run with --write, and need an account you don't mind: they start/end/edit/
delete fronts and set/clear the mood. They only delete rows they created, and
they try to put the front set and mood back afterwards (rows they had to end
are reopened with their original start time).

Nothing is written to disk until every exchange has been scrubbed and
re-checked for leaks. See tools/README.md.
"""

import argparse
import html
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrub import Scrubber  # noqa: E402

from pluralspace.credentials import CredentialError, PassStore  # noqa: E402
from pluralspace.fronts import reopen_body, row_from_calendar  # noqa: E402

BASE_URL = "https://pluralspace.app"
DELAY = 1.5  # seconds between actions; set from --delay
WRONG_PASSWORD = "plsp-fixtures-wrong-password"
KEEP_HEADERS = {
    "content-type",
    "location",
    "x-inertia",
    "x-inertia-location",
    "retry-after",
}
PAGE_RE = re.compile(r'<script[^>]*data-page="app"[^>]*>(.*?)</script>', re.DOTALL)

# The login form. If the site changes these, fix them here.
EMAIL_SELECTOR = 'input[type="email"], input[name="email"]'
PASSWORD_SELECTOR = 'input[type="password"]'
SUBMIT_SELECTOR = 'button[type="submit"]'


class RecorderError(Exception):
    pass


def pause() -> None:
    """Be polite to the site: wait between actions."""
    time.sleep(DELAY)


# -- recording -----------------------------------------------------------


@dataclass
class Exchange:
    scenario: str
    label: str
    method: str
    path: str
    request_body: Optional[str]
    status: int
    headers: List[tuple]
    set_cookie_names: List[str]
    body: str


@dataclass
class Recorder:
    scenario: str = ""
    label: str = ""
    exchanges: List[Exchange] = field(default_factory=list)
    site_version: Optional[str] = None
    secrets: set = field(default_factory=set)  # cookie values seen, rotated or not

    def add(self, method, url, request_body, status, headers, body: bytes, base):
        path = url[len(base) :] if url.startswith(base) else url
        kept = [(k.lower(), v) for k, v in headers if k.lower() in KEEP_HEADERS]
        cookies = [v.split("=", 1)[0] for k, v in headers if k.lower() == "set-cookie"]
        text = body.decode("utf-8", "replace")
        m = PAGE_RE.search(text)
        if m and self.site_version is None:
            try:
                self.site_version = json.loads(html.unescape(m.group(1))).get("version")
            except ValueError:
                pass
        self.exchanges.append(
            Exchange(
                self.scenario, self.label, method, path, request_body,
                status, kept, cookies, text,
            )
        )  # fmt: skip


@dataclass
class Reply:
    status: int
    headers: Dict[str, str]
    text: str

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except ValueError:
            return None

    @property
    def props(self) -> Dict[str, Any]:
        data = self.json() or {}
        return data.get("props", {}) if isinstance(data, dict) else {}


class Site:
    """Requests that behave like the CLI's: Inertia headers, XSRF echo, no
    redirects followed. They go through the browser context, so they share the
    cookies the real login created."""

    def __init__(self, context, rec: Recorder, base: str):
        self.ctx, self.rec, self.base = context, rec, base
        self.version: Optional[str] = None

    def note_cookies(self) -> None:
        self.rec.secrets.update(c["value"] for c in self.ctx.cookies())

    def xsrf(self) -> Optional[str]:
        for c in self.ctx.cookies():
            if c["name"] == "XSRF-TOKEN":
                return unquote(c["value"])
        return None

    def request(
        self,
        label: str,
        method: str,
        path: str,
        *,
        body: Optional[dict] = None,
        inertia: bool = True,
        partial: Optional[List[str]] = None,
        component: Optional[str] = None,
        xsrf: Optional[str] = "auto",
        version: Optional[str] = "auto",
    ) -> Reply:
        pause()
        self.rec.label = label
        headers = {"Origin": self.base, "Referer": self.base + "/"}
        if inertia:
            headers.update(
                {
                    "Accept": "text/html, application/xhtml+xml",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-Inertia": "true",
                }
            )
            v = self.version if version == "auto" else version
            if v:
                headers["X-Inertia-Version"] = v
            if partial and component:
                headers["X-Inertia-Partial-Component"] = component
                headers["X-Inertia-Partial-Data"] = ",".join(partial)
        else:
            headers["Accept"] = "text/html"
        token = self.xsrf() if xsrf == "auto" else xsrf
        if token:
            headers["X-XSRF-TOKEN"] = token
        data = None
        if body is not None:
            data = json.dumps(body)
            headers["Content-Type"] = "application/json"
        resp = self.ctx.request.fetch(
            self.base + path,
            method=method,
            headers=headers,
            data=data,
            max_redirects=0,
            fail_on_status_code=False,
        )
        raw = resp.body()
        self.note_cookies()
        self.rec.add(
            method, self.base + path, data, resp.status,
            [(h["name"], h["value"]) for h in resp.headers_array], raw, self.base,
        )  # fmt: skip
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        return Reply(resp.status, hdrs, raw.decode("utf-8", "replace"))

    # -- what the CLI does ------------------------------------------------

    def bootstrap(self, label: str) -> None:
        """GET /space as a document to learn the Inertia asset version."""
        r = self.request(label, "GET", "/space", inertia=False)
        m = PAGE_RE.search(r.text)
        if m:
            self.version = json.loads(html.unescape(m.group(1))).get("version")

    def partial(self, label: str, path: str, names: List[str], component: str):
        return self.request(
            label, "GET", path, partial=names, component=component
        ).props

    def deferred(self, label: str, path: str) -> Dict[str, Any]:
        first = self.request(label, "GET", path)
        data = first.json() or {}
        names = [
            n for group in (data.get("deferredProps") or {}).values() for n in group
        ]
        props = dict(data.get("props") or {})
        if names:
            second = self.request(
                label + "-deferred", "GET", path, partial=names,
                component=data.get("component"),
            )  # fmt: skip
            props.update(second.props)
        return props

    def current_fronts(self, label: str) -> List[dict]:
        return (
            self.partial(
                label,
                "/space",
                ["currentFronts", "currentFrontsTotal"],
                "App/Dashboard",
            ).get("currentFronts")
            or []
        )

    def atmosphere(self, label: str) -> dict:
        return (
            self.partial(label, "/space", ["atmosphere"], "App/Dashboard").get(
                "atmosphere"
            )
            or {}
        )

    def front_types(self, label: str) -> List[dict]:
        p = self.partial(
            label, "/space", ["frontTypes", "subsystemFrontTypes"], "App/Dashboard"
        )
        return (p.get("frontTypes") or []) + (p.get("subsystemFrontTypes") or [])

    def calendar(self, label: str, month: Optional[str] = None) -> dict:
        path = "/space/fronts" + (f"?month={quote(month)}" if month else "")
        return self.deferred(label, path)

    def calendar_rows(self, label: str) -> Dict[str, dict]:
        rows = {}
        for week in self.calendar(label).get("weeks") or []:
            for day in week:
                for f in day.get("fronts") or []:
                    rows.setdefault(f["id"], f)
        return rows

    def members(self, label: str, query: str = "", page: int = 1, extra: str = ""):
        qs = f"page={page}" + (f"&q={quote(query)}" if query else "") + extra
        return self.deferred(label, f"/members?{qs}")


# -- login through the real UI --------------------------------------------


def ui_login(page, site: Site, email: str, password: str, label: str, expect_ok: bool):
    """Log in through the actual form, recording every document/XHR response."""
    site.rec.label = label

    def on_response(resp):
        req = resp.request
        if req.resource_type not in ("document", "xhr", "fetch"):
            return
        if not resp.url.startswith(site.base):
            return
        try:
            body = resp.body()
        except Exception:  # redirects have no body
            body = b""
        site.note_cookies()
        site.rec.add(
            req.method, resp.url, req.post_data, resp.status,
            [(h["name"], h["value"]) for h in resp.headers_array()], body, site.base,
        )  # fmt: skip

    page.on("response", on_response)
    try:
        page.goto(site.base + "/login")
        pause()
        page.fill(EMAIL_SELECTOR, email)
        page.fill(PASSWORD_SELECTOR, password)
        pause()
        if expect_ok:
            with page.expect_navigation(url=re.compile(r"/space")):
                page.click(SUBMIT_SELECTOR)
            page.wait_for_load_state("networkidle")
        else:
            page.click(SUBMIT_SELECTOR)
            page.wait_for_load_state("networkidle")
    finally:
        page.remove_listener("response", on_response)


# -- scenarios ------------------------------------------------------------


@dataclass
class Ctx:
    site: Site
    page: Any
    email: str
    password: str
    new_context: Callable[[], Any]


def scenario_auth(c: Ctx) -> None:
    """Login (browser and CLI-style), bad password, XSRF and version
    mismatches, logout, and what an expired session looks like."""
    s = c.site
    ui_login(c.page, s, c.email, c.password, "ui-login", True)
    s.bootstrap("session-dashboard")
    s.request(
        "whoami", "GET", "/space", partial=["currentUser"], component="App/Dashboard"
    )

    # XSRF: a POST with a wrong token must be rejected before doing anything.
    s.request("xsrf-bad-token", "POST", "/logout", body={}, xsrf="not-the-token")
    # 409: a stale asset version on a GET (harmless) gets X-Inertia-Location.
    s.request("version-mismatch", "GET", "/space", version="stale-version")

    s.request("logout", "POST", "/logout", body={})
    s.request("after-logout", "GET", "/space")  # redirect to /login
    s.request("after-logout-document", "GET", "/space", inertia=False)

    # Re-login exactly like plsp: bootstrap /login, then POST JSON.
    s.request("cli-login-page", "GET", "/login", inertia=False)
    s.request(
        "cli-login-bad-password", "POST", "/login",
        body={"email": c.email, "password": WRONG_PASSWORD, "remember": True},
    )  # fmt: skip
    s.request("cli-login-errors", "GET", "/login")
    s.request("cli-login-page-again", "GET", "/login", inertia=False)
    s.request(
        "cli-login", "POST", "/login",
        body={"email": c.email, "password": c.password, "remember": True},
    )  # fmt: skip
    s.bootstrap("cli-login-dashboard")

    # A fresh browser, wrong password through the real form.
    ctx2 = c.new_context()
    try:
        page2 = ctx2.new_page()
        s2 = Site(ctx2, s.rec, s.base)
        ui_login(page2, s2, c.email, WRONG_PASSWORD, "ui-login-bad-password", False)
    finally:
        ctx2.close()


def scenario_reads(c: Ctx) -> None:
    """Every page and lookup plsp reads."""
    s = c.site
    ui_login(c.page, s, c.email, c.password, "ui-login", True)
    s.bootstrap("dashboard-document")
    s.request(
        "whoami", "GET", "/space", partial=["currentUser"], component="App/Dashboard"
    )
    s.current_fronts("current-fronts")
    s.atmosphere("atmosphere")
    s.front_types("front-types")

    page1 = s.members("members-page-1")
    s.members("members-search", query="a")
    s.members("members-archived", extra="&status=archived")
    s.members("members-fronting", extra="&fronting=1")
    meta = (page1.get("members") or {}).get("meta") or {}
    if meta.get("last_page", 1) > 1:
        s.members("members-page-2", page=2)
    data = (page1.get("members") or {}).get("data") or []
    if data:
        s.deferred("member-profile", f"/members/{quote(data[0]['id'])}")

    cal = s.calendar("fronts-calendar")
    month = (cal.get("month") or {}).get("value")
    if month:
        s.calendar("fronts-calendar-month", month)
    s.request("moods", "GET", "/system/moods/search?q=")
    s.request("member-search", "GET", "/space/members/search?tree=front&q=")
    s.request("member-search-query", "GET", "/space/members/search?tree=front&q=a")


def _pick_members(c: Ctx, count: int) -> List[dict]:
    data = ((c.site.members("pick-members").get("members")) or {}).get("data") or []
    if len(data) < count:
        raise RecorderError(f"the account needs at least {count} members")
    return data[:count]


def _put_fronts_back(s: Site, baseline_ids: List[str], created: List[str], tz: str):
    """End everything, delete only the rows this run made, reopen the rows
    that were live when we started."""
    s.request("cleanup-end-all", "POST", "/space/fronts/end-all", body={})
    for rid in created:
        s.request("cleanup-delete", "DELETE", f"/space/fronts/{quote(rid)}", body={})
    rows = s.calendar_rows("cleanup-calendar")
    for rid in baseline_ids:
        f = rows.get(rid)
        if f is None or f.get("ended_at") is None:
            continue
        try:
            body = reopen_body(row_from_calendar(f), tz)
        except ValueError as e:
            print(f"warning: could not reopen a front ({e}); put it back by hand")
            continue
        s.request("cleanup-reopen", "PATCH", f"/space/fronts/{quote(rid)}", body=body)


def scenario_fronts(c: Ctx) -> None:
    """Switch, add, retype, end, edit, reopen, delete, and the error cases."""
    s = c.site
    ui_login(c.page, s, c.email, c.password, "ui-login", True)
    s.bootstrap("dashboard-document")
    a, b = _pick_members(c, 2)
    types = s.front_types("front-types")
    if not types:
        raise RecorderError("the account has no front types")
    t1, t2 = types[0], types[1] if len(types) > 1 else None

    baseline = s.current_fronts("baseline-current-fronts")
    baseline_ids = [f["id"] for f in baseline]
    before = s.calendar_rows("baseline-calendar")
    tz = (s.calendar("baseline-calendar-props").get("viewerTimezone")) or "UTC"
    created: List[str] = []

    def track(label):
        rows = s.calendar_rows(label)
        for rid in rows:
            if rid not in before and rid not in created:
                created.append(rid)
        return rows

    def start(label, fronters, comment=None, silent=False):
        s.request(
            label, "POST", "/space/fronts/start-multi",
            body={"fronters": fronters, "comment": comment, "silent": silent},
        )  # fmt: skip
        s.current_fronts(label + "-verify")
        return track(label + "-calendar")

    try:
        start("switch-one", {a["id"]: t1["id"]}, comment="fixture comment")
        start("add-second", {a["id"]: t1["id"], b["id"]: t1["id"]})
        if t2:
            start("retype-second", {a["id"]: t1["id"], b["id"]: t2["id"]})
        s.request("end-one", "POST", f"/space/fronts/{quote(b['id'])}/end", body={})
        s.current_fronts("end-one-verify")
        s.request(  # errors must be recorded, not just the happy path
            "start-unknown-member", "POST", "/space/fronts/start-multi",
            body={"fronters": {"00000000-0000-4000-8000-00000000dead": t1["id"]},
                  "comment": None, "silent": False},
        )  # fmt: skip
        s.request("end-all", "POST", "/space/fronts/end-all", body={})
        s.current_fronts("end-all-verify")

        rows = track("created-rows")
        if created:
            rid = created[0]
            row = row_from_calendar(rows[rid])
            body = reopen_body(row, tz)
            s.request("reopen", "PATCH", f"/space/fronts/{quote(rid)}", body=body)
            s.current_fronts("reopen-verify")
            body["comment"] = "edited by fixtures"
            s.request("edit-comment", "PATCH", f"/space/fronts/{quote(rid)}", body=body)
            track("edit-calendar")
            s.request("end-all-again", "POST", "/space/fronts/end-all", body={})
            s.request("delete-front", "DELETE", f"/space/fronts/{quote(rid)}", body={})
            # Deleting again shows what a replayed delete looks like.
            s.request(
                "delete-front-replay", "DELETE", f"/space/fronts/{quote(rid)}", body={}
            )
            created.remove(rid)
    finally:
        print("restoring fronts...")
        _put_fronts_back(s, baseline_ids, created, tz)
        now = {f["id"] for f in s.current_fronts("final-current-fronts")}
        if now != set(baseline_ids):
            print("warning: live fronts differ from before the run; check the app")


def scenario_moods(c: Ctx) -> None:
    """Set, change and clear the mood, plus an unknown mood."""
    s = c.site
    ui_login(c.page, s, c.email, c.password, "ui-login", True)
    s.bootstrap("dashboard-document")
    moods = (s.request("moods", "GET", "/system/moods/search?q=").json() or {}).get(
        "data"
    ) or []
    if not moods:
        raise RecorderError("the account has no moods")
    before = s.atmosphere("baseline-atmosphere")
    try:
        s.request("set-mood", "POST", "/space/mood", body={"mood": moods[0]["id"]})
        s.atmosphere("set-mood-verify")
        other = moods[1] if len(moods) > 1 else moods[0]
        s.request("change-mood", "POST", "/space/mood", body={"mood": other["id"]})
        s.atmosphere("change-mood-verify")
        s.request("clear-mood", "DELETE", "/space/mood", body={})
        s.atmosphere("clear-mood-verify")
        s.request(
            "set-unknown-mood", "POST", "/space/mood",
            body={"mood": "00000000-0000-4000-8000-00000000dead"},
        )  # fmt: skip
    finally:
        print("restoring mood...")
        if before.get("mood"):
            s.request(
                "cleanup-mood", "POST", "/space/mood", body={"mood": before["mood"]}
            )
        else:
            s.request("cleanup-mood", "DELETE", "/space/mood", body={})


SAFE = {"auth": scenario_auth, "reads": scenario_reads}
WRITES = {"fronts": scenario_fronts, "moods": scenario_moods}


# -- output ---------------------------------------------------------------


def extension(content_type: str) -> str:
    return (
        "json"
        if "json" in content_type
        else "html"
        if "html" in content_type
        else "txt"
    )


def write_fixtures(rec: Recorder, scrubber: Scrubber, out: Path, base: str) -> int:
    for ex in rec.exchanges:  # learn front type names before scrubbing anything
        try:
            scrubber.collect_keep(json.loads(ex.body))
        except ValueError:
            pass
    for ex in rec.exchanges:  # learn every private value before replacing any
        scrubber.body(ex.body, dict(ex.headers).get("content-type", ""))
    files: Dict[Path, str] = {}
    leaks: List[tuple] = []  # (file, what), never the values
    manifests: Dict[str, List[dict]] = {}
    for n, ex in enumerate(rec.exchanges, 1):
        ctype = dict(ex.headers).get("content-type", "")
        entry = {
            "seq": n,
            "label": ex.label,
            "method": ex.method,
            "path": scrubber.path(ex.path),
            "status": ex.status,
            "headers": {k: scrubber.text(v) for k, v in ex.headers},
            "set_cookies": ex.set_cookie_names,
        }
        where = f"{ex.scenario}/{n:03d}-{ex.label}"
        if ex.request_body:
            try:
                entry["request_body"] = scrubber.value(json.loads(ex.request_body))
                found = scrubber.check_value(entry["request_body"])
                leaks += [(where + " (request)", w) for w in found]
            except ValueError:
                entry["request_body"] = scrubber.text(ex.request_body)
        if ex.body:
            name = f"{len(manifests.get(ex.scenario, [])) + 1:03d}-{ex.label}.{extension(ctype)}"
            entry["body_file"] = name
            text = scrubber.body(ex.body, ctype)
            files[out / ex.scenario / name] = text
            leaks += [(where, w) for w in scrubber.check_body(text, ctype)]
        manifests.setdefault(ex.scenario, []).append(entry)
    for scenario, entries in manifests.items():
        files[out / scenario / "manifest.json"] = (
            json.dumps({"scenario": scenario, "exchanges": entries}, indent=2) + "\n"
        )
    files[out / "index.json"] = (
        json.dumps(
            {"site_version": rec.site_version, "scenarios": sorted(manifests)}, indent=2
        )
        + "\n"
    )

    for path, text in files.items():
        leaks += [(str(path.relative_to(out)), w) for w in scrubber.secret_leaks(text)]
    if leaks:
        for where, what in sorted(set(leaks)):
            print(f"LEAK: {what} in {where}", file=sys.stderr)
        raise RecorderError("scrubbing left private data behind; nothing was written")
    for scenario in manifests:
        shutil.rmtree(out / scenario, ignore_errors=True)
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return len(rec.exchanges)


# -- main -----------------------------------------------------------------


def credentials(profile: str):
    email, password = (
        os.environ.get("PLSP_FIXTURE_EMAIL"),
        os.environ.get("PLSP_FIXTURE_PASSWORD"),
    )
    if email and password:
        return email, password
    try:
        creds = PassStore(profile).load()
    except CredentialError as e:
        raise RecorderError(
            f"{e}\nSet PLSP_FIXTURE_EMAIL and PLSP_FIXTURE_PASSWORD, or save a pass "
            f"entry pluralspace/{profile}."
        ) from None
    return creds.email, creds.password


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("scenarios", nargs="*", help=f"any of {sorted({**SAFE, **WRITES})}")
    p.add_argument(
        "--write",
        action="store_true",
        help="also run the scenarios that change the account (fronts, moods)",
    )
    p.add_argument(
        "--profile",
        default="testing",
        help="pass entry pluralspace/<profile> to log in with (default: testing)",
    )
    p.add_argument("--base-url", default=BASE_URL)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "site")
    p.add_argument(
        "--delay",
        type=float,
        default=DELAY,
        help="seconds to wait between actions (default: %(default)s)",
    )
    p.add_argument("--headed", action="store_true", help="show the browser")
    p.add_argument("--yes", action="store_true", help="don't ask before writing")
    return p.parse_args(argv)  # fmt: skip


def main(argv=None) -> int:
    global DELAY
    args = parse_args(argv)
    DELAY = max(0.0, args.delay)
    every = {**SAFE, **WRITES}
    names = args.scenarios or (list(SAFE) + (list(WRITES) if args.write else []))
    unknown = [n for n in names if n not in every]
    if unknown:
        print(f"unknown scenario(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    writing = [n for n in names if n in WRITES]
    if writing and not args.write:
        print(f"{', '.join(writing)} change the account: pass --write", file=sys.stderr)
        return 2

    try:
        email, password = credentials(args.profile)
        if writing and not args.yes:
            print(
                f"These scenarios WRITE to the account {email}:\n  {', '.join(writing)}"
            )
            if input("Type the email to continue: ").strip() != email:
                print("aborted")
                return 1
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is missing: see tools/README.md", file=sys.stderr)
        return 2
    except RecorderError as e:
        print(e, file=sys.stderr)
        return 2

    base = args.base_url.rstrip("/")
    rec = Recorder()
    scrubber = Scrubber(base, [email, password, WRONG_PASSWORD])
    failed = False
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        try:
            for name in names:
                print(f"== {name}")
                rec.scenario = name
                context = browser.new_context()
                site = Site(context, rec, base)
                try:
                    ctx = Ctx(site, context.new_page(), email, password,
                              lambda: browser.new_context())  # fmt: skip
                    every[name](ctx)
                except Exception as e:  # keep what we have for the other scenarios
                    failed = True
                    print(f"{name} failed: {type(e).__name__}: {e}", file=sys.stderr)
                finally:
                    site.note_cookies()
                    context.close()
        finally:
            browser.close()
    for value in rec.secrets:
        scrubber.add_secret(value)
    if failed:
        print("a scenario failed: not writing fixtures", file=sys.stderr)
        return 1
    try:
        count = write_fixtures(rec, scrubber, args.out, base)
    except RecorderError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"wrote {count} exchanges to {args.out}")
    for w in sorted(scrubber.warnings):
        print(f"check by hand: {w}")
    print("Review `git diff` / `git status` before committing: names and text were")
    print("scrubbed by key, so look for anything personal that slipped through.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
