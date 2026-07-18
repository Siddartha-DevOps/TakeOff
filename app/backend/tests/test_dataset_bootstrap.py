"""Tests for the public floor-plan dataset bootstrap (cold-start training seed)."""

import pytest

from ml.datasets.bootstrap_public import (
    SPACE_CLASSES,
    build_label_lines,
    build_dataset_from_public,
    class_id,
    data_yaml_text,
    normalize_ring,
    polygon_to_seg_line,
    remap_label,
)

SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10]]


# --- label remap -----------------------------------------------------------
def test_remap_known_categories():
    assert remap_label("LivingRoom") == "living"
    assert remap_label("Bath") == "bathroom"
    assert remap_label("Kitchen") == "kitchen"
    assert remap_label("Balcony") == "balcony"


def test_remap_is_case_and_separator_insensitive():
    assert remap_label("living room") == "living"
    assert remap_label("living_room") == "living"
    assert remap_label("LIVINGROOM") == "living"


def test_remap_drops_out_of_vocab():
    assert remap_label("Wall") is None
    assert remap_label("Window") is None
    assert remap_label("Undefined") is None


def test_remap_custom_mapping():
    assert remap_label("Chambre", {"Chambre": "bedroom"}) == "bedroom"


# --- class ids -------------------------------------------------------------
def test_class_id_matches_index():
    for i, name in enumerate(SPACE_CLASSES):
        assert class_id(name) == i


def test_class_id_unknown_raises():
    with pytest.raises(ValueError):
        class_id("garage")  # maps to 'storage'; the class name itself is invalid


# --- normalization ---------------------------------------------------------
def test_normalize_ring_scales_and_clamps():
    coords = normalize_ring([[0, 0], [200, 100]], img_w=100, img_h=100)
    # (0,0) -> 0,0 ; (200,100) clamps x to 1.0, y to 1.0
    assert coords == [0.0, 0.0, 1.0, 1.0]


def test_normalize_ring_rejects_bad_dims():
    with pytest.raises(ValueError):
        normalize_ring(SQUARE, 0, 10)


# --- seg lines -------------------------------------------------------------
def test_seg_line_format():
    line = polygon_to_seg_line("Kitchen", SQUARE, 100, 100)
    parts = line.split()
    assert parts[0] == str(class_id("kitchen"))
    # 4 points -> 8 normalized coords after the class id
    assert len(parts) == 1 + 8
    assert parts[1:3] == ["0", "0"]  # 0/100 -> 0


def test_seg_line_dropped_class_is_none():
    assert polygon_to_seg_line("Wall", SQUARE, 100, 100) is None


def test_seg_line_degenerate_polygon_is_none():
    assert polygon_to_seg_line("Kitchen", [[0, 0], [1, 1]], 100, 100) is None


def test_build_label_lines_skips_dropped_and_degenerate():
    rooms = [
        ("Kitchen", SQUARE),                 # kept
        ("Wall", SQUARE),                    # dropped (out of vocab)
        ("Bedroom", [[0, 0], [1, 1]]),       # dropped (degenerate)
        ("LivingRoom", SQUARE),              # kept
    ]
    lines = build_label_lines(rooms, 100, 100)
    assert len(lines) == 2
    assert lines[0].startswith(str(class_id("kitchen")))
    assert lines[1].startswith(str(class_id("living")))


# --- data.yaml -------------------------------------------------------------
def test_data_yaml_lists_all_classes():
    text = data_yaml_text("/data/spaces")
    assert f"nc: {len(SPACE_CLASSES)}" in text
    for i, name in enumerate(SPACE_CLASSES):
        assert f"  {i}: {name}" in text


# --- end-to-end dataset write (no cv2: images omitted) --------------------
def test_build_dataset_writes_labels_and_yaml(tmp_path):
    samples = [
        {"image_id": "plan_0", "image": None, "width": 100, "height": 100,
         "rooms": [("Kitchen", SQUARE), ("Bedroom", SQUARE)]},
        {"image_id": "plan_1", "image": None, "width": 100, "height": 100,
         "rooms": [("Wall", SQUARE)]},  # all rooms dropped -> skipped image
        {"image_id": "plan_2", "image": None, "width": 100, "height": 100,
         "rooms": [("LivingRoom", SQUARE)]},
    ]
    summary = build_dataset_from_public(samples, tmp_path, val_every=2)

    assert summary["dropped_images"] == 1
    assert summary["rooms"] == 3  # kitchen+bedroom from plan_0, living from plan_2
    assert (tmp_path / "data.yaml").exists()
    # plan_0 is idx 0 -> val; plan_2 is idx 2 -> val (val_every=2)
    assert (tmp_path / "labels/val/plan_0.txt").exists()
    assert (tmp_path / "labels/val/plan_2.txt").exists()
    assert not (tmp_path / "labels/train/plan_1.txt").exists()  # dropped
    # two label lines in plan_0
    assert len((tmp_path / "labels/val/plan_0.txt").read_text().splitlines()) == 2
