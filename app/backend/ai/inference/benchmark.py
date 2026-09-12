"""
Inference benchmarking harness (mission item #7).

Measures latency percentiles and throughput of any callable — the real model on
the GPU box, or a stub in tests. Timing is done through an injectable ``clock``
so the statistics core is deterministic and unit-tested without sleeping or a
GPU. Warmup iterations are excluded (first calls pay lazy-load / CUDA-graph
costs that don't represent steady state).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Callable, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class BenchmarkResult:
    runs: int
    device: str
    mean_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    throughput_ips: float  # items per second (1000 / mean_ms)

    def as_dict(self) -> dict:
        return asdict(self)


def summarize_latencies(latencies_ms: Sequence[float], *, device: str = "cpu") -> BenchmarkResult:
    """Compute percentile/throughput stats from a list of per-run latencies (ms)."""
    if not latencies_ms:
        raise ValueError("need at least one latency sample")
    arr = np.asarray(latencies_ms, dtype=float)
    mean = float(arr.mean())
    return BenchmarkResult(
        runs=len(arr),
        device=device,
        mean_ms=round(mean, 3),
        p50_ms=round(float(np.percentile(arr, 50)), 3),
        p90_ms=round(float(np.percentile(arr, 90)), 3),
        p95_ms=round(float(np.percentile(arr, 95)), 3),
        p99_ms=round(float(np.percentile(arr, 99)), 3),
        min_ms=round(float(arr.min()), 3),
        max_ms=round(float(arr.max()), 3),
        throughput_ips=round(1000.0 / mean, 3) if mean > 0 else 0.0,
    )


def benchmark(
    fn: Callable[[object], object],
    inputs: Sequence[object],
    *,
    warmup: int = 1,
    repeats: int = 1,
    device: str = "cpu",
    clock: Optional[Callable[[], float]] = None,
) -> BenchmarkResult:
    """Time ``fn(input)`` across ``inputs`` × ``repeats`` after ``warmup`` calls.

    ``clock`` returns seconds (defaults to ``time.perf_counter``); tests inject a
    deterministic clock. Warmup calls run against the first input and are not
    timed.
    """
    if not inputs:
        raise ValueError("need at least one input")
    now = clock or time.perf_counter

    for _ in range(max(0, warmup)):
        fn(inputs[0])

    latencies: list[float] = []
    for _ in range(max(1, repeats)):
        for x in inputs:
            t0 = now()
            fn(x)
            latencies.append((now() - t0) * 1000.0)
    return summarize_latencies(latencies, device=device)
