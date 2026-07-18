"""
Rate limiting + job quotas (backend hardening #2).

Fixed-window limiter with an injectable store: Redis in production (multi-worker,
already a dependency), an in-process dict fallback for dev/CI. The decision logic
is pure and unit-tested with a fake clock; the FastAPI dependency
(``RateLimit``) enforces it per user/org (or client IP when unauthenticated).

Fail-open by design: if the store is unreachable, requests are allowed (a limiter
outage must not take the app down) — logged, not silent.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Stores
# --------------------------------------------------------------------------- #
class InMemoryStore:
    """Process-local fixed-window counter store (dev/CI/tests)."""

    def __init__(self):
        self._data: dict = {}   # key -> (count, expires_at)

    def incr(self, key: str, ttl: int, now: float) -> int:
        count, exp = self._data.get(key, (0, 0.0))
        if now >= exp:
            count, exp = 0, now + ttl
        count += 1
        self._data[key] = (count, exp)
        return count


class RedisStore:
    """Redis-backed store (lazy import). Atomic INCR + EXPIRE on first hit."""

    def __init__(self, url: str):
        import redis  # lazy
        self._r = redis.Redis.from_url(url)

    def incr(self, key: str, ttl: int, now: float) -> int:
        count = self._r.incr(key)
        if count == 1:
            self._r.expire(key, ttl)
        return int(count)


_store = None


def get_store():
    """Return the process's rate-limit store (Redis if REDIS_URL else in-memory)."""
    global _store
    if _store is None:
        url = os.environ.get("REDIS_URL")
        if url:
            try:
                _store = RedisStore(url)
            except Exception as exc:  # noqa: BLE001 — fall back, never crash
                logger.warning("rate limit: Redis unavailable (%s); using in-memory store", exc)
                _store = InMemoryStore()
        else:
            _store = InMemoryStore()
    return _store


# --------------------------------------------------------------------------- #
# Pure decision logic
# --------------------------------------------------------------------------- #
def window_key(identity: str, bucket: str, now: float, window_s: int) -> str:
    """Fixed-window key: same identity+bucket collapses within a window."""
    return f"rl:{bucket}:{identity}:{int(now) // window_s}"


def check(store, identity: str, bucket: str, *, limit: int, window_s: int,
          now: Optional[float] = None) -> dict:
    """Increment the window counter and decide. Returns allowed/remaining/retry_after.

    Pure aside from ``store.incr``; test with InMemoryStore + a fixed ``now``.
    """
    t = time.time() if now is None else now
    key = window_key(identity, bucket, t, window_s)
    try:
        count = store.incr(key, window_s, t)
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning("rate limit: store error (%s); allowing request", exc)
        return {"allowed": True, "remaining": limit, "retry_after": 0}
    remaining = max(0, limit - count)
    retry_after = window_s - (int(t) % window_s) if count > limit else 0
    return {"allowed": count <= limit, "remaining": remaining, "retry_after": retry_after}


# --------------------------------------------------------------------------- #
# FastAPI dependency
# --------------------------------------------------------------------------- #
def _identity(request) -> str:
    """Best-effort caller identity: org:user when authed, else client IP."""
    user = getattr(getattr(request, "state", None), "user", None)
    if user is not None:
        return f"org{getattr(user, 'organization_id', '?')}:u{getattr(user, 'id', '?')}"
    client = getattr(request, "client", None)
    return f"ip:{getattr(client, 'host', 'unknown')}"


def RateLimit(bucket: str, *, limit: int, window_s: int = 60) -> Callable:
    """FastAPI dependency: ``limit`` requests per ``window_s`` per caller, per bucket."""
    from fastapi import HTTPException, Request

    async def dependency(request: Request):
        result = check(get_store(), _identity(request), bucket, limit=limit, window_s=window_s)
        if not result["allowed"]:
            raise HTTPException(
                status_code=429, detail="Rate limit exceeded — slow down.",
                headers={"Retry-After": str(result["retry_after"])},
            )
        return result

    return dependency
