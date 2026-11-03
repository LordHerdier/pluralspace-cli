import pytest

from pluralspace.credentials import CredentialError, PassStore


def test_parse_password_and_email():
    c = PassStore.parse("hunter2\nemail: a@b.c\nnotes: x\n")
    assert (c.email, c.password) == ("a@b.c", "hunter2")


def test_parse_accepts_user_key():
    assert PassStore.parse("pw\nuser: a@b.c").email == "a@b.c"


def test_parse_requires_email():
    with pytest.raises(CredentialError):
        PassStore.parse("pw\n")


def test_entry_name():
    assert PassStore("alt").entry == "pluralspace/alt"
