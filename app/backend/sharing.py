"""
External-share helpers — tokens, validity, and guest permissions.

Pure logic behind ProjectShare (external collaboration): mint an unguessable
share token, decide whether a share still grants access (not revoked, not
expired), and what a guest role may do. Unit-tested; the DB I/O lives in
routes/sharing_routes.py.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

VALID_ROLES = ("viewer", "commenter")


def new_share_token() -> str:
    """A URL-safe, unguessable share token (256 bits)."""
    return secrets.token_urlsafe(32)


def normalize_role(role: Optional[str]) -> str:
    """Coerce to a valid role; default to the least-privileged 'viewer'."""
    r = (role or "viewer").strip().lower()
    return r if r in VALID_ROLES else "viewer"


def share_is_valid(*, revoked: bool, expires_at: Optional[datetime],
                   now: Optional[datetime] = None) -> bool:
    """A share grants access iff it isn't revoked and hasn't expired."""
    if revoked:
        return False
    if expires_at is not None:
        t = now or datetime.now(timezone.utc)
        # Compare tz-aware; treat a naive expires_at as UTC.
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        if exp <= t:
            return False
    return True


def can_comment(role: str) -> bool:
    """Only the 'commenter' role may post comments; 'viewer' is read-only."""
    return normalize_role(role) == "commenter"
