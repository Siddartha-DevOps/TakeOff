"""Tests for the golden-set builder + promotion invariant (Phase 4)."""

import json
import struct

import pytest

from ml.eval.build_golden import (
    attach_predictions,
    build_golden_gt,
    default_symbol_classes,
    denormalize_ring,
    gt_sample,
    labels_to_gt,
    polygon_area,
    predictions_from_detections,
    ring_bbox,
)
from ml.eval.harness import evaluate
from ml.eval.promote import ACTIVE, CANDIDATE, plan_promotion

CLASS_NAMES = ["living", "bedroom", "door"]  # 2 spaces + 1 symbol


def _fake_png(path, w, h):
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    path.write_bytes(sig + struct.pack(">I", 13) + ihdr)


# --- geometry helpers ------------------------------------------------------
def test_denormalize_ring():
    assert denormalize_ring([[0.5, 0.5], [1.0, 1.0]], 200, 100) == [[100.0, 50.0], [200.0, 100.0]]


def test_ring_bbox_and_area():
    sq = [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert ring_bbox(sq) == [0, 0, 10, 10]
    assert polygon_area(sq) == 100.0


def test_default_symbol_classes():
    assert default_symbol_classes(CLASS_NAMES) == {"door"}


# --- GT extraction ---------------------------------------------------------
def test_labels_to_gt_splits_rooms_and_symbols():
    # one living-room square (class 0) + one door box (class 2), normalized coords
    text = "0 0 0 0.5 0 0.5 0.5 0 0.5\n2 0.1 0.1 0.2 0.1 0.2 0.2 0.1 0.2"
    gt = labels_to_gt(text, CLASS_NAMES, 100, 100)
    assert len(gt["rooms"]) == 1
    assert "door" in gt["symbols"] and len(gt["symbols"]["door"]) == 1
    assert gt["quantities"]["room_count"] == 1 and gt["quantities"]["symbol_count"] == 1
    assert gt["quantities"]["floor_area_px"] == pytest.approx(2500.0)  # 50x50 px


# --- predictions adapter ---------------------------------------------------
def test_predictions_from_detections_shape():
    dets = [
        {"label": "living", "polygon": [[0, 0], [50, 0], [50, 50], [0, 50]], "confidence": 0.9},
        {"label": "door", "bbox": [10, 10, 20, 20], "confidence": 0.8},
    ]
    pred = predictions_from_detections(dets, symbol_classes={"door"})
    assert len(pred["rooms"]) == 1
    assert pred["symbols"]["door"][0]["score"] == 0.8
    assert pred["symbols"]["door"][0]["geom"] == [10, 10, 20, 20]


# --- end-to-end: builder output is harness-valid, perfect preds pass gate --
def test_golden_roundtrip_perfect_predictions_passes_gate(tmp_path):
    ds = tmp_path / "dataset"
    (ds / "labels" / "val").mkdir(parents=True)
    (ds / "images" / "val").mkdir(parents=True)
    # two sheets, each: a room square + a door box
    for name in ("s0", "s1"):
        (ds / "labels" / "val" / f"{name}.txt").write_text(
            "0 0 0 0.5 0 0.5 0.5 0 0.5\n2 0.1 0.1 0.2 0.1 0.2 0.2 0.1 0.2")
        _fake_png(ds / "images" / "val" / f"{name}.png", 100, 100)

    samples = build_golden_gt(ds, CLASS_NAMES, split="val")
    assert len(samples) == 2

    # Synthesize perfect predictions from the GT (mirror rooms + score-1 boxes).
    preds = {}
    for s in samples:
        dets = [{"label": "living", "polygon": r, "confidence": 1.0} for r in s["rooms"]["gt"]]
        for cls, boxes in s["symbols"]["gt"].items():
            dets += [{"label": cls, "bbox": b, "confidence": 1.0} for b in boxes]
        preds[s["image_id"]] = predictions_from_detections(dets, symbol_classes={"door"})
    attach_predictions(samples, preds)

    report = evaluate(samples)
    assert report["gate_passed"] is True
    assert report["metrics"]["miou"] == pytest.approx(1.0)
    assert report["metrics"]["map"] == pytest.approx(1.0)
    assert report["metrics"]["measurement_error_pct"] == pytest.approx(0.0)


def test_golden_empty_predictions_fails_gate(tmp_path):
    ds = tmp_path / "dataset"
    (ds / "labels" / "val").mkdir(parents=True)
    (ds / "images" / "val").mkdir(parents=True)
    (ds / "labels" / "val" / "s0.txt").write_text("0 0 0 0.5 0 0.5 0.5 0 0.5")
    _fake_png(ds / "images" / "val" / "s0.png", 100, 100)

    samples = attach_predictions(build_golden_gt(ds, CLASS_NAMES), {})  # no preds
    report = evaluate(samples)
    assert report["gate_passed"] is False  # fails closed with no predictions


# --- promotion invariant ---------------------------------------------------
def test_plan_promotion_promotes_and_demotes_prior_active():
    existing = [{"version_string": "v1", "stage": ACTIVE},
                {"version_string": "v0", "stage": CANDIDATE}]
    plan = plan_promotion(existing, "v2", passed=True)
    assert plan["new_stage"] == ACTIVE and plan["demote"] == ["v1"] and plan["promoted"] is True


def test_plan_promotion_failed_stays_candidate_no_demotion():
    existing = [{"version_string": "v1", "stage": ACTIVE}]
    plan = plan_promotion(existing, "v2", passed=False)
    assert plan["new_stage"] == CANDIDATE and plan["demote"] == [] and plan["promoted"] is False
