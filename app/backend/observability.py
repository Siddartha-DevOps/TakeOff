"""
Observability (backend hardening #3) — Sentry + structured request logging.

The audit found no error tracking / metrics / tracing (CLAUDE.md §3 asked for
Sentry). This adds:
  - Sentry init (lazy, no-op unless SENTRY_DSN set and the SDK is installed),
  - a request-logging middleware that emits one structured line per request
    (method, path, status, duration, request id, caller) and sets X-Request-ID,
  - secret-redacting header helper.

All heavy imports (sentry_sdk, starlette types) are lazy/inside ``init_observability``
so this module imports with stdlib only and its pure helpers are unit-tested on a
bare box. ``init_observability(app)`` is called once at server startup.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

logger = logging.getLogger("takeoff.request")

_REDACT_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization"}


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------- #
def new_request_id() -> str:
    """A short unique request id (uuid4 hex, 12 chars)."""
    return uuid.uuid4().hex[:12]


def redact_headers(headers: dict) -> dict:
    """Copy headers with secret values masked (case-insensitive names)."""
    out = {}
    for k, v in headers.items():
        out[k] = "***" if k.lower() in _REDACT_HEADERS else v
    return out


def build_access_log(*, method: str, path: str, status: int, duration_ms: float,
                     request_id: str, identity: str = "-") -> dict:
    """The structured access-log record for one request."""
    return {
        "event": "http_request",
        "request_id": request_id,
        "method": method,
        "path": path,
        "status": status,
        "duration_ms": round(duration_ms, 1),
        "identity": identity,
    }


def _identity(request) -> str:
    user = getattr(getattr(request, "state", None), "user", None)
    if user is not None:
        return f"org{getattr(user, 'organization_id', '?')}:u{getattr(user, 'id', '?')}"
    client = getattr(request, "client", None)
    return f"ip:{getattr(client, 'host', 'unknown')}"


# --------------------------------------------------------------------------- #
# Wiring (lazy heavy imports) — called once at startup
# --------------------------------------------------------------------------- #
def init_sentry(dsn: Optional[str] = None, environment: Optional[str] = None) -> bool:
    """Initialize Sentry if a DSN is configured and the SDK is available. No-op else."""
    dsn = dsn if dsn is not None else os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk  # lazy — not a CI dep
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry_sdk not installed; skipping")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment or os.environ.get("ENVIRONMENT", "development"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
    )
    logger.info("Sentry initialized")
    return True


def init_observability(app) -> None:
    """Configure logging, init Sentry, and add the request-logging middleware."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_sentry()

    @app.middleware("http")
    async def _request_logger(request, call_next):
        rid = new_request_id()
        request.state.request_id = rid
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = (time.perf_counter() - t0) * 1000
            logger.exception("%s", build_access_log(
                method=request.method, path=request.url.path, status=500,
                duration_ms=duration, request_id=rid, identity=_identity(request)))
            raise
        duration = (time.perf_counter() - t0) * 1000
        record = build_access_log(
            method=request.method, path=request.url.path, status=response.status_code,
            duration_ms=duration, request_id=rid, identity=_identity(request))
        (logger.warning if response.status_code >= 500 else logger.info)("%s", record)
        response.headers["X-Request-ID"] = rid
        return response
