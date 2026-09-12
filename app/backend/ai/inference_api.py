"""
Backward-compatibility shim.

The mock inference engine that used to live here has been replaced by the
production ``ai.inference`` package (device-aware, multi-model, tiled, no
fabricated output). This module now only re-exports the public names so existing
imports keep working:

    from ai.inference_api import TakeoffAIInference   # server.py
    ai_engine.analyze(raster_path, drawing_id)         # routes/takeoff_routes.py

There is no longer a ``_mock_analysis``: when no trained model is installed,
``analyze`` raises ``ai.inference.ModelUnavailableError`` instead of returning
fake detections. See ``ai/inference/README.md``.
"""

from ai.inference import (  # noqa: F401
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
