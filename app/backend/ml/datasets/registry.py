"""Versioned, portable dataset registry records.

The files described by a record may live outside Git (the normal production
case).  This module stores only evidence: provenance, licensing, taxonomy,
split counts, and a content checksum supplied by the dataset preparation job.
It deliberately does not copy source images or annotations.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SPLITS = ("train", "validation", "test")


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    version: str
    source: str
    license: str
    provenance: str
    classes: list[str]
    image_count: int
    annotation_count: int
    train_count: int
    validation_count: int
    test_count: int
    created_at: str
    checksum: str | None = None
    annotation_format: str | None = None
    split_policy: str = "project-level"
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        for name in ("dataset_id", "version", "source", "license", "provenance"):
            if not str(getattr(self, name)).strip():
                errors.append(f"{name} is required")
        if not self.classes or len(set(self.classes)) != len(self.classes):
            errors.append("classes must be a non-empty, unique ordered list")
        counts = {
            "image_count": self.image_count,
            "annotation_count": self.annotation_count,
            "train_count": self.train_count,
            "validation_count": self.validation_count,
            "test_count": self.test_count,
        }
        for name, value in counts.items():
            if not isinstance(value, int) or value < 0:
                errors.append(f"{name} must be a non-negative integer")
        if self.train_count + self.validation_count + self.test_count != self.image_count:
            errors.append("train + validation + test counts must equal image_count")
        try:
            datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            errors.append("created_at must be ISO-8601")
        if self.checksum is not None and not SHA256_RE.fullmatch(self.checksum.lower()):
            errors.append("checksum must be a SHA-256 hex digest")
        if self.split_policy not in {"project-level", "building-level", "source-drawing-level"}:
            errors.append("split_policy must prevent page-level leakage")
        return errors

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_registry(path: str | Path) -> list[DatasetRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("datasets"), list):
        raise ValueError("dataset registry must use schema_version 1 and contain datasets[]")
    records = [DatasetRecord(**item) for item in payload["datasets"]]
    errors = [f"{record.dataset_id}@{record.version}: {error}"
              for record in records for error in record.validate()]
    identities = [(record.dataset_id, record.version) for record in records]
    if len(identities) != len(set(identities)):
        errors.append("dataset_id/version pairs must be unique")
    if errors:
        raise ValueError("; ".join(errors))
    return records


def write_registry(records: list[DatasetRecord], path: str | Path) -> Path:
    errors = [f"{record.dataset_id}@{record.version}: {error}"
              for record in records for error in record.validate()]
    identities = [(record.dataset_id, record.version) for record in records]
    if len(identities) != len(set(identities)):
        errors.append("dataset_id/version pairs must be unique")
    if errors:
        raise ValueError("; ".join(errors))
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "datasets": [record.as_dict() for record in sorted(
            records, key=lambda value: (value.dataset_id, value.version)
        )],
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
