"""Read-only preflight for the frozen Swiss Dwellings room-training plan.

This validates the frozen manifest, selected train/validation images and masks,
taxonomy, and split isolation. It never opens test labels, writes dataset files,
or starts Ultralytics. The current frozen labels are semantic PNG masks, so the
report deliberately blocks YOLO training until a deterministic instance-polygon
adapter is materialized and frozen separately.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from PIL import Image


EXPECTED_CLASSES = [
    "bedroom", "bathroom", "kitchen", "living", "living_dining", "corridor",
    "storage", "balcony", "office", "utility", "stairs", "entry_lobby",
    "generic_room", "shaft",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_room_count(output_dir: Path) -> int:
    supervision = output_dir / "supervision.json.gz"
    if not supervision.is_file():
        raise FileNotFoundError(f"missing room provenance: {supervision}")
    with gzip.open(supervision, "rt", encoding="utf-8") as handle:
        records = json.load(handle)
    return sum(
        record.get("target_family") == "spaces"
        and record.get("mapping_state") == "TRAIN"
        and not record.get("excluded", False)
        for record in records
    )


def validate_plan(config_path: str | Path) -> dict:
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []

    required_sections = {"dataset", "taxonomy", "model", "training", "evaluation", "artifacts"}
    missing_sections = sorted(required_sections - set(config))
    if missing_sections:
        errors.append(f"configuration missing sections: {missing_sections}")

    dataset = config.get("dataset", {})
    manifest_path = Path(dataset.get("manifest_path", ""))
    if not manifest_path.is_file():
        return {"ready": False, "errors": [f"manifest not found: {manifest_path}"], "warnings": warnings}
    actual_manifest_sha = _sha256(manifest_path)
    if actual_manifest_sha != dataset.get("manifest_sha256"):
        errors.append(
            f"manifest SHA-256 mismatch: expected {dataset.get('manifest_sha256')}, "
            f"found {actual_manifest_sha}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    classes = config.get("taxonomy", {}).get("classes", [])
    names = [row.get("name") for row in classes]
    training_ids = [row.get("training_id") for row in classes]
    mask_ids = [row.get("mask_id") for row in classes]
    if names != EXPECTED_CLASSES:
        errors.append(f"taxonomy order must be {EXPECTED_CLASSES}, found {names}")
    if training_ids != list(range(len(EXPECTED_CLASSES))):
        errors.append("training class IDs must be contiguous 0..13")
    if mask_ids != list(range(1, len(EXPECTED_CLASSES) + 1)):
        errors.append("mask class IDs must be contiguous 1..14")

    expected_counts = dataset.get("split_counts", {})
    actual_counts = manifest.get("summary", {}).get("eligible_floors_by_split", {})
    if expected_counts != actual_counts:
        errors.append(f"split counts differ: config={expected_counts}, manifest={actual_counts}")
    exclusions = set(map(str, dataset.get("excluded_floor_ids", [])))
    eligible_ids = {str(row["floor_id"]) for row in manifest.get("eligible_floors", [])}
    accidental = sorted(exclusions & eligible_ids)
    if accidental:
        errors.append(f"excluded floors are training eligible: {accidental}")

    buildings_by_split: dict[str, set[str]] = {"train": set(), "val": set(), "test": set()}
    for row in manifest.get("eligible_floors", []):
        buildings_by_split[row["split"]].add(row["building_key"])
    leakage = sorted(
        (buildings_by_split["train"] & buildings_by_split["val"])
        | (buildings_by_split["train"] & buildings_by_split["test"])
        | (buildings_by_split["val"] & buildings_by_split["test"])
    )
    if leakage:
        errors.append(f"building leakage across splits: {leakage[:10]}")
    summary = manifest.get("summary", {})
    if summary.get("duplicate_relationships_crossing_splits") or summary.get("duplicate_connected_clusters_crossing_splits"):
        errors.append("frozen manifest reports duplicate-aware split leakage")

    selected = [row for row in manifest.get("eligible_floors", []) if row["split"] in {"train", "val"}]
    missing_assets: list[str] = []
    invalid_masks: list[str] = []
    unexpected_empty_masks: list[str] = []
    negative_masks = 0
    observed_mask_ids: set[int] = set()
    valid_mask_ids = set(range(len(EXPECTED_CLASSES) + 1))
    for row in selected:
        image_path = Path(row["rendered_input_path"])
        mask_path = Path(row["room_label_path"])
        for path in (image_path, mask_path):
            if not path.is_file():
                missing_assets.append(str(path))
        if not image_path.is_file() or not mask_path.is_file():
            continue
        with Image.open(mask_path) as mask:
            if mask.mode != "L":
                invalid_masks.append(f"{row['floor_key']}: expected L mask, found {mask.mode}")
                continue
            colors = mask.getcolors(maxcolors=256)
            if colors is None:
                invalid_masks.append(f"{row['floor_key']}: mask has more than 256 values")
                continue
            values = {int(value) for _, value in colors}
            observed_mask_ids.update(values)
            if not values.issubset(valid_mask_ids):
                invalid_masks.append(f"{row['floor_key']}: invalid values {sorted(values - valid_mask_ids)}")
            if not (values - {0}):
                try:
                    expected_rooms = _expected_room_count(mask_path.parent)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    unexpected_empty_masks.append(f"{row['floor_key']}: cannot validate negative mask: {exc}")
                else:
                    if expected_rooms:
                        unexpected_empty_masks.append(
                            f"{row['floor_key']}: empty mask but {expected_rooms} TRAIN room records exist"
                        )
                    else:
                        negative_masks += 1

    if missing_assets:
        errors.append(f"{len(missing_assets)} selected train/val assets are missing")
    if invalid_masks:
        errors.append(f"{len(invalid_masks)} train/val masks have invalid class IDs or mode")
    if unexpected_empty_masks:
        errors.append(f"{len(unexpected_empty_masks)} train/val masks are unexpectedly empty")
    missing_classes = sorted(set(range(1, len(EXPECTED_CLASSES) + 1)) - observed_mask_ids)
    if missing_classes:
        errors.append(f"train/val masks do not cover class IDs: {missing_classes}")

    label_status = dataset.get("label_contract", {}).get("status")
    adapter_ready = label_status == "YOLO_INSTANCE_POLYGONS_FROZEN"
    if not adapter_ready:
        errors.append(
            "YOLOv8m-seg requires instance polygon TXT labels, but the frozen manifest "
            "currently references semantic PNG masks; deterministic adapter output is not frozen"
        )

    weights_path = (Path(__file__).resolve().parents[2] / config.get("model", {}).get("initialization_weights", ""))
    weights_sha = None
    if weights_path.is_file():
        weights_sha = _sha256(weights_path)
        if weights_sha != config["model"].get("initialization_sha256"):
            errors.append("initialization checkpoint SHA-256 mismatch")
    else:
        warnings.append(f"initialization checkpoint is not present at {weights_path}")

    return {
        "ready": not errors,
        "config_parsed": True,
        "manifest_path": str(manifest_path),
        "manifest_sha256": actual_manifest_sha,
        "manifest_sha_verified": actual_manifest_sha == dataset.get("manifest_sha256"),
        "selected_train_val_samples": len(selected),
        "split_counts": actual_counts,
        "missing_selected_assets": len(missing_assets),
        "invalid_masks": len(invalid_masks),
        "unexpected_empty_masks": len(unexpected_empty_masks),
        "intentional_negative_masks": negative_masks,
        "observed_mask_ids": sorted(observed_mask_ids),
        "excluded_floors_accidentally_included": accidental,
        "building_leakage_count": len(leakage),
        "duplicate_relationships_crossing_splits": summary.get("duplicate_relationships_crossing_splits"),
        "duplicate_clusters_crossing_splits": summary.get("duplicate_connected_clusters_crossing_splits"),
        "initialization_weights_sha256": weights_sha,
        "adapter_ready": adapter_ready,
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    report = validate_plan(args.config)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
