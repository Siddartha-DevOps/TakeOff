"""Regression test for the passlib + bcrypt password-hashing incompatibility.

passlib 1.7.4 with bcrypt>=4.1 raises "password cannot be longer than 72 bytes"
from its backend self-test, which 500s every signup and login. This asserts the
exact CryptContext auth.py uses can hash + verify — so a future dependency bump
that reintroduces the break fails CI instead of production login.
"""

import pytest

pytest.importorskip("passlib.context")
pytest.importorskip("bcrypt")


def _ctx():
    from passlib.context import CryptContext

    # Must mirror auth.py exactly.
    return CryptContext(schemes=["bcrypt"], deprecated="auto")


def test_hash_and_verify_roundtrip():
    ctx = _ctx()
    hashed = ctx.hash("demo1234")
    assert hashed and hashed != "demo1234"
    assert ctx.verify("demo1234", hashed) is True
    assert ctx.verify("wrong-password", hashed) is False


def test_long_password_does_not_crash():
    # bcrypt truncates at 72 bytes; it must not raise (the failure mode we hit).
    ctx = _ctx()
    hashed = ctx.hash("x" * 200)
    assert ctx.verify("x" * 200, hashed) is True
