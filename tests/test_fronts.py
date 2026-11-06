from pluralspace.api_client import dedupe_fronts


def _front(id_, started):
    return {"id": id_, "started_at": started}


def test_dedupe_keeps_each_front_once_newest_first():
    weeks = [
        [
            {"fronts": [_front("a", "2026-09-08T00:00:00+00:00")]},
            {
                "fronts": [
                    _front("a", "2026-09-08T00:00:00+00:00"),
                    _front("b", "2026-10-01T00:00:00+00:00"),
                ]
            },
        ]
    ]
    assert [f["id"] for f in dedupe_fronts(weeks)] == ["b", "a"]


def test_resolve_front_type_by_name_or_slug():
    from pluralspace.cli import resolve_front_type

    types = [
        {"id": "1", "name": "Co-Front", "slug": "co_front"},
        {"id": "2", "name": "Front", "slug": "front"},
    ]
    assert resolve_front_type(types, "front")["id"] == "2"
    assert resolve_front_type(types, "co_front")["id"] == "1"


def test_resolve_mood_exact_only():
    import pytest

    from pluralspace.cli import resolve_mood
    from pluralspace.credentials import CredentialError

    moods = [
        {"id": "1", "name": "Calm"},
        {"id": "2", "name": "Content"},
        {"id": "3", "name": "Tired"},
    ]
    assert resolve_mood(moods, "calm")["id"] == "1"
    with pytest.raises(CredentialError):
        resolve_mood(moods, "ti")
    with pytest.raises(CredentialError):
        resolve_mood(moods, "c")


def test_editorjs_text_and_relationship():
    from pluralspace.cli import _field_value, _format_relationship

    doc = (
        '{"blocks":[{"type":"header","data":{"text":"gender"}},'
        '{"type":"list","data":{"style":"unordered","items":[{"content":"<b>pan:</b> a&amp;b","items":[]}]}},'
        '{"type":"delimiter","data":{}}]}'
    )
    assert _field_value(doc) == "gender\n- pan: a&b\n---"
    assert _field_value('{"blocks":[{"type":"delimiter","data":{}}]}') == ""
    assert _field_value("plain") == "plain"
    r = {
        "label": "Sibling",
        "notes": None,
        "cross_system": False,
        "other_member": {"display_label": "Chara"},
    }
    assert _format_relationship(r) == "Sibling: Chara"


FUZZY_MEMBERS = [
    {
        "id": "aaaaaaaa-0000-0000-0000-000000000001",
        "name": "Amanda",
        "display_name": "⊹˚₊ Amanda ₊˚⊹",
        "display_label": "⊹˚₊ Amanda  ₊˚⊹",
    },
    {
        "id": "aaaaaaaa-0000-0000-0000-000000000002",
        "name": "Alex",
        "display_name": "Alex",
        "display_label": "Alex",
    },
    {"id": "aaaaaaaa-0000-0000-0000-000000000003", "display_label": "Custom Front"},
]


def test_match_member_exact_by_plain_name_display_name_or_id():
    from pluralspace.cli import match_member_exact

    ids = lambda ref: [m["id"][-1] for m in match_member_exact(FUZZY_MEMBERS, ref)]
    assert ids("Amanda") == ["1"]
    assert ids("⊹˚₊ Amanda ₊˚⊹") == ["1"]
    assert ids("custom front") == ["3"]
    assert ids("000000000002") == ["2"]  # id suffix
    assert ids("aaaaaaaa-0000-0000-0000-000000000002") == ["2"]


def test_match_member_exact_rejects_partial_and_empty():
    from pluralspace.cli import match_member_exact

    for ref in ("Al", "Char", "lex", "", "  "):
        assert match_member_exact(FUZZY_MEMBERS, ref) == []


def _cur(mid, tid, label="X"):
    return {
        "member_id": mid,
        "system_front_type_id": tid,
        "started_at": "2026-11-03T03:04:19+00:00",
        "member": {"display_label": label},
        "front_type": {"name": tid},
    }


def test_plan_fronts_classifies_changes():
    from pluralspace.cli import plan_fronts

    current = [_cur("a", "t1"), _cur("b", "t1"), _cur("c", "t1")]
    plan = plan_fronts(current, {"a": "t1", "b": "t2", "d": "t1"})
    assert plan.keep == ["a"]
    assert plan.retype == ["b"]
    assert plan.start == ["d"]
    assert plan.end == ["c"]


def test_format_front_plan_names_and_end_all():
    from pluralspace.cli import format_front_plan, plan_fronts

    current = [_cur("a", "t1", "Alex")]
    lines = format_front_plan(plan_fronts(current, {}), {}, {"t1": "Front"})
    assert any("end" in ln and "Alex" in ln for ln in lines)
    empty = format_front_plan(plan_fronts([], {}), {}, {})
    assert "nobody fronting" in empty[-1]


def test_confirm_replace_non_tty_errors():
    import io

    import pytest

    from pluralspace.cli import confirm_replace
    from pluralspace.credentials import CredentialError

    with pytest.raises(CredentialError, match="--replace"):
        confirm_replace(["Ada"], stdin=io.StringIO("y\n"), stdout=io.StringIO())


def test_confirm_replace_prompt():
    import io

    import pytest

    from pluralspace.cli import confirm_replace
    from pluralspace.credentials import CredentialError

    class TTY(io.StringIO):
        def isatty(self):
            return True

    confirm_replace(["Ada"], stdin=TTY("y\n"), stdout=io.StringIO())
    with pytest.raises(CredentialError, match="aborted"):
        confirm_replace(["Ada"], stdin=TTY("\n"), stdout=io.StringIO())
