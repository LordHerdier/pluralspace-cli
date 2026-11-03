from pluralspace.api_client import dedupe_fronts


def _front(id_, started):
    return {"id": id_, "started_at": started}


def test_dedupe_keeps_each_front_once_newest_first():
    weeks = [[
        {"fronts": [_front("a", "2026-09-08T00:00:00+00:00")]},
        {"fronts": [_front("a", "2026-09-08T00:00:00+00:00"), _front("b", "2026-10-01T00:00:00+00:00")]},
    ]]
    assert [f["id"] for f in dedupe_fronts(weeks)] == ["b", "a"]


def test_resolve_front_type_by_name_or_slug():
    from pluralspace.cli import resolve_front_type
    types = [{"id": "1", "name": "Co-Front", "slug": "co_front"}, {"id": "2", "name": "Front", "slug": "front"}]
    assert resolve_front_type(types, "front")["id"] == "2"
    assert resolve_front_type(types, "co_front")["id"] == "1"


def test_resolve_mood_exact_then_prefix():
    import pytest
    from pluralspace.cli import resolve_mood
    from pluralspace.credentials import CredentialError
    moods = [{"id": "1", "name": "Calm"}, {"id": "2", "name": "Content"}, {"id": "3", "name": "Tired"}]
    assert resolve_mood(moods, "calm")["id"] == "1"
    assert resolve_mood(moods, "ti")["id"] == "3"
    with pytest.raises(CredentialError):
        resolve_mood(moods, "c")


def test_editorjs_text_and_relationship():
    from pluralspace.cli import _field_value, _format_relationship
    doc = ('{"blocks":[{"type":"header","data":{"text":"gender"}},'
           '{"type":"list","data":{"style":"unordered","items":[{"content":"<b>pan:</b> a&amp;b","items":[]}]}},'
           '{"type":"delimiter","data":{}}]}')
    assert _field_value(doc) == "gender\n- pan: a&b\n---"
    assert _field_value('{"blocks":[{"type":"delimiter","data":{}}]}') == ""
    assert _field_value("plain") == "plain"
    r = {"label": "Sibling", "notes": None, "cross_system": False,
         "other_member": {"display_label": "Chara"}}
    assert _format_relationship(r) == "Sibling: Chara"
