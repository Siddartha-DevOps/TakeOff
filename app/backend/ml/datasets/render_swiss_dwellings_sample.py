"""Deterministically render a few Swiss Dwellings sample plans.

This prototype accepts only the building-complete sample produced by
``audit_swiss_dwellings_sample.py``. It emits semantic masks, an inspection
image, opening labels, and an invertible metric-to-pixel transform. It never
walks or renders the complete source dataset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw
from shapely import wkt
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry


RENDERER_VERSION = "swiss-dwellings-sample-renderer-v1"
SOURCE_DOI = "10.5281/zenodo.7788422"
SOURCE_VERSION = "3.0.0"
DEFAULT_PPM = 16
DEFAULT_PADDING_M = 2.0
MAX_DIMENSION_PX = 4096

ROOM_CLASSES = {
    "BEDROOM": 1, "BATHROOM": 2, "KITCHEN": 3, "LIVING_ROOM": 4,
    "DINING": 5, "CORRIDOR": 6, "STOREROOM": 7, "BALCONY": 8,
    "OFFICE": 9, "STAIRCASE": 10, "FOYER": 11, "LOBBY": 12,
    "LIVING_DINING": 13, "KITCHEN_DINING": 14, "ROOM": 15,
    "NOT_DEFINED": 16,
}
SEPARATOR_CLASSES = {"WALL": 1, "COLUMN": 2, "RAILING": 3, "AREA_SPLITTER": 4, "NOT_DEFINED": 5}
OPENING_CLASSES = {"DOOR": 1, "ENTRANCE_DOOR": 2, "WINDOW": 3,
                   "WINDOW_ENVELOPE": 4, "WINDOW_INTERIOR": 5, "NOT_DEFINED": 6}

COMPOSITE_COLORS = {
    "AREA": (205, 225, 255), "SEPARATOR": (35, 35, 35),
    "DOOR": (220, 80, 60), "WINDOW": (40, 145, 230), "OTHER_OPENING": (220, 170, 40),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_token(value: object) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in str(value))


def _polygons(geometry: BaseGeometry):
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms


def _draw_geometry(draw: ImageDraw.ImageDraw, geometry: BaseGeometry, transform, fill: int | tuple[int, int, int]):
    for polygon in _polygons(geometry):
        exterior = [transform(x, y) for x, y, *_ in polygon.exterior.coords]
        draw.polygon(exterior, fill=fill)
        hole_fill = 0 if isinstance(fill, int) else (255, 255, 255)
        for interior in polygon.interiors:
            draw.polygon([transform(x, y) for x, y, *_ in interior.coords], fill=hole_fill)


def _choose_plans(frame: pd.DataFrame, max_plans: int) -> list[tuple[str, str, str, str]]:
    counts = []
    for key, group in frame.groupby(["site_id", "building_id", "plan_id", "floor_id"], sort=True):
        counts.append((tuple(str(value) for value in key), len(group)))
    if not counts:
        return []
    ordered = sorted(counts, key=lambda item: (item[1], item[0]))
    if len(ordered) <= max_plans:
        return [item[0] for item in ordered]
    indexes = sorted({round(index * (len(ordered) - 1) / (max_plans - 1)) for index in range(max_plans)})
    return [ordered[index][0] for index in indexes]


def render_plan(group: pd.DataFrame, output_dir: str | Path, *, pixels_per_metre: int = DEFAULT_PPM,
                padding_m: float = DEFAULT_PADDING_M, source_csv_sha256: str) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed = []
    for value in group.geometry:
        geometry = wkt.loads(value)
        if not geometry.is_empty:
            parsed.append(geometry)
    if not parsed:
        raise ValueError("plan has no renderable geometry")
    minx = min(geometry.bounds[0] for geometry in parsed)
    miny = min(geometry.bounds[1] for geometry in parsed)
    maxx = max(geometry.bounds[2] for geometry in parsed)
    maxy = max(geometry.bounds[3] for geometry in parsed)
    width = int(round((maxx - minx + 2 * padding_m) * pixels_per_metre)) + 1
    height = int(round((maxy - miny + 2 * padding_m) * pixels_per_metre)) + 1
    if width <= 1 or height <= 1 or width > MAX_DIMENSION_PX or height > MAX_DIMENSION_PX:
        raise ValueError(f"plan render dimensions outside bounds: {width}x{height}")

    def transform(x: float, y: float) -> tuple[int, int]:
        return (round((x - minx + padding_m) * pixels_per_metre),
                round((maxy - y + padding_m) * pixels_per_metre))

    composite = Image.new("RGB", (width, height), "white")
    room_mask = Image.new("L", (width, height), 0)
    separator_mask = Image.new("L", (width, height), 0)
    opening_mask = Image.new("L", (width, height), 0)
    composite_draw = ImageDraw.Draw(composite)
    room_draw = ImageDraw.Draw(room_mask)
    separator_draw = ImageDraw.Draw(separator_mask)
    opening_draw = ImageDraw.Draw(opening_mask)
    opening_labels = []

    ordered = group.assign(_type=group.entity_type.str.upper(), _subtype=group.entity_subtype.str.upper())
    order = {"AREA": 0, "SEPARATOR": 1, "OPENING": 2, "FEATURE": 3}
    ordered = ordered.assign(_order=ordered._type.map(order).fillna(9)).sort_values(
        ["_order", "entity_subtype", "geometry"], kind="mergesort"
    )
    for _, row in ordered.iterrows():
        geometry = wkt.loads(row.geometry)
        entity_type, subtype = row._type, row._subtype or "NOT_DEFINED"
        if entity_type == "AREA":
            value = ROOM_CLASSES.get(subtype, ROOM_CLASSES["NOT_DEFINED"])
            _draw_geometry(room_draw, geometry, transform, value)
            _draw_geometry(composite_draw, geometry, transform, COMPOSITE_COLORS["AREA"])
        elif entity_type == "SEPARATOR":
            value = SEPARATOR_CLASSES.get(subtype, SEPARATOR_CLASSES["NOT_DEFINED"])
            _draw_geometry(separator_draw, geometry, transform, value)
            _draw_geometry(composite_draw, geometry, transform, COMPOSITE_COLORS["SEPARATOR"])
        elif entity_type == "OPENING":
            value = OPENING_CLASSES.get(subtype, OPENING_CLASSES["NOT_DEFINED"])
            _draw_geometry(opening_draw, geometry, transform, value)
            family = "DOOR" if "DOOR" in subtype else "WINDOW" if "WINDOW" in subtype else "OTHER_OPENING"
            _draw_geometry(composite_draw, geometry, transform, COMPOSITE_COLORS[family])
            opening_labels.append({
                "subtype": subtype, "class_id": value, "wkt_metric": geometry.wkt,
                "bounds_metric": list(geometry.bounds),
                "bounds_pixels": [list(transform(geometry.bounds[0], geometry.bounds[3])),
                                  list(transform(geometry.bounds[2], geometry.bounds[1]))],
            })

    composite.save(output_dir / "composite.png", optimize=False, compress_level=9)
    room_mask.save(output_dir / "room_mask.png", optimize=False, compress_level=9)
    separator_mask.save(output_dir / "separator_mask.png", optimize=False, compress_level=9)
    opening_mask.save(output_dir / "opening_mask.png", optimize=False, compress_level=9)
    first = ordered.iloc[0]
    metadata = {
        "renderer_version": RENDERER_VERSION,
        "source": {"dataset": "Swiss Dwellings", "version": SOURCE_VERSION, "doi": SOURCE_DOI,
                   "sample_csv_sha256": source_csv_sha256},
        "ids": {column: str(first[column]) for column in
                ("site_id", "building_id", "plan_id", "floor_id")},
        "transform": {
            "coordinate_unit": "metre", "pixels_per_metre": pixels_per_metre,
            "padding_m": padding_m, "source_bounds_m": [minx, miny, maxx, maxy],
            "image_size_px": [width, height], "x_px": "round((x-minx+padding_m)*ppm)",
            "y_px": "round((maxy-y+padding_m)*ppm)",
        },
        "classes": {"rooms": ROOM_CLASSES, "separators": SEPARATOR_CLASSES, "openings": OPENING_CLASSES},
        "opening_labels": opening_labels,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    hashes = {path.name: _sha256(path) for path in sorted(output_dir.iterdir()) if path.is_file()}
    (output_dir / "hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ids": metadata["ids"], "output_dir": str(output_dir), "hashes": hashes,
            "width_px": width, "height_px": height, "openings": len(opening_labels)}


def render_sample(sample_csv: str | Path, output_root: str | Path, *, max_plans: int = 3,
                  pixels_per_metre: int = DEFAULT_PPM) -> dict:
    sample_csv = Path(sample_csv)
    output_root = Path(output_root)
    frame = pd.read_csv(sample_csv, dtype=str, keep_default_na=False, low_memory=False)
    csv_hash = _sha256(sample_csv)
    selected = _choose_plans(frame, max_plans)
    results = []
    for key in selected:
        mask = pd.Series(True, index=frame.index)
        for column, value in zip(("site_id", "building_id", "plan_id", "floor_id"), key):
            mask &= frame[column].astype(str) == value
        name = "__".join(_safe_token(value) for value in key)
        results.append(render_plan(frame[mask], output_root / name, pixels_per_metre=pixels_per_metre,
                                   source_csv_sha256=csv_hash))
    manifest = {"renderer_version": RENDERER_VERSION, "source_csv": str(sample_csv.resolve()),
                "source_csv_sha256": csv_hash, "pixels_per_metre": pixels_per_metre,
                "rendered_plans": results}
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "render_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                                       encoding="utf-8")
    return manifest


def verify_repeatability(sample_csv: str | Path, *, max_plans: int = 3,
                         pixels_per_metre: int = DEFAULT_PPM) -> dict:
    with tempfile.TemporaryDirectory(prefix="swiss-render-a-") as first_dir, \
            tempfile.TemporaryDirectory(prefix="swiss-render-b-") as second_dir:
        first = render_sample(sample_csv, first_dir, max_plans=max_plans, pixels_per_metre=pixels_per_metre)
        second = render_sample(sample_csv, second_dir, max_plans=max_plans, pixels_per_metre=pixels_per_metre)
        first_hashes = [item["hashes"] for item in first["rendered_plans"]]
        second_hashes = [item["hashes"] for item in second["rendered_plans"]]
        return {"identical": first_hashes == second_hashes, "first": first_hashes, "second": second_hashes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-csv", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--max-plans", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--pixels-per-metre", type=int, default=DEFAULT_PPM)
    parser.add_argument("--verify-repeatability", action="store_true")
    args = parser.parse_args(argv)
    result = render_sample(args.sample_csv, args.output_root, max_plans=args.max_plans,
                           pixels_per_metre=args.pixels_per_metre)
    if args.verify_repeatability:
        result["repeatability"] = verify_repeatability(args.sample_csv, max_plans=args.max_plans,
                                                        pixels_per_metre=args.pixels_per_metre)
        if not result["repeatability"]["identical"]:
            raise SystemExit("determinism check failed")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
