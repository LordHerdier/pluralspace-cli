"""Argument parsing and top-level error handling for `plsp`."""

import argparse
import os
import sys

from .. import __version__
from ..api_client import APIError, AuthError, PluralspaceAPI
from ..credentials import CredentialError, PassStore
from ..errors import UsageError
from .commands import auth, fronts, members, mood, undo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plsp", description="Pluralspace CLI")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--read-only",
        action="store_true",
        default=os.environ.get("PLSP_READ_ONLY") == "1",
        help="refuse all writes (also set by PLSP_READ_ONLY=1)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for module in (auth, members, fronts, mood, undo):
        module.register(sub)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    api = PluralspaceAPI(
        args.profile,
        debug=args.debug,
        read_only=args.read_only,
    )
    store = PassStore(args.profile)
    try:
        return args.func(args, api, store)
    except (AuthError, CredentialError, UsageError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except APIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        return 130
