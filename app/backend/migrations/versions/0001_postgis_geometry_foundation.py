"""PostGIS geometry foundation: first-class Detection/Measurement geometry.

Enables the PostGIS extension and creates the geometry-first tables (sheets,
conditions, model_versions, detections, measurements, correction_events) with
SRID-0 planar geometry columns and GiST spatial indexes.

This replaces storing detections as JSON ``Text`` blobs (guardrail #4) and
stands up the CorrectionEvent flywheel table (guardrail #5).

Revision ID: 0001_postgis_geometry
Revises:
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "0001_postgis_geometry"
down_revision = None
branch_labels = None
depends_on = None

SRID = 0  # local planar drawing space (PDF points / feet), not geographic


def upgrade() -> None:
    # 1. PostGIS extension (idempotent).
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # 2. Sheets — per-page calibration.
    op.create_table(
        "sheets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("drawing_id", sa.Integer, sa.ForeignKey("drawings.id", ondelete="CASCADE"), index=True),
        sa.Column("page_no", sa.Integer, server_default="0"),
        sa.Column("scale_ratio", sa.Float),
        sa.Column("scale_text", sa.String(50)),
        sa.Column("dpi", sa.Integer, server_default="300"),
        sa.Column("width_pt", sa.Float),
        sa.Column("height_pt", sa.Float),
        sa.Column("is_vector", sa.Boolean, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 3. Conditions — named takeoff items measurements roll up to.
    op.create_table(
        "conditions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("trade", sa.String(100)),
        sa.Column("type", sa.String(100)),
        sa.Column("unit", sa.String(20)),
        sa.Column("color", sa.String(20)),
        sa.Column("formula", sa.Text),
        sa.Column("waste_pct", sa.Float, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 4. Model versions — provenance + eval-gated promotion.
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("task", sa.String(60)),
        sa.Column("metrics", sa.JSON),
        sa.Column("weights_uri", sa.String(500)),
        sa.Column("promoted", sa.Boolean, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 5. Detections — real geometry, not JSON. spatial_index handled below.
    op.create_table(
        "detections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sheet_id", sa.Integer, sa.ForeignKey("sheets.id", ondelete="CASCADE"), index=True),
        sa.Column("detection_class", sa.String(80)),
        sa.Column("confidence", sa.Float, server_default="1.0"),
        sa.Column("source", sa.String(20), server_default="vector"),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_versions.id")),
        sa.Column("properties", sa.JSON),
        sa.Column("geom", Geometry(geometry_type="GEOMETRY", srid=SRID, spatial_index=False)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 6. Measurements — value + unit + the geometry it came from.
    op.create_table(
        "measurements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("detection_id", sa.Integer, sa.ForeignKey("detections.id", ondelete="CASCADE"), index=True),
        sa.Column("condition_id", sa.Integer, sa.ForeignKey("conditions.id", ondelete="SET NULL")),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("geom", Geometry(geometry_type="GEOMETRY", srid=SRID, spatial_index=False)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 7. Correction events — the training-data flywheel.
    op.create_table(
        "correction_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("detection_id", sa.Integer, sa.ForeignKey("detections.id", ondelete="CASCADE"), index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), index=True),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("before", sa.JSON),
        sa.Column("after", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 8. GiST spatial indexes for fast intersect/contains/diff queries.
    op.execute("CREATE INDEX ix_detections_geom ON detections USING gist (geom)")
    op.execute("CREATE INDEX ix_measurements_geom ON measurements USING gist (geom)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_measurements_geom")
    op.execute("DROP INDEX IF EXISTS ix_detections_geom")
    op.drop_table("correction_events")
    op.drop_table("measurements")
    op.drop_table("detections")
    op.drop_table("model_versions")
    op.drop_table("conditions")
    op.drop_table("sheets")
    # Leave the postgis extension installed; other features may rely on it.
