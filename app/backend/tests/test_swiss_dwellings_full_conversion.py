"""Durability and determinism tests for the streaming Swiss converter."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ml.datasets.convert_swiss_dwellings_full import (
    _connect,
    assign_full_splits,
    build_floor_profiles,
    ingest_source,
    initialize_state,
    render_full,
)
from ml.datasets.convert_swiss_dwellings_pilot import load_taxonomy


COLUMNS = [
    "apartment_id", "site_id", "building_id", "plan_id", "floor_id", "unit_id", "area_id",
    "unit_usage", "entity_type", "entity_subtype", "geometry", "elevation", "height",
]
TAXONOMY = Path(__file__).parents[1] / "ml" / "datasets" / "swiss_dwellings_taxonomy_v1.json"


def _row(building: int, subtype: str, geometry: str, *, entity_type: str = "AREA", unit: int = 1):
    return {
        "apartment_id": f"apt-{building}-{unit}", "site_id": "site", "building_id": str(building),
        "plan_id": f"plan-{building}", "floor_id": "0", "unit_id": str(unit), "area_id": "area",
        "unit_usage": "RESIDENTIAL", "entity_type": entity_type, "entity_subtype": subtype,
        "geometry": geometry, "elevation": "0", "height": "2.6",
    }


def _rows():
    output = []
    for building, offset in ((1, 0), (2, 20), (3, 40)):
        room = f"POLYGON (({offset} 0, {offset+8} 0, {offset+8} 6, {offset} 6, {offset} 0))"
        wall = f"POLYGON (({offset} 0, {offset+8} 0, {offset+8} .2, {offset} .2, {offset} 0))"
        output.extend([
            _row(building, "BEDROOM", room),
            _row(building, "WALL", wall, entity_type="SEPARATOR"),
            _row(building, "DOOR", f"POLYGON (({offset+1} 0, {offset+2} 0, {offset+2} .2, {offset+1} .2, {offset+1} 0))", entity_type="OPENING"),
            _row(building, "WINDOW", f"POLYGON (({offset+4} 0, {offset+6} 0, {offset+6} .2, {offset+4} .2, {offset+4} 0))", entity_type="OPENING"),
            _row(building, "WALL", wall, entity_type="SEPARATOR", unit=2),
        ])
    return output


def _write(path: Path):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(_rows())


def test_ingest_resume_is_idempotent_and_preserves_every_relationship(tmp_path):
    source, state = tmp_path / "geometry.csv", tmp_path / "state.sqlite3"
    _write(source)
    with _connect(state) as connection:
        initialize_state(connection)
        first = ingest_source(connection, source, chunk_rows=3, stop_after_rows=7)
        assert first["rows_processed"] == 7
        assert not first["complete"]
        second = ingest_source(connection, source, chunk_rows=4)
        assert second["complete"]
        relationship_count = connection.execute("SELECT COUNT(*) FROM source_relationships").fetchone()[0]
        canonical_count = connection.execute("SELECT COUNT(*) FROM canonical_geometries").fetchone()[0]
        assert relationship_count == len(_rows())
        assert canonical_count == len(_rows()) - 3
        third = ingest_source(connection, source, chunk_rows=2)
        assert third["new_relationships"] == 0
        assert connection.execute("SELECT COUNT(*) FROM source_relationships").fetchone()[0] == relationship_count
        assert connection.execute("SELECT SUM(source_count) FROM canonical_geometries").fetchone()[0] == len(_rows())


def test_profiles_splits_and_outputs_resume_without_duplicates(tmp_path):
    source, state, output = tmp_path / "geometry.csv", tmp_path / "state.sqlite3", tmp_path / "outside"
    _write(source)
    taxonomy = load_taxonomy(TAXONOMY)
    with _connect(state) as connection:
        initialize_state(connection)
        assert ingest_source(connection, source, chunk_rows=2)["complete"]
        partial = build_floor_profiles(connection, stop_after_floors=1)
        assert partial["processed"] == 1 and not partial["complete"]
        complete = build_floor_profiles(connection)
        assert complete["processed"] == 3 and complete["complete"]
        first_splits = assign_full_splits(connection)
        assignments = list(connection.execute("SELECT building_key,split FROM building_splits ORDER BY building_key"))
        second_splits = assign_full_splits(connection)
        assert assignments == list(connection.execute("SELECT building_key,split FROM building_splits ORDER BY building_key"))
        assert first_splits["building_count"] == second_splits["building_count"] == 3

        first = render_full(connection, output, taxonomy, "fixture-hash", stop_after_floors=1)
        assert first["new"] == 1
        one_hash = connection.execute("SELECT result_json FROM render_status WHERE status='succeeded'").fetchone()[0]
        second = render_full(connection, output, taxonomy, "fixture-hash")
        assert second["succeeded"] == 3
        assert connection.execute("SELECT COUNT(*) FROM render_status").fetchone()[0] == 3
        assert connection.execute("SELECT result_json FROM render_status ORDER BY floor_key LIMIT 1").fetchone()[0] == one_hash
        third = render_full(connection, output, taxonomy, "fixture-hash")
        assert third["new"] == 0
        assert third["succeeded"] == 3

        result = json.loads(connection.execute(
            "SELECT result_json FROM render_status ORDER BY floor_key LIMIT 1"
        ).fetchone()[0])
        assert "supervision.json.gz" in result["hashes"]
        assert not list(output.rglob("supervision.json"))


def test_streaming_reader_never_requests_unbounded_dataframe(tmp_path, monkeypatch):
    source, state = tmp_path / "geometry.csv", tmp_path / "state.sqlite3"
    _write(source)
    import ml.datasets.convert_swiss_dwellings_full as converter

    real_read_csv = converter.pd.read_csv
    calls = []

    def guarded(*args, **kwargs):
        if kwargs.get("nrows") != 0:
            assert kwargs.get("chunksize") == 2
        calls.append(dict(kwargs))
        return real_read_csv(*args, **kwargs)

    monkeypatch.setattr(converter.pd, "read_csv", guarded)
    with _connect(state) as connection:
        initialize_state(connection)
        ingest_source(connection, source, chunk_rows=2)
    assert any(call.get("chunksize") == 2 for call in calls)


def test_profile_precision_does_not_mutate_canonical_metric_wkt(tmp_path):
    source, state = tmp_path / "geometry.csv", tmp_path / "state.sqlite3"
    _write(source)
    with _connect(state) as connection:
        initialize_state(connection)
        ingest_source(connection, source, chunk_rows=2)
        before = connection.execute(
            "SELECT geometry_id,geometry_wkt FROM canonical_geometries ORDER BY geometry_id"
        ).fetchall()
        assert build_floor_profiles(connection)["complete"]
        after = connection.execute(
            "SELECT geometry_id,geometry_wkt FROM canonical_geometries ORDER BY geometry_id"
        ).fetchall()
        assert before == after
        assert connection.execute("SELECT COUNT(*) FROM floor_profiles").fetchone()[0] == 3
