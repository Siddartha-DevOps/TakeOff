"""Tests for rights/provenance/de-identification intake eligibility."""

import hashlib
import json

from PIL import Image

from ml.datasets.validate_in_domain_intake import validate_intake_manifest


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sample(tmp_path, sample_id="sheet-a", project_id="project-a", *, seed=1):
    path = tmp_path / f"{sample_id}.png"
    image = Image.new("RGB", (64, 64), "white")
    image.putpixel((seed, seed), (0, 0, 0))
    image.save(path)
    digest = _sha(path)
    return {
        "sample_id": sample_id,
        "project_id": project_id,
        "source_owner": "Example owner",
        "permission_basis": "customer_consent",
        "commercial_ml_training_allowed": True,
        "redistribution_allowed": False,
        "confidentiality_restrictions": "restricted training access",
        "deidentification_required": False,
        "deidentification_status": "not_required",
        "deidentification": {
            "performed_by": "",
            "reviewed_by": "",
            "completed_at": None,
            "redaction_log_ref": "",
            "geometry_preserved": True,
        },
        "drawing_type": "residential_single_family",
        "discipline": "architectural_floor_plan",
        "revision": "A",
        "page_sheet_number": "A101",
        "source_file_sha256": digest,
        "eligible_file_sha256": digest,
        "source_path": path.name,
        "eligible_path": path.name,
        "intake_date": "2026-09-01",
        "rights": {
            "status": "approved",
            "evidence_ref": "restricted-rights-register/agreement-1",
            "verified_by": "rights-reviewer",
            "verified_at": "2026-09-01T09:00:00Z",
        },
        "provenance": {
            "status": "recorded",
            "source_reference": "restricted-intake/source-1",
            "recorded_by": "intake-reviewer",
            "recorded_at": "2026-09-01T09:10:00Z",
        },
        "file_integrity": {"status": "passed", "verified_at": "2026-09-01T09:15:00Z"},
    }


def _manifest(tmp_path, samples):
    path = tmp_path / "intake.json"
    path.write_text(json.dumps({"schema_version": 2, "samples": samples}), encoding="utf-8")
    return path


def test_complete_intake_is_eligible_even_when_redistribution_is_forbidden(tmp_path):
    audit = validate_intake_manifest(_manifest(tmp_path, [_sample(tmp_path)]), tmp_path)
    assert audit.ready_for_annotation is True
    assert audit.counts["eligible"] == 1
    assert audit.counts["annotated"] == 0
    assert audit.sheets[0].status == "eligible"


def test_rights_blocker_is_reported(tmp_path):
    sample = _sample(tmp_path)
    sample["commercial_ml_training_allowed"] = False
    sample["rights"]["evidence_ref"] = ""
    audit = validate_intake_manifest(_manifest(tmp_path, [sample]), tmp_path)
    assert audit.ready_for_annotation is False
    assert audit.blockers["rights"] == 1
    assert "rights" in audit.sheets[0].blockers


def test_provenance_and_unknown_project_are_reported_separately(tmp_path):
    sample = _sample(tmp_path)
    sample["project_id"] = ""
    sample["provenance"]["source_reference"] = ""
    audit = validate_intake_manifest(_manifest(tmp_path, [sample]), tmp_path)
    assert audit.blockers["provenance"] == 1
    assert audit.blockers["project_leakage_risk"] == 1


def test_required_deidentification_needs_distinct_reviewed_derivative(tmp_path):
    sample = _sample(tmp_path)
    sample["deidentification_required"] = True
    sample["deidentification_status"] = "pending"
    audit = validate_intake_manifest(_manifest(tmp_path, [sample]), tmp_path)
    assert audit.blockers["deidentification"] == 1
    reasons = audit.sheets[0].blockers["deidentification"]
    assert any("separately hashed derivative" in reason for reason in reasons)


def test_corrupt_or_hash_mismatched_file_is_reported(tmp_path):
    sample = _sample(tmp_path)
    sample["eligible_file_sha256"] = "0" * 64
    audit = validate_intake_manifest(_manifest(tmp_path, [sample]), tmp_path)
    assert audit.blockers["corrupted"] == 1
    assert any("SHA-256" in reason for reason in audit.sheets[0].blockers["corrupted"])


def test_duplicate_across_projects_is_duplicate_and_leakage_risk(tmp_path):
    first = _sample(tmp_path, "same-file", "project-a", seed=1)
    second = dict(first)
    second.update({"sample_id": "same-file-copy", "project_id": "project-b"})
    audit = validate_intake_manifest(_manifest(tmp_path, [first, second]), tmp_path)
    assert audit.blockers["duplicate"] == 2
    assert audit.blockers["project_leakage_risk"] == 2
    assert all(sheet.status == "blocked" for sheet in audit.sheets)


def test_conflicting_requested_splits_for_one_project_are_blocked(tmp_path):
    first = _sample(tmp_path, "first", "project-a", seed=1)
    second = _sample(tmp_path, "second", "project-a", seed=2)
    first["requested_split"] = "train"
    second["requested_split"] = "golden"
    audit = validate_intake_manifest(_manifest(tmp_path, [first, second]), tmp_path)
    assert audit.blockers["project_leakage_risk"] == 2
