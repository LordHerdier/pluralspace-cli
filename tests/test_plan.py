from pluralspace.fronts import (
    DRY_RUN_HEADER,
    FrontPlan,
    format_front_plan,
    plan_fronts,
    replaced_names,
)


def _cur(mid, tid, label="X", type_name="Front"):
    return {
        "member_id": mid,
        "system_front_type_id": tid,
        "started_at": "2026-11-03T03:04:19+00:00",
        "member": {"display_label": label},
        "front_type": {"name": type_name},
    }


def test_plan_is_a_dataclass_with_target_and_current():
    plan = plan_fronts([_cur("a", "t1")], {"a": "t1", "b": "t2"})
    assert isinstance(plan, FrontPlan)
    assert plan.target == {"a": "t1", "b": "t2"}
    assert set(plan.current) == {"a"}


def test_plan_truthiness_means_something_is_fronting_before_or_after():
    assert not plan_fronts([], {})
    assert plan_fronts([_cur("a", "t1")], {})
    assert plan_fronts([], {"a": "t1"})


def test_replaced_names_lists_only_those_that_would_end():
    current = [_cur("a", "t1", "Ada"), _cur("b", "t1", "Bo")]
    assert replaced_names(plan_fronts(current, {"a": "t1"})) == ["Bo"]
    assert replaced_names(plan_fronts(current, {"a": "t1", "b": "t1"})) == []


def test_replaced_names_falls_back_to_hidden():
    current = [{**_cur("a", "t1"), "member": None}]
    assert replaced_names(plan_fronts(current, {})) == ["(hidden)"]


def test_format_front_plan_covers_every_kind_of_change():
    current = [
        _cur("keep", "t1", "Kay"),
        _cur("re", "t1", "Rae"),
        _cur("gone", "t1", "Gus"),
    ]
    plan = plan_fronts(current, {"keep": "t1", "re": "t2", "new": "t1"})
    lines = format_front_plan(
        plan,
        {"new": "Nia"},
        {"t1": "Front", "t2": "Co-Front"},
        comment="hello",
        silent=True,
    )
    assert lines[0] == DRY_RUN_HEADER
    text = "\n".join(lines)
    assert "+ start  Nia  [Front]" in text
    assert "~ retype Rae  [Front -> Co-Front]" in text
    assert "= keep   Kay  [Front]  since " in text
    assert "- end    Gus  [Front]" in text
    assert "comment: hello" in text
    assert "silent: no notifications" in text


def test_format_front_plan_nobody_before_or_after():
    lines = format_front_plan(plan_fronts([], {}), {}, {})
    assert lines == [DRY_RUN_HEADER, "  (nobody fronting before or after)"]


def test_format_front_plan_prefers_current_label_over_argument_label():
    plan = plan_fronts([_cur("a", "t1", "Shown")], {"a": "t1"})
    lines = format_front_plan(plan, {"a": "Typed"}, {"t1": "Front"})
    assert any("Shown" in ln for ln in lines)
    assert not any("Typed" in ln for ln in lines)
