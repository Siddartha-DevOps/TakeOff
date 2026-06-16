"""
Unit tests for detection_engine model-loading robustness.

These tests deliberately run WITHOUT a trained model, GPU, ultralytics, or the
heavy preprocessing stack (OpenCV / PyMuPDF). They verify that:

  - the module imports cleanly with only numpy + loguru installed,
  - BlueprintDetector never crashes when weights are missing, and
  - detect() returns a well-formed "untrained" result with the right schema.

Run: pytest backend/ai/test_detection_engine.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

import detection_engine as de


def test_module_imports_without_heavy_stack():
    # If module-level imports pulled in cv2/boto3/ultralytics this file would
    # have failed to import above. Sanity-check a couple of public symbols.
    assert hasattr(de, "BlueprintDetector")
    assert callable(de.model_is_available)


def test_ensure_model_returns_none_when_missing():
    assert de._ensure_model("definitely_not_a_real_model_xyz.pt") is None


def test_detector_does_not_crash_without_weights():
    det = de.BlueprintDetector(model_filename="definitely_not_a_real_model_xyz.pt")
    assert det.available is False
    assert det.model is None


def test_detect_returns_untrained_result_schema():
    det = de.BlueprintDetector(model_filename="definitely_not_a_real_model_xyz.pt")
    # A dummy image — should never be touched because there is no model.
    img = np.zeros((8, 8, 3), dtype=np.uint8)

    result = det.detect(img, scale_info={"ratio": 48.0})

    # Same top-level shape as a real detection result.
    for key in (
        "rooms", "doors", "windows", "mep",
        "summary", "quantities", "scale_ratio",
        "processing_time_ms", "model_version",
    ):
        assert key in result, f"missing key: {key}"

    assert result["rooms"] == []
    assert result["doors"] == []
    assert result["windows"] == []
    assert result["mep"] == []
    assert result["quantities"] == []
    assert result["scale_ratio"] == 48.0
    assert result["model_version"] == "untrained"
    assert result["model_status"] == "untrained"
    assert result["summary"]["totalArea"] == 0

    # Summary keys consumed by the frontend / chat context.
    for key in ("rooms", "doors", "windows", "mep", "walls", "totalArea"):
        assert key in result["summary"]


def test_detect_defaults_scale_ratio_when_no_scale_info():
    det = de.BlueprintDetector(model_filename="definitely_not_a_real_model_xyz.pt")
    result = det.detect(np.zeros((8, 8, 3), dtype=np.uint8))
    assert result["scale_ratio"] == 96.0


def test_snap_to_standard_width():
    assert de._snap_to_standard_width(31) == 30
    assert de._snap_to_standard_width(35) == 36
    assert de._snap_to_standard_width(100) == 72


def test_compute_quantities_empty_input():
    # No detections → no quantities, no crash.
    assert de.compute_quantities([], [], [], [], scale_ratio=96.0, dpi=300) == []


def test_compute_quantities_basic():
    rooms = [
        {"label": "Bedroom", "area": 144},
        {"label": "Bathroom", "area": 50},
    ]
    doors = [{"type": "standard_door"}]
    windows = [{"type": "sliding_window"}]
    mep = [{"type": "toilet"}, {"type": "outlet"}]

    qs = de.compute_quantities(rooms, doors, windows, mep, scale_ratio=96.0, dpi=300)
    trades = {q["trade"] for q in qs}
    assert {"Drywall", "Painting", "Flooring", "Doors", "Windows", "Plumbing", "Electrical"} <= trades
