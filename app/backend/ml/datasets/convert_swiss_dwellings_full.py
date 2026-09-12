"""Resumable full-corpus Swiss Dwellings v3.0.0 converter.

The raw geometries CSV is streamed in bounded chunks into an external SQLite
state database. PostgreSQL/application code is deliberately not involved. The
state database is both a durable checkpoint and the reconciliation ledger for
canonical geometries and all original source relationships.

This command must be pointed at an output directory outside the Git checkout.
It is safe to rerun: completed phases and verified floor outputs are reused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from shapely import from_wkt, normalize, set_precision, to_wkb, to_wkt
from shapely.affinity import translate
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ml.datasets.convert_swiss_dwellings_pilot import (
    DEFAULT_PADDING_M,
    DEFAULT_PPM,
    FLOOR_COLUMNS,
    MAX_DIMENSION_PX,
    REQUIRED_COLUMNS,
    SOURCE_DOI,
    SOURCE_VERSION,
    _building_key,
    _mapping_for,
    _safe_token,
    _sha256_bytes,
    _sha256_file,
    _validate_render,
    load_taxonomy,
    render_floor,
)


FULL_CONVERSION_VERSION = "swiss-dwellings-takeoff-full-v1"
STATE_SCHEMA_VERSION = 1
PROFILE_VERSION = "metric-union-grid-0.01m-pointwise-v1"
DEFAULT_CHUNK_ROWS = 20_000
ALIGNMENT_TOLERANCE_M = 0.05
NEAR_DUPLICATE_HAUSDORFF_M = 0.10
NEAR_DUPLICATE_MIN_AREA_RATIO = 0.98


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=120)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-131072")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize_state(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS canonical_geometries (
            geometry_id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            building_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            floor_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_subtype TEXT NOT NULL,
            geometry_hash TEXT NOT NULL,
            geometry_wkt TEXT NOT NULL,
            unit_usage TEXT NOT NULL,
            elevation TEXT NOT NULL,
            height TEXT NOT NULL,
            source_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(site_id, building_id, plan_id, floor_id,
                   entity_type, entity_subtype, geometry_hash)
        );
        CREATE TABLE IF NOT EXISTS source_relationships (
            source_row_number INTEGER PRIMARY KEY,
            geometry_id TEXT NOT NULL REFERENCES canonical_geometries(geometry_id),
            apartment_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            area_id TEXT NOT NULL,
            original_geometry_wkt TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invalid_source_rows (
            source_row_number INTEGER PRIMARY KEY,
            reason TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS floor_profiles (
            floor_key TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            building_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            floor_id TEXT NOT NULL,
            building_key TEXT NOT NULL,
            canonical_count INTEGER NOT NULL,
            source_count INTEGER NOT NULL,
            unit_count INTEGER NOT NULL,
            minx REAL NOT NULL,
            miny REAL NOT NULL,
            maxx REAL NOT NULL,
            maxy REAL NOT NULL,
            normalized_hash TEXT NOT NULL,
            normalized_wkb BLOB NOT NULL,
            normalized_area REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS building_splits (
            building_key TEXT PRIMARY KEY,
            duplicate_cluster TEXT NOT NULL,
            split TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS duplicate_pairs (
            left_floor TEXT NOT NULL,
            right_floor TEXT NOT NULL,
            match_type TEXT NOT NULL,
            area_ratio REAL NOT NULL,
            hausdorff_m REAL NOT NULL,
            PRIMARY KEY(left_floor, right_floor, match_type)
        );
        CREATE TABLE IF NOT EXISTS render_status (
            floor_key TEXT PRIMARY KEY REFERENCES floor_profiles(floor_key),
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            output_dir TEXT,
            result_json TEXT,
            error TEXT,
            started_at TEXT,
            completed_at TEXT
        );
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('state_schema_version', ?)",
        (str(STATE_SCHEMA_VERSION),),
    )
    connection.commit()


def _meta_get(connection: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def _meta_set(connection: sqlite3.Connection, key: str, value: object) -> None:
    connection.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def _require_external_output(output_root: Path, repository_root: Path | None) -> None:
    output_root = output_root.resolve()
    if repository_root is not None:
        repository_root = repository_root.resolve()
        if output_root == repository_root or repository_root in output_root.parents:
            raise ValueError("full converted dataset must remain outside the Git repository")


def _validate_source_columns(source_csv: Path) -> list[str]:
    columns = list(pd.read_csv(source_csv, nrows=0).columns)
    missing = sorted(REQUIRED_COLUMNS - set(columns))
    if missing:
        raise ValueError(f"source CSV missing required columns: {missing}")
    return columns


def _normalize_geometry(raw_wkt: str) -> tuple[BaseGeometry | None, str | None]:
    try:
        geometry = from_wkt(raw_wkt, on_invalid="ignore")
    except Exception as exc:
        return None, f"malformed WKT: {exc}"
    if geometry is None:
        return None, "malformed WKT"
    if geometry.is_empty:
        return None, "empty geometry"
    if not geometry.is_valid:
        return None, "invalid geometry"
    return normalize(geometry), None


def ingest_source(
    connection: sqlite3.Connection,
    source_csv: Path,
    *,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
    stop_after_rows: int | None = None,
    progress_every: int = 100_000,
) -> dict:
    """Stream source rows into the durable ledger, resuming by CSV row number."""
    _validate_source_columns(source_csv)
    if _meta_get(connection, "ingest_complete", "0") == "1":
        return {
            "rows_processed": int(_meta_get(connection, "ingest_rows_processed", "0") or 0),
            "new_relationships": 0,
            "new_invalid": 0,
            "complete": True,
        }
    last_done = int(_meta_get(connection, "ingest_rows_processed", "0") or 0)
    total_seen = last_done
    inserted_sources = 0
    invalid = 0
    started = time.monotonic()

    reader = pd.read_csv(
        source_csv,
        dtype=str,
        keep_default_na=False,
        usecols=sorted(REQUIRED_COLUMNS),
        chunksize=chunk_rows,
        low_memory=False,
    )
    chunk_start = 0
    for chunk in reader:
        chunk_end = chunk_start + len(chunk)
        if chunk_end <= last_done:
            chunk_start = chunk_end
            continue
        if chunk_start < last_done:
            chunk = chunk.iloc[last_done - chunk_start :]
            chunk_start = last_done
        if stop_after_rows is not None:
            remaining = stop_after_rows - (total_seen - last_done)
            if remaining <= 0:
                break
            chunk = chunk.iloc[:remaining]
        canonical_rows: dict[str, tuple] = {}
        relationships: list[tuple] = []
        invalid_rows: list[tuple] = []
        source_counts = Counter()
        for offset, row in enumerate(chunk.itertuples(index=False), start=1):
            source_index = chunk_start + offset
            source_row_number = source_index + 1  # one-based including header
            values = row._asdict()
            raw_geometry = str(values["geometry"])
            geometry, error = _normalize_geometry(raw_geometry)
            required_ids = [str(values[column]).strip() for column in FLOOR_COLUMNS]
            if not all(required_ids):
                error = error or "blank required hierarchy ID"
            if error:
                invalid_rows.append((source_row_number, error, json.dumps(values, sort_keys=True)))
                invalid += 1
                continue
            entity_type = str(values["entity_type"]).strip().upper()
            subtype = str(values["entity_subtype"]).strip().upper() or "NOT_DEFINED"
            geometry_wkb = to_wkb(geometry, hex=False)
            geometry_hash = _sha256_bytes(geometry_wkb)
            geometry_id = _sha256_bytes(
                ("|".join((SOURCE_VERSION, *required_ids, entity_type, subtype, geometry_hash))).encode("utf-8")
            )
            canonical_rows.setdefault(
                geometry_id,
                (
                    geometry_id, *required_ids, entity_type, subtype, geometry_hash,
                    to_wkt(geometry, rounding_precision=-1, trim=False),
                    str(values["unit_usage"]).strip(), str(values["elevation"]).strip(),
                    str(values["height"]).strip(),
                ),
            )
            source_counts[geometry_id] += 1
            relationships.append(
                (
                    source_row_number, geometry_id, str(values["apartment_id"]).strip(),
                    str(values["unit_id"]).strip(), str(values["area_id"]).strip(), raw_geometry,
                )
            )
        with connection:
            connection.executemany(
                "INSERT OR IGNORE INTO canonical_geometries("
                "geometry_id,site_id,building_id,plan_id,floor_id,entity_type,entity_subtype,"
                "geometry_hash,geometry_wkt,unit_usage,elevation,height) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                canonical_rows.values(),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO source_relationships("
                "source_row_number,geometry_id,apartment_id,unit_id,area_id,original_geometry_wkt) "
                "VALUES(?,?,?,?,?,?)",
                relationships,
            )
            connection.executemany(
                "INSERT OR IGNORE INTO invalid_source_rows(source_row_number,reason,raw_json) VALUES(?,?,?)",
                invalid_rows,
            )
            connection.executemany(
                "UPDATE canonical_geometries SET source_count=source_count+? WHERE geometry_id=?",
                [(count, geometry_id) for geometry_id, count in source_counts.items()],
            )
            total_seen = chunk_start + len(chunk)
            _meta_set(connection, "ingest_rows_processed", total_seen)
            _meta_set(connection, "ingest_updated_at", _utc_now())
        inserted_sources += len(relationships)
        chunk_start = chunk_end
        if total_seen and (total_seen % progress_every < len(chunk)):
            elapsed = max(time.monotonic() - started, 0.001)
            print(json.dumps({"phase": "ingest", "geometry_rows_processed": total_seen,
                              "rows_per_second": round((total_seen - last_done) / elapsed, 1)}), flush=True)
        if stop_after_rows is not None and total_seen - last_done >= stop_after_rows:
            break

    fully_consumed = stop_after_rows is None and total_seen >= chunk_start
    if fully_consumed:
        with connection:
            _meta_set(connection, "ingest_complete", "1")
            connection.executescript(
                "CREATE INDEX IF NOT EXISTS ix_canonical_floor ON canonical_geometries"
                "(site_id,building_id,plan_id,floor_id);"
                "CREATE INDEX IF NOT EXISTS ix_source_geometry ON source_relationships(geometry_id);"
                "CREATE INDEX IF NOT EXISTS ix_source_unit ON source_relationships(unit_id);"
            )
    return {
        "rows_processed": int(_meta_get(connection, "ingest_rows_processed", "0") or 0),
        "new_relationships": inserted_sources,
        "new_invalid": invalid,
        "complete": _meta_get(connection, "ingest_complete", "0") == "1",
    }


def _floor_key_string(values: tuple[str, str, str, str]) -> str:
    return "\x1f".join(values)


def _floor_key_values(value: str) -> tuple[str, str, str, str]:
    parts = tuple(value.split("\x1f"))
    if len(parts) != 4:
        raise ValueError(f"invalid durable floor key: {value!r}")
    return parts  # type: ignore[return-value]


def _load_floor_frame(connection: sqlite3.Connection, floor: tuple[str, str, str, str]) -> pd.DataFrame:
    rows = connection.execute(
        "SELECT * FROM canonical_geometries WHERE site_id=? AND building_id=? AND plan_id=? AND floor_id=? "
        "ORDER BY entity_type,entity_subtype,geometry_hash",
        floor,
    ).fetchall()
    geometry_ids = [row["geometry_id"] for row in rows]
    relationship_map: dict[str, list[dict]] = defaultdict(list)
    if geometry_ids:
        for start in range(0, len(geometry_ids), 900):
            batch = geometry_ids[start : start + 900]
            placeholders = ",".join("?" for _ in batch)
            relationships = connection.execute(
                f"SELECT geometry_id,source_row_number,apartment_id,unit_id,area_id,original_geometry_wkt "
                f"FROM source_relationships WHERE geometry_id IN ({placeholders}) ORDER BY source_row_number",
                batch,
            ).fetchall()
            for relationship in relationships:
                relationship_map[relationship["geometry_id"]].append({
                    key: relationship[key] for key in (
                        "source_row_number", "apartment_id", "unit_id", "area_id", "original_geometry_wkt"
                    )
                })
    records = []
    for row in rows:
        record = dict(row)
        record["geometry"] = row["geometry_wkt"]
        record["_geometry"] = from_wkt(row["geometry_wkt"])
        record["source_rows"] = relationship_map[row["geometry_id"]]
        records.append(record)
    return pd.DataFrame(records)


def build_floor_profiles(connection: sqlite3.Connection, *, stop_after_floors: int | None = None) -> dict:
    if _meta_get(connection, "ingest_complete", "0") != "1" and stop_after_floors is None:
        raise ValueError("cannot profile an incomplete ingestion")
    if _meta_get(connection, "profile_version") != PROFILE_VERSION:
        with connection:
            connection.execute("DELETE FROM render_status")
            connection.execute("DELETE FROM duplicate_pairs")
            connection.execute("DELETE FROM building_splits")
            connection.execute("DELETE FROM floor_profiles")
            _meta_set(connection, "profiles_complete", "0")
            _meta_set(connection, "splits_complete", "0")
            _meta_set(connection, "profile_version", PROFILE_VERSION)
    floors = connection.execute(
        "SELECT DISTINCT site_id,building_id,plan_id,floor_id FROM canonical_geometries "
        "ORDER BY site_id,building_id,plan_id,floor_id"
    ).fetchall()
    completed = {row[0] for row in connection.execute("SELECT floor_key FROM floor_profiles")}
    new_count = 0
    for index, row in enumerate(floors, start=1):
        floor = tuple(row)
        key = _floor_key_string(floor)
        if key in completed:
            continue
        frame = _load_floor_frame(connection, floor)
        positive = [item for item in frame._geometry if item.area > 0]
        if not positive:
            continue
        merged = unary_union(positive)
        minx, miny, maxx, maxy = merged.bounds
        # This is a duplicate-signature geometry only. ``pointwise`` avoids GEOS
        # topology reconstruction failures on complex but valid source unions;
        # the canonical metric WKT used for labels remains completely untouched.
        normalized = normalize(set_precision(
            translate(merged, xoff=-minx, yoff=-miny), 0.01, mode="pointwise"
        ))
        normalized_wkb = to_wkb(normalized, hex=False)
        source_count = int(frame.source_count.sum())
        unit_count = connection.execute(
            "SELECT COUNT(DISTINCT s.unit_id) FROM source_relationships s "
            "JOIN canonical_geometries c ON c.geometry_id=s.geometry_id "
            "WHERE c.site_id=? AND c.building_id=? AND c.plan_id=? AND c.floor_id=?",
            floor,
        ).fetchone()[0]
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO floor_profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, *floor, _building_key(floor[0], floor[1]), len(frame), source_count, unit_count,
                 minx, miny, maxx, maxy, _sha256_bytes(normalized_wkb), normalized_wkb, normalized.area),
            )
            _meta_set(connection, "profile_updated_at", _utc_now())
        new_count += 1
        if index % 100 == 0:
            print(json.dumps({"phase": "profile", "floors_processed": len(completed) + new_count,
                              "floors_total": len(floors)}), flush=True)
        if stop_after_floors is not None and new_count >= stop_after_floors:
            break
    total = connection.execute("SELECT COUNT(*) FROM floor_profiles").fetchone()[0]
    if total == len(floors):
        with connection:
            _meta_set(connection, "profiles_complete", "1")
    return {"new": new_count, "processed": total, "total": len(floors),
            "complete": total == len(floors)}


class _UnionFind:
    def __init__(self, values: list[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: str, right: str) -> None:
        left, right = self.find(left), self.find(right)
        if left != right:
            self.parent[max(left, right)] = min(left, right)


def assign_full_splits(connection: sqlite3.Connection) -> dict:
    """Cluster cross-building duplicate floors, then split deterministic clusters."""
    profiles = connection.execute("SELECT * FROM floor_profiles ORDER BY floor_key").fetchall()
    buildings = sorted({row["building_key"] for row in profiles})
    union_find = _UnionFind(buildings)
    exact_groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for profile in profiles:
        exact_groups[profile["normalized_hash"]].append(profile)
    exact_pairs = 0
    with connection:
        connection.execute("DELETE FROM duplicate_pairs")
        for group in exact_groups.values():
            by_building = {}
            for item in group:
                by_building.setdefault(item["building_key"], item)
            representatives = sorted(by_building.values(), key=lambda item: item["floor_key"])
            for index, left in enumerate(representatives):
                for right in representatives[index + 1 :]:
                    union_find.union(left["building_key"], right["building_key"])
                    connection.execute(
                        "INSERT OR IGNORE INTO duplicate_pairs VALUES(?,?,?,?,?)",
                        (left["floor_key"], right["floor_key"], "exact", 1.0, 0.0),
                    )
                    exact_pairs += 1

    # Near comparison is deliberately bucketed, avoiding an all-pairs corpus scan.
    buckets: dict[tuple[int, int, int], list[sqlite3.Row]] = defaultdict(list)
    for profile in profiles:
        width = profile["maxx"] - profile["minx"]
        height = profile["maxy"] - profile["miny"]
        area = max(profile["normalized_area"], 1e-9)
        buckets[(round(width / 0.25), round(height / 0.25), round(math.log(area) / math.log(1.01)))].append(profile)
    near_pairs = 0
    seen_pairs = set()
    bucket_total = len(buckets)
    for bucket_index, (key, group) in enumerate(buckets.items(), start=1):
        candidates = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for da in (-2, -1, 0, 1, 2):
                    candidates.extend(buckets.get((key[0] + dx, key[1] + dy, key[2] + da), []))
        for left in group:
            left_shape = from_wkt("GEOMETRYCOLLECTION EMPTY") if not left["normalized_wkb"] else None
            for right in candidates:
                pair = tuple(sorted((left["floor_key"], right["floor_key"])))
                if pair[0] == pair[1] or pair in seen_pairs or left["building_key"] == right["building_key"]:
                    continue
                seen_pairs.add(pair)
                if left["normalized_hash"] == right["normalized_hash"]:
                    continue
                area_ratio = min(left["normalized_area"], right["normalized_area"]) / max(
                    left["normalized_area"], right["normalized_area"]
                )
                if area_ratio < NEAR_DUPLICATE_MIN_AREA_RATIO:
                    continue
                if left_shape is None:
                    from shapely import from_wkb
                    left_shape = from_wkb(left["normalized_wkb"]).simplify(0.01, preserve_topology=True)
                from shapely import from_wkb
                right_shape = from_wkb(right["normalized_wkb"]).simplify(0.01, preserve_topology=True)
                distance = float(left_shape.hausdorff_distance(right_shape))
                if distance <= NEAR_DUPLICATE_HAUSDORFF_M:
                    union_find.union(left["building_key"], right["building_key"])
                    with connection:
                        connection.execute(
                            "INSERT OR IGNORE INTO duplicate_pairs VALUES(?,?,?,?,?)",
                            (*pair, "near", area_ratio, distance),
                        )
                    near_pairs += 1
        if bucket_index % 500 == 0:
            print(json.dumps({"phase": "duplicate_scan", "buckets_processed": bucket_index,
                              "buckets_total": bucket_total, "exact_pairs": exact_pairs,
                              "near_pairs": near_pairs}), flush=True)

    clusters: dict[str, list[str]] = defaultdict(list)
    for building in buildings:
        clusters[union_find.find(building)].append(building)
    ordered_clusters = sorted(
        (sorted(values) for values in clusters.values()),
        key=lambda values: _sha256_bytes((FULL_CONVERSION_VERSION + "|" + "|".join(values)).encode()),
    )
    assignments = {}
    for cluster in ordered_clusters:
        token = "|".join(cluster)
        percentile = int(_sha256_bytes(token.encode())[:8], 16) / 0xFFFFFFFF
        split = "test" if percentile < 0.10 else "val" if percentile < 0.20 else "train"
        for building in cluster:
            assignments[building] = (token, split)
    with connection:
        connection.execute("DELETE FROM building_splits")
        connection.executemany(
            "INSERT INTO building_splits(building_key,duplicate_cluster,split) VALUES(?,?,?)",
            [(building, cluster, split) for building, (cluster, split) in assignments.items()],
        )
        _meta_set(connection, "splits_complete", "1")
        _meta_set(connection, "splits_updated_at", _utc_now())
    return {
        "building_count": len(buildings),
        "cluster_count": len(ordered_clusters),
        "exact_cross_building_pairs": exact_pairs,
        "near_cross_building_pairs": near_pairs,
        "buildings_by_split": dict(sorted(Counter(value[1] for value in assignments.values()).items())),
    }


def _render_output_valid(output_dir: Path, result: dict) -> bool:
    expected = result.get("hashes", {})
    return bool(expected) and all((output_dir / name).is_file() and _sha256_file(output_dir / name) == digest
                                  for name, digest in expected.items())


def render_full(
    connection: sqlite3.Connection,
    output_root: Path,
    taxonomy: dict,
    source_hash: str,
    *,
    pixels_per_metre: int = DEFAULT_PPM,
    padding_m: float = DEFAULT_PADDING_M,
    stop_after_floors: int | None = None,
) -> dict:
    profiles = connection.execute(
        "SELECT p.*,s.split FROM floor_profiles p JOIN building_splits s USING(building_key) ORDER BY p.floor_key"
    ).fetchall()
    completed = 0
    failed = 0
    retried = 0
    newly_rendered = 0
    for index, profile in enumerate(profiles, start=1):
        key = profile["floor_key"]
        prior = connection.execute("SELECT * FROM render_status WHERE floor_key=?", (key,)).fetchone()
        if prior and prior["status"] == "succeeded":
            result = json.loads(prior["result_json"])
            if _render_output_valid(Path(prior["output_dir"]), result):
                completed += 1
                continue
            retried += 1
        floor = _floor_key_values(key)
        name = "__".join(_safe_token(value) for value in floor)
        final_dir = output_root / "samples" / profile["split"] / name
        staging_dir = output_root / "staging" / name
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        with connection:
            connection.execute(
                "INSERT INTO render_status(floor_key,status,attempts,started_at,error) VALUES(?, 'running', 1, ?, NULL) "
                "ON CONFLICT(floor_key) DO UPDATE SET status='running',attempts=attempts+1,started_at=excluded.started_at,error=NULL",
                (key, _utc_now()),
            )
        try:
            frame = _load_floor_frame(connection, floor)
            result = render_floor(
                frame, staging_dir, taxonomy,
                pixels_per_metre=pixels_per_metre, padding_m=padding_m,
                split=profile["split"], source_csv_sha256=source_hash,
                compress_supervision=True, conversion_version=FULL_CONVERSION_VERSION,
            )
            errors = _validate_render(result, taxonomy)
            if errors:
                raise ValueError("; ".join(errors))
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            if final_dir.exists():
                shutil.rmtree(final_dir)
            staging_dir.replace(final_dir)
            result["output_dir"] = str(final_dir)
            with connection:
                connection.execute(
                    "UPDATE render_status SET status='succeeded',output_dir=?,result_json=?,error=NULL,completed_at=? "
                    "WHERE floor_key=?",
                    (str(final_dir), json.dumps(result, separators=(",", ":"), sort_keys=True), _utc_now(), key),
                )
            completed += 1
            newly_rendered += 1
        except Exception as exc:
            failed += 1
            with connection:
                connection.execute(
                    "UPDATE render_status SET status='failed',error=?,completed_at=? WHERE floor_key=?",
                    (str(exc), _utc_now(), key),
                )
        if index % 25 == 0:
            print(json.dumps({"phase": "render", "floors_processed": completed + failed,
                              "floors_total": len(profiles), "failures": failed,
                              "output_bytes": directory_size(output_root)}), flush=True)
        if stop_after_floors is not None and newly_rendered >= stop_after_floors:
            break
    if completed + failed == len(profiles):
        with connection:
            _meta_set(connection, "render_pass_complete", "1")
    return {"processed": completed + failed, "total": len(profiles), "succeeded": completed,
            "failed": failed, "new": newly_rendered, "retried": retried}


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def _room_overlap_count(connection: sqlite3.Connection) -> tuple[int, list[dict]]:
    """Count positive-area overlaps among mapped room instances, floor by floor."""
    taxonomy_path = Path(__file__).with_name("swiss_dwellings_taxonomy_v1.json")
    taxonomy = load_taxonomy(taxonomy_path)
    approved = set(taxonomy["spaces"]["source_mapping"])
    total = 0
    examples = []
    for profile in connection.execute("SELECT floor_key FROM floor_profiles ORDER BY floor_key"):
        floor = _floor_key_values(profile["floor_key"])
        rows = connection.execute(
            "SELECT geometry_id,entity_subtype,geometry_wkt FROM canonical_geometries "
            "WHERE site_id=? AND building_id=? AND plan_id=? AND floor_id=? AND entity_type='AREA'",
            floor,
        ).fetchall()
        rooms = [(row["geometry_id"], from_wkt(row["geometry_wkt"])) for row in rows
                 if row["entity_subtype"] in approved]
        # Typical floors have tens of rooms; bounding-box rejection keeps this bounded.
        for left_index, (left_id, left) in enumerate(rooms):
            left_bounds = left.bounds
            for right_id, right in rooms[left_index + 1 :]:
                right_bounds = right.bounds
                if (left_bounds[2] <= right_bounds[0] or right_bounds[2] <= left_bounds[0]
                        or left_bounds[3] <= right_bounds[1] or right_bounds[3] <= left_bounds[1]):
                    continue
                overlap = float(left.intersection(right).area)
                if overlap > 1e-6:
                    total += 1
                    if len(examples) < 100:
                        examples.append({"floor": list(floor), "left": left_id, "right": right_id,
                                         "overlap_m2": overlap})
    return total, examples


def _count_distinct(connection: sqlite3.Connection, expression: str, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(DISTINCT {expression}) FROM {table}").fetchone()[0])


def finalize_qa(connection: sqlite3.Connection, output_root: Path, taxonomy: dict,
                source_csv: Path, source_hash: str, *, determinism_count: int = 10) -> dict:
    source_rows = int(_meta_get(connection, "ingest_rows_processed", "0") or 0)
    invalid_rows = connection.execute("SELECT COUNT(*) FROM invalid_source_rows").fetchone()[0]
    relationship_rows = connection.execute("SELECT COUNT(*) FROM source_relationships").fetchone()[0]
    canonical_rows = connection.execute("SELECT COUNT(*) FROM canonical_geometries").fetchone()[0]
    render_rows = connection.execute("SELECT * FROM render_status ORDER BY floor_key").fetchall()
    succeeded = [json.loads(row["result_json"]) for row in render_rows if row["status"] == "succeeded"]
    failed = [dict(row) for row in render_rows if row["status"] != "succeeded"]
    class_counts, excluded_counts = Counter(), Counter()
    totals = Counter()
    alignment_count = alignment_ok = 0
    maximum_distance = 0.0
    invalid_labels = 0
    transform_errors = 0
    for result in succeeded:
        class_counts.update(result["counts"]["class_counts"])
        excluded_counts.update(result["counts"]["excluded_counts"])
        totals["room_instances"] += result["counts"]["room_instances"]
        totals["wall_labels"] += result["counts"]["class_counts"].get("separators:wall", 0)
        totals["door_labels"] += result["counts"]["door_labels"]
        totals["window_labels"] += result["counts"]["window_labels"]
        alignment = result["opening_wall_alignment"]
        alignment_count += alignment["count"]
        alignment_ok += alignment["aligned_within_0_05m"]
        maximum_distance = max(maximum_distance, alignment["maximum_distance_m"] or 0.0)
        errors = _validate_render(result, taxonomy)
        invalid_labels += sum("unknown values" in error for error in errors)
        transform_errors += sum("transform" in error for error in errors)

    split_rows = connection.execute(
        "SELECT split,COUNT(*) FROM building_splits GROUP BY split ORDER BY split"
    ).fetchall()
    split_floors = connection.execute(
        "SELECT s.split,COUNT(*) FROM floor_profiles p JOIN building_splits s USING(building_key) "
        "GROUP BY s.split ORDER BY s.split"
    ).fetchall()
    leakage = connection.execute(
        "SELECT building_key,COUNT(DISTINCT split) n FROM building_splits GROUP BY building_key HAVING n>1"
    ).fetchall()
    duplicates = connection.execute(
        "SELECT match_type,COUNT(*) FROM duplicate_pairs GROUP BY match_type ORDER BY match_type"
    ).fetchall()

    # Re-render a stable representative slice and compare content hashes.
    determinism = []
    for row in connection.execute(
        "SELECT r.floor_key,r.output_dir,r.result_json,s.split FROM render_status r "
        "JOIN floor_profiles p USING(floor_key) JOIN building_splits s USING(building_key) "
        "WHERE r.status='succeeded' ORDER BY r.floor_key LIMIT ?", (determinism_count,)
    ):
        original = json.loads(row["result_json"])
        floor = _floor_key_values(row["floor_key"])
        with tempfile.TemporaryDirectory(prefix="swiss-full-repeat-") as temp_dir:
            repeated = render_floor(
                _load_floor_frame(connection, floor), Path(temp_dir), taxonomy,
                pixels_per_metre=DEFAULT_PPM, padding_m=DEFAULT_PADDING_M,
                split=row["split"], source_csv_sha256=source_hash,
                compress_supervision=True, conversion_version=FULL_CONVERSION_VERSION,
            )
            determinism.append({"floor": list(floor), "identical": original["hashes"] == repeated["hashes"]})

    room_overlaps, room_overlap_examples = _room_overlap_count(connection)
    reconciliation_ok = source_rows == relationship_rows + invalid_rows
    complete = (
        _meta_get(connection, "ingest_complete", "0") == "1"
        and _meta_get(connection, "profiles_complete", "0") == "1"
        and not failed
        and len(succeeded) == connection.execute("SELECT COUNT(*) FROM floor_profiles").fetchone()[0]
    )
    qa_errors = []
    if not reconciliation_ok:
        qa_errors.append("source relationship reconciliation failed")
    if leakage:
        qa_errors.append("building split leakage")
    if invalid_labels or transform_errors:
        qa_errors.append("render label/transform validation failed")
    if alignment_count != alignment_ok:
        qa_errors.append("openings outside wall alignment tolerance")
    if not all(item["identical"] for item in determinism):
        qa_errors.append("deterministic rerender mismatch")
    if failed:
        qa_errors.append("one or more floors failed rendering")

    report = {
        "manifest_version": 1,
        "conversion_version": FULL_CONVERSION_VERSION,
        "created_at": _utc_now(),
        "source": {"dataset": "Swiss Dwellings", "version": SOURCE_VERSION, "doi": SOURCE_DOI,
                   "geometries_csv": str(source_csv), "sha256": source_hash},
        "complete": complete,
        "counts": {
            "buildings": _count_distinct(connection, "site_id || char(31) || building_id", "canonical_geometries"),
            "plans": _count_distinct(connection, "site_id || char(31) || building_id || char(31) || plan_id", "canonical_geometries"),
            "floors": connection.execute("SELECT COUNT(*) FROM floor_profiles").fetchone()[0],
            "units": int(connection.execute(
                "SELECT COUNT(DISTINCT c.site_id || char(31) || c.building_id || char(31) || s.unit_id) "
                "FROM source_relationships s JOIN canonical_geometries c USING(geometry_id)"
            ).fetchone()[0]),
            "source_geometries": source_rows,
            "valid_source_relationships": relationship_rows,
            "invalid_geometries": invalid_rows,
            "canonical_geometries": canonical_rows,
            "collapsed_relationships": relationship_rows - canonical_rows,
            **dict(totals),
        },
        "splits": {"buildings": dict(split_rows), "floors": dict(split_floors),
                   "leakage_count": len(leakage)},
        "duplicates": {**dict(duplicates), "policy": "duplicate building clusters remain in one split"},
        "classes": dict(sorted(class_counts.items())),
        "excluded_semantics": dict(sorted(excluded_counts.items())),
        "validation": {
            "invalid_label_count": invalid_labels,
            "transform_error_count": transform_errors,
            "source_reconciliation": reconciliation_ok,
            "opening_labels": alignment_count,
            "openings_aligned_within_0_05m": alignment_ok,
            "orphan_or_misaligned_openings": alignment_count - alignment_ok,
            "maximum_opening_wall_distance_m": maximum_distance,
            "room_overlap_pair_count": room_overlaps,
            "room_overlap_examples": room_overlap_examples,
            "failed_floors": [{"floor_key": row["floor_key"], "error": row["error"]} for row in failed],
            "deterministic_rerenders": determinism,
            "errors": qa_errors,
        },
        "rendering": {"pixels_per_metre": DEFAULT_PPM, "padding_m": DEFAULT_PADDING_M,
                      "maximum_dimension_px": MAX_DIMENSION_PX},
        "storage_bytes": directory_size(output_root),
        "training_ready": bool(complete and not qa_errors),
        "training_authorized": False,
    }
    manifest_dir = output_root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "full_conversion_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    weighting = {
        "applied_to_stored_labels": False,
        "recommendation": "derive inverse-frequency sampling caps from the final train split; cap common-class down-weighting, oversample rare positive floors, retain explicit negative floors, and sample each canonical shared geometry once",
        "evidence_class_counts": dict(sorted(class_counts.items())),
    }
    (manifest_dir / "recommended_weighting_policy.json").write_text(
        json.dumps(weighting, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def run_full_conversion(source_csv: str | Path, output_root: str | Path, taxonomy_path: str | Path,
                        *, repository_root: str | Path | None = None, chunk_rows: int = DEFAULT_CHUNK_ROWS,
                        stop_after_ingest_rows: int | None = None,
                        stop_after_profile_floors: int | None = None,
                        stop_after_render_floors: int | None = None,
                        finalize: bool = True) -> dict:
    source_csv = Path(source_csv).resolve()
    output_root = Path(output_root).resolve()
    _require_external_output(output_root, Path(repository_root) if repository_root else None)
    taxonomy = load_taxonomy(taxonomy_path)
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / "state" / "full_conversion.sqlite3"
    with _connect(state_path) as connection:
        initialize_state(connection)
        existing_source = _meta_get(connection, "source_csv")
        if existing_source and Path(existing_source).resolve() != source_csv:
            raise ValueError("state database belongs to a different source CSV")
        with connection:
            _meta_set(connection, "source_csv", source_csv)
            _meta_set(connection, "conversion_version", FULL_CONVERSION_VERSION)
        ingestion = ingest_source(connection, source_csv, chunk_rows=chunk_rows,
                                  stop_after_rows=stop_after_ingest_rows)
        result = {"ingestion": ingestion, "state_database": str(state_path)}
        if not ingestion["complete"]:
            return result
        source_hash = _meta_get(connection, "source_sha256")
        if source_hash is None:
            source_hash = _sha256_file(source_csv)
            with connection:
                _meta_set(connection, "source_sha256", source_hash)
        profiles = build_floor_profiles(connection, stop_after_floors=stop_after_profile_floors)
        result["profiles"] = profiles
        if not profiles["complete"]:
            return result
        if _meta_get(connection, "splits_complete", "0") != "1":
            result["splits"] = assign_full_splits(connection)
        else:
            result["splits"] = {"reused": True}
        rendering = render_full(connection, output_root, taxonomy, source_hash,
                                stop_after_floors=stop_after_render_floors)
        result["rendering"] = rendering
        if finalize and rendering["processed"] == rendering["total"]:
            result["qa"] = finalize_qa(connection, output_root, taxonomy, source_csv, source_hash)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-csv", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--taxonomy", type=Path, default=Path(__file__).with_name("swiss_dwellings_taxonomy_v1.json"))
    parser.add_argument("--chunk-rows", type=int, default=DEFAULT_CHUNK_ROWS)
    parser.add_argument("--stop-after-ingest-rows", type=int)
    parser.add_argument("--stop-after-profile-floors", type=int)
    parser.add_argument("--stop-after-render-floors", type=int)
    parser.add_argument("--no-finalize", action="store_true")
    args = parser.parse_args(argv)
    result = run_full_conversion(
        args.source_csv, args.output_root, args.taxonomy,
        repository_root=args.repository_root, chunk_rows=args.chunk_rows,
        stop_after_ingest_rows=args.stop_after_ingest_rows,
        stop_after_profile_floors=args.stop_after_profile_floors,
        stop_after_render_floors=args.stop_after_render_floors,
        finalize=not args.no_finalize,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
