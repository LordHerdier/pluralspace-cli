"""
Credential storage backed by pass(1), the standard unix password manager.

Entry layout (pass convention, first line is the secret):

    <password>
    email: you@example.com

Only the email/password live in pass. The session cookie jar is kept
separately by the API client, since it is short-lived and rotates constantly.
"""

import subprocess
from dataclasses import dataclass
from typing import Optional

DEFAULT_PREFIX = "pluralspace"


class CredentialError(Exception):
    pass


@dataclass
class Credentials:
    email: str
    password: str


class PassStore:
    def __init__(self, profile: str = "default", prefix: str = DEFAULT_PREFIX):
        self.entry = f"{prefix}/{profile}"

    def _run(self, args, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                ["pass", *args],
                input=stdin,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            raise CredentialError("`pass` not found in PATH") from None

    def exists(self) -> bool:
        # `pass ls <entry>` exits 0 for an existing entry or directory
        return self._run(["ls", self.entry]).returncode == 0

    def load(self) -> Credentials:
        # Output goes through capture_output, never a terminal, so the
        # secret isn't echoed. gpg-agent/pinentry still prompts as needed.
        result = self._run(["show", self.entry])
        if result.returncode != 0:
            raise CredentialError(
                f"could not read pass entry '{self.entry}': {result.stderr.strip()}"
            )
        return self.parse(result.stdout)

    @staticmethod
    def parse(text: str) -> Credentials:
        lines = text.splitlines()
        if not lines or not lines[0]:
            raise CredentialError("pass entry is empty")
        email = None
        for line in lines[1:]:
            key, sep, value = line.partition(":")
            if sep and key.strip().lower() in ("email", "user", "username", "login"):
                email = value.strip()
                break
        if not email:
            raise CredentialError("pass entry has no 'email: ...' line")
        return Credentials(email=email, password=lines[0])

    def save(self, creds: Credentials) -> None:
        # Secret goes over stdin, never argv (visible in `ps`).
        body = f"{creds.password}\nemail: {creds.email}\n"
        result = self._run(["insert", "--multiline", "--force", self.entry], stdin=body)
        if result.returncode != 0:
            raise CredentialError(f"pass insert failed: {result.stderr.strip()}")

    def remove(self) -> None:
        result = self._run(["rm", "--force", self.entry])
        if result.returncode != 0:
            raise CredentialError(f"pass rm failed: {result.stderr.strip()}")
