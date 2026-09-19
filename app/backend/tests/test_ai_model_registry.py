import json
from pathlib import Path

import pytest

from ml.registry.metadata import (
    DeploymentStatus,
    ModelRecord,
    artifact_checksum,
    load_registry,
    verify_artifact,
    write_registry,
)


def _record(**overrides):
    values = dict(
        model_id="rooms", model_name="Room model", version="v1", task="segmentation",
        classes=["room"], artifact_location="weights.pt", checksum="a" * 64,
        dataset_version="dataset-v1", evaluation_version=None,
        created_at="2026-09-19T00:00:00Z", deployment_status=DeploymentStatus.CANDIDATE,
    )
    values.update(overrides)
    return ModelRecord(**values)


def test_model_registry_round_trip(tmp_path):
    path = write_registry([_record()], tmp_path / "models.json")
    assert load_registry(path) == [_record()]


def test_production_requires_evaluation_and_is_unique(tmp_path):
    assert "evaluation_version" in " ".join(_record(deployment_status=DeploymentStatus.PRODUCTION).validate())
    first = _record(version="v1", evaluation_version="eval-v1", deployment_status=DeploymentStatus.PRODUCTION)
    second = _record(model_id="rooms-2", version="v2", evaluation_version="eval-v2",
                     deployment_status=DeploymentStatus.PRODUCTION)
    with pytest.raises(ValueError, match="only one PRODUCTION"):
        write_registry([first, second], tmp_path / "models.json")


def test_artifact_checksum_verification(tmp_path):
    artifact = tmp_path / "weights.pt"
    artifact.write_bytes(b"checkpoint")
    record = _record(artifact_location=str(artifact), checksum=artifact_checksum(artifact))
    assert verify_artifact(record) is True
    artifact.write_bytes(b"changed")
    assert verify_artifact(record) is False


def test_committed_resplan_model_record_matches_checkpoint():
    backend = Path(__file__).resolve().parents[1]
    record = load_registry(backend / "ml" / "registry" / "model_registry.json")[0]
    assert record.deployment_status == DeploymentStatus.CANDIDATE
    assert record.evaluation_version is None
    # Model binaries are intentionally external to Git. Verify the pinned
    # checkpoint when present without requiring it in source-only CI.
    artifact = backend / record.artifact_location
    if artifact.exists():
        assert verify_artifact(record, artifact) is True
    assert record.classes == ["living", "bedroom", "bathroom", "kitchen", "balcony", "stair", "storage"]
