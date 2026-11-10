"""Helpers shared by the command modules."""

import json
import sys
from typing import Any, Callable, TypeVar

from ..api_client import AuthError, PluralspaceAPI
from ..credentials import PassStore
from ..errors import UsageError
from ..state import StateError, build_snapshot, save_snapshot, update_after

T = TypeVar("T")


def _authed(api: PluralspaceAPI, store: PassStore, fn: Callable[[], T]) -> T:
    """Run fn; on an expired session, re-login from pass and retry once."""
    try:
        return fn()
    except AuthError:
        if not store.exists():
            raise
        creds = store.load()
        api.login(creds.email, creds.password)
        return fn()


def _emit_json(data) -> int:
    """Print data as JSON; returns the exit status (0) for `return _emit_json(...)`."""
    print(json.dumps(data, indent=2))
    return 0


def add_json(p) -> None:
    p.add_argument("--json", action="store_true")


def add_dry_run(p) -> None:
    p.add_argument(
        "--dry-run", action="store_true", help="show what would change, change nothing"
    )


def snapshot_before(args, kind: str, command: str, before: Any) -> None:
    """Save what is about to be overwritten, so `plsp undo` can restore it.

    Called immediately before a write. If the snapshot can't be saved this
    raises, and the write must not go ahead. Read-only mode refuses here too,
    so a refused write can't replace the saved state.
    """
    if getattr(args, "read_only", False):
        raise UsageError(f"read-only mode: refusing to {command}")
    save_snapshot(args.profile, build_snapshot(kind, command, before))


def snapshot_after(args, after: Any) -> None:
    """Record the confirmed result. The write has already happened, so a
    failure here only warns: undo then can't detect later changes."""
    try:
        update_after(args.profile, after)
    except StateError as e:
        print(f"warning: {e}", file=sys.stderr)
