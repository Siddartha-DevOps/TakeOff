"""Generic image/annotation dataset validator with machine-readable output."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


VALID_SPLITS = {"train", "validation", "test"}


@dataclass
class ValidationReport:
    valid: bool
    samples_checked: int
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    split_counts: dict[str, int] = field(default_factory=dict)
    duplicate_hashes: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _issue(code: str, sample_id: str, message: str) -> dict[str, str]:
    return {"code": code, "sample_id": sample_id, "message": message}


def _validate_yolo(path: Path, class_count: int, annotation_format: str) -> tuple[int, list[str]]:
    annotations = 0
    errors: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        values = raw.split()
        try:
            class_id = int(values[0])
            coords = [float(value) for value in values[1:]]
        except (ValueError, IndexError):
            errors.append(f"line {line_number}: non-numeric YOLO annotation")
            continue
        if not 0 <= class_id < class_count:
            errors.append(f"line {line_number}: unknown class {class_id}")
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in coords):
            errors.append(f"line {line_number}: coordinates must be finite and normalized")
        if annotation_format == "yolo_bbox":
            if len(coords) != 4 or (len(coords) == 4 and (coords[2] <= 0 or coords[3] <= 0)):
                errors.append(f"line {line_number}: invalid bounding box")
        elif annotation_format == "yolo_segmentation":
            if len(coords) < 6 or len(coords) % 2:
                errors.append(f"line {line_number}: invalid polygon")
            elif len(coords) >= 6:
                points = list(zip(coords[::2], coords[1::2]))
                area = abs(sum(x1 * y2 - x2 * y1
                               for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2
                if area <= 1e-8:
                    errors.append(f"line {line_number}: degenerate polygon")
        else:
            errors.append(f"line {line_number}: unsupported annotation format {annotation_format}")
        annotations += 1
    return annotations, errors


def validate_dataset_index(index_path: str | Path, *, output_path: str | Path | None = None) -> ValidationReport:
    """Validate an external dataset index without copying its assets.

    Index format: ``{root, classes, samples:[{sample_id, project_id, split,
    image, annotation, annotation_format}]}``.
    """
    index_path = Path(index_path)
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    root = Path(payload.get("root") or index_path.parent)
    if not root.is_absolute():
        root = (index_path.parent / root).resolve()
    classes = payload.get("classes") or []
    samples = payload.get("samples") or []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    split_counts: dict[str, int] = {}
    hashes: dict[str, list[tuple[str, str]]] = {}
    projects: dict[str, set[str]] = {}
    seen_sample_ids: set[str] = set()

    for sample in samples:
        sample_id = str(sample.get("sample_id") or "")
        split = str(sample.get("split") or "")
        project_id = str(sample.get("project_id") or "")
        if not sample_id or sample_id in seen_sample_ids:
            errors.append(_issue("duplicate_sample_id", sample_id, "sample_id is missing or duplicated"))
        seen_sample_ids.add(sample_id)
        if split not in VALID_SPLITS:
            errors.append(_issue("invalid_split", sample_id, f"unsupported split {split!r}"))
        split_counts[split] = split_counts.get(split, 0) + 1
        if not project_id:
            errors.append(_issue("missing_project_id", sample_id, "project_id is required for leakage checks"))
        else:
            projects.setdefault(project_id, set()).add(split)

        image = root / str(sample.get("image") or "")
        annotation = root / str(sample.get("annotation") or "")
        if not image.is_file():
            errors.append(_issue("missing_image", sample_id, str(image)))
        else:
            try:
                with Image.open(image) as opened:
                    opened.verify()
            except (OSError, UnidentifiedImageError) as exc:
                errors.append(_issue("corrupted_image", sample_id, str(exc)))
            digest = _sha256(image)
            hashes.setdefault(digest, []).append((sample_id, split))
        if not annotation.is_file():
            errors.append(_issue("missing_annotation", sample_id, str(annotation)))
        elif classes:
            count, label_errors = _validate_yolo(
                annotation, len(classes), sample.get("annotation_format", "yolo_segmentation")
            )
            if count == 0:
                warnings.append(_issue("empty_annotation", sample_id, "intentional negatives must be documented"))
            errors.extend(_issue("invalid_annotation", sample_id, message) for message in label_errors)

    for project_id, splits in projects.items():
        if len(splits) > 1:
            errors.append(_issue("project_leakage", project_id, f"project crosses splits: {sorted(splits)}"))
    duplicate_hashes: dict[str, list[str]] = {}
    for digest, occurrences in hashes.items():
        if len(occurrences) > 1:
            ids = [sample_id for sample_id, _ in occurrences]
            duplicate_hashes[digest] = ids
            split_set = {split for _, split in occurrences}
            code = "cross_split_duplicate" if len(split_set) > 1 else "duplicate_image"
            errors.append(_issue(code, ",".join(ids), f"image hash {digest} occurs in {sorted(split_set)}"))

    report = ValidationReport(not errors, len(samples), errors, warnings, split_counts, duplicate_hashes)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
