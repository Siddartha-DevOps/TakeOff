"""
GPU / CPU device resolution for inference (mission item #8).

Picks the best available torch device from a request string, with a fully
injectable capability *probe* so the selection logic is unit-testable without
torch installed. The default probe lazily imports torch on the GPU box.

    resolve_device("auto")   -> cuda if present, else mps (Apple), else cpu
    resolve_device("cpu")    -> forced cpu
    resolve_device("cuda:1") -> that gpu if it exists, else a downgrade w/ reason
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

VALID_KINDS = ("gpu", "cpu")


@dataclass(frozen=True)
class DeviceInfo:
    """Resolved device the engine will run on."""
    device: str      # torch device string: 'cuda', 'cuda:0', 'mps', 'cpu'
    kind: str        # 'gpu' | 'cpu'
    name: str        # human-readable, e.g. 'NVIDIA A10G' or 'CPU'
    reason: str      # why this device was chosen (audit / logs)


# A capability probe returns what hardware is actually present. Kept as a plain
# dict so tests can inject any scenario without torch.
Probe = Callable[[], dict]


def default_probe() -> dict:
    """Real hardware probe — lazily imports torch (GPU box only)."""
    try:
        import torch
    except ImportError:
        return {"cuda": False, "cuda_count": 0, "mps": False, "cuda_names": []}
    cuda = bool(torch.cuda.is_available())
    count = int(torch.cuda.device_count()) if cuda else 0
    names = [torch.cuda.get_device_name(i) for i in range(count)] if cuda else []
    mps = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    return {"cuda": cuda, "cuda_count": count, "mps": mps, "cuda_names": names}


def _parse_cuda_index(requested: str) -> Optional[int]:
    """Extract N from 'cuda:N', or None for bare 'cuda'."""
    if ":" in requested:
        try:
            return int(requested.split(":", 1)[1])
        except ValueError:
            return None
    return None


def resolve_device(requested: str = "auto", *, probe: Optional[Probe] = None) -> DeviceInfo:
    """Resolve a requested device against actual hardware capabilities.

    Never raises for an unavailable device — it downgrades to the best available
    option and records *why* in ``reason`` (so a job that expected a GPU but ran
    on CPU is visible in logs, not silent).
    """
    req = (requested or "auto").strip().lower()
    caps = (probe or default_probe)()
    cuda, count, mps = caps.get("cuda", False), caps.get("cuda_count", 0), caps.get("mps", False)
    names = caps.get("cuda_names", []) or []

    def gpu(idx: int, reason: str) -> DeviceInfo:
        name = names[idx] if idx < len(names) else f"cuda:{idx}"
        return DeviceInfo(device=f"cuda:{idx}", kind="gpu", name=name, reason=reason)

    def cpu(reason: str) -> DeviceInfo:
        return DeviceInfo(device="cpu", kind="cpu", name="CPU", reason=reason)

    if req == "cpu":
        return cpu("cpu explicitly requested")

    if req.startswith("cuda"):
        if not cuda or count == 0:
            return cpu(f"{req} requested but no CUDA device available")
        idx = _parse_cuda_index(req)
        if idx is None:
            return gpu(0, "cuda requested; using device 0")
        if idx >= count:
            return gpu(0, f"cuda:{idx} out of range ({count} device(s)); using device 0")
        return gpu(idx, f"cuda:{idx} requested and available")

    if req == "mps":
        if mps:
            return DeviceInfo(device="mps", kind="gpu", name="Apple MPS", reason="mps requested and available")
        return cpu("mps requested but not available")

    # auto (or anything unrecognized) -> best available
    if cuda and count > 0:
        return gpu(0, "auto: CUDA available")
    if mps:
        return DeviceInfo(device="mps", kind="gpu", name="Apple MPS", reason="auto: MPS available")
    return cpu("auto: no GPU detected")
