"""Argument parsing and top-level error handling for `plsp`."""

import argparse
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
    sub = parser.add_subparsers(dest="command", required=True)
    for module in (auth, members, fronts, mood, undo):
        module.register(sub)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    api = PluralspaceAPI(args.profile, debug=args.debug)
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
