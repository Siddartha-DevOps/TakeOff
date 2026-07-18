"""Tests for confidence scoring, NMS, and calibration."""

import numpy as np
import pytest

from ai.inference.confidence import (
    apply_class_thresholds,
    apply_temperature,
    box_iou,
    expected_calibration_error,
    fit_temperature,
    nms,
)


def test_class_thresholds_filter():
    dets = [
        {"label": "wall", "confidence": 0.4},
        {"label": "outlet", "confidence": 0.4},
        {"label": "door", "confidence": 0.1},
    ]
    kept = apply_class_thresholds(dets, {"wall": 0.3, "outlet": 0.5}, default=0.25)
    labels = {d["label"] for d in kept}
    assert labels == {"wall"}  # outlet below 0.5, door below default 0.25


def test_class_thresholds_drops_missing_score():
    assert apply_class_thresholds([{"label": "wall"}], {}, default=0.0) == []


def test_box_iou_half_overlap():
    assert box_iou([0, 0, 2, 2], [1, 0, 3, 2]) == pytest.approx(2 / 6)


def test_nms_suppresses_overlap_keeps_best():
    boxes = [[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]]
    kept = nms(boxes, [0.7, 0.9, 0.5], iou_thr=0.5)
    assert kept[0] == 1        # highest score first
    assert 0 not in kept       # overlaps idx 1 -> suppressed
    assert 2 in kept           # disjoint survives


def test_temperature_softens_and_sharpens():
    hi = apply_temperature([0.9], 2.0)[0]   # T>1 pulls toward 0.5
    lo = apply_temperature([0.9], 0.5)[0]   # T<1 pushes toward 1
    assert hi < 0.9 < lo


def test_fit_temperature_recovers_overconfidence():
    # Model says 0.9 but is only right ~half the time -> calibration should soften.
    scores = [0.9] * 100
    correct = [True, False] * 50
    t = fit_temperature(scores, correct)
    assert t > 1.0
    assert apply_temperature([0.9], t)[0] < 0.9


def test_ece_zero_when_perfectly_calibrated():
    # 0.5-confidence detections that are right exactly half the time.
    scores = [0.5] * 100
    correct = [True, False] * 50
    assert expected_calibration_error(scores, correct, n_bins=10) == pytest.approx(0.0, abs=1e-9)


def test_ece_positive_when_overconfident():
    scores = [0.95] * 100
    correct = [True, False] * 50   # only 50% right
    assert expected_calibration_error(scores, correct) > 0.4
