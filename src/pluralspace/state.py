"""The saved pre-write state that `plsp undo` restores.

One file per profile, `$XDG_STATE_HOME/pluralspace/<profile>.last-state.json`,
holding only the most recent write:

    {"version": 1, "kind": "fronts" | "mood", "command": "switch",
     "taken_at": "<iso>", "before": ..., "after": ... | null}

For `fronts`, before/after are lists of front rows (see fronts.row_from_*);
for `mood`, a {"id", "label"} dict (both null when no mood is set). `after`
is null until the write has been confirmed.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import UsageError

SNAPSHOT_VERSION = 1
KINDS = ("fronts", "mood")
_ROW_KEYS = ("id", "member_id", "type_id", "started_at")


class StateError(UsageError):
    """The saved state is unreadable or can't be written. Never guessed around."""


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(base) / "pluralspace"


def snapshot_path(profile: str) -> Path:
    return state_dir() / f"{profile}.last-state.json"


def build_snapshot(
    kind: str, command: str, before: Any, after: Any = None, now: Optional[str] = None
) -> Dict[str, Any]:
    snap = {
        "version": SNAPSHOT_VERSION,
        "kind": kind,
        "command": command,
        "taken_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "before": before,
        "after": after,
    }
    return validate_snapshot(snap)


def _check_state(kind: str, value: Any, field: str) -> None:
    if kind == "fronts":
        if not isinstance(value, list):
            raise StateError(f"saved state: {field} must be a list of fronts")
        for row in value:
            if not isinstance(row, dict) or not all(
                isinstance(row.get(k), str) and row[k] for k in _ROW_KEYS
            ):
                raise StateError(f"saved state: malformed front in {field}")
    else:
        if not isinstance(value, dict) or set(value) != {"id", "label"}:
            raise StateError(f"saved state: malformed mood in {field}")


def validate_snapshot(data: Any) -> Dict[str, Any]:
    """Return data if it is a snapshot we understand; raise StateError if not."""
    if not isinstance(data, dict):
        raise StateError("saved state is not a JSON object")
    if data.get("version") != SNAPSHOT_VERSION:
        raise StateError(
            f"saved state has version {data.get('version')!r}; "
            f"this plsp reads version {SNAPSHOT_VERSION}"
        )
    kind = data.get("kind")
    if kind not in KINDS:
        raise StateError(f"saved state has unknown kind {kind!r}")
    for key in ("command", "taken_at"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise StateError(f"saved state is missing {key!r}")
    _check_state(kind, data.get("before"), "before")
    if data.get("after") is not None:
        _check_state(kind, data["after"], "after")
    return data


def save_snapshot(profile: str, snap: Dict[str, Any]) -> Path:
    """Write atomically with 0600 from the start: the file names members."""
    validate_snapshot(snap)
    path = snapshot_path(profile)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(snap, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise StateError(
            f"can't save undo state to {path}: {e.strerror or e}"
        ) from None
    return path


def load_snapshot(profile: str) -> Optional[Dict[str, Any]]:
    """The saved snapshot, or None if there isn't one."""
    path = snapshot_path(profile)
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise StateError(f"can't read {path}: {e.strerror or e}") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise StateError(f"{path} is corrupt (not valid JSON)") from None
    return validate_snapshot(data)


def update_after(profile: str, after: Any) -> Dict[str, Any]:
    """Record the confirmed state after the saved write."""
    snap = load_snapshot(profile)
    if snap is None:
        raise StateError("no saved state to update")
    snap["after"] = after
    save_snapshot(profile, snap)
    return snap


def clear_snapshot(profile: str) -> None:
    """Forget the saved state, e.g. when an undo removed what it described."""
    try:
        snapshot_path(profile).unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        raise StateError(f"can't remove saved undo state: {e.strerror or e}") from None
