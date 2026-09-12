"""Production QA gate for the rights-cleared in-domain spaces corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from shapely.geometry import Polygon


SPLITS = ("train", "val", "test", "golden")


@dataclass
class InDomainAudit:
    ready: bool
    sheet_counts: dict[str, int] = field(default_factory=dict)
    project_counts: dict[str, int] = field(default_factory=dict)
    class_instances: dict[str, int] = field(default_factory=dict)
    difficulty_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dhash(path: Path) -> str:
    with Image.open(path) as image:
        pixels = list(image.convert("L").resize((9, 8)).get_flattened_data())
    bits = [pixels[row * 9 + col] > pixels[row * 9 + col + 1] for row in range(8) for col in range(8)]
    value = sum(int(bit) << index for index, bit in enumerate(bits))
    return f"{value:016x}"


def _label_polygons(path: Path, class_count: int) -> tuple[list[tuple[int, Polygon]], list[str]]:
    polygons: list[tuple[int, Polygon]] = []
    errors: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        parts = raw.strip().split()
        if not parts:
            continue
        where = f"{path}:{line_number}"
        if len(parts) < 7 or (len(parts) - 1) % 2:
            errors.append(f"{where}: requires class plus at least three x/y points")
            continue
        try:
            class_id = int(parts[0])
            coords = [float(item) for item in parts[1:]]
        except ValueError:
            errors.append(f"{where}: non-numeric class or coordinate")
            continue
        if not 0 <= class_id < class_count:
            errors.append(f"{where}: class id {class_id} outside taxonomy")
            continue
        if any(not math.isfinite(item) or not 0 <= item <= 1 for item in coords):
            errors.append(f"{where}: coordinates must be finite and normalized")
            continue
        polygon = Polygon(list(zip(coords[0::2], coords[1::2])))
        if polygon.is_empty or polygon.area <= 1e-8 or not polygon.is_valid:
            errors.append(f"{where}: invalid, self-intersecting, or zero-area polygon")
            continue
        polygons.append((class_id, polygon))
    return polygons, errors


def validate_in_domain_manifest(manifest_path: str | Path, config_path: str | Path, source_root: str | Path) -> InDomainAudit:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    root = Path(source_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    samples = manifest.get("samples", [])
    classes = config["classes"]
    if manifest.get("dataset_name") != config["dataset_name"]:
        errors.append("manifest dataset_name does not match configuration")
    if not samples:
        errors.append("no rights-cleared in-domain samples are present")

    sheet_counts = Counter()
    projects_by_split: dict[str, set[str]] = defaultdict(set)
    splits_by_project: dict[str, set[str]] = defaultdict(set)
    class_counts = Counter()
    difficulty_counts = Counter()
    sample_ids: set[str] = set()
    byte_hashes: dict[str, tuple[str, str]] = {}
    perceptual_hashes: dict[str, tuple[str, str]] = {}

    for sample in samples:
        sample_id = str(sample.get("sample_id", "")).strip()
        split = sample.get("split")
        project_id = str(sample.get("project_id", "")).strip()
        where = f"sample {sample_id or '<missing>'}"
        if not sample_id or sample_id in sample_ids:
            errors.append(f"{where}: sample_id is missing or duplicated")
        sample_ids.add(sample_id)
        if split not in SPLITS:
            errors.append(f"{where}: invalid split {split!r}")
            continue
        if not project_id:
            errors.append(f"{where}: project_id is required")
            continue
        sheet_counts[split] += 1
        projects_by_split[split].add(project_id)
        splits_by_project[project_id].add(split)

        if sample.get("intake_eligibility", {}).get("status") != "eligible":
            errors.append(f"{where}: sheet has not passed the rights/provenance intake eligibility gate")

        rights = sample.get("rights", {})
        if not (rights.get("status") == "approved" and rights.get("commercial_training") is True
                and str(rights.get("evidence_ref", "")).strip()):
            errors.append(f"{where}: approved commercial-training rights evidence is required")
        annotation = sample.get("annotation", {})
        if annotation.get("status") != "approved" or not annotation.get("reviewers"):
            errors.append(f"{where}: independently reviewed approved annotation is required")
        if split == "golden" and not (sample.get("golden_approved") is True and sample.get("untouched") is True):
            errors.append(f"{where}: golden samples must be explicitly approved and untouched")

        tags = set(sample.get("difficulty_tags", []))
        difficulty_counts.update(tags)
        image_path = (root / str(sample.get("image_path", ""))).resolve()
        label_path = (root / str(sample.get("label_path", ""))).resolve()
        if root not in image_path.parents or root not in label_path.parents:
            errors.append(f"{where}: source path escapes dataset root")
            continue
        if not image_path.is_file() or not label_path.is_file():
            errors.append(f"{where}: image or label file is missing")
            continue
        try:
            with Image.open(image_path) as image:
                image.verify()
            with Image.open(image_path) as image:
                width, height = image.size
            if width < config["minimum_image_width"] or height < config["minimum_image_height"]:
                errors.append(f"{where}: image resolution {width}x{height} is below minimum")
        except (OSError, UnidentifiedImageError) as exc:
            errors.append(f"{where}: corrupt or unsupported image: {exc}")
            continue

        digest = _sha256(image_path)
        if digest in byte_hashes:
            other_id, other_split = byte_hashes[digest]
            errors.append(f"{where}: byte-identical duplicate of {other_id} ({other_split})")
        else:
            byte_hashes[digest] = (sample_id, split)
        visual_digest = _dhash(image_path)
        if visual_digest in perceptual_hashes:
            other_id, other_split = perceptual_hashes[visual_digest]
            message = f"{where}: perceptual duplicate candidate of {other_id} ({other_split})"
            (errors if other_split != split else warnings).append(message)
        else:
            perceptual_hashes[visual_digest] = (sample_id, split)

        polygons, label_errors = _label_polygons(label_path, len(classes))
        errors.extend(label_errors)
        if not polygons and not (sample.get("negative") is True and annotation.get("status") == "approved"):
            errors.append(f"{where}: empty labels require an explicitly approved negative sheet")
        for class_id, _polygon in polygons:
            class_counts[classes[class_id]] += 1
        for index, (_, left) in enumerate(polygons):
            for _, right in polygons[index + 1:]:
                overlap = left.intersection(right).area
                smaller = min(left.area, right.area)
                if smaller and overlap / smaller > float(config["maximum_mask_overlap_ratio"]):
                    errors.append(f"{where}: room masks overlap by more than the allowed ratio")
                    break

    for project_id, split_set in splits_by_project.items():
        if len(split_set) > 1:
            errors.append(f"project {project_id} leaks across splits: {sorted(split_set)}")

    total = sum(sheet_counts.values())
    minimum_total, maximum_total = config["allowed_total_range"]
    if not minimum_total <= total <= maximum_total:
        errors.append(f"total sheet count {total} is outside {minimum_total}..{maximum_total}")
    golden_min, golden_max = config["allowed_golden_range"]
    if not golden_min <= sheet_counts["golden"] <= golden_max:
        errors.append(f"golden sheet count {sheet_counts['golden']} is outside {golden_min}..{golden_max}")
    for split in SPLITS:
        if not projects_by_split[split]:
            errors.append(f"{split} has no projects")
    for class_name, minimum in config["minimum_instances_per_class"].items():
        if class_counts[class_name] < minimum:
            errors.append(f"class {class_name} has {class_counts[class_name]} instances; minimum is {minimum}")
    tag_minimum = int(config["minimum_sheets_per_difficulty_tag"])
    for tag in config["required_difficulty_tags"]:
        if difficulty_counts[tag] < tag_minimum:
            errors.append(f"difficulty tag {tag} appears on {difficulty_counts[tag]} sheets; minimum is {tag_minimum}")

    return InDomainAudit(
        ready=not errors,
        sheet_counts=dict(sheet_counts),
        project_counts={split: len(projects_by_split[split]) for split in SPLITS},
        class_instances=dict(class_counts),
        difficulty_counts=dict(difficulty_counts),
        errors=errors,
        warnings=warnings,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    audit = validate_in_domain_manifest(args.manifest, args.config, args.source_root)
    payload = json.dumps(audit.as_dict(), indent=2, sort_keys=True) + "\n"
    if args.report:
        Path(args.report).write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if audit.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
