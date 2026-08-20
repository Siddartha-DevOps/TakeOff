"""Tests for the inference benchmarking harness (deterministic injected clock)."""

import pytest

from ai.inference.benchmark import benchmark, summarize_latencies


def test_summarize_percentiles_and_throughput():
    res = summarize_latencies([10, 20, 30, 40], device="cuda:0")
    assert res.runs == 4
    assert res.device == "cuda:0"
    assert res.mean_ms == 25.0
    assert res.min_ms == 10.0 and res.max_ms == 40.0
    assert res.throughput_ips == pytest.approx(1000 / 25.0, rel=1e-3)


def test_summarize_requires_samples():
    with pytest.raises(ValueError):
        summarize_latencies([])


def test_benchmark_excludes_warmup_and_uses_injected_clock():
    # Fake clock advances 0.1s (100ms) every call.
    ticks = iter(range(0, 100000))
    clock = lambda: next(ticks) * 0.1

    calls = []
    res = benchmark(lambda x: calls.append(x), inputs=["a", "b"], warmup=1, repeats=2, clock=clock, device="cpu")

    # warmup(1) + inputs(2)*repeats(2) = 5 calls total
    assert len(calls) == 5
    # each timed call spans exactly two clock reads (before/after) = 100ms
    assert res.runs == 4
    assert res.mean_ms == pytest.approx(100.0)


def test_benchmark_requires_inputs():
    with pytest.raises(ValueError):
        benchmark(lambda x: x, inputs=[])
