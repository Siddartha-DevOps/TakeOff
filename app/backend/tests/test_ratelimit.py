"""Tests for rate-limit decisions and FastAPI dependency integration."""

from fastapi import Depends, FastAPI

from ratelimit import InMemoryStore, RateLimit, check, window_key


def test_dependency_injects_request_instead_of_exposing_query_parameter():
    app = FastAPI()

    @app.get("/limited", dependencies=[Depends(RateLimit("test", limit=1))])
    async def limited():
        return {"ok": True}

    parameters = app.openapi()["paths"]["/limited"]["get"].get("parameters", [])
    assert not any(parameter["name"] == "request" for parameter in parameters)


def test_window_key_collapses_within_window_and_rolls_over():
    # Fixed windows bucket by absolute 60s edges: [60,120) is window 1, [120,180) is 2.
    k1 = window_key("u1", "ai", now=100, window_s=60)   # window 1
    k2 = window_key("u1", "ai", now=115, window_s=60)   # same window 1
    k3 = window_key("u1", "ai", now=125, window_s=60)   # window 2
    assert k1 == k2 and k1 != k3


def test_allows_up_to_limit_then_denies():
    store = InMemoryStore()
    results = [check(store, "u1", "ai", limit=3, window_s=60, now=1000) for _ in range(4)]
    assert [r["allowed"] for r in results] == [True, True, True, False]
    assert results[2]["remaining"] == 0
    assert results[3]["retry_after"] > 0


def test_separate_identities_independent():
    store = InMemoryStore()
    a = check(store, "u1", "ai", limit=1, window_s=60, now=1000)
    b = check(store, "u2", "ai", limit=1, window_s=60, now=1000)
    assert a["allowed"] and b["allowed"]                 # different callers, own buckets


def test_separate_buckets_independent():
    store = InMemoryStore()
    check(store, "u1", "ai", limit=1, window_s=60, now=1000)
    other = check(store, "u1", "upload", limit=1, window_s=60, now=1000)
    assert other["allowed"]                              # different bucket


def test_window_reset_after_rollover():
    store = InMemoryStore()
    assert check(store, "u1", "ai", limit=1, window_s=60, now=1000)["allowed"]
    assert not check(store, "u1", "ai", limit=1, window_s=60, now=1000)["allowed"]
    # next window -> counter resets
    assert check(store, "u1", "ai", limit=1, window_s=60, now=1061)["allowed"]


def test_fail_open_on_store_error():
    class Boom:
        def incr(self, *a, **k):
            raise RuntimeError("redis down")
    r = check(Boom(), "u1", "ai", limit=1, window_s=60, now=1000)
    assert r["allowed"] is True                          # limiter outage must not block
