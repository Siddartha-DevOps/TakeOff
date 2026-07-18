"""Tests for the SAM2 zero-shot room bootstrap geometry (no torch/GPU needed)."""

import numpy as np
import pytest

from ai.sam2_zero_shot import (
    bbox_to_ring,
    filter_by_area,
    mask_area,
    mask_bbox,
    mask_iou,
    masks_to_detections,
    nms_masks,
    point_prompt_grid,
    run_sam2_zero_shot,
    sam2_weights_available,
)


def _rect_mask(h, w, x1, y1, x2, y2):
    m = np.zeros((h, w), dtype=bool)
    m[y1:y2, x1:x2] = True
    return m


# --- point grid -----------------------------------------------------------
def test_point_grid_count_and_interior():
    pts = point_prompt_grid(100, 200, n_per_side=4)
    assert len(pts) == 16
    # every point strictly inside the page, never on the border
    assert all(0 < x < 100 and 0 < y < 200 for x, y in pts)


def test_point_grid_rejects_bad_dims():
    with pytest.raises(ValueError):
        point_prompt_grid(0, 10, 4)
    with pytest.raises(ValueError):
        point_prompt_grid(10, 10, 0)


# --- mask primitives ------------------------------------------------------
def test_mask_bbox_and_area():
    m = _rect_mask(50, 50, 10, 5, 20, 25)  # 10 wide x 20 tall
    assert mask_bbox(m) == [10, 5, 20, 25]
    assert mask_area(m) == 10 * 20


def test_mask_bbox_empty_is_none():
    assert mask_bbox(np.zeros((10, 10), dtype=bool)) is None


def test_mask_iou_half_overlap():
    a = _rect_mask(10, 10, 0, 0, 4, 4)   # area 16
    b = _rect_mask(10, 10, 2, 0, 6, 4)   # area 16, overlap 8
    # inter 8, union 24
    assert mask_iou(a, b) == pytest.approx(8 / 24)


def test_mask_iou_disjoint_is_zero():
    a = _rect_mask(10, 10, 0, 0, 2, 2)
    b = _rect_mask(10, 10, 5, 5, 7, 7)
    assert mask_iou(a, b) == 0.0


# --- NMS -------------------------------------------------------------------
def test_nms_collapses_duplicates_keeps_best():
    base = _rect_mask(20, 20, 0, 0, 10, 10)
    dup = _rect_mask(20, 20, 0, 0, 10, 10)      # identical -> IoU 1.0
    far = _rect_mask(20, 20, 12, 12, 18, 18)    # disjoint
    kept = nms_masks([base, dup, far], scores=[0.8, 0.9, 0.7], iou_thr=0.5)
    # the higher-scoring duplicate (idx 1) survives, its twin (idx 0) is dropped
    assert 1 in kept and 0 not in kept
    assert 2 in kept
    assert kept[0] == 1  # highest score first


# --- area filter -----------------------------------------------------------
def test_filter_by_area_drops_speck_and_blob():
    page = 100 * 100
    speck = _rect_mask(100, 100, 0, 0, 3, 3)        # 0.0009 of page -> drop
    room = _rect_mask(100, 100, 10, 10, 40, 40)     # 0.09 -> keep
    blob = _rect_mask(100, 100, 0, 0, 90, 90)       # 0.81 -> drop
    keep = filter_by_area([speck, room, blob], page_area=page,
                          min_frac=0.005, max_frac=0.6)
    assert keep == [1]


def test_filter_by_area_rejects_bad_page():
    with pytest.raises(ValueError):
        filter_by_area([], page_area=0)


# --- ring + detection assembly --------------------------------------------
def test_bbox_to_ring_rectangle():
    assert bbox_to_ring([1, 2, 5, 8]) == [[1, 2], [5, 2], [5, 8], [1, 8]]


def test_masks_to_detections_shape_matches_inference_api():
    m = _rect_mask(50, 50, 10, 10, 30, 30)
    dets = masks_to_detections([m], scores=[0.87])
    assert len(dets) == 1
    d = dets[0]
    # same keys the canvas / accept-reject path expects
    for key in ("id", "label", "bbox", "polygon", "area", "confidence"):
        assert key in d
    assert d["label"] == "space"          # class-agnostic until the human labels it
    assert d["bbox"] == [10.0, 10.0, 30.0, 30.0]
    assert d["confidence"] == 0.87
    assert d["source"] == "sam2_zero_shot"


def test_masks_to_detections_prefers_supplied_ring():
    m = _rect_mask(50, 50, 10, 10, 30, 30)
    traced = [[10, 10], [30, 12], [28, 30], [11, 29]]
    dets = masks_to_detections([m], scores=[0.9], rings=[traced])
    assert dets[0]["polygon"] == [[10.0, 10.0], [30.0, 12.0], [28.0, 30.0], [11.0, 29.0]]


# --- graceful degradation without weights ---------------------------------
def test_run_returns_needs_weights_without_checkpoint(tmp_path):
    missing = tmp_path / "nope.pt"
    out = run_sam2_zero_shot("whatever.png", checkpoint=str(missing))
    assert out["status"] == "needs_weights"
    assert out["rooms"] == []


def test_weights_available_is_false_in_ci():
    # No SAM2 checkpoint is ever committed / present in CI.
    assert sam2_weights_available() is False
