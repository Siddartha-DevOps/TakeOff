"""Correctness tests for the golden-set eval metrics (these gate promotion)."""

import pytest

from ml.eval.metrics import (
    average_precision,
    box_iou,
    mean_average_precision,
    mean_iou,
    measurement_error_pct,
    poly_iou,
)

SQ_A = [[0, 0], [2, 0], [2, 2], [0, 2]]            # area 4
SQ_B = [[1, 0], [3, 0], [3, 2], [1, 2]]            # area 4, overlaps A by 2
BOX_A = [0, 0, 2, 2]
BOX_B = [1, 0, 3, 2]


def test_poly_iou_half_overlap():
    assert poly_iou(SQ_A, SQ_A) == pytest.approx(1.0)
    assert poly_iou(SQ_A, SQ_B) == pytest.approx(2 / 6)  # inter 2, union 6


def test_box_iou_matches_poly():
    assert box_iou(BOX_A, BOX_A) == pytest.approx(1.0)
    assert box_iou(BOX_A, BOX_B) == pytest.approx(2 / 6)
    assert box_iou([0, 0, 1, 1], [5, 5, 6, 6]) == 0.0  # disjoint


def test_mean_iou_matched_and_missed():
    assert mean_iou([SQ_A], [SQ_A]) == pytest.approx(1.0)
    assert mean_iou([SQ_A], []) == pytest.approx(0.0)       # miss -> 0
    # A matches perfectly, a far-away second GT is missed -> mean 0.5
    far = [[10, 10], [12, 10], [12, 12], [10, 12]]
    assert mean_iou([SQ_A, far], [SQ_A]) == pytest.approx(0.5)
    assert mean_iou([], [SQ_A]) is None                     # undefined


def test_average_precision_perfect_and_with_fp():
    gts = [BOX_A, [10, 10, 12, 12]]
    perfect = [{"score": 0.9, "geom": BOX_A}, {"score": 0.8, "geom": [10, 10, 12, 12]}]
    assert average_precision(perfect, gts) == pytest.approx(1.0)

    # one true positive + one false positive against two GT -> AP 0.5
    one_tp_one_fp = [{"score": 0.9, "geom": BOX_A}, {"score": 0.8, "geom": [50, 50, 52, 52]}]
    assert average_precision(one_tp_one_fp, gts) == pytest.approx(0.5)

    assert average_precision([], gts) == pytest.approx(0.0)  # no preds
    assert average_precision(perfect, []) is None            # no GT -> undefined


def test_mean_average_precision_skips_classes_without_gt():
    preds = {"door": [{"score": 0.9, "geom": BOX_A}], "window": [{"score": 0.5, "geom": BOX_A}]}
    gts = {"door": [BOX_A], "window": []}  # window has no GT -> excluded
    assert mean_average_precision(preds, gts) == pytest.approx(1.0)


def test_measurement_error_pct():
    assert measurement_error_pct({"a": 105, "b": 45}, {"a": 100, "b": 50}) == pytest.approx(7.5)
    assert measurement_error_pct({}, {"a": 100}) == pytest.approx(100.0)  # missing pred -> 0
    assert measurement_error_pct({"a": 1}, {}) is None                    # no GT
