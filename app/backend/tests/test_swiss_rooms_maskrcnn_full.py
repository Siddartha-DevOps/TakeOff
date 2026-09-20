import gzip
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from ml.datasets import adapt_swiss_rooms_maskrcnn_full as adapter
from ml.training.maskrcnn_rooms import CocoRLEMaskDataset


TRANSFORM = {
    "image_size_px": [100, 100], "source_bounds_m": [0.0, 0.0, 8.0, 8.0],
    "padding_m": 1.0, "pixels_per_metre": 10,
}


def _room(identifier, class_name="bedroom", geometry=None):
    return {
        "geometry_id": identifier, "target_family": "spaces",
        "target_class": class_name,
        "target_class_id": list(adapter.ROOM_CLASSES).index(class_name) + 1,
        "mapping_state": "TRAIN", "excluded": False,
        "geometry_wkt_metric": geometry or "POLYGON ((1 1, 7 1, 7 7, 1 7, 1 1))",
    }


def _floor(tmp_path, split, floor_id, building, rooms):
    source = tmp_path / "frozen" / split / floor_id
    source.mkdir(parents=True)
    Image.new("RGB", (100, 100), "white").save(source / "image.png")
    Image.new("I;16", (100, 100), 0).save(source / "room_instance.png")
    (source / "metadata.json").write_text(json.dumps({"transform": TRANSFORM}))
    with gzip.GzipFile(filename="", mode="wb", fileobj=(source / "supervision.json.gz").open("wb"), mtime=0) as handle:
        handle.write(json.dumps(rooms, sort_keys=True).encode())
    image_sha = hashlib.sha256((source / "image.png").read_bytes()).hexdigest()
    return {
        "floor_key": floor_id, "site_id": "site", "building_id": building,
        "building_key": building, "plan_id": f"plan-{floor_id}", "floor_id": floor_id,
        "split": split, "rendered_input_path": str(source / "image.png"),
        "output_hashes_sha256": {"image.png": image_sha},
    }


def _manifest(tmp_path, monkeypatch, rows, *, duplicate_leakage=0):
    counts = {split: sum(row["split"] == split for row in rows) for split in adapter.SPLITS}
    value = {
        "dataset": {"training_dataset_version": "test-v1", "conversion_version": "conversion-v1"},
        "summary": {
            "eligible_floors_by_split": counts,
            "duplicate_relationships_crossing_splits": duplicate_leakage,
            "duplicate_connected_clusters_crossing_splits": 0,
        },
        "eligible_floors": rows,
        "exclusions": [{"floor_id": floor} for floor in sorted(adapter.EXCLUDED_FLOORS)],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value, sort_keys=True))
    monkeypatch.setattr(adapter, "SOURCE_MANIFEST_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(adapter, "EXPECTED_FLOORS", len(rows))
    return path


def _three_floors(tmp_path):
    hole = "POLYGON ((1 1, 7 1, 7 7, 1 7, 1 1), (3 3, 5 3, 5 5, 3 5, 3 3))"
    return [
        _floor(tmp_path, "train", "1", "building-a", [_room("room-1", geometry=hole)]),
        _floor(tmp_path, "val", "2", "building-b", []),
        _floor(tmp_path, "test", "3", "building-c", [_room("room-3", "shaft")]),
    ]


def test_full_adapter_preserves_holes_negatives_splits_and_is_deterministic(tmp_path, monkeypatch):
    manifest_path = _manifest(tmp_path, monkeypatch, _three_floors(tmp_path))
    output = tmp_path / "adapter"
    first = adapter.build_full_adapter(manifest_path, output)
    floor_paths = sorted((output / "annotations").rglob("*.json"))
    mtimes = {path: path.stat().st_mtime_ns for path in floor_paths}
    second = adapter.build_full_adapter(manifest_path, output)
    assert first["complete"] and second["complete"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert second["processed_now"] == 0 and second["outputs_written_now"] == 0
    assert {path: path.stat().st_mtime_ns for path in floor_paths} == mtimes
    full = json.loads(Path(first["manifest_path"]).read_text())
    assert full["summary"]["floor_count"] == 3
    assert full["summary"]["authoritative_instance_count"] == 2
    assert full["summary"]["converted_instance_count"] == 2
    assert full["summary"]["hole_instance_count"] == 1
    assert full["summary"]["intentional_negative_floor_count"] == 1
    assert full["summary"]["building_leakage_count"] == 0
    shard = json.loads((output / "annotations" / "train" / "site__building-a__plan-1__1.json").read_text())
    assert shard["annotations"][0]["interior_ring_count"] == 1
    mask = adapter.decode_uncompressed_rle(shard["annotations"][0]["segmentation"])
    assert mask[50, 50] == 0
    dataset = CocoRLEMaskDataset(first["manifest_path"], output / "images")
    assert len(dataset) == 3 and dataset.sharded is True


def test_resume_after_interruption_uses_durable_checkpoint(tmp_path, monkeypatch):
    rows = _three_floors(tmp_path)
    source = _manifest(tmp_path, monkeypatch, rows)
    output = tmp_path / "adapter"
    partial = adapter.build_full_adapter(source, output, max_floors=1)
    assert partial["complete"] is False
    assert partial["status_counts"] == {"pending": 2, "succeeded": 1}
    resumed = adapter.build_full_adapter(source, output)
    assert resumed["complete"] is True
    assert resumed["processed_now"] == 2
    assert resumed["summary"]["floor_count"] == 3


def test_existing_output_mismatch_fails_instead_of_rewriting(tmp_path, monkeypatch):
    rows = [_floor(tmp_path, "train", "1", "building-a", [_room("one")])]
    source = _manifest(tmp_path, monkeypatch, rows)
    output = tmp_path / "adapter"
    adapter.build_full_adapter(source, output)
    annotation = next((output / "annotations").rglob("*.json"))
    annotation.write_text("corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        adapter.build_full_adapter(source, output)


def test_rejected_instance_is_explicit_and_reconciled(tmp_path, monkeypatch):
    invalid = "POLYGON ((1 1, 1 1, 1 1, 1 1))"
    rows = [_floor(tmp_path, "train", "1", "building-a", [_room("bad", geometry=invalid)])]
    source = _manifest(tmp_path, monkeypatch, rows)
    result = adapter.build_full_adapter(source, tmp_path / "adapter")
    assert result["summary"]["authoritative_instance_count"] == 1
    assert result["summary"]["converted_instance_count"] == 0
    assert result["summary"]["rejected_instance_count"] == 1
    published = json.loads(Path(result["manifest_path"]).read_text())
    assert published["rejected_instances"][0]["source_instance_id"] == "bad"


def test_building_leakage_is_rejected(tmp_path, monkeypatch):
    rows = [
        _floor(tmp_path, "train", "1", "same-building", [_room("one")]),
        _floor(tmp_path, "val", "2", "same-building", [_room("two")]),
    ]
    source = _manifest(tmp_path, monkeypatch, rows)
    with pytest.raises(ValueError, match="split leakage"):
        adapter.build_full_adapter(source, tmp_path / "adapter")


def test_frozen_duplicate_cluster_leakage_is_rejected(tmp_path, monkeypatch):
    rows = [_floor(tmp_path, "train", "1", "building-a", [_room("one")])]
    source = _manifest(tmp_path, monkeypatch, rows, duplicate_leakage=1)
    with pytest.raises(ValueError, match="split leakage"):
        adapter.build_full_adapter(source, tmp_path / "adapter")


def test_source_manifest_and_exclusions_are_immutable_guards(tmp_path, monkeypatch):
    rows = [_floor(tmp_path, "train", "5593", "building-a", [_room("one")])]
    source = _manifest(tmp_path, monkeypatch, rows)
    with pytest.raises(ValueError, match="excluded source-exception"):
        adapter.build_full_adapter(source, tmp_path / "adapter")
