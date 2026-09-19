"""File-backed model metadata registry used alongside the operational DB index.

The database ``ModelVersion`` row remains the queryable promotion control.  This
artifact registry records the richer reproducibility contract (dataset,
checksum, taxonomy, evaluation version) without making weights part of Git.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DeploymentStatus(str, Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    CANDIDATE = "CANDIDATE"
    PRODUCTION = "PRODUCTION"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    model_name: str
    version: str
    task: str
    classes: list[str]
    artifact_location: str
    checksum: str
    dataset_version: str
    evaluation_version: str | None
    created_at: str
    deployment_status: DeploymentStatus = DeploymentStatus.EXPERIMENTAL
    architecture: str | None = None
    input_resolution: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        for name in ("model_id", "model_name", "version", "task", "artifact_location", "dataset_version"):
            if not str(getattr(self, name)).strip():
                errors.append(f"{name} is required")
        if not self.classes or len(self.classes) != len(set(self.classes)):
            errors.append("classes must be a non-empty, unique ordered list")
        if not SHA256_RE.fullmatch(self.checksum.lower()):
            errors.append("checksum must be a SHA-256 hex digest")
        try:
            datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            errors.append("created_at must be ISO-8601")
        if self.deployment_status == DeploymentStatus.PRODUCTION and not self.evaluation_version:
            errors.append("PRODUCTION models require an evaluation_version")
        return errors

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["deployment_status"] = self.deployment_status.value
        return payload


def artifact_checksum(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(record: ModelRecord, path: str | Path | None = None) -> bool:
    artifact = Path(path or record.artifact_location)
    return artifact.is_file() and artifact_checksum(artifact) == record.checksum.lower()


def write_registry(records: list[ModelRecord], path: str | Path) -> Path:
    errors = [f"{record.model_id}: {error}" for record in records for error in record.validate()]
    identities = [(record.model_id, record.version) for record in records]
    if len(identities) != len(set(identities)):
        errors.append("model_id/version pairs must be unique")
    production_by_name: dict[str, int] = {}
    for record in records:
        if record.deployment_status == DeploymentStatus.PRODUCTION:
            production_by_name[record.model_name] = production_by_name.get(record.model_name, 0) + 1
    if any(count > 1 for count in production_by_name.values()):
        errors.append("only one PRODUCTION version is allowed per model_name")
    if errors:
        raise ValueError("; ".join(errors))
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema_version": 1,
        "models": [record.as_dict() for record in sorted(records, key=lambda item: (item.model_name, item.version))],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def load_registry(path: str | Path) -> list[ModelRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("models"), list):
        raise ValueError("model registry must use schema_version 1 and contain models[]")
    records = []
    for item in payload["models"]:
        item = dict(item)
        item["deployment_status"] = DeploymentStatus(item["deployment_status"])
        records.append(ModelRecord(**item))
    # Reuse the writer's validation without touching disk.
    for record in records:
        errors = record.validate()
        if errors:
            raise ValueError(f"{record.model_id}: {'; '.join(errors)}")
    return records
