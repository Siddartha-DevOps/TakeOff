"""Schema smoke tests for the PostGIS first-class geometry model.

No live database needed — we assert the SQLAlchemy table definitions are shaped
the way the migration expects (geometry columns, local SRID, the flywheel
table). Skips cleanly if GeoAlchemy2 is not installed."""

import pytest

geo_models = pytest.importorskip("geo_models")

if not geo_models.HAS_GEOALCHEMY2:  # pragma: no cover
    pytest.skip("geoalchemy2 not installed", allow_module_level=True)


def test_all_geometry_tables_defined():
    tables = set(geo_models.GeoBase.metadata.tables)
    assert {
        "sheets",
        "conditions",
        "model_versions",
        "detections",
        "measurements",
        "correction_events",
    } <= tables


@pytest.mark.parametrize("model", [geo_models.Detection, geo_models.Measurement])
def test_geometry_columns_use_local_srid(model):
    geom = model.__table__.c.geom
    # GeoAlchemy2 exposes the configured SRID on the column type.
    assert geom.type.srid == geo_models.DRAWING_SRID


def test_detection_records_source_provenance():
    assert "source" in geo_models.Detection.__table__.c


def test_correction_event_is_the_flywheel():
    cols = geo_models.CorrectionEvent.__table__.c
    for required in ("action", "before", "after", "user_id", "detection_id"):
        assert required in cols
