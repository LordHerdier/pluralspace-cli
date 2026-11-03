#!/usr/bin/env python3
"""
Pluralspace CLI

Usage:
    pluralspace login [--email EMAIL]   Log in (uses the pass entry, offers to create it)
    pluralspace logout                  Drop the local session
    pluralspace whoami                  Show the logged-in account

Credentials live in pass at pluralspace/<profile>:
    <password>
    email: you@example.com
"""

import argparse
import getpass
import sys
from typing import Callable, TypeVar

from . import __version__
from .api_client import APIError, AuthError, PluralspaceAPI
from .credentials import CredentialError, Credentials, PassStore

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


def cmd_login(args, api: PluralspaceAPI, store: PassStore) -> int:
    if store.exists() and not args.email:
        creds = store.load()
    else:
        email = args.email or input("Email: ").strip()
        password = getpass.getpass("Password: ")
        creds = Credentials(email, password)
    api.login(creds.email, creds.password)
    user = api.whoami()
    print(f"Logged in as {user.get('name')} ({user.get('email')})")
    if not store.exists() or args.email:
        if input(f"Save credentials to pass ({store.entry})? [Y/n] ").strip().lower() in ("", "y", "yes"):
            store.save(creds)
            print(f"Saved to pass: {store.entry}")
    return 0


def cmd_logout(args, api: PluralspaceAPI, store: PassStore) -> int:
    api.logout()
    print("Session cleared (pass entry left in place)")
    return 0


def cmd_whoami(args, api: PluralspaceAPI, store: PassStore) -> int:
    user = _authed(api, store, api.whoami)
    print(f"{user.get('name')} <{user.get('email')}> [{user.get('id')}]")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pluralspace", description="Pluralspace CLI")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="log in and optionally store credentials in pass")
    p.add_argument("--email")
    p.set_defaults(func=cmd_login)
    sub.add_parser("logout", help="drop the local session").set_defaults(func=cmd_logout)
    sub.add_parser("whoami", help="show the logged-in account").set_defaults(func=cmd_whoami)

    args = parser.parse_args(argv)
    api = PluralspaceAPI(args.profile, debug=args.debug)
    store = PassStore(args.profile)
    try:
        return args.func(args, api, store)
    except (AuthError, CredentialError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except APIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        return 130


if __name__ == "__main__":
    sys.exit(main())
