"""Tests for external-share token / validity / permission logic (pure)."""

from datetime import datetime, timedelta, timezone

from sharing import can_comment, new_share_token, normalize_role, share_is_valid


def test_tokens_unique_and_urlsafe():
    toks = {new_share_token() for _ in range(200)}
    assert len(toks) == 200
    assert all("/" not in t and "+" not in t and len(t) >= 32 for t in toks)


def test_normalize_role():
    assert normalize_role("commenter") == "commenter"
    assert normalize_role("VIEWER") == "viewer"
    assert normalize_role("admin") == "viewer"     # unknown -> least privilege
    assert normalize_role(None) == "viewer"


def test_can_comment():
    assert can_comment("commenter") is True
    assert can_comment("viewer") is False
    assert can_comment("bogus") is False            # normalized to viewer


def test_share_valid_when_not_revoked_and_no_expiry():
    assert share_is_valid(revoked=False, expires_at=None) is True


def test_revoked_share_invalid():
    assert share_is_valid(revoked=True, expires_at=None) is False


def test_expired_share_invalid():
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    past = now - timedelta(hours=1)
    future = now + timedelta(hours=1)
    assert share_is_valid(revoked=False, expires_at=past, now=now) is False
    assert share_is_valid(revoked=False, expires_at=future, now=now) is True


def test_naive_expiry_treated_as_utc():
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    naive_past = datetime(2026, 7, 23, 11, 0)       # no tzinfo
    assert share_is_valid(revoked=False, expires_at=naive_past, now=now) is False
