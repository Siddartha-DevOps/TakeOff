"""Extract and validate a complete-building Swiss Dwellings v3 sample.

The source CSVs are read-only. The first pass profiles buildings using IDs and
lightweight counts; a deterministic diversity sampler then selects complete
buildings. The second pass copies every matching row into an external sample
directory. Geometry validation is intentionally bounded to that sample.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from shapely import set_precision, wkt
from shapely.affinity import translate
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


DATASET = "Swiss Dwellings"
VERSION = "3.0.0"
DOI = "10.5281/zenodo.7788422"
ARCHIVE_BYTES = 931_868_205
ARCHIVE_MD5 = "3b7915ecd5bf8e492a3e78c598b74123"
REQUIRED_GEOMETRY_COLUMNS = {
    "site_id", "building_id", "plan_id", "floor_id", "apartment_id",
    "unit_id", "area_id", "unit_usage", "entity_type", "entity_subtype",
    "geometry", "elevation", "height",
}
CORE_IDS = ("site_id", "building_id", "plan_id", "floor_id")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _md5(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - comparison to the publisher's checksum
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _key(site_id: object, building_id: object) -> str:
    return f"{str(site_id).strip()}::{str(building_id).strip()}"


def _safe_float(value: object) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass
class BuildingProfile:
    site_id: str
    building_id: str
    rows: int = 0
    plans: set[str] = field(default_factory=set)
    floors: set[str] = field(default_factory=set)
    units: set[str] = field(default_factory=set)
    apartments: set[str] = field(default_factory=set)
    entity_types: Counter = field(default_factory=Counter)
    subtypes: Counter = field(default_factory=Counter)
    room_types: set[str] = field(default_factory=set)
    opening_types: Counter = field(default_factory=Counter)
    geometry_chars: int = 0

    def update(self, row: dict[str, str]) -> None:
        self.rows += 1
        for column, target in (
            ("plan_id", self.plans), ("floor_id", self.floors),
            ("unit_id", self.units), ("apartment_id", self.apartments),
        ):
            value = row.get(column, "").strip()
            if value:
                target.add(value)
        entity_type = row.get("entity_type", "").strip().upper()
        subtype = row.get("entity_subtype", "").strip().upper() or "<MISSING>"
        self.entity_types[entity_type or "<MISSING>"] += 1
        self.subtypes[subtype] += 1
        if entity_type == "AREA":
            self.room_types.add(subtype)
        elif entity_type == "OPENING":
            self.opening_types[subtype] += 1
        self.geometry_chars += len(row.get("geometry", ""))

    def summary(self) -> dict:
        openings = self.entity_types.get("OPENING", 0)
        return {
            "site_id": self.site_id,
            "building_id": self.building_id,
            "rows": self.rows,
            "plans": len(self.plans),
            "floors": len(self.floors),
            "units": len(self.units),
            "apartments": len(self.apartments),
            "area_rows": self.entity_types.get("AREA", 0),
            "separator_rows": self.entity_types.get("SEPARATOR", 0),
            "opening_rows": openings,
            "feature_rows": self.entity_types.get("FEATURE", 0),
            "room_type_count": len(self.room_types),
            "room_types": sorted(self.room_types),
            "opening_types": dict(sorted(self.opening_types.items())),
            "opening_density": openings / max(1, self.entity_types.get("AREA", 0)),
            "mean_geometry_chars": self.geometry_chars / max(1, self.rows),
        }


def _open_csv(path: Path):
    return path.open("r", encoding="utf-8-sig", newline="")


def profile_buildings(geometries_csv: str | Path) -> tuple[dict[str, BuildingProfile], list[str]]:
    path = Path(geometries_csv)
    profiles: dict[str, BuildingProfile] = {}
    with _open_csv(path) as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        missing = sorted(REQUIRED_GEOMETRY_COLUMNS - set(columns))
        if missing:
            raise ValueError(f"geometries.csv missing required columns: {missing}")
        for row in reader:
            site_id = row.get("site_id", "").strip()
            building_id = row.get("building_id", "").strip()
            key = _key(site_id, building_id)
            if key not in profiles:
                profiles[key] = BuildingProfile(site_id=site_id, building_id=building_id)
            profiles[key].update(row)
    return profiles, columns


def _feature_vector(summary: dict) -> list[float]:
    return [
        math.log1p(summary["rows"]), math.log1p(summary["plans"]),
        math.log1p(summary["floors"]), math.log1p(summary["units"]),
        math.log1p(summary["apartments"]), summary["room_type_count"],
        summary["opening_density"], math.log1p(summary["mean_geometry_chars"]),
    ]


def select_representative_buildings(profiles: dict[str, BuildingProfile], count: int = 8) -> list[str]:
    """Deterministic max-min diversity sampling over building-level features."""
    candidates = [(key, profile.summary()) for key, profile in sorted(profiles.items())]
    candidates = [(key, summary) for key, summary in candidates if summary["area_rows"] > 0]
    if len(candidates) < count:
        raise ValueError(f"only {len(candidates)} buildings contain areas; requested {count}")

    vectors = [_feature_vector(summary) for _, summary in candidates]
    dimensions = len(vectors[0])
    mins = [min(vector[index] for vector in vectors) for index in range(dimensions)]
    maxs = [max(vector[index] for vector in vectors) for index in range(dimensions)]
    normalized = [
        [(value - mins[index]) / (maxs[index] - mins[index]) if maxs[index] > mins[index] else 0.0
         for index, value in enumerate(vector)]
        for vector in vectors
    ]

    centroid = [sum(vector[index] for vector in normalized) / len(normalized) for index in range(dimensions)]
    start = min(
        range(len(candidates)),
        key=lambda idx: (sum((normalized[idx][j] - centroid[j]) ** 2 for j in range(dimensions)), candidates[idx][0]),
    )
    selected = [start]
    while len(selected) < count:
        remaining = [idx for idx in range(len(candidates)) if idx not in selected]
        next_index = max(
            remaining,
            key=lambda idx: (
                min(sum((normalized[idx][j] - normalized[chosen][j]) ** 2 for j in range(dimensions))
                    for chosen in selected),
                candidates[idx][0],
            ),
        )
        selected.append(next_index)
    return [candidates[index][0] for index in selected]


def _filter_csv(source: Path, destination: Path, selected: set[str]) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with _open_csv(source) as source_handle, destination.open("w", encoding="utf-8", newline="") as target_handle:
        reader = csv.DictReader(source_handle)
        columns = reader.fieldnames or []
        if "building_id" not in columns:
            raise ValueError(f"{source.name} does not contain building_id")
        writer = csv.DictWriter(target_handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            site_id = row.get("site_id", "").strip()
            building_id = row.get("building_id", "").strip()
            exact = _key(site_id, building_id)
            if exact in selected or (not site_id and any(key.endswith(f"::{building_id}") for key in selected)):
                writer.writerow(row)
                rows += 1
    return rows


def extract_sample(dataset_root: str | Path, sample_root: str | Path,
                   selected_keys: Iterable[str]) -> dict[str, int]:
    source_root = Path(dataset_root)
    target_root = Path(sample_root)
    selected = set(selected_keys)
    counts: dict[str, int] = {}
    for name in ("geometries.csv", "simulations.csv", "locations.csv", "location_ratings.csv"):
        source = source_root / name
        if source.is_file():
            counts[name] = _filter_csv(source, target_root / name, selected)
    return counts


def _parse_geometry(value: str) -> tuple[BaseGeometry | None, str | None]:
    if not value.strip():
        return None, "missing"
    try:
        geometry = wkt.loads(value)
    except Exception as exc:  # GEOS exposes several parse exception classes
        return None, f"malformed: {exc}"
    return geometry, None


def _normalized_floor_signature(geometries: list[BaseGeometry]) -> tuple[str, BaseGeometry] | None:
    polygons = [geometry for geometry in geometries if not geometry.is_empty and geometry.area > 0]
    if not polygons:
        return None
    merged = unary_union(polygons)
    minx, miny, _, _ = merged.bounds
    normalized = set_precision(translate(merged, xoff=-minx, yoff=-miny), 0.01).normalize()
    return hashlib.sha256(normalized.wkb).hexdigest(), normalized


def validate_sample(geometries_csv: str | Path) -> dict:
    path = Path(geometries_csv)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    missing_columns = sorted(REQUIRED_GEOMETRY_COLUMNS - set(frame.columns))
    if missing_columns:
        raise ValueError(f"sample geometries.csv missing required columns: {missing_columns}")

    class_frequencies: dict[str, Counter] = defaultdict(Counter)
    missing_ids = Counter()
    errors: list[dict] = []
    invalid: list[int] = []
    empty: list[int] = []
    zero_area: list[int] = []
    disconnected: list[int] = []
    extreme: list[int] = []
    parsed: list[BaseGeometry | None] = []
    bounds_by_floor: dict[tuple[str, str, str, str], list[float]] = {}
    floor_geometries: dict[tuple[str, str, str, str], list[BaseGeometry]] = defaultdict(list)

    for index, row in frame.iterrows():
        entity_type = row["entity_type"].strip().upper() or "<MISSING>"
        subtype = row["entity_subtype"].strip().upper() or "<MISSING>"
        class_frequencies[entity_type][subtype] += 1
        for column in CORE_IDS:
            if not row[column].strip():
                missing_ids[column] += 1
        geometry, error = _parse_geometry(row["geometry"])
        parsed.append(geometry)
        if error:
            errors.append({"row": int(index) + 2, "error": error})
            continue
        assert geometry is not None
        if geometry.is_empty:
            empty.append(int(index) + 2)
            continue
        if not geometry.is_valid:
            invalid.append(int(index) + 2)
        if geometry.geom_type in {"Polygon", "MultiPolygon"} and geometry.area <= 1e-9:
            zero_area.append(int(index) + 2)
        if geometry.geom_type.startswith("Multi") and len(geometry.geoms) > 1:
            disconnected.append(int(index) + 2)
        if any(not math.isfinite(value) or abs(value) > 1_000_000 for value in geometry.bounds):
            extreme.append(int(index) + 2)
        floor_key = tuple(row[column].strip() for column in CORE_IDS)
        floor_geometries[floor_key].append(geometry)
        minx, miny, maxx, maxy = geometry.bounds
        if floor_key not in bounds_by_floor:
            bounds_by_floor[floor_key] = [minx, miny, maxx, maxy]
        else:
            bounds = bounds_by_floor[floor_key]
            bounds[:] = [min(bounds[0], minx), min(bounds[1], miny), max(bounds[2], maxx), max(bounds[3], maxy)]

    frame["_geometry"] = parsed
    frame["_building_key"] = [_key(site, building) for site, building in zip(frame.site_id, frame.building_id)]
    exact_duplicate_rows = int(frame.drop(columns=["_geometry"]).duplicated().sum())
    geometry_hashes: dict[str, list[int]] = defaultdict(list)
    for index, geometry in enumerate(parsed):
        if geometry is not None and not geometry.is_empty:
            geometry_hashes[hashlib.sha256(geometry.normalize().wkb).hexdigest()].append(index + 2)
    duplicate_geometry_groups = [rows for rows in geometry_hashes.values() if len(rows) > 1]

    missing_by_floor = []
    grouped = frame.groupby(list(CORE_IDS), dropna=False)
    for floor_key, group in grouped:
        types = Counter(value.strip().upper() for value in group.entity_type)
        openings = group[group.entity_type.str.upper() == "OPENING"].entity_subtype.str.upper()
        missing_by_floor.append({
            "key": list(floor_key),
            "missing_rooms": types.get("AREA", 0) == 0,
            "missing_separators": types.get("SEPARATOR", 0) == 0,
            "missing_openings": types.get("OPENING", 0) == 0,
            "missing_doors": not openings.str.contains("DOOR", regex=False).any(),
            "missing_windows": not openings.str.contains("WINDOW", regex=False).any(),
        })

    floor_signatures: dict[tuple[str, str, str, str], tuple[str, BaseGeometry]] = {}
    for floor_key, geometries in floor_geometries.items():
        signature = _normalized_floor_signature(geometries)
        if signature:
            floor_signatures[floor_key] = signature
    signature_groups: dict[str, list[list[str]]] = defaultdict(list)
    for floor_key, (signature_hash, _) in floor_signatures.items():
        signature_groups[signature_hash].append(list(floor_key))
    cross_building_exact = []
    for floors in signature_groups.values():
        buildings = {_key(floor[0], floor[1]) for floor in floors}
        if len(buildings) > 1:
            cross_building_exact.append(floors)

    cross_building_near = []
    items = sorted(floor_signatures.items())
    for left_index, (left_key, (_, left_geometry)) in enumerate(items):
        for right_key, (_, right_geometry) in items[left_index + 1:]:
            if _key(left_key[0], left_key[1]) == _key(right_key[0], right_key[1]):
                continue
            area_ratio = min(left_geometry.area, right_geometry.area) / max(left_geometry.area, right_geometry.area)
            if area_ratio < 0.98:
                continue
            distance = left_geometry.hausdorff_distance(right_geometry)
            if distance <= 0.10:
                cross_building_near.append({"left": list(left_key), "right": list(right_key),
                                            "area_ratio": area_ratio, "hausdorff_m": distance})

    alignment = _opening_alignment(frame)
    floor_extents = []
    for key, bounds in sorted(bounds_by_floor.items()):
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        floor_extents.append({"key": list(key), "width_m": width, "height_m": height,
                              "plausible": 1.0 <= width <= 500.0 and 1.0 <= height <= 500.0})

    nonempty_units = frame[frame.unit_id.str.strip() != ""]
    unit_building_conflicts = int(
        nonempty_units.groupby(["site_id", "unit_id"])["building_id"].nunique().gt(1).sum()
    )
    return {
        "rows": len(frame),
        "counts": {
            "sites": int(frame.site_id.nunique()), "buildings": int(frame._building_key.nunique()),
            "plans": int(frame.plan_id.nunique()), "floors": int(frame.floor_id.nunique()),
            "units": int(nonempty_units[["site_id", "building_id", "floor_id", "unit_id"]].drop_duplicates().shape[0]),
            "apartments": int(frame[frame.apartment_id.str.strip() != ""][["site_id", "apartment_id"]].drop_duplicates().shape[0]),
        },
        "class_frequencies": {entity: dict(counter.most_common()) for entity, counter in sorted(class_frequencies.items())},
        "integrity": {
            "missing_core_ids": dict(missing_ids), "malformed_or_missing_wkt": errors,
            "invalid_geometry_rows": invalid, "empty_geometry_rows": empty,
            "zero_area_polygon_rows": zero_area, "disconnected_geometry_rows": disconnected,
            "extreme_coordinate_rows": extreme, "exact_duplicate_rows": exact_duplicate_rows,
            "duplicate_geometry_groups": duplicate_geometry_groups,
            "floor_coverage": missing_by_floor, "unit_building_conflicts": unit_building_conflicts,
            "cross_building_exact_floor_groups": cross_building_exact,
            "cross_building_near_floor_pairs": cross_building_near,
        },
        "metric": {"declared_unit": "metres", "floor_extents": floor_extents,
                   "all_floor_extents_plausible": all(item["plausible"] for item in floor_extents)},
        "opening_alignment": alignment,
    }


def _opening_alignment(frame: pd.DataFrame) -> dict:
    records = []
    for floor_key, group in frame.groupby(list(CORE_IDS), dropna=False):
        walls = [geometry for geometry in group.loc[
            (group.entity_type.str.upper() == "SEPARATOR") & (group.entity_subtype.str.upper() == "WALL"), "_geometry"
        ] if geometry is not None and not geometry.is_empty]
        if not walls:
            continue
        wall_union = unary_union(walls)
        for _, row in group[group.entity_type.str.upper() == "OPENING"].iterrows():
            geometry = row["_geometry"]
            if geometry is None or geometry.is_empty:
                continue
            records.append({"floor": list(floor_key), "subtype": row.entity_subtype.strip().upper(),
                            "distance_m": float(geometry.distance(wall_union))})
    distances = [item["distance_m"] for item in records]
    by_family = {}
    for family, predicate in (
        ("doors", lambda value: "DOOR" in value),
        ("windows", lambda value: "WINDOW" in value),
        ("other", lambda value: "DOOR" not in value and "WINDOW" not in value),
    ):
        values = [item["distance_m"] for item in records if predicate(item["subtype"])]
        by_family[family] = {
            "count": len(values), "aligned_0_05m": sum(value <= 0.05 for value in values),
            "aligned_0_20m": sum(value <= 0.20 for value in values),
            "median_distance_m": float(pd.Series(values).median()) if values else None,
            "max_distance_m": max(values) if values else None,
        }
    return {"total": len(records), "overall_aligned_0_05m": sum(value <= 0.05 for value in distances),
            "overall_aligned_0_20m": sum(value <= 0.20 for value in distances), "by_family": by_family}


def audit_archive(archive_path: str | Path) -> dict:
    path = Path(archive_path).resolve()
    return {
        "path": str(path), "bytes": path.stat().st_size, "expected_bytes": ARCHIVE_BYTES,
        "size_matches": path.stat().st_size == ARCHIVE_BYTES,
        "md5": _md5(path), "expected_md5": ARCHIVE_MD5,
        "md5_matches": _md5(path) == ARCHIVE_MD5, "sha256": _sha256(path),
    }


def run_sample_audit(dataset_root: str | Path, sample_root: str | Path, archive_path: str | Path,
                     *, building_count: int = 8) -> dict:
    dataset_root = Path(dataset_root).resolve()
    sample_root = Path(sample_root).resolve()
    profiles, columns = profile_buildings(dataset_root / "geometries.csv")
    selected = select_representative_buildings(profiles, building_count)
    extracted = extract_sample(dataset_root, sample_root, selected)
    validation = validate_sample(sample_root / "geometries.csv")
    return {
        "schema_version": 1, "dataset": DATASET, "version": VERSION, "doi": DOI,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "source": audit_archive(archive_path), "raw_root": str(dataset_root), "sample_root": str(sample_root),
        "source_geometry_columns": columns, "source_building_count": len(profiles),
        "selection_method": "deterministic max-min diversity over building-level size, units, floors, taxonomy, openings and WKT complexity",
        "selected_buildings": [profiles[key].summary() for key in selected],
        "extracted_rows": extracted, "validation": validation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--sample-root", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--building-count", type=int, default=8, choices=range(5, 11))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    report = run_sample_audit(args.dataset_root, args.sample_root, args.archive,
                              building_count=args.building_count)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"source": report["source"], "selected_buildings": len(report["selected_buildings"]),
                      "validation": report["validation"]["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
