"""Tests for the inference engine: partitioning, quantities, and mock removal."""

import pytest

from ai.inference import (
    CLASSES,
    InferenceEngine,
    ModelRegistry,
    ModelSpec,
    ModelUnavailableError,
    TakeoffAIInference,
    TakeoffAnalysis,
)
from ai.inference.engine import partition_detections, raster_quantities


def test_backcompat_names_preserved():
    # The old import path and class name still resolve (API preserved).
    from ai.inference_api import TakeoffAIInference as Shim
    assert Shim is InferenceEngine
    assert TakeoffAIInference is InferenceEngine


def test_partition_detections_buckets_and_summary():
    dets = [
        {"label": "living", "bbox": [0, 0, 10, 10], "area": 100, "confidence": 0.9},
        {"label": "door", "bbox": [0, 0, 2, 4], "confidence": 0.8},
        {"label": "window", "bbox": [0, 0, 2, 2], "confidence": 0.7},
        {"label": "wall", "bbox": [0, 0, 20, 2], "confidence": 0.6},
        {"label": "balcony", "bbox": [0, 0, 5, 5], "area": 25, "confidence": 0.5},
    ]
    rooms, doors, windows, walls, balconies, summary, avg = partition_detections(dets)
    assert len(rooms) == 1 and len(doors) == 1 and len(windows) == 1
    assert len(walls) == 1 and len(balconies) == 1
    assert summary["totalArea"] == 100
    assert avg == pytest.approx(0.7, abs=1e-6)


def test_raster_quantities_shape():
    rooms = [{"label": "bathroom", "area": 50}, {"label": "living", "area": 200}]
    walls = [{"bbox": [0, 0, 90, 5]}]
    qs = raster_quantities(rooms, [{"label": "door"}], [{"label": "window"}], walls)
    trades = {q["trade"] for q in qs}
    assert {"Flooring", "Drywall", "Doors", "Windows", "Electrical", "Plumbing"} <= trades


def test_analyze_raises_when_no_model_installed(tmp_path):
    # No weights on disk -> production engine refuses to fabricate (mock removed).
    engine = InferenceEngine(model_path=str(tmp_path / "missing.pt"), device="cpu")
    assert engine.available is False
    with pytest.raises(ModelUnavailableError):
        engine.analyze("whatever.png", drawing_id=1)


def test_registry_reports_unavailable_without_weights(tmp_path):
    reg = ModelRegistry(device="cpu")
    reg.register(ModelSpec(task="symbols", name="sym-v1", weights_path=str(tmp_path / "no.pt")))
    assert reg.available("symbols") is False
    with pytest.raises(ModelUnavailableError):
        reg.load("symbols")


def test_no_mock_symbols_remain():
    # Guard against re-introducing a fabricated fallback.
    import ai.inference.engine as eng
    src = eng.__doc__ or ""
    assert "mock" in src.lower()  # doc explains the removal
    assert not hasattr(InferenceEngine, "_mock_analysis")


def test_takeoff_analysis_defaults_backcompat():
    a = TakeoffAnalysis(
        drawing_id=1, processing_time_ms=5, ai_model_version="v", rooms=[], doors=[],
        windows=[], walls=[], balconies=[], summary={}, quantities=[], confidence_avg=0.0,
    )
    assert a.model_available is True and a.status == "ok" and a.device == "cpu"
