"""Tests for the CorrectionEvent -> YOLO-seg label export (pure functions)."""

import pytest

from ml.training.export_corrections import (
    build_class_map,
    build_label_lines,
    correction_to_seg_line,
    normalize_ring,
    _ring_from_geometry,
)
from ml.registry.model_card import build_model_card, card_to_markdown

CLASS_MAP = {"Door": 0, "Kitchen": 1}


def test_ring_from_bbox_and_ring():
    assert _ring_from_geometry([0, 0, 10, 20]) == [[0, 0], [10, 0], [10, 20], [0, 20]]
    ring = [[0, 0], [1, 0], [1, 1]]
    assert _ring_from_geometry(ring) == [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]
    assert _ring_from_geometry([[0, 0], [1, 1]]) is None  # < 3 pts, not a bbox


def test_normalize_ring_clamps_0_1():
    got = normalize_ring([[0, 0], [150, 100]], 300, 200)
    assert got == [0.0, 0.0, 0.5, 0.5]
    assert normalize_ring([[600, 400]], 300, 200) == [1.0, 1.0]  # clamped
    with pytest.raises(ValueError):
        normalize_ring([[0, 0]], 0, 200)


def test_correction_to_seg_line():
    after = {"geometry": [[0, 0], [300, 0], [300, 200], [0, 200]], "meta": {"label": "Kitchen"}}
    label, line = correction_to_seg_line(after, CLASS_MAP, 300, 200)
    assert label == "Kitchen"
    assert line.split()[0] == "1"  # class id for Kitchen
    assert line == "1 0 0 1 0 1 1 0 1"


def test_correction_skips_unknown_label_or_bad_geom():
    assert correction_to_seg_line({"geometry": [[0, 0]], "meta": {"label": "Door"}}, CLASS_MAP, 10, 10) is None
    assert correction_to_seg_line({"geometry": [[0, 0], [1, 0], [1, 1]], "label": "Unknown"}, CLASS_MAP, 10, 10) is None


def test_build_label_lines_and_class_map():
    corrections = [
        {"geometry": [0, 0, 10, 10], "label": "Door"},
        {"geometry": [[0, 0], [10, 0], [10, 10], [0, 10]], "meta": {"label": "Kitchen"}},
        {"geometry": [0, 0, 5, 5], "label": "NotInMap"},  # skipped
    ]
    lines = build_label_lines(corrections, CLASS_MAP, 100, 100)
    assert len(lines) == 2
    assert build_class_map(["Door", "Kitchen", "Door"]) == {"Door": 0, "Kitchen": 1}


def test_model_card_from_report():
    report = {
        "metrics": {"miou": 0.82, "map": 0.61, "measurement_error_pct": 3.4, "n_samples": 12},
        "gate_passed": True, "gate_reasons": [], "thresholds": {"min_miou": 0.7},
    }
    card = build_model_card(name="symbol_seg", version="2026.07.1", task="symbol_det", eval_report=report)
    assert card["promotable"] is True
    assert card["metrics"]["map@0.5"] == 0.61
    md = card_to_markdown(card)
    assert "✅ PASSED" in md and "symbol_seg" in md
