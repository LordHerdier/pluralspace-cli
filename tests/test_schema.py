import json
import re

import pytest

from pluralspace import schema
from pluralspace.api_client import PluralspaceAPI, ResponseShapeError

FRONT = {
    "id": "f1",
    "member_id": "m1",
    "system_front_type_id": "t1",
    "started_at": "2026-11-06T19:52:44+00:00",
    "member": {"display_label": "Ada"},
}


def test_current_fronts_accepts_a_good_payload_and_extra_fields():
    assert schema.check_current_fronts([{**FRONT, "new_field": 1}])
    assert schema.check_current_fronts([]) == []


@pytest.mark.parametrize(
    "value, problem",
    [
        (None, "currentFronts: expected a list"),
        ([{**FRONT, "member_id": None}], "currentFronts[0].member_id: expected str"),
        (
            [{k: v for k, v in FRONT.items() if k != "id"}],
            "currentFronts[0].id: missing",
        ),
        ([{**FRONT, "started_at": ""}], "currentFronts[0].started_at: empty"),
        (["x"], "currentFronts[0]: expected an object"),
    ],
)
def test_current_fronts_names_the_first_problem(value, problem):
    with pytest.raises(schema.ShapeError, match=re.escape(problem)):
        schema.check_current_fronts(value)


def test_atmosphere_requires_the_mood_key_but_allows_null():
    assert schema.check_atmosphere({"mood": None, "mood_label": None})
    with pytest.raises(schema.ShapeError, match="atmosphere.mood: missing"):
        schema.check_atmosphere({"mood_label": "Calm"})
    with pytest.raises(schema.ShapeError, match="mood_label"):
        schema.check_atmosphere({"mood": "x", "mood_label": 3})


def test_fronts_page_checks_nested_calendar_rows():
    day = {"fronts": [{"id": "r1", "started_at": "2026-11-01T00:00:00+00:00"}]}
    assert schema.check_fronts_page({"weeks": [[day]]})
    with pytest.raises(schema.ShapeError, match=r"props.weeks\[0\]\[0\].fronts"):
        schema.check_fronts_page({"weeks": [[{}]]})
    with pytest.raises(schema.ShapeError, match="props.weeks: missing"):
        schema.check_fronts_page({})


def test_members_page_needs_pagination_meta():
    ok = {
        "members": {
            "data": [{"id": "m1", "display_label": "Ada"}],
            "meta": {"last_page": 1},
        }
    }
    assert schema.check_members_page(ok)
    ok["members"]["meta"] = {}
    with pytest.raises(schema.ShapeError, match="members.meta.last_page: missing"):
        schema.check_members_page(ok)


def test_moods_and_front_types_and_search():
    assert schema.check_moods({"data": [{"id": "a", "name": "Calm"}]})
    with pytest.raises(schema.ShapeError, match=r"data\[0\].name"):
        schema.check_moods({"data": [{"id": "a"}]})
    with pytest.raises(schema.ShapeError, match="frontTypes"):
        schema.check_front_types({})
    with pytest.raises(schema.ShapeError, match="search results"):
        schema.check_member_search({"data": []})


def test_deferred_props_must_name_a_component():
    with pytest.raises(schema.ShapeError, match="component: missing"):
        schema.check_deferred({"deferredProps": {"d": ["members"]}})
    assert schema.check_deferred({"props": {}})


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    client = PluralspaceAPI("test")
    monkeypatch.setattr(client, "has_session", lambda: True)
    client.version = "v1"
    monkeypatch.setattr(client, "_save_jar", lambda: None)
    return client


def _serve(api, monkeypatch, payload):
    monkeypatch.setattr(
        api, "_request", lambda *a, **kw: (200, {}, json.dumps(payload))
    )


def test_changed_payload_raises_one_clear_error_not_a_keyerror(api, monkeypatch):
    _serve(api, monkeypatch, {"props": {"currentFronts": [{"id": "f1"}]}})
    with pytest.raises(ResponseShapeError) as e:
        api.current_fronts()
    msg = str(e.value)
    assert msg.startswith("Pluralspace's response changed. Please update plsp")
    assert "currentFronts[0].member_id: missing" in msg


def test_non_object_page_is_a_shape_error(api, monkeypatch):
    _serve(api, monkeypatch, ["nope"])
    with pytest.raises(ResponseShapeError):
        api.current_fronts()


def test_good_payload_passes_through(api, monkeypatch):
    _serve(api, monkeypatch, {"props": {"currentFronts": [FRONT]}})
    assert api.current_fronts() == [FRONT]
