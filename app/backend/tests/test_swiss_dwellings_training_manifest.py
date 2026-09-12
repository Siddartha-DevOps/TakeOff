"""Validation tests for the frozen Swiss Dwellings training manifest."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import ml.datasets.freeze_swiss_dwellings_training_manifest as freezer


def _state(tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "state.sqlite3"
    samples = tmp_path / "samples"
    connection = sqlite3.connect(state)
    connection.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE floor_profiles(floor_key TEXT PRIMARY KEY,site_id TEXT,building_id TEXT,
          plan_id TEXT,floor_id TEXT,building_key TEXT);
        CREATE TABLE building_splits(building_key TEXT PRIMARY KEY,duplicate_cluster TEXT,split TEXT);
        CREATE TABLE duplicate_pairs(left_floor TEXT,right_floor TEXT,match_type TEXT);
        CREATE TABLE render_status(floor_key TEXT PRIMARY KEY,status TEXT,attempts INTEGER,
          output_dir TEXT,result_json TEXT,error TEXT);
        CREATE TABLE canonical_geometries(geometry_id TEXT PRIMARY KEY,site_id TEXT,building_id TEXT,
          plan_id TEXT,floor_id TEXT,entity_type TEXT,entity_subtype TEXT,geometry_wkt TEXT);
    """)
    connection.executemany("INSERT INTO meta VALUES(?,?)", [
        ("splits_complete", "1"), ("render_pass_complete", "1"),
        ("conversion_version", "swiss-dwellings-takeoff-full-v1"),
        ("profile_version", "profile-v1"), ("source_sha256", "source-hash"),
        ("splits_updated_at", "2026-09-08T09:07:50+00:00"),
    ])
    excluded = {"5593", "5639", "5640"}
    for index in range(6):
        floor_id = str(index) if index < 3 else sorted(excluded)[index - 3]
        floor_key = f"s\x1fb{index}\x1fp{index}\x1f{floor_id}"
        building_key = f"s::b{index}"
        split = "train" if index % 10 < 8 else "val" if index % 10 == 8 else "test"
        connection.execute("INSERT INTO floor_profiles VALUES(?,?,?,?,?,?)",
                           (floor_key, "s", f"b{index}", f"p{index}", floor_id, building_key))
        connection.execute("INSERT INTO building_splits VALUES(?,?,?)", (building_key, building_key, split))
        if floor_id in excluded:
            connection.execute("INSERT INTO render_status VALUES(?,?,?,?,?,?)",
                               (floor_key, "failed", 1, None, None, "opening farther than 0.05m from wall"))
            connection.execute("INSERT INTO canonical_geometries VALUES(?,?,?,?,?,?,?,?)",
                               (f"w{index}", "s", f"b{index}", f"p{index}", floor_id,
                                "SEPARATOR", "WALL", "POLYGON ((0 0,10 0,10 .2,0 .2,0 0))"))
            connection.execute("INSERT INTO canonical_geometries VALUES(?,?,?,?,?,?,?,?)",
                               (f"o{index}", "s", f"b{index}", f"p{index}", floor_id,
                                "OPENING", "DOOR", "POLYGON ((0 .4,1 .4,1 .5,0 .5,0 .4))"))
        else:
            output = samples / floor_key.replace("\x1f", "_")
            output.mkdir(parents=True)
            hashes = {}
            for filename in freezer.RELEVANT_FILES.values():
                path = output / filename
                path.write_bytes(filename.encode())
                hashes[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
            result = {"hashes": hashes}
            connection.execute("INSERT INTO render_status VALUES(?,?,?,?,?,?)",
                               (floor_key, "succeeded", 1, str(output), json.dumps(result), None))
    connection.commit()
    connection.close()
    return state, samples


def test_freeze_is_deterministic_complete_and_exclusion_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(freezer, "EXPECTED_TOTAL_FLOORS", 6)
    monkeypatch.setattr(freezer, "EXPECTED_ELIGIBLE_FLOORS", 3)
    state, _ = _state(tmp_path)
    output = tmp_path / "training_manifest.json"
    first = freezer.freeze_training_manifest(state, output)
    first_bytes = output.read_bytes()
    second = freezer.freeze_training_manifest(state, output)

    assert output.read_bytes() == first_bytes
    assert first["sha256"] == second["sha256"] == hashlib.sha256(first_bytes).hexdigest()
    manifest = json.loads(first_bytes)
    assert manifest["summary"]["eligible_floor_count"] == 3
    assert manifest["summary"]["excluded_floor_count"] == 3
    assert manifest["summary"]["pending_floor_count"] == 0
    assert manifest["summary"]["missing_file_reference_count"] == 0
    assert manifest["summary"]["excluded_floors_accidentally_included"] == []
    assert manifest["summary"]["duplicate_relationships_crossing_splits"] == 0
    assert manifest["summary"]["duplicate_connected_clusters_crossing_splits"] == 0
    assert {row["floor_id"] for row in manifest["exclusions"]} == {"5593", "5639", "5640"}
    assert {row["reason"] for row in manifest["exclusions"]} == {"SOURCE_DATA_EXCEPTION"}
    assert all(row["maximum_opening_to_wall_distance_m"] == pytest.approx(0.2)
               for row in manifest["exclusions"])
    assert output.with_suffix(".json.sha256").read_text().startswith(first["sha256"])


def test_missing_render_reference_blocks_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr(freezer, "EXPECTED_TOTAL_FLOORS", 6)
    monkeypatch.setattr(freezer, "EXPECTED_ELIGIBLE_FLOORS", 3)
    state, samples = _state(tmp_path)
    next(samples.rglob("image.png")).unlink()
    with pytest.raises(ValueError, match="missing file references"):
        freezer.freeze_training_manifest(state, tmp_path / "training_manifest.json")
