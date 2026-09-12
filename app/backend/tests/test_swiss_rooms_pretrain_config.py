import gzip
import hashlib
import json
from pathlib import Path

from PIL import Image

from ml.training.validate_swiss_rooms_pretrain import EXPECTED_CLASSES, validate_plan


def _write_fixture(tmp_path: Path, *, invalid_mask=False):
    rows = []
    for split, floor_id, building, mask_id in (
        ("train", "1", "a", 1),
        ("val", "2", "b", 14),
        ("test", "3", "c", 2),
    ):
        out = tmp_path / split / floor_id
        out.mkdir(parents=True)
        Image.new("RGB", (8, 8), "white").save(out / "image.png")
        mask = Image.new("L", (8, 8), mask_id)
        if split == "train":
            pixels = mask.load()
            for index, value in enumerate(range(1, 15)):
                pixels[index % 8, index // 8] = value
            if invalid_mask:
                pixels[7, 7] = 15
        mask.save(out / "room_semantic.png")
        with gzip.open(out / "supervision.json.gz", "wt", encoding="utf-8") as handle:
            json.dump([{"target_family": "spaces", "mapping_state": "TRAIN", "excluded": False}], handle)
        rows.append({
            "floor_key": floor_id,
            "floor_id": floor_id,
            "building_key": building,
            "split": split,
            "rendered_input_path": str(out / "image.png"),
            "room_label_path": str(out / "room_semantic.png"),
        })
    manifest = {
        "summary": {
            "eligible_floors_by_split": {"train": 1, "val": 1, "test": 1},
            "duplicate_relationships_crossing_splits": 0,
            "duplicate_connected_clusters_crossing_splits": 0,
        },
        "eligible_floors": rows,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    classes = [
        {"training_id": index, "mask_id": index + 1, "name": name}
        for index, name in enumerate(EXPECTED_CLASSES)
    ]
    config = {
        "dataset": {
            "manifest_path": str(manifest_path),
            "manifest_sha256": digest,
            "split_counts": {"train": 1, "val": 1, "test": 1},
            "excluded_floor_ids": ["5593", "5639", "5640"],
            "label_contract": {"status": "ADAPTER_REQUIRED"},
        },
        "taxonomy": {"classes": classes},
        "model": {"initialization_weights": "missing.pt", "initialization_sha256": "none"},
        "training": {},
        "evaluation": {},
        "artifacts": {},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def test_valid_frozen_data_is_blocked_only_by_missing_yolo_adapter(tmp_path):
    report = validate_plan(_write_fixture(tmp_path))
    assert report["config_parsed"] is True
    assert report["manifest_sha_verified"] is True
    assert report["missing_selected_assets"] == 0
    assert report["building_leakage_count"] == 0
    assert report["adapter_ready"] is False
    assert report["ready"] is False
    assert any("instance polygon TXT" in error for error in report["errors"])


def test_invalid_mask_class_is_rejected(tmp_path):
    report = validate_plan(_write_fixture(tmp_path, invalid_mask=True))
    assert report["invalid_masks"] == 1
    assert any("invalid class IDs" in error for error in report["errors"])


def test_manifest_hash_mismatch_is_rejected(tmp_path):
    config_path = _write_fixture(tmp_path)
    config = json.loads(config_path.read_text())
    config["dataset"]["manifest_sha256"] = "0" * 64
    config_path.write_text(json.dumps(config))
    report = validate_plan(config_path)
    assert report["manifest_sha_verified"] is False
    assert any("SHA-256 mismatch" in error for error in report["errors"])
