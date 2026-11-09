"""Shape checks for the parts of Pluralspace's responses that plsp relies on.

Each `check_*` function takes a decoded payload, returns it unchanged if every
field the commands read is present with a usable type, and otherwise raises
`ShapeError` naming the first thing that's wrong (e.g. `currentFronts[0]
.member_id: missing`). The API client turns that into one clear error, so a
changed site fails before any write rather than as a KeyError halfway through.

Only fields we actually read are required; extras are ignored. Optional fields
are checked for type only when present.
"""

from typing import Any, Callable, Dict


class ShapeError(ValueError):
    """A response doesn't look the way plsp expects. Message is `path: problem`."""


_MISSING = object()


def _where(path: str, key: Any) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else str(key)


def _obj(value: Any, path: str) -> Dict[str, Any]:
    if value is _MISSING:
        raise ShapeError(f"{path}: missing")
    if not isinstance(value, dict):
        raise ShapeError(f"{path or 'response'}: expected an object")
    return value


def _list(value: Any, path: str) -> list:
    if value is _MISSING:
        raise ShapeError(f"{path}: missing")
    if not isinstance(value, list):
        raise ShapeError(f"{path}: expected a list")
    return value


def _field(obj: Dict[str, Any], key: str, kind: type, path: str, nonempty=True) -> Any:
    value = obj.get(key, _MISSING)
    here = _where(path, key)
    if value is _MISSING:
        raise ShapeError(f"{here}: missing")
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
        raise ShapeError(f"{here}: expected {kind.__name__}")
    if nonempty and kind is str and not value:
        raise ShapeError(f"{here}: empty")
    return value


def _optional(obj: Dict[str, Any], key: str, kind: type, path: str) -> None:
    value = obj.get(key)
    if value is not None and not isinstance(value, kind):
        raise ShapeError(f"{_where(path, key)}: expected {kind.__name__} or null")


def _each(value: Any, path: str, item: Callable[[Any, str], None]) -> list:
    items = _list(value, path)
    for i, entry in enumerate(items):
        item(entry, _where(path, i))
    return items


# -- pages ---------------------------------------------------------------


def check_page(payload: Any) -> Dict[str, Any]:
    """The Inertia envelope: an object with a `props` object."""
    page = _obj(payload, "")
    _obj(page.get("props", _MISSING), "props")
    return page


def check_deferred(page: Dict[str, Any]) -> Dict[str, Any]:
    """If a page defers props, it must say which, and name its component."""
    deferred = page.get("deferredProps")
    if deferred is None:
        return page
    for group, names in _obj(deferred, "deferredProps").items():
        _each(names, f"deferredProps.{group}", lambda n, p: _str(n, p))
    if any(deferred.values()):
        _field(page, "component", str, "")
    return page


def _str(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value:
        raise ShapeError(f"{path}: expected a non-empty string")


# -- fronts --------------------------------------------------------------


def _current_front(front: Any, path: str) -> None:
    front = _obj(front, path)
    for key in ("id", "member_id", "system_front_type_id", "started_at"):
        _field(front, key, str, path)
    for key in ("member", "front_type"):
        _optional(front, key, dict, path)


def check_current_fronts(value: Any) -> list:
    return _each(value, "currentFronts", _current_front)


def _calendar_front(front: Any, path: str) -> None:
    front = _obj(front, path)
    _field(front, "id", str, path)
    _field(front, "started_at", str, path)
    _optional(front, "ended_at", str, path)
    for key in ("member", "front_type"):
        _optional(front, key, dict, path)


def _calendar_day(day: Any, path: str) -> None:
    _each(_obj(day, path).get("fronts", _MISSING), f"{path}.fronts", _calendar_front)


def check_fronts_page(props: Any) -> Dict[str, Any]:
    props = _obj(props, "props")
    weeks = _list(props.get("weeks", _MISSING), "props.weeks")
    for i, week in enumerate(weeks):
        _each(week, f"props.weeks[{i}]", _calendar_day)
    _optional(props, "viewerTimezone", str, "props")
    _optional(props, "permissions", dict, "props")
    _optional(props, "month", dict, "props")
    return props


def check_front_types(props: Any) -> Dict[str, Any]:
    props = _obj(props, "props")

    def front_type(t: Any, path: str) -> None:
        t = _obj(t, path)
        _field(t, "id", str, path)
        _field(t, "name", str, path)

    _each(props.get("frontTypes", _MISSING), "frontTypes", front_type)
    if props.get("subsystemFrontTypes") is not None:
        _each(props["subsystemFrontTypes"], "subsystemFrontTypes", front_type)
    return props


# -- members -------------------------------------------------------------


def _member(m: Any, path: str) -> None:
    m = _obj(m, path)
    _field(m, "id", str, path)
    _field(m, "display_label", str, path, nonempty=False)


def check_members_page(props: Any) -> Dict[str, Any]:
    members = _obj(_obj(props, "props").get("members", _MISSING), "members")
    _each(members.get("data", _MISSING), "members.data", _member)
    meta = _obj(members.get("meta", _MISSING), "members.meta")
    _field(meta, "last_page", int, "members.meta")
    return members


def check_member_search(value: Any) -> list:
    def hit(m: Any, path: str) -> None:
        _field(_obj(m, path), "id", str, path)

    return _each(value, "search results", hit)


def check_member_props(props: Any) -> Dict[str, Any]:
    props = _obj(props, "props")
    _member(props.get("member", _MISSING), "props.member")
    return props


# -- moods ---------------------------------------------------------------


def check_moods(value: Any) -> list:
    def mood(m: Any, path: str) -> None:
        m = _obj(m, path)
        _field(m, "id", str, path)
        _field(m, "name", str, path)

    return _each(_obj(value, "").get("data", _MISSING), "data", mood)


def check_atmosphere(value: Any) -> Dict[str, Any]:
    atmosphere = _obj(value, "atmosphere")
    if "mood" not in atmosphere:
        # Absent is not the same as "no mood set"; a verify must not guess.
        raise ShapeError("atmosphere.mood: missing")
    _optional(atmosphere, "mood", str, "atmosphere")
    _optional(atmosphere, "mood_label", str, "atmosphere")
    return atmosphere
