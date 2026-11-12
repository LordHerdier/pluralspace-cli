"""The fixture recorder's scrubber (tools/scrub.py) guards what gets committed."""

import html
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "scrub", Path(__file__).resolve().parent.parent / "tools" / "scrub.py"
)
scrub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scrub)

UUID = "3b2a29c2-1111-4222-8333-444455556666"
BASE = "https://pluralspace.app"


def make():
    return scrub.Scrubber(BASE, ["me@real.test", "hunter2", "cookie%3Dvalue"])


def test_ids_are_pseudonymized_consistently_in_keys_values_and_paths():
    s = make()
    out = s.value({"fronters": {UUID: "t1"}, "member_id": UUID})
    pseudo = s.text(UUID)
    assert UUID not in json.dumps(out)
    assert out["member_id"] == pseudo and pseudo in out["fronters"]
    assert s.path(f"/space/fronts/{UUID}/end") == f"/space/fronts/{pseudo}/end"


def test_private_text_replaced_but_front_type_names_kept():
    s = make()
    data = {
        "frontTypes": [{"id": "t1", "name": "Front", "slug": "front"}],
        "members": [{"name": "Amanda", "display_name": "~Amanda~", "bio": "secret"}],
        "moods": [{"name": "Gloomy"}],
    }
    s.collect_keep(data)
    out = json.dumps(s.value(data))
    assert "Front" in out and "front" in out
    for private in ("Amanda", "secret", "Gloomy"):
        assert private not in out
    assert "Mood 1" in out


def test_secrets_and_external_urls_removed():
    s = make()
    out = s.value(
        {
            "password": "x",
            "msg": "hi me@real.test hunter2 cookie=value",
            "avatar": "https://cdn.other.test/a.png",
            "link": "https://other.test/x?q=Amanda",
            "ok": "https://pluralspace.app/space?q=Amanda",
        }
    )
    dumped = json.dumps(out)
    for bad in ("me@real.test", "hunter2", "other.test", "Amanda"):
        assert bad not in dumped
    assert out["ok"] == "https://pluralspace.app/space?q=query"


def test_html_page_data_is_scrubbed_and_stays_parseable():
    s = make()
    data = {"props": {"user": {"email": "me@real.test", "name": "Amanda"}}}
    page = (
        '<meta name="csrf-token" content="tok123">'
        f'<script data-page="app" type="application/json">{html.escape(json.dumps(data))}</script>'
    )
    out = s.body(page, "text/html")
    assert "Amanda" not in out and "me@real.test" not in out and "tok123" not in out
    inner = out.split(">", 2)[2].split("</script>")[0]
    assert json.loads(html.unescape(inner))["props"]["user"]["name"] == "Member 1"


def test_private_value_is_replaced_inside_prose_once_learned():
    s = make()
    s.value({"members": [{"name": "Amanda"}, {"name": "Partner"}]})  # learn
    out = json.dumps(s.value({"note": "with Partner and amanda's friend"}))
    assert "amanda" not in out.lower() and "Partner" not in out


def test_enum_words_are_never_rewritten_by_matching():
    s = make()
    s.value({"groups": [{"name": "archive"}, {"name": "system"}]})  # learn
    out = s.value({"filters": {"status": "archived"}, "appearance": "system"})
    assert out == {"filters": {"status": "archived"}, "appearance": "system"}
    assert s.check_value(out) == []  # not fatal...
    assert any("appearance" in w for w in s.warnings)  # ...but flagged


def test_real_world_free_text_and_credential_keys():
    s = make()
    s.value({"x": 1})
    out = s.value(
        {
            "body": "Your Charlotte's System export is ready",
            "title": "Waffles or bacon?",
            "initials": "T",
            "description_html": "<p>hello there</p>",
            "auth": "8TvQa5fx:deadbeef",
            "text": "#422431",
        }
    )
    dumped = json.dumps(out)
    for bad in ("Charlotte", "Waffles", "hello there", "deadbeef", '"T"'):
        assert bad not in dumped
    assert out["text"] == "#422431"  # a theme colour, not prose
    assert s.text("socket_id=4536498357.1590062039&c=1") == "socket_id=0.0&c=1"


def test_html_page_data_survives_urls_and_stays_parseable():
    s = make()
    data = {"props": {"defaultLogoUrl": "https://cdn.other.test/logo.png", "a": "b"}}
    page = (
        f'<script data-page="app" type="application/json">'
        f"{html.escape(json.dumps(data))}</script>"
    )
    out = s.body(page, "text/html")
    inner = out.split(">", 1)[1].rsplit("</script>", 1)[0]
    parsed = json.loads(html.unescape(inner))
    assert parsed["props"]["a"] == "b"
    assert parsed["props"]["defaultLogoUrl"].startswith("https://example.invalid/")
    assert s.check_body(out, "text/html") == []
    broken = out.replace("&quot;a&quot;", "")
    assert s.check_body(broken, "text/html") == ["page data that does not parse"]


def test_short_or_structural_matches_are_not_leaks():
    s = make()
    s.value({"customFields": [{"name": "Age"}], "groups": [{"name": "Members"}]})
    scrubbed = s.value(
        {
            "url": "/members?page=1",
            "links": [{"label": "Next page"}],
            "path": "/space/members/search",
        }
    )
    # "Age" must not eat "page"; paths and queries are structure, not prose
    assert scrubbed["links"][0]["label"] == "Next page"
    assert scrubbed["url"] == "/members?page=1"
    assert s.check_value(scrubbed) == []


def test_check_value_flags_missed_private_values_without_echoing_them():
    s = make()
    s.value({"name": "Amanda"})
    leaks = s.check_value({"title": "notification: Amanda started fronting"})
    assert leaks == ["a value replaced at name (length 6)"]
    assert s.check_value({"title": "Member 1 started fronting"}) == []


def test_secret_leaks_checks_whole_text():
    s = make()
    assert s.secret_leaks("login as me@real.test") == ["a login secret"]
    assert s.secret_leaks("nothing private here") == []
