"""Tests for the Model 2 symbol/object dataset scaffolding (pure functions)."""

import pytest

from training.objects_dataset import SYMBOL_CLASSES, bbox_to_yolo_line, build_objects_yaml


def test_symbol_classes_are_distinct_from_segmentation_symbol_set():
    """Model 2's detection classes must not silently collapse into Model 1's set."""
    from ai.detect_symbols import SYMBOL_CLASS_NAMES

    assert set(SYMBOL_CLASSES) != set(SYMBOL_CLASS_NAMES.values())
    assert len(SYMBOL_CLASSES) == 18


def test_bbox_to_yolo_line_centers_and_normalizes():
    # A 100x200 box centered in a 200x400 image -> cx=cy=0.5, w=0.5, h=0.5
    line = bbox_to_yolo_line(3, 50, 100, 150, 300, img_w=200, img_h=400)
    cls_id, cx, cy, bw, bh = line.split()
    assert cls_id == "3"
    assert (float(cx), float(cy), float(bw), float(bh)) == pytest.approx((0.5, 0.5, 0.5, 0.5))


def test_bbox_to_yolo_line_rejects_zero_size_image():
    with pytest.raises(ValueError):
        bbox_to_yolo_line(0, 0, 0, 10, 10, img_w=0, img_h=100)


def test_build_objects_yaml_writes_expected_yaml(tmp_path):
    out = build_objects_yaml(tmp_path)

    assert out == tmp_path / "objects.yaml"
    text = out.read_text()
    assert f"path: {tmp_path}" in text
    assert "train: images/train" in text
    assert "val: images/val" in text
    assert f"nc: {len(SYMBOL_CLASSES)}" in text
    for i, name in enumerate(SYMBOL_CLASSES):
        assert f"  {i}: {name}" in text
