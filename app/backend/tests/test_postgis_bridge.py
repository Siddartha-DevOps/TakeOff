"""Tests for the shapely -> PostGIS bridge (first-class geometry)."""

import pytest

from geometry.postgis import (
    DRAWING_SRID,
    detection_payload,
    measurement_from_polygon,
    polygon_from_points,
    rooms_to_persistence,
    to_ewkt,
    to_geojson,
)

SCALE_RATIO = 96.0


@pytest.fixture
def square():
    # 72 x 72 pt square = 1 square paper inch = 64 sqft at ratio 96.
    return polygon_from_points([(0, 0), (72, 0), (72, 72), (0, 72)])


def test_ewkt_carries_local_srid(square):
    ewkt = to_ewkt(square)
    assert ewkt.startswith(f"SRID={DRAWING_SRID};POLYGON")


def test_geojson_is_polygon(square):
    gj = to_geojson(square)
    assert gj["type"] == "Polygon"
    assert gj["coordinates"]


def test_measurement_from_polygon_is_exact(square):
    m = measurement_from_polygon(square, SCALE_RATIO)
    assert m["area"]["unit"] == "sqft"
    assert m["area"]["value"] == pytest.approx(64.0, abs=0.1)
    # Perimeter 4 * 72 pt = 288 pt -> 32 ft at ratio 96.
    assert m["perimeter"]["value"] == pytest.approx(32.0, abs=0.1)


def test_detection_payload_records_provenance(square):
    payload = detection_payload(square, "Space", source="vector")
    assert payload["source"] == "vector"
    assert payload["detection_class"] == "Space"
    assert payload["geom_ewkt"].startswith("SRID=0;")
    assert payload["geojson"]["type"] == "Polygon"


def test_rooms_to_persistence_bundles_detection_and_measurements(square):
    measurement = {
        "rooms": [
            {"id": "vr_0", "label": "Space", "confidence": 1.0, "geometry": square},
        ]
    }
    records = rooms_to_persistence(measurement, SCALE_RATIO)
    assert len(records) == 1
    rec = records[0]
    assert rec["ref_id"] == "vr_0"
    assert rec["detection"]["source"] == "vector"
    assert rec["measurements"]["area"]["value"] == pytest.approx(64.0, abs=0.1)


def test_rooms_without_geometry_are_skipped():
    records = rooms_to_persistence({"rooms": [{"id": "x", "geometry": None}]}, SCALE_RATIO)
    assert records == []
