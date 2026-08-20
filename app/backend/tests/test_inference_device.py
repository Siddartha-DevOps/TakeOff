"""Tests for GPU/CPU device resolution (injected probe — no torch needed)."""

from ai.inference.device import resolve_device


def probe(cuda=False, count=0, mps=False, names=None):
    return lambda: {"cuda": cuda, "cuda_count": count, "mps": mps, "cuda_names": names or []}


def test_auto_prefers_cuda():
    d = resolve_device("auto", probe=probe(cuda=True, count=2, names=["A10G", "A10G"]))
    assert d.device == "cuda:0" and d.kind == "gpu" and d.name == "A10G"


def test_auto_falls_back_to_mps_then_cpu():
    assert resolve_device("auto", probe=probe(mps=True)).device == "mps"
    assert resolve_device("auto", probe=probe()).device == "cpu"


def test_cpu_is_forced():
    d = resolve_device("cpu", probe=probe(cuda=True, count=1))
    assert d.device == "cpu" and "explicitly" in d.reason


def test_cuda_requested_without_gpu_downgrades_with_reason():
    d = resolve_device("cuda", probe=probe())
    assert d.device == "cpu" and "no CUDA" in d.reason


def test_specific_cuda_index_out_of_range_clamps():
    d = resolve_device("cuda:3", probe=probe(cuda=True, count=2, names=["a", "b"]))
    assert d.device == "cuda:0" and "out of range" in d.reason


def test_specific_cuda_index_in_range():
    d = resolve_device("cuda:1", probe=probe(cuda=True, count=2, names=["a", "b"]))
    assert d.device == "cuda:1" and d.name == "b"
