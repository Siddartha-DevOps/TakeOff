"""Tests for the strict spaces-v1 data-quality gate."""

import json

from ml.datasets.validate_spaces import validate_spaces_dataset


LABEL = "0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9\n"


def _dataset(tmp_path, *, duplicate=False, groups=None):
    for split in ("train", "val"):
        (tmp_path / "images" / split).mkdir(parents=True)
        (tmp_path / "labels" / split).mkdir(parents=True)
        content = b"same" if duplicate else split.encode()
        (tmp_path / "images" / split / f"{split}.png").write_bytes(content)
        (tmp_path / "labels" / split / f"{split}.txt").write_text(LABEL)
    (tmp_path / "data.yaml").write_text(
        f"path: {tmp_path}\ntrain: images/train\nval: images/val\nnc: 1\nnames: [space]\n"
    )
    if groups is not None:
        (tmp_path / "groups.json").write_text(json.dumps(groups))
    return tmp_path / "data.yaml"


def test_valid_dataset_builds_deterministic_manifest(tmp_path):
    data = _dataset(tmp_path, groups={"train": "project-a", "val": "project-b"})
    first = validate_spaces_dataset(data, require_groups=True, expected_classes=["space"])
    second = validate_spaces_dataset(data, require_groups=True, expected_classes=["space"])

    assert first.ready is True
    assert first.split_counts == {"train": 1, "val": 1}
    assert first.polygon_counts == {"train": 1, "val": 1}
    assert first.manifest["dataset_id"] == second.manifest["dataset_id"]


def test_cross_split_duplicate_is_blocked(tmp_path):
    audit = validate_spaces_dataset(_dataset(tmp_path, duplicate=True))
    assert audit.ready is False
    assert any("identical image" in error for error in audit.errors)


def test_project_group_leakage_is_blocked(tmp_path):
    data = _dataset(tmp_path, groups={"train": "same-project", "val": "same-project"})
    audit = validate_spaces_dataset(data, require_groups=True)
    assert any("appears across splits" in error for error in audit.errors)


def test_bad_polygon_and_missing_pair_are_blocked(tmp_path):
    data = _dataset(tmp_path)
    (tmp_path / "labels" / "train" / "train.txt").write_text("0 0.1 0.1 0.2 0.2\n")
    (tmp_path / "labels" / "val" / "val.txt").unlink()
    audit = validate_spaces_dataset(data)
    assert audit.ready is False
    assert any("at least 3" in error for error in audit.errors)
    assert any("missing label" in error for error in audit.errors)


def test_wrong_taxonomy_is_blocked_when_requested(tmp_path):
    audit = validate_spaces_dataset(_dataset(tmp_path), expected_classes=["room"])
    assert any("class taxonomy" in error for error in audit.errors)


def test_orphan_label_is_blocked(tmp_path):
    data = _dataset(tmp_path)
    (tmp_path / "labels" / "train" / "deleted-image.txt").write_text(LABEL)
    audit = validate_spaces_dataset(data)
    assert any("orphan label" in error for error in audit.errors)
