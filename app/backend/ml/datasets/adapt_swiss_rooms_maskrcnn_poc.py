"""Deterministic Swiss Dwellings room-mask POC for torchvision Mask R-CNN.

The frozen training manifest is the dataset index.  Canonical metric room
geometry is rasterized into one independent binary mask per authoritative room
and encoded as COCO uncompressed RLE.  This preserves interior rings and
overlapping instances without connected-component inference.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw
from shapely import from_wkt
from shapely.geometry import MultiPolygon, Polygon

SOURCE_MANIFEST_SHA256 = "6375b709932223b328de146282549807c4e2555526d4a2654ff216c68b377c4b"
YOLO_AUDIT_MANIFEST_SHA256 = "d200cb85320862cf1b42eb1ca97b588d51fe56fe0e61ecfdba4441cc37145020"
ADAPTER_VERSION = "swiss-dwellings-rooms-maskrcnn-coco-rle-poc-v1"
POC_SPLIT_QUOTAS = {"train": 72, "val": 12, "test": 12}
ROOM_CLASSES = (
    "bedroom", "bathroom", "kitchen", "living", "living_dining",
    "corridor", "storage", "balcony", "office", "utility", "stairs",
    "entry_lobby", "generic_room", "shaft",
)
CLASS_TO_ID = {name: index + 1 for index, name in enumerate(ROOM_CLASSES)}
EXCLUDED_FLOORS = {"5593", "5639", "5640"}


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


def _write_deterministic(path: Path, payload: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise ValueError(f"existing deterministic output differs: {path}")
        return
    _atomic_write(path, payload)


def _safe(value: Any) -> str:
    text = "".join(char if char.isalnum() or char in "_.-" else "_" for char in str(value)).strip("._")
    if not text:
        raise ValueError(f"unsafe empty path component: {value!r}")
    return text


def floor_stem(row: dict) -> str:
    return "__".join(_safe(row[key]) for key in ("site_id", "building_id", "plan_id", "floor_id"))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_supervision(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError(f"supervision is not a list: {path}")
    return value


def authoritative_rooms(records: Iterable[dict]) -> list[dict]:
    return [
        row for row in records
        if row.get("target_family") == "spaces"
        and row.get("mapping_state") == "TRAIN"
        and not row.get("excluded")
    ]


def _hash_rank(floor_key: str) -> str:
    return hashlib.sha256(f"{ADAPTER_VERSION}|{floor_key}".encode()).hexdigest()


def select_poc_floors(source_rows: list[dict], audit_manifest: dict) -> tuple[list[dict], dict]:
    """Select 96 floors deterministically without changing source split membership."""
    audit_rows = {row["floor_key"]: row for row in audit_manifest["floors"]}
    rejected_classes: dict[str, set[str]] = defaultdict(set)
    for item in audit_manifest["rejected_instances"]:
        rejected_classes[item["floor_key"]].add(item["class"])

    selected: list[dict] = []
    reasons: dict[str, list[str]] = defaultdict(list)
    for split, quota in POC_SPLIT_QUOTAS.items():
        candidates = [row for row in source_rows if row["split"] == split]
        chosen: dict[str, dict] = {}

        def take(rows: Iterable[dict], reason: str, limit: int) -> None:
            for row in rows:
                if len(chosen) >= quota or limit <= 0:
                    return
                key = row["floor_key"]
                if key not in chosen:
                    chosen[key] = row
                    reasons[key].append(reason)
                    limit -= 1

        def audit_count(row: dict) -> int:
            return int(audit_rows[row["floor_key"]]["authoritative_instance_count"])

        negatives = sorted((r for r in candidates if audit_count(r) == 0), key=lambda r: _hash_rank(r["floor_key"]))
        office = sorted((r for r in candidates if "office" in rejected_classes.get(r["floor_key"], set())), key=lambda r: _hash_rank(r["floor_key"]))
        stairs = sorted((r for r in candidates if "stairs" in rejected_classes.get(r["floor_key"], set())), key=lambda r: _hash_rank(r["floor_key"]))
        holes = sorted((r for r in candidates if audit_rows[r["floor_key"]]["rejected_instance_count"] > 0), key=lambda r: (-audit_rows[r["floor_key"]]["rejected_instance_count"], _hash_rank(r["floor_key"])))
        positives = [r for r in candidates if audit_count(r) > 0]
        simple = sorted(positives, key=lambda r: (audit_count(r), _hash_rank(r["floor_key"])))
        complex_rows = sorted(positives, key=lambda r: (-audit_count(r), _hash_rank(r["floor_key"])))
        take(negatives, "intentional_negative", 1)
        take(office, "hole_room_office", 2)
        take(stairs, "hole_room_stairs", 3)
        take(holes, "hole_containing_rooms", max(4, quota // 3))
        take(simple, "simple_floor", max(3, quota // 8))
        take(complex_rows, "complex_floor", max(3, quota // 8))
        take(sorted(candidates, key=lambda r: _hash_rank(r["floor_key"])), "deterministic_fill", quota)
        if len(chosen) != quota:
            raise ValueError(f"could not satisfy {split} POC quota: {len(chosen)}/{quota}")
        selected.extend(chosen.values())

    selected.sort(key=lambda row: (row["split"], row["building_key"], row["floor_key"]))
    selected_keys = {row["floor_key"] for row in selected}
    if len(selected_keys) != sum(POC_SPLIT_QUOTAS.values()):
        raise AssertionError("POC floor selection contains duplicates")
    if any(str(row["floor_id"]) in EXCLUDED_FLOORS for row in selected):
        raise AssertionError("excluded source-exception floor selected")
    return selected, {key: sorted(value) for key, value in sorted(reasons.items()) if key in selected_keys}


def _polygons(geometry) -> Iterable[Polygon]:
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms
    else:
        raise ValueError(f"room geometry is not polygonal: {geometry.geom_type}")


def rasterize_room(geometry_wkt: str, transform: dict) -> tuple[np.ndarray, int]:
    geometry = from_wkt(geometry_wkt)
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("authoritative room geometry is empty or invalid")
    width, height = map(int, transform["image_size_px"])
    minx, _, _, maxy = map(float, transform["source_bounds_m"])
    padding = float(transform["padding_m"])
    ppm = float(transform["pixels_per_metre"])

    def point(x: float, y: float) -> tuple[int, int]:
        return round((x - minx + padding) * ppm), round((maxy - y + padding) * ppm)

    image = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(image)
    ring_count = 0
    for polygon in _polygons(geometry):
        draw.polygon([point(x, y) for x, y, *_ in polygon.exterior.coords], fill=1)
        for interior in polygon.interiors:
            ring_count += 1
            draw.polygon([point(x, y) for x, y, *_ in interior.coords], fill=0)
    mask = np.asarray(image, dtype=np.uint8)
    if not mask.any():
        raise ValueError("authoritative room rasterized to an empty mask")
    return mask, ring_count


def encode_uncompressed_rle(mask: np.ndarray) -> dict:
    """COCO RLE uses column-major pixels and starts with the zero run."""
    if mask.ndim != 2 or mask.dtype != np.uint8:
        raise ValueError("RLE input must be a uint8 HxW mask")
    pixels = mask.reshape(-1, order="F")
    changes = np.flatnonzero(pixels[1:] != pixels[:-1]) + 1
    counts = np.diff(np.concatenate(([0], changes, [pixels.size]))).astype(int).tolist()
    if pixels.size and pixels[0] != 0:
        counts.insert(0, 0)
    return {"size": [int(mask.shape[0]), int(mask.shape[1])], "counts": counts}


def decode_uncompressed_rle(rle: dict) -> np.ndarray:
    height, width = map(int, rle["size"])
    counts = np.asarray(rle["counts"], dtype=np.int64)
    if np.any(counts < 0) or int(counts.sum()) != height * width:
        raise ValueError("RLE counts do not cover the declared mask")
    values = np.repeat(np.arange(counts.size, dtype=np.uint8) % 2, counts)
    return values.reshape((height, width), order="F")


def _bbox(mask: np.ndarray) -> list[float]:
    ys, xs = np.nonzero(mask)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    return [float(x0), float(y0), float(x1 - x0 + 1), float(y1 - y0 + 1)]


def _link_or_verify(source: Path, destination: Path, expected_sha: str | None) -> str:
    actual = sha256_file(source)
    if expected_sha and actual != expected_sha:
        raise ValueError(f"source image checksum mismatch: {source}")
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != actual:
            raise ValueError(f"existing POC image differs: {destination}")
        return "hardlink" if os.path.samefile(source, destination) else "copy"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        method = "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        method = "copy"
    if sha256_file(destination) != actual:
        raise ValueError(f"POC image materialization checksum mismatch: {destination}")
    return method


def build_poc(source_manifest_path: str | Path, yolo_audit_manifest_path: str | Path,
              output_root: str | Path) -> dict:
    source_manifest_path = Path(source_manifest_path).resolve()
    audit_path = Path(yolo_audit_manifest_path).resolve()
    output_root = Path(output_root).resolve()
    if sha256_file(source_manifest_path) != SOURCE_MANIFEST_SHA256:
        raise ValueError("frozen training manifest SHA-256 mismatch")
    if sha256_file(audit_path) != YOLO_AUDIT_MANIFEST_SHA256:
        raise ValueError("verified YOLO audit manifest SHA-256 mismatch")
    source = _load_json(source_manifest_path)
    audit = _load_json(audit_path)
    selected, reasons = select_poc_floors(source["eligible_floors"], audit)

    annotations_by_split: dict[str, dict] = {
        split: {"info": {"version": ADAPTER_VERSION}, "licenses": [],
                "categories": [{"id": i + 1, "name": name, "supercategory": "room"}
                               for i, name in enumerate(ROOM_CLASSES)],
                "images": [], "annotations": []}
        for split in POC_SPLIT_QUOTAS
    }
    annotation_ids = Counter()
    total_instances = 0
    total_hole_instances = 0
    total_hole_rings = 0
    materialization = Counter()
    floor_records = []
    buildings_by_split: dict[str, set[str]] = defaultdict(set)

    for row in selected:
        split = row["split"]
        buildings_by_split[split].add(row["building_key"])
        source_image = Path(row["rendered_input_path"])
        source_dir = source_image.parent
        metadata = _load_json(source_dir / "metadata.json")
        records = _load_supervision(source_dir / "supervision.json.gz")
        rooms = authoritative_rooms(records)
        stem = floor_stem(row)
        destination_image = output_root / "images" / split / f"{stem}.png"
        method = _link_or_verify(source_image, destination_image, row["output_hashes_sha256"].get("image.png"))
        materialization[method] += 1
        with Image.open(source_image) as image:
            width, height = image.size
        if list(map(int, metadata["transform"]["image_size_px"])) != [width, height]:
            raise ValueError(f"image/transform dimensions differ: {row['floor_key']}")
        coco = annotations_by_split[split]
        image_id = len(coco["images"]) + 1
        coco["images"].append({
            "id": image_id, "file_name": f"../images/{split}/{stem}.png",
            "width": width, "height": height, "floor_key": row["floor_key"],
            "site_id": row["site_id"], "building_id": row["building_id"],
            "plan_id": row["plan_id"], "floor_id": row["floor_id"],
        })
        floor_holes = 0
        for room in rooms:
            class_name = room.get("target_class")
            if class_name not in CLASS_TO_ID or int(room.get("target_class_id")) != CLASS_TO_ID[class_name]:
                raise ValueError(f"invalid frozen room class: {row['floor_key']} {class_name!r}")
            mask, rings = rasterize_room(room["geometry_wkt_metric"], metadata["transform"])
            rle = encode_uncompressed_rle(mask)
            if not np.array_equal(mask, decode_uncompressed_rle(rle)):
                raise AssertionError("RLE round-trip changed an authoritative mask")
            annotation_ids[split] += 1
            coco["annotations"].append({
                "id": annotation_ids[split], "image_id": image_id,
                "category_id": CLASS_TO_ID[class_name], "segmentation": rle,
                "area": int(mask.sum()), "bbox": _bbox(mask), "iscrowd": 0,
                "source_instance_id": room["geometry_id"],
                "interior_ring_count": rings,
            })
            total_instances += 1
            if rings:
                total_hole_instances += 1
                total_hole_rings += rings
                floor_holes += 1
        floor_records.append({
            "floor_key": row["floor_key"], "site_id": row["site_id"],
            "building_id": row["building_id"], "plan_id": row["plan_id"],
            "floor_id": row["floor_id"], "building_key": row["building_key"],
            "split": split, "selection_reasons": reasons[row["floor_key"]],
            "authoritative_instance_count": len(rooms),
            "converted_instance_count": len(rooms),
            "hole_instance_count": floor_holes,
            "source_image_path": str(source_image.resolve()),
            "poc_image_path": str(destination_image.resolve()),
        })

    annotation_paths = {}
    output_hashes = {}
    for split, coco in annotations_by_split.items():
        path = output_root / "annotations" / f"instances_{split}.json"
        payload = (json.dumps(coco, sort_keys=True, separators=(",", ":")) + "\n").encode()
        _write_deterministic(path, payload)
        annotation_paths[split] = str(path.resolve())
        output_hashes[path.name] = hashlib.sha256(payload).hexdigest()

    leakage = set()
    splits = tuple(POC_SPLIT_QUOTAS)
    for index, left in enumerate(splits):
        for right in splits[index + 1:]:
            leakage.update(buildings_by_split[left] & buildings_by_split[right])
    if leakage:
        raise ValueError(f"building leakage in POC: {sorted(leakage)}")
    if source["summary"]["duplicate_relationships_crossing_splits"] != 0 \
            or source["summary"]["duplicate_connected_clusters_crossing_splits"] != 0:
        raise ValueError("frozen source manifest does not prove duplicate-cluster isolation")
    if any(str(item["floor_id"]) in EXCLUDED_FLOORS for item in floor_records):
        raise AssertionError("excluded floor entered POC")

    manifest = {
        "schema_version": 1,
        "adapter_version": ADAPTER_VERSION,
        "architecture_target": "torchvision-maskrcnn-resnet50-fpn-v2",
        "label_representation": "COCO instance segmentation with uncompressed RLE",
        "source_training_manifest_path": str(source_manifest_path),
        "source_training_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "selection_audit_manifest_path": str(audit_path),
        "selection_audit_manifest_sha256": YOLO_AUDIT_MANIFEST_SHA256,
        "taxonomy": [{"id": i + 1, "name": name} for i, name in enumerate(ROOM_CLASSES)],
        "selection_policy": {"split_quotas": POC_SPLIT_QUOTAS,
                             "rule": "fixed quotas; negatives, hole rooms, rare office/stairs, simple/complex, hash fill"},
        "annotation_paths": annotation_paths,
        "floors": floor_records,
        "summary": {
            "floor_count": len(floor_records),
            "floors_by_split": dict(Counter(row["split"] for row in floor_records)),
            "buildings_by_split": {split: len(values) for split, values in buildings_by_split.items()},
            "authoritative_instance_count": total_instances,
            "converted_instance_count": total_instances,
            "dropped_instance_count": 0,
            "hole_instance_count": total_hole_instances,
            "interior_ring_count": total_hole_rings,
            "intentional_negative_floor_count": sum(row["authoritative_instance_count"] == 0 for row in floor_records),
            "building_leakage_count": 0,
            "duplicate_relationships_crossing_splits": 0,
            "duplicate_connected_clusters_crossing_splits": 0,
            "excluded_floors_present": False,
            "image_materialization_methods": dict(materialization),
        },
        "output_hashes_sha256": output_hashes,
    }
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    manifest_path = output_root / "poc-manifest.json"
    manifest_sha = hashlib.sha256(payload).hexdigest()
    _atomic_write(manifest_path, payload)
    _atomic_write(manifest_path.with_suffix(".json.sha256"), f"{manifest_sha}  {manifest_path.name}\n".encode("ascii"))
    return {"output_path": str(output_root), "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_sha, "summary": manifest["summary"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--yolo-audit-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build_poc(args.source_manifest, args.yolo_audit_manifest, args.output), indent=2))


if __name__ == "__main__":
    main()
