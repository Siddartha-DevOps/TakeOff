import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from ml.datasets import adapt_swiss_rooms_yolo as adapter


TRANSFORM = {
    "image_size_px": [100, 100],
    "source_bounds_m": [0.0, 0.0, 8.0, 8.0],
    "padding_m": 1.0,
    "pixels_per_metre": 10,
}


def _room(geometry_id, class_name, mask_id, wkt):
    return {
        "geometry_id": geometry_id,
        "target_family": "spaces",
        "target_class": class_name,
        "target_class_id": mask_id,
        "mapping_state": "TRAIN",
        "excluded": False,
        "geometry_wkt_metric": wkt,
    }


def _floor(tmp_path, split, floor_id, building, rooms):
    source = tmp_path / "source" / split / floor_id
    source.mkdir(parents=True)
    Image.new("RGB", (100, 100), "white").save(source / "image.png")
    Image.new("I;16", (100, 100), 0).save(source / "room_instance.png")
    (source / "metadata.json").write_text(json.dumps({"transform": TRANSFORM}))
    with gzip.GzipFile(filename="", mode="wb", fileobj=(source / "supervision.json.gz").open("wb"), mtime=0) as handle:
        handle.write(json.dumps(rooms, sort_keys=True).encode())
    image_sha = hashlib.sha256((source / "image.png").read_bytes()).hexdigest()
    return {
        "floor_key": floor_id,
        "site_id": "site",
        "building_id": building,
        "plan_id": f"plan-{floor_id}",
        "floor_id": floor_id,
        "building_key": building,
        "split": split,
        "rendered_input_path": str(source / "image.png"),
        "output_hashes_sha256": {"image.png": image_sha},
    }


def _manifest(tmp_path, rows):
    value = {
        "dataset": {
            "training_dataset_version": "test-dataset",
            "conversion_version": "test-conversion",
        },
        "summary": {
            "eligible_floors_by_split": dict(__import__("collections").Counter(row["split"] for row in rows)),
            "duplicate_relationships_crossing_splits": 0,
            "duplicate_connected_clusters_crossing_splits": 0,
        },
        "eligible_floors": rows,
        "exclusions": [{"floor_id": value} for value in sorted(adapter.EXPECTED_EXCLUSIONS)],
    }
    path = tmp_path / "training-manifest.json"
    path.write_text(json.dumps(value, sort_keys=True))
    adapter.EXPECTED_SOURCE_MANIFEST_SHA256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return path


def test_polygon_conversion_is_deterministic_and_normalized():
    wkt = "POLYGON ((1 1, 4 1, 4 4, 1 4, 1 1))"
    first = adapter.polygon_to_yolo(wkt, class_id=3, transform=TRANSFORM)
    second = adapter.polygon_to_yolo(wkt, class_id=3, transform=TRANSFORM)
    assert first == second and first[1] is None
    values = [float(value) for value in first[0].split()[1:]]
    assert values and all(0 <= value <= 1 for value in values)


@pytest.mark.parametrize(
    "wkt,reason",
    [
        ("POLYGON ((1 1, 1 1, 1 1, 1 1))", "INVALID_GEOMETRY"),
        ("MULTIPOLYGON (((1 1, 2 1, 2 2, 1 2, 1 1)))", "UNREPRESENTABLE_GEOMETRY_TYPE:MultiPolygon"),
        ("POLYGON ((0 0, 5 0, 5 5, 0 5, 0 0), (1 1, 2 1, 2 2, 1 2, 1 1))", "UNREPRESENTABLE_INTERIOR_RINGS"),
    ],
)
def test_unrepresentable_polygons_are_rejected(wkt, reason):
    line, actual = adapter.polygon_to_yolo(wkt, class_id=0, transform=TRANSFORM)
    assert line is None and actual == reason


def test_adapter_preserves_instances_negatives_splits_and_is_deterministic(tmp_path):
    room_wkt_1 = "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))"
    room_wkt_2 = "POLYGON ((4 4, 6 4, 6 6, 4 6, 4 4))"
    rows = [
        _floor(tmp_path, "train", "1", "building-a", [
            _room("one", "bedroom", 1, room_wkt_1),
            _room("two", "bedroom", 1, room_wkt_2),
        ]),
        _floor(tmp_path, "val", "2", "building-b", []),
        _floor(tmp_path, "test", "3", "building-c", [
            _room("three", "shaft", 14, room_wkt_1),
        ]),
    ]
    source_manifest = _manifest(tmp_path, rows)
    output = tmp_path / "adapter"
    first = adapter.build_adapter(source_manifest, output)
    stable_outputs = [
        output / "data.yaml",
        output / "groups.json",
        output / "labels" / "train" / "site__building-a__plan-1__1.txt",
        output / "labels" / "val" / "site__building-b__plan-2__2.txt",
        output / "labels" / "test" / "site__building-c__plan-3__3.txt",
    ]
    mtimes = {path: path.stat().st_mtime_ns for path in stable_outputs}
    second = adapter.build_adapter(source_manifest, output)
    assert first["adapter_manifest_sha256"] == second["adapter_manifest_sha256"]
    assert {path: path.stat().st_mtime_ns for path in stable_outputs} == mtimes
    manifest = json.loads(Path(first["adapter_manifest_path"]).read_text())
    assert manifest["summary"]["authoritative_room_instance_count"] == 3
    assert manifest["summary"]["generated_yolo_instance_count"] == 3
    assert manifest["summary"]["intentional_negative_label_count"] == 1
    assert manifest["summary"]["building_leakage_count"] == 0
    assert manifest["summary"]["excluded_floors_present"] is False
    train_label = output / "labels" / "train" / "site__building-a__plan-1__1.txt"
    assert len(train_label.read_text().splitlines()) == 2
    negative_label = output / "labels" / "val" / "site__building-b__plan-2__2.txt"
    assert negative_label.read_bytes() == b""
    assert (output / "data.yaml").is_file()


def test_rejected_instance_reconciles_without_fabrication(tmp_path):
    rows = [_floor(tmp_path, "train", "1", "building-a", [
        _room("multi", "bedroom", 1, "MULTIPOLYGON (((1 1, 2 1, 2 2, 1 2, 1 1)))")
    ])]
    source_manifest = _manifest(tmp_path, rows)
    result = adapter.build_adapter(source_manifest, tmp_path / "adapter")
    manifest = json.loads(Path(result["adapter_manifest_path"]).read_text())
    assert manifest["summary"]["authoritative_room_instance_count"] == 1
    assert manifest["summary"]["generated_yolo_instance_count"] == 0
    assert manifest["summary"]["rejected_instance_count"] == 1
    assert manifest["rejected_instances"][0]["source_instance"] == "multi"


def test_source_manifest_checksum_is_mandatory(tmp_path):
    path = _manifest(tmp_path, [])
    adapter.EXPECTED_SOURCE_MANIFEST_SHA256 = "0" * 64
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        adapter.build_adapter(path, tmp_path / "adapter")
