"""Resumable Swiss Dwellings -> sharded COCO-RLE room adapter.

The frozen training manifest is authoritative.  Each floor is converted in
isolation and committed to a SQLite checkpoint only after its image and COCO
annotation shard have been verified.  Canonical metric WKT is rasterized
directly; connected components and polygon approximation are never used.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from ml.datasets.adapt_swiss_rooms_maskrcnn_poc import (
    CLASS_TO_ID,
    EXCLUDED_FLOORS,
    ROOM_CLASSES,
    authoritative_rooms,
    decode_uncompressed_rle,
    encode_uncompressed_rle,
    floor_stem,
    rasterize_room,
    sha256_file,
)


SOURCE_MANIFEST_SHA256 = "6375b709932223b328de146282549807c4e2555526d4a2654ff216c68b377c4b"
ADAPTER_VERSION = "swiss-dwellings-rooms-maskrcnn-coco-rle-full-v1"
EXPECTED_FLOORS = 13_902
SPLITS = ("train", "val", "test")


def _canonical_json(value: Any, *, indent: int | None = None) -> bytes:
    return (json.dumps(value, indent=indent, sort_keys=True, separators=(",", ":") if indent is None else None)
            + "\n").encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _write_deterministic(path: Path, payload: bytes) -> bool:
    """Write once, verify thereafter; return True only for a new file."""
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise ValueError(f"existing deterministic output differs: {path}")
        return False
    _atomic_write(path, payload)
    return True


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_supervision(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError(f"supervision is not a list: {path}")
    return value


def _link_or_verify(source: Path, destination: Path, expected_sha: str | None) -> tuple[str, bool]:
    actual = sha256_file(source)
    if expected_sha and actual != expected_sha:
        raise ValueError(f"frozen image checksum mismatch: {source}")
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != actual:
            raise ValueError(f"existing adapter image differs: {destination}")
        try:
            method = "hardlink" if os.path.samefile(source, destination) else "copy"
        except OSError:
            method = "copy"
        return method, False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        method = "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        method = "copy"
    if sha256_file(destination) != actual:
        destination.unlink(missing_ok=True)
        raise ValueError(f"adapter image checksum mismatch after {method}: {destination}")
    return method, True


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS floors (
            ordinal INTEGER NOT NULL,
            floor_key TEXT PRIMARY KEY,
            split TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            record_json TEXT NOT NULL,
            error_json TEXT,
            annotation_sha256 TEXT,
            image_sha256 TEXT,
            authoritative_count INTEGER,
            converted_count INTEGER,
            rejected_count INTEGER,
            hole_instance_count INTEGER,
            interior_ring_count INTEGER,
            image_materialization TEXT
        )
        """
    )
    connection.commit()
    return connection


def _initialize_state(connection: sqlite3.Connection, rows: list[dict]) -> None:
    existing = connection.execute("SELECT COUNT(*) FROM floors").fetchone()[0]
    if existing not in (0, len(rows)):
        raise ValueError(f"checkpoint/source floor count differs: {existing}/{len(rows)}")
    for ordinal, row in enumerate(rows):
        record_json = json.dumps(row, sort_keys=True, separators=(",", ":"))
        found = connection.execute(
            "SELECT ordinal, split, record_json FROM floors WHERE floor_key = ?", (row["floor_key"],)
        ).fetchone()
        if found:
            if found["ordinal"] != ordinal or found["split"] != row["split"] or found["record_json"] != record_json:
                raise ValueError(f"checkpoint source record differs: {row['floor_key']}")
        else:
            connection.execute(
                "INSERT INTO floors(ordinal, floor_key, split, record_json) VALUES (?, ?, ?, ?)",
                (ordinal, row["floor_key"], row["split"], record_json),
            )
    connection.commit()


def _floor_paths(output_root: Path, row: dict) -> tuple[Path, Path]:
    stem = floor_stem(row)
    return (
        output_root / "images" / row["split"] / f"{stem}.png",
        output_root / "annotations" / row["split"] / f"{stem}.json",
    )


def _annotation_shard(row: dict, source_image: Path, metadata: dict, records: Iterable[dict]) -> tuple[dict, dict]:
    transform = metadata["transform"]
    with Image.open(source_image) as image:
        width, height = image.size
    if list(map(int, transform["image_size_px"])) != [width, height]:
        raise ValueError("image/transform dimensions differ")

    rooms = sorted(authoritative_rooms(records), key=lambda item: (
        int(item.get("target_class_id", 0)), str(item.get("geometry_id", ""))
    ))
    annotations: list[dict] = []
    rejected: list[dict] = []
    hole_instances = 0
    interior_rings = 0
    for room in rooms:
        class_name = room.get("target_class")
        try:
            if class_name not in CLASS_TO_ID or int(room.get("target_class_id")) != CLASS_TO_ID[class_name]:
                raise ValueError("UNKNOWN_OR_MISMATCHED_CLASS")
            mask, rings = rasterize_room(room["geometry_wkt_metric"], transform)
            rle = encode_uncompressed_rle(mask)
            if not (mask == decode_uncompressed_rle(rle)).all():
                raise ValueError("RLE_ROUND_TRIP_MISMATCH")
            ys, xs = mask.nonzero()
            annotation = {
                "id": len(annotations) + 1,
                "image_id": 1,
                "category_id": CLASS_TO_ID[class_name],
                "segmentation": rle,
                "area": int(mask.sum()),
                "bbox": [float(xs.min()), float(ys.min()),
                         float(xs.max() - xs.min() + 1), float(ys.max() - ys.min() + 1)],
                "iscrowd": 0,
                "source_instance_id": room.get("geometry_id"),
                "source_geometry_wkt_metric": room["geometry_wkt_metric"],
                "source_geometry_sha256": hashlib.sha256(
                    room["geometry_wkt_metric"].encode("utf-8")
                ).hexdigest(),
                "interior_ring_count": rings,
            }
            annotations.append(annotation)
            if rings:
                hole_instances += 1
                interior_rings += rings
        except Exception as exc:  # rejection is evidence, never a silent drop
            rejected.append({
                "source_instance_id": room.get("geometry_id"),
                "class": class_name,
                "reason": str(exc) or type(exc).__name__,
                "exception_type": type(exc).__name__,
            })

    shard = {
        "schema_version": 1,
        "adapter_version": ADAPTER_VERSION,
        "categories": [{"id": value, "name": name, "supercategory": "room"}
                       for name, value in CLASS_TO_ID.items()],
        "image": {
            "id": 1,
            "file_name": str(source_image.resolve()),
            "width": width,
            "height": height,
            "floor_key": row["floor_key"],
            "site_id": row["site_id"],
            "building_id": row["building_id"],
            "plan_id": row["plan_id"],
            "floor_id": row["floor_id"],
        },
        "annotations": annotations,
        "rejected_instances": rejected,
    }
    stats = {
        "authoritative_count": len(rooms),
        "converted_count": len(annotations),
        "rejected_count": len(rejected),
        "hole_instance_count": hole_instances,
        "interior_ring_count": interior_rings,
    }
    if stats["authoritative_count"] != stats["converted_count"] + stats["rejected_count"]:
        raise AssertionError("floor instance reconciliation failed")
    return shard, stats


def _verify_completed(output_root: Path, row: dict, state: sqlite3.Row) -> None:
    image_path, annotation_path = _floor_paths(output_root, row)
    if not image_path.is_file() or sha256_file(image_path) != state["image_sha256"]:
        raise ValueError(f"completed image checksum mismatch: {row['floor_key']}")
    if not annotation_path.is_file() or sha256_file(annotation_path) != state["annotation_sha256"]:
        raise ValueError(f"completed annotation checksum mismatch: {row['floor_key']}")


def _process_floor(output_root: Path, row: dict) -> tuple[dict, dict, str, bool]:
    source_image = Path(row["rendered_input_path"])
    source_dir = source_image.parent
    metadata_path = source_dir / "metadata.json"
    supervision_path = source_dir / "supervision.json.gz"
    instance_mask_path = source_dir / "room_instance.png"
    for path in (source_image, metadata_path, supervision_path, instance_mask_path):
        if not path.is_file():
            raise FileNotFoundError(f"required frozen artifact missing: {path}")
    expected_image_sha = row.get("output_hashes_sha256", {}).get("image.png")
    image_path, annotation_path = _floor_paths(output_root, row)
    method, image_written = _link_or_verify(source_image, image_path, expected_image_sha)
    shard, stats = _annotation_shard(row, image_path, _load_json(metadata_path), _load_supervision(supervision_path))
    shard["image"]["file_name"] = str(image_path.resolve())
    payload = _canonical_json(shard)
    annotation_written = _write_deterministic(annotation_path, payload)
    record = {
        "floor_key": row["floor_key"], "site_id": row["site_id"],
        "building_id": row["building_id"], "building_key": row["building_key"],
        "plan_id": row["plan_id"], "floor_id": row["floor_id"], "split": row["split"],
        "image_path": str(image_path.resolve()), "annotation_path": str(annotation_path.resolve()),
        "source_metric_supervision_path": str(supervision_path.resolve()),
        "source_room_instance_mask_path": str(instance_mask_path.resolve()),
        "image_sha256": sha256_file(image_path),
        "annotation_sha256": hashlib.sha256(payload).hexdigest(),
        **stats,
    }
    return record, stats, method, image_written or annotation_written


def _publish_manifest(source_manifest_path: Path, source: dict, output_root: Path,
                      connection: sqlite3.Connection) -> dict:
    state_rows = connection.execute("SELECT * FROM floors ORDER BY ordinal").fetchall()
    if any(row["status"] not in ("succeeded", "rejected") for row in state_rows):
        raise ValueError("cannot publish a manifest while floors remain pending or failed")
    floors: list[dict] = []
    failures: list[dict] = []
    buildings: dict[str, set[str]] = defaultdict(set)
    summary = Counter()
    for state in state_rows:
        row = json.loads(state["record_json"])
        image_path, annotation_path = _floor_paths(output_root, row)
        _verify_completed(output_root, row, state)
        shard = _load_json(annotation_path)
        rejection_rows = shard["rejected_instances"]
        floors.append({
            "floor_key": row["floor_key"], "site_id": row["site_id"],
            "building_id": row["building_id"], "building_key": row["building_key"],
            "plan_id": row["plan_id"], "floor_id": row["floor_id"], "split": row["split"],
            "image_path": str(image_path.resolve()), "annotation_path": str(annotation_path.resolve()),
            "image_sha256": state["image_sha256"], "annotation_sha256": state["annotation_sha256"],
            "authoritative_instance_count": state["authoritative_count"],
            "converted_instance_count": state["converted_count"],
            "rejected_instance_count": state["rejected_count"],
            "hole_instance_count": state["hole_instance_count"],
            "interior_ring_count": state["interior_ring_count"],
        })
        for rejection in rejection_rows:
            failures.append({"floor_key": row["floor_key"], **rejection})
        buildings[row["split"]].add(row["building_key"])
        summary["authoritative"] += state["authoritative_count"]
        summary["converted"] += state["converted_count"]
        summary["rejected"] += state["rejected_count"]
        summary["holes"] += state["hole_instance_count"]
        summary["rings"] += state["interior_ring_count"]
        summary[f"floors_{row['split']}"] += 1
        summary["negatives"] += state["authoritative_count"] == 0

    leakage = ((buildings["train"] & buildings["val"]) |
               (buildings["train"] & buildings["test"]) |
               (buildings["val"] & buildings["test"]))
    source_summary = source["summary"]
    if leakage or source_summary["duplicate_relationships_crossing_splits"] != 0 \
            or source_summary["duplicate_connected_clusters_crossing_splits"] != 0:
        raise ValueError("frozen split leakage guarantee failed")
    if {split: summary[f"floors_{split}"] for split in SPLITS} != source_summary["eligible_floors_by_split"]:
        raise ValueError("full adapter split counts differ from frozen manifest")

    manifest = {
        "schema_version": 1,
        "adapter_version": ADAPTER_VERSION,
        "label_representation": "sharded COCO instance segmentation with uncompressed RLE",
        "architecture_target": "torchvision-maskrcnn-resnet50-fpn-v2",
        "source_training_manifest_path": str(source_manifest_path),
        "source_training_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "source_dataset_version": source["dataset"]["training_dataset_version"],
        "source_conversion_version": source["dataset"]["conversion_version"],
        "taxonomy": [{"id": value, "name": name} for name, value in CLASS_TO_ID.items()],
        "policy": {
            "instance_source": "canonical metric WKT in per-floor supervision.json.gz",
            "holes": "preserve in binary mask RLE", "connected_components": False,
            "polygon_approximation": False, "split_source": "frozen training manifest",
        },
        "summary": {
            "floor_count": len(floors),
            "floors_by_split": {split: summary[f"floors_{split}"] for split in SPLITS},
            "buildings_by_split": {split: len(buildings[split]) for split in SPLITS},
            "authoritative_instance_count": summary["authoritative"],
            "converted_instance_count": summary["converted"],
            "rejected_instance_count": summary["rejected"],
            "hole_instance_count": summary["holes"],
            "interior_ring_count": summary["rings"],
            "intentional_negative_floor_count": summary["negatives"],
            "missing_or_mismatched_file_count": 0,
            "building_leakage_count": 0,
            "duplicate_relationships_crossing_splits": 0,
            "duplicate_connected_clusters_crossing_splits": 0,
            "excluded_floors_present": False,
        },
        "floors": floors,
        "rejected_instances": failures,
    }
    payload = _canonical_json(manifest, indent=2)
    manifest_path = output_root / "full-adapter-manifest.json"
    manifest_sha = hashlib.sha256(payload).hexdigest()
    _write_deterministic(manifest_path, payload)
    _write_deterministic(manifest_path.with_suffix(".json.sha256"),
                         f"{manifest_sha}  {manifest_path.name}\n".encode("ascii"))
    return {"manifest_path": str(manifest_path), "manifest_sha256": manifest_sha,
            "summary": manifest["summary"]}


def build_full_adapter(source_manifest_path: str | Path, output_root: str | Path,
                       *, max_floors: int | None = None, progress_every: int = 0,
                       workers: int = 1) -> dict:
    source_manifest_path = Path(source_manifest_path).resolve()
    output_root = Path(output_root).resolve()
    source_sha = sha256_file(source_manifest_path)
    if source_sha != SOURCE_MANIFEST_SHA256:
        raise ValueError(f"source training-manifest SHA-256 mismatch: {source_sha}")
    source = _load_json(source_manifest_path)
    rows = source["eligible_floors"]
    if len(rows) != EXPECTED_FLOORS:
        raise ValueError(f"unexpected eligible floor count: {len(rows)}")
    if {str(row["floor_id"]) for row in rows} & EXCLUDED_FLOORS:
        raise ValueError("excluded source-exception floor appears in eligible rows")
    if len({row["floor_key"] for row in rows}) != len(rows):
        raise ValueError("duplicate floor key in frozen source manifest")

    state_path = output_root / "adapter-state.sqlite3"
    connection = _connect(state_path)
    _initialize_state(connection, rows)
    processed_now = 0
    rewritten_now = 0
    failures_now = 0
    try:
        pending_rows = []
        for row in rows:
            state = connection.execute("SELECT * FROM floors WHERE floor_key = ?", (row["floor_key"],)).fetchone()
            if state["status"] in ("succeeded", "rejected"):
                _verify_completed(output_root, row, state)
                continue
            if max_floors is not None and len(pending_rows) >= max_floors:
                break
            pending_rows.append(row)

        def commit_result(row: dict, result=None, error: Exception | None = None) -> None:
            nonlocal processed_now, rewritten_now, failures_now
            if error is None:
                record, stats, method, wrote = result
                status = "succeeded" if stats["rejected_count"] == 0 else "rejected"
                connection.execute(
                    """UPDATE floors SET status=?, error_json=NULL, annotation_sha256=?, image_sha256=?,
                       authoritative_count=?, converted_count=?, rejected_count=?, hole_instance_count=?,
                       interior_ring_count=?, image_materialization=? WHERE floor_key=?""",
                    (status, record["annotation_sha256"], record["image_sha256"],
                     stats["authoritative_count"], stats["converted_count"], stats["rejected_count"],
                     stats["hole_instance_count"], stats["interior_ring_count"], method, row["floor_key"]),
                )
                processed_now += 1
                rewritten_now += int(wrote)
            else:
                failures_now += 1
                payload = json.dumps({"type": type(error).__name__, "message": str(error)}, sort_keys=True)
                connection.execute("UPDATE floors SET status='failed', error_json=? WHERE floor_key=?",
                                   (payload, row["floor_key"]))
            connection.commit()
            if progress_every and processed_now and processed_now % progress_every == 0:
                complete_count = connection.execute(
                    "SELECT COUNT(*) FROM floors WHERE status IN ('succeeded', 'rejected')"
                ).fetchone()[0]
                print(json.dumps({"event": "progress", "floors_complete": complete_count,
                                  "floors_total": len(rows), "failures_now": failures_now}), flush=True)

        if workers > 1 and pending_rows:
            # Floor jobs are independent and CPU-heavy. The process count is
            # explicitly bounded; SQLite writes remain serialized here.
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_process_floor, output_root, row): row for row in pending_rows}
                for future in as_completed(futures):
                    row = futures[future]
                    try:
                        commit_result(row, result=future.result())
                    except Exception as exc:
                        commit_result(row, error=exc)
        else:
            for row in pending_rows:
                try:
                    commit_result(row, result=_process_floor(output_root, row))
                except Exception as exc:
                    commit_result(row, error=exc)
        counts = dict(connection.execute(
            "SELECT status, COUNT(*) FROM floors GROUP BY status"
        ).fetchall())
        complete = sum(counts.get(status, 0) for status in ("succeeded", "rejected")) == len(rows)
        result = {
            "output_path": str(output_root), "state_path": str(state_path),
            "processed_now": processed_now, "outputs_written_now": rewritten_now,
            "failures_now": failures_now, "status_counts": counts, "complete": complete,
        }
        if complete:
            result.update(_publish_manifest(source_manifest_path, source, output_root, connection))
        return result
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-floors", type=int)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args(argv)
    print(json.dumps(build_full_adapter(args.source_manifest, args.output, max_floors=args.max_floors,
                                        progress_every=args.progress_every, workers=args.workers),
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
