"""Frozen Swiss Dwellings manifest -> deterministic YOLO room polygons.

The source render tree and frozen training manifest are read-only.  This adapter
uses canonical metric room instances from each floor's ``supervision.json.gz``
and the exact metric-to-pixel transform in ``metadata.json``.  It never infers
instances from semantic connected components.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image
from shapely import from_wkt
from shapely.geometry import Polygon


ADAPTER_VERSION = "swiss-dwellings-rooms-yolo-v1"
EXPECTED_SOURCE_MANIFEST_SHA256 = "6375b709932223b328de146282549807c4e2555526d4a2654ff216c68b377c4b"
EXPECTED_EXCLUSIONS = {"5593", "5639", "5640"}
ROOM_CLASSES = [
    "bedroom", "bathroom", "kitchen", "living", "living_dining", "corridor",
    "storage", "balcony", "office", "utility", "stairs", "entry_lobby",
    "generic_room", "shaft",
]
CLASS_TO_ID = {name: index for index, name in enumerate(ROOM_CLASSES)}
COORDINATE_PRECISION = 8
MIN_NORMALIZED_AREA = 1e-12
BOUNDARY_EPSILON = 1e-9


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _write_if_changed(path: Path, payload: bytes) -> bool:
    """Atomically create or update a file, preserving identical outputs."""
    if path.is_file() and path.read_bytes() == payload:
        return False
    _atomic_write(path, payload)
    return True


def _safe_component(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    if not text:
        raise ValueError(f"identifier cannot form a safe path component: {value!r}")
    return text


def floor_stem(row: dict) -> str:
    return "__".join(_safe_component(row[key]) for key in ("site_id", "building_id", "plan_id", "floor_id"))


def _shoelace_area(points: list[tuple[float, float]]) -> float:
    return abs(sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )) / 2.0


def polygon_to_yolo(
    geometry_wkt: str,
    *,
    class_id: int,
    transform: dict,
) -> tuple[str | None, str | None]:
    """Return one deterministic YOLO polygon line or an explicit rejection."""
    try:
        geometry = from_wkt(geometry_wkt)
    except Exception as exc:
        return None, f"MALFORMED_WKT:{type(exc).__name__}"
    if geometry.is_empty:
        return None, "EMPTY_GEOMETRY"
    if not geometry.is_valid:
        return None, "INVALID_GEOMETRY"
    if not isinstance(geometry, Polygon):
        return None, f"UNREPRESENTABLE_GEOMETRY_TYPE:{geometry.geom_type}"
    if geometry.interiors:
        return None, "UNREPRESENTABLE_INTERIOR_RINGS"

    width, height = map(int, transform["image_size_px"])
    minx, _, _, maxy = map(float, transform["source_bounds_m"])
    padding = float(transform["padding_m"])
    pixels_per_metre = float(transform["pixels_per_metre"])
    if width <= 1 or height <= 1 or pixels_per_metre <= 0:
        return None, "INVALID_RENDER_TRANSFORM"

    points: list[tuple[float, float]] = []
    for x, y, *_ in list(geometry.exterior.coords)[:-1]:
        x_norm = ((float(x) - minx + padding) * pixels_per_metre) / width
        y_norm = ((maxy - float(y) + padding) * pixels_per_metre) / height
        if not (math.isfinite(x_norm) and math.isfinite(y_norm)):
            return None, "NONFINITE_NORMALIZED_COORDINATE"
        if x_norm < -BOUNDARY_EPSILON or x_norm > 1 + BOUNDARY_EPSILON \
                or y_norm < -BOUNDARY_EPSILON or y_norm > 1 + BOUNDARY_EPSILON:
            return None, "NORMALIZED_COORDINATE_OUT_OF_BOUNDS"
        point = (
            round(min(1.0, max(0.0, x_norm)), COORDINATE_PRECISION),
            round(min(1.0, max(0.0, y_norm)), COORDINATE_PRECISION),
        )
        if not points or point != points[-1]:
            points.append(point)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(set(points)) < 3 or _shoelace_area(points) <= MIN_NORMALIZED_AREA:
        return None, "DEGENERATE_NORMALIZED_POLYGON"

    values = " ".join(f"{value:.{COORDINATE_PRECISION}f}" for point in points for value in point)
    return f"{class_id} {values}", None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_supervision(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError(f"supervision must be a list: {path}")
    return value


def _link_or_verify(source: Path, destination: Path, expected_sha256: str | None) -> str:
    source_sha = expected_sha256 or sha256_file(source)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != source_sha:
            raise ValueError(f"existing adapter image differs from frozen source: {destination}")
        try:
            return "hardlink" if os.path.samefile(source, destination) else "copy"
        except OSError:
            return "copy"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        method = "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        method = "copy"
    if sha256_file(destination) != source_sha:
        destination.unlink(missing_ok=True)
        raise ValueError(f"adapter image checksum mismatch after {method}: {destination}")
    return method


def _yaml_text(output_root: Path) -> str:
    names = "\n".join(f"  {index}: {name}" for index, name in enumerate(ROOM_CLASSES))
    return (
        f"path: {json.dumps(output_root.resolve().as_posix())}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        f"nc: {len(ROOM_CLASSES)}\n"
        f"names:\n{names}\n"
    )


def build_adapter(source_manifest_path: str | Path, output_root: str | Path) -> dict:
    source_manifest_path = Path(source_manifest_path).resolve()
    output_root = Path(output_root).resolve()
    source_sha = sha256_file(source_manifest_path)
    if source_sha != EXPECTED_SOURCE_MANIFEST_SHA256:
        raise ValueError(
            f"source training-manifest SHA-256 mismatch: expected "
            f"{EXPECTED_SOURCE_MANIFEST_SHA256}, found {source_sha}"
        )
    source_manifest = _load_json(source_manifest_path)
    source_rows = source_manifest.get("eligible_floors", [])
    excluded_ids = {str(row["floor_id"]) for row in source_manifest.get("exclusions", [])}
    if excluded_ids != EXPECTED_EXCLUSIONS:
        raise ValueError(f"unexpected frozen exclusions: {sorted(excluded_ids)}")

    floor_records: list[dict] = []
    rejections: list[dict] = []
    split_counts = Counter()
    authoritative_total = 0
    generated_total = 0
    intentional_negatives = 0
    link_methods = Counter()
    seen_stems: set[str] = set()
    buildings_by_split = {"train": set(), "val": set(), "test": set()}

    for row in source_rows:
        floor_id = str(row["floor_id"])
        if floor_id in EXPECTED_EXCLUSIONS:
            raise ValueError(f"excluded floor appears in eligible source rows: {floor_id}")
        split = row["split"]
        if split not in buildings_by_split:
            raise ValueError(f"unsupported split {split!r} for floor {row['floor_key']}")
        stem = floor_stem(row)
        if stem in seen_stems:
            raise ValueError(f"adapter filename collision: {stem}")
        seen_stems.add(stem)
        split_counts[split] += 1
        buildings_by_split[split].add(row["building_key"])

        source_image = Path(row["rendered_input_path"])
        source_dir = source_image.parent
        metadata_path = source_dir / "metadata.json"
        supervision_path = source_dir / "supervision.json.gz"
        instance_mask_path = source_dir / "room_instance.png"
        for required in (source_image, metadata_path, supervision_path, instance_mask_path):
            if not required.is_file():
                raise FileNotFoundError(f"required frozen artifact missing: {required}")
        metadata = _load_json(metadata_path)
        transform = metadata["transform"]
        with Image.open(source_image) as image:
            image_size = [int(image.width), int(image.height)]
        if image_size != list(map(int, transform["image_size_px"])):
            raise ValueError(f"render transform/image dimensions disagree for {row['floor_key']}")

        source_image_sha = row.get("output_hashes_sha256", {}).get("image.png")
        if source_image_sha and sha256_file(source_image) != source_image_sha:
            raise ValueError(f"frozen image checksum mismatch for {row['floor_key']}")
        adapter_image = output_root / "images" / split / f"{stem}.png"
        adapter_label = output_root / "labels" / split / f"{stem}.txt"
        link_methods[_link_or_verify(source_image, adapter_image, source_image_sha)] += 1

        authoritative = [
            record for record in _load_supervision(supervision_path)
            if record.get("target_family") == "spaces"
            and record.get("mapping_state") == "TRAIN"
            and not record.get("excluded", False)
        ]
        authoritative.sort(key=lambda record: (
            int(record.get("target_class_id", 0)), str(record.get("geometry_id", ""))
        ))
        lines: list[str] = []
        floor_rejections = 0
        for record in authoritative:
            class_name = record.get("target_class")
            mask_class_id = record.get("target_class_id")
            expected_mask_id = CLASS_TO_ID.get(class_name, -1) + 1
            if class_name not in CLASS_TO_ID or mask_class_id != expected_mask_id:
                reason = "UNKNOWN_OR_MISMATCHED_CLASS"
                line = None
            else:
                line, reason = polygon_to_yolo(
                    record.get("geometry_wkt_metric", ""),
                    class_id=CLASS_TO_ID[class_name],
                    transform=transform,
                )
            if line is None:
                floor_rejections += 1
                rejections.append({
                    "floor_key": row["floor_key"],
                    "site_id": row["site_id"],
                    "building_id": row["building_id"],
                    "plan_id": row["plan_id"],
                    "floor_id": floor_id,
                    "source_instance": record.get("geometry_id"),
                    "class": class_name,
                    "reason": reason,
                })
            else:
                lines.append(line)
        label_payload = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
        if adapter_label.exists():
            if adapter_label.read_bytes() != label_payload:
                raise ValueError(f"existing adapter label differs from deterministic output: {adapter_label}")
        else:
            _atomic_write(adapter_label, label_payload)

        authoritative_count = len(authoritative)
        generated_count = len(lines)
        if authoritative_count == 0:
            intentional_negatives += 1
            if label_payload:
                raise AssertionError("intentional negative floor produced a non-empty label")
        if authoritative_count != generated_count + floor_rejections:
            raise AssertionError(f"instance reconciliation failed for {row['floor_key']}")
        authoritative_total += authoritative_count
        generated_total += generated_count
        floor_records.append({
            "floor_key": row["floor_key"],
            "site_id": row["site_id"],
            "building_id": row["building_id"],
            "plan_id": row["plan_id"],
            "floor_id": floor_id,
            "building_key": row["building_key"],
            "split": split,
            "source_rendered_input_path": str(source_image.resolve()),
            "source_room_instance_mask_path": str(instance_mask_path.resolve()),
            "source_metric_supervision_path": str(supervision_path.resolve()),
            "rendered_input_path": str(adapter_image.resolve()),
            "generated_label_path": str(adapter_label.resolve()),
            "image_dimensions_px": image_size,
            "authoritative_instance_count": authoritative_count,
            "generated_instance_count": generated_count,
            "rejected_instance_count": floor_rejections,
            "output_hashes_sha256": {
                "image.png": sha256_file(adapter_image),
                "label.txt": hashlib.sha256(label_payload).hexdigest(),
            },
        })

    leakage = (
        (buildings_by_split["train"] & buildings_by_split["val"])
        | (buildings_by_split["train"] & buildings_by_split["test"])
        | (buildings_by_split["val"] & buildings_by_split["test"])
    )
    source_summary = source_manifest["summary"]
    if leakage:
        raise ValueError(f"building leakage across adapter splits: {sorted(leakage)[:10]}")
    if source_summary.get("duplicate_relationships_crossing_splits") != 0 \
            or source_summary.get("duplicate_connected_clusters_crossing_splits") != 0:
        raise ValueError("source manifest does not prove duplicate-aware split isolation")
    if dict(split_counts) != source_summary.get("eligible_floors_by_split"):
        raise ValueError("adapter split counts differ from frozen source manifest")

    yaml_path = output_root / "data.yaml"
    groups_path = output_root / "groups.json"
    _write_if_changed(yaml_path, _yaml_text(output_root).encode("utf-8"))
    groups = {
        "schema_version": 1,
        "groups": {
            f"images/{row['split']}/{floor_stem(row)}.png": row["building_key"]
            for row in source_rows
        },
    }
    _write_if_changed(
        groups_path,
        (json.dumps(groups, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )

    manifest = {
        "schema_version": 1,
        "adapter_version": ADAPTER_VERSION,
        "source_training_manifest_path": str(source_manifest_path),
        "source_training_manifest_sha256": source_sha,
        "source_dataset_version": source_manifest["dataset"]["training_dataset_version"],
        "source_conversion_version": source_manifest["dataset"]["conversion_version"],
        "authoritative_instance_source": "canonical metric WKT in supervision.json.gz",
        "polygon_policy": {
            "simplification_tolerance_m": 0.0,
            "coordinate_precision_decimals": COORDINATE_PRECISION,
            "holes": "reject",
            "multipolygons": "reject",
            "invalid_or_degenerate": "reject",
        },
        "taxonomy": [
            {"class_id": index, "mask_id": index + 1, "name": name}
            for index, name in enumerate(ROOM_CLASSES)
        ],
        "ultralytics_dataset_yaml": str(yaml_path.resolve()),
        "groups_manifest": str(groups_path.resolve()),
        "summary": {
            "floor_count": len(floor_records),
            "floors_by_split": dict(sorted(split_counts.items())),
            "buildings_by_split": {
                split: len(buildings) for split, buildings in sorted(buildings_by_split.items())
            },
            "authoritative_room_instance_count": authoritative_total,
            "generated_yolo_instance_count": generated_total,
            "rejected_instance_count": len(rejections),
            "intentional_negative_label_count": intentional_negatives,
            "excluded_floors_present": False,
            "missing_image_label_references": 0,
            "building_leakage_count": 0,
            "duplicate_relationships_crossing_splits": 0,
            "duplicate_connected_clusters_crossing_splits": 0,
            "image_materialization_methods": dict(sorted(link_methods.items())),
        },
        "floors": floor_records,
        "rejected_instances": rejections,
    }
    manifest_payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path = output_root / "rooms-v1.manifest.json"
    manifest_sha = hashlib.sha256(manifest_payload).hexdigest()
    _atomic_write(manifest_path, manifest_payload)
    _atomic_write(
        manifest_path.with_suffix(manifest_path.suffix + ".sha256"),
        f"{manifest_sha}  {manifest_path.name}\n".encode("ascii"),
    )
    return {
        "adapter_output_path": str(output_root),
        "adapter_manifest_path": str(manifest_path),
        "adapter_manifest_sha256": manifest_sha,
        "dataset_yaml_path": str(yaml_path),
        "summary": manifest["summary"],
        "rejection_reasons": dict(sorted(Counter(row["reason"] for row in rejections).items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = build_adapter(args.source_manifest, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
