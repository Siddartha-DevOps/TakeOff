"""Critical guarantees for the bounded Swiss Dwellings converter."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image

from ml.datasets.convert_swiss_dwellings_pilot import (
    CONVERSION_VERSION,
    convert_pilot,
    deduplicate_floor_geometry,
    load_pilot,
    load_taxonomy,
)
from ml.datasets.qa_swiss_dwellings_pilot import automatic_checks, select_review_floors


COLUMNS = [
    "apartment_id", "site_id", "building_id", "plan_id", "floor_id", "unit_id", "area_id",
    "unit_usage", "entity_type", "entity_subtype", "geometry", "elevation", "height",
]
TAXONOMY = Path(__file__).parents[1] / "ml" / "datasets" / "swiss_dwellings_taxonomy_v1.json"


def _row(building: int, floor: int, entity_type: str, subtype: str, geometry: str,
         *, unit: int = 1, area: str = "") -> dict[str, str]:
    return {
        "apartment_id": f"apt-{building}-{unit}", "site_id": "site-1", "building_id": str(building),
        "plan_id": f"plan-{building}", "floor_id": f"floor-{floor}", "unit_id": str(unit),
        "area_id": area, "unit_usage": "RESIDENTIAL", "entity_type": entity_type,
        "entity_subtype": subtype, "geometry": geometry, "elevation": "0", "height": "2.6",
    }


def _building_rows(building: int, *, x: float, duplicate_wall: bool = False,
                   width: float = 10.0) -> list[dict[str, str]]:
    room = f"POLYGON (({x} 0, {x + width} 0, {x + width} 8, {x} 8, {x} 0))"
    wall = f"POLYGON (({x} 0, {x + width} 0, {x + width} 0.2, {x} 0.2, {x} 0))"
    rows = [
        _row(building, building, "AREA", "BEDROOM", room, area=f"area-{building}"),
        _row(building, building, "SEPARATOR", "WALL", wall),
        _row(building, building, "OPENING", "DOOR",
             f"POLYGON (({x + 2} 0, {x + 3} 0, {x + 3} 0.2, {x + 2} 0.2, {x + 2} 0))"),
        _row(building, building, "OPENING", "WINDOW",
             f"POLYGON (({x + 6} 0, {x + 8} 0, {x + 8} 0.2, {x + 6} 0.2, {x + 6} 0))"),
        _row(building, building, "AREA", "GARAGE",
             f"POLYGON (({x} 9, {x + 3} 9, {x + 3} 11, {x} 11, {x} 9))", area=f"garage-{building}"),
    ]
    if duplicate_wall:
        rows.append(_row(building, building, "SEPARATOR", "WALL", wall, unit=2))
    return rows


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_taxonomy_keeps_composites_and_ambiguous_classes_explicit():
    taxonomy = load_taxonomy(TAXONOMY)

    assert taxonomy["conversion_version"] == CONVERSION_VERSION
    assert taxonomy["spaces"]["source_mapping"]["LIVING_DINING"] == "living_dining"
    assert "GARAGE" not in taxonomy["spaces"]["source_mapping"]
    assert "GARAGE" in taxonomy["spaces"]["excluded_or_ambiguous"]
    assert taxonomy["separators"]["source_mapping"] == {
        "COLUMN": "column", "RAILING": "railing", "WALL": "wall"
    }
    assert set(taxonomy["mapping_states"]) == {
        "TRAIN", "MAP_TO_OTHER", "IGNORE_FOR_CURRENT_MODEL", "REVIEW"
    }
    assert taxonomy["spaces"]["review_policy"]["GARAGE"] == {
        "canonical_takeoff_class": "other_aec",
        "mapping_state": "MAP_TO_OTHER",
        "reason": "Useful AEC space retained for a future garage/parking model.",
    }
    assert set(taxonomy["spaces"]["review_policy"]) == set(
        taxonomy["spaces"]["excluded_or_ambiguous"]
    )
    assert {policy["mapping_state"] for policy in taxonomy["spaces"]["review_policy"].values()} <= set(
        taxonomy["mapping_states"]
    )


def test_floor_semantic_dedup_preserves_provenance_and_distinct_semantics(tmp_path):
    path = tmp_path / "sample.csv"
    rows = _building_rows(1, x=0, duplicate_wall=True)
    coincident_railing = dict(rows[1])
    coincident_railing["entity_subtype"] = "RAILING"
    rows.append(coincident_railing)
    _write(path, rows)

    deduplicated, stats = deduplicate_floor_geometry(load_pilot(path))

    walls = deduplicated[(deduplicated.entity_type == "SEPARATOR") & (deduplicated.entity_subtype == "WALL")]
    railings = deduplicated[(deduplicated.entity_type == "SEPARATOR") & (deduplicated.entity_subtype == "RAILING")]
    assert len(walls) == 1
    assert len(walls.iloc[0].source_rows) == 2
    assert {item["unit_id"] for item in walls.iloc[0].source_rows} == {"1", "2"}
    assert len(railings) == 1
    assert stats["removed"] == 1
    assert stats["source_rows_preserved"] == len(rows)


def test_conversion_outputs_labels_transforms_splits_and_is_deterministic(tmp_path):
    rows = []
    for building in range(1, 5):
        rows.extend(_building_rows(building, x=building * 20.0, duplicate_wall=True,
                                   width=10.0 + building))
    sample = tmp_path / "sample.csv"
    _write(sample, rows)

    first = convert_pilot(sample, tmp_path / "out-a", TAXONOMY, determinism_count=4)
    second = convert_pilot(sample, tmp_path / "out-b", TAXONOMY, determinism_count=4)

    assert first["bounded_pilot"] == {"max_buildings": 10, "max_floors": 100,
                                       "actual_buildings": 4, "actual_floors": 4}
    assert first["deduplication"]["removed"] == 4
    assert first["totals"]["room_instances"] == 4
    assert first["totals"]["wall_masks"] == 4
    assert first["totals"]["door_labels"] == 4
    assert first["totals"]["window_labels"] == 4
    assert first["excluded_counts"] == {"spaces:GARAGE": 4}
    assert first["alignment"] == {"opening_labels": 8, "aligned_within_0_05m": 8,
                                  "maximum_distance_m": 0.0}
    assert first["validation_errors"] == []
    assert first["splits"]["leakage"] == {}
    assert set(first["splits"]["assignments"].values()) == {"train", "val", "test"}
    assert all(item["identical"] for item in first["determinism"])
    assert [item["hashes"] for item in first["renders"]] == [item["hashes"] for item in second["renders"]]

    output = Path(first["renders"][0]["output_dir"])
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    supervision = json.loads((output / "supervision.json").read_text(encoding="utf-8"))
    assert metadata["transform"]["pixels_per_metre"] == 16
    assert metadata["source"]["sample_csv_sha256"]
    assert any(item["excluded"] and item["source_subtype"] == "GARAGE" for item in supervision)
    assert all(item["geometry_wkt_metric"] for item in supervision)
    assert all(item["source_rows"] for item in supervision)
    assert {item["mapping_state"] for item in supervision} >= {"TRAIN", "MAP_TO_OTHER"}
    garage = next(item for item in supervision if item["source_subtype"] == "GARAGE")
    assert garage["canonical_candidate"] == "other_aec"
    for filename in ("image.png", "room_semantic.png", "room_instance.png", "separator.png",
                     "door.png", "window.png", "doors.txt", "windows.txt", "hashes.json"):
        assert (output / filename).is_file()
    with Image.open(output / "room_instance.png") as image:
        assert image.getbbox() is not None


def test_cross_building_duplicate_floors_are_clustered_into_one_split(tmp_path):
    rows = _building_rows(1, x=0) + _building_rows(2, x=100) + _building_rows(3, x=300)
    sample = tmp_path / "sample.csv"
    _write(sample, rows)

    manifest = convert_pilot(sample, tmp_path / "out", TAXONOMY, determinism_count=1)

    assert manifest["splits"]["evidence"]["exact_cross_building_floor_pairs"]
    assignments = manifest["splits"]["assignments"]
    assert assignments["site-1::1"] == assignments["site-1::2"]
    assert manifest["splits"]["leakage"] == {}


def test_rerunning_into_existing_output_is_deterministic(tmp_path):
    sample = tmp_path / "sample.csv"
    _write(sample, _building_rows(1, x=0))
    output = tmp_path / "out"

    first = convert_pilot(sample, output, TAXONOMY, determinism_count=1)
    second = convert_pilot(sample, output, TAXONOMY, determinism_count=1)

    assert first["renders"][0]["hashes"] == second["renders"][0]["hashes"]
    assert "hashes.json" not in second["renders"][0]["hashes"]
    assert second["determinism"] == [{"ids": second["renders"][0]["ids"], "identical": True}]


def test_converter_refuses_unbounded_building_input(tmp_path):
    rows = []
    for building in range(1, 12):
        rows.extend(_building_rows(building, x=building * 20.0))
    sample = tmp_path / "sample.csv"
    _write(sample, rows)

    with pytest.raises(ValueError, match="bounded converter refuses 11 buildings"):
        load_pilot(sample)


def test_automated_qa_proves_dedup_has_no_geometry_or_relationship_loss(tmp_path):
    rows = _building_rows(1, x=0, duplicate_wall=True)
    sample = tmp_path / "sample.csv"
    _write(sample, rows)
    raw = load_pilot(sample)
    deduplicated, stats = deduplicate_floor_geometry(raw)

    checks = automatic_checks(raw, deduplicated, load_taxonomy(TAXONOMY), stats)

    assert checks["invalid_polygons"] == []
    assert checks["orphan_openings"] == []
    assert checks["openings_outside_0_05m"] == []
    assert checks["deduplication"]["nonduplicate_geometry_loss"] == 0
    assert checks["deduplication"]["source_relationship_loss"] == 0
    assert checks["excluded_area_counts"] == {"GARAGE": 1}
    assert checks["excluded_area_mapping_state_counts"] == {"MAP_TO_OTHER": 1}
    assert checks["unclassified_source_semantics"] == {}
    assert checks["class_imbalance"]["by_family"]["spaces"]["counts"] == {"bedroom": 1}


def test_visual_qa_selector_covers_all_required_review_categories():
    profiles = []
    for index in range(8):
        profiles.append({
            "key": ("site", f"building-{index}", f"plan-{index}", f"floor-{index}"),
            "building": f"site::building-{index}", "building_floors": index + 1,
            "raw_rows": 10 + index * 10, "canonical_rows": 10 + index * 8,
            "collapsed_rows": index, "units": index + 1, "mapped_rooms": 0 if index == 6 else index + 1,
            "room_names": ["bedroom", "kitchen"] if index != 6 else [],
            "rare_score": 10 if index == 5 else 0, "garages": 1 if index == 6 else 0,
            "walls": 10 + index, "openings": index * 2, "extent_area_m2": 100 + index * 100,
        })

    selected = select_review_floors(profiles)

    assert len(selected) == 8
    assert {item["category"] for item in selected} == {
        "simple_residential", "multi_unit_residential", "large_building", "multi_floor_building",
        "dense_wall_opening", "rare_room_classes", "negative_garage_only", "shared_wall",
    }
    assert len({item["key"] for item in selected}) == 8
