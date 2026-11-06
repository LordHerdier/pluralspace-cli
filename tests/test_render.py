import time

import pytest

from pluralspace.render import (
    _day,
    _strip_html,
    editorjs_text,
    front_member_label,
    front_type_name,
    member_flags,
)


def test_strip_html_handles_breaks_tags_and_entities():
    assert _strip_html("a<br>b<br/>c") == "a\nb\nc"
    assert _strip_html("<b>x</b>&nbsp;&amp;&nbsp;y") == "x & y"
    assert _strip_html(None) == ""


def test_editorjs_blocks():
    doc = {
        "blocks": [
            {"type": "paragraph", "data": {"text": "hi <i>there</i>"}},
            {"type": "quote", "data": {"text": "q", "caption": "me"}},
            {
                "type": "list",
                "data": {
                    "style": "ordered",
                    "items": [
                        {"content": "one", "items": [{"content": "inner"}]},
                        "two",
                    ],
                },
            },
            {"type": "table", "data": {"content": [["a", "b"], ["c", "d"]]}},
            {"type": "image", "data": {"file": {"url": "http://x/i.png"}}},
            {
                "type": "gallery",
                "data": {"images": [{"file": {"url": "http://x/g.png"}}]},
            },
            {
                "type": "columns",
                "data": {
                    "cols": [
                        {"blocks": [{"type": "paragraph", "data": {"text": "col"}}]}
                    ]
                },
            },
        ]
    }
    assert editorjs_text(doc).splitlines() == [
        "hi there",
        "> q",
        "  — me",
        "1. one",
        "  1. inner",
        "2. two",
        "a | b",
        "c | d",
        "[image: http://x/i.png]",
        "[image: http://x/g.png]",
        "col",
    ]


def test_editorjs_text_edge_cases():
    assert editorjs_text("plain text") == "plain text"
    assert editorjs_text("{not json") == "{not json"
    assert editorjs_text({"no": "blocks"}) == ""
    assert editorjs_text(None) == ""
    assert editorjs_text({"blocks": []}) == ""
    only_blank = {"blocks": [{"type": "paragraph", "data": {"text": ""}}]}
    assert editorjs_text(only_blank) == ""
    # a JSON string is parsed
    assert editorjs_text('{"blocks":[{"type":"paragraph","data":{"text":"x"}}]}') == "x"


@pytest.fixture
def utc_plus_2(monkeypatch):
    monkeypatch.setenv("TZ", "Etc/GMT-2")  # POSIX sign: this is UTC+2
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_day_converts_utc_to_local(utc_plus_2):
    assert _day("2026-11-03T03:04:19+00:00") == "2026-11-03 05:04"
    assert _day("2026-11-03T03:04:19Z") == "2026-11-03 05:04"
    assert _day("2026-11-03T03:04:19") == "2026-11-03 05:04"  # naive means UTC


def test_day_degrades_gracefully():
    assert _day("") == "-"
    assert _day(None) == "-"
    # unparseable input is truncated to 16 chars, with "T" shown as a space
    assert _day("garbage-Tgarbage-and-more") == "garbage- garbage"


def test_member_flags_order_and_options():
    m = {
        "active_front": True,
        "is_custom_front": True,
        "is_pinned": True,
        "is_archived": True,
    }
    assert member_flags(m, fronting=True) == [
        "fronting",
        "custom",
        "pinned",
        "archived",
    ]
    assert member_flags(m) == ["custom", "pinned", "archived"]
    assert member_flags(m, custom_label="custom front")[0] == "custom front"
    assert member_flags({}) == []


def test_front_helpers():
    assert front_member_label({"member": {"display_label": "Ada"}}) == "Ada"
    assert front_member_label({"member": None}) == "(hidden)"
    assert front_member_label({"member": {"display_label": ""}}) == "(hidden)"
    assert front_type_name({"front_type": {"name": "Front"}}) == "Front"
    assert front_type_name({}) == ""
