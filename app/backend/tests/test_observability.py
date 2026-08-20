"""Tests for observability pure helpers (no fastapi/sentry needed)."""

from observability import (
    build_access_log,
    init_sentry,
    new_request_id,
    redact_headers,
)


def test_request_id_unique_and_short():
    ids = {new_request_id() for _ in range(100)}
    assert len(ids) == 100                       # unique
    assert all(len(i) == 12 for i in ids)


def test_redact_headers_masks_secrets():
    h = {"Authorization": "Bearer x", "Cookie": "s=1", "Content-Type": "application/json"}
    out = redact_headers(h)
    assert out["Authorization"] == "***"
    assert out["Cookie"] == "***"
    assert out["Content-Type"] == "application/json"   # non-secret preserved


def test_redact_is_case_insensitive():
    assert redact_headers({"AUTHORIZATION": "x"})["AUTHORIZATION"] == "***"
    assert redact_headers({"x-api-key": "k"})["x-api-key"] == "***"


def test_build_access_log_shape():
    rec = build_access_log(method="POST", path="/api/x", status=200,
                           duration_ms=12.345, request_id="abc123", identity="org1:u2")
    assert rec == {
        "event": "http_request", "request_id": "abc123", "method": "POST",
        "path": "/api/x", "status": 200, "duration_ms": 12.3, "identity": "org1:u2",
    }


def test_init_sentry_noop_without_dsn():
    assert init_sentry(dsn=None) is False        # no DSN -> no-op, no crash
    assert init_sentry(dsn="") is False
