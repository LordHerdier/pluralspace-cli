"""Errors raised for bad user input, as opposed to bad credentials."""

from .credentials import CredentialError


class UsageError(CredentialError):
    """The request can't be carried out as given (unknown member, ambiguous
    name, declined confirmation, ...). Subclasses CredentialError so existing
    handlers keep working; both exit with status 1."""
