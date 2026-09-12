"""Convert an audited Swiss Dwellings sample into deterministic supervision.

Safety is intentional: this command refuses more than ten buildings or one
hundred floor occurrences. It is a bounded-pilot converter, not a full-corpus
pipeline. Source CSVs are read-only and all generated data belongs outside Git.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from PIL import Image, ImageDraw
from shapely import set_precision, wkt
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


CONVERSION_VERSION = "swiss-dwellings-takeoff-pilot-v1"
SOURCE_VERSION = "3.0.0"
SOURCE_DOI = "10.5281/zenodo.7788422"
DEFAULT_PPM = 16
DEFAULT_PADDING_M = 2.0
MAX_PILOT_BUILDINGS = 10
MAX_PILOT_FLOORS = 100
MAX_DIMENSION_PX = 4096
FLOOR_COLUMNS = ("site_id", "building_id", "plan_id", "floor_id")
REQUIRED_COLUMNS = {
    "apartment_id", "site_id", "building_id", "plan_id", "floor_id", "unit_id",
    "area_id", "unit_usage", "entity_type", "entity_subtype", "geometry",
    "elevation", "height",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_token(value: object) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in str(value))


def _floor_key(row: pd.Series) -> tuple[str, str, str, str]:
    return tuple(str(row[column]).strip() for column in FLOOR_COLUMNS)


def _building_key(site_id: object, building_id: object) -> str:
    return f"{str(site_id).strip()}::{str(building_id).strip()}"


def load_taxonomy(path: str | Path) -> dict:
    taxonomy = json.loads(Path(path).read_text(encoding="utf-8"))
    if taxonomy.get("conversion_version") != CONVERSION_VERSION:
        raise ValueError("taxonomy conversion_version does not match converter")
    for family in ("spaces", "separators", "doors", "windows"):
        if not taxonomy.get(family, {}).get("classes"):
            raise ValueError(f"taxonomy missing {family}.classes")
    return taxonomy


def load_pilot(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"pilot CSV missing required columns: {missing}")
    if frame.empty:
        raise ValueError("pilot CSV is empty")
    for column in FLOOR_COLUMNS:
        if frame[column].str.strip().eq("").any():
            raise ValueError(f"pilot CSV contains blank required ID: {column}")
    building_count = frame[["site_id", "building_id"]].drop_duplicates().shape[0]
    floor_count = frame[list(FLOOR_COLUMNS)].drop_duplicates().shape[0]
    if building_count > MAX_PILOT_BUILDINGS:
        raise ValueError(f"bounded converter refuses {building_count} buildings (max {MAX_PILOT_BUILDINGS})")
    if floor_count > MAX_PILOT_FLOORS:
        raise ValueError(f"bounded converter refuses {floor_count} floors (max {MAX_PILOT_FLOORS})")
    return frame


def deduplicate_floor_geometry(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Collapse only identical, same-semantic geometry on the same floor."""
    records: dict[tuple, dict] = {}
    before_by_family = Counter()
    for zero_index, row in frame.iterrows():
        try:
            geometry = wkt.loads(row.geometry)
        except Exception as exc:
            raise ValueError(f"unparseable WKT at CSV row {zero_index + 2}: {exc}") from exc
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"invalid/empty geometry at CSV row {zero_index + 2}")
        normalized = geometry.normalize()
        geometry_hash = _sha256_bytes(normalized.wkb)
        entity_type = row.entity_type.strip().upper()
        subtype = row.entity_subtype.strip().upper() or "NOT_DEFINED"
        before_by_family[entity_type] += 1
        floor = _floor_key(row)
        key = (*floor, entity_type, subtype, geometry_hash)
        source = {
            "source_row_number": int(zero_index) + 2,
            "apartment_id": row.apartment_id.strip(),
            "unit_id": row.unit_id.strip(),
            "area_id": row.area_id.strip(),
        }
        if key not in records:
            geometry_id = _sha256_bytes(
                ("|".join((SOURCE_VERSION, *floor, entity_type, subtype, geometry_hash))).encode("utf-8")
            )
            records[key] = {
                **{column: floor[index] for index, column in enumerate(FLOOR_COLUMNS)},
                "entity_type": entity_type,
                "entity_subtype": subtype,
                "geometry": geometry.wkt,
                "_geometry": geometry,
                "geometry_hash": geometry_hash,
                "geometry_id": geometry_id,
                "source_rows": [source],
                "unit_usage": row.unit_usage.strip(),
                "elevation": row.elevation.strip(),
                "height": row.height.strip(),
            }
        else:
            records[key]["source_rows"].append(source)

    output = pd.DataFrame(records.values())
    output = output.sort_values(
        [*FLOOR_COLUMNS, "entity_type", "entity_subtype", "geometry_hash"], kind="mergesort"
    ).reset_index(drop=True)
    after_by_family = Counter(output.entity_type)
    shared = output.source_rows.map(len)
    stats = {
        "before": int(len(frame)),
        "after": int(len(output)),
        "removed": int(len(frame) - len(output)),
        "before_by_entity_type": dict(sorted(before_by_family.items())),
        "after_by_entity_type": dict(sorted(after_by_family.items())),
        "collapsed_geometry_records": int((shared > 1).sum()),
        "maximum_source_rows_per_geometry": int(shared.max()),
        "source_rows_preserved": int(shared.sum()),
        "rule": "floor IDs + entity type + source subtype + normalized metric geometry",
    }
    return output, stats


def _polygons(geometry: BaseGeometry) -> Iterable[Polygon]:
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms


def _draw_geometry(draw: ImageDraw.ImageDraw, geometry: BaseGeometry, transform, fill):
    for polygon in _polygons(geometry):
        draw.polygon([transform(x, y) for x, y, *_ in polygon.exterior.coords], fill=fill)
        hole_fill = 0 if isinstance(fill, int) else (255, 255, 255)
        for interior in polygon.interiors:
            draw.polygon([transform(x, y) for x, y, *_ in interior.coords], fill=hole_fill)


def _mapping_for(row: pd.Series, taxonomy: dict) -> tuple[str | None, int | None, str | None]:
    entity_type, subtype = row.entity_type, row.entity_subtype
    if entity_type == "AREA":
        family = "spaces"
    elif entity_type == "SEPARATOR":
        family = "separators"
    elif entity_type == "OPENING" and "DOOR" in subtype:
        family = "doors"
    elif entity_type == "OPENING" and "WINDOW" in subtype:
        family = "windows"
    else:
        return None, None, "entity family is outside pilot targets"
    config = taxonomy[family]
    target = config["source_mapping"].get(subtype)
    if target is None:
        policy = config.get("review_policy", {}).get(subtype, {})
        reason = policy.get("reason") or config.get("excluded_or_ambiguous", {}).get(
            subtype, "source class is not approved"
        )
        return family, None, reason
    return family, int(config["classes"][target]), None


def _normalized_floor_shape(group: pd.DataFrame) -> tuple[str, BaseGeometry] | None:
    geometries = [geometry for geometry in group._geometry if geometry.area > 0]
    if not geometries:
        return None
    merged = unary_union(geometries)
    minx, miny, _, _ = merged.bounds
    normalized = set_precision(translate(merged, xoff=-minx, yoff=-miny), 0.01).normalize()
    return _sha256_bytes(normalized.wkb), normalized


class _UnionFind:
    def __init__(self, values: Iterable[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def assign_building_splits(frame: pd.DataFrame) -> tuple[dict[str, str], dict]:
    buildings = sorted({_building_key(row.site_id, row.building_id) for _, row in frame.iterrows()})
    union_find = _UnionFind(buildings)
    floor_shapes = []
    for floor, group in frame.groupby(list(FLOOR_COLUMNS), sort=True):
        result = _normalized_floor_shape(group)
        if result:
            floor_shapes.append((tuple(str(value) for value in floor), *result))

    exact_pairs, near_pairs = [], []
    for left_index, (left_floor, left_hash, left_shape) in enumerate(floor_shapes):
        left_building = _building_key(left_floor[0], left_floor[1])
        for right_floor, right_hash, right_shape in floor_shapes[left_index + 1:]:
            right_building = _building_key(right_floor[0], right_floor[1])
            if left_building == right_building:
                continue
            if left_hash == right_hash:
                exact_pairs.append({"left": list(left_floor), "right": list(right_floor)})
                union_find.union(left_building, right_building)
                continue
            area_ratio = min(left_shape.area, right_shape.area) / max(left_shape.area, right_shape.area)
            if area_ratio >= 0.98:
                distance = float(left_shape.hausdorff_distance(right_shape))
                if distance <= 0.10:
                    near_pairs.append({"left": list(left_floor), "right": list(right_floor),
                                       "area_ratio": area_ratio, "hausdorff_m": distance})
                    union_find.union(left_building, right_building)

    clusters: dict[str, list[str]] = defaultdict(list)
    for building in buildings:
        clusters[union_find.find(building)].append(building)
    ordered_clusters = sorted(
        (sorted(values) for values in clusters.values()),
        key=lambda values: _sha256_bytes((CONVERSION_VERSION + "|" + "|".join(values)).encode("utf-8")),
    )
    cluster_splits: dict[str, str] = {}
    if len(ordered_clusters) >= 3:
        cluster_splits["|".join(ordered_clusters[0])] = "test"
        cluster_splits["|".join(ordered_clusters[1])] = "val"
        for cluster in ordered_clusters[2:]:
            cluster_splits["|".join(cluster)] = "train"
    else:
        for index, cluster in enumerate(ordered_clusters):
            cluster_splits["|".join(cluster)] = ("val" if index == 0 else "train")
    assignments = {}
    for cluster in ordered_clusters:
        split = cluster_splits["|".join(cluster)]
        for building in cluster:
            assignments[building] = split
    return assignments, {
        "rule": "building-level duplicate clusters; no apartment/unit/page randomization",
        "clusters": ordered_clusters,
        "exact_cross_building_floor_pairs": exact_pairs,
        "near_cross_building_floor_pairs": near_pairs,
        "buildings_by_split": dict(Counter(assignments.values())),
    }


def _mask_values(path: Path) -> list[int]:
    with Image.open(path) as image:
        return sorted(set(image.get_flattened_data()))


def render_floor(group: pd.DataFrame, output_dir: Path, taxonomy: dict, *, pixels_per_metre: int,
                 padding_m: float, split: str, source_csv_sha256: str,
                 compress_supervision: bool = False,
                 conversion_version: str = CONVERSION_VERSION) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    geometries = list(group._geometry)
    minx = min(item.bounds[0] for item in geometries)
    miny = min(item.bounds[1] for item in geometries)
    maxx = max(item.bounds[2] for item in geometries)
    maxy = max(item.bounds[3] for item in geometries)
    width = int(math.ceil((maxx - minx + 2 * padding_m) * pixels_per_metre)) + 1
    height = int(math.ceil((maxy - miny + 2 * padding_m) * pixels_per_metre)) + 1
    if width <= 1 or height <= 1 or width > MAX_DIMENSION_PX or height > MAX_DIMENSION_PX:
        raise ValueError(f"floor output dimensions outside safe bounds: {width}x{height}")

    def transform(x: float, y: float) -> tuple[int, int]:
        return (round((x - minx + padding_m) * pixels_per_metre),
                round((maxy - y + padding_m) * pixels_per_metre))

    images = {
        "image": Image.new("RGB", (width, height), "white"),
        "room_semantic": Image.new("L", (width, height), 0),
        "room_instance": Image.new("I;16", (width, height), 0),
        "separator": Image.new("L", (width, height), 0),
        "door": Image.new("L", (width, height), 0),
        "window": Image.new("L", (width, height), 0),
    }
    draws = {name: ImageDraw.Draw(image) for name, image in images.items()}
    room_instance = 0
    yolo = {"doors": [], "windows": []}
    supervision = []
    class_counts = Counter()
    exclusion_counts = Counter()

    order = {"AREA": 0, "SEPARATOR": 1, "OPENING": 2, "FEATURE": 3}
    ordered = group.assign(_order=group.entity_type.map(order).fillna(9)).sort_values(
        ["_order", "entity_subtype", "geometry_hash"], kind="mergesort"
    )
    for _, row in ordered.iterrows():
        family, class_id, exclusion_reason = _mapping_for(row, taxonomy)
        target_name = None
        review_policy = taxonomy.get(family or "", {}).get("review_policy", {}).get(row.entity_subtype, {})
        if family and class_id:
            target_name = next(name for name, value in taxonomy[family]["classes"].items() if int(value) == class_id)
            class_counts[f"{family}:{target_name}"] += 1
        elif family:
            exclusion_counts[f"{family}:{row.entity_subtype}"] += 1
        geometry = row._geometry
        if family == "spaces" and class_id:
            room_instance += 1
            _draw_geometry(draws["room_semantic"], geometry, transform, class_id)
            _draw_geometry(draws["room_instance"], geometry, transform, room_instance)
            _draw_geometry(draws["image"], geometry, transform, (226, 236, 249))
        elif family == "separators" and class_id:
            _draw_geometry(draws["separator"], geometry, transform, class_id)
            _draw_geometry(draws["image"], geometry, transform, (35, 35, 35))
        elif family in {"doors", "windows"} and class_id:
            mask_name = "door" if family == "doors" else "window"
            color = (220, 80, 60) if family == "doors" else (40, 145, 230)
            _draw_geometry(draws[mask_name], geometry, transform, class_id)
            _draw_geometry(draws["image"], geometry, transform, color)
            x1, y1 = transform(geometry.bounds[0], geometry.bounds[3])
            x2, y2 = transform(geometry.bounds[2], geometry.bounds[1])
            left, right = sorted((max(0, x1), min(width - 1, x2)))
            top, bottom = sorted((max(0, y1), min(height - 1, y2)))
            cx, cy = ((left + right) / 2 / width, (top + bottom) / 2 / height)
            box_width, box_height = ((right - left) / width, (bottom - top) / height)
            yolo[family].append(f"{class_id - 1} {cx:.8f} {cy:.8f} {box_width:.8f} {box_height:.8f}")
        supervision.append({
            "geometry_id": row.geometry_id,
            "entity_type": row.entity_type,
            "source_subtype": row.entity_subtype,
            "target_family": family,
            "target_class": target_name,
            "target_class_id": class_id,
            "mapping_state": "TRAIN" if class_id is not None else review_policy.get(
                "mapping_state", "IGNORE_FOR_CURRENT_MODEL"
            ),
            "canonical_candidate": target_name if class_id is not None else review_policy.get(
                "canonical_takeoff_class"
            ),
            "excluded": class_id is None,
            "exclusion_reason": exclusion_reason,
            "geometry_wkt_metric": row.geometry,
            "source_rows": row.source_rows,
        })

    files = {
        "image": "image.png", "room_semantic": "room_semantic.png",
        "room_instance": "room_instance.png", "separator": "separator.png",
        "door": "door.png", "window": "window.png",
    }
    for name, filename in files.items():
        images[name].save(output_dir / filename, optimize=False, compress_level=9)
    (output_dir / "doors.txt").write_text("\n".join(yolo["doors"]) + ("\n" if yolo["doors"] else ""), encoding="utf-8")
    (output_dir / "windows.txt").write_text("\n".join(yolo["windows"]) + ("\n" if yolo["windows"] else ""), encoding="utf-8")

    first = ordered.iloc[0]
    ids = {column: str(first[column]) for column in FLOOR_COLUMNS}
    walls = [row._geometry for _, row in ordered.iterrows()
             if row.entity_type == "SEPARATOR" and row.entity_subtype == "WALL"]
    wall_union = unary_union(walls) if walls else None
    opening_distances = [float(row._geometry.distance(wall_union)) for _, row in ordered.iterrows()
                         if wall_union is not None and row.entity_type == "OPENING"
                         and ("DOOR" in row.entity_subtype or "WINDOW" in row.entity_subtype)]
    metadata = {
        "conversion_version": conversion_version,
        "source": {"dataset": "Swiss Dwellings", "version": SOURCE_VERSION, "doi": SOURCE_DOI,
                   "sample_csv_sha256": source_csv_sha256},
        "ids": ids,
        "split": split,
        "transform": {
            "coordinate_unit": "metre", "pixels_per_metre": pixels_per_metre,
            "padding_m": padding_m, "source_bounds_m": [minx, miny, maxx, maxy],
            "image_size_px": [width, height],
            "x_px": "(x-minx+padding_m)*pixels_per_metre",
            "y_px": "(maxy-y+padding_m)*pixels_per_metre",
            "x_m": "x_px/pixels_per_metre+minx-padding_m",
            "y_m": "maxy+padding_m-y_px/pixels_per_metre",
        },
        "taxonomy": {family: taxonomy[family]["classes"] for family in
                     ("spaces", "separators", "doors", "windows")},
        "counts": {
            "deduplicated_geometries": int(len(ordered)), "room_instances": room_instance,
            "door_labels": len(yolo["doors"]), "window_labels": len(yolo["windows"]),
            "class_counts": dict(sorted(class_counts.items())),
            "excluded_counts": dict(sorted(exclusion_counts.items())),
        },
        "opening_wall_alignment": {
            "count": len(opening_distances),
            "aligned_within_0_05m": sum(distance <= 0.05 for distance in opening_distances),
            "maximum_distance_m": max(opening_distances) if opening_distances else None,
        },
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if compress_supervision:
        encoded = (json.dumps(supervision, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        with (output_dir / "supervision.json.gz").open("wb") as raw_handle:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as compressed:
                compressed.write(encoded)
    else:
        (output_dir / "supervision.json").write_text(
            json.dumps(supervision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    hashes = {
        path.name: _sha256_file(path)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "hashes.json"
    }
    (output_dir / "hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "ids": ids, "split": split, "output_dir": str(output_dir), "width_px": width,
        "height_px": height, "counts": metadata["counts"], "hashes": hashes,
        "mask_values": {name: _mask_values(output_dir / filename) for name, filename in files.items()
                        if name != "image"},
        "opening_wall_alignment": metadata["opening_wall_alignment"],
    }


def _validate_render(render: dict, taxonomy: dict) -> list[str]:
    errors = []
    output_dir = Path(render["output_dir"])
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    expected_size = tuple(metadata["transform"]["image_size_px"])
    for name in ("image.png", "room_semantic.png", "room_instance.png", "separator.png", "door.png", "window.png"):
        with Image.open(output_dir / name) as image:
            if image.size != expected_size:
                errors.append(f"{render['ids']}: {name} size mismatch")
    allowed = {
        "room_semantic": {0, *map(int, taxonomy["spaces"]["classes"].values())},
        "separator": {0, *map(int, taxonomy["separators"]["classes"].values())},
        "door": {0, *map(int, taxonomy["doors"]["classes"].values())},
        "window": {0, *map(int, taxonomy["windows"]["classes"].values())},
    }
    for name, values in render["mask_values"].items():
        if name in allowed and not set(values).issubset(allowed[name]):
            errors.append(f"{render['ids']}: unknown values in {name}")
    transform = metadata["transform"]
    minx, miny, maxx, maxy = transform["source_bounds_m"]
    ppm, padding = transform["pixels_per_metre"], transform["padding_m"]
    for x, y in ((minx, miny), (maxx, maxy), ((minx + maxx) / 2, (miny + maxy) / 2)):
        x_px, y_px = (x - minx + padding) * ppm, (maxy - y + padding) * ppm
        x_back, y_back = x_px / ppm + minx - padding, maxy + padding - y_px / ppm
        if abs(x_back - x) > 1e-9 or abs(y_back - y) > 1e-9:
            errors.append(f"{render['ids']}: metric transform is not invertible")
    alignment = render["opening_wall_alignment"]
    if alignment["count"] and alignment["aligned_within_0_05m"] != alignment["count"]:
        errors.append(f"{render['ids']}: opening farther than 0.05m from wall")
    return errors


def _render_hashes_without_paths(render: dict) -> dict:
    return render["hashes"]


def convert_pilot(sample_csv: str | Path, output_root: str | Path, taxonomy_path: str | Path,
                  *, pixels_per_metre: int = DEFAULT_PPM, padding_m: float = DEFAULT_PADDING_M,
                  max_floors: int = MAX_PILOT_FLOORS, determinism_count: int = 3) -> dict:
    sample_csv, output_root = Path(sample_csv).resolve(), Path(output_root).resolve()
    taxonomy = load_taxonomy(taxonomy_path)
    raw_frame = load_pilot(sample_csv)
    deduplicated, dedup_stats = deduplicate_floor_geometry(raw_frame)
    floor_keys = sorted(tuple(map(str, key)) for key in deduplicated.groupby(list(FLOOR_COLUMNS)).groups)
    if len(floor_keys) > max_floors:
        raise ValueError(f"pilot contains {len(floor_keys)} floors; configured bound is {max_floors}")
    splits, split_evidence = assign_building_splits(deduplicated)
    source_hash = _sha256_file(sample_csv)
    renders = []
    class_counts, excluded_counts = Counter(), Counter()
    for floor in floor_keys:
        mask = pd.Series(True, index=deduplicated.index)
        for column, value in zip(FLOOR_COLUMNS, floor):
            mask &= deduplicated[column].astype(str) == value
        group = deduplicated[mask]
        split = splits[_building_key(floor[0], floor[1])]
        name = "__".join(_safe_token(value) for value in floor)
        rendered = render_floor(group, output_root / split / name, taxonomy,
                                pixels_per_metre=pixels_per_metre, padding_m=padding_m,
                                split=split, source_csv_sha256=source_hash)
        renders.append(rendered)
        class_counts.update(rendered["counts"]["class_counts"])
        excluded_counts.update(rendered["counts"]["excluded_counts"])

    validation_errors = []
    for rendered in renders:
        validation_errors.extend(_validate_render(rendered, taxonomy))
    leakage = defaultdict(set)
    for rendered in renders:
        ids = rendered["ids"]
        leakage[_building_key(ids["site_id"], ids["building_id"])].add(rendered["split"])
    split_leakage = {key: sorted(values) for key, values in leakage.items() if len(values) > 1}

    deterministic = []
    for rendered in renders[:min(determinism_count, len(renders))]:
        floor = tuple(rendered["ids"][column] for column in FLOOR_COLUMNS)
        mask = pd.Series(True, index=deduplicated.index)
        for column, value in zip(FLOOR_COLUMNS, floor):
            mask &= deduplicated[column].astype(str) == value
        with tempfile.TemporaryDirectory(prefix="swiss-conversion-repeat-") as temp_dir:
            repeat = render_floor(deduplicated[mask], Path(temp_dir), taxonomy,
                                  pixels_per_metre=pixels_per_metre, padding_m=padding_m,
                                  split=rendered["split"], source_csv_sha256=source_hash)
            deterministic.append({"ids": rendered["ids"],
                                  "identical": _render_hashes_without_paths(rendered) == _render_hashes_without_paths(repeat)})
    if not all(item["identical"] for item in deterministic):
        validation_errors.append("deterministic rerender hash mismatch")
    if split_leakage:
        validation_errors.append("building-level split leakage detected")

    manifest = {
        "manifest_version": 1,
        "conversion_version": CONVERSION_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {"dataset": "Swiss Dwellings", "version": SOURCE_VERSION, "doi": SOURCE_DOI,
                   "sample_csv": str(sample_csv), "sample_csv_sha256": source_hash},
        "bounded_pilot": {"max_buildings": MAX_PILOT_BUILDINGS, "max_floors": max_floors,
                          "actual_buildings": len(splits), "actual_floors": len(renders)},
        "rendering": {"pixels_per_metre": pixels_per_metre, "padding_m": padding_m,
                      "maximum_dimension_px": MAX_DIMENSION_PX, "distortion": "none"},
        "deduplication": dedup_stats,
        "splits": {"assignments": splits, "evidence": split_evidence, "leakage": split_leakage},
        "class_counts": dict(sorted(class_counts.items())),
        "excluded_counts": dict(sorted(excluded_counts.items())),
        "totals": {
            "room_instances": sum(item["counts"]["room_instances"] for item in renders),
            "wall_masks": sum(item["counts"]["class_counts"].get("separators:wall", 0) for item in renders),
            "door_labels": sum(item["counts"]["door_labels"] for item in renders),
            "window_labels": sum(item["counts"]["window_labels"] for item in renders),
            "empty_room_masks": sum(item["mask_values"]["room_semantic"] == [0] for item in renders),
            "empty_wall_masks": sum(item["mask_values"]["separator"] == [0] for item in renders),
            "empty_door_labels": sum(item["counts"]["door_labels"] == 0 for item in renders),
            "empty_window_labels": sum(item["counts"]["window_labels"] == 0 for item in renders),
        },
        "alignment": {
            "opening_labels": sum(item["opening_wall_alignment"]["count"] for item in renders),
            "aligned_within_0_05m": sum(item["opening_wall_alignment"]["aligned_within_0_05m"] for item in renders),
            "maximum_distance_m": max(
                (item["opening_wall_alignment"]["maximum_distance_m"] or 0 for item in renders), default=0
            ),
        },
        "determinism": deterministic,
        "validation_errors": validation_errors,
        "renders": renders,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "pilot_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                                       encoding="utf-8")
    if validation_errors:
        raise ValueError("pilot validation failed: " + "; ".join(validation_errors))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-csv", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--taxonomy", type=Path, default=Path(__file__).with_name("swiss_dwellings_taxonomy_v1.json"))
    parser.add_argument("--pixels-per-metre", type=int, default=DEFAULT_PPM)
    parser.add_argument("--padding-m", type=float, default=DEFAULT_PADDING_M)
    parser.add_argument("--max-floors", type=int, default=MAX_PILOT_FLOORS)
    parser.add_argument("--determinism-count", type=int, default=3)
    args = parser.parse_args(argv)
    if args.pixels_per_metre <= 0 or args.padding_m < 0:
        raise SystemExit("pixels-per-metre must be positive and padding non-negative")
    manifest = convert_pilot(args.sample_csv, args.output_root, args.taxonomy,
                             pixels_per_metre=args.pixels_per_metre, padding_m=args.padding_m,
                             max_floors=args.max_floors, determinism_count=args.determinism_count)
    print(json.dumps({
        "floors": manifest["bounded_pilot"]["actual_floors"],
        "deduplication": manifest["deduplication"],
        "totals": manifest["totals"],
        "alignment": manifest["alignment"],
        "splits": manifest["splits"]["evidence"]["buildings_by_split"],
        "deterministic": all(item["identical"] for item in manifest["determinism"]),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
