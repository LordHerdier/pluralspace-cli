"""Timestamp conversion for the front-edit endpoint.

Pluralspace sends timestamps as ISO 8601 with an offset, but its front edit
form posts them back as *naive* local times in the viewer's timezone. Getting
that conversion wrong would silently shift real fronting history, so anything
we can't convert exactly raises ValueError instead of guessing.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NAIVE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def parse_iso(ts: str) -> datetime:
    """Parse an API timestamp into an aware datetime (naive is taken as UTC)."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def zone(name: str):
    """tzinfo for an IANA name. UTC never needs the tz database."""
    if name in ("UTC", "Etc/UTC"):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        raise ValueError(f"unknown timezone {name!r}") from None


def to_viewer_naive(ts: str, tz_name: str) -> str:
    """The naive local time in `tz_name` that the front edit form expects.

    Raises ValueError if the result would not map back to exactly the same
    instant: fractional seconds, or a local time that is ambiguous because
    the clocks went back. Only the *first* occurrence of a repeated hour is
    written: verified against the live site (America/Chicago, 01:30 on
    2026-11-01 was stored as 06:30Z, i.e. CDT), so the second is refused.
    """
    original = parse_iso(ts)
    tz = zone(tz_name)
    naive = original.astimezone(tz).strftime(NAIVE_FORMAT)
    back = datetime.strptime(naive, NAIVE_FORMAT).replace(tzinfo=tz, fold=0)
    if back.astimezone(timezone.utc) != original.astimezone(timezone.utc):
        raise ValueError(f"{ts} cannot be written unambiguously in {tz_name}")
    return naive


def month_of(ts: str, tz_name: str) -> str:
    """YYYY-MM of an API timestamp as the viewer's calendar shows it."""
    return parse_iso(ts).astimezone(zone(tz_name)).strftime("%Y-%m")
