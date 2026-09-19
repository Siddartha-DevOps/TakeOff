import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from ml.datasets.registry import DatasetRecord, load_registry, write_registry
from ml.datasets.validator import validate_dataset_index


def _record(**overrides):
    values = dict(
        dataset_id="rooms", version="v1", source="approved source",
        license="CC BY 4.0", provenance="owner and revision recorded",
        classes=["room"], image_count=3, annotation_count=3,
        train_count=1, validation_count=1, test_count=1,
        created_at="2026-09-19T00:00:00Z", checksum="a" * 64,
    )
    values.update(overrides)
    return DatasetRecord(**values)


def test_dataset_registry_round_trip(tmp_path):
    output = write_registry([_record()], tmp_path / "registry.json")
    loaded = load_registry(output)
    assert loaded == [_record()]


def test_dataset_registry_rejects_split_count_mismatch():
    assert "must equal image_count" in " ".join(_record(test_count=0).validate())


def test_committed_resplan_registry_matches_authoritative_manifest():
    backend = Path(__file__).resolve().parents[1]
    record = load_registry(backend / "ml" / "datasets" / "dataset_registry.json")[0]
    manifest = backend / "data" / "spaces_v1" / "spaces-v1.manifest.json"
    assert record.checksum == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert (record.train_count, record.validation_count, record.test_count) == (13053, 1622, 1621)


def _write_sample(root, split, name, project, *, label="0 0.1 0.1 0.9 0.1 0.9 0.9\n"):
    image = root / "images" / split / f"{name}.png"
    annotation = root / "labels" / split / f"{name}.txt"
    image.parent.mkdir(parents=True, exist_ok=True)
    annotation.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color=(len(name), 0, 0)).save(image)
    annotation.write_text(label)
    return {
        "sample_id": name, "project_id": project, "split": split,
        "image": image.relative_to(root).as_posix(),
        "annotation": annotation.relative_to(root).as_posix(),
        "annotation_format": "yolo_segmentation",
    }


def test_validator_passes_clean_project_split_dataset(tmp_path):
    samples = [
        _write_sample(tmp_path, "train", "a", "project-a"),
        _write_sample(tmp_path, "validation", "bb", "project-b"),
        _write_sample(tmp_path, "test", "ccc", "project-c"),
    ]
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"root": str(tmp_path), "classes": ["room"], "samples": samples}))
    report = validate_dataset_index(index, output_path=tmp_path / "report.json")
    assert report.valid is True
    assert report.split_counts == {"train": 1, "validation": 1, "test": 1}
    assert json.loads((tmp_path / "report.json").read_text())["valid"] is True


def test_validator_detects_corruption_invalid_geometry_duplicates_and_leakage(tmp_path):
    first = _write_sample(tmp_path, "train", "a", "same-project")
    second = _write_sample(tmp_path, "validation", "b", "same-project")
    (tmp_path / second["image"]).write_bytes((tmp_path / first["image"]).read_bytes())
    (tmp_path / second["annotation"]).write_text("2 0.1 0.1 0.2 0.2\n")
    third = _write_sample(tmp_path, "test", "c", "other-project")
    (tmp_path / third["image"]).write_bytes(b"not an image")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"root": str(tmp_path), "classes": ["room"],
                                 "samples": [first, second, third]}))
    report = validate_dataset_index(index)
    codes = {error["code"] for error in report.errors}
    assert {"project_leakage", "cross_split_duplicate", "corrupted_image", "invalid_annotation"} <= codes
    assert report.valid is False
