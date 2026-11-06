import pytest

from pluralspace.timeutil import month_of, parse_iso, to_viewer_naive, zone


def _needs_tzdata(name):
    try:
        zone(name)
    except ValueError:
        pytest.skip("tz database not available")


def test_utc_viewer_is_the_same_wall_clock_without_offset():
    assert to_viewer_naive("2026-11-06T19:52:44+00:00", "UTC") == "2026-11-06T19:52:44"
    assert to_viewer_naive("2026-11-06T19:52:44Z", "UTC") == "2026-11-06T19:52:44"


def test_utc_needs_no_tz_database():
    assert zone("UTC") is zone("Etc/UTC")


def test_offset_zone_converts_to_local_wall_clock():
    _needs_tzdata("America/New_York")
    assert (
        to_viewer_naive("2026-11-06T19:52:44+00:00", "America/New_York")
        == "2026-11-06T14:52:44"
    )
    assert (
        to_viewer_naive("2026-07-06T19:52:44+00:00", "America/New_York")
        == "2026-07-06T15:52:44"
    )


def test_ambiguous_local_time_after_clocks_go_back_is_refused():
    _needs_tzdata("America/New_York")
    # 2026-11-01 01:30 happens twice in New York: 05:30Z (EDT) and 06:30Z (EST).
    assert (
        to_viewer_naive("2026-11-01T05:30:00+00:00", "America/New_York")
        == "2026-11-01T01:30:00"
    )
    with pytest.raises(ValueError, match="unambiguously"):
        to_viewer_naive("2026-11-01T06:30:00+00:00", "America/New_York")


def test_fractional_seconds_are_refused_rather_than_truncated():
    with pytest.raises(ValueError):
        to_viewer_naive("2026-11-06T19:52:44.500000+00:00", "UTC")


def test_unknown_timezone_is_refused():
    with pytest.raises(ValueError, match="unknown timezone"):
        to_viewer_naive("2026-11-06T19:52:44+00:00", "Mars/Olympus")


def test_naive_input_is_taken_as_utc():
    assert parse_iso("2026-11-06T19:52:44").utcoffset().total_seconds() == 0


def test_month_of_uses_the_viewers_calendar():
    _needs_tzdata("Pacific/Auckland")
    assert month_of("2026-11-30T23:00:00+00:00", "UTC") == "2026-11"
    assert month_of("2026-11-30T23:00:00+00:00", "Pacific/Auckland") == "2026-12"
