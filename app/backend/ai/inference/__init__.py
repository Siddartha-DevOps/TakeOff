"""
Production inference package for TakeOff.ai.

Replaces the single-file ``ai/inference_api.py`` mock engine with a real,
device-aware, multi-model, tiled inference stack. The old public names
(``TakeoffAIInference``, ``TakeoffAnalysis``, ``CLASSES``, ``get_instance``,
``analyze``) are re-exported so ``server.py`` and ``routes/takeoff_routes.py``
keep working unchanged — the HTTP API and the Python API are preserved; only the
implementation is replaced.

Design goals:
- **No fabricated output.** When no trained model is installed, ``analyze``
  raises ``ModelUnavailableError`` instead of returning fake detections. The
  real no-model path is vector-PDF geometry (``geometry/vector_pdf.py``), not a
  mock.
- **GPU or CPU** via ``ai.inference.device`` (auto-detect, override-able).
- **Multi-model** via a task→model registry (``ModelRegistry``), so room
  segmentation, symbol detection, and future trades share one engine.
- **Large drawings**: tiled inference with cross-seam NMS merge
  (``ai.inference.tiling``).
- **Confidence**: per-class thresholds + calibration (``ai.inference.confidence``).
- **Benchmarking**: latency/throughput harness (``ai.inference.benchmark``).

Every logic core here is pure NumPy/stdlib and unit-tested; torch / ultralytics /
cv2 are imported lazily inside the methods that actually run a model.
"""

from .engine import (
    CLASSES,
    InferenceEngine,
    ModelRegistry,
    ModelSpec,
    ModelUnavailableError,
    TakeoffAIInference,
    TakeoffAnalysis,
)

__all__ = [
    "CLASSES",
    "InferenceEngine",
    "ModelRegistry",
    "ModelSpec",
    "ModelUnavailableError",
    "TakeoffAIInference",
    "TakeoffAnalysis",
]
