"""Freeze and validate the bounded Task 7 Mask R-CNN training package."""

from __future__ import annotations

import hashlib
import json
import zipfile
import argparse
from collections import defaultdict
from pathlib import Path


EXPECTED_TAXONOMY = [
    "bedroom", "bathroom", "kitchen", "living", "living_dining",
    "corridor", "storage", "balcony", "office", "utility", "stairs",
    "entry_lobby", "generic_room", "shaft",
]
EXPECTED_SPLITS = {"train": 11337, "val": 1362, "test": 1203}
TASK7_KAGGLE_SOURCE_FILES = [
    "app/backend/ml/__init__.py",
    "app/backend/ml/training/__init__.py",
    "app/backend/ml/training/maskrcnn_rooms.py",
    "app/backend/ml/training/maskrcnn_task7_ops.py",
    "app/backend/ml/training/maskrcnn_task7_package.py",
    "app/backend/ml/training/maskrcnn_task7_train.py",
    "app/backend/ml/training/requirements-maskrcnn-task7.txt",
    "app/backend/ml/training/TASK7_KAGGLE_OPERATIONS.md",
    "app/backend/ml/training/configs/swiss_dwellings_rooms_maskrcnn_task7_bounded_v1.json",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_member(name: str) -> str:
    return name.replace("\\", "/").lstrip("./")


def portable_basename(value: str | Path) -> str:
    """Return a basename for either Windows or POSIX manifest paths."""
    name = str(value).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not name:
        raise ValueError(f"asset path has no filename: {value!r}")
    return name


def _finish_tree_hash(rows) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for relative, size, content_sha256 in sorted(rows):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(content_sha256.encode("ascii"))
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def directory_tree_sha256(root: str | Path) -> tuple[str, int]:
    """Hash relative paths, sizes and bytes for an extracted Kaggle dataset."""
    root = Path(root)
    rows = []
    for path in root.rglob("*"):
        if path.is_file():
            rows.append((_normalized_member(path.relative_to(root).as_posix()), path.stat().st_size, sha256_file(path)))
    return _finish_tree_hash(rows)


def zip_tree_sha256(path: str | Path) -> tuple[str, int]:
    """Produce the same content hash as the archive's extracted directory."""
    rows = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            content_hash = hashlib.sha256()
            with archive.open(info) as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    content_hash.update(chunk)
            rows.append((_normalized_member(info.filename), info.file_size, content_hash.hexdigest()))
    return _finish_tree_hash(rows)


def _asset_path(root: Path, row: dict, key: str, family: str) -> Path:
    original = Path(row[key])
    if original.is_file():
        return original
    return root / family / row["split"] / portable_basename(row[key])


def validate_package(
    config_path: str | Path,
    adapter_root: str | Path,
    initialization_path: str | Path,
    *, verify_all_assets: bool = True,
) -> dict:
    """Validate immutable inputs without reading the locked test labels."""
    config_path = Path(config_path)
    adapter_root = Path(adapter_root)
    initialization_path = Path(initialization_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest_path = adapter_root / config["dataset"]["adapter_manifest_filename"]
    manifest_hash = sha256_file(manifest_path)
    if manifest_hash != config["dataset"]["adapter_manifest_sha256"]:
        raise ValueError("frozen adapter manifest checksum mismatch")
    if sha256_file(initialization_path) != config["initialization"]["sha256"]:
        raise ValueError("initialization checkpoint checksum mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    taxonomy = [row["name"] for row in manifest["taxonomy"]]
    if taxonomy != EXPECTED_TAXONOMY or taxonomy != config["taxonomy"]:
        raise ValueError("frozen taxonomy mismatch")
    summary = manifest["summary"]
    if summary["floors_by_split"] != EXPECTED_SPLITS:
        raise ValueError("frozen split counts mismatch")
    if summary["building_leakage_count"] != 0:
        raise ValueError("building leakage detected")
    if summary["duplicate_relationships_crossing_splits"] != 0:
        raise ValueError("duplicate relationship leakage detected")
    if summary["duplicate_connected_clusters_crossing_splits"] != 0:
        raise ValueError("duplicate-cluster leakage detected")
    if summary["rejected_instance_count"] != 0:
        raise ValueError("adapter contains rejected instances")
    counts = defaultdict(int)
    buildings = defaultdict(set)
    missing = []
    for row in manifest["floors"]:
        split = row["split"]
        counts[split] += 1
        buildings[split].add(row["building_key"])
        if verify_all_assets:
            image = _asset_path(adapter_root, row, "image_path", "images")
            annotation = _asset_path(adapter_root, row, "annotation_path", "annotations")
            if not image.is_file():
                missing.append(str(image))
            if not annotation.is_file():
                missing.append(str(annotation))
    if dict(counts) != EXPECTED_SPLITS:
        raise ValueError("floor membership differs from frozen splits")
    if set(buildings["train"]) & set(buildings["val"] | buildings["test"]):
        raise ValueError("train building leakage")
    if set(buildings["val"]) & set(buildings["test"]):
        raise ValueError("validation/test building leakage")
    if missing:
        raise ValueError(f"missing adapter assets: {len(missing)}")
    if config["dataset"]["test_policy"] != "LOCKED_UNTOUCHED_UNTIL_FINAL_EVALUATION":
        raise ValueError("test split is not locked")
    return {
        "status": "PASS",
        "config_sha256": sha256_file(config_path),
        "adapter_manifest_sha256": manifest_hash,
        "initialization_sha256": sha256_file(initialization_path),
        "floors_by_split": dict(counts),
        "buildings_by_split": {key: len(value) for key, value in buildings.items()},
        "authoritative_instances": summary["authoritative_instance_count"],
        "hole_instances": summary["hole_instance_count"],
        "intentional_negative_floors": summary["intentional_negative_floor_count"],
        "missing_assets": len(missing),
        "test_labels_read": False,
    }


def write_lock(path: str | Path, validation: dict, config: dict) -> Path:
    path = Path(path)
    payload = {
        "schema_version": 1,
        "run_id": config["run_id"],
        "status": "FROZEN_NOT_STARTED",
        "validation": validation,
        "runtime": config["runtime"],
        "training": config["training"],
        "evaluation": config["evaluation"],
        "acceptance": config["acceptance"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_source_zip(repo_root: str | Path, output_path: str | Path, files: list[str]) -> Path:
    """Write a byte-reproducible source-only archive for Kaggle."""
    repo_root, output_path = Path(repo_root), Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sorted(files):
            source = repo_root / relative
            info = zipfile.ZipInfo(relative.replace("\\", "/"), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())
    return output_path


def write_kaggle_package_manifest(path: str | Path, artifacts: dict[str, str | Path]) -> Path:
    """Freeze checksums for external upload artifacts without embedding secrets."""
    path = Path(path)
    rows = []
    for role, artifact in sorted(artifacts.items()):
        artifact = Path(artifact)
        row = {
            "role": role, "filename": artifact.name,
            "bytes": artifact.stat().st_size, "sha256": sha256_file(artifact),
        }
        if artifact.suffix.lower() == ".zip":
            row["extracted_tree_sha256"], row["extracted_file_count"] = zip_tree_sha256(artifact)
        rows.append(row)
    payload = {
        "schema_version": 1,
        "package_version": "takeoff-task7-maskrcnn-bounded-v1",
        "status": "FROZEN_NOT_STARTED",
        "artifacts": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_task7_trainer_bundle(
    repo_root: str | Path, output_path: str | Path, *, source_commit: str,
) -> dict:
    """Build a byte-reproducible, source-only Task 7 Kaggle bundle."""
    repo_root, output_path = Path(repo_root), Path(output_path)
    if not source_commit or any(character.isspace() for character in source_commit):
        raise ValueError("source_commit must be a non-empty Git revision")
    rows = []
    for relative in TASK7_KAGGLE_SOURCE_FILES:
        source = repo_root / relative
        if not source.is_file():
            raise FileNotFoundError(f"missing Task 7 package source: {source}")
        rows.append({
            "path": relative.replace("\\", "/"),
            "bytes": source.stat().st_size,
            "sha256": sha256_file(source),
        })
    manifest = {
        "schema_version": 2,
        "package": "takeoff-task7-m76-kaggle-trainer",
        "source_commit": source_commit,
        "files": rows,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
    ) as archive:
        for row in rows:
            source = repo_root / row["path"]
            info = zipfile.ZipInfo(row["path"], (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())
        info = zipfile.ZipInfo("PACKAGE_MANIFEST.json", (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, manifest_bytes)
    with zipfile.ZipFile(output_path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"Task 7 bundle CRC failure: {bad_member}")
    return {
        "archive": str(output_path.resolve()),
        "archive_sha256": sha256_file(output_path),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_commit": source_commit,
        "source_file_count": len(rows),
        "archive_file_count": len(rows) + 1,
        "zip_crc": "PASS",
    }


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the Task 7 Kaggle trainer bundle")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build_task7_trainer_bundle(
        args.repo_root, args.output, source_commit=args.source_commit,
    ), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
