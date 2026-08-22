"""Strict, dependency-free validation for a YOLO spaces dataset.

The ordinary ML preflight only proves that label files exist.  This module is
the data-quality gate used before spending GPU time: it validates polygon
syntax, image/label pairing, split coverage, byte-identical cross-split leaks,
and (when supplied) project/group leakage.  It can also write a deterministic
manifest that identifies the exact samples used by a training run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ml.preflight import parse_data_yaml


IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
REQUIRED_SPLITS = ("train", "val")


@dataclass
class DatasetAudit:
    ready: bool
    data_yaml: str
    classes: list[str] = field(default_factory=list)
    split_counts: dict[str, int] = field(default_factory=dict)
    polygon_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _yaml_scalar(text: str, key: str) -> str | None:
    """Read a simple top-level YAML scalar without adding a PyYAML dependency."""
    prefix = f"{key}:"
    for raw in text.splitlines():
        if raw.startswith(prefix):
            value = raw.split(":", 1)[1].strip().strip("'\"")
            return value or None
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _polygon_area(coords: list[float]) -> float:
    points = list(zip(coords[0::2], coords[1::2]))
    return abs(sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )) / 2.0


def _validate_label(path: Path, n_classes: int) -> tuple[int, list[str]]:
    errors: list[str] = []
    polygons = 0
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        where = f"{path}:{line_number}"
        if len(parts) < 7 or (len(parts) - 1) % 2:
            errors.append(f"{where}: segmentation needs a class plus at least 3 x/y points")
            continue
        try:
            class_id = int(parts[0])
            coords = [float(value) for value in parts[1:]]
        except ValueError:
            errors.append(f"{where}: class and polygon coordinates must be numeric")
            continue
        if not 0 <= class_id < n_classes:
            errors.append(f"{where}: class id {class_id} is outside 0..{n_classes - 1}")
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in coords):
            errors.append(f"{where}: polygon coordinates must be finite and normalized to [0, 1]")
        elif _polygon_area(coords) <= 1e-8:
            errors.append(f"{where}: polygon has zero area")
        polygons += 1
    return polygons, errors


def _load_groups(dataset_root: Path) -> tuple[dict[str, str], str | None]:
    path = dataset_root / "groups.json"
    if not path.is_file():
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        mapping = payload.get("groups", payload) if isinstance(payload, dict) else {}
        if not isinstance(mapping, dict) or not all(isinstance(v, str) and v for v in mapping.values()):
            return {}, "groups.json must be an object mapping sample ids/paths to non-empty group ids"
        return {str(k).replace("\\", "/"): v for k, v in mapping.items()}, None
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"cannot parse groups.json: {exc}"


def validate_spaces_dataset(
    data_yaml: str | Path,
    *,
    require_groups: bool = False,
    expected_classes: list[str] | None = None,
) -> DatasetAudit:
    """Audit a YOLO segmentation dataset and return a machine-readable verdict."""
    yaml_path = Path(data_yaml)
    errors: list[str] = []
    warnings: list[str] = []
    if not yaml_path.is_file():
        return DatasetAudit(False, str(yaml_path), errors=[f"dataset not found: {yaml_path}"])

    text = yaml_path.read_text(encoding="utf-8-sig")
    meta = parse_data_yaml(text)
    classes = meta["names"]
    if not classes or meta["nc"] != len(classes):
        errors.append(f"data.yaml nc ({meta['nc']}) must equal the number of names ({len(classes)})")
    if expected_classes is not None and classes != expected_classes:
        errors.append(f"class taxonomy must be {expected_classes}, found {classes}")

    root_value = _yaml_scalar(text, "path")
    dataset_root = Path(root_value) if root_value else yaml_path.parent
    if not dataset_root.is_absolute():
        dataset_root = (yaml_path.parent / dataset_root).resolve()

    groups, groups_error = _load_groups(dataset_root)
    if groups_error:
        errors.append(groups_error)
    if require_groups and not groups:
        errors.append("groups.json is required to prove project-level split isolation")
    elif not groups:
        warnings.append("no groups.json; byte leakage is checked, but project-level leakage cannot be proven")

    samples: list[dict] = []
    split_counts: dict[str, int] = {}
    polygon_counts: dict[str, int] = {}
    hashes_by_split: dict[str, set[str]] = {}
    groups_by_split: dict[str, set[str]] = {}

    for split in ("train", "val", "test"):
        split_value = _yaml_scalar(text, split)
        if not split_value:
            if split in REQUIRED_SPLITS:
                errors.append(f"data.yaml is missing required '{split}' split")
            continue
        image_dir = Path(split_value)
        if not image_dir.is_absolute():
            image_dir = dataset_root / image_dir
        if not image_dir.is_dir():
            errors.append(f"{split} image directory not found: {image_dir}")
            continue
        images = sorted(p for p in image_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS)
        split_counts[split] = len(images)
        polygon_counts[split] = 0
        if split in REQUIRED_SPLITS and not images:
            errors.append(f"{split} split has no images")

        try:
            images_index = image_dir.parts.index("images")
            label_dir = Path(*image_dir.parts[:images_index], "labels", *image_dir.parts[images_index + 1:])
        except ValueError:
            label_dir = dataset_root / "labels" / split

        expected_labels = {(label_dir / image.relative_to(image_dir)).with_suffix(".txt") for image in images}
        if label_dir.is_dir():
            for label_path in label_dir.rglob("*.txt"):
                if label_path not in expected_labels:
                    errors.append(f"orphan label has no matching image: {label_path}")

        for image_path in images:
            rel_image = image_path.relative_to(dataset_root).as_posix()
            rel_within_split = image_path.relative_to(image_dir)
            label_path = (label_dir / rel_within_split).with_suffix(".txt")
            if not label_path.is_file():
                errors.append(f"missing label for {rel_image}: {label_path}")
                continue
            if image_path.stat().st_size == 0:
                errors.append(f"empty image file: {rel_image}")
            polygons, label_errors = _validate_label(label_path, len(classes))
            polygon_counts[split] += polygons
            errors.extend(label_errors)
            image_hash = _sha256(image_path)
            label_hash = _sha256(label_path)
            hashes_by_split.setdefault(image_hash, set()).add(split)

            sample_key = rel_within_split.with_suffix("").as_posix()
            group_id = groups.get(rel_image) or groups.get(sample_key) or groups.get(image_path.stem)
            if groups and not group_id:
                errors.append(f"groups.json has no group id for {rel_image}")
            if group_id:
                groups_by_split.setdefault(group_id, set()).add(split)
            samples.append({
                "sample_id": sample_key,
                "group_id": group_id,
                "split": split,
                "image": rel_image,
                "label": label_path.relative_to(dataset_root).as_posix(),
                "image_sha256": image_hash,
                "label_sha256": label_hash,
                "polygons": polygons,
            })

    for digest, splits in hashes_by_split.items():
        if len(splits) > 1:
            errors.append(f"identical image {digest[:12]} appears across splits: {sorted(splits)}")
    for group_id, splits in groups_by_split.items():
        if len(splits) > 1:
            errors.append(f"group '{group_id}' appears across splits: {sorted(splits)}")

    canonical = json.dumps(samples, sort_keys=True, separators=(",", ":"))
    manifest = {
        "schema_version": 1,
        "dataset_id": hashlib.sha256(canonical.encode()).hexdigest()[:16],
        "data_yaml": str(yaml_path),
        "classes": classes,
        "split_counts": split_counts,
        "polygon_counts": polygon_counts,
        "samples": samples,
    }
    return DatasetAudit(not errors, str(yaml_path), classes, split_counts,
                        polygon_counts, errors, warnings, manifest)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate and manifest a spaces-v1 dataset")
    parser.add_argument("--data", required=True, help="path to YOLO data.yaml")
    parser.add_argument("--manifest", default=None, help="write the deterministic JSON manifest here")
    parser.add_argument("--require-groups", action="store_true",
                        help="fail unless groups.json proves project-level split isolation")
    parser.add_argument("--expected-class", action="append", dest="expected_classes",
                        help="required class name in id order; repeat for multiple classes")
    parser.add_argument("--json", action="store_true", help="print the complete JSON audit")
    args = parser.parse_args(argv)

    audit = validate_spaces_dataset(args.data, require_groups=args.require_groups,
                                    expected_classes=args.expected_classes)
    if args.manifest and audit.manifest:
        output = Path(args.manifest)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(audit.manifest, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(audit.as_dict(), indent=2))
    else:
        print(f"spaces-v1 ready: {audit.ready}")
        print(f"classes: {audit.classes}; splits: {audit.split_counts}; polygons: {audit.polygon_counts}")
        for warning in audit.warnings:
            print(f"warning: {warning}")
        for error in audit.errors:
            print(f"blocker: {error}")
    return 0 if audit.ready else 1


if __name__ == "__main__":
    sys.exit(main())
