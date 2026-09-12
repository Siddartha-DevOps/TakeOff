"""Run automated and visual QA over the bounded Swiss Dwellings pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from shapely import wkt
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ml.datasets.convert_swiss_dwellings_pilot import (
    CONVERSION_VERSION,
    DEFAULT_PADDING_M,
    DEFAULT_PPM,
    FLOOR_COLUMNS,
    _building_key,
    _mapping_for,
    deduplicate_floor_geometry,
    load_pilot,
    load_taxonomy,
)


QA_VERSION = "swiss-dwellings-pilot-visual-qa-v1"
REVIEW_CATEGORIES = (
    "simple_residential", "multi_unit_residential", "large_building", "multi_floor_building",
    "dense_wall_opening", "rare_room_classes", "negative_garage_only", "shared_wall",
)
ROOM_COLORS = [
    (225, 235, 255), (255, 226, 226), (255, 239, 198), (218, 244, 220),
    (230, 220, 255), (220, 242, 245), (242, 225, 207), (220, 245, 236),
    (238, 228, 250), (232, 235, 205), (221, 230, 240), (255, 230, 245),
    (235, 235, 235), (219, 234, 236),
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _polygons(geometry: BaseGeometry):
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms


def _font(size: int = 12):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _wall_thickness(geometry: BaseGeometry) -> float:
    rectangle = geometry.minimum_rotated_rectangle
    if not isinstance(rectangle, Polygon):
        return 0.0
    coords = list(rectangle.exterior.coords)
    sides = [math.dist(coords[index][:2], coords[index + 1][:2]) for index in range(4)]
    return min(sides) if sides else 0.0


def _floor_profiles(raw: pd.DataFrame, deduplicated: pd.DataFrame, taxonomy: dict) -> list[dict]:
    building_floor_counts = raw.groupby(["site_id", "building_id"])["floor_id"].nunique().to_dict()
    profiles = []
    for key, group in deduplicated.groupby(list(FLOOR_COLUMNS), sort=True):
        key = tuple(str(value) for value in key)
        raw_mask = pd.Series(True, index=raw.index)
        for column, value in zip(FLOOR_COLUMNS, key):
            raw_mask &= raw[column].astype(str) == value
        source = raw[raw_mask]
        mapped_rooms, rare_score, garages = 0, 0, 0
        room_names = []
        for _, row in group[group.entity_type == "AREA"].iterrows():
            _, class_id, _ = _mapping_for(row, taxonomy)
            if class_id:
                mapped_rooms += 1
                name = next(name for name, value in taxonomy["spaces"]["classes"].items() if int(value) == class_id)
                room_names.append(name)
                if name in {"entry_lobby", "utility", "office", "stairs", "balcony"}:
                    rare_score += 1
            elif row.entity_subtype == "GARAGE":
                garages += 1
            elif row.entity_subtype in taxonomy["spaces"].get("review_policy", {}):
                rare_score += 1
        walls = group[(group.entity_type == "SEPARATOR") & (group.entity_subtype == "WALL")]
        openings = group[group.entity_type == "OPENING"]
        geometries = list(group._geometry)
        minx = min(item.bounds[0] for item in geometries)
        miny = min(item.bounds[1] for item in geometries)
        maxx = max(item.bounds[2] for item in geometries)
        maxy = max(item.bounds[3] for item in geometries)
        profiles.append({
            "key": key,
            "building": _building_key(key[0], key[1]),
            "building_floors": int(building_floor_counts[(key[0], key[1])]),
            "raw_rows": int(len(source)),
            "canonical_rows": int(len(group)),
            "collapsed_rows": int(len(source) - len(group)),
            "units": int(source.unit_id[source.unit_id.str.strip() != ""].nunique()),
            "mapped_rooms": mapped_rooms,
            "room_names": sorted(set(room_names)),
            "rare_score": rare_score,
            "garages": garages,
            "walls": int(len(walls)),
            "openings": int(len(openings)),
            "extent_area_m2": float((maxx - minx) * (maxy - miny)),
        })
    return profiles


def select_review_floors(profiles: list[dict]) -> list[dict]:
    selected: set[tuple[str, ...]] = set()
    results = []

    def choose(category: str, candidates: list[dict], score, reverse: bool = True):
        available = [item for item in candidates if item["key"] not in selected]
        if not available:
            available = [item for item in profiles if item["key"] not in selected]
        if not available:
            return
        item = sorted(available, key=lambda value: (score(value), value["key"]), reverse=reverse)[0]
        selected.add(item["key"])
        results.append({"category": category, **item})

    residential = [item for item in profiles if {"bedroom", "kitchen"} & set(item["room_names"])]
    choose("simple_residential", residential, lambda item: item["canonical_rows"], reverse=False)
    choose("multi_unit_residential", [item for item in residential if item["units"] > 1],
           lambda item: item["units"])
    choose("large_building", profiles, lambda item: item["extent_area_m2"])
    choose("multi_floor_building", profiles, lambda item: (item["building_floors"], item["canonical_rows"]))
    choose("dense_wall_opening", profiles, lambda item: item["walls"] + item["openings"])
    choose("rare_room_classes", profiles, lambda item: (item["rare_score"], item["mapped_rooms"]))
    choose("negative_garage_only", [item for item in profiles if item["mapped_rooms"] == 0 and item["garages"]],
           lambda item: item["garages"])
    choose("shared_wall", [item for item in profiles if item["collapsed_rows"] > 0],
           lambda item: item["collapsed_rows"])
    return results


def automatic_checks(raw: pd.DataFrame, deduplicated: pd.DataFrame, taxonomy: dict, dedup_stats: dict) -> dict:
    invalid, empty = [], []
    for index, geometry in enumerate(deduplicated._geometry):
        if not geometry.is_valid:
            invalid.append(index)
        if geometry.is_empty:
            empty.append(index)

    orphan_openings, outside_tolerance = [], []
    overlaps = []
    tiny_rooms, huge_rooms = [], []
    suspicious_walls = []
    train_counts, state_counts, excluded_counts = Counter(), Counter(), Counter()
    excluded_state_counts, unclassified_source_semantics = Counter(), Counter()
    for floor, group in deduplicated.groupby(list(FLOOR_COLUMNS), sort=True):
        floor = tuple(str(value) for value in floor)
        walls = list(group.loc[(group.entity_type == "SEPARATOR") &
                               (group.entity_subtype == "WALL"), "_geometry"])
        wall_union = unary_union(walls) if walls else None
        for _, row in group.iterrows():
            family, class_id, _ = _mapping_for(row, taxonomy)
            policy = taxonomy.get(family or "", {}).get("review_policy", {}).get(row.entity_subtype, {})
            state = "TRAIN" if class_id else policy.get("mapping_state", "IGNORE_FOR_CURRENT_MODEL")
            state_counts[state] += 1
            if class_id and family:
                name = next(name for name, value in taxonomy[family]["classes"].items() if int(value) == class_id)
                train_counts[f"{family}:{name}"] += 1
            elif family == "spaces":
                excluded_counts[row.entity_subtype] += 1
                excluded_state_counts[state] += 1
                if row.entity_subtype not in taxonomy["spaces"].get("review_policy", {}):
                    unclassified_source_semantics[f"spaces:{row.entity_subtype}"] += 1
            elif family in {"separators", "doors", "windows"} and not class_id:
                policy = taxonomy[family].get("review_policy", {})
                exclusions = taxonomy[family].get("excluded_or_ambiguous", {})
                if row.entity_subtype not in policy and row.entity_subtype not in exclusions:
                    unclassified_source_semantics[f"{family}:{row.entity_subtype}"] += 1
            if row.entity_type == "OPENING" and ("DOOR" in row.entity_subtype or "WINDOW" in row.entity_subtype):
                record = {"floor": list(floor), "geometry_id": row.geometry_id, "subtype": row.entity_subtype}
                if wall_union is None:
                    orphan_openings.append(record)
                else:
                    distance = float(row._geometry.distance(wall_union))
                    if distance > 0.05:
                        outside_tolerance.append({**record, "distance_m": distance})
            if row.entity_type == "AREA" and class_id:
                area = float(row._geometry.area)
                record = {"floor": list(floor), "geometry_id": row.geometry_id,
                          "subtype": row.entity_subtype, "area_m2": area}
                if area < 1.0:
                    tiny_rooms.append(record)
                if area > 500.0:
                    huge_rooms.append(record)
            if row.entity_type == "SEPARATOR" and row.entity_subtype == "WALL":
                thickness = _wall_thickness(row._geometry)
                area = float(row._geometry.area)
                if area < 0.002 or area > 500.0 or thickness < 0.01 or thickness > 3.0:
                    suspicious_walls.append({"floor": list(floor), "geometry_id": row.geometry_id,
                                             "area_m2": area, "min_rotated_side_m": thickness})

        rooms = []
        for _, row in group[group.entity_type == "AREA"].iterrows():
            family, class_id, _ = _mapping_for(row, taxonomy)
            if family == "spaces" and class_id:
                rooms.append(row)
        for left_index, left in enumerate(rooms):
            for right in rooms[left_index + 1:]:
                if not left._geometry.bounds or not right._geometry.bounds:
                    continue
                intersection = float(left._geometry.intersection(right._geometry).area)
                if intersection > 0.1:
                    ratio = intersection / min(left._geometry.area, right._geometry.area)
                    if ratio > 0.01:
                        overlaps.append({"floor": list(floor), "left": left.geometry_id,
                                         "right": right.geometry_id, "intersection_m2": intersection,
                                         "smaller_room_fraction": ratio})

    unique_keys = {
        (*tuple(str(row[column]).strip() for column in FLOOR_COLUMNS), row.entity_type.strip().upper(),
         row.entity_subtype.strip().upper() or "NOT_DEFINED",
         hashlib.sha256(wkt.loads(row.geometry).normalize().wkb).hexdigest())
        for _, row in raw.iterrows()
    }
    canonical_keys = {
        (*tuple(str(row[column]).strip() for column in FLOOR_COLUMNS), row.entity_type,
         row.entity_subtype, row.geometry_hash)
        for _, row in deduplicated.iterrows()
    }
    counts = list(train_counts.values())
    by_family = {}
    for family in ("spaces", "separators", "doors", "windows"):
        values = {key.split(":", 1)[1]: value for key, value in train_counts.items()
                  if key.startswith(f"{family}:")}
        family_counts = list(values.values())
        by_family[family] = {
            "minimum_nonzero_count": min(family_counts) if family_counts else 0,
            "maximum_count": max(family_counts) if family_counts else 0,
            "max_to_min_ratio": max(family_counts) / min(family_counts)
            if family_counts and min(family_counts) else None,
            "counts": dict(sorted(values.items())),
        }
    imbalance = {
        "minimum_nonzero_count": min(counts) if counts else 0,
        "maximum_count": max(counts) if counts else 0,
        "max_to_min_ratio": max(counts) / min(counts) if counts and min(counts) else None,
        "counts": dict(sorted(train_counts.items())),
        "by_family": by_family,
    }
    return {
        "invalid_polygons": invalid,
        "empty_geometries": empty,
        "orphan_openings": orphan_openings,
        "openings_outside_0_05m": outside_tolerance,
        "overlapping_room_pairs": overlaps,
        "tiny_rooms_under_1m2": tiny_rooms,
        "huge_rooms_over_500m2": huge_rooms,
        "suspicious_walls": suspicious_walls,
        "mapping_state_counts_all_geometries": dict(sorted(state_counts.items())),
        "excluded_area_mapping_state_counts": dict(sorted(excluded_state_counts.items())),
        "excluded_area_counts": dict(sorted(excluded_counts.items())),
        "unclassified_source_semantics": dict(sorted(unclassified_source_semantics.items())),
        "class_imbalance": imbalance,
        "deduplication": {
            **dedup_stats,
            "unique_semantic_geometry_keys_before": len(unique_keys),
            "canonical_geometry_keys_after": len(canonical_keys),
            "nonduplicate_geometry_loss": len(unique_keys - canonical_keys),
            "source_relationship_loss": len(raw) - sum(len(rows) for rows in deduplicated.source_rows),
        },
    }


def render_review_overlay(group: pd.DataFrame, taxonomy: dict, destination: Path, category: str,
                          profile: dict, *, pixels_per_metre: int = DEFAULT_PPM,
                          padding_m: float = DEFAULT_PADDING_M) -> dict:
    geometries = list(group._geometry)
    minx = min(item.bounds[0] for item in geometries)
    miny = min(item.bounds[1] for item in geometries)
    maxx = max(item.bounds[2] for item in geometries)
    maxy = max(item.bounds[3] for item in geometries)
    plan_width = int(math.ceil((maxx - minx + 2 * padding_m) * pixels_per_metre)) + 1
    height = int(math.ceil((maxy - miny + 2 * padding_m) * pixels_per_metre)) + 1
    legend_width = 360

    def transform(x: float, y: float):
        return (round((x - minx + padding_m) * pixels_per_metre),
                round((maxy - y + padding_m) * pixels_per_metre))

    image = Image.new("RGB", (plan_width + legend_width, height), "white")
    draw = ImageDraw.Draw(image)
    label_font, title_font = _font(11), _font(15)
    present = defaultdict(set)

    for geometry in geometries:
        for polygon in _polygons(geometry):
            draw.line([transform(x, y) for x, y, *_ in polygon.exterior.coords], fill=(205, 205, 205), width=1)

    ordered = group.assign(_order=group.entity_type.map({"AREA": 0, "SEPARATOR": 1, "OPENING": 2}).fillna(9))
    ordered = ordered.sort_values(["_order", "entity_subtype", "geometry_hash"], kind="mergesort")
    for _, row in ordered.iterrows():
        family, class_id, _ = _mapping_for(row, taxonomy)
        geometry = row._geometry
        if family == "spaces" and class_id:
            name = next(name for name, value in taxonomy["spaces"]["classes"].items() if int(value) == class_id)
            color = ROOM_COLORS[(class_id - 1) % len(ROOM_COLORS)]
            for polygon in _polygons(geometry):
                draw.polygon([transform(x, y) for x, y, *_ in polygon.exterior.coords], fill=color,
                             outline=(110, 110, 110))
            point = geometry.representative_point()
            draw.text(transform(point.x, point.y), name, fill=(20, 35, 55), font=label_font, anchor="mm")
            present["spaces"].add(name)
        elif family == "spaces":
            policy = taxonomy["spaces"].get("review_policy", {}).get(row.entity_subtype, {})
            state = policy.get("mapping_state", "IGNORE_FOR_CURRENT_MODEL")
            for polygon in _polygons(geometry):
                draw.line([transform(x, y) for x, y, *_ in polygon.exterior.coords], fill=(185, 65, 155), width=2)
            point = geometry.representative_point()
            draw.text(transform(point.x, point.y), f"{row.entity_subtype} [{state}]",
                      fill=(145, 35, 120), font=label_font, anchor="mm")
            present["excluded/review"].add(f"{row.entity_subtype} [{state}]")

    for _, row in ordered[ordered.entity_type == "SEPARATOR"].iterrows():
        family, class_id, _ = _mapping_for(row, taxonomy)
        if family == "separators" and class_id:
            name = next(name for name, value in taxonomy["separators"]["classes"].items() if int(value) == class_id)
            color = (25, 25, 25) if name == "wall" else (105, 105, 105) if name == "column" else (185, 145, 25)
            for polygon in _polygons(row._geometry):
                draw.polygon([transform(x, y) for x, y, *_ in polygon.exterior.coords], fill=color)
            present["separators"].add(name)
    for _, row in ordered[ordered.entity_type == "OPENING"].iterrows():
        family, class_id, _ = _mapping_for(row, taxonomy)
        if family in {"doors", "windows"} and class_id:
            name = next(name for name, value in taxonomy[family]["classes"].items() if int(value) == class_id)
            color = (225, 65, 55) if family == "doors" else (30, 135, 230)
            for polygon in _polygons(row._geometry):
                draw.polygon([transform(x, y) for x, y, *_ in polygon.exterior.coords], fill=color)
            present[family].add(name)

    legend_x = plan_width + 15
    draw.rectangle((plan_width, 0, plan_width + legend_width, height), fill=(247, 249, 252))
    draw.text((legend_x, 15), category.replace("_", " ").title(), fill=(15, 25, 45), font=title_font)
    draw.text((legend_x, 40), "/".join(profile["key"]), fill=(45, 55, 75), font=label_font)
    y = 65
    for family in ("spaces", "excluded/review", "separators", "doors", "windows"):
        if not present[family]:
            continue
        draw.text((legend_x, y), family.upper(), fill=(65, 70, 90), font=label_font)
        y += 16
        for name in sorted(present[family]):
            draw.text((legend_x + 10, y), name, fill=(25, 35, 55), font=label_font)
            y += 15
            if y > height - 45:
                break
    y = max(y + 8, height - 55)
    draw.text((legend_x, y), f"raw {profile['raw_rows']} | canonical {profile['canonical_rows']}",
              fill=(45, 55, 75), font=label_font)
    draw.text((legend_x, y + 16), f"collapsed {profile['collapsed_rows']} | units {profile['units']}",
              fill=(45, 55, 75), font=label_font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, optimize=False, compress_level=9)
    return {"category": category, "ids": dict(zip(FLOOR_COLUMNS, profile["key"])),
            "path": str(destination), "sha256": _sha256(destination),
            "image_size_px": list(image.size), "profile": profile,
            "present_labels": {key: sorted(values) for key, values in present.items()}}


def _contact_sheet(reviews: list[dict], destination: Path) -> None:
    thumb_width, thumb_height = 600, 420
    sheet = Image.new("RGB", (thumb_width * 2, thumb_height * 4), (235, 238, 244))
    for index, review in enumerate(reviews):
        with Image.open(review["path"]) as image:
            copy = image.copy()
        copy.thumbnail((thumb_width - 10, thumb_height - 10))
        x = (index % 2) * thumb_width + (thumb_width - copy.width) // 2
        y = (index // 2) * thumb_height + (thumb_height - copy.height) // 2
        sheet.paste(copy, (x, y))
    sheet.save(destination, optimize=False, compress_level=9)


def run_qa(sample_csv: str | Path, pilot_manifest: str | Path, taxonomy_path: str | Path,
           output_root: str | Path) -> dict:
    sample_csv, output_root = Path(sample_csv).resolve(), Path(output_root).resolve()
    taxonomy = load_taxonomy(taxonomy_path)
    raw = load_pilot(sample_csv)
    deduplicated, dedup_stats = deduplicate_floor_geometry(raw)
    pilot = json.loads(Path(pilot_manifest).read_text(encoding="utf-8"))
    if pilot.get("conversion_version") != CONVERSION_VERSION:
        raise ValueError("pilot manifest conversion version mismatch")
    profiles = _floor_profiles(raw, deduplicated, taxonomy)
    selections = select_review_floors(profiles)
    if {item["category"] for item in selections} != set(REVIEW_CATEGORIES):
        raise ValueError("could not select every required review category")
    reviews = []
    for index, profile in enumerate(selections, start=1):
        mask = pd.Series(True, index=deduplicated.index)
        for column, value in zip(FLOOR_COLUMNS, profile["key"]):
            mask &= deduplicated[column].astype(str) == value
        destination = output_root / f"{index:02d}_{profile['category']}_{'__'.join(profile['key'])}.png"
        reviews.append(render_review_overlay(deduplicated[mask], taxonomy, destination,
                                             profile["category"], profile))
    contact_sheet = output_root / "review_contact_sheet.png"
    _contact_sheet(reviews, contact_sheet)
    checks = automatic_checks(raw, deduplicated, taxonomy, dedup_stats)
    checks["empty_positive_labels"] = {
        "room_mask_floors": int(pilot["totals"]["empty_room_masks"]),
        "wall_mask_floors": int(pilot["totals"]["empty_wall_masks"]),
        "door_label_floors": int(pilot["totals"]["empty_door_labels"]),
        "window_label_floors": int(pilot["totals"]["empty_window_labels"]),
        "room_negative_is_known_garage_only": int(pilot["totals"]["empty_room_masks"]) == 1,
    }
    report = {
        "qa_version": QA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {"sample_csv": str(sample_csv), "sample_csv_sha256": _sha256(sample_csv),
                   "pilot_manifest": str(Path(pilot_manifest).resolve())},
        "review_categories": list(REVIEW_CATEGORIES),
        "reviews": reviews,
        "contact_sheet": {"path": str(contact_sheet), "sha256": _sha256(contact_sheet)},
        "checks": checks,
        "decision_rules": {
            "material_geometry_failures": len(checks["invalid_polygons"]) + len(checks["empty_geometries"])
            + len(checks["orphan_openings"]) + len(checks["openings_outside_0_05m"])
            + checks["deduplication"]["nonduplicate_geometry_loss"]
            + abs(checks["deduplication"]["source_relationship_loss"]),
            "overlaps_require_review": len(checks["overlapping_room_pairs"]),
            "wall_outliers_require_review": len(checks["suspicious_walls"]),
            "room_size_outliers_require_review": len(checks["tiny_rooms_under_1m2"])
            + len(checks["huge_rooms_over_500m2"]),
        },
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "qa_manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                                    encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-csv", required=True, type=Path)
    parser.add_argument("--pilot-manifest", required=True, type=Path)
    parser.add_argument("--taxonomy", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    report = run_qa(args.sample_csv, args.pilot_manifest, args.taxonomy, args.output_root)
    print(json.dumps({
        "reviews": len(report["reviews"]),
        "categories": report["review_categories"],
        "decision_rules": report["decision_rules"],
        "class_imbalance": report["checks"]["class_imbalance"],
        "excluded_area_counts": report["checks"]["excluded_area_counts"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
