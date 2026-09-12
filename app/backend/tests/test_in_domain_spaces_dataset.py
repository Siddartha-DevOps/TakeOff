"""Tests for project splitting and the in-domain room dataset QA gate."""

import json

import pytest
from PIL import Image

from ml.datasets.prepare_in_domain_spaces import assign_project_splits
from ml.datasets.validate_in_domain_spaces import validate_in_domain_manifest


CLASSES = ["living", "bedroom", "bathroom", "kitchen", "balcony", "stair", "storage"]


def _config(tmp_path):
    config = {
        "dataset_name": "test-in-domain",
        "classes": CLASSES,
        "target_counts": {"train": 1, "val": 1, "test": 1, "golden": 1},
        "allowed_total_range": [4, 10],
        "allowed_golden_range": [1, 2],
        "minimum_image_width": 32,
        "minimum_image_height": 32,
        "minimum_instances_per_class": {name: 1 for name in CLASSES},
        "required_difficulty_tags": ["open_plan"],
        "minimum_sheets_per_difficulty_tag": 1,
        "maximum_mask_overlap_ratio": 0.02,
        "split_seed": "test-seed",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return config, path


def _label_text():
    rows = []
    for class_id in range(len(CLASSES)):
        x = 0.02 + class_id * 0.13
        rows.append(f"{class_id} {x} 0.1 {x + 0.08} 0.1 {x + 0.08} 0.2 {x} 0.2")
    return "\n".join(rows) + "\n"


def _sample(root, sample_id, project_id, split, *, approved=True, golden=False, image_seed=1):
    image_path = root / "images" / f"{sample_id}.png"
    label_path = root / "labels" / f"{sample_id}.txt"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (64, 64), "white")
    for index in range(8):
        image.putpixel(((image_seed * 7 + index * 5) % 63, index * 7), (0, 0, 0))
    image.save(image_path)
    label_path.write_text(_label_text(), encoding="utf-8")
    return {
        "sample_id": sample_id,
        "project_id": project_id,
        "sheet_id": f"sheet-{sample_id}",
        "split": split,
        "image_path": image_path.relative_to(root).as_posix(),
        "label_path": label_path.relative_to(root).as_posix(),
        "rights": {
            "status": "approved" if approved else "pending",
            "commercial_training": approved,
            "evidence_ref": f"rights/{project_id}" if approved else "",
        },
        "intake_eligibility": {
            "status": "eligible",
            "validated_at": "2026-09-01T09:30:00Z",
            "report_ref": "intake-report.json",
        },
        "annotation": {"status": "approved", "reviewers": ["reviewer-1"]},
        "difficulty_tags": ["open_plan"],
        "golden_approved": golden,
        "untouched": golden,
    }


def _manifest(tmp_path, samples):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"dataset_name": "test-in-domain", "samples": samples}), encoding="utf-8")
    return path


def test_split_assignment_keeps_all_project_pages_together(tmp_path):
    config, _ = _config(tmp_path)
    samples = [
        {"sample_id": "a-1", "project_id": "project-a", "intake_eligibility": {"status": "eligible"}},
        {"sample_id": "a-2", "project_id": "project-a", "intake_eligibility": {"status": "eligible"}},
        {"sample_id": "b-1", "project_id": "project-b", "golden_approved": True,
         "untouched": True, "intake_eligibility": {"status": "eligible"}},
    ]
    result = assign_project_splits(samples, config)
    assigned = {sample["sample_id"]: sample["split"] for sample in result["samples"]}
    assert assigned["a-1"] == assigned["a-2"]
    assert assigned["b-1"] == "golden"


def test_conflicting_explicit_project_splits_are_rejected(tmp_path):
    config, _ = _config(tmp_path)
    with pytest.raises(ValueError, match="multiple splits"):
        assign_project_splits([
            {"sample_id": "a", "project_id": "same", "split": "train",
             "intake_eligibility": {"status": "eligible"}},
            {"sample_id": "b", "project_id": "same", "split": "test",
             "intake_eligibility": {"status": "eligible"}},
        ], config)


def test_split_assignment_rejects_unverified_intake(tmp_path):
    config, _ = _config(tmp_path)
    with pytest.raises(ValueError, match="not intake-eligible"):
        assign_project_splits([{"sample_id": "a", "project_id": "project-a"}], config)


def test_empty_manifest_is_truthfully_not_ready(tmp_path):
    _, config_path = _config(tmp_path)
    audit = validate_in_domain_manifest(_manifest(tmp_path, []), config_path, tmp_path)
    assert audit.ready is False
    assert any("no rights-cleared" in error for error in audit.errors)
    assert audit.sheet_counts == {}


def test_complete_approved_project_split_manifest_passes(tmp_path):
    _, config_path = _config(tmp_path)
    samples = [
        _sample(tmp_path, "train", "project-train", "train", image_seed=1),
        _sample(tmp_path, "val", "project-val", "val", image_seed=2),
        _sample(tmp_path, "test", "project-test", "test", image_seed=3),
        _sample(tmp_path, "golden", "project-golden", "golden", golden=True, image_seed=4),
    ]
    audit = validate_in_domain_manifest(_manifest(tmp_path, samples), config_path, tmp_path)
    assert audit.ready is True, audit.errors
    assert audit.sheet_counts == {"train": 1, "val": 1, "test": 1, "golden": 1}
    assert all(audit.class_instances[name] == 4 for name in CLASSES)


def test_rights_and_golden_freeze_are_enforced(tmp_path):
    _, config_path = _config(tmp_path)
    samples = [
        _sample(tmp_path, "train", "project-train", "train", approved=False, image_seed=1),
        _sample(tmp_path, "val", "project-val", "val", image_seed=2),
        _sample(tmp_path, "test", "project-test", "test", image_seed=3),
        _sample(tmp_path, "golden", "project-golden", "golden", golden=False, image_seed=4),
    ]
    audit = validate_in_domain_manifest(_manifest(tmp_path, samples), config_path, tmp_path)
    assert audit.ready is False
    assert any("rights evidence" in error for error in audit.errors)
    assert any("golden samples" in error for error in audit.errors)


def test_project_leakage_and_overlapping_masks_are_rejected(tmp_path):
    _, config_path = _config(tmp_path)
    samples = [
        _sample(tmp_path, "train", "leaked-project", "train", image_seed=1),
        _sample(tmp_path, "val", "leaked-project", "val", image_seed=2),
        _sample(tmp_path, "test", "project-test", "test", image_seed=3),
        _sample(tmp_path, "golden", "project-golden", "golden", golden=True, image_seed=4),
    ]
    (tmp_path / samples[0]["label_path"]).write_text(
        "0 0.1 0.1 0.5 0.1 0.5 0.5 0.1 0.5\n"
        "1 0.2 0.2 0.6 0.2 0.6 0.6 0.2 0.6\n",
        encoding="utf-8",
    )
    audit = validate_in_domain_manifest(_manifest(tmp_path, samples), config_path, tmp_path)
    assert audit.ready is False
    assert any("leaks across splits" in error for error in audit.errors)
    assert any("room masks overlap" in error for error in audit.errors)
