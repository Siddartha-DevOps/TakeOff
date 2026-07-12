"""Tests for the golden-set harness aggregation + promotion gate."""

import pytest

from ml.eval.harness import evaluate, gate

SQ = [[0, 0], [100, 0], [100, 100], [0, 100]]
BOX = [0, 0, 100, 100]


def _perfect_sample():
    return {
        "image_id": "s1",
        "rooms": {"gt": [SQ], "pred": [SQ]},
        "symbols": {"gt": {"door": [BOX]}, "pred": {"door": [{"score": 0.95, "geom": BOX}]}},
        "quantities": {"gt": {"floor_area_sqft": 100, "door_count": 1},
                       "pred": {"floor_area_sqft": 100, "door_count": 1}},
    }


def test_perfect_sample_passes_gate():
    report = evaluate([_perfect_sample()])
    m = report["metrics"]
    assert m["miou"] == pytest.approx(1.0)
    assert m["map"] == pytest.approx(1.0)
    assert m["measurement_error_pct"] == pytest.approx(0.0)
    assert report["gate_passed"] is True
    assert report["gate_reasons"] == []


def test_bad_sample_fails_gate():
    bad = {
        "image_id": "s2",
        "rooms": {"gt": [SQ], "pred": []},  # missed room -> mIoU 0
        "symbols": {"gt": {"door": [BOX]}, "pred": {}},  # missed door -> AP 0
        "quantities": {"gt": {"floor_area_sqft": 100}, "pred": {"floor_area_sqft": 130}},  # 30% off
    }
    report = evaluate([bad])
    assert report["gate_passed"] is False
    # all three checks should fail
    assert any("mIoU" in r for r in report["gate_reasons"])
    assert any("mAP" in r for r in report["gate_reasons"])
    assert any("measurement error" in r for r in report["gate_reasons"])


def test_gate_thresholds_override():
    metrics = {"miou": 0.6, "map": 0.6, "measurement_error_pct": 4.0}
    assert gate(metrics)[0] is False                       # 0.6 < default 0.70 mIoU
    assert gate(metrics, {"min_miou": 0.5, "min_map": 0.5})[0] is True


def test_missing_metric_fails_closed():
    passed, reasons = gate({"miou": None, "map": 0.9, "measurement_error_pct": 1.0})
    assert passed is False
    assert any("no samples" in r for r in reasons)
