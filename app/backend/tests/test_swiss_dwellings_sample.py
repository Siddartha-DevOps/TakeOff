"""Small-fixture tests for Swiss Dwellings sample extraction and rendering."""

from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image

from ml.datasets.audit_swiss_dwellings_sample import (
    extract_sample,
    profile_buildings,
    select_representative_buildings,
    validate_sample,
)
from ml.datasets.render_swiss_dwellings_sample import render_sample, verify_repeatability


COLUMNS = [
    "apartment_id", "site_id", "building_id", "plan_id", "floor_id", "unit_id", "area_id",
    "unit_usage", "entity_type", "entity_subtype", "geometry", "elevation", "height",
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _building_rows(building: int, *, offset: float = 0.0, room_subtype: str = "BEDROOM") -> list[dict[str, str]]:
    common = {
        "apartment_id": f"apt-{building}", "site_id": "1", "building_id": str(building),
        "plan_id": str(100 + building), "floor_id": str(200 + building), "unit_id": str(300 + building),
        "unit_usage": "RESIDENTIAL", "elevation": "0", "height": "2.6",
    }

    def row(entity_type: str, subtype: str, geometry: str, area_id: str = "") -> dict[str, str]:
        return {**common, "area_id": area_id, "entity_type": entity_type,
                "entity_subtype": subtype, "geometry": geometry}

    x = offset
    return [
        row("area", room_subtype,
            f"POLYGON (({x} 0, {x + 10} 0, {x + 10} 8, {x} 8, {x} 0))", f"area-{building}"),
        row("separator", "WALL", f"POLYGON (({x} 0, {x + 10} 0, {x + 10} 0.2, {x} 0.2, {x} 0))"),
        row("separator", "WALL", f"POLYGON (({x} 7.8, {x + 10} 7.8, {x + 10} 8, {x} 8, {x} 7.8))"),
        row("opening", "DOOR", f"POLYGON (({x + 4} 0, {x + 5} 0, {x + 5} 0.2, {x + 4} 0.2, {x + 4} 0))"),
        row("opening", "WINDOW_ENVELOPE",
            f"POLYGON (({x + 6} 7.8, {x + 8} 7.8, {x + 8} 8, {x + 6} 8, {x + 6} 7.8))"),
        row("feature", "SINK", f"POLYGON (({x + 1} 1, {x + 2} 1, {x + 2} 2, {x + 1} 2, {x + 1} 1))",
            f"area-{building}"),
    ]


def test_profiles_selects_and_extracts_complete_buildings(tmp_path):
    source = tmp_path / "raw"
    rows = []
    room_types = ["BEDROOM", "BATHROOM", "KITCHEN", "LIVING_ROOM", "BALCONY", "OFFICE"]
    for building, room_type in enumerate(room_types, start=1):
        rows.extend(_building_rows(building, offset=building * 20.0, room_subtype=room_type))
    _write_csv(source / "geometries.csv", rows)

    profiles, columns = profile_buildings(source / "geometries.csv")
    selected = select_representative_buildings(profiles, 5)
    counts = extract_sample(source, tmp_path / "sample", selected)

    assert len(profiles) == 6
    assert set(COLUMNS) == set(columns)
    assert len(selected) == 5
    assert counts["geometries.csv"] == 30
    sample_profiles, _ = profile_buildings(tmp_path / "sample" / "geometries.csv")
    assert set(sample_profiles) == set(selected)
    assert all(profile.rows == 6 for profile in sample_profiles.values())


def test_validation_reports_classes_metric_alignment_and_cross_building_duplicate(tmp_path):
    rows = _building_rows(1, offset=0.0) + _building_rows(2, offset=100.0)
    path = tmp_path / "geometries.csv"
    _write_csv(path, rows)

    report = validate_sample(path)

    assert report["counts"]["buildings"] == 2
    assert report["class_frequencies"]["AREA"] == {"BEDROOM": 2}
    assert report["class_frequencies"]["OPENING"] == {"DOOR": 2, "WINDOW_ENVELOPE": 2}
    assert report["integrity"]["malformed_or_missing_wkt"] == []
    assert report["integrity"]["invalid_geometry_rows"] == []
    assert report["metric"]["all_floor_extents_plausible"] is True
    assert report["opening_alignment"]["by_family"]["doors"]["aligned_0_05m"] == 2
    assert report["opening_alignment"]["by_family"]["windows"]["aligned_0_05m"] == 2
    assert len(report["integrity"]["cross_building_exact_floor_groups"]) == 1


def test_sample_renderer_emits_masks_metadata_and_is_repeatable(tmp_path):
    sample_csv = tmp_path / "geometries.csv"
    _write_csv(sample_csv, _building_rows(1))
    output = tmp_path / "renders"

    manifest = render_sample(sample_csv, output, max_plans=1, pixels_per_metre=16)
    rendered = Path(manifest["rendered_plans"][0]["output_dir"])

    for name in ("composite.png", "room_mask.png", "separator_mask.png", "opening_mask.png",
                 "metadata.json", "hashes.json"):
        assert (rendered / name).is_file()
    with Image.open(rendered / "room_mask.png") as image:
        assert image.getbbox() is not None
    assert verify_repeatability(sample_csv, max_plans=1)["identical"] is True
