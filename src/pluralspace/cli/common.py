"""Helpers shared by the command modules."""

import json
from typing import Callable, TypeVar

from ..api_client import AuthError, PluralspaceAPI
from ..credentials import PassStore

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
