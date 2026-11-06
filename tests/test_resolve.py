import pytest

from pluralspace.errors import UsageError
from pluralspace.resolve import resolve_front_type, resolve_member, resolve_mood


class FakeAPI:
    def __init__(self, search=(), members=()):
        self._search, self._members = list(search), list(members)

    def search_members(self, ref):
        return self._search

    def members(self, *a, **kw):
        return self._members


def M(suffix, name=None, label=None):
    m = {"id": f"00000000-0000-0000-0000-{suffix:>012}", "display_label": label or name}
    if name:
        m["name"] = name
    return m


def test_fuzzy_lone_search_hit_is_accepted_for_reads():
    api = FakeAPI(search=[M("1", "Alexandra")])
    assert resolve_member(api, "alex")["name"] == "Alexandra"


def test_fuzzy_ambiguous_search_is_rejected():
    api = FakeAPI(search=[M("1", "Alexandra"), M("2", "Alexei")])
    with pytest.raises(UsageError, match="no member matches"):
        resolve_member(api, "alex")


def test_exact_hit_wins_over_other_fuzzy_hits():
    api = FakeAPI(search=[M("1", "Alex"), M("2", "Alexei")])
    assert resolve_member(api, "alex")["id"].endswith("1")


def test_id_suffix_falls_back_to_members_listing():
    api = FakeAPI(search=[], members=[M("123456789", "Zed")])
    assert resolve_member(api, "123456789")["name"] == "Zed"


def test_writes_require_exact_match_and_suggest_near_misses():
    api = FakeAPI(search=[M("1", "Alexandra")], members=[M("1", "Alexandra")])
    with pytest.raises(UsageError, match="did you mean: .*Alexandra"):
        resolve_member(api, "alex", exact=True)
    assert resolve_member(api, "ALEXANDRA", exact=True)["id"].endswith("1")


def test_writes_merge_custom_fronts_from_search_with_plain_names_from_members():
    custom = M("3", label="Custom Front")  # only visible in search
    plain = M("1", "Amanda", label="~ Amanda ~")  # real name only in /members
    api = FakeAPI(search=[custom, {**plain, "name": None}], members=[plain])
    assert resolve_member(api, "custom front", exact=True)["id"].endswith("3")
    assert resolve_member(api, "Amanda", exact=True)["id"].endswith("1")


def test_exact_ambiguity_lists_candidates():
    twins = [M("1", "Sam"), M("2", "sam")]
    api = FakeAPI(search=twins, members=twins)
    with pytest.raises(UsageError, match="ambiguous"):
        resolve_member(api, "sam", exact=True)


def test_front_type_errors_list_available_and_flag_ambiguity():
    types = [
        {"id": "1", "name": "Front", "slug": "front"},
        {"id": "2", "name": "front", "slug": "x"},
    ]
    with pytest.raises(UsageError, match="ambiguous"):
        resolve_front_type(types, "front")
    with pytest.raises(UsageError, match="available: Front, front"):
        resolve_front_type(types, "nope")


def test_mood_errors_are_usage_errors_listing_options():
    moods = [{"id": "1", "name": "Calm"}]
    with pytest.raises(UsageError, match="available: Calm"):
        resolve_mood(moods, "cal")
    assert resolve_mood(moods, "  CALM ")["id"] == "1"
