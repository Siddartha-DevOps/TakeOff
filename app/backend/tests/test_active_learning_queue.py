"""Tests for the active-learning review-queue aggregation (Phase 6)."""

from ml.active_learning.queue import (
    REJECTION_ACTIONS,
    aggregate_drawing_stats,
    detection_items,
)
from ml.active_learning.sampler import rank_drawings_for_review, select_batch


def test_aggregate_means_and_counts():
    dets = [(1, 0.9), (1, 0.7), (2, 0.4)]
    corrs = [(1, "accept"), (2, "reject"), (2, "edit"), (None, "reject")]
    stats = {s["drawing_id"]: s for s in aggregate_drawing_stats(dets, corrs)}

    assert stats[1]["n_detections"] == 2
    assert stats[1]["mean_confidence"] == 0.8
    assert stats[1]["n_rejections"] == 0          # only an 'accept'
    assert stats[2]["n_rejections"] == 2          # reject + edit
    assert None not in stats                       # null drawing_id dropped


def test_aggregate_null_confidence_treated_as_confident():
    stats = aggregate_drawing_stats([(5, None), (5, None)], [])
    assert stats[0]["n_detections"] == 2
    assert stats[0]["mean_confidence"] == 1.0      # no scores -> confident, low priority


def test_correction_only_drawing_appears():
    # A drawing with corrections but no detection rows still enters the queue.
    stats = {s["drawing_id"]: s for s in aggregate_drawing_stats([], [(7, "relabel")])}
    assert stats[7]["n_rejections"] == 1 and stats[7]["n_detections"] == 0


def test_rejection_action_set():
    assert REJECTION_ACTIONS == {"reject", "relabel", "edit"}
    assert "accept" not in REJECTION_ACTIONS


def test_end_to_end_ranking_prioritizes_uncertain_and_disputed():
    # d1: confident, no rejections. d2: unsure + heavily rejected -> top priority.
    dets = [(1, 0.95)] * 5 + [(2, 0.55)] * 5
    corrs = [(2, "reject")] * 4
    stats = aggregate_drawing_stats(dets, corrs)
    ranked = rank_drawings_for_review(stats)
    assert ranked[0]["drawing_id"] == 2
    assert ranked[0]["priority"] > ranked[1]["priority"]


def test_detection_items_and_batch_selection():
    rows = [
        (10, 1, "wall", 0.95),
        (11, 1, "door", 0.20),   # most uncertain
        (12, 2, "window", 0.40),
    ]
    items = detection_items(rows)
    assert items[1]["confidence"] == 0.20
    # least-confidence first, spread across drawings
    picked = select_batch(items, 2, diversity_key="drawing_id")
    assert {p["drawing_id"] for p in picked} == {1, 2}


def test_detection_items_null_confidence_is_zero():
    items = detection_items([(1, 1, "wall", None)])
    assert items[0]["confidence"] == 0.0   # unscored -> maximally uncertain
