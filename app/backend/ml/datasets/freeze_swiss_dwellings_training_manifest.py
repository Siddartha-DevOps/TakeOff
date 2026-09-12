"""Freeze a deterministic training manifest from completed Swiss conversion state.

This command is read-only with respect to conversion state and rendered samples.
It writes only the versioned manifest and its SHA-256 sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

from shapely import from_wkt
from shapely.ops import unary_union


MANIFEST_SCHEMA_VERSION = 1
TRAINING_DATASET_VERSION = "swiss-dwellings-takeoff-training-v1"
SOURCE_DATASET_VERSION = "3.0.0"
EXPECTED_TOTAL_FLOORS = 13_905
EXPECTED_ELIGIBLE_FLOORS = 13_902
EXPECTED_EXCLUDED_FLOOR_IDS = {"5593", "5639", "5640"}
SOURCE_DATA_EXCEPTION = "SOURCE_DATA_EXCEPTION"
RELEVANT_FILES = {
    "rendered_input_path": "image.png",
    "room_label_path": "room_semantic.png",
    "wall_separator_label_path": "separator.png",
    "door_label_path": "doors.txt",
    "window_label_path": "windows.txt",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri_path = path.resolve().as_posix()
    connection = sqlite3.connect(f"file:{uri_path}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _meta(connection: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in connection.execute("SELECT key,value FROM meta")}


def _maximum_opening_wall_distance(connection: sqlite3.Connection, floor: sqlite3.Row) -> float | None:
    rows = connection.execute(
        "SELECT entity_type,entity_subtype,geometry_wkt FROM canonical_geometries "
        "WHERE site_id=? AND building_id=? AND plan_id=? AND floor_id=?",
        (floor["site_id"], floor["building_id"], floor["plan_id"], floor["floor_id"]),
    ).fetchall()
    walls = [from_wkt(row["geometry_wkt"]) for row in rows
             if row["entity_type"] == "SEPARATOR" and row["entity_subtype"] == "WALL"]
    openings = [from_wkt(row["geometry_wkt"]) for row in rows
                if row["entity_type"] == "OPENING"
                and ("DOOR" in row["entity_subtype"] or "WINDOW" in row["entity_subtype"])]
    if not walls or not openings:
        return None
    wall_union = unary_union(walls)
    violations = [float(opening.distance(wall_union)) for opening in openings
                  if opening.distance(wall_union) > 0.05]
    return max(violations) if violations else 0.0


def build_training_manifest(state_database: str | Path) -> tuple[dict, list[str]]:
    state_database = Path(state_database)
    missing_references: list[str] = []
    with _readonly_connection(state_database) as connection:
        meta = _meta(connection)
        if meta.get("splits_complete") != "1" or meta.get("render_pass_complete") != "1":
            raise ValueError("conversion split/render pass is not complete")

        floor_total = connection.execute("SELECT COUNT(1) FROM floor_profiles").fetchone()[0]
        status_counts = dict(connection.execute(
            "SELECT status,COUNT(1) FROM render_status GROUP BY status"
        ).fetchall())
        eligible_rows = connection.execute(
            "SELECT p.floor_key,p.site_id,p.building_id,p.plan_id,p.floor_id,p.building_key,"
            "s.split,r.output_dir,r.result_json "
            "FROM render_status r JOIN floor_profiles p USING(floor_key) "
            "JOIN building_splits s USING(building_key) "
            "WHERE r.status='succeeded' ORDER BY p.floor_key"
        ).fetchall()
        excluded_rows = connection.execute(
            "SELECT p.floor_key,p.site_id,p.building_id,p.plan_id,p.floor_id,p.building_key,"
            "s.split,r.error,r.attempts "
            "FROM render_status r JOIN floor_profiles p USING(floor_key) "
            "JOIN building_splits s USING(building_key) "
            "WHERE r.status='failed' ORDER BY p.floor_key"
        ).fetchall()
        pending = connection.execute(
            "SELECT COUNT(1) FROM floor_profiles p LEFT JOIN render_status r USING(floor_key) "
            "WHERE r.floor_key IS NULL OR r.status NOT IN ('succeeded','failed')"
        ).fetchone()[0]

        excluded_ids = {row["floor_id"] for row in excluded_rows}
        if floor_total != EXPECTED_TOTAL_FLOORS:
            raise ValueError(f"expected {EXPECTED_TOTAL_FLOORS} floors, found {floor_total}")
        if len(eligible_rows) != EXPECTED_ELIGIBLE_FLOORS:
            raise ValueError(f"expected {EXPECTED_ELIGIBLE_FLOORS} eligible floors, found {len(eligible_rows)}")
        if excluded_ids != EXPECTED_EXCLUDED_FLOOR_IDS:
            raise ValueError(f"unexpected excluded floor IDs: {sorted(excluded_ids)}")
        if pending:
            raise ValueError(f"expected zero pending floors, found {pending}")

        eligible = []
        eligible_floor_keys = set()
        for row in eligible_rows:
            result = json.loads(row["result_json"])
            output_dir = Path(row["output_dir"])
            paths = {field: str((output_dir / filename).resolve())
                     for field, filename in RELEVANT_FILES.items()}
            for field, path_text in paths.items():
                if not Path(path_text).is_file():
                    missing_references.append(f"{row['floor_key']}:{field}:{path_text}")
            hashes = {
                filename: result.get("hashes", {}).get(filename)
                for filename in RELEVANT_FILES.values()
                if result.get("hashes", {}).get(filename)
            }
            eligible_floor_keys.add(row["floor_key"])
            eligible.append({
                "floor_key": row["floor_key"],
                "site_id": row["site_id"],
                "building_id": row["building_id"],
                "plan_id": row["plan_id"],
                "floor_id": row["floor_id"],
                "building_key": row["building_key"],
                "split": row["split"],
                **paths,
                "output_hashes_sha256": dict(sorted(hashes.items())),
                "source_version": SOURCE_DATASET_VERSION,
                "conversion_version": meta["conversion_version"],
            })

        exclusions = []
        for row in excluded_rows:
            exclusions.append({
                "floor_key": row["floor_key"],
                "site_id": row["site_id"],
                "building_id": row["building_id"],
                "plan_id": row["plan_id"],
                "floor_id": row["floor_id"],
                "building_key": row["building_key"],
                "split": row["split"],
                "reason": SOURCE_DATA_EXCEPTION,
                "recorded_render_error": row["error"],
                "maximum_opening_to_wall_distance_m": _maximum_opening_wall_distance(connection, row),
                "attempts": row["attempts"],
                "source_version": SOURCE_DATASET_VERSION,
                "conversion_version": meta["conversion_version"],
            })

        excluded_floor_keys = {row["floor_key"] for row in excluded_rows}
        accidental_inclusions = sorted(eligible_floor_keys & excluded_floor_keys)
        duplicate_edges_crossing = connection.execute(
            "SELECT COUNT(1) FROM duplicate_pairs d "
            "JOIN floor_profiles lp ON lp.floor_key=d.left_floor "
            "JOIN floor_profiles rp ON rp.floor_key=d.right_floor "
            "JOIN building_splits ls ON ls.building_key=lp.building_key "
            "JOIN building_splits rs ON rs.building_key=rp.building_key "
            "WHERE ls.split<>rs.split"
        ).fetchone()[0]
        duplicate_clusters_crossing = connection.execute(
            "SELECT COUNT(1) FROM (SELECT duplicate_cluster FROM building_splits "
            "GROUP BY duplicate_cluster HAVING COUNT(DISTINCT split)>1)"
        ).fetchone()[0]
        assigned_buildings = dict(connection.execute(
            "SELECT split,COUNT(1) FROM building_splits GROUP BY split ORDER BY split"
        ).fetchall())
        eligible_buildings = dict(connection.execute(
            "SELECT s.split,COUNT(DISTINCT p.building_key) FROM render_status r "
            "JOIN floor_profiles p USING(floor_key) JOIN building_splits s USING(building_key) "
            "WHERE r.status='succeeded' GROUP BY s.split ORDER BY s.split"
        ).fetchall())
        eligible_floors = dict(Counter(row["split"] for row in eligible_rows))

        manifest = {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "dataset": {
                "name": "Swiss Dwellings",
                "training_dataset_version": TRAINING_DATASET_VERSION,
                "source_version": SOURCE_DATASET_VERSION,
                "source_doi": "10.5281/zenodo.7788422",
                "source_sha256": meta.get("source_sha256"),
                "conversion_version": meta["conversion_version"],
                "profile_version": meta.get("profile_version"),
            },
            "freeze": {
                "split_assignment_source": f"{state_database.resolve()}#building_splits",
                "split_assignments_persisted_at": meta.get("splits_updated_at"),
                "split_ratios": {"train": 0.80, "val": 0.10, "test": 0.10},
                "random_seed": None,
                "rule": "existing duplicate-connected building clusters and assignments preserved exactly",
                "eligible_render_status": "succeeded",
            },
            "summary": {
                "total_floors": floor_total,
                "eligible_floor_count": len(eligible),
                "excluded_floor_count": len(exclusions),
                "pending_floor_count": pending,
                "status_counts": dict(sorted(status_counts.items())),
                "eligible_floors_by_split": dict(sorted(eligible_floors.items())),
                "eligible_buildings_by_split": dict(sorted(eligible_buildings.items())),
                "assigned_buildings_by_split": dict(sorted(assigned_buildings.items())),
                "missing_file_reference_count": len(missing_references),
                "excluded_floors_accidentally_included": accidental_inclusions,
                "duplicate_relationships_crossing_splits": duplicate_edges_crossing,
                "duplicate_connected_clusters_crossing_splits": duplicate_clusters_crossing,
            },
            "eligible_floors": eligible,
            "exclusions": exclusions,
        }
    return manifest, missing_references


def validate_training_manifest(manifest: dict, missing_references: list[str]) -> None:
    summary = manifest["summary"]
    if missing_references:
        raise ValueError(f"manifest contains {len(missing_references)} missing file references")
    if summary["excluded_floors_accidentally_included"]:
        raise ValueError("excluded floors are present among eligible floors")
    if summary["duplicate_relationships_crossing_splits"]:
        raise ValueError("duplicate relationships cross frozen splits")
    if summary["duplicate_connected_clusters_crossing_splits"]:
        raise ValueError("duplicate-connected building clusters cross frozen splits")
    if summary["eligible_floor_count"] + summary["excluded_floor_count"] != summary["total_floors"]:
        raise ValueError("eligible/excluded floor reconciliation failed")
    floor_keys = [row["floor_key"] for row in manifest["eligible_floors"]]
    if len(floor_keys) != len(set(floor_keys)):
        raise ValueError("eligible manifest contains duplicate floor keys")


def freeze_training_manifest(state_database: str | Path, output_path: str | Path) -> dict:
    manifest, missing = build_training_manifest(state_database)
    validate_training_manifest(manifest, missing)
    payload = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    digest = _sha256_bytes(payload)
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, output_path)
    sidecar = output_path.with_suffix(output_path.suffix + ".sha256")
    sidecar_payload = f"{digest}  {output_path.name}\n".encode("ascii")
    temporary_sidecar = sidecar.with_suffix(sidecar.suffix + ".tmp")
    temporary_sidecar.write_bytes(sidecar_payload)
    os.replace(temporary_sidecar, sidecar)
    return {"manifest_path": str(output_path), "sha256_path": str(sidecar),
            "sha256": digest, "summary": manifest["summary"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(freeze_training_manifest(args.state_database, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
