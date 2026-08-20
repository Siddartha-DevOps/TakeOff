"""Tests for annotation format converters (COCO / Label Studio / YOLO-seg)."""

from ml.annotation import (
    coco_to_yolo_seg,
    label_studio_to_rings,
    parse_yolo_seg_line,
    validate_ring,
    yolo_seg_line,
)

SQUARE = [[0, 0], [100, 0], [100, 100], [0, 100]]


def test_validate_ring():
    assert validate_ring(SQUARE) is True
    assert validate_ring([[0, 0], [1, 1]]) is False


def test_yolo_seg_line_roundtrip():
    line = yolo_seg_line(3, SQUARE, 100, 100)
    parsed = parse_yolo_seg_line(line)
    assert parsed is not None
    class_id, ring = parsed
    assert class_id == 3
    assert ring[1] == [1.0, 0.0]  # 100/100 normalized


def test_yolo_seg_line_degenerate_is_none():
    assert yolo_seg_line(0, [[0, 0], [1, 1]], 100, 100) is None


def test_parse_rejects_malformed():
    assert parse_yolo_seg_line("") is None
    assert parse_yolo_seg_line("0 0.1 0.2 0.3") is None            # <3 points
    assert parse_yolo_seg_line("0 0.1 0.2 0.3 0.4 0.5") is None    # 2.5 points (odd)


def test_coco_to_yolo_seg_maps_and_filters():
    coco = {
        "images": [{"id": 1, "file_name": "plan.png", "width": 200, "height": 100}],
        "annotations": [
            {"image_id": 1, "category_id": 7, "segmentation": [[0, 0, 200, 0, 200, 100, 0, 100]]},
            {"image_id": 1, "category_id": 99, "segmentation": [[0, 0, 10, 0, 10, 10]]},  # not in map -> dropped
        ],
    }
    out = coco_to_yolo_seg(coco, class_map={7: 0})
    assert "plan.png" in out
    assert len(out["plan.png"]) == 1
    class_id, ring = parse_yolo_seg_line(out["plan.png"][0])
    assert class_id == 0
    assert ring[1] == [1.0, 0.0]  # 200/200 -> 1.0


def test_label_studio_percentages_to_pixels():
    task = {
        "annotations": [{
            "result": [{
                "original_width": 200, "original_height": 100,
                "value": {"points": [[0, 0], [100, 0], [100, 100]], "polygonlabels": ["kitchen"]},
            }],
        }],
    }
    rings = label_studio_to_rings(task)
    assert len(rings) == 1
    label, ring = rings[0]
    assert label == "kitchen"
    # 100% width -> 200 px, 100% height -> 100 px
    assert ring[1] == [200.0, 0.0]
    assert ring[2] == [200.0, 100.0]
