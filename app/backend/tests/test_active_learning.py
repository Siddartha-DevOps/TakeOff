"""Tests for active-learning query strategies."""

import math

import pytest

from ml.active_learning import (
    entropy,
    least_confidence,
    margin_confidence,
    rank_drawings_for_review,
    select_batch,
    uncertainty_rank,
)


def test_least_confidence():
    assert least_confidence(0.9) == pytest.approx(0.1)


def test_margin_confidence():
    assert margin_confidence(0.6, 0.5) == pytest.approx(0.9)


def test_entropy_uniform_is_max():
    assert entropy([0.5, 0.5]) == pytest.approx(math.log(2))
    assert entropy([1.0, 0.0]) == pytest.approx(0.0)


def test_uncertainty_rank_orders_most_unsure_first():
    items = [{"confidence": 0.95}, {"confidence": 0.55}, {"confidence": 0.8}]
    ranked = uncertainty_rank(items)
    assert [r["confidence"] for r in ranked] == [0.55, 0.8, 0.95]


def test_select_batch_topk():
    items = [{"confidence": c} for c in (0.9, 0.5, 0.7, 0.6)]
    picked = select_batch(items, 2)
    assert [p["confidence"] for p in picked] == [0.5, 0.6]


def test_select_batch_diversity_spreads_across_groups():
    # Group A has all the most-uncertain items; without diversity we'd pick 3 from A.
    items = [
        {"confidence": 0.10, "drawing_id": 1},
        {"confidence": 0.11, "drawing_id": 1},
        {"confidence": 0.12, "drawing_id": 1},
        {"confidence": 0.40, "drawing_id": 2},
    ]
    picked = select_batch(items, 2, diversity_key="drawing_id")
    dids = {p["drawing_id"] for p in picked}
    assert dids == {1, 2}  # round-robin pulled from both drawings


def test_rank_drawings_weights_uncertainty_and_disagreement():
    drawings = [
        {"drawing_id": 1, "mean_confidence": 0.95, "n_detections": 10, "n_rejections": 0},
        {"drawing_id": 2, "mean_confidence": 0.60, "n_detections": 10, "n_rejections": 6},
    ]
    ranked = rank_drawings_for_review(drawings)
    assert ranked[0]["drawing_id"] == 2   # low confidence + high rejection -> label first
    assert ranked[0]["priority"] > ranked[1]["priority"]
